"""Sprint 1 service boundary tests."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import numpy as np
import pytest

from instruments.fixed_income import fixed_bond, irs
from instruments.fx import fx_forward, fx_option
from instruments.vanilla import european
from risk.stress import stress_option
from risk.var import historical_var, parametric_var
from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService
from services.risk_service import RiskService


def _assert_contract(result, model_id):
    assert result["model_id"] == model_id
    assert "model_status" in result
    assert isinstance(result["warnings"], list)
    assert isinstance(result["errors"], list)
    assert "market_data_snapshot_id" in result
    assert result["calculation_id"]
    assert result["inputs_hash"]
    assert result["audit_record"].model_id == model_id


def test_pricing_service_matches_direct_vanilla_option():
    direct = european(100, 100, 1, 0.05, 0.20, 0.0, "call", "bsm")
    result = PricingService().price_vanilla_option(100, 100, 1, 0.05, 0.20)

    _assert_contract(result, "black_scholes")
    assert result["value"] == pytest.approx(direct["price"])
    assert result["raw"]["delta"] == pytest.approx(direct["delta"])


def test_pricing_service_matches_direct_bond_with_snapshot_curve():
    market_data = MarketDataService()
    snapshot = market_data.demo_snapshot(date(2026, 6, 3))
    curve = snapshot.curves["flat_rub"]
    direct = fixed_bond(100, 0.05, 2.0, 2, curve)

    result = PricingService(market_data=market_data).price_bond(
        100, 0.05, 2.0, 2, snapshot=snapshot, curve_id="flat_rub"
    )

    _assert_contract(result, "fixed_bond")
    assert result["value"] == pytest.approx(direct["price"])
    assert result["market_data_snapshot_id"] == snapshot.snapshot_id
    assert any("DEMO" in warning or "Demo" in warning for warning in result["warnings"])


def test_pricing_service_matches_direct_irs_with_snapshot_curve():
    market_data = MarketDataService()
    snapshot = market_data.demo_snapshot(date(2026, 6, 3))
    curve = snapshot.curves["flat_rub"]
    direct = irs(1_000_000, 0.09, 3.0, 2, curve, True)

    result = PricingService(market_data=market_data).price_irs(
        1_000_000, 0.09, 3.0, 2, pay_fixed=True, snapshot=snapshot, curve_id="flat_rub"
    )

    _assert_contract(result, "irs")
    assert result["value"] == pytest.approx(direct["npv"])


def test_pricing_service_matches_direct_fx_forward_and_option():
    forward = fx_forward(90.0, 0.10, 0.04, 0.5)
    forward_result = PricingService().price_fx_forward(90.0, 0.10, 0.04, 0.5)

    _assert_contract(forward_result, "fx_forward")
    assert forward_result["value"] == pytest.approx(forward["forward"])

    option = fx_option(90.0, 92.0, 0.5, 0.10, 0.04, 0.20)
    option_result = PricingService().price_fx_option(90.0, 92.0, 0.5, 0.10, 0.04, 0.20)

    _assert_contract(option_result, "garman_kohlhagen")
    assert option_result["value"] == pytest.approx(option["price"])


def test_risk_service_matches_direct_historical_and_parametric_var():
    rng = np.random.default_rng(123)
    returns = rng.normal(0.0, 0.01, 500)

    direct_hist = historical_var(returns, 1_000_000, 0.95, 1)
    service_hist = RiskService().historical_var(returns, 1_000_000, 0.95, 1)
    _assert_contract(service_hist, "var_historical")
    assert service_hist["value"] == pytest.approx(direct_hist["VaR"])

    direct_param = parametric_var(returns, 1_000_000, 0.95, 1)
    service_param = RiskService().parametric_var(returns, 1_000_000, 0.95, 1)
    _assert_contract(service_param, "var_parametric")
    assert service_param["value"] == pytest.approx(direct_param["VaR"])


def test_risk_service_expected_shortfall_uses_cvar_value():
    rng = np.random.default_rng(456)
    returns = rng.normal(0.0, 0.01, 500)
    direct = historical_var(returns, 1_000_000, 0.95, 1)

    result = RiskService().expected_shortfall(returns, 1_000_000, 0.95, 1)

    _assert_contract(result, "var_historical")
    assert result["value"] == pytest.approx(direct["CVaR"])


def test_risk_service_stress_wrapper_matches_direct_worst_pnl():
    direct = stress_option(100, 100, 1, 0.05, 0.20)
    result = RiskService().stress_option(100, 100, 1, 0.05, 0.20)

    _assert_contract(result, "var_parametric")
    assert result["value"] == pytest.approx(min(row["pnl"] for row in direct))


def test_governance_surfaces_prototype_warning():
    warnings = GovernanceService().warnings_for_model("short_rate")

    assert any("not production allowed" in warning for warning in warnings)
    assert any("Prototype" in warning for warning in warnings)


def test_unknown_service_model_returns_structured_error_and_warning():
    result = PricingService().price_vanilla_option(100, 100, 1, 0.05, 0.20, model="unknown")

    _assert_contract(result, "unknown")
    assert result["errors"]
    assert any("not production allowed" in warning for warning in result["warnings"])


def test_pricing_service_workflow_status_returns_governed_readiness_result():
    result = PricingService().workflow_status("variance_swap", reason="wrapper pending")

    _assert_contract(result, "variance_swap")
    assert result["value"] is None
    assert result["model_version"]
    assert result["model_status"] == "Validated"  # variance_swap: batch-1 2026-07
    assert result["raw"]["workflow_available"] is False
    assert "wrapper pending" in result["warnings"]
