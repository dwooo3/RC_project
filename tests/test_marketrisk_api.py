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


def test_stress_var_uses_named_window(ctx):
    from api.marketrisk import overview
    base = overview(ctx, confidence=0.99, window=300)
    stressed = overview(ctx, confidence=0.99, window=300, stress="2022")
    assert stressed["stress"] == "2022"
    assert "2022" in stressed["stress_period"]
    # the 2022 shock period must not silently fall back to the plain window
    assert stressed["n_scenarios"] != base["n_scenarios"] or \
        stressed["var"] != base["var"]


def test_incremental_var_coherent(ctx):
    from api.marketrisk import incremental
    from api.pricing_workstation import find_product
    product = find_product("irs")
    params = {s.key: s.default
              for s in product.params_for(product.engines[0], [], [])}
    out = incremental(ctx, "irs", "irs", params, quantity=1.0,
                      confidence=0.99, window=300)
    assert out["var_base"] > 0
    assert out["var_with_trade"] == out["var_base"] + out["incremental_var"]
    # subadditivity of the historical quantile: standalone >= incremental
    assert out["standalone_var"] >= out["incremental_var"] - 1e-6
    assert out["diversification_benefit"] == out["standalone_var"] - out["incremental_var"]


def test_pnl_explain_shape(ctx):
    from api.marketrisk import pnl_explain
    out = pnl_explain(ctx)
    assert out["as_of"]
    assert out["effects"], "expected greek-effect components"
    assert out["total_pnl"] == out["total_pnl"]        # not NaN
    assert abs(out["explained"] + out["residual"] - out["total_pnl"]) < 1e-6


def test_market_position_mapping(ctx):
    from api.underlying import market_position
    inst, params, desc = market_position(ctx, "bonds", "SU26238RMFS4")
    assert inst == "bond"
    assert params["face"] == 1000.0
    assert 10 < params["T"] < 20                        # matures 2041
    assert 0 < params["coupon"] < 0.2
    assert "SU26238RMFS4" in desc

    from services.portfolio_service import PortfolioService
    from domain.portfolio import Position
    ps = PortfolioService()
    ps.add(Position(id="t_real_bond", instrument=inst, quantity=1000.0,
                    description=desc, params=params))
    ps.price_all()
    assert not ps.positions[0].errors


def test_backtest_coherent(ctx):
    from api.marketrisk import backtest
    bt = backtest(ctx, confidence=0.95, window=300, lookback=150)
    assert bt["n_obs"] == len(bt["rows"])
    assert bt["n_exceptions"] == sum(1 for r in bt["rows"] if r["breach"])
    assert bt["traffic_light"] in ("green", "amber", "red")
    for r in bt["rows"][:5]:
        assert r["var"] < 0, "VaR line is plotted as a loss level"
