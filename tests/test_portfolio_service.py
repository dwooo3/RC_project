"""Portfolio service architecture and compatibility tests."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from domain import Portfolio, Position, RiskFactorExposure
from risk.portfolio import Portfolio as LegacyPortfolio
from services.portfolio_service import PortfolioService


def test_domain_portfolio_owns_positions():
    portfolio = Portfolio("Test")
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
