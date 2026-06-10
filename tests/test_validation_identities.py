"""
Permanent validation gate distilled from the June 2026 independent pricing audit
(validation_audit_2026_06.py). Every check here is a model-independent identity,
a published benchmark, or a cheap MC cross-check; together they pin the exact
defects the audit found (barrier up-branches, lookback transcription, variance
swap forward factor, cap/floor forward convention, basis swap degeneracy) so
they cannot regress silently.
"""
import numpy as np
import pytest

from models.black_scholes import bsm, black76, garman_kohlhagen, bachelier
from curves.yield_curve import YieldCurve


# ── Vanilla closed forms ─────────────────────────────────

def test_bsm_hull_benchmark():
    assert bsm(42, 40, 0.5, 0.10, 0.2).price == pytest.approx(4.7594, abs=1e-3)
    assert bsm(42, 40, 0.5, 0.10, 0.2, opt="put").price == pytest.approx(0.8086, abs=1e-3)


def test_put_call_parities():
    S, K, T, r, q, sig = 100, 95, 1.25, 0.07, 0.03, 0.35
    c = bsm(S, K, T, r, sig, q).price
    p = bsm(S, K, T, r, sig, q, "put").price
    assert c - p == pytest.approx(S*np.exp(-q*T) - K*np.exp(-r*T), abs=1e-10)
    F = 105.0
    assert (black76(F, K, T, r, sig).price - black76(F, K, T, r, sig, "put").price
            == pytest.approx(np.exp(-r*T)*(F-K), abs=1e-10))
    cgk = garman_kohlhagen(S, K, T, 0.16, 0.04, sig).price
    pgk = garman_kohlhagen(S, K, T, 0.16, 0.04, sig, "put").price
    assert cgk - pgk == pytest.approx(S*np.exp(-0.04*T) - K*np.exp(-0.16*T), abs=1e-10)
    assert bachelier(100, 100, 1.0, 0.05, 10.0).price == pytest.approx(
        np.exp(-0.05)*10.0*np.sqrt(1/(2*np.pi)), abs=1e-9)


# ── Digitals ─────────────────────────────────────────────

def test_digital_identities():
    from instruments.digital import asset_or_nothing, cash_or_nothing
    S, K, T, r, q, sig = 100, 95, 1.25, 0.07, 0.03, 0.35
    dc = cash_or_nothing(S, K, T, r, sig, q, "call", 10)["price"]
    dp = cash_or_nothing(S, K, T, r, sig, q, "put", 10)["price"]
    assert dc + dp == pytest.approx(10*np.exp(-r*T), abs=1e-10)
    ac = asset_or_nothing(S, K, T, r, sig, q, "call")["price"]
    ap = asset_or_nothing(S, K, T, r, sig, q, "put")["price"]
    assert ac + ap == pytest.approx(S*np.exp(-q*T), abs=1e-10)
    con1 = cash_or_nothing(S, K, T, r, sig, q, "call", 1.0)["price"]
    assert ac - K*con1 == pytest.approx(bsm(S, K, T, r, sig, q).price, abs=1e-10)


# ── Barrier: full branch table (the 2026-06 audit bug) ───

def test_barrier_in_out_parity_all_branches():
    from instruments.barrier import single_barrier
    S, T, r, q, sig = 100.0, 0.5, 0.08, 0.04, 0.25
    for opt in ("call", "put"):
        for K in (90.0, 110.0):
            for H in (95.0, 105.0):
                d = "down" if H < S else "up"
                ko = single_barrier(S, K, H, T, r, sig, q, opt, f"{d}-out")["price"]
                ki = single_barrier(S, K, H, T, r, sig, q, opt, f"{d}-in")["price"]
                vanilla = bsm(S, K, T, r, sig, q, opt).price
                assert ko + ki == pytest.approx(vanilla, abs=1e-9), (opt, K, H)
                assert ko >= -1e-12 and ki >= -1e-12


def test_barrier_degenerate_branches():
    from instruments.barrier import single_barrier
    # up-and-out call with K >= H is worthless (audit found 16.03 here)
    assert single_barrier(100, 110, 105, 1.0, 0.05, 0.25, 0.0, "call", "up-out")["price"] \
        == pytest.approx(0.0, abs=1e-9)
    # down-and-out put with K <= H is worthless
    assert single_barrier(100, 90, 95, 0.5, 0.08, 0.25, 0.04, "put", "down-out")["price"] \
        == pytest.approx(0.0, abs=1e-9)
    # far barrier -> vanilla
    assert single_barrier(100, 100, 20, 1.0, 0.05, 0.25, 0.0, "call", "down-out")["price"] \
        == pytest.approx(bsm(100, 100, 1.0, 0.05, 0.25).price, abs=1e-4)
    # already-knocked spot
    assert single_barrier(100, 100, 100, 1.0, 0.05, 0.25, 0.0, "call", "down-out",
                          rebate=3.0)["price"] == pytest.approx(3.0)


def test_barrier_haug_reference():
    from instruments.barrier import single_barrier
    # Haug (2007) table 4-13: S=100, X=100, H=95, T=0.5, r=0.08, b=0.04, sigma=0.25, R=3
    v = single_barrier(100, 100, 95, 0.5, 0.08, 0.25, 0.04, "call", "down-out", rebate=3.0)
    assert v["price"] == pytest.approx(6.7924, abs=2e-4)


def test_barrier_vs_mc_bgk():
    from instruments.barrier import single_barrier
    from models.monte_carlo import gbm_paths
    S, K, H, T, r, q, sig = 100.0, 100.0, 90.0, 1.0, 0.05, 0.02, 0.25
    steps, n_sims = 500, 30_000
    dt = T/steps
    paths = gbm_paths(S, r, q, sig, T, steps, n_sims, seed=17)
    Hs = H*np.exp(0.5826*sig*np.sqrt(dt))           # BGK continuity adjustment
    knocked = paths.min(axis=1) <= Hs
    pv = np.exp(-r*T)*np.where(knocked, 0.0, np.maximum(paths[:, -1]-K, 0))
    cf = single_barrier(S, K, H, T, r, sig, q, "call", "down-out")["price"]
    assert cf == pytest.approx(pv.mean(), abs=4*pv.std()/np.sqrt(n_sims) + 0.05)


# ── Lookback: identity + MC (the 2026-06 audit bug) ──────

def test_lookback_float_put_fixed_call_identity():
    from instruments.lookback import fixed_lookback, floating_lookback
    S, T, r, q, sig = 100.0, 1.0, 0.05, 0.0, 0.3
    fp = floating_lookback(S, T, r, sig, q, "put")["price"]
    fc = fixed_lookback(S, S, T, r, sig, q, "call")["price"]
    # floating put == fixed call(K=M=S) + S e^{-rT} - S e^{-qT}, exact
    assert fp == pytest.approx(fc + S*np.exp(-r*T) - S*np.exp(-q*T), abs=1e-9)
    fcall = floating_lookback(S, T, r, sig, q, "call")["price"]
    fput_fixed = fixed_lookback(S, S, T, r, sig, q, "put")["price"]
    assert fcall == pytest.approx(fput_fixed + S*np.exp(-q*T) - S*np.exp(-r*T), abs=1e-9)


def test_lookback_vs_mc_richardson():
    from instruments.lookback import fixed_lookback, floating_lookback
    from models.monte_carlo import gbm_paths
    S, T, r, q, sig = 100.0, 1.0, 0.05, 0.0, 0.3
    vals = {}
    for steps in (250, 1000):
        paths = gbm_paths(S, r, q, sig, T, steps, 40_000, seed=23)
        S_T, mx, mn = paths[:, -1], paths.max(axis=1), paths.min(axis=1)
        disc = np.exp(-r*T)
        vals[steps] = dict(
            float_put=disc*np.maximum(mx - S_T, 0).mean(),
            fixed_call=disc*np.maximum(mx - 110.0, 0).mean(),
            fixed_put=disc*np.maximum(90.0 - mn, 0).mean(),
        )
    for key, cf in (
        ("float_put", floating_lookback(S, T, r, sig, q, "put")["price"]),
        ("fixed_call", fixed_lookback(S, 110.0, T, r, sig, q, "call")["price"]),
        ("fixed_put", fixed_lookback(S, 90.0, T, r, sig, q, "put")["price"]),
    ):
        extrap = 2*vals[1000][key] - vals[250][key]   # bias ~ sqrt(dt)
        assert cf == pytest.approx(extrap, abs=max(0.2, 0.02*extrap)), key


def test_lookback_dominates_vanilla():
    from instruments.lookback import floating_lookback
    lb = floating_lookback(100, 1.0, 0.05, 0.2, 0.0, "call")["price"]
    assert lb >= bsm(100, 100, 1.0, 0.05, 0.2).price - 1e-9


# ── Asian ────────────────────────────────────────────────

def test_geometric_asian_n1_equals_bsm():
    from instruments.asian import geometric_asian_discrete
    assert geometric_asian_discrete(100, 95, 1.25, 0.07, 0.35, 0.03, 1)["price"] \
        == pytest.approx(bsm(100, 95, 1.25, 0.07, 0.35, 0.03).price, abs=1e-9)


# ── Variance swap (the 2026-06 audit bug) ────────────────

def test_variance_swap_recovers_sigma_squared():
    from instruments.variance_swaps import variance_swap_fair_strike
    sig, T, r, q = 0.22, 0.75, 0.04, 0.03
    F = 100*np.exp((r-q)*T)
    ks = np.linspace(30, 300, 540)
    puts = [(k, bsm(100, k, T, r, sig, q, "put").price) for k in ks if k < F]
    calls = [(k, bsm(100, k, T, r, sig, q, "call").price) for k in ks if k >= F]
    vs = variance_swap_fair_strike(r, q, T, puts, calls, 100.0)
    assert vs["variance_strike"] == pytest.approx(sig**2, abs=5e-5)


# ── Rates: parities and fair-value zeros ─────────────────

@pytest.fixture(scope="module")
def flat():
    return YieldCurve.flat(0.10)


def test_cap_floor_swap_parity(flat):
    from instruments.fixed_income import cap_floor
    K, N = 0.10, 1_000_000
    cap = cap_floor(N, K, 3.0, 4, flat, 0.30, "cap")["price"]
    floor = cap_floor(N, K, 3.0, 4, flat, 0.30, "floor")["price"]
    swap = sum(0.25*flat.discount(i*0.25)
               * ((flat.discount((i-1)*0.25)/flat.discount(i*0.25)-1)/0.25 - K)
               for i in range(1, 13)) * N
    assert cap - floor == pytest.approx(swap, abs=1e-6)
    assert cap > 0 and floor > 0    # ATM on flat curve: both strictly positive


def test_irs_fair_rate_and_telescope(flat):
    from instruments.fixed_income import irs
    sw = irs(1_000_000, 0.10, 5.0, 2, flat)
    assert sw["float_pv"]/1e6 == pytest.approx(1 - flat.discount(5.0), abs=1e-12)
    assert irs(1_000_000, sw["fair_rate"], 5.0, 2, flat)["npv"] == pytest.approx(0.0, abs=1e-6)
    # dual-curve: projection above discount makes paying fixed at single-curve fair a gain
    proj = flat.parallel_shift(50)
    assert irs(1_000_000, sw["fair_rate"], 5.0, 2, flat, True, proj)["npv"] > 0


def test_basis_swap_reflects_curve_basis(flat):
    from instruments.fixed_income import basis_swap
    shifted = flat.parallel_shift(50)
    bs = basis_swap(1_000_000, 0.0, 3.0, 4, flat, shifted)
    # receiving the higher index requires paying away ~50bp (simple-rate equivalent)
    assert bs["fair_spread"] == pytest.approx(-0.005, abs=5e-4)
    assert bs["npv"] > 0
    at_fair = basis_swap(1_000_000, bs["fair_spread"], 3.0, 4, flat, shifted)
    assert at_fair["npv"] == pytest.approx(0.0, abs=1e-6)
    same = basis_swap(1_000_000, 0.0, 3.0, 4, flat, flat)
    assert same["fair_spread"] == pytest.approx(0.0, abs=1e-12)


def test_swaption_payer_receiver_parity(flat):
    from instruments.fixed_income import swaption
    K, N = 0.09, 1_000_000
    pay = swaption(N, K, 1.0, 5.0, 2, flat, 0.25, "payer")
    rec = swaption(N, K, 1.0, 5.0, 2, flat, 0.25, "receiver")
    assert pay["price"] - rec["price"] == pytest.approx(
        N*pay["annuity"]*(pay["fwd_swap_rate"] - K), abs=1e-6)


def test_fra_and_ois_zero_at_fair(flat):
    from instruments.fixed_income import fra, ois
    fwd_simple = (flat.discount(1.0)/flat.discount(1.5) - 1)/0.5
    assert fra(1_000_000, fwd_simple, 1.0, 1.5, flat)["npv"] == pytest.approx(0.0, abs=1e-6)
    o = ois(1_000_000, 0.0, 2.0, flat)
    assert ois(1_000_000, o["fair_ois_rate"], 2.0, flat)["npv"] == pytest.approx(0.0, abs=1e-6)


def test_callable_putable_bounds(flat):
    from instruments.fixed_income import callable_bond, fixed_bond
    cb = callable_bond(100, 0.12, 5.0, 2, flat, sigma=0.15,
                       call_price=100, call_start=1.0, option="callable")
    assert cb["price"] <= cb["straight_value"] + 1e-9
    pb = callable_bond(100, 0.08, 5.0, 2, flat, sigma=0.15,
                       put_price=100, put_start=1.0, option="putable")
    assert pb["price"] >= pb["straight_value"] - 1e-9
    assert cb["straight_value"] == pytest.approx(
        fixed_bond(100, 0.12, 5.0, 2, flat)["price"], abs=0.1)


# ── Credit ───────────────────────────────────────────────

def test_cds_fair_spread_consistency():
    from instruments.credit import cds, cds_implied_hazard
    c1 = cds(10_000_000, 0.01, 5.0, 4, 0.02, 0.05, 0.4, True)
    assert cds(10_000_000, c1["fair_spread"], 5.0, 4, 0.02, 0.05, 0.4, True)["npv"] \
        == pytest.approx(0.0, abs=1.0)
    assert c1["fair_spread"] == pytest.approx(0.02*0.6, abs=5e-4)
    h = cds_implied_hazard(0.012, 5.0, 4, 0.05, 0.4)
    assert cds(1, 0.012, 5.0, 4, h, 0.05, 0.4)["npv"] == pytest.approx(0.0, abs=1e-8)


# ── Multi-asset / stochastic vol ─────────────────────────

def test_kirk_margrabe_and_quanto_limits():
    from instruments.multi_asset import exchange_option, quanto_option, spread_option_kirk
    ex = exchange_option(100, 95, 1.0, 0.05, 0.3, 0.25, 0.4)["price"]
    assert spread_option_kirk(100, 95, 0.0, 1.0, 0.05, 0.3, 0.25, 0.4)["price"] \
        == pytest.approx(ex, abs=1e-9)
    assert quanto_option(100, 100, 1.0, 0.05, 0.03, 0.3, 0.0, 0.0)["price"] \
        == pytest.approx(bsm(100, 100, 1.0, 0.05, 0.3, 0.03).price, abs=1e-9)


def test_heston_parity_and_bsm_limit():
    from models.heston import heston_price
    hp = heston_price(100, 100, 1.0, 0.05, 0.0, 0.09, 2.0, 0.09, 1e-4, 0.0)
    assert hp["price"] == pytest.approx(bsm(100, 100, 1.0, 0.05, 0.3).price, abs=5e-3)
    hc = heston_price(100, 90, 1.0, 0.05, 0.02, 0.09, 1.5, 0.08, 0.5, -0.6)["price"]
    hpv = heston_price(100, 90, 1.0, 0.05, 0.02, 0.09, 1.5, 0.08, 0.5, -0.6, "put")["price"]
    assert hc - hpv == pytest.approx(100*np.exp(-0.02) - 90*np.exp(-0.05), abs=5e-3)


def test_sabr_limits():
    from models.heston import sabr_vol
    assert sabr_vol(0.05, 0.05, 2.0, 0.2, 1.0, 0.0, 1e-6) == pytest.approx(0.2, abs=1e-4)
    assert sabr_vol(0.05, 0.0500001, 1.0, 0.2, 0.5, -0.3, 0.4) == pytest.approx(
        sabr_vol(0.05, 0.05, 1.0, 0.2, 0.5, -0.3, 0.4), abs=1e-4)


# ── Short-rate models ────────────────────────────────────

def test_hull_white_fit_and_option_parity(flat):
    from models.short_rate import HullWhite
    hw = HullWhite(0.1, 0.012, flat)
    assert hw.zero_rate(7.0) == pytest.approx(flat.rate(7.0), abs=5e-4)
    KB = 0.7
    c = hw.bond_option(1.0, 5.0, KB, "call")
    p = hw.bond_option(1.0, 5.0, KB, "put")
    assert c - p == pytest.approx(
        hw.bond_price(hw._r0, 0, 5.0) - KB*hw.bond_price(hw._r0, 0, 1.0), abs=1e-8)


# ── Implied vol round-trip ───────────────────────────────

def test_implied_vol_round_trip():
    from models.implied_vol import implied_vol_bsm
    price = bsm(100, 95, 1.25, 0.07, 0.35, 0.03).price
    assert implied_vol_bsm(price, 100, 95, 1.25, 0.07, 0.03, "call") \
        == pytest.approx(0.35, abs=1e-6)
