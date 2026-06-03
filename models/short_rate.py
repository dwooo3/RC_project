"""
Short rate models (Hull Ch. 31-32):
  - Vasicek
  - CIR (Cox-Ingersoll-Ross)
  - Hull-White (one-factor, extended Vasicek)
  - Black-Derman-Toy (BDT)
  - Black-Karasinski (BK)
  - Ho-Lee

Bond and bond option pricing from each model.
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import minimize, brentq
from scipy.integrate import quad


# ─────────────────────────────────────────────────────────
# Vasicek model
# ─────────────────────────────────────────────────────────

class Vasicek:
    """
    dr = kappa(theta - r)dt + sigma dW
    Analytic bond prices, bond option prices.
    """
    def __init__(self, r0: float, kappa: float, theta: float, sigma: float):
        self.r0    = r0
        self.kappa = kappa
        self.theta = theta
        self.sigma = sigma

    def _AB(self, T: float):
        k, th, sig = self.kappa, self.theta, self.sigma
        if k == 0:
            B = T
            A = (sig**2 * T**3 / 6)
            return A, B
        B = (1 - np.exp(-k*T)) / k
        A = ((B - T)*(k**2*th - sig**2/2)/k**2 - sig**2*B**2/(4*k))
        return A, B

    def bond_price(self, r: float, T: float) -> float:
        A, B = self._AB(T)
        return np.exp(A - B*r)

    def zero_rate(self, T: float) -> float:
        if T < 1e-10:
            return self.r0
        P = self.bond_price(self.r0, T)
        return -np.log(P) / T

    def bond_option(self, T_opt: float, T_bond: float, K: float,
                    opt: str = "call") -> float:
        """European option on zero-coupon bond (Jamshidian)."""
        _, B_opt  = self._AB(T_opt)
        P_T  = self.bond_price(self.r0, T_opt)
        P_Tb = self.bond_price(self.r0, T_bond)
        sigma_p = self.sigma * np.sqrt((1-np.exp(-2*self.kappa*T_opt))/(2*self.kappa)) * B_opt
        if sigma_p < 1e-10:
            return max(P_Tb - K*P_T, 0) if opt=="call" else max(K*P_T - P_Tb, 0)
        h = np.log(P_Tb/(K*P_T))/sigma_p + sigma_p/2
        if opt == "call":
            return P_Tb*norm.cdf(h) - K*P_T*norm.cdf(h-sigma_p)
        else:
            return K*P_T*norm.cdf(-h+sigma_p) - P_Tb*norm.cdf(-h)

    def simulate(self, T: float, steps: int = 252, n_sims: int = 10_000,
                 seed: int = 42) -> np.ndarray:
        """Simulate short rate paths. Returns (n_sims, steps+1)."""
        rng = np.random.default_rng(seed)
        dt  = T / steps
        r   = np.full((n_sims, steps+1), self.r0)
        for i in range(steps):
            Z = rng.standard_normal(n_sims)
            dr = self.kappa*(self.theta - r[:,i])*dt + self.sigma*np.sqrt(dt)*Z
            r[:,i+1] = r[:,i] + dr
        return r

    def mean_reversion_half_life(self) -> float:
        return np.log(2) / self.kappa

    @property
    def long_run_vol(self) -> float:
        return self.sigma / np.sqrt(2 * self.kappa)


# ─────────────────────────────────────────────────────────
# CIR model
# ─────────────────────────────────────────────────────────

class CIR:
    """
    dr = kappa(theta - r)dt + sigma sqrt(r) dW
    Feller condition: 2*kappa*theta > sigma^2
    """
    def __init__(self, r0: float, kappa: float, theta: float, sigma: float):
        self.r0    = r0
        self.kappa = kappa
        self.theta = theta
        self.sigma = sigma

    def _ABh(self, T: float):
        k, th, sig = self.kappa, self.theta, self.sigma
        h = np.sqrt(k**2 + 2*sig**2)
        denom = 2*h + (k+h)*(np.exp(h*T)-1)
        B = 2*(np.exp(h*T)-1) / denom
        A = (2*h*np.exp((k+h)*T/2) / denom)**(2*k*th/sig**2)
        return A, B, h

    def bond_price(self, r: float, T: float) -> float:
        A, B, _ = self._ABh(T)
        return A * np.exp(-B*r)

    def zero_rate(self, T: float) -> float:
        if T < 1e-10:
            return self.r0
        return -np.log(self.bond_price(self.r0, T)) / T

    def feller_ok(self) -> bool:
        return 2*self.kappa*self.theta > self.sigma**2

    def simulate(self, T: float, steps: int = 252, n_sims: int = 10_000,
                 seed: int = 42) -> np.ndarray:
        rng = np.random.default_rng(seed)
        dt  = T / steps
        r   = np.full((n_sims, steps+1), self.r0)
        for i in range(steps):
            Z = rng.standard_normal(n_sims)
            r_pos = np.maximum(r[:,i], 0)
            dr = self.kappa*(self.theta - r_pos)*dt + self.sigma*np.sqrt(r_pos*dt)*Z
            r[:,i+1] = np.maximum(r[:,i] + dr, 0)
        return r


# ─────────────────────────────────────────────────────────
# Hull-White one-factor (extended Vasicek)
# ─────────────────────────────────────────────────────────

class HullWhite:
    """
    dr = [theta(t) - kappa*r]dt + sigma dW
    theta(t) calibrated to fit initial term structure exactly.
    """
    def __init__(self, kappa: float, sigma: float, curve):
        self.kappa = kappa
        self.sigma = sigma
        self.curve = curve  # YieldCurve for calibration

    def _B(self, T: float) -> float:
        return (1 - np.exp(-self.kappa*T)) / self.kappa

    def _A(self, T: float) -> float:
        """From Hull-White: A(T) fitted to market curve."""
        k, sig = self.kappa, self.sigma
        f0 = self.curve.forward_rate(0, T)  # market forward rate
        B  = self._B(T)
        return (np.log(self.curve.discount(T))
                + B * f0
                - sig**2 * B**2 * (1 - np.exp(-2*k*T)) / (4*k))

    def bond_price(self, r: float, t: float, T: float) -> float:
        """P(t,T) given r(t)."""
        k, sig = self.kappa, self.sigma
        dt = T - t
        B  = (1 - np.exp(-k*dt)) / k
        # fit to initial curve
        P0T = self.curve.discount(T)
        P0t = self.curve.discount(t) if t > 1e-8 else 1.0
        f0t = self.curve.forward_rate(t, T)
        A   = (P0T/P0t) * np.exp(B*f0t - sig**2*B**2*(1-np.exp(-2*k*t))/(4*k))
        return A * np.exp(-B*r)

    def zero_rate(self, T: float) -> float:
        r0 = self.curve.rate(0.001)
        P  = self.bond_price(r0, 0, T)
        return -np.log(P) / T

    def bond_option(self, T_opt: float, T_bond: float, K: float,
                    opt: str = "call") -> float:
        """Analytic bond option under Hull-White."""
        k, sig = self.kappa, self.sigma
        B_opt   = self._B(T_opt)
        B_bond  = self._B(T_bond)
        P_T     = self.bond_price(self.curve.rate(0.001), 0, T_opt)
        P_Tb    = self.bond_price(self.curve.rate(0.001), 0, T_bond)
        sigma_p = sig * np.sqrt((1-np.exp(-2*k*T_opt))/(2*k)) * self._B(T_bond-T_opt)
        if sigma_p < 1e-10:
            return max(P_Tb - K*P_T, 0) if opt=="call" else max(K*P_T - P_Tb, 0)
        h = np.log(P_Tb/(K*P_T))/sigma_p + sigma_p/2
        if opt == "call":
            return P_Tb*norm.cdf(h) - K*P_T*norm.cdf(h-sigma_p)
        else:
            return K*P_T*norm.cdf(-h+sigma_p) - P_Tb*norm.cdf(-h)

    def swaption(self, notional: float, K: float, T_opt: float,
                 T_swap: float, freq: int = 2) -> dict:
        """Swaption price via Jamshidian decomposition."""
        dt      = 1.0 / freq
        periods = int(round(T_swap * freq))
        times   = [T_opt + i*dt for i in range(1, periods+1)]
        coupons = [K/freq * notional] * periods
        coupons[-1] += notional

        # Find r* such that sum of bond prices = notional
        def bond_sum(r_star):
            return sum(c * self.bond_price(r_star, T_opt, t)
                       for c, t in zip(coupons, times)) - notional

        try:
            r_star = brentq(bond_sum, -0.5, 2.0)
        except ValueError:
            r_star = self.curve.rate(T_opt)

        # Jamshidian: sum of bond options
        payer_price = sum(
            c * self.bond_option(T_opt, t, self.bond_price(r_star, T_opt, t), "put")
            for c, t in zip(coupons, times)
        )
        receiver_price = sum(
            c * self.bond_option(T_opt, t, self.bond_price(r_star, T_opt, t), "call")
            for c, t in zip(coupons, times)
        )
        return dict(payer=payer_price, receiver=receiver_price,
                    r_star=r_star, T_opt=T_opt, T_swap=T_swap)

    def simulate(self, T: float, steps: int = 252, n_sims: int = 10_000,
                 seed: int = 42) -> np.ndarray:
        rng = np.random.default_rng(seed)
        dt  = T / steps
        r0  = self.curve.rate(0.001)
        r   = np.full((n_sims, steps+1), r0)
        for i in range(steps):
            t_i = i * dt
            f   = self.curve.forward_rate(t_i, t_i+dt)
            dfdt = (self.curve.rate(t_i+dt) - self.curve.rate(max(t_i-dt,0.001))) / (2*dt)
            theta_t = dfdt + self.kappa*f + self.sigma**2*(1-np.exp(-2*self.kappa*t_i))/(2*self.kappa)
            Z = rng.standard_normal(n_sims)
            dr = (theta_t - self.kappa*r[:,i])*dt + self.sigma*np.sqrt(dt)*Z
            r[:,i+1] = r[:,i] + dr
        return r


# ─────────────────────────────────────────────────────────
# Ho-Lee model
# ─────────────────────────────────────────────────────────

class HoLee:
    """
    dr = theta(t)dt + sigma dW   (simplest no-arbitrage model)
    theta(t) = df(0,t)/dt + sigma^2 * t
    """
    def __init__(self, sigma: float, curve):
        self.sig   = sigma
        self.sigma = sigma
        self.curve = curve
        self.r0    = curve.rate(0.001)

    def bond_price(self, r: float, t: float, T: float) -> float:
        P0T = self.curve.discount(T)
        P0t = self.curve.discount(t) if t > 0 else 1.0
        f0t = self.curve.forward_rate(0, t)
        dt  = T - t
        return (P0T/P0t)*np.exp(-(r-f0t)*dt - 0.5*self.sig**2*t*dt**2)

    def zero_rate(self, T: float) -> float:
        r0 = self.curve.rate(0.001)
        P  = self.bond_price(r0, 0, T)
        return -np.log(max(P, 1e-12))/T

    def simulate(self, T: float, steps: int = 252, n_sims: int = 10_000,
                 seed: int = 42) -> np.ndarray:
        rng = np.random.default_rng(seed)
        dt  = T / steps
        r0  = self.curve.rate(0.001)
        r   = np.full((n_sims, steps+1), r0)
        for i in range(steps):
            t_i = i * dt
            dfdt = (self.curve.rate(t_i+dt) - self.curve.rate(max(t_i-dt, 0.001))) / (2*dt)
            theta_t = dfdt + self.sig**2 * t_i
            Z = rng.standard_normal(n_sims)
            r[:,i+1] = r[:,i] + theta_t*dt + self.sig*np.sqrt(dt)*Z
        return r


# ─────────────────────────────────────────────────────────
# Calibration helper
# ─────────────────────────────────────────────────────────

def calibrate_hull_white(curve, swaption_vols: list,
                         swaption_specs: list) -> dict:
    """
    Calibrate Hull-White kappa and sigma to market swaption vols.
    swaption_specs: list of (T_opt, T_swap, strike, vol_mkt).
    """
    def obj(params):
        kappa, sigma = params
        if kappa <= 0 or sigma <= 0:
            return 1e10
        hw = HullWhite(kappa, sigma, curve)
        err = 0
        for T_opt, T_swap, K, vol_mkt in swaption_specs:
            try:
                res = hw.swaption(1e6, K, T_opt, T_swap)
                # rough implied vol from payer price
                from models.black_scholes import black76
                annuity = sum(0.5*curve.discount(T_opt+i*0.5)
                              for i in range(1, int(T_swap*2)+1))
                fwd_sw = (curve.discount(T_opt) - curve.discount(T_opt+T_swap)) / annuity
                from models.implied_vol import implied_vol_black76
                iv = implied_vol_black76(res["payer"]/1e6/annuity, fwd_sw, K, T_opt,
                                         curve.rate(T_opt), "call")
                if iv == iv:
                    err += (iv - vol_mkt)**2
            except Exception:
                err += 1e4
        return err

    from scipy.optimize import minimize
    res = minimize(obj, [0.1, 0.01], bounds=[(0.001,5),(0.0001,0.5)],
                   method="L-BFGS-B")
    k, s = res.x
    return dict(kappa=k, sigma=s, rmse=np.sqrt(res.fun/len(swaption_specs)))
