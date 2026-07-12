"""Этап 5: расширение продуктовой линейки — валидационные тождества для
equity forward/swap/dividend swap, asset swap (par-par), CDS index, FX barrier.

Имена тестов соответствуют полю "tests" в models/registry.py — это
validation evidence для governance-статусов новых прайсеров.
"""

from __future__ import annotations

import numpy as np
import pytest

from instruments.credit import asset_swap_parpar, cds, cds_index, isda_flat_hazard
from instruments.equity_linear import dividend_swap, equity_forward, equity_swap


# ── equity_forward: cost-of-carry + zero at fair ─────────

def test_cost_of_carry_identity():
    S, r, q, T = 100.0, 0.10, 0.02, 1.5
    f = equity_forward(S, 100, T, r, q)
    assert f["fair_forward"] == pytest.approx(S * np.exp((r - q) * T))
    # delta длинного форварда = e^{−qT}
    assert f["delta"] == pytest.approx(np.exp(-q * T))


def test_npv_zero_at_fair_forward():
    S, r, q, T = 120.0, 0.08, 0.03, 2.0
    fair = equity_forward(S, 0, T, r, q)["fair_forward"]
    z = equity_forward(S, fair, T, r, q)
    assert z["npv"] == pytest.approx(0.0, abs=1e-9)
    # короткая позиция зеркальна
    short = equity_forward(S, 90, T, r, q, position="short")
    long = equity_forward(S, 90, T, r, q, position="long")
    assert short["npv"] == pytest.approx(-long["npv"])


# ── dividend_swap: expected div + zero at fair strike ────

def test_expected_div_identity():
    S, r, q, T = 100.0, 0.05, 0.04, 3.0
    d = dividend_swap(S, T, r, q)
    assert d["expected_dividends_pv"] == pytest.approx(S * (1 - np.exp(-q * T)))


def test_npv_zero_at_fair_strike():
    S, r, q, T = 100.0, 0.05, 0.04, 3.0
    d = dividend_swap(S, T, r, q)                 # div_strike=None → fair
    assert d["npv"] == pytest.approx(0.0, abs=1e-9)
    # цена растёт со страйком линейно вниз для получателя дивидендов
    hi = dividend_swap(S, T, r, q, div_strike=d["fair_strike"] * 1.5)
    assert hi["npv"] < 0


# ── equity_swap: leg parity + npv = −spread leg ──────────

def test_leg_parity_identity():
    s = equity_swap(100, 1e6, 5, 0.12, 0.03, spread=0.0, freq=4)
    assert s["equity_leg_pv"] == pytest.approx(s["floating_leg_pv"])
    # без спреда своп стоит ноль (паритет ног)
    assert s["npv"] == pytest.approx(0.0, abs=1e-6)


def test_npv_equals_minus_spread_leg():
    s = equity_swap(100, 1e6, 5, 0.12, 0.03, spread=0.005, freq=4)
    # получатель equity платит спред → NPV = −(spread leg)
    assert s["npv"] == pytest.approx(-s["spread_leg_pv"])
    payer = equity_swap(100, 1e6, 5, 0.12, 0.03, spread=0.005, freq=4,
                        receive_equity=False)
    assert payer["npv"] == pytest.approx(-s["npv"])


# ── asset_swap: zero at riskfree value + sign ────────────

def test_asw_zero_at_riskfree_value():
    face, coupon, T, freq, r = 100.0, 0.08, 5.0, 2, 0.10
    v_star = asset_swap_parpar(face, coupon, T, freq, 0, r)["riskfree_value"]
    at_par = asset_swap_parpar(face, coupon, T, freq, v_star, r)
    assert at_par["asset_swap_spread"] == pytest.approx(0.0, abs=1e-9)


def test_spread_sign():
    # бумага дешевле risk-free стоимости → положительный ASW spread
    face, coupon, T, freq, r = 100.0, 0.10, 5.0, 2, 0.10
    v_star = asset_swap_parpar(face, coupon, T, freq, 0, r)["riskfree_value"]
    cheap = asset_swap_parpar(face, coupon, T, freq, v_star - 5, r)
    rich = asset_swap_parpar(face, coupon, T, freq, v_star + 5, r)
    assert cheap["asset_swap_spread_bp"] > 0 > rich["asset_swap_spread_bp"]


def test_asw_spread_is_scale_invariant_rate():
    """asset_swap_spread — истинная десятичная ставка (не s·face): та же
    экономика на разном номинале даёт тот же спред и bp = spread·1e4."""
    a1 = asset_swap_parpar(100.0, 0.08, 5.0, 2, 95.0, 0.10)
    a2 = asset_swap_parpar(1e6, 0.08, 5.0, 2, 95.0e4, 0.10)   # ×1e4 масштаб
    assert a1["asset_swap_spread"] == pytest.approx(a2["asset_swap_spread"])
    assert a1["asset_swap_spread_bp"] == pytest.approx(
        a1["asset_swap_spread"] * 10000)
    # порядок величины: бумага у номинала с купоном ≈ ставке → десятки-сотни bp
    assert abs(a1["asset_swap_spread"]) < 0.5      # не 95% (было бы s·face)


# ── cds_index: upfront zero at coupon + hazard roundtrip ─

def test_upfront_zero_at_coupon():
    # индекс-спред == купон → upfront ≈ 0
    ci = cds_index(10e6, 0.01, 0.01, 5, 4, 0.08)
    assert ci["upfront"] == pytest.approx(0.0, abs=1.0)
    # buy vs sell protection зеркальны
    buy = cds_index(10e6, 0.015, 0.01, 5, 4, 0.08, buy_protection=True)
    sell = cds_index(10e6, 0.015, 0.01, 5, 4, 0.08, buy_protection=False)
    assert buy["upfront"] == pytest.approx(-sell["upfront"])


def test_isda_flat_hazard_roundtrip():
    # плоский hazard, откалиброванный к спреду, воспроизводит fair spread индекса
    spread, T, freq, r = 0.011, 5.0, 4, 0.08
    h = isda_flat_hazard(spread, T, freq, r, 0.4)
    ci = cds_index(10e6, spread, 0.01, T, freq, r)
    assert ci["fair_spread"] == pytest.approx(spread, rel=1e-3)
    assert ci["hazard"] == pytest.approx(h, rel=1e-9)


# ── fx_barrier: GK carry consistency (q = r_f) ───────────

def test_fx_barrier_matches_gk_barrier():
    from instruments.barrier import single_barrier
    from instruments.fx import fx_barrier
    S, K, H, T, r_d, r_f, sig = 90.0, 92.0, 85.0, 1.0, 0.16, 0.05, 0.15
    fb = fx_barrier(S, K, H, T, r_d, r_f, sig, "call", "down-out", 0.0, 1.0)
    eq = single_barrier(S, K, H, T, r_d, sig, r_f, "call", "down-out", 0.0)
    assert fb["price"] == pytest.approx(eq["price"], rel=1e-12)
    # in + out = vanilla-эквивалент барьера (rebate=0)
    ki = fx_barrier(S, K, H, T, r_d, r_f, sig, "call", "down-in", 0.0, 1.0)
    ko = fx_barrier(S, K, H, T, r_d, r_f, sig, "call", "down-out", 0.0, 1.0)
    assert ki["price"] + ko["price"] > 0
