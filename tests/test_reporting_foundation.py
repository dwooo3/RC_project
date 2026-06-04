"""Reporting foundation tests."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain import Position, ReportDocument, ReportSection, ReportTable
from services.governance_service import GovernanceService
from services.portfolio_service import PortfolioService
from services.reporting_service import ReportingService
from services.risk_service import RiskService


def _portfolio_service() -> PortfolioService:
    service = PortfolioService("Report Portfolio")
    service.add(Position("eq1", "equity", "Equity spot", 10, {"S": 100.0}))
    service.add(Position("fx1", "fx_forward", "USD/RUB forward", 5, {"S": 90.0, "r_d": 0.10, "r_f": 0.04, "T": 0.5, "ccy_pair": "USD/RUB"}))
    return service


def _assert_pdf_ready(report: ReportDocument, report_type: str):
    assert isinstance(report, ReportDocument)
    assert report.report_type == report_type
    assert report.pdf_ready is True
    assert report.metadata["format"] == "pdf_ready_structure"
    assert report.metadata["renderer"] == "not_implemented"
    assert report.sections
    payload = report.as_dict()
    assert payload["pdf_ready"] is True
    assert payload["sections"]


def test_reporting_domain_structures_are_pdf_ready_dicts():
    report = ReportDocument(
        report_type="test",
        title="Test Report",
        sections=[ReportSection("Section", tables=[ReportTable("Table", ["A"], [[1]])])],
    )

    payload = report.as_dict()

    assert payload["report_type"] == "test"
    assert payload["sections"][0]["tables"][0]["columns"] == ["A"]
    assert payload["sections"][0]["tables"][0]["rows"] == [[1]]


def test_portfolio_report_uses_portfolio_service_outputs():
    reporting = ReportingService(portfolio=_portfolio_service())

    report = reporting.portfolio_report()

    _assert_pdf_ready(report, "portfolio")
    assert "PortfolioService" in report.source_services
    assert report.title == "Portfolio Report"
    assert report.metadata["portfolio_id"] == "report-portfolio"
    assert any(section.title == "Positions" for section in report.sections)
    assert any(table.title == "Positions" for section in report.sections for table in section.tables)


def test_risk_report_uses_portfolio_and_risk_service_context():
    reporting = ReportingService(portfolio=_portfolio_service(), risk=RiskService())

    report = reporting.risk_report()

    _assert_pdf_ready(report, "risk")
    assert report.source_services == ["PortfolioService", "RiskService"]
    assert any(section.title == "Exposure Buckets" for section in report.sections)
    assert any(table.title == "Factor Contributions" for section in report.sections for table in section.tables)


def test_var_report_uses_risk_service_methods_and_audit_metadata():
    returns = np.array([0.01, -0.02, 0.015, -0.03, 0.005, 0.012, -0.011])
    reporting = ReportingService(risk=RiskService())

    report = reporting.var_report(returns, 1_000_000, confidence=0.95, horizon=1)

    _assert_pdf_ready(report, "var")
    assert "RiskService" in report.source_services
    assert report.metadata["confidence"] == 0.95
    var_table = next(table for section in report.sections for table in section.tables if table.title == "VaR Methods")
    assert {"historical_var", "parametric_var", "monte_carlo_var", "expected_shortfall"} <= {row[0] for row in var_table.rows}
    assert all(row[5] for row in var_table.rows)
    assert all(row[6] for row in var_table.rows)


def test_scenario_report_contains_scenario_and_pnl_explain_sections():
    reporting = ReportingService(portfolio=_portfolio_service())

    report = reporting.scenario_report(
        {
            "scenario_id": "risk-off",
            "name": "Risk Off",
            "scenario_type": "Hypothetical",
            "shocks": [
                {"shock_type": "equity_shock", "value": -2.0, "unit": "absolute", "bucket": "Equity"},
                {"shock_type": "fx_shock", "value": -1.0, "unit": "absolute", "bucket": "FX"},
            ],
        }
    )

    _assert_pdf_ready(report, "scenario")
    assert report.metadata["scenario_id"] == "risk-off"
    assert any(section.title == "Scenario P&L" for section in report.sections)
    assert any(section.title == "PnL Explain" for section in report.sections)


def test_model_governance_report_uses_governance_service_metadata():
    reporting = ReportingService(governance=GovernanceService())

    report = reporting.model_governance_report()

    _assert_pdf_ready(report, "model_governance")
    assert report.title == "Model Governance Report"
    registry_table = next(table for section in report.sections for table in section.tables if table.title == "Model Registry")
    assert "Quant Review" in registry_table.columns
    assert any(row[0] == "fixed_bond" for row in registry_table.rows)
    quant_table = next(table for section in report.sections for table in section.tables if table.title == "Quant Review Status")
    assert {"Fixed", "False Positive", "Partially Validated", "Open"} <= {row[0] for row in quant_table.rows}
