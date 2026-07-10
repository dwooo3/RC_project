"""
Multi-asset options:
  - Exchange option (Margrabe)
  - Spread option (Kirk approximation + MC)
  - Basket option (MC)
  - Rainbow options: best-of, worst-of, N-asset
  - Quanto option
  - Outperformance option
  - Mountain range: Himalaya, Everest, Atlas, Altiplano
"""

import numpy as np
from scipy.stats import norm, multivariate_normal
from models.monte_carlo import multi_asset_paths


# ─────────────────────────────────────────────────────────
# Exchange option (Margrabe 1978)
# ─────────────────────────────────────────────────────────

def exchange_option(S1: float, S2: float, T: float, r: float,
                    sigma1: float, sigma2: float, rho: float,
                    q1: float = 0.0, q2: float = 0.0) -> dict:
    """Exchange option: right to exchange asset 2 for asset 1. Payoff: max(S1-S2, 0)."""
    sigma = np.sqrt(sigma1**2 + sigma2**2 - 2*rho*sigma1*sigma2)
    d1 = (np.log(S1/S2) + (q2-q1+0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    price = S1*np.exp(-q1*T)*norm.cdf(d1) - S2*np.exp(-q2*T)*norm.cdf(d2)
    delta1 = np.exp(-q1*T)*norm.cdf(d1)
    delta2 = -np.exp(-q2*T)*norm.cdf(d2)
    return dict(price=price, delta1=delta1, delta2=delta2, sigma_eff=sigma)


# ─────────────────────────────────────────────────────────
# Spread option (Kirk approximation)
# ─────────────────────────────────────────────────────────

def spread_option_kirk(S1: float, S2: float, K: float, T: float, r: float,
                       sigma1: float, sigma2: float, rho: float,
                       q1: float = 0.0, q2: float = 0.0) -> dict:
    """
    Spread option payoff: max(S1 - S2 - K, 0).
    Kirk (1995) approximation.
    """
    F1 = S1 * np.exp((r-q1)*T)
    F2 = S2 * np.exp((r-q2)*T)
    FK = F2 + K
    sigma = np.sqrt(sigma1**2 + sigma2**2*(F2/FK)**2
                    - 2*rho*sigma1*sigma2*(F2/FK))
    d1 = (np.log(F1/FK) + 0.5*sigma**2*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    disc = np.exp(-r*T)
    price = disc*(F1*norm.cdf(d1) - FK*norm.cdf(d2))
    return dict(price=max(price,0), sigma_eff=sigma)


def spread_option_mc(S1: float, S2: float, K: float, T: float, r: float,
                     sigma1: float, sigma2: float, rho: float,
                     q1: float = 0.0, q2: float = 0.0,
                     n_sims: int = 100_000, steps: int = 252, seed: int = 42) -> dict:
    """Spread option via MC."""
    S0   = np.array([S1, S2])
    sig  = np.array([sigma1, sigma2])
    q    = np.array([q1, q2])
    corr = np.array([[1.0, rho], [rho, 1.0]])
    paths = multi_asset_paths(S0, r, q, sig, corr, T, steps, n_sims, seed)
    S1_T, S2_T = paths[:, 0, -1], paths[:, 1, -1]
    pv   = np.exp(-r*T) * np.maximum(S1_T - S2_T - K, 0)
    return dict(price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims))


# ─────────────────────────────────────────────────────────
# Rainbow options
# ─────────────────────────────────────────────────────────

def best_of_assets_cash(assets: list, cash: float, T: float, r: float,
                        sigmas: list, corr_matrix: np.ndarray,
                        q_list: list = None) -> dict:
    """
    Best-of (n assets or cash): pays max(S1_T, S2_T, ..., Sn_T, cash).
    Stulz (1982) for n=2; MC for n>2.
    """
    n = len(assets)
    q_list = q_list or [0.0]*n
    if n == 2:
        return _best_of_2_cash(assets[0], assets[1], cash, T, r,
                                sigmas[0], sigmas[1], corr_matrix[0,1],
                                q_list[0], q_list[1])
    return _rainbow_mc(assets, cash, T, r, sigmas, corr_matrix, q_list, "best", n_sims=100_000)


def worst_of_assets(assets: list, T: float, r: float,
                    sigmas: list, corr_matrix: np.ndarray,
                    q_list: list = None) -> dict:
    """Worst-of: pays min(S1_T, ..., Sn_T). Useful for structured products."""
    n = len(assets); q_list = q_list or [0.0]*n
    return _rainbow_mc(assets, 0, T, r, sigmas, corr_matrix, q_list, "worst", n_sims=100_000)


def _best_of_2_cash(S1, S2, K, T, r, sig1, sig2, rho, q1=0.0, q2=0.0):
    """Stulz (1982) exact: max(S1, S2, K)."""
    sig = np.sqrt(sig1**2 + sig2**2 - 2*rho*sig1*sig2)
    d1  = (np.log(S1/S2) + 0.5*sig**2*T) / (sig*np.sqrt(T))
    rho1 = (sig1 - rho*sig2)/sig; rho2 = (sig2 - rho*sig1)/sig

    def M(a, b, r_): return multivariate_normal.cdf([a,b], cov=[[1,r_],[r_,1]])

    e1  = (np.log(S1/K) + (r-q1+sig1**2/2)*T)/(sig1*np.sqrt(T))
    e2  = (np.log(S2/K) + (r-q2+sig2**2/2)*T)/(sig2*np.sqrt(T))
    f1  = e1 - sig1*np.sqrt(T); f2 = e2 - sig2*np.sqrt(T)

    cmax = (S1*np.exp(-q1*T)*M(e1, d1, rho1)
            +S2*np.exp(-q2*T)*M(e2,-d1+sig*np.sqrt(T), rho2)
            -K*np.exp(-r*T)*(1 - multivariate_normal.cdf([-f1,-f2], cov=[[1,rho],[rho,1]])))
    # payoff = max(S1, S2, K) = K + (max(S1,S2) - K)+  =>  value = K*df + cmax.
    # 2026-07 fix: the K*df leg was missing -- the function returned only the
    # call-on-max and understated best-of-cash by ~K*df (found by the batch-5
    # MC==Stulz benchmark).
    price = K*np.exp(-r*T) + max(cmax, 0.0)
    return dict(price=price, call_on_max=max(cmax, 0.0), model="stulz_exact")


def _rainbow_mc(assets, cash, T, r, sigmas, corr, q_list, style, n_sims=100_000, seed=42):
    S0   = np.array(assets, dtype=float)
    sig  = np.array(sigmas, dtype=float)
    q    = np.array(q_list, dtype=float)
    paths = multi_asset_paths(S0, r, q, sig, np.array(corr), T, 252, n_sims, seed)
    S_T   = paths[:, :, -1]  # (n_sims, n_assets)
    if style == "best":
        payoff = np.maximum(S_T.max(axis=1), cash)
    else:
        payoff = S_T.min(axis=1)
    pv = np.exp(-r*T)*payoff
    return dict(price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims), style=style)


# ─────────────────────────────────────────────────────────
# Basket option
# ─────────────────────────────────────────────────────────

def basket_option(assets: list, weights: list, K: float, T: float, r: float,
                  sigmas: list, corr_matrix: np.ndarray, q_list: list = None,
                  opt: str = "call", method: str = "mc",
                  n_sims: int = 100_000, seed: int = 42) -> dict:
    """
    Basket option on weighted sum of assets.
    method: mc | moment_matching (lognormal approximation)
    """
    n      = len(assets); q_list = q_list or [0.0]*n
    S0     = np.array(assets, dtype=float)
    w      = np.array(weights, dtype=float); w /= w.sum()
    sig    = np.array(sigmas,  dtype=float)
    q      = np.array(q_list,  dtype=float)

    if method == "mc":
        paths  = multi_asset_paths(S0, r, q, sig, np.array(corr_matrix), T, 252, n_sims, seed)
        S_T    = paths[:, :, -1]
        basket = (w * S_T).sum(axis=1)
        sign   = 1 if opt == "call" else -1
        payoff = np.maximum(sign*(basket - K), 0)
        pv     = np.exp(-r*T) * payoff
        return dict(price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims), method="mc")

    else:  # moment matching (Levy 1992)
        F  = S0 * np.exp((r - q)*T)
        m1 = (w * F).sum()
        cov= np.array(corr_matrix) * np.outer(sig, sig)
        v  = 0
        for i in range(n):
            for j in range(n):
                v += w[i]*w[j]*F[i]*F[j]*np.exp(cov[i,j]*T)
        sigma_b = np.sqrt(np.log(v / m1**2))
        S_b     = m1 * np.exp(-0.5*sigma_b**2*T)
        from models.black_scholes import bsm
        g = bsm(S_b, K, T, r, sigma_b, 0, opt)
        return dict(price=g.price, delta=g.delta, sigma_basket=sigma_b, method="moment_matching")


# ─────────────────────────────────────────────────────────
# Quanto option
# ─────────────────────────────────────────────────────────

def quanto_option(S: float, K: float, T: float, r_d: float, r_f: float,
                  sigma_S: float, sigma_FX: float, rho_SFX: float,
                  q: float = 0.0, opt: str = "call",
                  FX_rate: float = 1.0) -> dict:
    """
    Quanto option: foreign asset, payoff in domestic currency at fixed FX rate.
    r_d, r_f: domestic/foreign rates.
    sigma_S: asset vol in foreign currency, sigma_FX: FX vol.
    rho_SFX: correlation between asset and FX.
    """
    from models.black_scholes import bsm
    q_adj = r_f - rho_SFX * sigma_S * sigma_FX  # quanto drift adjustment
    g = bsm(S, K, T, r_d, sigma_S, q_adj, opt)
    return dict(price=g.price * FX_rate, delta=g.delta * FX_rate,
                gamma=g.gamma * FX_rate, vega=g.vega * FX_rate,
                theta=g.theta * FX_rate, quanto_drift=q_adj)


# ─────────────────────────────────────────────────────────
# Mountain range: Himalaya
# ─────────────────────────────────────────────────────────

def himalaya(assets: list, T: float, r: float, sigmas: list,
             corr_matrix: np.ndarray, q_list: list = None,
             n_sims: int = 50_000, steps: int = 252, seed: int = 42) -> dict:
    """
    Himalaya option: at each sub-period, best performing asset is removed.
    Final payoff = average of the best performances, each measured at their period.
    """
    n      = len(assets); q_list = q_list or [0.0]*n
    S0     = np.array(assets, dtype=float)
    sig    = np.array(sigmas, dtype=float)
    q      = np.array(q_list, dtype=float)
    paths  = multi_asset_paths(S0, r, q, sig, np.array(corr_matrix), T, steps, n_sims, seed)

    period_steps = steps // n
    total_return = np.zeros(n_sims)
    active       = np.ones((n_sims, n), dtype=bool)

    for k in range(n):
        idx_end   = (k+1) * period_steps
        S_end     = paths[:, :, min(idx_end, steps)]
        rets      = np.where(active, S_end / S0, -np.inf)
        best_idx  = rets.argmax(axis=1)
        best_ret  = rets[np.arange(n_sims), best_idx]
        total_return += best_ret
        active[np.arange(n_sims), best_idx] = False

    payoff = np.maximum(total_return / n - 1, 0)
    pv     = np.exp(-r*T) * payoff
    return dict(price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims), n_assets=n)


def altiplano(assets: list, K_barrier: float, coupon: float, T: float, r: float,
              sigmas: list, corr_matrix: np.ndarray, q_list: list = None,
              n_sims: int = 50_000, steps: int = 252, seed: int = 42) -> dict:
    """
    Altiplano: pays full coupon if all assets stay above barrier, else basket payoff.
    """
    n = len(assets); q_list = q_list or [0.0]*n
    S0 = np.array(assets, dtype=float)
    paths = multi_asset_paths(S0, r, np.array(q_list), np.array(sigmas),
                              np.array(corr_matrix), T, steps, n_sims, seed)
    S_T      = paths[:, :, -1]
    min_path = paths.min(axis=2)       # min over time per asset
    all_above = (min_path / S0 > K_barrier).all(axis=1)  # relative barrier
    basket_ret = (S_T / S0).mean(axis=1) - 1
    payoff = np.where(all_above, coupon, np.maximum(basket_ret, 0))
    pv     = np.exp(-r*T) * payoff
    return dict(price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims))
