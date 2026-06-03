"""
Fixed income instruments:
  - Zero-coupon bond
  - Fixed-rate bond (yield, price, duration, convexity, DV01)
  - Floating-rate note (FRN)
  - Interest rate swap (IRS) — fixed vs floating
  - Basis swap
  - OIS (overnight index swap)
  - Cap / Floor / Collar (Black-76)
  - Swaption (Black-76)
  - Bond option (Black-76)
  - Hull-White model (short rate) for callable bonds
  - CMS spread option
"""

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm
from models.black_scholes import black76


# ─────────────────────────────────────────────────────────
# Yield curve (flat or bootstrapped)
# ─────────────────────────────────────────────────────────

class YieldCurve:
    """Simple piece-wise linear discount curve."""

    def __init__(self, tenors: list, rates: list, convention: str = "continuous"):
        self.tenors = np.array(tenors)
        self.rates  = np.array(rates)
        self.convention = convention

    def rate(self, T: float) -> float:
        return float(np.interp(T, self.tenors, self.rates))

    def discount(self, T: float) -> float:
        r = self.rate(T)
        if self.convention == "continuous":
            return np.exp(-r * T)
        elif self.convention == "annual":
            return 1 / (1 + r)**T
        else:  # simple
            return 1 / (1 + r*T)

    def forward_rate(self, T1: float, T2: float) -> float:
        """Continuously compounded forward rate between T1 and T2."""
        if T2 <= T1:
            return self.rate(T1)
        d1 = self.discount(T1); d2 = self.discount(T2)
        return -np.log(d2/d1) / (T2 - T1)

    @classmethod
    def flat(cls, rate: float):
        return cls([0.001, 100], [rate, rate])

    @classmethod
    def bootstrap(cls, instruments: list) -> "YieldCurve":
        """
        Bootstrap from (maturity, coupon_rate, price) for bonds.
        instruments: list of (T, coupon, price, freq) tuples.
        """
        tenors = []; rates = []
        for T, coupon, price, freq in sorted(instruments):
            periods = int(round(T * freq))
            dt      = 1.0 / freq
            def eq(r):
                pv = sum(coupon/freq * np.exp(-float(np.interp(i*dt,
                         [0.001]+tenors, [rates[0] if rates else r]+rates)) * i*dt)
                         for i in range(1, periods))
                pv += (1 + coupon/freq) * np.exp(-r*T)
                return pv - price
            r0 = 0.03
            try:
                r = brentq(eq, -0.05, 0.5)
            except Exception:
                r = r0
            tenors.append(T); rates.append(r)
        return cls(tenors, rates)


# ─────────────────────────────────────────────────────────
# Zero-coupon bond
# ─────────────────────────────────────────────────────────

def zcb(T: float, curve: YieldCurve, face: float = 100.0) -> dict:
    """Zero-coupon bond price, duration, convexity."""
    r     = curve.rate(T)
    price = face * curve.discount(T)
    dur   = T
    conv  = T**2
    dv01  = price * T / 10000
    return dict(price=price, duration=dur, convexity=conv, dv01=dv01, ytm=r)


# ─────────────────────────────────────────────────────────
# Fixed-rate bond
# ─────────────────────────────────────────────────────────

def fixed_bond(face: float, coupon: float, T: float, freq: int,
               curve: YieldCurve) -> dict:
    """
    Price fixed-rate bond.
    coupon: annual coupon rate (e.g. 0.05 = 5%).
    freq:   coupons per year.
    """
    dt      = 1.0 / freq
    periods = int(round(T * freq))
    cf_times = [i * dt for i in range(1, periods + 1)]
    coupons  = [face * coupon / freq] * periods
    coupons[-1] += face  # add principal at maturity

    price = sum(c * curve.discount(t) for c, t in zip(coupons, cf_times))

    # macaulay duration
    pv_t = sum(c * curve.discount(t) * t for c, t in zip(coupons, cf_times))
    mac_dur = pv_t / price

    # modified duration
    r_T = curve.rate(T)
    mod_dur = mac_dur / (1 + r_T / freq)

    # convexity
    conv = sum(c * curve.discount(t) * t**2 for c, t in zip(coupons, cf_times)) / price

    dv01 = price * mod_dur / 10000

    # YTM (flat yield)
    def ytm_eq(y):
        return sum(c * np.exp(-y*t) for c, t in zip(coupons, cf_times)) - price
    ytm = brentq(ytm_eq, -0.1, 0.5)

    # z-spread
    def zspread_eq(z):
        return sum(c * curve.discount(t) * np.exp(-z*t)
                   for c, t in zip(coupons, cf_times)) - price
    try:
        zspread = brentq(zspread_eq, -0.1, 0.5)
    except Exception:
        zspread = np.nan

    return dict(price=price, ytm=ytm, zspread=zspread,
                mac_duration=mac_dur, mod_duration=mod_dur,
                convexity=conv, dv01=dv01,
                cash_flows=list(zip(cf_times, coupons)))


# ─────────────────────────────────────────────────────────
# Floating-rate note
# ─────────────────────────────────────────────────────────

def frn(face: float, spread: float, T: float, freq: int, curve: YieldCurve) -> dict:
    """
    FRN priced at par + spread PV (ignoring reset timing).
    spread: annual spread over LIBOR/SOFR.
    For simple pricing: FRN ≈ face * disc(T_reset) + spread cashflows.
    """
    dt      = 1.0 / freq
    periods = int(round(T * freq))
    spread_pv = sum(face * spread / freq * curve.discount(i*dt) for i in range(1, periods+1))
    principal_pv = face * curve.discount(T)
    price = principal_pv + spread_pv
    dv01  = price * T / 10000 * 0.1  # approximate (low duration)
    return dict(price=price, spread_pv=spread_pv, dv01=dv01, duration=0.5/freq)


# ─────────────────────────────────────────────────────────
# Interest rate swap (IRS)
# ─────────────────────────────────────────────────────────

def irs(notional: float, fixed_rate: float, T: float, freq: int,
        curve: YieldCurve, pay_fixed: bool = True) -> dict:
    """
    Vanilla IRS: fixed vs floating.
    Returns fair swap rate, NPV, DV01, BPV.
    """
    dt      = 1.0 / freq
    periods = int(round(T * freq))
    times   = [i*dt for i in range(1, periods+1)]

    # annuity (PV of fixed leg basis)
    annuity = sum(dt * curve.discount(t) for t in times)
    # floating leg = 1 - final discount (par FRN)
    float_pv = curve.discount(0.001) - curve.discount(T)  # approx

    fair_rate = float_pv / annuity
    fixed_pv  = fixed_rate * annuity * notional
    float_pv_n= float_pv * notional

    npv = (float_pv_n - fixed_pv) if pay_fixed else (fixed_pv - float_pv_n)

    dv01 = notional * annuity / 10000
    bpv  = dv01  # bpv = dv01 for flat curve

    return dict(npv=npv, fair_rate=fair_rate, annuity=annuity,
                fixed_pv=fixed_pv, float_pv=float_pv_n,
                dv01=dv01, duration=annuity/curve.discount(T))


def ois(notional: float, fixed_rate: float, T: float,
        curve: YieldCurve) -> dict:
    """OIS: single-period (or compounded) overnight swap. Simple pricing."""
    disc  = curve.discount(T)
    fwd   = (1/disc - 1) / T  # implied OIS rate
    npv   = notional * (fwd - fixed_rate) * T * disc
    dv01  = notional * T * disc / 10000
    return dict(npv=npv, fair_ois_rate=fwd, dv01=dv01)


def basis_swap(notional: float, spread: float, T: float, freq: int,
               curve1: YieldCurve, curve2: YieldCurve) -> dict:
    """Basis swap: floating1 vs floating2 + spread. Pricing via two FRN legs."""
    leg1 = frn(notional, 0,      T, freq, curve1)
    leg2 = frn(notional, spread, T, freq, curve2)
    npv  = leg2["price"] - leg1["price"]
    # fair spread
    ann2 = sum(1/freq * curve2.discount(i/freq) for i in range(1, int(T*freq)+1))
    ann1 = sum(1/freq * curve1.discount(i/freq) for i in range(1, int(T*freq)+1))
    fair_spread = (leg1["price"] - frn(notional, 0, T, freq, curve2)["price"]) / (notional * ann2)
    return dict(npv=npv, fair_spread=fair_spread)


# ─────────────────────────────────────────────────────────
# Caplet / Floorlet / Cap / Floor
# ─────────────────────────────────────────────────────────

def caplet(notional: float, K: float, T1: float, T2: float,
           fwd_rate: float, sigma: float, disc: float,
           opt: str = "cap") -> dict:
    """Single caplet/floorlet via Black-76."""
    tau = T2 - T1
    F   = fwd_rate
    r_eff = -np.log(disc) / T2 if disc > 0 and T2 > 0 else 0
    g   = black76(F, K, T1, r_eff, sigma, "call" if opt=="cap" else "put")
    price = notional * tau * disc * g.price
    delta = notional * tau * disc * g.delta
    return dict(price=price, delta=delta, vega=g.vega*notional*tau*disc, T1=T1, T2=T2)


def cap_floor(notional: float, K: float, T: float, freq: int,
              curve: YieldCurve, vol_curve, opt: str = "cap") -> dict:
    """
    Cap/Floor as sum of caplets.
    vol_curve: callable(T) → vol, or constant float.
    """
    dt    = 1.0 / freq
    total = 0.0
    total_delta = 0.0
    caplets = []
    for i in range(1, int(round(T*freq))+1):
        T1 = (i-1)*dt; T2 = i*dt
        fwd  = curve.forward_rate(T1, T2)
        disc = curve.discount(T2)
        sigma = vol_curve(T2) if callable(vol_curve) else vol_curve
        cl   = caplet(notional, K, T1, T2, fwd, sigma, disc, opt)
        total       += cl["price"]
        total_delta += cl["delta"]
        caplets.append(cl)
    return dict(price=total, delta=total_delta,
                n_caplets=len(caplets), caplets=caplets)


def collar(notional: float, K_cap: float, K_floor: float, T: float, freq: int,
           curve: YieldCurve, vol_cap, vol_floor=None) -> dict:
    """Collar = buy cap + sell floor."""
    vol_floor = vol_floor or vol_cap
    cap_res   = cap_floor(notional, K_cap,   T, freq, curve, vol_cap,   "cap")
    floor_res = cap_floor(notional, K_floor, T, freq, curve, vol_floor, "floor")
    return dict(price=cap_res["price"] - floor_res["price"],
                cap=cap_res["price"], floor=floor_res["price"],
                net_cost=cap_res["price"] - floor_res["price"])


# ─────────────────────────────────────────────────────────
# Swaption (Black-76)
# ─────────────────────────────────────────────────────────

def swaption(notional: float, K: float, T_option: float,
             T_swap: float, freq: int, curve: YieldCurve,
             sigma: float, opt: str = "payer") -> dict:
    """
    European swaption via Black-76.
    opt: payer (right to pay fixed) | receiver (right to receive fixed).
    """
    dt      = 1.0 / freq
    periods = int(round(T_swap * freq))
    times   = [T_option + i*dt for i in range(1, periods+1)]
    annuity = sum(dt * curve.discount(t) for t in times)

    # forward swap rate
    disc0   = curve.discount(T_option)
    disc_T  = curve.discount(T_option + T_swap)
    S0      = (disc0 - disc_T) / annuity

    r_eff   = -np.log(curve.discount(T_option)) / T_option if T_option > 0 else 0
    g       = black76(S0, K, T_option, r_eff, sigma,
                      "call" if opt=="payer" else "put")
    price   = notional * annuity * g.price
    delta_S = notional * annuity * g.delta
    vega    = notional * annuity * g.vega

    return dict(price=price, delta_S=delta_S, vega=vega, annuity=annuity,
                fwd_swap_rate=S0, opt=opt)


# ─────────────────────────────────────────────────────────
# Bond option (Black-76)
# ─────────────────────────────────────────────────────────

def bond_option(bond_price: float, K: float, T_option: float,
                sigma: float, r: float, opt: str = "call") -> dict:
    """European option on a bond, priced via Black-76."""
    g = black76(bond_price, K, T_option, r, sigma, opt)
    return dict(price=g.price, delta=g.delta, gamma=g.gamma, vega=g.vega)


# ─────────────────────────────────────────────────────────
# CMS (Constant Maturity Swap) spread option
# ─────────────────────────────────────────────────────────

def cms_spread_option(S1: float, S2: float, K: float, T: float, r: float,
                      sigma1: float, sigma2: float, rho: float,
                      opt: str = "call") -> dict:
    """
    CMS spread option: max(CMS1 - CMS2 - K, 0) via Kirk approximation.
    """
    from instruments.multi_asset import spread_option_kirk
    return spread_option_kirk(S1, S2, K, T, r, sigma1, sigma2, rho)
