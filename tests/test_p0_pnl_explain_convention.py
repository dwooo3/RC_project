"""Directed regressions for historical P&L Explain spot conventions."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from api import marketrisk
from domain.portfolio import Position
from services.portfolio_service import PortfolioService


class _AppDB:
    @staticmethod
    def load_actual_pnl(_dt):
        return None


def _run_explain(monkeypatch, ps, *, eq, fx, eq_names=None, fx_pairs=None):
    monkeypatch.setattr(marketrisk, "factor_shifts", lambda *args, **kwargs: {
        "dates": ["2026-07-10"],
        "eq": np.array([eq]),
        "dr": np.array([0.0]),
        "dvol": np.array([0.0]),
        "fx": np.array([fx]),
        "eq_names": {k: np.array([v]) for k, v in (eq_names or {}).items()},
        "fx_pairs": {k: np.array([v]) for k, v in (fx_pairs or {}).items()},
    })
    ctx = SimpleNamespace(portfolio=ps, app_db=_AppDB())
    return marketrisk.pnl_explain(ctx, theta_days=0.0)


def _effect(result, key):
    return next(row["value"] for row in result["effects"] if row["key"] == key)


def test_equity_log_return_becomes_absolute_delta_move(monkeypatch):
    ps = PortfolioService()
    ps.add(Position(id="eq", instrument="equity", quantity=10.0,
                    description="Linear equity", params={"S": 100.0}))

    result = _run_explain(
        monkeypatch, ps, eq=math.log(1.10), fx=0.0)

    assert result["moves"]["equity"] == pytest.approx(0.10)
    assert _effect(result, "delta_pnl") == pytest.approx(100.0)
    assert result["total_pnl"] == pytest.approx(100.0)
    assert result["residual"] == pytest.approx(0.0, abs=1e-10)


def test_fx_attribution_uses_fx_move_not_equity_move(monkeypatch):
    ps = PortfolioService()
    ps.add(Position(
        id="fx", instrument="fx_forward", quantity=1_000.0,
        description="USD/RUB forward", ccy_pair="USD/RUB",
        params={"S": 90.0, "K": 90.0, "T": 0.25,
                "r_d": 0.0, "r_f": 0.0, "ccy_pair": "USD/RUB"}))

    result = _run_explain(
        monkeypatch, ps, eq=math.log(1.05), fx=math.log(1.20))

    assert result["moves"]["equity"] == pytest.approx(0.05)
    assert result["moves"]["fx"] == pytest.approx(0.20)
    assert _effect(result, "fx_pnl") == pytest.approx(18_000.0)
    assert result["total_pnl"] == pytest.approx(18_000.0)
    assert result["residual"] == pytest.approx(0.0, abs=1e-8)


def test_per_name_moves_use_each_positions_own_spot(monkeypatch):
    ps = PortfolioService()
    ps.add(Position(id="a", instrument="equity", quantity=1.0,
                    description="A", params={"S": 100.0, "secid": "A"}))
    ps.add(Position(id="b", instrument="equity", quantity=1.0,
                    description="B", params={"S": 200.0, "secid": "B"}))

    result = _run_explain(
        monkeypatch, ps, eq=math.log(1.02), fx=0.0,
        eq_names={"A": math.log(1.10), "B": math.log(0.95)})
    by_position = {row["position"]: row["pnl"]
                   for row in result["by_position"]}

    assert by_position["a"] == pytest.approx(10.0)
    assert by_position["b"] == pytest.approx(-10.0)
    assert result["total_pnl"] == pytest.approx(0.0, abs=1e-10)


def test_legacy_absolute_dS_remains_backward_compatible():
    ps = PortfolioService()
    ps.add(Position(id="eq", instrument="equity", quantity=10.0,
                    description="Linear equity", params={"S": 100.0}))

    result = ps.explain_pnl(total_pnl=100.0, dS=10.0)

    assert result.delta_pnl == pytest.approx(100.0)
    assert result.residual == pytest.approx(0.0)
