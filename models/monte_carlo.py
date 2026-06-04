"""
Monte Carlo engine with:
  - GBM (log-normal paths)
  - Heston stochastic volatility paths
  - Multi-asset correlated GBM
  - Variance reduction: antithetic, control variate, moment matching
  - Longstaff-Schwartz LSM for early exercise
"""

import numpy as np
from typing import Callable, Optional


# ─────────────────────────────────────────────────────────
# Path generators
# ─────────────────────────────────────────────────────────

def gbm_paths(S0: float, r: float, q: float, sigma: float,
              T: float, steps: int, n_sims: int,
              antithetic: bool = True,
              moment_match: bool = True,
              seed: Optional[int] = None) -> np.ndarray:
    """
    Geometric Brownian Motion paths.
    Returns array shape (n_sims, steps+1).
    """
    rng = np.random.default_rng(seed)
    # Ensure even number for antithetic pairing
    n   = (n_sims // 2) if antithetic else n_sims
    actual_sims = n * 2 if antithetic else n
    dt  = T / steps
    Z   = rng.standard_normal((n, steps))
    if moment_match:
        Z = (Z - Z.mean()) / Z.std()
    if antithetic:
        Z = np.vstack([Z, -Z])

    increments = (r - q - 0.5*sigma**2)*dt + sigma*np.sqrt(dt)*Z
    log_S = np.log(S0) + np.cumsum(increments, axis=1)
    S = np.empty((actual_sims, steps+1))
    S[:, 0] = S0
    S[:, 1:] = np.exp(log_S)
    return S


def heston_paths(S0: float, v0: float, r: float, q: float,
                 kappa: float, theta: float, xi: float, rho: float,
                 T: float, steps: int, n_sims: int,
                 antithetic: bool = True,
                 seed: Optional[int] = None) -> tuple:
    """
    Heston stochastic vol paths using Euler-Maruyama with reflection.
    Returns (S_paths, v_paths) each shape (n_sims, steps+1).
    """
    rng  = np.random.default_rng(seed)
    dt   = T / steps
    n    = n_sims // 2 if antithetic else n_sims

    Z1 = rng.standard_normal((n, steps))
    Z2 = rho*Z1 + np.sqrt(1 - rho**2)*rng.standard_normal((n, steps))
    if antithetic:
        Z1 = np.vstack([Z1, -Z1])
        Z2 = np.vstack([Z2, -Z2])

    S = np.empty((n_sims, steps+1)); S[:, 0] = S0
    v = np.empty((n_sims, steps+1)); v[:, 0] = v0

    for i in range(steps):
        v_pos = np.maximum(v[:, i], 0)
        sv    = np.sqrt(v_pos)
        v[:, i+1] = np.abs(v[:, i] + kappa*(theta - v_pos)*dt + xi*sv*np.sqrt(dt)*Z2[:, i])
        S[:, i+1] = S[:, i] * np.exp((r - q - 0.5*v_pos)*dt + sv*np.sqrt(dt)*Z1[:, i])

    return S, v


def multi_asset_paths(S0: np.ndarray, r: float, q: np.ndarray,
                      sigma: np.ndarray, corr: np.ndarray,
                      T: float, steps: int, n_sims: int,
                      seed: Optional[int] = None) -> np.ndarray:
    """
    Correlated multi-asset GBM.
    Returns shape (n_sims, n_assets, steps+1).
    """
    rng  = np.random.default_rng(seed)
    n_a  = len(S0)
    dt   = T / steps
    L    = np.linalg.cholesky(corr)
    Z    = rng.standard_normal((n_sims, steps, n_a)) @ L.T

    paths = np.empty((n_sims, n_a, steps+1))
    paths[:, :, 0] = S0
    for i in range(steps):
        drift = (r - q - 0.5*sigma**2)*dt
        diff  = sigma * np.sqrt(dt) * Z[:, i, :]
        paths[:, :, i+1] = paths[:, :, i] * np.exp(drift + diff)
    return paths


# ─────────────────────────────────────────────────────────
# Generic MC pricer (single-asset)
# ─────────────────────────────────────────────────────────

def mc_price(payoff_fn: Callable[[np.ndarray], np.ndarray],
             S0: float, r: float, q: float, sigma: float,
             T: float, steps: int = 252, n_sims: int = 100_000,
             antithetic: bool = True,
             moment_match: bool = True,
             control_variate: bool = False,
             seed: int = 42) -> dict:
    """
    Price any path-dependent payoff via Monte Carlo.
    payoff_fn: (paths array n_sims×(steps+1)) → payoff array (n_sims,)
    """
    paths = gbm_paths(S0, r, q, sigma, T, steps, n_sims,
                      antithetic, moment_match, seed)
    disc  = np.exp(-r * T)
    pv    = disc * payoff_fn(paths)

    if control_variate:
        S_T      = paths[:, -1]
        # Control variate is the discounted terminal spot disc*S_T, whose known
        # expectation is E[disc*S_T] = S0*e^{-qT} (a martingale up to dividends).
        # Was S0*e^{(r-q)T} = E[S_T] (undiscounted), which left the CV uncentred
        # and biased the price by ~beta*S0*(e^{(r-q)T}-e^{-qT}).
        cv_true  = S0 * np.exp(-q*T)
        beta     = np.cov(pv, disc*S_T)[0,1] / np.var(disc*S_T)
        pv       = pv - beta*(disc*S_T - cv_true)

    price = pv.mean()
    stderr = pv.std() / np.sqrt(n_sims)
    ci95   = (price - 1.96*stderr, price + 1.96*stderr)

    # bump Greeks
    eps = S0 * 0.005
    def _p(S_):
        pt = gbm_paths(S_, r, q, sigma, T, steps, n_sims, antithetic, moment_match, seed)
        return np.exp(-r*T) * payoff_fn(pt).mean()

    delta = (_p(S0+eps) - _p(S0-eps)) / (2*eps)
    gamma = (_p(S0+eps) - 2*price + _p(S0-eps)) / eps**2

    dv  = 0.001
    vp  = gbm_paths(S0, r, q, sigma+dv, T, steps, n_sims, antithetic, moment_match, seed)
    vm  = gbm_paths(S0, r, q, sigma-dv, T, steps, n_sims, antithetic, moment_match, seed)
    vega = (np.exp(-r*T)*payoff_fn(vp).mean() - np.exp(-r*T)*payoff_fn(vm).mean()) / (2*dv*100)

    return dict(price=price, stderr=stderr, ci95=ci95,
                delta=delta, gamma=gamma, vega=vega, n_sims=n_sims)


# ─────────────────────────────────────────────────────────
# Longstaff-Schwartz LSM (American/Bermudan)
# ─────────────────────────────────────────────────────────

def _lsm_price_only(S0, K, T, r, sigma, q, n_sims, steps,
                    opt, exercise_dates, basis_degree, seed) -> float:
    """Price-only LSM — used for bump-and-reprice Greeks (no recursion)."""
    paths = gbm_paths(S0, r, q, sigma, T, steps, n_sims, seed=seed)
    dt    = T / steps
    disc  = np.exp(-r * dt)

    if exercise_dates is not None:
        ex_steps = sorted({int(round(t / dt)) for t in exercise_dates if t <= T})
    else:
        ex_steps = list(range(1, steps + 1))

    intrinsic_fn = (lambda S: np.maximum(S - K, 0)) if opt == "call" \
                   else (lambda S: np.maximum(K - S, 0))

    cf    = intrinsic_fn(paths[:, -1])
    pv_cf = cf.copy()

    for i in range(steps - 1, 0, -1):
        pv_cf *= disc
        if i not in ex_steps:
            continue
        S_i = paths[:, i]
        iv  = intrinsic_fn(S_i)
        itm = iv > 0
        if itm.sum() < 10:
            continue
        X      = S_i[itm]
        Y      = pv_cf[itm]
        coeffs = np.polyfit(X, Y, basis_degree)
        cont   = np.polyval(coeffs, X)
        pv_cf[itm] = np.where(iv[itm] >= cont, iv[itm], pv_cf[itm])

    pv_cf *= disc
    return float(pv_cf.mean())


def lsm(S0: float, K: float, T: float, r: float, sigma: float,
        q: float = 0.0, n_sims: int = 50_000, steps: int = 252,
        opt: str = "call", exercise_dates: Optional[list] = None,
        basis_degree: int = 3, seed: int = 42) -> dict:
    """
    Longstaff-Schwartz Monte Carlo for American/Bermudan options.
    exercise_dates: list of exercise times in years (None = American = daily).
    """
    paths = gbm_paths(S0, r, q, sigma, T, steps, n_sims, seed=seed)
    dt    = T / steps
    disc  = np.exp(-r * dt)

    if exercise_dates is not None:
        ex_steps = sorted({int(round(t / dt)) for t in exercise_dates if t <= T})
    else:
        ex_steps = list(range(1, steps + 1))  # American: every step

    if opt == "call":
        intrinsic_fn = lambda S: np.maximum(S - K, 0)
    else:
        intrinsic_fn = lambda S: np.maximum(K - S, 0)

    # cashflows: initialise at expiry
    cf = intrinsic_fn(paths[:, -1])
    # discount cashflows backward
    pv_cf = cf.copy()

    for i in range(steps - 1, 0, -1):
        pv_cf *= disc
        if i not in ex_steps:
            continue
        S_i = paths[:, i]
        iv  = intrinsic_fn(S_i)
        itm = iv > 0
        if itm.sum() < 10:
            continue
        X   = S_i[itm]
        Y   = pv_cf[itm]
        # polynomial regression for continuation value
        coeffs = np.polyfit(X, Y, basis_degree)
        cont   = np.polyval(coeffs, X)
        exercise = iv[itm] >= cont
        pv_cf[itm] = np.where(exercise, iv[itm], pv_cf[itm])

    pv_cf *= disc  # discount from step 1 to 0
    price  = pv_cf.mean()
    stderr = pv_cf.std() / np.sqrt(n_sims)

    # Greeks via bump-and-reprice using price-only helper (no recursion)
    eps   = max(S0 * 0.005, 0.01)
    pu    = _lsm_price_only(S0+eps, K, T, r, sigma, q, n_sims, steps, opt, exercise_dates, basis_degree, seed)
    pd    = _lsm_price_only(S0-eps, K, T, r, sigma, q, n_sims, steps, opt, exercise_dates, basis_degree, seed)
    delta = (pu - pd) / (2 * eps)
    gamma = (pu - 2 * price + pd) / eps**2

    return dict(price=price, stderr=stderr, delta=delta, gamma=gamma)


# ─────────────────────────────────────────────────────────
# Heston MC pricer
# ─────────────────────────────────────────────────────────

def heston_mc_price(payoff_fn: Callable,
                    S0: float, v0: float, r: float, q: float,
                    kappa: float, theta: float, xi: float, rho: float,
                    T: float, steps: int = 252, n_sims: int = 50_000,
                    seed: int = 42) -> dict:
    """MC pricer under Heston model."""
    paths, _ = heston_paths(S0, v0, r, q, kappa, theta, xi, rho,
                             T, steps, n_sims, seed=seed)
    disc  = np.exp(-r * T)
    pv    = disc * payoff_fn(paths)
    price = pv.mean()
    stderr = pv.std() / np.sqrt(n_sims)
    return dict(price=price, stderr=stderr, n_sims=n_sims)
