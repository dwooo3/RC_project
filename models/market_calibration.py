"""
Market-surface calibrations, task-3 of the post-M8 hardening.

Two calibrations that fit a model to observed market quotes:

* **Schwartz-Smith → futures strip + ATM vols** — least squares of the model log
  futures curve and spot-vol term structure onto observed futures prices and
  at-the-money option vols.
* **CDO base correlation** — for each detachment K the flat one-factor Gaussian
  copula correlation that reprices the [0,K] base-tranche expected loss; a
  market with a correlation skew yields a rising/curved base-correlation curve,
  while a flat-correlation pool returns a flat curve == that correlation.

Validated identity-first: each round-trips (calibrate to a model-generated
surface and recover its parameters / reprice it).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares, brentq

from models.commodity import SchwartzSmith
from models.credit_portfolio import cdo_tranche


# ── Schwartz-Smith calibration ───────────────────────────────

def calibrate_schwartz_smith(tenors, futures_mkt, vol_tenors, vol_mkt, r=0.05,
                             spot=None) -> dict:
    """Calibrate Schwartz-Smith (χ0, ξ0, κ, σχ, μξ, σξ, ρ) to an observed futures
    strip and an ATM spot-vol term structure (vol of F(·,T) realised to T)."""
    tenors = np.asarray(tenors, float)
    lnF_mkt = np.log(np.asarray(futures_mkt, float))
    vt = np.asarray(vol_tenors, float)
    vm = np.asarray(vol_mkt, float)
    xi0_guess = np.log(spot) if spot else lnF_mkt[0]

    def build(p):
        chi0, xi0, kappa, schi, muxi, sxi, rho = p
        return SchwartzSmith(chi0=chi0, xi0=xi0, kappa=kappa, sigma_chi=schi,
                             mu_xi=muxi, sigma_xi=sxi, rho=rho, r=r)

    def resid(p):
        m = build(p)
        f_err = [np.log(m.futures(T)) - lf for T, lf in zip(tenors, lnF_mkt)]
        v_err = [np.sqrt(m.futures_log_var(T, T) / T) - v for T, v in zip(vt, vm)]
        return f_err + v_err

    x0 = [0.0, xi0_guess, 1.0, 0.3, 0.0, 0.15, 0.3]
    lo = [-2, xi0_guess - 2, 0.05, 1e-2, -0.5, 1e-2, -0.95]
    hi = [2, xi0_guess + 2, 10.0, 3.0, 0.5, 3.0, 0.95]
    res = least_squares(resid, x0=x0, bounds=(lo, hi), xtol=1e-12, ftol=1e-12)
    m = build(res.x)
    rmse = float(np.sqrt(np.mean(np.square(resid(res.x)))))
    keys = ["chi0", "xi0", "kappa", "sigma_chi", "mu_xi", "sigma_xi", "rho"]
    out = {k: float(v) for k, v in zip(keys, res.x)}
    out.update(rmse=rmse, converged=bool(res.success), model=m)
    return out


# ── CDO base correlation ─────────────────────────────────────

def base_tranche_el(pds, rho, detachment, recovery=0.4, n_z=400):
    """Expected loss of the equity (base) tranche [0, K], fraction of [0,K]."""
    return cdo_tranche(pds, rho, 0.0, detachment, recovery, n_z)["expected_tranche_loss"]


def calibrate_base_correlation(pds, detachments, target_els, recovery=0.4, n_z=400):
    """Solve the flat base correlation ρ(K) that reprices each [0,K] base-tranche
    expected loss to its market value. Returns the base-correlation curve."""
    curve = {}
    for K, target in zip(detachments, target_els):
        def f(rho):
            return base_tranche_el(pds, rho, K, recovery, n_z) - target
        lo, hi = 1e-4, 0.999
        try:
            curve[float(K)] = float(brentq(f, lo, hi, xtol=1e-8))
        except ValueError:                              # target outside [ρ_lo, ρ_hi]
            curve[float(K)] = float(lo if f(lo) > 0 else hi)
    return curve
