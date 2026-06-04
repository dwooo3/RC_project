"""Portfolio service architecture and compatibility tests."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from domain import (
    Portfolio,
    PortfolioRiskResult,
    PortfolioValuationResult,
    Position,
    PositionType,
    RiskFactor,
    RiskFactorExposure,
    RiskFactorGroup,
    RiskFactorHierarchy,
)
from risk.portfolio import Portfolio as LegacyPortfolio
from services.portfolio_service import PortfolioService


def test_domain_portfolio_owns_positions():
    portfolio = Portfolio("Test", base_currency="USD")
    pos = Position(
        id="eq1",
        instrument="equity",
        description="Equity spot",
        quantity=10,
        params={"S": 100.0},
    )

    portfolio.add(pos)

    assert len(portfolio) == 1
    assert portfolio.positions[0].id == "eq1"
    assert portfolio.portfolio_id == "test"
    assert portfolio.base_currency == "USD"
    assert portfolio.by_type(PositionType.EQUITY) == [pos]


def test_position_type_is_inferred_for_legacy_positions():
    option = Position(
        id="opt1",
        instrument="call",
        description="Call option",
        quantity=1,
        params={},
    )

    assert option.type == PositionType.OPTION


def test_risk_factor_exposure_supports_bucket_backward_compatibility():
    exposure = RiskFactorExposure(
        factor_name="spot",
        factor_type="equity",
        currency="RUB",
        bump_size=1.0,
        sensitivity=10.0,
        unit="Delta",
    )

    assert exposure.bucket == "Unclassified"


def test_risk_factor_domain_hierarchy_contracts():
    factor = RiskFactor(
        factor_id="rates.yield_curve",
        name="Yield Curve",
        bucket=RiskFactorHierarchy.RATES.value,
        factor_type="yield_curve",
        currency="RUB",
        unit="DV01",
        bump_size=0.0001,
    )
    exposure = RiskFactorExposure(
        factor_id=factor.factor_id,
        factor_name=factor.name,
        factor_type=factor.factor_type,
        currency=factor.currency,
        bump_size=factor.bump_size,
        sensitivity=125.0,
        unit=factor.unit,
        bucket=factor.bucket,
        position_id="bond1",
    )
    group = RiskFactorGroup.from_exposures("Rates", [exposure])

    assert factor.bucket == "Rates"
    assert group.totals_by_unit["DV01"] == pytest.approx(125.0)
    assert group.exposures[0].position_id == "bond1"


def test_portfolio_service_buckets_equity_and_vol_exposures():
    service = PortfolioService("Test")
    service.add(
        Position(
            id="call1",
            instrument="call",
            description="ATM call",
            quantity=2,
            params={"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "sigma": 0.20, "opt": "call"},
        )
    )

    agg = service.aggregate()

    assert agg["market_value"] > 0
    assert agg["exposure_buckets"]["Equity"]["Delta"] != 0
    assert agg["exposure_buckets"]["Volatility"]["Vega"] > 0
    assert agg["delta"] != 0
    assert agg["vega"] > 0
    assert agg["risk_factors"]["equity.spot"]["sensitivity"] == pytest.approx(agg["delta"])
    assert agg["risk_factors"]["vol.implied"]["sensitivity"] == pytest.approx(agg["vega"])


def test_portfolio_service_returns_valuation_result():
    service = PortfolioService("Valuation")
    service.add(
        Position(
            id="eq1",
            instrument="equity",
            description="Equity spot",
            quantity=4,
            params={"S": 25.0},
        )
    )

    result = service.value()

    assert isinstance(result, PortfolioValuationResult)
    assert result.portfolio_id == "valuation"
    assert result.total_market_value == pytest.approx(100.0)
    assert result.positions[0].model_id == "equity_spot"


def test_portfolio_service_returns_risk_result():
    service = PortfolioService("Risk")
    service.add(
        Position(
            id="eq1",
            instrument="equity",
            description="Equity spot",
            quantity=4,
            params={"S": 25.0},
        )
    )

    result = service.risk()

    assert isinstance(result, PortfolioRiskResult)
    assert result.portfolio_id == "risk"
    assert result.market_value == pytest.approx(100.0)
    assert result.exposure_buckets["Equity"]["Delta"] == pytest.approx(4.0)
    assert result.risk_factor_groups
    assert any(group.bucket == "Equity" for group in result.risk_factor_groups)
    assert result.scenario_pnl["bucket_pnl"]["Equity"] == pytest.approx(0.0)


def test_portfolio_service_scenario_pnl_returns_bucket_components():
    service = PortfolioService("Test")
    service.add(
        Position(
            id="eq1",
            instrument="equity",
            description="Equity spot",
            quantity=10,
            params={"S": 100.0},
        )
    )

    result = service.scenario_pnl(dS=2.0)

    assert result["pnl"] == pytest.approx(20.0)
    assert result["bucket_pnl"]["Equity"] == pytest.approx(20.0)
    assert result["factor_pnl"]["equity.spot"] == pytest.approx(20.0)
    assert result["position_pnl"]["eq1"] == pytest.approx(20.0)


def test_portfolio_service_contribution_analysis_by_factor():
    service = PortfolioService("Contribution")
    service.add(
        Position(
            id="eq1",
            instrument="equity",
            description="Equity spot",
            quantity=10,
            params={"S": 100.0},
        )
    )
    service.add(
        Position(
            id="fx1",
            instrument="fx_forward",
            description="USD/RUB forward",
            quantity=5,
            params={"S": 90.0, "r_d": 0.10, "r_f": 0.04, "T": 0.5, "ccy_pair": "USD/RUB"},
        )
    )

    service.value()
    contributions = service.factor_contributions(dS=2.0)
    scenario = service.scenario_pnl(dS=2.0)

    assert contributions["equity.spot"] == pytest.approx(20.0)
    assert contributions["fx.usd/rub"] == pytest.approx(10.0)
    assert scenario["bucket_pnl"]["Equity"] == pytest.approx(20.0)
    assert scenario["bucket_pnl"]["FX"] == pytest.approx(10.0)
    assert scenario["pnl"] == pytest.approx(30.0)


def test_legacy_risk_portfolio_import_path_still_works():
    portfolio = LegacyPortfolio("Legacy")
    portfolio.add(
        Position(
            id="eq1",
            instrument="equity",
            description="Equity spot",
            quantity=3,
            params={"S": 50.0},
        )
    )

    agg = portfolio.aggregate()

    assert agg["market_value"] == pytest.approx(150.0)
    assert agg["delta"] == pytest.approx(3.0)
