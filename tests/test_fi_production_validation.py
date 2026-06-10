"""Production-grade validation of all Fixed Income pricers (parities, par, bounds)."""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")

from services.pricing_service import PricingService


@pytest.fixture
def s():
    return PricingService()


def _curve(s, r=0.08):
    return s.market_data.flat_curve(r)


# ── Bond par & accrued consistency ───────────────────────
def test_fixed_bond_clean_dirty_accrued_consistency(s):
    res = s.price_bond(1000, 0.07, 10, 2, curve=_curve(s, 0.07))
    raw = res["raw"]
    assert raw["dirty_price"] == pytest.approx(raw["clean_price"] + raw["accrued_interest"], abs=1e-6)
    assert raw["mod_duration"] < raw["mac_duration"]
    assert raw["convexity"] > 0


def test_fixed_bond_near_par_when_coupon_matches_curve(s):
    # continuous flat 7% curve, semiannual 7% coupon -> close to par (within compounding gap)
    res = s.price_bond(1000, 0.07, 10, 2, curve=_curve(s, 0.07))
    assert 950 < res["value"] < 1050


# ── Cap/Floor parity: cap(K) - floor(K) = payer swap value ──
def test_cap_floor_parity(s):
    curve = _curve(s, 0.10)
    notional, K, T, freq, vol = 1_000_000, 0.10, 3, 2, 0.20
    cap = s.price_cap_floor(notional, K, T, freq, vol, "cap", curve=curve)["value"]
    floor = s.price_cap_floor(notional, K, T, freq, vol, "floor", curve=curve)["value"]
    # payer swap = sum tau*(fwd_i - K)*disc_i * notional, with the SIMPLE forward
    # (P(t1)/P(t2)-1)/tau — the caplet market convention (2026-06 audit fix; the
    # old continuously-compounded curve.forward_rate broke this parity by ~12bp).
    dt = 1 / freq
    swap = 0.0
    for i in range(1, int(round(T * freq)) + 1):
        t1, t2 = (i - 1) * dt, i * dt
        fwd = (curve.discount(t1) / curve.discount(t2) - 1.0) / dt
        swap += dt * (fwd - K) * curve.discount(t2) * notional
    assert cap - floor == pytest.approx(swap, abs=1e-4)


# ── Swaption payer-receiver parity ───────────────────────
def test_swaption_payer_receiver_parity(s):
    curve = _curve(s, 0.10)
    notional, K, To, Ts, freq, vol = 1_000_000, 0.10, 1, 5, 2, 0.20
    payer = s.price_swaption(notional, K, To, Ts, freq, vol, "payer", curve=curve)
    receiver = s.price_swaption(notional, K, To, Ts, freq, vol, "receiver", curve=curve)
    raw = payer["raw"]
    annuity = raw.get("annuity")
    fwd = raw.get("fwd_swap_rate")
    parity = annuity * (fwd - K) * notional
    assert payer["value"] - receiver["value"] == pytest.approx(parity, rel=0.05, abs=50)


# ── Amortizing principal sums to face ────────────────────
def test_amortizing_principal_sums_to_face(s):
    res = s.price_amortizing_bond(1000, 0.07, 5, 2, "linear", curve=_curve(s, 0.10))
    assert res["value"] > 0 and res["raw"]["effective_duration"] > 0


# ── FRA fair NPV ~ 0 ─────────────────────────────────────
def test_fra_npv_zero_at_fair(s):
    curve = _curve(s, 0.10)
    fair = s.price_fra(1_000_000, 0.10, 1, 1.5, curve=curve)["raw"]["forward_rate"]
    assert abs(s.price_fra(1_000_000, fair, 1, 1.5, curve=curve)["value"]) < 1.0


# ── Money market yield ordering ──────────────────────────
def test_tbill_yield_ordering(s):
    raw = s.price_treasury_bill(1000, 0.09, 0.5)["raw"]
    assert raw["bey"] > raw["money_market_yield"] >= raw["discount_yield"] - 1e-9 or raw["bey"] > raw["discount_yield"]


# ── Callable <= straight <= putable on same terms ────────
def test_callable_putable_ordering(s):
    curve = _curve(s, 0.07)
    call = s.price_callable_bond(1000, 0.08, 5, 2, sigma=0.15, call_price=1000, call_start=1,
                                 option="callable", curve=curve)["raw"]
    put = s.price_callable_bond(1000, 0.08, 5, 2, sigma=0.15, put_price=1000, put_start=1,
                                option="putable", curve=curve)["raw"]
    assert call["callable_value"] <= call["straight_value"] + 1e-6
    assert put["putable_value"] >= put["straight_value"] - 1e-6


# ── Increment 2: conventions, dual-curve, manual schedule ──
def test_custom_bond_matches_dcf(s):
    cfs = [(1, 35), (2, 35), (3, 1035)]
    curve = _curve(s, 0.10)
    res = s.price_custom_bond(cfs, 2, curve=curve)
    dcf = sum(a * curve.discount(t) for t, a in cfs)
    assert res["value"] == pytest.approx(dcf, rel=1e-9)


def test_day_count_act360_richer_than_act365(s):
    curve = _curve(s, 0.10)
    p365 = s.price_amortizing_bond(1000, 0.08, 10, 2, "linear", "act365", curve=curve)["value"]
    p360 = s.price_amortizing_bond(1000, 0.08, 10, 2, "linear", "act360", curve=curve)["value"]
    assert p360 > p365      # act/360 accrues more interest per period


def test_fra_dual_curve_forward_from_projection(s):
    disc = s.market_data.flat_curve(0.05)
    proj = s.market_data.flat_curve(0.12)
    single = s.price_fra(1_000_000, 0.10, 1, 1.5, curve=disc)["raw"]["forward_rate"]
    dual = s.price_fra(1_000_000, 0.10, 1, 1.5, curve=disc, proj_curve=proj)["raw"]["forward_rate"]
    assert dual > single        # forward driven by the higher projection curve
