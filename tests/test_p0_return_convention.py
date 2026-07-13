"""MR-2: historical log-returns and explicit simple stress shocks must not mix."""

from __future__ import annotations

import math

import pytest

from domain.portfolio import Portfolio
from domain.portfolio import Position
from services.portfolio_service import PortfolioService
from services.risk_service import RiskService


def _equity_book() -> PortfolioService:
    ps = PortfolioService()
    ps.add(Position(
        id="eq",
        instrument="equity",
        quantity=10.0,
        description="Linear equity",
        params={"S": 100.0, "secid": "EQ"},
    ))
    return ps


def _fx_book() -> PortfolioService:
    ps = PortfolioService()
    ps.add(Position(
        id="fx",
        instrument="fx_forward",
        quantity=1_000.0,
        description="USD/RUB forward",
        ccy_pair="USD/RUB",
        params={
            "S": 90.0,
            "K": 90.0,
            "T": 0.25,
            "r_d": 0.10,
            "r_f": 0.05,
            "ccy_pair": "USD/RUB",
        },
    ))
    return ps


@pytest.mark.parametrize("book_factory", [_equity_book, _fx_book])
def test_log_return_matches_equivalent_simple_shock(book_factory):
    """ln(1.10) must reproduce an exact +10% level move for equity and FX."""
    ps = book_factory()

    simple = ps.full_reprice_pnl(dS=0.10, dfx=0.10)
    log = ps.full_reprice_pnl(
        dS=math.log(1.10),
        dfx=math.log(1.10),
        spot_shock_convention="log",
    )

    assert log["pnl"] == pytest.approx(simple["pnl"], rel=1e-12, abs=1e-12)
    assert log["shocks"]["dS"] == pytest.approx(0.10)
    assert log["shocks"]["dfx"] == pytest.approx(0.10)


def test_log_return_conversion_covers_granular_maps():
    """Per-name and per-pair histories use the same convention as fallbacks."""
    eq = _equity_book()
    fx = _fx_book()

    eq_simple = eq.full_reprice_pnl(dS_by_name={"EQ": 0.20})
    eq_log = eq.full_reprice_pnl(
        dS_by_name={"EQ": math.log(1.20)},
        spot_shock_convention="log",
    )
    fx_simple = fx.full_reprice_pnl(dfx_by_pair={"USD/RUB": -0.15})
    fx_log = fx.full_reprice_pnl(
        dfx_by_pair={"USD/RUB": math.log(0.85)},
        spot_shock_convention="log",
    )

    assert eq_log["pnl"] == pytest.approx(eq_simple["pnl"], rel=1e-12)
    assert fx_log["pnl"] == pytest.approx(fx_simple["pnl"], rel=1e-12)


def test_simple_is_default_and_invalid_convention_is_rejected():
    """Existing desk stress values stay simple unless the caller opts into log."""
    ps = _equity_book()

    default = ps.full_reprice_pnl(dS=0.10)
    explicit = ps.full_reprice_pnl(dS=0.10, spot_shock_convention="simple")

    assert default["pnl"] == pytest.approx(100.0)
    assert explicit["pnl"] == pytest.approx(default["pnl"])
    with pytest.raises(ValueError, match="spot_shock_convention"):
        ps.full_reprice_pnl(dS=0.10, spot_shock_convention="percentage")


def test_risk_service_declares_and_applies_historical_return_convention():
    ps = PortfolioService(Portfolio(name="return-convention"))
    ps.add(Position(
        id="eq",
        instrument="equity",
        quantity=10.0,
        description="Linear equity",
        params={"S": 100.0},
    ))
    risk = RiskService(market_data=ps.market_data, audit=ps.audit)
    zeros = [0.0] * 30

    simple = risk.full_reprice_var(
        ps, [0.10] * 30, zeros, spot_return_convention="simple")
    log = risk.full_reprice_var(
        ps, [math.log(1.10)] * 30, zeros,
        spot_return_convention="log")

    assert simple["errors"] == []
    assert log["errors"] == []
    assert log["value"] == pytest.approx(simple["value"], abs=1e-12)
    assert log["raw"]["pnl_mean"] == pytest.approx(
        simple["raw"]["pnl_mean"], rel=1e-12)
    assert log["raw"]["spot_return_convention"] == "log"
