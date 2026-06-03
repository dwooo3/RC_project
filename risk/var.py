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

def historical_var(returns: np.ndarray, position_value: float,
                   confidence: float = 0.95, horizon: int = 1,
                   weights: np.ndarray = None) -> dict:
    """
    Historical simulation VaR and CVaR.
    weights: exponential decay weights for EWMA-filtered historical VaR.
    """
    if weights is not None:
        weights = np.array(weights) / np.array(weights).sum()
        sorted_idx = np.argsort(returns)
        sorted_r   = returns[sorted_idx]
        sorted_w   = weights[sorted_idx]
        cum_w      = np.cumsum(sorted_w)
        var_idx    = np.searchsorted(cum_w, 1 - confidence)
        var_pct    = sorted_r[max(var_idx, 0)]
        cvar_pct   = np.sum(sorted_r[:var_idx] * sorted_w[:var_idx]) / max(1-confidence, 1e-10)
    else:
        scaled     = returns * np.sqrt(horizon)
        var_pct    = np.percentile(scaled, (1-confidence)*100)
        cvar_pct   = scaled[scaled <= var_pct].mean() if (scaled <= var_pct).any() else var_pct

    return dict(VaR=abs(var_pct)*position_value,
                CVaR=abs(cvar_pct)*position_value,
                VaR_pct=abs(var_pct), CVaR_pct=abs(cvar_pct),
                method="historical", confidence=confidence, horizon=horizon,
                n_obs=len(returns))


def parametric_var(returns: np.ndarray, position_value: float,
                   confidence: float = 0.95, horizon: int = 1,
                   distribution: str = "normal") -> dict:
    """
    Parametric VaR: normal or Student-t.
    distribution: normal | t
    """
    mu  = returns.mean()
    sig = returns.std()

    if distribution == "t":
        df, loc, scale = t_dist.fit(returns, floc=mu)
        z     = t_dist.ppf(1-confidence, df)
        cvar_z= -t_dist.pdf(z, df) / (1-confidence) * scale + mu
        var_pct = -(loc + scale*z)
        cvar_pct= abs(cvar_z)
    else:
        z        = norm.ppf(1-confidence)
        var_pct  = -(mu + sig*z)
        cvar_pct = -mu + sig*norm.pdf(z)/(1-confidence)

    var_pct  *= np.sqrt(horizon)
    cvar_pct *= np.sqrt(horizon)

    return dict(VaR=var_pct*position_value,
                CVaR=cvar_pct*position_value,
                VaR_pct=var_pct, CVaR_pct=cvar_pct,
                mu=mu, sigma=sig,
                method=f"parametric_{distribution}", confidence=confidence, horizon=horizon)


def montecarlo_var(returns: np.ndarray, position_value: float,
                   confidence: float = 0.95, horizon: int = 1,
                   n_sims: int = 100_000, seed: int = 42) -> dict:
    """Monte Carlo VaR from fitted normal distribution."""
    rng  = np.random.default_rng(seed)
    mu   = returns.mean(); sig = returns.std()
    sim  = rng.normal(mu*horizon, sig*np.sqrt(horizon), n_sims)
    var_pct  = np.percentile(sim, (1-confidence)*100)
    cvar_pct = sim[sim <= var_pct].mean()
    return dict(VaR=abs(var_pct)*position_value,
                CVaR=abs(cvar_pct)*position_value,
                VaR_pct=abs(var_pct), CVaR_pct=abs(cvar_pct),
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
