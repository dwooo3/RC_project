"""
Regression tests for the MEDIUM-severity items in MODEL_REVIEW_AND_RECOMMENDATIONS.md.

Genuine fixes (validated numerically before changing code):
  1a. BSM put delta at expiry  (-1 when ITM, was 0)
  1b. BSM volga scaling        (per 1%^2, was 100x too large)
  1c. BSM ultima formula       (/sigma^2, was /sigma)
  2.  Heston dividend-adjusted delta (e^{-qT} P1)
  4.  Monte Carlo control-variate expectation (E[disc*S_T]=S0 e^{-qT})
  5.  Fixed-income modified duration uses YTM (was zero rate at maturity)
  6.  Cash digital put gamma sign

False positive (NOT changed) — guard test locks the already-correct behaviour:
  3.  Vasicek kappa=0 limit: A = +sigma^2 T^3/6 is correct (convexity raises the
      bond price), confirmed against Monte Carlo. The review's sign-flip is wrong.

References: Haug (2007) App. B; Heston (1993); Vasicek (1977); Glasserman (2004)
§4.1 (control variates); Tuckman & Serrat (duration).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import numpy as np
import pytest

warnings.filterwarnings("ignore")

from models.black_scholes import bsm
from models.heston import heston_price
from models.short_rate import Vasicek
from models.monte_carlo import gbm_paths, mc_price
from curves.yield_curve import YieldCurve
from instruments.fixed_income import fixed_bond
from instruments.digital import cash_or_nothing


# ─────────────────────────────────────────────────────────
# 1a. BSM put delta at expiry
# ─────────────────────────────────────────────────────────

def test_bsm_put_delta_at_expiry_itm():
    assert bsm(90, 100, 0.0, 0.03, 0.2, 0.0, "put").delta == -1.0


def test_bsm_put_delta_at_expiry_otm():
    assert bsm(110, 100, 0.0, 0.03, 0.2, 0.0, "put").delta == 0.0


def test_bsm_call_delta_at_expiry_unchanged():
    assert bsm(110, 100, 0.0, 0.03, 0.2, 0.0, "call").delta == 1.0
    assert bsm(90, 100, 0.0, 0.03, 0.2, 0.0, "call").delta == 0.0


def test_bsm_put_delta_continuous_into_expiry():
    """Near-expiry analytic delta should approach the boundary value."""
    near = bsm(90, 100, 1e-6, 0.03, 0.2, 0.0, "put").delta
    assert near == pytest.approx(-1.0, abs=1e-4)


# ─────────────────────────────────────────────────────────
# 1b. BSM volga scaling (per 1%^2)
# ─────────────────────────────────────────────────────────

def test_bsm_volga_per_one_pct_squared():
    S, K, T, r, sig, q = 100, 100, 1.0, 0.05, 0.2, 0.0
    g = bsm(S, K, T, r, sig, q, "call")
    h = 1e-5
    # d(vega_per1%)/dsigma * (1% step) — finite difference in per-1%^2 units
    vup = bsm(S, K, T, r, sig + h, q, "call").vega
    vdn = bsm(S, K, T, r, sig - h, q, "call").vega
    fd = (vup - vdn) / (2 * h) * 0.01
    assert g.volga == pytest.approx(fd, rel=1e-3)


# ─────────────────────────────────────────────────────────
# 1c. BSM ultima formula (/sigma^2)
# ─────────────────────────────────────────────────────────

def test_bsm_ultima_matches_dvolga_dsigma():
    S, K, T, r, sig, q = 100, 100, 1.0, 0.05, 0.2, 0.0
    g = bsm(S, K, T, r, sig, q, "call")
    h = 1e-5
    # raw volga = code volga (per 1%^2) * 10000
    raw = lambda s: bsm(S, K, T, r, s, q, "call").volga * 10000
    fd_ultima = (raw(sig + h) - raw(sig - h)) / (2 * h)
    assert g.ultima == pytest.approx(fd_ultima, rel=1e-3)


# ─────────────────────────────────────────────────────────
# 2. Heston dividend-adjusted delta
# ─────────────────────────────────────────────────────────

def test_heston_delta_dividend_adjusted():
    q, T = 0.04, 2.0
    args = dict(opt="call")
    res = heston_price(100, 100, T, 0.03, q, 0.04, 1.5, 0.04, 0.5, -0.5, **args)
    f = lambda s: heston_price(s, 100, T, 0.03, q, 0.04, 1.5, 0.04, 0.5, -0.5, **args)["price"]
    fd = (f(100.5) - f(99.5)) / 1.0
    assert res["delta"] == pytest.approx(fd, abs=2e-3)


def test_heston_delta_equals_bsm_when_no_dividend_low_volvol():
    res = heston_price(100, 100, 1.0, 0.03, 0.0, 0.04, 1.5, 0.04, 1e-4, -0.5, "call")
    b = bsm(100, 100, 1.0, 0.03, 0.2, 0.0, "call")
    assert res["delta"] == pytest.approx(b.delta, abs=2e-3)


# ─────────────────────────────────────────────────────────
# 3. Vasicek kappa=0 — FALSE POSITIVE, code is correct
# ─────────────────────────────────────────────────────────

def test_vasicek_kappa_zero_matches_analytic_and_is_positive_A():
    r0, sig, T = 0.03, 0.02, 5.0
    v = Vasicek(r0, 0.0, 0.05, sig)
    A, B = v._AB(T)
    assert A == pytest.approx(sig**2 * T**3 / 6, rel=1e-12)   # POSITIVE (convexity)
    assert B == pytest.approx(T)
    P = v.bond_price(r0, T)
    assert P == pytest.approx(np.exp(-r0 * T + sig**2 * T**3 / 6), rel=1e-12)


def test_vasicek_kappa_zero_matches_monte_carlo():
    r0, sig, T = 0.03, 0.02, 5.0
    P_analytic = Vasicek(r0, 0.0, 0.05, sig).bond_price(r0, T)
    rng = np.random.default_rng(0)
    n, steps = 200_000, 500
    dt = T / steps
    r = np.full(n, r0); integ = np.zeros(n)
    for _ in range(steps):
        integ += r * dt
        r = r + sig * np.sqrt(dt) * rng.standard_normal(n)
    P_mc = np.exp(-integ).mean()
    assert P_analytic == pytest.approx(P_mc, rel=5e-3)


# ─────────────────────────────────────────────────────────
# 4. Monte Carlo control-variate expectation
# ─────────────────────────────────────────────────────────

def test_mc_control_variate_unbiased_vs_bsm():
    S0, r, q, sig, T = 100, 0.05, 0.0, 0.2, 1.0
    ref = bsm(S0, 100, T, r, sig, q, "call").price

    def payoff(p):
        return np.maximum(p[:, -1] - 100, 0)

    res = mc_price(payoff, S0, r, q, sig, T, steps=1, n_sims=200_000,
                   control_variate=True, seed=1)
    assert res["price"] == pytest.approx(ref, abs=0.05)


def test_mc_control_variate_reduces_bias_with_dividend():
    S0, r, q, sig, T = 100, 0.05, 0.03, 0.2, 1.0
    ref = bsm(S0, 100, T, r, sig, q, "call").price

    def payoff(p):
        return np.maximum(p[:, -1] - 100, 0)

    res = mc_price(payoff, S0, r, q, sig, T, steps=1, n_sims=200_000,
                   control_variate=True, seed=3)
    assert abs(res["price"] - ref) < 0.05


# ─────────────────────────────────────────────────────────
# 5. Modified duration uses YTM
# ─────────────────────────────────────────────────────────

def test_mod_duration_defined_off_ytm():
    crv = YieldCurve(np.array([0.5, 1, 2, 3, 5, 7, 10]),
                     np.array([0.02, 0.025, 0.03, 0.033, 0.037, 0.04, 0.042]))
    res = fixed_bond(face=100, coupon=0.05, T=10, freq=2, curve=crv)
    expected = res["mac_duration"] / (1 + res["ytm"] / 2)
    assert res["mod_duration"] == pytest.approx(expected, rel=1e-9)


def test_mod_duration_differs_from_zero_rate_version_on_sloped_curve():
    crv = YieldCurve(np.array([0.5, 1, 2, 3, 5, 7, 10]),
                     np.array([0.02, 0.025, 0.03, 0.033, 0.037, 0.04, 0.042]))
    res = fixed_bond(face=100, coupon=0.05, T=10, freq=2, curve=crv)
    zero_rate_version = res["mac_duration"] / (1 + crv.rate(10.0) / 2)
    assert abs(res["mod_duration"] - zero_rate_version) > 1e-6


# ─────────────────────────────────────────────────────────
# 6. Cash digital put gamma sign
# ─────────────────────────────────────────────────────────

def test_digital_put_gamma_sign_matches_finite_difference():
    S, K, T, r, sig, q = 100, 100, 0.5, 0.04, 0.2, 0.0
    put = cash_or_nothing(S, K, T, r, sig, q, "put")
    h = 1e-3
    du = cash_or_nothing(S + h, K, T, r, sig, q, "put")["delta"]
    dd = cash_or_nothing(S - h, K, T, r, sig, q, "put")["delta"]
    fd = (du - dd) / (2 * h)
    assert put["gamma"] == pytest.approx(fd, rel=2e-2)


def test_digital_put_gamma_is_negative_of_call_gamma():
    S, K, T, r, sig, q = 100, 100, 0.5, 0.04, 0.2, 0.0
    call = cash_or_nothing(S, K, T, r, sig, q, "call")
    put = cash_or_nothing(S, K, T, r, sig, q, "put")
    assert put["gamma"] == pytest.approx(-call["gamma"], rel=1e-12)
