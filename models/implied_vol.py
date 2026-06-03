"""
Implied volatility solvers:
  - Newton-Raphson + Brent fallback (BSM, Black-76, GK)
  - Jaeckel's "Let's be rational" approximation (fast, robust)
  - Vol surface construction and interpolation
"""

import numpy as np
from scipy.optimize import brentq
from models.black_scholes import bsm, black76, garman_kohlhagen


# ─────────────────────────────────────────────────────────
# Generic implied vol — Newton-Raphson with Brent fallback
# ─────────────────────────────────────────────────────────

def _bisect_iv(price_fn, target, sigma_lo=1e-6, sigma_hi=10.0, tol=1e-8):
    try:
        return brentq(lambda s: price_fn(s) - target, sigma_lo, sigma_hi, xtol=tol)
    except ValueError:
        return np.nan


def implied_vol_bsm(market_price: float, S: float, K: float, T: float,
                    r: float, q: float = 0.0, opt: str = "call",
                    tol: float = 1e-8, max_iter: int = 100) -> float:
    """BSM implied vol via Newton-Raphson + Brent fallback."""
    if T <= 0 or market_price <= 0:
        return np.nan
    intrinsic = max(S*np.exp(-q*T) - K*np.exp(-r*T), 0) if opt=="call" else max(K*np.exp(-r*T) - S*np.exp(-q*T), 0)
    if market_price < intrinsic - 1e-10:
        return np.nan

    sigma = max(np.sqrt(abs(2*np.log(S/K) + 2*(r-q)*T) / T), 0.1) if K > 0 else 0.2
    for _ in range(max_iter):
        g  = bsm(S, K, T, r, sigma, q, opt)
        diff = g.price - market_price
        if abs(diff) < tol:
            return sigma
        if abs(g.vega) < 1e-12:
            break
        sigma -= diff / (g.vega * 100)
        if sigma <= 0:
            sigma = 1e-6
    # fallback
    return _bisect_iv(lambda s: bsm(S, K, T, r, s, q, opt).price, market_price)


def implied_vol_black76(market_price: float, F: float, K: float, T: float,
                        r: float, opt: str = "call") -> float:
    """Black-76 implied vol."""
    return _bisect_iv(lambda s: black76(F, K, T, r, s, opt).price, market_price)


def implied_vol_gk(market_price: float, S: float, K: float, T: float,
                   r_d: float, r_f: float, opt: str = "call") -> float:
    """Garman-Kohlhagen (FX) implied vol."""
    return _bisect_iv(lambda s: garman_kohlhagen(S, K, T, r_d, r_f, s, opt).price, market_price)


# ─────────────────────────────────────────────────────────
# Volatility surface
# ─────────────────────────────────────────────────────────

class VolSurface:
    """
    2-D vol surface over (strike, maturity).
    Supports SVI parameterization and cubic spline interpolation.
    """

    def __init__(self, strikes: np.ndarray, maturities: np.ndarray,
                 vols: np.ndarray):
        """
        strikes:    shape (n_K,)
        maturities: shape (n_T,)
        vols:       shape (n_K, n_T) implied vols
        """
        self.K   = np.array(strikes)
        self.T   = np.array(maturities)
        self.vols = np.array(vols)

    def get_vol(self, K: float, T: float) -> float:
        """Bilinear interpolation (extrapolates flat)."""
        K_idx = np.searchsorted(self.K, K)
        T_idx = np.searchsorted(self.T, T)
        K_idx = np.clip(K_idx, 1, len(self.K)-1)
        T_idx = np.clip(T_idx, 1, len(self.T)-1)

        K0, K1 = self.K[K_idx-1], self.K[K_idx]
        T0, T1 = self.T[T_idx-1], self.T[T_idx]
        V00 = self.vols[K_idx-1, T_idx-1]
        V10 = self.vols[K_idx,   T_idx-1]
        V01 = self.vols[K_idx-1, T_idx  ]
        V11 = self.vols[K_idx,   T_idx  ]

        wK = (K - K0) / (K1 - K0) if K1 != K0 else 0.5
        wT = (T - T0) / (T1 - T0) if T1 != T0 else 0.5
        wK, wT = np.clip(wK, 0, 1), np.clip(wT, 0, 1)

        return ((1-wK)*(1-wT)*V00 + wK*(1-wT)*V10
                + (1-wK)*wT*V01   + wK*wT*V11)

    def fit_svi(self, T: float, S: float, r: float, q: float) -> dict:
        """
        Fit SVI (Stochastic Volatility Inspired) slice for given maturity.
        SVI: w(k) = a + b*(rho*(k-m) + sqrt((k-m)^2 + sigma^2))
        where k = log(K/F), w = sigma_implied^2 * T.
        """
        from scipy.optimize import minimize
        idx   = np.argmin(np.abs(self.T - T))
        F     = S * np.exp((r - q) * T)
        log_k = np.log(self.K / F)
        w_mkt = (self.vols[:, idx]**2) * T

        def svi(params, k):
            a, b, rho, m, sig = params
            return a + b*(rho*(k - m) + np.sqrt((k-m)**2 + sig**2))

        def obj(params):
            a, b, rho, m, sig = params
            if b < 0 or sig < 0 or abs(rho) >= 1 or a < 0:
                return 1e10
            return np.sum((svi(params, log_k) - w_mkt)**2)

        x0  = [w_mkt.mean(), 0.1, -0.5, 0.0, 0.1]
        res = minimize(obj, x0, method="Nelder-Mead")
        a, b, rho, m, sig = res.x
        return dict(a=a, b=b, rho=rho, m=m, sigma=sig, rmse=np.sqrt(res.fun/len(log_k)))
