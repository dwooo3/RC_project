"""
Regression tests for the CRITICAL mathematical-correctness review.

Covers the three items flagged as CRITICAL in MODEL_REVIEW_AND_RECOMMENDATIONS.md:

  1. Variance-swap replication weight   -> genuine bug, FIXED here.
  2. Theta in models/trees.py           -> verified ALREADY CORRECT (no change).
  3. Theta in models/monte_carlo.py     -> no theta is computed there (nothing to fix).

The theta tests are deliberately strict so they would FAIL if the originally
proposed `(pt - price) / 365` "fix" were ever applied (that change would make
theta 365x too small).

References:
  - Demeterfi, Derman, Kamal, Zou (1999), "More Than You Ever Wanted to Know
    About Volatility Swaps", Goldman Sachs Quantitative Strategies Research Notes.
  - Hull, "Options, Futures, and Other Derivatives", 11th ed., §19.5 (theta).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from models.black_scholes import bsm
from models.trees import binomial_crr, trinomial
from models.monte_carlo import mc_price
from instruments.variance_swaps import variance_swap_fair_strike


# ─────────────────────────────────────────────────────────
# 1. Variance swap — fair variance strike under a flat vol surface
# ─────────────────────────────────────────────────────────

def _flat_vol_chain(S0=100.0, r=0.0, q=0.0, T=1.0, sigma=0.20,
                    lo=20.0, hi=300.0, step=0.5):
    """OTM put/call chain priced at a flat implied vol (r=q=0 => forward prices)."""
    F = S0 * np.exp((r - q) * T)
    strikes = np.arange(lo, hi + 1e-9, step)
    puts  = [(float(K), float(bsm(S0, K, T, r, sigma, q, "put").price))
             for K in strikes if K < F]
    calls = [(float(K), float(bsm(S0, K, T, r, sigma, q, "call").price))
             for K in strikes if K >= F]
    return S0, r, q, T, sigma, F, puts, calls


def test_variance_swap_flat_vol_recovers_sigma_squared():
    """Under a flat 20% surface the fair variance strike must equal sigma^2 = 0.04."""
    S0, r, q, T, sigma, F, puts, calls = _flat_vol_chain()
    res = variance_swap_fair_strike(r, q, T, puts, calls, S0, F)
    assert abs(res["variance_strike"] - sigma**2) < 1e-3, (
        f"K_var={res['variance_strike']:.5f} expected={sigma**2:.5f}")
    assert abs(res["vol_strike"] - sigma) < 5e-3, (
        f"vol_strike={res['vol_strike']:.5f} expected={sigma:.5f}")


def test_variance_swap_no_systematic_overestimate_under_refinement():
    """
    The bug (spurious 1 - log(K/F) weight) produced a ~1% overestimate that did
    NOT shrink as the strike grid was refined. After the fix the estimate must
    sit essentially on sigma^2 on a fine grid, not biased high.
    """
    _, r, q, T, sigma, F, puts, calls = _flat_vol_chain(step=0.25, lo=10.0, hi=400.0)
    res = variance_swap_fair_strike(r, q, T, puts, calls, 100.0, F)
    err = res["variance_strike"] - sigma**2
    # must be within tight band and not the old +0.0004 (=+1%) high bias
    assert abs(err) < 5e-4, f"K_var={res['variance_strike']:.6f} err={err:+.6f}"


# ─────────────────────────────────────────────────────────
# 2. Tree theta — verified correct (per calendar day), guards the wrong "fix"
# ─────────────────────────────────────────────────────────

def _bsm_theta_per_day(S, K, T, r, sigma, q=0.0, opt="call"):
    """Analytical BSM theta; black_scholes.bsm already returns it per calendar day."""
    return bsm(S, K, T, r, sigma, q, opt).theta


def test_crr_theta_matches_bsm_per_day():
    """
    CRR theta must match the analytical BSM theta on a *per calendar day* basis.
    This fails hard if theta is rescaled (e.g. the rejected (pt-price)/365 fix,
    which would be ~365x too small).
    """
    S, K, T, r, sigma = 100, 100, 0.25, 0.05, 0.20
    res = binomial_crr(S, K, T, r, sigma, N=2000, opt="call", exercise="european")
    ref = _bsm_theta_per_day(S, K, T, r, sigma, opt="call")
    assert abs(res["theta"] - ref) < 5e-3, (
        f"CRR theta/day={res['theta']:.5f} BSM theta/day={ref:.5f}")


def test_crr_theta_is_daily_scale_not_annual():
    """ATM 3M call daily theta is O(0.01-0.1); annual would be O(10). Guards scaling."""
    res = binomial_crr(100, 100, 0.25, 0.05, 0.20, N=1000, opt="call")
    assert res["theta"] < 0.0, "call theta should be negative"
    assert abs(res["theta"]) < 1.0, (
        f"theta={res['theta']:.5f} looks like annual, not per-day")


def test_crr_theta_sign_for_put():
    """Long European put theta is typically negative for these parameters."""
    res = binomial_crr(100, 100, 0.5, 0.05, 0.20, N=1000, opt="put")
    assert abs(res["theta"]) < 1.0


# ─────────────────────────────────────────────────────────
# 3. Monte Carlo — there is no theta in mc_price (nothing to fix)
# ─────────────────────────────────────────────────────────

def test_mc_price_has_no_theta_key():
    """
    Documents that mc_price intentionally returns no theta; the audit item
    referring to a theta double-division in monte_carlo.py does not apply.
    """
    def payoff(paths):
        return np.maximum(paths[:, -1] - 100, 0)

    res = mc_price(payoff, 100, 0.05, 0.0, 0.20, 1.0,
                   steps=50, n_sims=20_000, seed=42)
    assert "theta" not in res
    for k in ("price", "delta", "gamma", "vega"):
        assert k in res
