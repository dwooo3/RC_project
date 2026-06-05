"""Sanity validation of all PricingService pricers — parities, bounds, monotonicity."""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")

from services.pricing_service import PricingService


@pytest.fixture
def s():
    return PricingService()


def V(res):
    return res["value"]


# ── Vanilla: put-call parity ─────────────────────────────
def test_vanilla_put_call_parity(s):
    a = dict(S=100, K=100, T=1, r=0.05, sigma=0.2, q=0.0)
    c = V(s.price_vanilla_option(**a, opt="call"))
    p = V(s.price_vanilla_option(**a, opt="put"))
    assert c - p == pytest.approx(100 * math.exp(-0.0) - 100 * math.exp(-0.05), abs=0.05)


# ── Barrier: in-out parity and KO < vanilla ──────────────
def test_barrier_in_out_parity(s):
    base = dict(S=100, K=100, H=90, T=1, r=0.05, sigma=0.2, q=0.0, opt="call")
    ko = V(s.price_barrier_option(**base, barrier_type="down-out"))
    ki = V(s.price_barrier_option(**base, barrier_type="down-in"))
    vanilla = V(s.price_vanilla_option(S=100, K=100, T=1, r=0.05, sigma=0.2, opt="call"))
    assert ko + ki == pytest.approx(vanilla, abs=0.05)
    assert ko < vanilla


# ── Asian geometric < vanilla ────────────────────────────
def test_asian_cheaper_than_vanilla(s):
    asian = V(s.price_asian_option(100, 100, 1, 0.05, 0.2, averaging="geometric"))
    vanilla = V(s.price_vanilla_option(100, 100, 1, 0.05, 0.2, opt="call"))
    assert 0 < asian < vanilla


# ── Digital cash bounded by discounted notional ──────────
def test_digital_cash_bounds(s):
    d = V(s.price_digital_option(100, 100, 1, 0.05, 0.2, style="cash", cash=1.0))
    assert 0 < d < math.exp(-0.05)


# ── Lookback >= vanilla ──────────────────────────────────
def test_lookback_ge_vanilla(s):
    lb = V(s.price_lookback_option(100, 1, 0.05, 0.2, opt="call", strike_type="floating"))
    vanilla = V(s.price_vanilla_option(100, 100, 1, 0.05, 0.2, opt="call"))
    assert lb >= vanilla - 1e-6


# ── Bond: monotone in coupon (up) and rate (down) ────────
def test_bond_monotonicity(s):
    def bond(coupon, r):
        return V(s.price_bond(1000, coupon, 10, 2, curve=s.market_data.flat_curve(r)))
    assert bond(0.08, 0.10) > bond(0.05, 0.10)      # higher coupon -> higher price
    assert bond(0.06, 0.08) > bond(0.06, 0.12)      # higher rate -> lower price


# ── FRN near par, monotone in spread ─────────────────────
def test_frn_near_par_and_spread_monotone(s):
    def frn(spread):
        return V(s.price_frn(1000, spread, 5, 2, curve=s.market_data.flat_curve(0.10)))
    assert 700 < frn(0.0) < 1300
    assert frn(0.02) > frn(0.0)


# ── Cap/Floor: non-negative, cap down in K, floor up in K ─
def test_cap_floor_monotonicity(s):
    def cap(K):
        return V(s.price_cap_floor(1_000_000, K, 3, 2, 0.20, "cap", curve=s.market_data.flat_curve(0.10)))
    def floor(K):
        return V(s.price_cap_floor(1_000_000, K, 3, 2, 0.20, "floor", curve=s.market_data.flat_curve(0.10)))
    assert cap(0.08) >= cap(0.12) >= 0
    assert floor(0.12) >= floor(0.08) >= 0


# ── Swaption: non-negative, increasing in vol ────────────
def test_swaption_increasing_in_vol(s):
    def sw(vol):
        return V(s.price_swaption(1_000_000, 0.10, 1, 5, 2, vol, "payer",
                                  curve=s.market_data.flat_curve(0.10)))
    assert sw(0.30) >= sw(0.15) >= 0


# ── FX forward covered interest parity ───────────────────
def test_fx_forward_parity(s):
    raw = s.price_fx_forward(90, 0.10, 0.04, 1.0)["raw"]
    fwd = raw.get("forward")
    assert fwd == pytest.approx(90 * math.exp((0.10 - 0.04) * 1.0), rel=1e-3)


# ── FX option: increasing in vol ─────────────────────────
def test_fx_option_increasing_in_vol(s):
    lo = V(s.price_fx_option(90, 92, 1, 0.10, 0.04, 0.10, opt="call"))
    hi = V(s.price_fx_option(90, 92, 1, 0.10, 0.04, 0.25, opt="call"))
    assert hi > lo > 0


# ── Spread option: non-negative, down in K ───────────────
def test_spread_option_monotone_in_strike(s):
    def sp(K):
        return V(s.price_spread_option(100, 100, K, 1, 0.05, 0.2, 0.25, 0.4))
    assert sp(2) >= sp(8) >= 0


# ── IRS: fair-rate NPV near zero ─────────────────────────
def test_irs_fair_rate_zero_npv(s):
    curve = s.market_data.flat_curve(0.10)
    res = s.price_irs(1_000_000, 0.10, 5, 4, curve=curve)
    # at a flat 10% curve, a 10% fixed swap is close to fair
    assert abs(res["value"]) < 0.05 * 1_000_000


# ── CDS: positive fair spread ────────────────────────────
def test_cds_fair_spread_positive(s):
    res = s.price_cds(1_000_000, 0.01, 5, 4, hazard=0.02, r=0.05)
    assert res["raw"]["fair_spread"] > 0


# ── Autocall: finite, positive, bounded ──────────────────
def test_autocall_finite_bounded(s):
    res = s.price_autocall_phoenix(100, 0.05, 0.0, 0.20, 3.0, [1, 2, 3], 1.0, 0.70, 0.65, 0.10,
                                   n_sims=5000, steps=50)
    v = res["value"]
    assert v is not None and math.isfinite(v) and 0 < v < 300
