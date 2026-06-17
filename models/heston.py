"""
Heston stochastic volatility model — semi-analytical pricing via characteristic function.
Includes:
  - European options (Lewis / Carr-Madan FFT)
  - Calibration helpers
  - SABR model (closed-form approximation)
"""

import numpy as np
from scipy.integrate import quad
from scipy.optimize import minimize


# ─────────────────────────────────────────────────────────
# Heston characteristic function
# ─────────────────────────────────────────────────────────

def _heston_cf(phi, S, v0, r, q, kappa, theta, xi, rho, T):
    """Characteristic function of log(S_T) under Heston."""
    i   = 1j
    lam = np.sqrt(xi**2*(phi**2 + i*phi) + (kappa - i*rho*xi*phi)**2)
    D   = (kappa - i*rho*xi*phi - lam) / (kappa - i*rho*xi*phi + lam)
    G   = (1 - D*np.exp(-lam*T)) / (1 - D)

    cf  = np.exp(i*phi*(np.log(S) + (r-q)*T))
    cf *= np.exp(kappa*theta/xi**2 * ((kappa - i*rho*xi*phi - lam)*T - 2*np.log(G)))
    cf *= np.exp(v0/xi**2 * (kappa - i*rho*xi*phi - lam) * (1 - np.exp(-lam*T)) / (1 - D*np.exp(-lam*T)))
    return cf


def heston_price(S: float, K: float, T: float, r: float, q: float,
                 v0: float, kappa: float, theta: float,
                 xi: float, rho: float,
                 opt: str = "call") -> dict:
    """
    Semi-analytical Heston price via Gil-Pelaez inversion.
    v0:    initial variance
    kappa: mean-reversion speed
    theta: long-run variance
    xi:    vol of vol
    rho:   spot-vol correlation
    """
    disc   = np.exp(-r * T)
    log_K  = np.log(K)

    def _char_fn(phi):
        return _heston_cf(phi, S, v0, r, q, kappa, theta, xi, rho, T)

    def _integrand_P1(phi):
        cf = _char_fn(phi - 1j)
        cf0= _char_fn(-1j)
        return np.real(np.exp(-1j*phi*log_K) * cf / (1j*phi*cf0))

    def _integrand_P2(phi):
        cf = _char_fn(phi)
        return np.real(np.exp(-1j*phi*log_K) * cf / (1j*phi))

    I1, _ = quad(_integrand_P1, 1e-5, 200, limit=500, epsabs=1e-6)
    I2, _ = quad(_integrand_P2, 1e-5, 200, limit=500, epsabs=1e-6)

    P1 = 0.5 + I1/np.pi
    P2 = 0.5 + I2/np.pi

    call = S*np.exp(-q*T)*P1 - K*disc*P2
    if opt == "call":
        price = max(call, 0)
    else:
        price = max(call - S*np.exp(-q*T) + K*disc, 0)

    from models.implied_vol import implied_vol_bsm
    iv = implied_vol_bsm(price, S, K, T, r, q, opt)

    # Delta carries the dividend discount: dC/dS = e^{-qT} P1 (put via parity).
    dq = np.exp(-q*T)
    return dict(price=price, implied_vol=iv,
                delta=dq*P1 if opt=="call" else dq*(P1-1),
                v0=v0, kappa=kappa, theta=theta, xi=xi, rho=rho)


# ─────────────────────────────────────────────────────────
# Heston calibration
# ─────────────────────────────────────────────────────────

def heston_calibrate(market_prices: list, S: float, strikes: list,
                     maturities: list, r: float, q: float,
                     opt_types: list = None) -> dict:
    """
    Calibrate Heston parameters to market option prices.
    market_prices, strikes, maturities must be same length.
    Returns calibrated {v0, kappa, theta, xi, rho}.
    """
    if opt_types is None:
        opt_types = ["call"] * len(market_prices)

    def objective(params):
        v0, kappa, theta, xi, rho = params
        if v0 <= 0 or kappa <= 0 or theta <= 0 or xi <= 0 or abs(rho) >= 1:
            return 1e10
        # Feller condition: 2*kappa*theta > xi^2
        err = 0
        for mp, K, T, ot in zip(market_prices, strikes, maturities, opt_types):
            try:
                p = heston_price(S, K, T, r, q, v0, kappa, theta, xi, rho, ot)["price"]
                err += (p - mp)**2
            except Exception:
                err += 1e6
        return err

    x0     = [0.04, 1.5, 0.04, 0.3, -0.7]
    bounds = [(1e-4,1), (0.1,20), (1e-4,1), (0.01,2), (-0.99,0.99)]
    res    = minimize(objective, x0, bounds=bounds, method="L-BFGS-B")
    v0, kappa, theta, xi, rho = res.x
    return dict(v0=v0, kappa=kappa, theta=theta, xi=xi, rho=rho,
                rmse=np.sqrt(res.fun/len(market_prices)))


# ─────────────────────────────────────────────────────────
# SABR model
# ─────────────────────────────────────────────────────────

def sabr_vol(F: float, K: float, T: float,
             alpha: float, beta: float, rho: float, nu: float) -> float:
    """
    Hagan et al. (2002) SABR implied volatility approximation.
    alpha: initial vol, beta: CEV exponent, rho: correlation, nu: vol-of-vol.
    """
    if abs(F - K) < 1e-10:  # ATM formula
        FK_b = F**(1 - beta)
        term1 = alpha / FK_b
        term2 = 1 + ((1-beta)**2/24 * alpha**2/FK_b**2
                     + rho*beta*nu*alpha/(4*FK_b)
                     + (2 - 3*rho**2)*nu**2/24) * T
        return term1 * term2

    log_FK = np.log(F / K)
    FK_b   = (F * K)**((1 - beta)/2)
    z      = nu / alpha * FK_b * log_FK
    chi_z  = np.log((np.sqrt(1 - 2*rho*z + z**2) + z - rho) / (1 - rho))

    A = alpha / (FK_b * (1 + (1-beta)**2/24*log_FK**2 + (1-beta)**4/1920*log_FK**4))
    B = z / chi_z
    C = 1 + ((1-beta)**2/24 * alpha**2/FK_b**2
             + rho*beta*nu*alpha/(4*FK_b)
             + (2 - 3*rho**2)*nu**2/24) * T
    return A * B * C


def sabr_price(F: float, K: float, T: float, r: float,
               alpha: float, beta: float, rho: float, nu: float,
               opt: str = "call") -> dict:
    """Price option using SABR vol in Black-76."""
    from models.black_scholes import black76
    sigma = sabr_vol(F, K, T, alpha, beta, rho, nu)
    g     = black76(F, K, T, r, sigma, opt)
    return dict(price=g.price, implied_vol=sigma, delta=g.delta,
                gamma=g.gamma, vega=g.vega, theta=g.theta)


def sabr_calibrate(market_vols: list, F: float, strikes: list,
                   T: float, beta: float = 0.5) -> dict:
    """Calibrate alpha, rho, nu given beta and market implied vols."""
    def objective(params):
        alpha, rho, nu = params
        if alpha <= 0 or nu <= 0 or abs(rho) >= 1:
            return 1e10
        return sum((sabr_vol(F, K, T, alpha, beta, rho, nu) - mv)**2
                   for K, mv in zip(strikes, market_vols))

    atm_vol = market_vols[len(market_vols)//2]
    x0      = [atm_vol * F**(1-beta), -0.3, 0.4]
    bounds  = [(1e-4, 2), (-0.99, 0.99), (0.01, 5)]
    res     = minimize(objective, x0, bounds=bounds, method="L-BFGS-B")
    alpha, rho, nu = res.x
    return dict(alpha=alpha, beta=beta, rho=rho, nu=nu,
                rmse=np.sqrt(res.fun/len(market_vols)))
