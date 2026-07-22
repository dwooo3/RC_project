"""MR-3/MR-7/MR-9 directed Market Risk correctness regressions."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from api.marketrisk import (
    _reprice_series,
    aggregate_factor_shifts,
    overview,
)


def _shifts(eq, dates=None):
    eq = np.asarray(eq, dtype=float)
    dates = dates or [f"2026-01-{i + 1:02d}" for i in range(len(eq))]
    zeros = np.zeros(len(eq))
    return {
        "dates": dates,
        "eq": eq,
        "dr": zeros.copy(),
        "dvol": zeros.copy(),
        "fx": zeros.copy(),
        "dr_tenors": {5.0: zeros.copy()},
        "eq_names": {"EQ": eq.copy()},
        "fx_pairs": {},
        "factors": ["equity"],
        "has_fx": False,
    }


def test_horizon_aggregates_factors_and_uses_window_end_date():
    shifts = _shifts([1.0, 2.0, 3.0, 4.0],
                     ["d1", "d2", "d3", "d4"])

    aggregated, method = aggregate_factor_shifts(
        shifts, horizon=2, min_windows=1)

    assert method == "factor_aggregation_full_reprice"
    assert aggregated["dates"] == ["d2", "d3", "d4"]
    assert aggregated["eq"].tolist() == pytest.approx([3.0, 5.0, 7.0])
    assert aggregated["eq_names"]["EQ"].tolist() == pytest.approx(
        [3.0, 5.0, 7.0])
    paths = aggregated["spot_return_paths"]
    assert paths["dates"] == [["d1", "d2"], ["d2", "d3"], ["d3", "d4"]]
    assert paths["fallback_log_returns"] == [[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]]
    assert paths["log_returns_by_factor"]["EQ"] == paths[
        "fallback_log_returns"]


def test_horizon_reprices_once_instead_of_summing_daily_nonlinear_pnl():
    class NonlinearBook:
        @staticmethod
        def full_reprice_pnl(**kwargs):
            # A deliberately nonlinear value function in the cumulative log
            # return. Two +10% days must be evaluated as one ln(1.21) shock.
            shock = float(kwargs["dS"])
            return {"pnl": shock**2, "errors": []}

    daily = _shifts([math.log(1.10), math.log(1.10)])
    daily_pnl, _ = _reprice_series(NonlinearBook(), daily)
    aggregated, _ = aggregate_factor_shifts(daily, 2, min_windows=1)
    horizon_pnl, _ = _reprice_series(NonlinearBook(), aggregated)

    assert horizon_pnl[0] == pytest.approx(math.log(1.21) ** 2)
    assert horizon_pnl[0] != pytest.approx(float(daily_pnl.sum()))


def test_short_history_fallback_is_explicit_and_keeps_daily_dates():
    shifts = _shifts(np.zeros(10))
    result, method = aggregate_factor_shifts(shifts, 5, min_windows=50)

    assert method == "sqrt_time"
    assert result is shifts
    assert len(result["dates"]) == 10


def test_invalid_horizon_and_unknown_stress_are_rejected():
    with pytest.raises(ValueError, match="positive integer"):
        aggregate_factor_shifts(_shifts([0.0]), 0)

    class ContextNotUsed:
        pass

    with pytest.raises(ValueError, match="unknown stress window"):
        overview(ContextNotUsed(), stress="not-a-window")


def test_empty_book_uses_empty_metadata_instead_of_full_portfolio(monkeypatch):
    from api import marketrisk

    class Book:
        def __init__(self, positions, value):
            self.positions = positions
            self._value = value

        def value(self):
            return SimpleNamespace(total_market_value=self._value)

    empty = Book([], 0.0)
    full = Book([object(), object()], 1_000_000.0)
    ctx = SimpleNamespace(
        portfolio=full,
        filtered_portfolio=lambda **_: empty,
    )
    pnl = np.linspace(-10.0, 10.0, 100)

    monkeypatch.setattr(marketrisk, "hyppl", lambda *args, **kwargs: {
        "dates": [f"d{i}" for i in range(len(pnl))],
        "pnl": pnl,
        "factors": ["equity"],
        "reprice_errors": [],
        "horizon_method": "none",
    })

    result = marketrisk.overview(ctx, book="missing-book")

    assert result["positions"] == 0
    assert result["portfolio_value"] == 0.0
    assert result["book"] == "missing-book"
