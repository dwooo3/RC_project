"""
Regression tests for the HIGH-severity items in MODEL_REVIEW_AND_RECOMMENDATIONS.md.

Genuine bugs fixed here (with dedicated + edge-case tests):
  - Caplet double-discounting        -> instruments/fixed_income.py
  - Hull-White curve reconstitution  -> models/short_rate.py
  - Historical VaR horizon handling  -> risk/var.py

False positives (NOT changed) — tests lock in the already-correct behaviour and
would fail if the proposed (harmful) "fixes" were ever applied:
  - Heston characteristic function (already the stable "Little Heston Trap" form)
  - Discrete geometric Asian d1 (already correct)

References:
  - Brigo & Mercurio, "Interest Rate Models — Theory and Practice" (2006), §1.6.
  - Hull & White, "Pricing Interest-Rate-Derivative Securities" (1990).
  - McNeil, Frey & Embrechts, "Quantitative Risk Management" (2015), §2.2.3.
  - Albrecher et al., "The Little Heston Trap" (2007).
  - Kemna & Vorst, "A Pricing Method for Options Based on Average Asset Values" (1990).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import numpy as np
import pytest

warnings.filterwarnings("ignore")

from models.black_scholes import bsm, black76
from models.heston import heston_price
from models.short_rate import HullWhite
from curves.yield_curve import YieldCurve
from instruments.fixed_income import caplet
from instruments.asian import geometric_asian_discrete
from risk.var import historical_var


# ─────────────────────────────────────────────────────────
# 7. Caplet — single discounting (was double-discounted by disc^(1+T1/T2))
# ─────────────────────────────────────────────────────────

def test_caplet_discounted_exactly_once():
    notional, K, T1, T2, F, sigma, disc = 1e6, 0.03, 1.0, 1.25, 0.035, 0.20, 0.95
    tau = T2 - T1
    expected = notional * tau * disc * black76(F, K, T1, 0.0, sigma, "call").price
    res = caplet(notional, K, T1, T2, F, sigma, disc, "cap")
    assert res["price"] == pytest.approx(expected, rel=1e-12)


def test_caplet_floorlet_parity():
    """cap - floor caplet = discounted forward intrinsic notional*tau*disc*(F-K)."""
    notional, K, T1, T2, F, sigma, disc = 1e6, 0.03, 1.0, 1.25, 0.035, 0.20, 0.95
    tau = T2 - T1
    cap = caplet(notional, K, T1, T2, F, sigma, disc, "cap")["price"]
    flr = caplet(notional, K, T1, T2, F, sigma, disc, "floor")["price"]
    assert cap - flr == pytest.approx(notional * tau * disc * (F - K), rel=1e-9)


def test_caplet_no_double_discount_when_disc_unity():
    """With disc=1 (r=0) the caplet equals the plain undiscounted Black-76 value."""
    notional, K, T1, T2, F, sigma = 1e6, 0.03, 1.0, 2.0, 0.035, 0.25
    tau = T2 - T1
    res = caplet(notional, K, T1, T2, F, sigma, 1.0, "cap")
    expected = notional * tau * black76(F, K, T1, 0.0, sigma, "call").price
    assert res["price"] == pytest.approx(expected, rel=1e-12)


def test_caplet_zero_time_value_floored():
    """Edge: tiny vol -> caplet ~ discounted intrinsic, non-negative."""
    res = caplet(1e6, 0.03, 1.0, 1.5, 0.035, 1e-8, 0.95, "cap")
    assert res["price"] >= 0.0


# ─────────────────────────────────────────────────────────
# 5. Hull-White — must reprice the initial discount curve exactly
# ─────────────────────────────────────────────────────────

def _sloped_curve():
    tenors = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10])
    zr     = np.array([0.02, 0.022, 0.025, 0.028, 0.030, 0.033, 0.035, 0.037])
    return YieldCurve(tenors, zr)


@pytest.mark.parametrize("T", [0.5, 1.0, 2.0, 5.0, 10.0])
def test_hw_reprices_initial_curve_sloped(T):
    crv = _sloped_curve()
    hw  = HullWhite(kappa=0.1, sigma=0.01, curve=crv)
    assert hw.bond_price(hw._r0, 0.0, T) == pytest.approx(crv.discount(T), rel=1e-6)


@pytest.mark.parametrize("kappa,sigma", [(0.03, 0.005), (0.5, 0.02), (1.0, 0.03)])
def test_hw_reprices_curve_across_params(kappa, sigma):
    """Exact fit must hold for any (kappa, sigma) — it is a no-arbitrage property."""
    crv = _sloped_curve()
    hw  = HullWhite(kappa=kappa, sigma=sigma, curve=crv)
    for T in (1.0, 3.0, 7.0):
        assert hw.bond_price(hw._r0, 0.0, T) == pytest.approx(crv.discount(T), rel=1e-6)


def test_hw_zero_rate_matches_market_curve():
    crv = _sloped_curve()
    hw  = HullWhite(kappa=0.1, sigma=0.01, curve=crv)
    for T in (1.0, 5.0, 10.0):
        assert hw.zero_rate(T) == pytest.approx(crv.rate(T), abs=1e-5)


def test_hw_reprices_flat_curve_edge():
    crv = YieldCurve.flat(0.03)
    hw  = HullWhite(kappa=0.2, sigma=0.015, curve=crv)
    for T in (0.5, 2.0, 8.0):
        assert hw.bond_price(hw._r0, 0.0, T) == pytest.approx(crv.discount(T), rel=1e-6)


def test_hw_instantaneous_forward_steeper_than_average():
    """On an upward curve the instantaneous forward at T exceeds the avg forward."""
    crv = _sloped_curve()
    hw  = HullWhite(kappa=0.1, sigma=0.01, curve=crv)
    T = 5.0
    inst = hw._inst_forward(T)
    avg  = crv.forward_rate(0, T)
    assert inst > avg


# ─────────────────────────────────────────────────────────
# 6. Historical VaR — horizon via actual multi-day windows, not sqrt(h)
# ─────────────────────────────────────────────────────────

def test_var_horizon_one_unchanged():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, 500)
    res = historical_var(returns, 1_000_000, confidence=0.95, horizon=1)
    losses = np.sort(-returns)
    idx = min(max(int(np.ceil(0.95 * len(losses))) - 1, 0), len(losses) - 1)
    assert res["VaR_pct"] == pytest.approx(max(losses[idx], 0.0))


def test_var_multiday_matches_overlapping_windows():
    """horizon=10 must equal the empirical 99% loss of overlapping 10-day sums."""
    rng = np.random.default_rng(1)
    returns = rng.standard_t(3, size=2000) * 0.01
    h, conf = 10, 0.99
    res = historical_var(returns, 1_000_000, confidence=conf, horizon=h)

    c = np.concatenate(([0.0], np.cumsum(returns)))
    agg = c[h:] - c[:-h]
    losses = np.sort(-agg)
    idx = min(max(int(np.ceil(conf * len(losses))) - 1, 0), len(losses) - 1)
    assert res["VaR_pct"] == pytest.approx(max(losses[idx], 0.0))


def test_var_multiday_differs_from_sqrt_scaling_on_fat_tails():
    """The whole point: on fat tails the window estimate is not sqrt(h)*1-day VaR."""
    rng = np.random.default_rng(2)
    returns = rng.standard_t(3, size=2000) * 0.01
    v1 = historical_var(returns, 1_000_000, confidence=0.99, horizon=1)["VaR_pct"]
    v10 = historical_var(returns, 1_000_000, confidence=0.99, horizon=10)["VaR_pct"]
    assert abs(v10 - v1 * np.sqrt(10)) / (v1 * np.sqrt(10)) > 0.05


def test_var_small_sample_falls_back_to_sqrt():
    """Backward-compatible: too few obs for windows -> legacy sqrt-time scaling."""
    returns = np.array([0.02, 0.01, 0.0, -0.01, -0.02])
    one = historical_var(returns, 100.0, confidence=0.80, horizon=1)["VaR"]
    four = historical_var(returns, 100.0, confidence=0.80, horizon=4)["VaR"]
    assert four == pytest.approx(one * 2.0)


def test_var_multiday_es_ge_var():
    rng = np.random.default_rng(3)
    returns = rng.normal(0, 0.012, 1500)
    res = historical_var(returns, 1_000_000, confidence=0.975, horizon=10)
    assert res["CVaR"] >= res["VaR"] - 1e-8


# ─────────────────────────────────────────────────────────
# 4. Heston — already stable (FALSE POSITIVE). Guard the correct formulation.
# ─────────────────────────────────────────────────────────

def test_heston_converges_to_bsm_low_volvol():
    """xi -> 0 with v0 = theta reduces Heston to BSM at constant vol sqrt(v0)."""
    h = heston_price(100, 100, 1.0, 0.02, 0.0, 0.04, 1.5, 0.04, 1e-4, -0.5, "call")["price"]
    b = bsm(100, 100, 1.0, 0.02, 0.2, 0.0, "call").price
    assert h == pytest.approx(b, abs=1e-3)


@pytest.mark.parametrize("T,xi,rho", [(5.0, 0.9, -0.8), (10.0, 1.0, -0.9)])
def test_heston_stable_long_dated_extreme(T, xi, rho):
    """Long-dated, high vol-of-vol, strong negative rho must stay finite & positive.

    The stable 'Little Heston Trap' formulation (exp(-lam*T)) is required here;
    the originally-proposed swap to exp(+lam*T) overflows to NaN.
    """
    price = heston_price(100, 100, T, 0.02, 0.0, 0.04, 1.0, 0.04, xi, rho, "call")["price"]
    assert np.isfinite(price)
    intrinsic = 100 - 100 * np.exp(-0.02 * T)
    assert price >= intrinsic - 1e-6
    assert price < 100.0


# ─────────────────────────────────────────────────────────
# 8. Discrete geometric Asian — already correct (FALSE POSITIVE).
# ─────────────────────────────────────────────────────────

def _mc_geo_discrete(S, K, T, r, sigma, q, n, seed=7, n_sims=300_000):
    rng = np.random.default_rng(seed)
    dt = T / n
    Z = rng.standard_normal((n_sims, n))
    logS = np.log(S) + np.cumsum((r - q - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z, axis=1)
    geo = np.exp(logS.mean(axis=1))
    pv = np.exp(-r * T) * np.maximum(geo - K, 0)
    return pv.mean(), pv.std() / np.sqrt(n_sims)


@pytest.mark.parametrize("S,K,T,r,sigma,n", [
    (100, 100, 1.0, 0.05, 0.20, 12),
    (100, 90, 1.0, 0.05, 0.20, 12),
])
def test_asian_discrete_matches_mc(S, K, T, r, sigma, n):
    cf = geometric_asian_discrete(S, K, T, r, sigma, 0.0, n, "call")["price"]
    mc, se = _mc_geo_discrete(S, K, T, r, sigma, 0.0, n)
    assert abs(cf - mc) < 4 * se, f"closed={cf:.4f} mc={mc:.4f}+-{se:.4f}"
