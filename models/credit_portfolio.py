"""
Portfolio credit risk — one-factor Gaussian copula, Master-plan M7.

Each name defaults by T when its latent variable X_i = √ρ·Z + √(1-ρ)·ε_i falls
below c_i = N⁻¹(p_i); conditional on the common factor Z the names are
independent with PD_i(Z) = N((c_i - √ρ·Z)/√(1-ρ)). Integrating the conditional
number-of-defaults distribution (built by an exact recursion) over Z gives the
portfolio loss distribution semi-analytically — the market-standard engine for
basket (kth-to-default) and CDO-tranche pricing.

Validated: portfolio expected loss is correlation-independent (= mean PD·LGD);
tranche expected losses across a full partition sum back to it; the recursion
agrees with a Monte-Carlo copula and (large pool) with the LHP closed form;
first-to-default probability falls and senior-tranche loss rises with
correlation (the credit-correlation skew).
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm


def _z_grid(n_z=400, width=6.0):
    z = np.linspace(-width, width, n_z)
    w = norm.pdf(z)
    w /= w.sum()
    return z, w


def conditional_pd(pds, rho, z):
    """Per-name default probability conditional on the systematic factor z."""
    c = norm.ppf(np.asarray(pds, float))
    return norm.cdf((c - np.sqrt(rho) * z) / np.sqrt(1 - rho))


def default_distribution(pds, rho, n_z=400):
    """P(exactly k defaults by T), k=0..n, one-factor Gaussian copula."""
    pds = np.asarray(pds, float)
    n = len(pds)
    z, wz = _z_grid(n_z)
    dist = np.zeros(n + 1)
    for zi, wi in zip(z, wz):
        pz = conditional_pd(pds, rho, zi)
        d = np.zeros(n + 1)
        d[0] = 1.0
        for pi in pz:                                  # exact recursion over names
            d[1:] = d[1:] * (1 - pi) + d[:-1] * pi
            d[0] = d[0] * (1 - pi)
        dist += wi * d
    return dist


def kth_to_default_prob(pds, rho, k=1, n_z=400):
    """P(at least k defaults by T)."""
    dist = default_distribution(pds, rho, n_z)
    return float(dist[k:].sum())


def portfolio_expected_loss(pds, rho=0.0, recovery=0.4, n_z=400):
    """E[L] as a fraction of pool notional (correlation-independent)."""
    dist = default_distribution(pds, rho, n_z)
    n = len(pds)
    k = np.arange(n + 1)
    return float((dist * k).sum() / n * (1 - recovery))


def cdo_tranche(pds, rho, K1, K2, recovery=0.4, n_z=400) -> dict:
    """Expected loss of the [K1,K2] tranche (fraction of tranche notional)."""
    dist = default_distribution(pds, rho, n_z)
    n = len(pds)
    loss = np.arange(n + 1) / n * (1 - recovery)        # pool loss for k defaults
    tranche_loss = np.clip(loss - K1, 0.0, K2 - K1)
    etl = float((dist * tranche_loss).sum() / (K2 - K1))
    return dict(expected_tranche_loss=etl, attachment=K1, detachment=K2,
                pool_el=float((dist * loss).sum()))


def basket_mc(pds, rho, k=1, recovery=0.4, n_sims=200_000, seed=0) -> dict:
    """Monte-Carlo one-factor copula cross-check: kth-to-default prob + pool EL."""
    pds = np.asarray(pds, float)
    n = len(pds)
    c = norm.ppf(pds)
    rng = np.random.default_rng(seed)
    Z = rng.standard_normal((n_sims, 1))
    eps = rng.standard_normal((n_sims, n))
    X = np.sqrt(rho) * Z + np.sqrt(1 - rho) * eps
    defaults = (X < c).sum(axis=1)
    return dict(kth_prob=float((defaults >= k).mean()),
                pool_el=float((defaults / n * (1 - recovery)).mean()))


# ── alternative copulas (t / Clayton), gap-closing batch 3 ──────────

def basket_mc_t(pds, rho, df=5, k=1, recovery=0.4, n_sims=200_000, seed=0) -> dict:
    """One-factor Student-t copula MC. As df→∞ it recovers the Gaussian copula:
    X_i = (√ρ·Z + √(1-ρ)·ε_i)·√(df/W), W~χ²(df) shared; default if X_i < t_df⁻¹(p_i)."""
    from scipy.stats import t as student_t, chi2
    pds = np.asarray(pds, float)
    n = len(pds)
    c = student_t.ppf(pds, df)
    rng = np.random.default_rng(seed)
    Z = rng.standard_normal((n_sims, 1))
    eps = rng.standard_normal((n_sims, n))
    W = chi2.rvs(df, size=(n_sims, 1), random_state=rng)
    Y = np.sqrt(rho) * Z + np.sqrt(1 - rho) * eps
    X = Y * np.sqrt(df / W)
    defaults = (X < c).sum(axis=1)
    return dict(kth_prob=float((defaults >= k).mean()),
                pool_el=float((defaults.mean() / n) * (1 - recovery)),
                mean_defaults=float(defaults.mean()))


def basket_mc_clayton(pds, theta=1.0, k=1, recovery=0.4, n_sims=200_000, seed=0) -> dict:
    """Clayton copula MC via Gamma frailty (Marshall-Olkin): V~Gamma(1/θ,1),
    U_i = (1 + E_i/V)^{-1/θ}, default if U_i < p_i. Lower-tail dependence
    λ_L = 2^{-1/θ} > 0 → default clustering the Gaussian copula misses."""
    pds = np.asarray(pds, float)
    n = len(pds)
    rng = np.random.default_rng(seed)
    V = rng.gamma(1.0 / theta, 1.0, size=(n_sims, 1))
    E = rng.exponential(1.0, size=(n_sims, n))
    U = (1 + E / V) ** (-1.0 / theta)
    defaults = (U < pds).sum(axis=1)
    return dict(kth_prob=float((defaults >= k).mean()),
                pool_el=float((defaults.mean() / n) * (1 - recovery)),
                mean_defaults=float(defaults.mean()))
