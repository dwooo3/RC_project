"""
Yield curve construction and analytics.
Methods: Bootstrapping, Nelson-Siegel, Svensson, Smith-Wilson (Solvency II).
Conventions: Act/365, Act/360, 30/360, Act/Act.
"""

import numpy as np
from scipy.optimize import minimize, brentq
from scipy.interpolate import CubicSpline, interp1d
from dataclasses import dataclass, field
from typing import Literal, Optional


DayCount = Literal["act365", "act360", "30360", "actact"]
Compounding = Literal["continuous", "annual", "semiannual", "simple"]


# ─────────────────────────────────────────────────────────
# Day count conventions
# ─────────────────────────────────────────────────────────

def year_fraction(T: float, convention: DayCount = "act365") -> float:
    """Already a float — identity. For real date pairs override below."""
    return float(T)


# ─────────────────────────────────────────────────────────
# Discount factor ↔ rate conversions
# ─────────────────────────────────────────────────────────

def df_to_rate(df: float, T: float, comp: Compounding = "continuous") -> float:
    if T <= 0 or df <= 0:
        return 0.0
    if comp == "continuous":
        return -np.log(df) / T
    elif comp == "annual":
        return (1/df)**(1/T) - 1
    elif comp == "semiannual":
        return 2 * ((1/df)**(1/(2*T)) - 1)
    else:  # simple
        return (1/df - 1) / T


def rate_to_df(r: float, T: float, comp: Compounding = "continuous") -> float:
    if T <= 0:
        return 1.0
    if comp == "continuous":
        return np.exp(-r * T)
    elif comp == "annual":
        return 1 / (1 + r)**T
    elif comp == "semiannual":
        return 1 / (1 + r/2)**(2*T)
    else:
        return 1 / (1 + r*T)


# ─────────────────────────────────────────────────────────
# Core yield curve class
# ─────────────────────────────────────────────────────────

class YieldCurve:
    """
    Multi-method yield curve. Stores zero rates as continuous,
    can convert to any convention on output.
    """

    def __init__(self, tenors: np.ndarray, zero_rates: np.ndarray,
                 label: str = "curve", interp: str = "cubic"):
        self.tenors     = np.array(tenors, dtype=float)
        self.zero_rates = np.array(zero_rates, dtype=float)
        self.label      = label
        self._interp    = interp
        self._build_interp()

    def _build_interp(self):
        if self._interp == "cubic" and len(self.tenors) >= 3:
            self._fn = CubicSpline(self.tenors, self.zero_rates,
                                   bc_type="natural", extrapolate=True)
        else:
            self._fn = interp1d(self.tenors, self.zero_rates,
                                kind="linear", fill_value="extrapolate")

    # ── Query ──────────────────────────────────────────────

    def rate(self, T: float, comp: Compounding = "continuous") -> float:
        """Zero rate at maturity T."""
        r_c = float(np.clip(self._fn(T), -0.3, 2.0))
        if comp == "continuous":
            return r_c
        df = rate_to_df(r_c, T, "continuous")
        return df_to_rate(df, T, comp)

    def discount(self, T: float) -> float:
        """Discount factor P(0,T)."""
        return rate_to_df(self.rate(T), T)

    def forward_rate(self, T1: float, T2: float,
                     comp: Compounding = "continuous") -> float:
        """Simply compounded forward rate for [T1, T2]."""
        if T2 <= T1:
            return self.rate(T1, comp)
        df1 = self.discount(T1)
        df2 = self.discount(T2)
        r_c = -np.log(df2/df1) / (T2 - T1)
        if comp == "continuous":
            return r_c
        df_fwd = np.exp(-r_c*(T2-T1))
        return df_to_rate(df_fwd, T2-T1, comp)

    def par_rate(self, T: float, freq: int = 2) -> float:
        """Par swap rate for maturity T (coupon bond par yield)."""
        dt = 1.0/freq
        periods = max(1, int(round(T*freq)))
        times = [i*dt for i in range(1, periods+1)]
        annuity = sum(dt * self.discount(t) for t in times)
        if annuity < 1e-12:
            return 0.0
        return (1 - self.discount(T)) / annuity

    def dv01(self, T: float, notional: float = 1e6) -> float:
        """DV01 for a zero-coupon bond position."""
        return notional * T * self.discount(T) / 10000

    def duration(self, cashflows: list, prices: list) -> dict:
        """Macaulay & Modified duration from cashflow schedule."""
        total_pv = sum(cf * self.discount(t) for t, cf in cashflows)
        if total_pv < 1e-12:
            return dict(macaulay=0, modified=0)
        mac = sum(t * cf * self.discount(t) for t, cf in cashflows) / total_pv
        y   = self.rate(cashflows[-1][0])
        mod = mac / (1 + y/2)  # semiannual compounding
        return dict(macaulay=mac, modified=mod, dv01=total_pv*mod/10000)

    def par_curve(self, tenors=None) -> dict:
        tenors = tenors or [0.25,0.5,1,2,3,5,7,10,15,20,30]
        return {T: self.par_rate(T) for T in tenors}

    def zero_curve(self, tenors=None) -> dict:
        tenors = tenors or [0.25,0.5,1,2,3,5,7,10,15,20,30]
        return {T: self.rate(T) for T in tenors}

    def forward_curve(self, tenors=None, tenor_step=0.5) -> dict:
        tenors = tenors or [0.25,0.5,1,2,3,5,7,10,15,20]
        return {T: self.forward_rate(T, T+tenor_step) for T in tenors}

    # ── Shift / spread ──────────────────────────────────────

    def parallel_shift(self, bps: float) -> "YieldCurve":
        """Return shifted curve (+bps basis points)."""
        return YieldCurve(self.tenors, self.zero_rates + bps/10000,
                          label=f"{self.label}+{bps}bp", interp=self._interp)

    def add_spread(self, spread_curve: "YieldCurve") -> "YieldCurve":
        """Add z-spread curve."""
        new_rates = self.zero_rates + np.array([spread_curve.rate(T)
                                                 for T in self.tenors])
        return YieldCurve(self.tenors, new_rates, label=f"{self.label}+spread")

    # ── Factories ───────────────────────────────────────────

    @classmethod
    def flat(cls, rate: float, label="flat") -> "YieldCurve":
        return cls([0.001, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30],
                   [rate]*11, label=label)

    @classmethod
    def from_par_rates(cls, tenors: list, par_rates: list,
                       freq: int = 2, label="bootstrapped") -> "YieldCurve":
        """Bootstrap zero curve from par rates (coupon bonds)."""
        zero_rates = []
        disc_factors = {}

        def _get_df(t):
            if t in disc_factors:
                return disc_factors[t]
            zi = np.interp(t, tenors[:len(zero_rates)], zero_rates) if zero_rates else 0.04
            return np.exp(-zi*t)

        dt = 1.0/freq
        for par, T in zip(par_rates, tenors):
            periods = max(1, int(round(T*freq)))
            times   = [i*dt for i in range(1, periods)]
            coupon  = par/freq
            # sum of PV of intermediate coupons
            pv_coupons = sum(coupon * _get_df(t) for t in times)
            # solve for df at T
            # P = coupon*sum_df + (1+coupon)*df_T  → df_T = (1 - pv_coupons) / (1+coupon)
            df_T = (1 - pv_coupons) / (1 + coupon)
            df_T = max(df_T, 1e-10)
            z_T  = -np.log(df_T) / T
            zero_rates.append(z_T)
            disc_factors[T] = df_T
            # interpolate intermediate tenors
            for t in times:
                if t not in disc_factors:
                    disc_factors[t] = np.exp(-np.interp(t, tenors[:len(zero_rates)], zero_rates)*t)

        return cls(tenors, zero_rates, label=label)


# ─────────────────────────────────────────────────────────
# Nelson-Siegel and Svensson parameterizations
# ─────────────────────────────────────────────────────────

def nelson_siegel(T: float, b0: float, b1: float, b2: float, tau: float) -> float:
    """Nelson-Siegel zero rate."""
    if T < 1e-6:
        return b0 + b1
    x = T / tau
    ex = np.exp(-x)
    return b0 + b1*(1-ex)/x + b2*((1-ex)/x - ex)


def svensson(T: float, b0: float, b1: float, b2: float, b3: float,
             tau1: float, tau2: float) -> float:
    """Svensson (extended Nelson-Siegel) zero rate."""
    if T < 1e-6:
        return b0 + b1
    x1 = T/tau1; x2 = T/tau2
    ex1 = np.exp(-x1); ex2 = np.exp(-x2)
    ns  = b0 + b1*(1-ex1)/x1 + b2*((1-ex1)/x1 - ex1)
    sv  = b3*((1-ex2)/x2 - ex2)
    return ns + sv


class NSCurve(YieldCurve):
    """Nelson-Siegel curve with calibration."""

    def __init__(self, b0, b1, b2, tau, label="NS"):
        self.params = (b0, b1, b2, tau)
        tenors = np.array([0.25,0.5,1,2,3,5,7,10,15,20,30])
        rates  = np.array([nelson_siegel(T,b0,b1,b2,tau) for T in tenors])
        super().__init__(tenors, rates, label, interp="cubic")

    def rate(self, T: float, comp="continuous") -> float:
        r = nelson_siegel(T, *self.params)
        if comp == "continuous":
            return r
        return df_to_rate(rate_to_df(r,T), T, comp)

    @classmethod
    def fit(cls, market_tenors: list, market_rates: list,
            label="NS-fitted") -> "NSCurve":
        def obj(p):
            b0,b1,b2,tau = p
            if tau < 0.1 or b0 < 0:
                return 1e10
            return sum((nelson_siegel(T,b0,b1,b2,tau) - r)**2
                       for T,r in zip(market_tenors, market_rates))
        x0 = [0.05, -0.02, 0.01, 2.0]
        res = minimize(obj, x0, method="Nelder-Mead")
        b0,b1,b2,tau = res.x
        c = cls(b0,b1,b2,tau,label)
        c.rmse = np.sqrt(res.fun/len(market_tenors))
        return c


class SvenssonCurve(YieldCurve):
    """Svensson curve with calibration."""

    def __init__(self, b0,b1,b2,b3,tau1,tau2, label="SV"):
        self.params = (b0,b1,b2,b3,tau1,tau2)
        tenors = np.array([0.25,0.5,1,2,3,5,7,10,15,20,30])
        rates  = np.array([svensson(T,b0,b1,b2,b3,tau1,tau2) for T in tenors])
        super().__init__(tenors, rates, label, interp="cubic")

    def rate(self, T: float, comp="continuous") -> float:
        r = svensson(T, *self.params)
        if comp == "continuous":
            return r
        return df_to_rate(rate_to_df(r,T), T, comp)

    @classmethod
    def fit(cls, market_tenors: list, market_rates: list,
            label="SV-fitted") -> "SvenssonCurve":
        def obj(p):
            b0,b1,b2,b3,tau1,tau2 = p
            if tau1<0.1 or tau2<0.1 or b0<0:
                return 1e10
            return sum((svensson(T,b0,b1,b2,b3,tau1,tau2) - r)**2
                       for T,r in zip(market_tenors, market_rates))
        x0 = [0.06, -0.02, 0.01, 0.005, 1.5, 5.0]
        res = minimize(obj, x0, method="Nelder-Mead", options={"maxiter":5000})
        c = cls(*res.x, label)
        c.rmse = np.sqrt(res.fun/len(market_tenors))
        return c
