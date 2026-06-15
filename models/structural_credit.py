"""
Structural credit models, Master-plan M7.

Default is driven by the firm's asset value V (GBM) hitting its debt:

* **Merton (1974)** — equity = a call on assets struck at the debt face D;
  default if V_T < D at maturity. Gives the risk-neutral PD = N(-d2), the
  distance-to-default, the credit spread and the implied recovery.
* **KMV** — inverts observable equity value/vol to the latent (V, σ_V) via the
  Merton equations, then reads off distance-to-default and EDF = N(-DD).
* **Black-Cox (1976)** — first-passage default: the firm defaults the first time
  V touches a barrier, so PD ≥ Merton's terminal-only PD (closed form via the
  reflection principle).

Validated: Merton equity == Black-Scholes call on assets, spread → 0 at low
leverage and rises with leverage/vol, KMV calibration round-trips (V,σ_V →
E,σ_E → V,σ_V), Black-Cox PD ≥ Merton PD.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm
from scipy.optimize import fsolve


def merton(V0, D, T, r, sigma_V) -> dict:
    """Merton structural model. Returns equity, debt, risk-neutral PD, distance
    to default, credit spread and implied recovery."""
    sq = sigma_V * np.sqrt(T)
    d1 = (np.log(V0 / D) + (r + 0.5 * sigma_V**2) * T) / sq
    d2 = d1 - sq
    equity = V0 * norm.cdf(d1) - D * np.exp(-r * T) * norm.cdf(d2)
    debt = V0 - equity
    pd = norm.cdf(-d2)
    spread = -np.log(debt / D) / T - r
    # E^Q[V_T | V_T < D] / D  -> implied recovery on the debt face
    recovery = (V0 * np.exp(r * T) * norm.cdf(-d1) / max(norm.cdf(-d2), 1e-300)) / D
    return dict(equity=float(equity), debt=float(debt), pd=float(pd),
                distance_to_default=float(d2), credit_spread=float(spread),
                recovery=float(recovery))


def kmv_calibrate(equity, sigma_E, D, T, r) -> dict:
    """KMV: solve (V0, σ_V) from observable equity value and equity vol via
        E = V·N(d1) - D·e^{-rT}·N(d2),   σ_E·E = N(d1)·σ_V·V.
    Returns the latent asset value/vol, distance to default and EDF=N(-DD)."""
    def eqs(z):
        V, sV = z
        if V <= 0 or sV <= 1e-6:
            return [1e6, 1e6]
        sq = sV * np.sqrt(T)
        d1 = (np.log(V / D) + (r + 0.5 * sV**2) * T) / sq
        d2 = d1 - sq
        E = V * norm.cdf(d1) - D * np.exp(-r * T) * norm.cdf(d2)
        return [E - equity, norm.cdf(d1) * sV * V - sigma_E * equity]

    V0, sigma_V = fsolve(eqs, [equity + D * np.exp(-r * T), sigma_E], full_output=False)
    m = merton(V0, D, T, r, sigma_V)
    return dict(asset_value=float(V0), asset_vol=float(sigma_V),
                distance_to_default=m["distance_to_default"],
                edf=float(norm.cdf(-m["distance_to_default"])), pd=m["pd"],
                credit_spread=m["credit_spread"])


def black_cox(V0, D, T, r, sigma_V, barrier=None) -> dict:
    """Black-Cox first-passage default: default the first time V hits `barrier`
    (default = D). PD via the reflection principle for drifted Brownian motion."""
    B = D if barrier is None else barrier
    sq = np.sqrt(T)
    mu = (r - 0.5 * sigma_V**2) / sigma_V          # drift of ln V / σ
    a = np.log(B / V0) / sigma_V                    # log-barrier (< 0)
    pd = norm.cdf((a - mu * T) / sq) + np.exp(2 * mu * a) * norm.cdf((a + mu * T) / sq)
    return dict(pd=float(min(max(pd, 0.0), 1.0)), barrier=float(B))
