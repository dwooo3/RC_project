"""Этап 2 плана по отчёту валидации: M1 overlapping-горизонты,
M2 maturity-bucketed rate factor, M3 per-name/per-pair факторы,
M4 матричный MC, M5 EVT-диагностика."""

from __future__ import annotations

import os

import numpy as np
import pytest

from domain.portfolio import Position
from services.portfolio_service import PortfolioService


# ── M1: overlapping-горизонты ────────────────────────────


def test_overlapping_horizon_pnl_windows():
    from risk.historical_var import overlapping_horizon_pnl
    pnl = np.arange(100, dtype=float)
    out, method = overlapping_horizon_pnl(pnl, 10)
    assert method == "overlapping"
    assert len(out) == 91
    assert out[0] == pytest.approx(sum(range(10)))     # первое окно = 0..9


def test_overlapping_falls_back_to_sqrt_when_short():
    from risk.historical_var import overlapping_horizon_pnl
    pnl = np.ones(30)
    out, method = overlapping_horizon_pnl(pnl, 10)     # 21 окно < 50
    assert method == "sqrt_time"
    assert out[0] == pytest.approx(np.sqrt(10))


def test_hs_var_reports_horizon_method():
    from risk.historical_var import hs_var
    rng = np.random.default_rng(2)
    pnl = rng.normal(0, 1000, size=500)
    res = hs_var(pnl, 0.99, horizon=10)
    assert res["horizon_method"] == "overlapping"
    assert res["n_obs"] == 491
    res1 = hs_var(pnl, 0.99, horizon=1)
    assert res1["horizon_method"] == "none"


# ── M2: bucketed rate factor == parallel при равных сдвигах ──


@pytest.fixture()
def demo_book():
    ps = PortfolioService()
    ps.add(Position(id="b", instrument="bond", quantity=1_000_000,
                    description="5Y bond",
                    params={"face": 100.0, "coupon": 0.075, "T": 5.0,
                            "freq": 2, "r": 0.08}))
    ps.add(Position(id="irs", instrument="irs", quantity=1.0,
                    description="pay fixed 2Y",
                    params={"notional": 10_000_000.0, "fixed_rate": 0.09,
                            "T": 2.0, "freq": 4, "r": 0.08, "pay_fixed": True}))
    return ps


def test_equal_tenor_shifts_equal_parallel(demo_book):
    """dr_curve с одинаковым сдвигом на всех тенорах == скалярный dr точно."""
    parallel = demo_book.full_reprice_pnl(dr=0.005)
    bucketed = demo_book.full_reprice_pnl(
        dr_curve=[(t, 0.005) for t in (0.25, 1.0, 2.0, 5.0, 10.0)])
    assert bucketed["pnl"] == pytest.approx(parallel["pnl"], rel=1e-12)


def test_bucketed_shift_hits_position_maturity(demo_book):
    """Сдвиг только 2Y-тенора бьёт по 2Y-свопу, но не по 5Y-бонду."""
    only_2y = demo_book.full_reprice_pnl(
        dr_curve=[(0.25, 0.0), (1.0, 0.0), (2.0, 0.01), (5.0, 0.0), (10.0, 0.0)])
    only_5y = demo_book.full_reprice_pnl(
        dr_curve=[(0.25, 0.0), (1.0, 0.0), (2.0, 0.0), (5.0, 0.01), (10.0, 0.0)])
    # 2Y-шок: своп реагирует (pay fixed выигрывает от роста), бонд почти нет
    assert only_2y["pnl"] > 0
    # 5Y-шок: бонд теряет заметно больше, чем при 2Y-шоке
    assert only_5y["pnl"] < only_2y["pnl"]


# ── M3: per-name / per-pair ──────────────────────────────


def test_per_name_equity_shock():
    ps = PortfolioService()
    ps.add(Position(id="a", instrument="equity", quantity=100,
                    description="A", params={"S": 200.0, "secid": "AAA"}))
    ps.add(Position(id="b", instrument="equity", quantity=100,
                    description="B", params={"S": 300.0}))
    res = ps.full_reprice_pnl(dS=0.0, dS_by_name={"AAA": 0.10})
    assert res["pnl"] == pytest.approx(200.0 * 100 * 0.10, rel=1e-9)
    # позиция без secid получает общий dS
    res2 = ps.full_reprice_pnl(dS=0.01, dS_by_name={"AAA": 0.0})
    assert res2["pnl"] == pytest.approx(300.0 * 100 * 0.01, rel=1e-9)


def test_per_pair_fx_shock():
    ps = PortfolioService()
    ps.add(Position(id="usd", instrument="fx_forward", quantity=1_000_000,
                    description="USD fwd", currency="RUB", ccy_pair="USD/RUB",
                    params={"S": 90.0, "K": 91.0, "r_d": 0.10, "r_f": 0.045,
                            "T": 0.25, "ccy_pair": "USD/RUB"}))
    up = ps.full_reprice_pnl(dfx=0.0, dfx_by_pair={"USD/RUB": 0.02})
    base = ps.full_reprice_pnl(dfx=0.02)
    assert up["pnl"] == pytest.approx(base["pnl"], rel=1e-9)
    other = ps.full_reprice_pnl(dfx=0.0, dfx_by_pair={"EUR/RUB": 0.02})
    assert abs(other["pnl"]) < 1e-9, "чужая пара не должна двигать USD-позицию"


# ── M5: EVT-диагностика ──────────────────────────────────


def test_evt_diagnostics_flags_thin_tail():
    from risk.var import evt_var
    rng = np.random.default_rng(9)
    res = evt_var(rng.normal(0, 0.01, 260), 1.0, 0.99)
    assert "xi_by_threshold" in res and "warnings" in res
    assert any("превышений" in w for w in res["warnings"]), (
        "26 превышений < 30 — предупреждение обязано появиться")


def test_evt_diagnostics_clean_on_rich_tail():
    from risk.var import evt_var
    rng = np.random.default_rng(5)
    res = evt_var(rng.standard_t(4, 5000) * 0.01, 1.0, 0.99)
    assert res["n_exceedances"] >= 30
    assert res["xi_spread"] < 0.3


# ── живая БД: M1/M2/M4 в контуре Market Risk ─────────────

_DB = os.path.join(os.path.dirname(__file__), "..", "data", "market_data.sqlite")
live = pytest.mark.skipif(not os.path.exists(_DB),
                          reason="live market store not present")


@live
def test_overview_overlapping_horizon():
    from api.context import CONTEXT
    from api import marketrisk
    marketrisk.invalidate_cache()
    ov = marketrisk.overview(CONTEXT, 0.99, 300, horizon=10)
    assert ov["horizon_method"] == "overlapping"
    assert ov["n_scenarios"] < 300                     # окна короче ряда
    ov1 = marketrisk.overview(CONTEXT, 0.99, 300, horizon=1)
    assert ov["var"] > ov1["var"]


@live
def test_factor_shifts_multi_tenor():
    from api.context import CONTEXT
    from api.marketrisk import _KBD_TENORS, factor_shifts
    s = factor_shifts(CONTEXT, 300)
    assert set(s["dr_tenors"]) == set(_KBD_TENORS)
    lens = {len(v) for v in s["dr_tenors"].values()}
    assert lens == {len(s["dates"])}
    # короткий конец КБД в окне КС-цикла не тише длинного
    assert np.std(s["dr_tenors"][0.25]) > 0


@live
def test_mc_matrix_var_coherent():
    from api.context import CONTEXT
    from api.marketrisk import mc_var_matrix
    mc = mc_var_matrix(CONTEXT, 0.99, 300, n_sims=200, seed=1)
    assert mc["var"] > 0
    assert mc["es"] >= mc["var"]
    assert len(mc["factors"]) == 8                     # eq + 5 rates + vol + fx
    assert abs(mc["corr_eq_rates5y"]) <= 1.0
