"""MR-4: captured equity futures must participate in historical spot shocks."""

from __future__ import annotations

import math

import pytest

from domain.portfolio import Position
from services.portfolio_service import PortfolioService


def _equity_future_book() -> PortfolioService:
    book = PortfolioService()
    book.add(Position(
        id="eq_future",
        instrument="future",
        quantity=10.0,
        description="Equity future",
        params={"F": 100.0, "multiplier": 2.0, "secid": "MXU6"},
    ))
    return book


def test_equity_future_f_moves_under_simple_spot_shock():
    book = _equity_future_book()

    result = book.full_reprice_pnl(dS=0.10)

    # 100 * 10 contracts * 2 multiplier * 10% level move.
    assert result["errors"] == []
    assert result["base_value"] == pytest.approx(2_000.0)
    assert result["shocked_value"] == pytest.approx(2_200.0)
    assert result["pnl"] == pytest.approx(200.0)
    assert result["pnl"] != 0.0


def test_equity_future_f_moves_under_historical_log_return():
    book = _equity_future_book()

    result = book.full_reprice_pnl(
        dS_by_name={"MXU6": math.log(1.10)},
        spot_shock_convention="log",
    )

    assert result["errors"] == []
    assert result["pnl"] == pytest.approx(200.0)
    assert result["pnl"] != 0.0
