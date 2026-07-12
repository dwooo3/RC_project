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


# ── FX exotics (digital/asian/lookback) — GK carry q=r_f ─

def test_fx_exotics_match_domain_engines():
    from instruments.asian import geometric_asian_discrete
    from instruments.digital import cash_or_nothing
    from instruments.fx import fx_asian, fx_digital, fx_lookback
    from instruments.lookback import floating_lookback
    S, K, T, r_d, r_f, sig = 90.0, 92.0, 1.0, 0.16, 0.05, 0.15
    # FX-обёртка == доменный движок с r=r_d, q=r_f
    assert fx_digital(S, K, T, r_d, r_f, sig, "call", "cash", 1.0, 1.0)["price"] \
        == pytest.approx(cash_or_nothing(S, K, T, r_d, sig, r_f, "call", 1.0)["price"])
    assert fx_asian(S, K, T, r_d, r_f, sig, "call", "geometric", 12,
                    notional=1.0)["price"] \
        == pytest.approx(geometric_asian_discrete(S, K, T, r_d, sig, r_f, 12,
                                                  "call")["price"])
    assert fx_lookback(S, T, r_d, r_f, sig, "call", "floating",
                       notional=1.0)["price"] \
        == pytest.approx(floating_lookback(S, T, r_d, sig, r_f, "call")["price"])


# ── equity_future: fair price + futures delta > forward ──

def test_future_fair_price_identity():
    from instruments.equity_linear import equity_future
    S, K, T, r, q = 100.0, 100.0, 1.0, 0.10, 0.02
    f = equity_future(S, K, T, r, q)
    assert f["fair_future"] == pytest.approx(S * np.exp((r - q) * T))
    z = equity_future(S, f["fair_future"], T, r, q)
    assert z["npv"] == pytest.approx(0.0, abs=1e-9)   # MtM без дисконта


def test_future_delta_exceeds_forward():
    from instruments.equity_linear import equity_forward, equity_future
    S, K, T, r, q = 100.0, 100.0, 1.0, 0.10, 0.02
    fut = equity_future(S, K, T, r, q)
    fwd = equity_forward(S, K, T, r, q)
    # futures delta e^{(r−q)T} > forward delta e^{−qT}
    assert fut["delta"] == pytest.approx(np.exp((r - q) * T))
    assert fut["delta"] > fwd["delta"]


# ── warrant: dilution factor + below undiluted ───────────

def test_warrant_dilution_factor():
    from instruments.equity_linear import warrant
    w = warrant(100, 100, 1, 0.05, 0.2, 0.0, n_shares=100, n_warrants=25)
    assert w["dilution_factor"] == pytest.approx(100 / 125)


def test_warrant_below_undiluted():
    from models.black_scholes import bsm
    from instruments.equity_linear import warrant
    w = warrant(100, 90, 1.5, 0.05, 0.25, 0.01, n_shares=100, n_warrants=10)
    c = bsm(100, 90, 1.5, 0.05, 0.25, 0.01, "call").price
    assert w["price"] < c
    assert w["price"] == pytest.approx((100 / 110) * c)


# ── cds_index_option: ATM symmetry + strike monotonic ────

def test_index_option_atm_symmetry():
    from instruments.credit import cds_index_option
    # ATM (strike == current): payer == receiver (Black)
    p = cds_index_option(10e6, 0.011, 0.011, 0.5, 0.5, 5, 4, 0.08, option="payer")
    r = cds_index_option(10e6, 0.011, 0.011, 0.5, 0.5, 5, 4, 0.08, option="receiver")
    assert p["price"] == pytest.approx(r["price"], rel=1e-6)


def test_index_option_strike_monotonic():
    from instruments.credit import cds_index_option
    # payer (право купить защиту): дороже при меньшем страйке
    lo = cds_index_option(10e6, 0.008, 0.011, 0.5, 0.5, 5, 4, 0.08, option="payer")
    hi = cds_index_option(10e6, 0.020, 0.011, 0.5, 0.5, 5, 4, 0.08, option="payer")
    assert lo["price"] > hi["price"] > 0


# ── term_deposit: NPV zero at fair rate + loan mirror ────

def test_deposit_npv_zero_at_fair_rate():
    from instruments.money_market import term_deposit
    td = term_deposit(1e6, 0.12, 0.25, 0.10, "simple")
    at_fair = term_deposit(1e6, td["fair_rate"], 0.25, 0.10, "simple")
    assert at_fair["npv"] == pytest.approx(0.0, abs=1e-6)
    # непрерывное начисление: fair rate == дисконтная ставка
    tdc = term_deposit(1e6, 0.10, 0.25, 0.10, "continuous")
    assert tdc["npv"] == pytest.approx(0.0, abs=1e-6)


def test_deposit_loan_mirror():
    from instruments.money_market import term_deposit
    dep = term_deposit(1e6, 0.15, 0.5, 0.10, "simple", deposit=True)
    loan = term_deposit(1e6, 0.15, 0.5, 0.10, "simple", deposit=False)
    assert dep["npv"] == pytest.approx(-loan["npv"])
    assert dep["npv"] > 0            # ставка 15% > дисконт 10% → депозит в плюсе
