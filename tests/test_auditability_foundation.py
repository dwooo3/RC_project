"""Auditability and reproducibility foundation tests."""

import os
import sys
from datetime import date

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain import AuditRecord, CalculationRecord, Position
from services.audit_service import AuditService
from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService
from services.pricing_service import PricingService
from services.risk_service import RiskService


def test_audit_service_hashes_inputs_deterministically():
    audit = AuditService()
    left = {"b": [2, 3], "a": {"x": 1}, "as_of": date(2026, 6, 4)}
    right = {"as_of": date(2026, 6, 4), "a": {"x": 1}, "b": [2, 3]}

    assert audit.hash_inputs(left) == audit.hash_inputs(right)
    assert audit.hash_inputs(left) != audit.hash_inputs({**left, "b": [2, 4]})


def test_pricing_result_contains_calculation_record_and_reproducibility_metadata():
    market_data = MarketDataService()
    snapshot = market_data.demo_snapshot(date(2026, 6, 4))
    pricing = PricingService(market_data=market_data)

    result = pricing.price_bond(100.0, 0.06, 3.0, 2, snapshot=snapshot, curve_id="flat_rub")

    assert isinstance(result["audit_record"], CalculationRecord)
    assert isinstance(result["audit_record"], AuditRecord)
    assert result["calculation_id"] == result["audit_record"].record_id
    assert result["inputs_hash"] == result["audit_record"].inputs_hash
    assert result["audit_record"].calculation_type == "bond_pricing"
    assert result["audit_record"].model_id == "fixed_bond"
    assert result["audit_record"].model_version == result["model_version"]
    assert result["audit_record"].snapshot_id == snapshot.snapshot_id
    assert pricing.audit.audit_trail()[-1]["inputs_hash"] == result["inputs_hash"]


def test_governance_audit_trail_can_read_supplied_audit_service_records():
    audit = AuditService()
    pricing = PricingService(audit=audit)
    result = pricing.price_vanilla_option(100, 100, 1, 0.05, 0.20)

    trail = GovernanceService(audit=audit).audit_trail()

    assert trail[-1]["calculation_id"] == result["calculation_id"]
    assert trail[-1]["model_id"] == "black_scholes"
    assert trail[-1]["model_version"] == result["model_version"]
    assert trail[-1]["inputs_hash"] == result["inputs_hash"]


def test_risk_result_contains_calculation_record_and_es_uses_es_calculation_type():
    returns = np.array([0.01, -0.02, 0.015, -0.03, 0.005])
    risk = RiskService()

    var_result = risk.historical_var(returns, 1_000_000, confidence=0.95)
    es_result = risk.expected_shortfall(returns, 1_000_000, confidence=0.95)

    assert var_result["audit_record"].calculation_type == "historical_var"
    assert var_result["inputs_hash"]
    assert es_result["audit_record"].calculation_type == "expected_shortfall"
    assert es_result["audit_record"].model_id == "var_historical"
    assert es_result["calculation_id"] != var_result["calculation_id"]
    assert len(risk.audit.records) >= 3


def test_portfolio_service_records_valuation_scenario_and_pnl_explain():
    service = PortfolioService("Audit Portfolio")
    service.add(Position("eq1", "equity", "Equity spot", 10, {"S": 100.0}))

    valuation = service.value()
    scenario = service.run_scenario(
        {
            "scenario_id": "audit-shock",
            "name": "Audit Shock",
            "scenario_type": "Custom",
            "shocks": [{"shock_type": "equity_shock", "value": -2.0, "unit": "absolute", "bucket": "Equity"}],
        }
    )
    pnl_explain = service.explain_pnl(scenario=scenario.scenario)

    assert valuation.calculation_record.calculation_type == "portfolio_valuation"
    assert valuation.calculation_id == valuation.calculation_record.record_id
    assert scenario.calculation_record.calculation_type == "portfolio_scenario"
    assert scenario.inputs_hash == scenario.calculation_record.inputs_hash
    assert pnl_explain.calculation_record.calculation_type == "pnl_explain"
    assert pnl_explain.as_dict()["audit_record"]["calculation_type"] == "pnl_explain"
    assert any(record.calculation_type == "portfolio_valuation" for record in service.audit.records)
    assert any(record.calculation_type == "portfolio_scenario" for record in service.audit.records)
    assert any(record.calculation_type == "pnl_explain" for record in service.audit.records)
