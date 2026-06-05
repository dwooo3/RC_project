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

from dataclasses import dataclass
from datetime import date, timedelta
import calendar

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm
from curves.yield_curve import YieldCurve, year_fraction
from models.black_scholes import black76


BusinessDayConvention = str


@dataclass(frozen=True)
class CouponPeriod:
    start_date: date
    end_date: date
    payment_date: date
    accrual_factor: float


def is_business_day(day: date, holidays: set[date] | None = None) -> bool:
    """Weekend-based business-day check with optional holiday set."""
    return day.weekday() < 5 and day not in (holidays or set())


def adjust_business_day(
    day: date,
    convention: BusinessDayConvention = "following",
    holidays: set[date] | None = None,
) -> date:
    """Adjust a date using a minimal business-day framework."""
    convention_key = convention.lower().replace("_", "-")
    holidays = holidays or set()
    if convention_key in {"none", "unadjusted"} or is_business_day(day, holidays):
        return day
    if convention_key in {"following", "modified-following"}:
        adjusted = day
        while not is_business_day(adjusted, holidays):
            adjusted += timedelta(days=1)
        if convention_key == "modified-following" and adjusted.month != day.month:
            return adjust_business_day(day, "preceding", holidays)
        return adjusted
    if convention_key == "preceding":
        adjusted = day
        while not is_business_day(adjusted, holidays):
            adjusted -= timedelta(days=1)
        return adjusted
    raise ValueError(f"Unsupported business-day convention: {convention}")


def settlement_from_valuation(
    valuation_date: date,
    settlement_days: int = 0,
    business_day_convention: BusinessDayConvention = "following",
    holidays: set[date] | None = None,
) -> date:
    """Advance a valuation date by business settlement days."""
    if settlement_days < 0:
        raise ValueError("settlement_days must be non-negative")
    current = valuation_date
    remaining = settlement_days
    while remaining > 0:
        current += timedelta(days=1)
        if is_business_day(current, holidays):
            remaining -= 1
    return adjust_business_day(current, business_day_convention, holidays)


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def _maturity_from_years(settlement_date: date, T: float, freq: int) -> date:
    periods = max(1, int(round(T * freq)))
    return _add_months(settlement_date, periods * int(round(12 / freq)))


def generate_coupon_schedule(
    issue_date: date,
    maturity_date: date,
    frequency: int,
    day_count: str = "act365",
    business_day_convention: BusinessDayConvention = "following",
    holidays: set[date] | None = None,
) -> list[CouponPeriod]:
    """Generate regular coupon periods backward from maturity."""
    if frequency <= 0:
        raise ValueError("frequency must be positive")
    if maturity_date <= issue_date:
        raise ValueError("maturity_date must be after issue_date")
    months = int(round(12 / frequency))
    if months <= 0 or 12 % frequency != 0:
        raise ValueError("frequency must divide 12 for date-based schedules")

    dates = [maturity_date]
    cursor = maturity_date
    while True:
        previous = _add_months(cursor, -months)
        if previous <= issue_date:
            dates.append(issue_date)
            break
        dates.append(previous)
        cursor = previous
    dates = sorted(set(dates))
    periods = []
    for start, end in zip(dates[:-1], dates[1:]):
        periods.append(
            CouponPeriod(
                start_date=start,
                end_date=end,
                payment_date=adjust_business_day(end, business_day_convention, holidays),
                accrual_factor=year_fraction(start, end, day_count),
            )
        )
    return periods


def _active_coupon_period(periods: list[CouponPeriod], settlement_date: date) -> CouponPeriod:
    for period in periods:
        if period.start_date <= settlement_date < period.end_date:
            return period
        if settlement_date == period.end_date:
            continue
    if settlement_date < periods[0].start_date:
        return periods[0]
    if settlement_date == periods[-1].end_date:
        return periods[-1]
    raise ValueError("settlement_date must be before or on maturity_date")


def _price_cashflows(cashflows: list[tuple[float, float]], curve: YieldCurve) -> float:
    return sum(amount * curve.discount(t) for t, amount in cashflows)


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
               curve: YieldCurve, settlement_date: date | None = None,
               maturity_date: date | None = None,
               issue_date: date | None = None,
               valuation_date: date | None = None,
               settlement_days: int = 0,
               day_count: str = "act365",
               business_day_convention: BusinessDayConvention = "following",
               holidays: set[date] | None = None,
               govt_curve: "YieldCurve | None" = None,
               swap_curve: "YieldCurve | None" = None,
               call_schedule: list | None = None,
               put_schedule: list | None = None) -> dict:
    """
    Price fixed-rate bond.
    coupon: annual coupon rate (e.g. 0.05 = 5%).
    freq:   coupons per year.
    """
    if freq <= 0:
        raise ValueError("freq must be positive")

    schedule = []
    accrued_interest = 0.0
    clean_price = None
    previous_coupon_date = None
    next_coupon_date = None

    if settlement_date is None and valuation_date is not None:
        settlement_date = settlement_from_valuation(
            valuation_date, settlement_days, business_day_convention, holidays
        )

    if settlement_date is not None:
        maturity_date = maturity_date or _maturity_from_years(settlement_date, T, freq)
        issue_date = issue_date or _add_months(maturity_date, -int(round(T * 12)))
        periods = generate_coupon_schedule(
            issue_date,
            maturity_date,
            freq,
            day_count,
            business_day_convention,
            holidays,
        )
        active_period = _active_coupon_period(periods, settlement_date)
        previous_coupon_date = active_period.start_date
        next_coupon_date = active_period.end_date
        elapsed_factor = 0.0
        if settlement_date != active_period.end_date:
            elapsed_factor = year_fraction(active_period.start_date, settlement_date, day_count)
        period_factor = active_period.accrual_factor
        coupon_amount = face * coupon / freq
        accrued_interest = coupon_amount * elapsed_factor / period_factor if period_factor > 0 else 0.0

        cf_times = []
        coupons = []
        for period in periods:
            if period.payment_date <= settlement_date:
                continue
            t = year_fraction(settlement_date, period.payment_date, day_count)
            amount = coupon_amount
            if period.end_date == maturity_date:
                amount += face
            cf_times.append(t)
            coupons.append(amount)
            schedule.append(
                {
                    "start_date": period.start_date,
                    "end_date": period.end_date,
                    "payment_date": period.payment_date,
                    "time": t,
                    "accrual_factor": period.accrual_factor,
                    "cash_flow": amount,
                }
            )
    else:
        dt = 1.0 / freq
        periods = int(round(T * freq))
        cf_times = [i * dt for i in range(1, periods + 1)]
        coupons = [face * coupon / freq] * periods
        coupons[-1] += face

    price = _price_cashflows(list(zip(cf_times, coupons)), curve)
    clean_price = price - accrued_interest

    # macaulay duration
    pv_t = sum(c * curve.discount(t) * t for c, t in zip(coupons, cf_times))
    mac_dur = pv_t / price if price else 0.0

    # YTM (flat internal yield) — solved before modified duration, which is
    # defined off the bond's own yield, not the zero rate at maturity.
    def ytm_eq(y):
        return sum(c / (1 + y / freq) ** (freq * t) for c, t in zip(coupons, cf_times)) - price
    ytm = brentq(ytm_eq, -0.99 * freq, 1.0)

    # modified duration = Macaulay / (1 + YTM/freq)  (was zero rate at maturity)
    mod_dur = mac_dur / (1 + ytm / freq)

    # convexity
    conv = sum(c * curve.discount(t) * t**2 for c, t in zip(coupons, cf_times)) / price if price else 0.0

    shifted_up = curve.parallel_shift(1.0)
    shifted_down = curve.parallel_shift(-1.0)
    price_up = _price_cashflows(list(zip(cf_times, coupons)), shifted_up)
    price_down = _price_cashflows(list(zip(cf_times, coupons)), shifted_down)
    dv01 = (price_down - price_up) / 2.0

    # z-spread
    def zspread_eq(z):
        return sum(c * curve.discount(t) * np.exp(-z*t)
                   for c, t in zip(coupons, cf_times)) - price
    try:
        zspread = brentq(zspread_eq, -0.1, 0.5)
    except Exception:
        zspread = np.nan

    # ── unified §6 analytics (effective/key-rate duration, YTW, spreads) ──
    from instruments.fixed_income_analytics import (
        effective_duration_convexity, key_rate_durations, yield_to_worst,
        g_spread as _g_spread, i_spread as _i_spread,
    )
    cfs = list(zip(cf_times, coupons))
    reprice = lambda sh: _price_cashflows(cfs, curve.parallel_shift(sh * 1e4))
    eff_dur, eff_cvx = effective_duration_convexity(reprice, price)
    krd = key_rate_durations(cfs, curve, price, _price_cashflows)
    workouts = yield_to_worst(cfs, price, freq, call_schedule, put_schedule)
    maturity_time = max(cf_times) if cf_times else T
    g_sp = _g_spread(ytm, govt_curve, maturity_time, freq) if govt_curve is not None else None
    i_sp = _i_spread(ytm, swap_curve, maturity_time, freq) if swap_curve is not None else None

    return dict(price=price, dirty_price=price, clean_price=clean_price,
                accrued_interest=accrued_interest,
                settlement_date=settlement_date,
                maturity_date=maturity_date,
                issue_date=issue_date,
                previous_coupon_date=previous_coupon_date,
                next_coupon_date=next_coupon_date,
                day_count=day_count,
                business_day_convention=business_day_convention,
                ytm=ytm, zspread=zspread,
                mac_duration=mac_dur, mod_duration=mod_dur,
                effective_duration=eff_dur, effective_convexity=eff_cvx,
                convexity=conv, dv01=dv01, pv01=dv01, bpv=dv01,
                key_rate_durations=krd,
                ytc=workouts["ytc"], ytp=workouts["ytp"], ytw=workouts["ytw"],
                g_spread=g_sp, i_spread=i_sp,
                cash_flows=cfs,
                cashflow_schedule=schedule)


def price_ofz(face: float, coupon_rate: float, maturity: float,
              freq: int, curve: YieldCurve,
              accrued_days: int = 0, day_count: int = 365) -> dict:
    """
    Price an OFZ (Russian government) bond.
    Russian OFZ use 30/360 for coupon calculation.
    Returns dirty price, clean price, accrued interest, YTM, duration.

    Pricing wrapper over fixed_bond(); lives in the pricing layer (moved here from
    curves/russia.py to remove the Market -> Pricing reverse dependency).
    """
    res = fixed_bond(face, coupon_rate, maturity, freq, curve)

    coupon  = face * coupon_rate / freq
    accrued = coupon * accrued_days / (day_count / freq)
    clean   = res["price"] - accrued

    return dict(
        dirty_price  = res["price"],
        clean_price  = clean,
        accrued      = accrued,
        ytm          = res["ytm"],
        ytm_pct      = res["ytm"] * 100,
        mac_duration = res["mac_duration"],
        mod_duration = res["mod_duration"],
        convexity    = res["convexity"],
        dv01         = res["dv01"],
        zspread      = res.get("zspread", 0),
    )


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
    # Par-reset identity: the floating leg (index coupons + redemption) replicates
    # a par bond, so at a reset date its PV is the face. Adding the fixed spread
    # coupons gives FRN = face + spread_pv. (Previously only face*disc(T) was used,
    # omitting the floating coupon PVs, which underpriced the note towards a ZCB.)
    price = face + spread_pv
    annuity = sum(dt * curve.discount(i*dt) for i in range(1, periods+1))
    dv01  = face * dt * curve.discount(dt) / 10000  # next-reset rate sensitivity
    return dict(price=price, spread_pv=spread_pv, dv01=dv01, duration=dt, annuity=annuity)


def fra(notional: float, K: float, T1: float, T2: float, curve: YieldCurve) -> dict:
    """
    Forward Rate Agreement: pay fixed K, receive the simple forward rate set at
    T1 for the accrual period [T1, T2], settled (PV) at T2.
    """
    tau = T2 - T1
    df1, df2 = curve.discount(T1), curve.discount(T2)
    fwd = (df1 / df2 - 1.0) / tau if tau > 0 else 0.0   # simple-compounded forward
    npv = notional * (fwd - K) * tau * df2
    dv01 = notional * tau * df2 / 10000
    return dict(npv=npv, forward_rate=fwd, dv01=dv01, tau=tau)


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
    # Black-76 with r=0 returns the *undiscounted* forward value of the caplet
    # under the T2-forward measure; the single payment at T2 is then discounted
    # exactly once by disc = P(0, T2). Previously r_eff = -ln(disc)/T2 made
    # black76 apply an internal exp(-r_eff*T1) = disc^(T1/T2) factor on top of
    # the external disc, double-discounting the caplet by disc^(1 + T1/T2)
    # (~4% error for T1=1, T2=1.25, disc=0.95). See Brigo & Mercurio (2006) §1.6.
    g   = black76(F, K, T1, 0.0, sigma, "call" if opt=="cap" else "put")
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
