"""
Variance and volatility products:
  - Variance swap (fair variance strike, P&L)
  - Volatility swap (Brockhaus-Long approximation + MC)
  - Gamma swap
  - Corridor variance swap
  - Conditional variance swap
  - VIX-style replication (log-contract)
"""

import numpy as np
from models.monte_carlo import gbm_paths


# ─────────────────────────────────────────────────────────
# Variance swap
# ─────────────────────────────────────────────────────────

def variance_swap_fair_strike(r: float, q: float, T: float,
                               puts: list, calls: list,
                               S0: float, F: float = None) -> dict:
    """
    Model-free fair variance strike via log-contract replication.
    puts:  list of (K, price) for OTM puts (K < F)
    calls: list of (K, price) for OTM calls (K > F)
    Demeterfi et al. (1999) formula.
    """
    F = F or S0 * np.exp((r-q)*T)

    def integral_part(options, F_, above):
        if not options:
            return 0.0
        options = sorted(options, key=lambda x: x[0])
        total = 0.0
        for i, (K, P) in enumerate(options):
            if i == 0:
                dK = options[1][0] - K if len(options) > 1 else K*0.01
            elif i == len(options)-1:
                dK = K - options[-2][0]
            else:
                dK = (options[i+1][0] - options[i-1][0]) / 2
            # Log-contract replication uses a pure 1/K^2 weight per strike strip.
            # The previous (1 - log(K/F)) factor double-counted the log-contract
            # correction (already carried by the leading term below) and produced
            # a systematic ~1% overestimate of the fair variance strike that did
            # not vanish under grid refinement. See Demeterfi et al. (1999).
            total += 2/T * P * dK / K**2
        return total

    var_strike = (2/T * (np.log(F/S0) - (F/S0 - 1))
                  + integral_part(puts,  F, False)
                  + integral_part(calls, F, True))
    vol_strike = np.sqrt(var_strike)
    return dict(variance_strike=var_strike, vol_strike=vol_strike,
                fair_variance=var_strike * T)


def variance_swap_pnl(realized_var: float, var_strike: float,
                      notional: float, vega_notional: float = None) -> dict:
    """
    P&L of variance swap position.
    notional:       vega notional (in vol points)
    vega_notional:  if given, converts to standard vega notional.
    """
    if vega_notional is not None:
        notional_var = vega_notional / (2 * np.sqrt(var_strike))
    else:
        notional_var = notional
    pnl = notional_var * (realized_var - var_strike)
    return dict(pnl=pnl, realized_var=realized_var, var_strike=var_strike,
                notional_var=notional_var)


def realized_variance(prices: np.ndarray, annualize: bool = True,
                      trading_days: int = 252) -> float:
    """Compute realized variance from price series."""
    log_returns = np.diff(np.log(prices))
    rv = np.sum(log_returns**2)
    if annualize:
        rv *= trading_days / len(log_returns)
    return rv


# ─────────────────────────────────────────────────────────
# Volatility swap
# ─────────────────────────────────────────────────────────

def vol_swap_brockhaus_long(sigma: float, T: float, convexity: float = None) -> dict:
    """
    Vol swap approximation: E[sqrt(V)] ≈ sqrt(K_var) - Convexity/(8*K_var^(3/2))
    where Convexity = Var(V) = variance of realized variance.
    """
    var_strike = sigma**2
    if convexity is None:
        # rough estimate: convexity ~ 2*var_strike^2 * T (heuristic)
        convexity = 2 * var_strike**2 * T
    vol_strike = np.sqrt(var_strike) - convexity / (8 * var_strike**1.5)
    return dict(vol_strike=vol_strike, var_strike=var_strike, convexity=convexity)


def vol_swap_mc(S: float, r: float, q: float, sigma: float, T: float,
                n_sims: int = 50_000, steps: int = 252, seed: int = 42) -> dict:
    """Vol swap fair strike via MC (realized vol distribution)."""
    paths = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)
    log_ret = np.diff(np.log(paths), axis=1)
    rv_ann  = np.sqrt(np.sum(log_ret**2, axis=1) * 252 / steps)
    vol_strike = rv_ann.mean()
    std_rv     = rv_ann.std()
    return dict(vol_strike=vol_strike, std_realized_vol=std_rv,
                ci95=(vol_strike - 1.96*std_rv/np.sqrt(n_sims),
                      vol_strike + 1.96*std_rv/np.sqrt(n_sims)))


# ─────────────────────────────────────────────────────────
# Gamma swap
# ─────────────────────────────────────────────────────────

def gamma_swap_fair_strike(S0: float, r: float, q: float, sigma: float, T: float,
                            puts: list = None, calls: list = None) -> dict:
    """
    Gamma swap: weighted variance swap where each day's variance is weighted by S_t/S_0.
    Fair strike via log-contract replication (same as var swap but kernel changes).
    Model: K_gamma = sigma^2 (for simple GBM — equals implied var).
    """
    # Under GBM: E[int_0^T S_t/S_0 dV_t] = sigma^2 * T (analytic)
    gamma_strike = sigma**2
    return dict(gamma_strike=gamma_strike, vol_equiv=sigma)


# ─────────────────────────────────────────────────────────
# Corridor / conditional variance swap
# ─────────────────────────────────────────────────────────

def corridor_variance_swap(S: float, r: float, q: float, sigma: float, T: float,
                            L: float, U: float,
                            n_sims: int = 100_000, steps: int = 252, seed: int = 42) -> dict:
    """
    Corridor variance swap: only counts realized variance when L < S_t < U.
    """
    paths   = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)
    log_ret = np.diff(np.log(paths), axis=1)
    in_corr = (paths[:, :-1] >= L) & (paths[:, :-1] <= U)
    rv_corr = (in_corr * log_ret**2).sum(axis=1) * 252 / steps
    strike  = rv_corr.mean()
    return dict(corridor_var_strike=strike, corridor_vol=np.sqrt(strike),
                lower=L, upper=U, pct_time_in=in_corr.mean())


def conditional_variance_swap(S: float, r: float, q: float, sigma: float, T: float,
                               L: float, U: float,
                               n_sims: int = 100_000, steps: int = 252, seed: int = 42) -> dict:
    """
    Conditional variance swap: realized variance conditional on being in [L, U].
    = corridor var / fraction of time in corridor.
    """
    paths   = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)
    log_ret = np.diff(np.log(paths), axis=1)
    in_corr = (paths[:, :-1] >= L) & (paths[:, :-1] <= U)
    days_in = in_corr.sum(axis=1)
    rv_cond = np.where(days_in > 0,
                       (in_corr * log_ret**2).sum(axis=1) / days_in * 252,
                       0.0)
    strike = rv_cond[days_in > 0].mean() if (days_in > 0).any() else 0.0
    return dict(conditional_var_strike=strike, conditional_vol=np.sqrt(max(strike,0)),
                lower=L, upper=U, avg_pct_in=in_corr.mean())
