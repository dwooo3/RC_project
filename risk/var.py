"""
Value at Risk:
  - Historical simulation (basic + filtered)
  - Parametric (delta-normal, delta-gamma-normal)
  - Monte Carlo
  - Extreme Value Theory (Peaks-Over-Threshold / GPD)
  - Expected Shortfall (CVaR)
  - Marginal / Component / Incremental VaR
  - Backtesting (Kupiec, Christoffersen)
"""

import numpy as np
from scipy.stats import norm, t as t_dist, genpareto
from scipy.optimize import minimize


# ─────────────────────────────────────────────────────────
# Base VaR functions
# ─────────────────────────────────────────────────────────

def _validate_confidence(confidence: float) -> float:
    confidence = float(confidence)
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _validate_horizon(horizon: int | float) -> float:
    horizon = float(horizon)
    if not np.isfinite(horizon) or horizon <= 0:
        raise ValueError("horizon must be positive")
    return horizon


def _as_finite_1d(values: np.ndarray, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional array")
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must not contain NaN or inf")
    return arr


def _loss_quantile_index(n: int, confidence: float) -> int:
    return min(max(int(np.ceil(confidence * n)) - 1, 0), n - 1)


# Minimum number of multi-day windows required before non-parametric horizon
# aggregation is used instead of the parametric sqrt-time fallback.
_MIN_HORIZON_WINDOWS = 50


def _horizon_returns(returns: np.ndarray, horizon: float) -> np.ndarray:
    """
    Return the return series to use for a given risk horizon.

    Historical simulation is non-parametric, so multi-day risk should come from
    actual multi-day P&L windows, NOT from scaling 1-day returns by sqrt(h)
    (which silently assumes i.i.d. normal returns and can misstate fat-tailed
    multi-day VaR by double digits). For an integer horizon > 1 with enough
    data we aggregate *overlapping* h-day returns (Basel FRTB style). When the
    horizon is non-integer or there are too few observations to form a stable
    set of windows, we fall back to the legacy sqrt-time scaling.

    Reference: McNeil, Frey & Embrechts, "Quantitative Risk Management" (2015),
    §2.2.3; Basel FRTB overlapping-window convention.
    """
    h = int(round(horizon))
    is_integer = abs(horizon - h) < 1e-9
    n_windows = len(returns) - h + 1
    if not is_integer or h <= 1 or n_windows < _MIN_HORIZON_WINDOWS:
        return returns * np.sqrt(horizon)
    c = np.concatenate(([0.0], np.cumsum(returns)))
    return c[h:] - c[:-h]   # overlapping h-day sums, length n - h + 1


def _loss_var_es(losses: np.ndarray, confidence: float,
                 weights: np.ndarray | None = None) -> tuple[float, float]:
    """VaR/ES for positive losses using one discrete convention."""
    confidence = _validate_confidence(confidence)
    losses = _as_finite_1d(losses, "losses")
    losses = np.maximum(losses, 0.0)
    if weights is None:
        sorted_losses = np.sort(losses)
        idx = _loss_quantile_index(len(sorted_losses), confidence)
        var = float(sorted_losses[idx])
        es = float(sorted_losses[idx:].mean())
        return max(var, 0.0), max(es, var, 0.0)

    weights = _as_finite_1d(weights, "weights")
    if weights.shape != losses.shape:
        raise ValueError("weights must have the same shape as losses")
    if np.any(weights < 0):
        raise ValueError("weights must be non-negative")
    weight_sum = weights.sum()
    if weight_sum <= 0:
        raise ValueError("weights must sum to a positive value")
    weights = weights / weight_sum

    sorted_idx = np.argsort(losses)
    sorted_losses = losses[sorted_idx]
    sorted_weights = weights[sorted_idx]
    cum_w = np.cumsum(sorted_weights)
    var_idx = min(np.searchsorted(cum_w, confidence, side="left"), len(sorted_losses) - 1)
    var = float(sorted_losses[var_idx])
    tail_mask = sorted_losses >= var
    tail_w = sorted_weights[tail_mask]
    es = float((sorted_losses[tail_mask] * tail_w).sum() / tail_w.sum())
    return max(var, 0.0), max(es, var, 0.0)


def historical_var(returns: np.ndarray, position_value: float,
                   confidence: float = 0.95, horizon: int = 1,
                   weights: np.ndarray = None) -> dict:
    """
    Historical simulation VaR and CVaR.
    weights: exponential decay weights for EWMA-filtered historical VaR.
    """
    confidence = _validate_confidence(confidence)
    horizon = _validate_horizon(horizon)
    returns = _as_finite_1d(returns, "returns")
    position_value = float(position_value)
    horizon_returns = _horizon_returns(returns, horizon)
    losses_pct = -horizon_returns
    # Align decay weights when overlapping windows shortened the series.
    if weights is not None and len(horizon_returns) != len(returns):
        weights = np.asarray(weights, dtype=float)[-len(horizon_returns):]
    var_pct, cvar_pct = _loss_var_es(losses_pct, confidence, weights)

    return dict(VaR=var_pct*position_value,
                CVaR=cvar_pct*position_value,
                ES=cvar_pct*position_value,
                VaR_pct=var_pct, CVaR_pct=cvar_pct,
                method="historical", confidence=confidence, horizon=horizon,
                n_obs=len(returns))


def parametric_var(returns: np.ndarray, position_value: float,
                   confidence: float = 0.95, horizon: int = 1,
                   distribution: str = "normal") -> dict:
    """
    Parametric VaR: normal or Student-t.
    distribution: normal | t
    """
    confidence = _validate_confidence(confidence)
    horizon = _validate_horizon(horizon)
    returns = _as_finite_1d(returns, "returns")
    position_value = float(position_value)
    mu  = returns.mean()
    sig = returns.std(ddof=1) if len(returns) > 1 else 0.0

    if distribution == "t":
        df, loc, scale = t_dist.fit(returns, floc=mu)
        q = t_dist.ppf(1 - confidence, df)
        daily_var = -(loc + scale*q)
        if df > 1:
            daily_es = -loc + scale * (
                t_dist.pdf(q, df) / (1 - confidence)
                * (df + q**2) / (df - 1)
            )
        else:
            daily_es = np.inf
        var_pct = max(daily_var * np.sqrt(horizon), 0.0)
        cvar_pct = max(daily_es * np.sqrt(horizon), var_pct)
    else:
        z = norm.ppf(confidence)
        mean_loss = -mu * horizon
        sig_h = sig * np.sqrt(horizon)
        var_pct = max(mean_loss + z * sig_h, 0.0)
        cvar_pct = max(mean_loss + sig_h * norm.pdf(z)/(1-confidence), var_pct)

    return dict(VaR=var_pct*position_value,
                CVaR=cvar_pct*position_value,
                ES=cvar_pct*position_value,
                VaR_pct=var_pct, CVaR_pct=cvar_pct,
                mu=mu, sigma=sig,
                method=f"parametric_{distribution}", confidence=confidence, horizon=horizon)


def montecarlo_var(returns: np.ndarray, position_value: float,
                   confidence: float = 0.95, horizon: int = 1,
                   n_sims: int = 100_000, seed: int = 42) -> dict:
    """Monte Carlo VaR from fitted normal distribution."""
    confidence = _validate_confidence(confidence)
    horizon = _validate_horizon(horizon)
    returns = _as_finite_1d(returns, "returns")
    if n_sims <= 0:
        raise ValueError("n_sims must be positive")
    rng  = np.random.default_rng(seed)
    mu   = returns.mean(); sig = returns.std(ddof=1) if len(returns) > 1 else 0.0
    sim  = rng.normal(mu*horizon, sig*np.sqrt(horizon), n_sims)
    losses_pct = -sim
    var_pct, cvar_pct = _loss_var_es(losses_pct, confidence)
    return dict(VaR=var_pct*position_value,
                CVaR=cvar_pct*position_value,
                ES=cvar_pct*position_value,
                VaR_pct=var_pct, CVaR_pct=cvar_pct,
                method="monte_carlo", confidence=confidence,
                horizon=horizon, n_sims=n_sims)


# ─────────────────────────────────────────────────────────
# Extreme Value Theory (EVT) — Peaks over Threshold
# ─────────────────────────────────────────────────────────

def evt_var(returns: np.ndarray, position_value: float,
            confidence: float = 0.99, threshold_pct: float = 0.10,
            horizon: int = 1) -> dict:
    """
    EVT VaR via Peaks-over-Threshold (POT) / Generalized Pareto Distribution.
    threshold_pct: fraction of worst returns used to fit GPD (e.g. 0.10 = bottom 10%).
    """
    losses   = -returns
    u        = np.percentile(losses, (1-threshold_pct)*100)
    excesses = losses[losses > u] - u

    if len(excesses) < 20:
        return {"error": "Too few exceedances; lower threshold_pct"}

    xi, loc, beta = genpareto.fit(excesses, floc=0)
    n  = len(losses); Nu = len(excesses)

    # GPD-based VaR
    p    = 1 - confidence
    if xi == 0:
        var_pct = u - beta*np.log(p*n/Nu)
    else:
        var_pct = u + beta/xi * ((p*n/Nu)**(-xi) - 1)

    # CVaR
    if xi < 1:
        cvar_pct = (var_pct + beta - xi*u) / (1 - xi)
    else:
        cvar_pct = np.inf

    var_pct  *= np.sqrt(horizon)
    cvar_pct *= np.sqrt(horizon)

    return dict(VaR=var_pct*position_value, CVaR=cvar_pct*position_value,
                VaR_pct=var_pct, CVaR_pct=cvar_pct,
                xi=xi, beta=beta, threshold=u, n_exceedances=Nu,
                method="evt_pot", confidence=confidence)


# ─────────────────────────────────────────────────────────
# Delta-Gamma-Normal VaR (for nonlinear positions)
# ─────────────────────────────────────────────────────────

def delta_gamma_var(delta: float, gamma: float, position: float,
                    sigma: float, confidence: float = 0.95,
                    horizon: int = 1) -> dict:
    """
    Approximate VaR for nonlinear position via delta-gamma expansion.
    Uses Cornish-Fisher expansion for non-normal distribution adjustment.
    """
    dS    = position * sigma * np.sqrt(horizon)
    mu_cf = 0.5 * gamma * dS**2
    sig_cf= abs(delta) * dS
    # skewness correction (Cornish-Fisher)
    skew  = gamma * dS**3 / sig_cf**3 if sig_cf > 0 else 0
    z     = norm.ppf(1-confidence)
    z_cf  = z + (z**2-1)*skew/6
    var   = -(mu_cf + z_cf * sig_cf)
    return dict(VaR=abs(var), VaR_pct=abs(var)/position if position else 0,
                delta=delta, gamma=gamma, skew=skew,
                method="delta_gamma_cornish_fisher")


# ─────────────────────────────────────────────────────────
# Portfolio VaR (multi-asset)
# ─────────────────────────────────────────────────────────

def portfolio_var(weights: np.ndarray, returns_matrix: np.ndarray,
                  portfolio_value: float, confidence: float = 0.95,
                  horizon: int = 1, method: str = "parametric") -> dict:
    """
    Portfolio VaR.
    weights:        shape (n_assets,) — portfolio weights, sum to 1
    returns_matrix: shape (n_obs, n_assets)
    method: parametric | historical | mc
    """
    port_returns = returns_matrix @ weights

    if method == "parametric":
        cov     = np.cov(returns_matrix.T)
        port_var= weights @ cov @ weights
        port_sig= np.sqrt(port_var * horizon)
        port_mu = port_returns.mean() * horizon
        z       = norm.ppf(1-confidence)
        var_pct = -(port_mu + z*port_sig)
        cvar_pct= -port_mu + port_sig*norm.pdf(z)/(1-confidence)
        annual_vol = np.sqrt(port_var * 252)
    else:
        res = (historical_var if method=="historical" else montecarlo_var)(
              port_returns, portfolio_value, confidence, horizon)
        res["method"] = f"portfolio_{method}"
        return res

    return dict(VaR=var_pct*portfolio_value, CVaR=cvar_pct*portfolio_value,
                VaR_pct=var_pct, CVaR_pct=cvar_pct,
                annual_vol=annual_vol, method="portfolio_parametric",
                confidence=confidence, horizon=horizon)


def component_var(weights: np.ndarray, returns_matrix: np.ndarray,
                  portfolio_value: float, confidence: float = 0.95) -> dict:
    """
    Marginal and component VaR decomposition.
    """
    port_r = returns_matrix @ weights
    mu_p   = port_r.mean(); sig_p = port_r.std()
    z      = norm.ppf(1-confidence)
    var_p  = -(mu_p + z*sig_p) * portfolio_value

    cov    = np.cov(returns_matrix.T)
    marginal = (cov @ weights) / sig_p
    component_var = weights * marginal * abs(z) * portfolio_value
    pct_component = component_var / var_p

    return dict(total_VaR=var_p,
                marginal_VaR=dict(zip(range(len(weights)), marginal * abs(z) * portfolio_value)),
                component_VaR=dict(zip(range(len(weights)), component_var)),
                pct_contribution=dict(zip(range(len(weights)), pct_component)))


# ─────────────────────────────────────────────────────────
# Backtesting
# ─────────────────────────────────────────────────────────

def kupiec_test(n_obs: int, n_exceptions: int, confidence: float = 0.95) -> dict:
    """
    Kupiec (1995) Proportion of Failures (POF) test.
    H0: model is correctly specified (exception rate = 1-confidence).
    """
    p    = 1 - confidence
    p_hat= n_exceptions / n_obs
    if p_hat == 0:
        lr = 2*n_obs*np.log(1/(1-p))
    elif p_hat == 1:
        lr = 2*n_obs*np.log(1/p)
    else:
        lr = -2*(np.log((1-p)**(n_obs-n_exceptions)*p**n_exceptions)
                -np.log((1-p_hat)**(n_obs-n_exceptions)*p_hat**n_exceptions))
    from scipy.stats import chi2
    p_val   = 1 - chi2.cdf(lr, df=1)
    critical= chi2.ppf(0.95, df=1)
    return dict(lr_stat=lr, p_value=p_val, reject=(lr > critical),
                expected_exceptions=n_obs*p,
                actual_exceptions=n_exceptions, n_obs=n_obs)


def christoffersen_test(exceptions: np.ndarray) -> dict:
    """
    Christoffersen (1998) independence test for VaR exceptions.
    exceptions: binary array (1=exception, 0=no exception).
    """
    n   = len(exceptions)
    T00 = np.sum((exceptions[:-1]==0) & (exceptions[1:]==0))
    T01 = np.sum((exceptions[:-1]==0) & (exceptions[1:]==1))
    T10 = np.sum((exceptions[:-1]==1) & (exceptions[1:]==0))
    T11 = np.sum((exceptions[:-1]==1) & (exceptions[1:]==1))

    pi01 = T01/(T00+T01) if (T00+T01)>0 else 0
    pi11 = T11/(T10+T11) if (T10+T11)>0 else 0
    pi   = (T01+T11)/(T00+T01+T10+T11)

    def safe_log(x): return np.log(x) if x > 0 else 0

    L_ind = (safe_log((1-pi)**(T00+T10)*pi**(T01+T11))
             - safe_log((1-pi01)**T00*pi01**T01*(1-pi11)**T10*pi11**T11))
    lr    = -2*L_ind
    from scipy.stats import chi2
    p_val = 1 - chi2.cdf(lr, df=1)
    return dict(lr_stat=lr, p_value=p_val, reject=(lr > chi2.ppf(0.95,1)),
                pi01=pi01, pi11=pi11, pi=pi)


def copula_var(weights, vols, corr, alpha=0.99, marginal="normal", df=5,
               n_sims=200_000, seed=0):
    """Portfolio VaR under a Gaussian copula of the marginal P&Ls.

    weights·vols are position P&L scales; `corr` is the copula correlation matrix;
    marginal ∈ {normal, t}. Comonotone (ρ=1) recovers Σ marginal VaRs; the
    independent case is strictly lower (diversification)."""
    import numpy as _np
    from scipy.stats import norm as _norm, t as _t
    w = _np.asarray(weights, float)
    s = _np.asarray(vols, float)
    C = _np.asarray(corr, float)
    rng = _np.random.default_rng(seed)
    L = _np.linalg.cholesky(C + 1e-12 * _np.eye(len(C)))
    Z = rng.standard_normal((n_sims, len(w))) @ L.T          # Gaussian copula
    if marginal == "t":
        U = _norm.cdf(Z)
        X = _t.ppf(U, df) * _np.sqrt((df - 2) / df)          # unit-variance t
    else:
        X = Z
    pnl = (X * (w * s)).sum(axis=1)
    var = float(-_np.quantile(pnl, 1 - alpha))
    return dict(var=var, alpha=alpha, marginal=marginal)
