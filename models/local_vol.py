"""
Local volatility Monte Carlo (Phase 3).

Tabulates the Dupire local vol (risk.vol_surface.dupire_local_vol) onto a
(spot, time) grid once, then runs a vectorized log-Euler MC with bilinear
lookup — the scalar Dupire callable is far too slow to evaluate per path-step.
Flat implied surface => flat local vol => exact BSM agreement (identity test).
"""

import numpy as np
from scipy.interpolate import RegularGridInterpolator


def tabulate_local_vol(vol_surface, S0: float, r: float, q: float, T: float,
                       n_s: int = 80, n_t: int = 40,
                       s_lo: float = 0.3, s_hi: float = 3.0):
    """
    Sample Dupire local vol on a log-spaced spot grid × time grid.
    Returns a vectorized callable lv(S_array, t) -> vol array.
    """
    from risk.vol_surface import dupire_local_vol

    lv_scalar = dupire_local_vol(vol_surface, S0, r, q)
    s_grid = S0 * np.exp(np.linspace(np.log(s_lo), np.log(s_hi), n_s))
    t_grid = np.linspace(0.01, max(T, 0.02), n_t)
    table = np.array([[lv_scalar(s, t) for t in t_grid] for s in s_grid])
    interp = RegularGridInterpolator((s_grid, t_grid), table,
                                     bounds_error=False, fill_value=None)

    def lv(S_arr, t):
        S_arr = np.clip(np.asarray(S_arr, dtype=float), s_grid[0], s_grid[-1])
        t_c = float(np.clip(t, t_grid[0], t_grid[-1]))
        pts = np.column_stack([S_arr, np.full_like(S_arr, t_c)])
        return np.maximum(interp(pts), 1e-4)

    return lv


def local_vol_mc(payoff_fn, S0: float, r: float, q: float, lv, T: float,
                 steps: int = 100, n_sims: int = 50_000,
                 seed: int = 42, antithetic: bool = True) -> dict:
    """
    Log-Euler MC under dS/S = (r-q)dt + sigma_loc(S,t) dW.
    lv: vectorized callable lv(S_array, t) -> vol array (see tabulate_local_vol).
    payoff_fn: paths (n_sims, steps+1) -> payoff array.
    """
    rng = np.random.default_rng(seed)
    dt = T / steps
    n = n_sims // 2 if antithetic else n_sims
    Z = rng.standard_normal((n, steps))
    if antithetic:
        Z = np.vstack([Z, -Z])
    n_eff = Z.shape[0]

    S = np.empty((n_eff, steps + 1))
    S[:, 0] = S0
    for i in range(steps):
        sig = lv(S[:, i], i * dt)
        S[:, i + 1] = S[:, i] * np.exp((r - q - 0.5 * sig**2) * dt
                                       + sig * np.sqrt(dt) * Z[:, i])
    pv = np.exp(-r * T) * payoff_fn(S)
    return dict(price=pv.mean(), stderr=pv.std() / np.sqrt(n_eff),
                n_sims=n_eff, model="local_vol_mc")
