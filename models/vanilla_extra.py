"""
Vanilla / volatility analytic extensions, gap-closing batch 1.

Closed-form pricers that fill the "vanilla formulas" and "numerical methods"
gaps of the model catalogue:

* displaced diffusion (shifted lognormal) — interpolates normal↔lognormal
* CEV (constant elasticity of variance, Schroder noncentral-χ²) — skew
* discrete-dividend BSM (escrowed-dividend adjustment)
* Jarrow-Rudd and Tian binomial trees — equal-probability / moment-matched
* lognormal-vol mixture — a convex blend of BSM prices (produces a smile)

Every one reduces to Black-Scholes in its natural limit (zero shift, β=1, no
dividends, large N, single mixture component) — the validation anchors.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import ncx2

from models.black_scholes import bsm, black76


def displaced_diffusion(F, K, T, r, sigma, shift=0.0, opt="call") -> float:
    """Shifted-lognormal (displaced diffusion): Black-76 on (F+shift, K+shift)."""
    return black76(F + shift, K + shift, T, r, sigma, opt).price


def cev_price(S, K, T, r, sigma, beta=1.0, q=0.0, opt="call") -> float:
    """CEV option (Schroder 1989) via the noncentral chi-square. β=1 → BSM."""
    if abs(beta - 1.0) < 1e-9:
        return bsm(S, K, T, r, sigma, q, opt).price
    b = r - q
    one_m = 1.0 - beta
    if abs(b) < 1e-12:
        kk = 1.0 / (sigma**2 * one_m**2 * T)
        x = kk * S ** (2 * one_m)
        y = kk * K ** (2 * one_m)
    else:
        ex = np.exp(2 * b * one_m * T)
        kk = 2 * b / (sigma**2 * one_m * (ex - 1))
        x = kk * S ** (2 * one_m) * ex
        y = kk * K ** (2 * one_m)
    z = 2 + 1.0 / one_m
    df_S, df_K = np.exp(-q * T) * S, np.exp(-r * T) * K
    if beta < 1.0:
        call = df_S * (1 - ncx2.cdf(2 * y, z, 2 * x)) - df_K * ncx2.cdf(2 * x, z - 2, 2 * y)
    else:                                              # β>1 (rare): roles swap
        call = df_S * (1 - ncx2.cdf(2 * x, -z + 2, 2 * y)) - df_K * ncx2.cdf(2 * y, -z + 4, 2 * x)
    if opt == "call":
        return float(call)
    return float(call - df_S + df_K)                  # put-call parity


def discrete_dividend_bsm(S, K, T, r, sigma, dividends, opt="call") -> float:
    """Escrowed-dividend BSM: subtract the PV of cash dividends from spot.
    dividends: list of (t, amount)."""
    pv = sum(d * np.exp(-r * t) for t, d in dividends if 0 < t <= T)
    return bsm(S - pv, K, T, r, sigma, 0.0, opt).price


def _binomial(S, K, T, r, sigma, q, opt, N, u, d, p, exercise="european") -> float:
    disc = np.exp(-r * T / N)
    j = np.arange(N + 1)
    ST = S * u ** (N - j) * d ** j
    V = np.maximum((ST - K) if opt == "call" else (K - ST), 0.0)
    for i in range(N - 1, -1, -1):
        V = disc * (p * V[:-1] + (1 - p) * V[1:])
        if exercise == "american":
            Si = S * u ** (i - np.arange(i + 1)) * d ** np.arange(i + 1)
            V = np.maximum(V, (Si - K) if opt == "call" else (K - Si))
    return float(V[0])


def binomial_jarrow_rudd(S, K, T, r, sigma, q=0.0, opt="call", N=500,
                         exercise="european") -> float:
    """Jarrow-Rudd equal-probability tree (p=½)."""
    dt = T / N
    nu = r - q - 0.5 * sigma**2
    u = np.exp(nu * dt + sigma * np.sqrt(dt))
    d = np.exp(nu * dt - sigma * np.sqrt(dt))
    return _binomial(S, K, T, r, sigma, q, opt, N, u, d, 0.5, exercise)


def binomial_tian(S, K, T, r, sigma, q=0.0, opt="call", N=500,
                  exercise="european") -> float:
    """Tian moment-matching tree (matches the first three moments)."""
    dt = T / N
    M = np.exp((r - q) * dt)
    V = np.exp(sigma**2 * dt)
    u = 0.5 * M * V * (V + 1 + np.sqrt(V**2 + 2 * V - 3))
    d = 0.5 * M * V * (V + 1 - np.sqrt(V**2 + 2 * V - 3))
    p = (M - d) / (u - d)
    return _binomial(S, K, T, r, sigma, q, opt, N, u, d, p, exercise)


def mixture_price(S, K, T, r, sigma_list, weights, q=0.0, opt="call") -> float:
    """Lognormal-vol mixture: Σ wᵢ·BSM(σᵢ). Weights need not sum to 1 (normalised)."""
    w = np.asarray(weights, float)
    w = w / w.sum()
    return float(sum(wi * bsm(S, K, T, r, si, q, opt).price
                     for wi, si in zip(w, sigma_list)))
