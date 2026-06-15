"""
Analytic American-option approximations, Master-plan M6.

Closed-form (or near-closed-form) approximations that avoid a lattice/PDE solve:

* **Barone-Adesi-Whaley (1987)** — the quadratic approximation: American value =
  European value + an early-exercise premium term A·(S/S*)^q built from the
  critical exercise price S*.
* **Bjerksund-Stensland (1993)** — a flat-exercise-boundary approximation via the
  φ/ψ machinery; the put is obtained from the McDonald-Schroder put-call
  transformation.

Both reduce to the European price when early exercise is never optimal
(a call with cost-of-carry b ≥ r, i.e. non-positive dividend), bracket it from
above (premium ≥ 0), and are validated against the binomial American reference.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq


def gbs(S, K, T, r, sigma, b, opt="call") -> float:
    """Generalised Black-Scholes with cost-of-carry b (b=r-q)."""
    sq = sigma * np.sqrt(T)
    d1 = (np.log(S / K) + (b + 0.5 * sigma**2) * T) / sq
    d2 = d1 - sq
    if opt == "call":
        return S * np.exp((b - r) * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp((b - r) * T) * norm.cdf(-d1)


# ── Barone-Adesi-Whaley ──────────────────────────────────────

def baw(S, K, T, r, sigma, q=0.0, opt="call") -> float:
    b = r - q
    if opt == "call" and b >= r:                       # no early exercise
        return gbs(S, K, T, r, sigma, b, "call")
    M = 2 * r / sigma**2
    Nn = 2 * b / sigma**2
    KT = 1.0 - np.exp(-r * T)
    sq = sigma * np.sqrt(T)

    def d1(Sx):
        return (np.log(Sx / K) + (b + 0.5 * sigma**2) * T) / sq

    if opt == "call":
        q2 = (-(Nn - 1) + np.sqrt((Nn - 1)**2 + 4 * M / KT)) / 2

        def f(Sx):
            return (Sx - K - gbs(Sx, K, T, r, sigma, b, "call")
                    - (1 - np.exp((b - r) * T) * norm.cdf(d1(Sx))) * Sx / q2)

        S_star = brentq(f, K, 50 * K, xtol=1e-8)
        if S >= S_star:
            return S - K
        A2 = (S_star / q2) * (1 - np.exp((b - r) * T) * norm.cdf(d1(S_star)))
        return gbs(S, K, T, r, sigma, b, "call") + A2 * (S / S_star)**q2

    q1 = (-(Nn - 1) - np.sqrt((Nn - 1)**2 + 4 * M / KT)) / 2

    def fp(Sx):
        return (K - Sx - gbs(Sx, K, T, r, sigma, b, "put")
                + (1 - np.exp((b - r) * T) * norm.cdf(-d1(Sx))) * Sx / q1)

    S_dstar = brentq(fp, 1e-6, K, xtol=1e-8)
    if S <= S_dstar:
        return K - S
    A1 = -(S_dstar / q1) * (1 - np.exp((b - r) * T) * norm.cdf(-d1(S_dstar)))
    return gbs(S, K, T, r, sigma, b, "put") + A1 * (S / S_dstar)**q1


# ── Bjerksund-Stensland 1993 ─────────────────────────────────

def _phi(S, T, gamma, H, X, r, b, sigma):
    sq = sigma * np.sqrt(T)
    lam = -r + gamma * b + 0.5 * gamma * (gamma - 1) * sigma**2
    kappa = 2 * b / sigma**2 + (2 * gamma - 1)
    d = -(np.log(S / H) + (b + (gamma - 0.5) * sigma**2) * T) / sq
    return (np.exp(lam * T) * S**gamma
            * (norm.cdf(d) - (X / S)**kappa * norm.cdf(d - 2 * np.log(X / S) / sq)))


def _bs93_call(S, K, T, r, sigma, b) -> float:
    if b >= r:
        return gbs(S, K, T, r, sigma, b, "call")
    beta = (0.5 - b / sigma**2) + np.sqrt((b / sigma**2 - 0.5)**2 + 2 * r / sigma**2)
    B_inf = beta / (beta - 1) * K
    B0 = max(K, r / (r - b) * K)
    h = -(b * T + 2 * sigma * np.sqrt(T)) * B0 / (B_inf - B0)
    X = B0 + (B_inf - B0) * (1 - np.exp(h))
    if S >= X:
        return S - K
    alpha = (X - K) * X**(-beta)
    return (alpha * S**beta
            - alpha * _phi(S, T, beta, X, X, r, b, sigma)
            + _phi(S, T, 1.0, X, X, r, b, sigma)
            - _phi(S, T, 1.0, K, X, r, b, sigma)
            - K * _phi(S, T, 0.0, X, X, r, b, sigma)
            + K * _phi(S, T, 0.0, K, X, r, b, sigma))


def bjerksund_stensland(S, K, T, r, sigma, q=0.0, opt="call") -> float:
    b = r - q
    if opt == "call":
        return _bs93_call(S, K, T, r, sigma, b)
    # McDonald-Schroder put-call transformation: P(S,K,r,b) = C(K,S,r-b,-b)
    return _bs93_call(K, S, T, r - b, sigma, -b)
