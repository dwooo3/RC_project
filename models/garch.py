"""
Volatility models (Hull Ch. 23):
  - EWMA (Exponentially Weighted Moving Average) — RiskMetrics
  - GARCH(1,1) — Bollerslev
  - GJR-GARCH (asymmetric)
  - EGARCH
  - Historical volatility (close-to-close, Parkinson, Garman-Klass, Yang-Zhang)
  - Volatility term structure forecasting
"""

import numpy as np
from scipy.optimize import minimize


# ─────────────────────────────────────────────────────────
# Historical volatility estimators
# ─────────────────────────────────────────────────────────

def hist_vol_cc(prices: np.ndarray, window: int = 21,
                annualize: bool = True, trading_days: int = 252) -> np.ndarray:
    """Close-to-close historical volatility."""
    log_ret = np.diff(np.log(prices))
    vol = np.array([log_ret[max(0,i-window):i].std()
                    for i in range(1, len(log_ret)+1)])
    if annualize:
        vol *= np.sqrt(trading_days)
    return vol


def hist_vol_parkinson(high: np.ndarray, low: np.ndarray,
                       window: int = 21, trading_days: int = 252) -> np.ndarray:
    """Parkinson high-low range estimator (more efficient than CC)."""
    k = 1 / (4 * np.log(2))
    hl_sq = (np.log(high/low))**2
    vol = np.array([np.sqrt(k * np.mean(hl_sq[max(0,i-window):i]) * trading_days)
                    for i in range(1, len(hl_sq)+1)])
    return vol


def hist_vol_garman_klass(open_: np.ndarray, high: np.ndarray,
                          low: np.ndarray, close: np.ndarray,
                          window: int = 21, trading_days: int = 252) -> np.ndarray:
    """Garman-Klass estimator: uses O, H, L, C."""
    u  = np.log(high/open_)
    d  = np.log(low/open_)
    c  = np.log(close/open_)
    gk = 0.511*(u-d)**2 - 0.019*(c*(u+d) - 2*u*d) - 0.383*c**2
    vol = np.array([np.sqrt(np.mean(gk[max(0,i-window):i]) * trading_days)
                    for i in range(1, len(gk)+1)])
    return vol


# ─────────────────────────────────────────────────────────
# EWMA (RiskMetrics)
# ─────────────────────────────────────────────────────────

def ewma_variance(returns: np.ndarray, lam: float = 0.94) -> np.ndarray:
    """
    EWMA variance: sigma_n^2 = lambda*sigma_{n-1}^2 + (1-lambda)*r_{n-1}^2
    lambda=0.94 for daily (RiskMetrics), 0.97 for monthly.
    """
    var = np.zeros(len(returns))
    var[0] = returns[0]**2
    for i in range(1, len(returns)):
        var[i] = lam*var[i-1] + (1-lam)*returns[i-1]**2
    return var


def ewma_vol(returns: np.ndarray, lam: float = 0.94,
             annualize: bool = True, trading_days: int = 252) -> np.ndarray:
    var = ewma_variance(returns, lam)
    vol = np.sqrt(var)
    if annualize:
        vol *= np.sqrt(trading_days)
    return vol


# ─────────────────────────────────────────────────────────
# GARCH(1,1)
# ─────────────────────────────────────────────────────────

class GARCH11:
    """
    sigma_n^2 = omega + alpha*r_{n-1}^2 + beta*sigma_{n-1}^2
    Long-run variance: VL = omega / (1 - alpha - beta)
    """

    def __init__(self, omega: float = None, alpha: float = 0.05,
                 beta: float = 0.90, long_run_vol: float = 0.20,
                 trading_days: int = 252):
        self.alpha       = alpha
        self.beta        = beta
        self.td          = trading_days
        if omega is not None:
            self.omega = omega
        else:
            daily_var = (long_run_vol / np.sqrt(trading_days))**2
            self.omega = daily_var * (1 - alpha - beta)

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    @property
    def long_run_var_daily(self) -> float:
        if self.persistence >= 1:
            return float("inf")
        return self.omega / (1 - self.persistence)

    @property
    def long_run_vol_annual(self) -> float:
        return np.sqrt(self.long_run_var_daily * self.td)

    def filter(self, returns: np.ndarray) -> np.ndarray:
        """Run GARCH filter; returns variance series."""
        var = np.zeros(len(returns))
        var[0] = self.long_run_var_daily
        for i in range(1, len(returns)):
            var[i] = self.omega + self.alpha*returns[i-1]**2 + self.beta*var[i-1]
        return var

    def forecast(self, current_var: float, horizon: int = 1) -> np.ndarray:
        """
        GARCH forecast for h steps ahead.
        E[sigma_{n+h}^2] = VL + (alpha+beta)^h * (sigma_n^2 - VL)
        """
        VL  = self.long_run_var_daily
        pers= self.persistence
        h   = np.arange(1, horizon+1)
        var = VL + pers**h * (current_var - VL)
        return var  # daily variance

    def forecast_vol_annual(self, current_var: float, horizon: int = 252) -> np.ndarray:
        """Annualised volatility term structure (daily horizons)."""
        daily_vars = self.forecast(current_var, horizon)
        return np.sqrt(daily_vars * self.td)

    @classmethod
    def fit(cls, returns: np.ndarray, trading_days: int = 252) -> "GARCH11":
        """MLE calibration of GARCH(1,1) parameters."""
        def neg_log_likelihood(params):
            omega, alpha, beta = params
            if omega <= 0 or alpha <= 0 or beta <= 0 or alpha+beta >= 1:
                return 1e10
            n = len(returns)
            var = np.zeros(n)
            var[0] = np.var(returns)
            for i in range(1, n):
                var[i] = omega + alpha*returns[i-1]**2 + beta*var[i-1]
            ll = -0.5 * np.sum(np.log(var) + returns**2/var)
            return -ll

        init_var = np.var(returns)
        x0 = [init_var*0.05, 0.05, 0.90]
        bounds = [(1e-8,1), (0.001,0.5), (0.001,0.999)]
        res = minimize(neg_log_likelihood, x0, bounds=bounds, method="L-BFGS-B")
        o, a, b = res.x
        obj = cls(omega=o, alpha=a, beta=b, trading_days=trading_days)
        obj._loglik = -res.fun
        return obj


# ─────────────────────────────────────────────────────────
# GJR-GARCH (captures leverage effect)
# ─────────────────────────────────────────────────────────

class GJRGARCH:
    """
    sigma_n^2 = omega + (alpha + gamma*I_{r<0})*r_{n-1}^2 + beta*sigma_{n-1}^2
    gamma > 0 → negative returns increase volatility more.
    """
    def __init__(self, omega, alpha, gamma, beta, trading_days=252):
        self.omega = omega; self.alpha = alpha
        self.gamma = gamma; self.beta  = beta
        self.td    = trading_days

    def filter(self, returns: np.ndarray) -> np.ndarray:
        var = np.zeros(len(returns))
        var[0] = np.var(returns)
        for i in range(1, len(returns)):
            ind = 1.0 if returns[i-1] < 0 else 0.0
            var[i] = (self.omega
                      + (self.alpha + self.gamma*ind)*returns[i-1]**2
                      + self.beta*var[i-1])
        return var

    @classmethod
    def fit(cls, returns: np.ndarray, trading_days=252) -> "GJRGARCH":
        def neg_ll(p):
            o,a,g,b = p
            if o<=0 or a<=0 or g<0 or b<=0 or a+g/2+b>=1:
                return 1e10
            n = len(returns)
            var = np.zeros(n); var[0] = np.var(returns)
            for i in range(1,n):
                ind = 1.0 if returns[i-1]<0 else 0.0
                var[i] = o + (a+g*ind)*returns[i-1]**2 + b*var[i-1]
            ll = -0.5*np.sum(np.log(var)+returns**2/var)
            return -ll
        iv = np.var(returns)
        res = minimize(neg_ll,[iv*0.04,0.04,0.04,0.88],
                       bounds=[(1e-8,1),(0.001,0.5),(0,0.5),(0.001,0.999)],
                       method="L-BFGS-B")
        return cls(*res.x, trading_days)


# ─────────────────────────────────────────────────────────
# Correlation estimation (Hull Ch. 23.5-23.6)
# ─────────────────────────────────────────────────────────

def ewma_covariance(r1: np.ndarray, r2: np.ndarray,
                    lam: float = 0.94) -> np.ndarray:
    """EWMA covariance between two return series."""
    cov = np.zeros(len(r1))
    cov[0] = r1[0]*r2[0]
    for i in range(1, len(r1)):
        cov[i] = lam*cov[i-1] + (1-lam)*r1[i-1]*r2[i-1]
    return cov


def ewma_correlation(r1: np.ndarray, r2: np.ndarray,
                     lam: float = 0.94) -> np.ndarray:
    cov  = ewma_covariance(r1, r2, lam)
    var1 = ewma_variance(r1, lam)
    var2 = ewma_variance(r2, lam)
    return cov / np.sqrt(var1 * var2)
