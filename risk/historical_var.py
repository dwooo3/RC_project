"""
Historical simulation VaR (Hull Ch. 22):
  - Basic historical simulation
  - Age-weighted (BRW — Boudoukh, Richardson, Whitelaw)
  - Volatility-scaled (filtered historical simulation — Hull-White approach)
  - Component VaR and marginal VaR
  - PCA-based VaR
  - Expected shortfall / CVaR
  - Full backtest suite
"""

import numpy as np
from scipy.stats import norm

from risk.var import (
    _as_finite_1d,
    _loss_var_es,
    _validate_confidence,
    _validate_horizon,
)


# ─────────────────────────────────────────────────────────
# Basic historical simulation
# ─────────────────────────────────────────────────────────

def hs_var(pnl: np.ndarray, confidence: float = 0.95,
           horizon: int = 1) -> dict:
    """
    Historical simulation VaR and CVaR.
    pnl: daily P&L series (negative = loss).
    """
    confidence = _validate_confidence(confidence)
    horizon = _validate_horizon(horizon)
    pnl = _as_finite_1d(pnl, "pnl")
    losses = -pnl * np.sqrt(horizon)
    var, cvar = _loss_var_es(losses, confidence)
    return dict(VaR=var, CVaR=cvar, ES=cvar,
                confidence=confidence, horizon=horizon, n_obs=len(pnl),
                method="historical_simulation")


# ─────────────────────────────────────────────────────────
# Age-weighted historical simulation (BRW 1998)
# ─────────────────────────────────────────────────────────

def hs_age_weighted(pnl: np.ndarray, confidence: float = 0.95,
                    decay: float = 0.98, horizon: int = 1) -> dict:
    """
    Age-weighted historical simulation.
    More recent observations get higher weight (decay^0 most recent, decay^T oldest).
    """
    confidence = _validate_confidence(confidence)
    horizon = _validate_horizon(horizon)
    pnl = _as_finite_1d(pnl, "pnl")
    if not 0.0 < decay < 1.0:
        raise ValueError("decay must be between 0 and 1")
    n = len(pnl)
    # weights: most recent obs = index n-1 -> weight proportional to decay^0
    k = np.arange(n-1, -1, -1)  # k=0 is most recent
    w = decay**k * (1-decay) / (1 - decay**n)
    w = w[::-1]  # align with pnl order

    losses = -pnl * np.sqrt(horizon)
    var, cvar = _loss_var_es(losses, confidence, w)

    return dict(VaR=var, CVaR=cvar, ES=cvar,
                confidence=confidence, horizon=horizon,
                decay=decay, method="age_weighted_hs")


# ─────────────────────────────────────────────────────────
# Volatility-scaled (filtered) historical simulation
# ─────────────────────────────────────────────────────────

def filtered_hs_var(returns: np.ndarray, position: float,
                    confidence: float = 0.95, horizon: int = 1,
                    ewma_lambda: float = 0.94) -> dict:
    """
    Hull-White (1998) filtered historical simulation.
    Scales each historical return by current_vol / historical_vol.
    """
    confidence = _validate_confidence(confidence)
    horizon = _validate_horizon(horizon)
    returns = _as_finite_1d(returns, "returns")
    from models.garch import ewma_variance
    var_series   = ewma_variance(returns, ewma_lambda)
    current_var  = var_series[-1]
    current_vol  = np.sqrt(current_var)

    # Standardise
    hist_vols    = np.sqrt(var_series)
    std_returns  = returns / (hist_vols + 1e-12)
    # Rescale to current volatility
    scaled_ret   = std_returns * current_vol * np.sqrt(horizon)

    losses = -scaled_ret * position
    var, cvar = _loss_var_es(losses, confidence)

    return dict(VaR=var, CVaR=cvar, ES=cvar,
                current_vol_annual=current_vol*np.sqrt(252),
                confidence=confidence, horizon=horizon,
                method="filtered_hs")


# ─────────────────────────────────────────────────────────
# Portfolio historical VaR with positions
# ─────────────────────────────────────────────────────────

def portfolio_hs_var(returns_matrix: np.ndarray, positions: np.ndarray,
                     market_values: np.ndarray, confidence: float = 0.95,
                     horizon: int = 1) -> dict:
    """
    Multi-asset historical VaR.
    returns_matrix: (n_obs, n_assets) daily returns
    positions:      (n_assets,) notional positions
    market_values:  (n_assets,) current market values
    """
    # P&L per scenario
    pnl = (returns_matrix * market_values * positions).sum(axis=1)
    res = hs_var(pnl, confidence, horizon)

    # Marginal VaR (numerical)
    eps = 0.01
    marginal = []
    for i in range(len(positions)):
        pos_up = positions.copy(); pos_up[i] *= (1+eps)
        pnl_up = (returns_matrix * market_values * pos_up).sum(axis=1)
        var_up = hs_var(pnl_up, confidence, horizon)["VaR"]
        marginal.append((var_up - res["VaR"]) / (positions[i]*eps + 1e-12))

    # Component VaR
    component = np.array(marginal) * positions
    res["marginal_VaR"]  = marginal
    res["component_VaR"] = component
    res["pct_VaR"]       = component / (res["VaR"] + 1e-12)
    return res


# ─────────────────────────────────────────────────────────
# Monte Carlo VaR with full repricing
# ─────────────────────────────────────────────────────────

def mc_var_full_reprice(pricer_fn, base_params: dict,
                        shock_params: list,
                        n_sims: int = 10_000,
                        confidence: float = 0.95,
                        seed: int = 42) -> dict:
    """
    Full revaluation MC VaR.
    pricer_fn: callable(params) → price
    base_params: dict of base market params
    shock_params: list of param keys to shock
    Returns VaR, CVaR, distribution.
    """
    rng       = np.random.default_rng(seed)
    base_price = pricer_fn(base_params)

    pnls = []
    for _ in range(n_sims):
        params = base_params.copy()
        for key in shock_params:
            if "vol" in key or "sigma" in key:
                params[key] *= np.exp(rng.normal(0, 0.02))
            elif "spot" in key or "S" in key:
                params[key] *= np.exp(rng.normal(0, 0.015))
            elif "rate" in key or "r" == key:
                params[key] += rng.normal(0, 0.001)
        try:
            new_price = pricer_fn(params)
            pnls.append(new_price - base_price)
        except Exception:
            pnls.append(0)

    pnls = np.array(pnls)
    losses = -pnls
    var  = np.percentile(losses, confidence*100)
    cvar = losses[losses >= var].mean()
    return dict(VaR=var, CVaR=cvar, pnl_distribution=pnls,
                base_price=base_price, n_sims=n_sims)


# ─────────────────────────────────────────────────────────
# Backtesting suite (Hull Ch. 22.8)
# ─────────────────────────────────────────────────────────

def backtest_var(pnl: np.ndarray, var_series: np.ndarray,
                 confidence: float = 0.95) -> dict:
    """
    Comprehensive VaR backtest.
    pnl:       daily realised P&L
    var_series: daily VaR estimates (positive numbers)
    """
    n          = len(pnl)
    exceptions = pnl < -var_series  # loss exceeds VaR
    n_exc      = exceptions.sum()
    exc_rate   = n_exc / n
    expected   = n * (1-confidence)

    # Kupiec POF test
    from risk.var import kupiec_test, christoffersen_test
    kupiec = kupiec_test(n, int(n_exc), confidence)

    # Christoffersen independence
    christoff = christoffersen_test(exceptions.astype(int))

    # Basel traffic light
    if n_exc <= int(expected*1.5):
        basel = "Green"
    elif n_exc <= int(expected*3):
        basel = "Yellow"
    else:
        basel = "Red"

    # Average excess loss
    excess_losses = (-pnl[exceptions] - var_series[exceptions])
    avg_excess    = excess_losses.mean() if len(excess_losses) > 0 else 0

    return dict(
        n_obs=n, n_exceptions=int(n_exc), exception_rate=exc_rate,
        expected_exceptions=expected,
        kupiec_lr=kupiec["lr_stat"], kupiec_pval=kupiec["p_value"],
        kupiec_reject=kupiec["reject"],
        christoffersen_lr=christoff["lr_stat"],
        christoffersen_reject=christoff["reject"],
        basel_zone=basel,
        avg_excess_loss=avg_excess,
    )


# ─────────────────────────────────────────────────────────
# PCA-based VaR for yield curve
# ─────────────────────────────────────────────────────────

def pca_var(returns_matrix: np.ndarray, dv01_vector: np.ndarray,
            confidence: float = 0.95, n_components: int = 3) -> dict:
    """
    PCA decomposition of yield curve risk (Hull Ch. 22.9).
    Returns_matrix: (n_obs, n_tenors) yield changes.
    dv01_vector:    (n_tenors,) DV01 at each tenor.
    """
    cov   = np.cov(returns_matrix.T)
    vals, vecs = np.linalg.eigh(cov)
    idx  = np.argsort(vals)[::-1]
    vals = vals[idx]; vecs = vecs[:,idx]

    # Factor loadings * DV01
    factor_dv01 = vecs[:, :n_components].T @ dv01_vector  # (n_comp,)
    factor_vol  = np.sqrt(vals[:n_components] * 252)       # annualised

    # VaR = z * sqrt(sum(factor_dv01^2 * factor_var))
    z      = norm.ppf(confidence)
    var    = z * np.sqrt(np.sum((factor_dv01 * np.sqrt(vals[:n_components]))**2))

    explained_var = vals[:n_components].sum() / vals.sum()

    return dict(
        VaR=abs(var),
        factor_dv01=factor_dv01,
        factor_vol_annual=factor_vol,
        pct_variance_explained=explained_var,
        eigenvalues=vals[:n_components],
        eigenvectors=vecs[:,:n_components],
        n_components=n_components,
    )
