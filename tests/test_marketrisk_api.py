"""Market Risk workstation gate: shifts generation from the real stored
history + full-reprice HypPL + VaR methods + backtest coherence.

Skipped when the live market store is absent (fresh clone) — the module is a
bridge layer over stored history, not a pure-math engine.
"""

from __future__ import annotations

import os

import pytest

_DB = os.path.join(os.path.dirname(__file__), "..", "data", "market_data.sqlite")

pytestmark = pytest.mark.skipif(not os.path.exists(_DB),
                                reason="live market store not present")


@pytest.fixture(scope="module")
def ctx():
    from api.context import CONTEXT
    try:
        if CONTEXT.market_db is None:
            pytest.skip("market db unavailable")
    except Exception as exc:                            # noqa: BLE001
        pytest.skip(f"context unavailable: {exc}")
    return CONTEXT


def test_factor_shifts_shapes(ctx):
    from api.marketrisk import factor_shifts
    s = factor_shifts(ctx, window=300)
    n = len(s["dates"])
    assert n >= 250
    assert len(s["eq"]) == len(s["dr"]) == len(s["dvol"]) == n
    # sanity: daily log-returns and rate diffs are small decimals
    assert abs(s["eq"]).max() < 0.5
    assert abs(s["dr"]).max() < 0.1


def test_overview_metrics_coherent(ctx):
    from api.marketrisk import overview
    ov = overview(ctx, confidence=0.99, window=300, horizon=1)
    assert ov["n_scenarios"] >= 250
    assert ov["var"] > 0
    assert ov["es"] >= ov["var"], "ES must not be below VaR"
    assert len(ov["methods"]) >= 4
    assert len(ov["histogram"]) > 10
    assert len(ov["hyppl"]) == ov["n_scenarios"]
    # sqrt-time scaling: 10d VaR must exceed 1d VaR
    ov10 = overview(ctx, confidence=0.99, window=300, horizon=10)
    assert ov10["var"] > ov["var"]


def test_backtest_coherent(ctx):
    from api.marketrisk import backtest
    bt = backtest(ctx, confidence=0.95, window=300, lookback=150)
    assert bt["n_obs"] == len(bt["rows"])
    assert bt["n_exceptions"] == sum(1 for r in bt["rows"] if r["breach"])
    assert bt["traffic_light"] in ("green", "amber", "red")
    for r in bt["rows"][:5]:
        assert r["var"] < 0, "VaR line is plotted as a loss level"
