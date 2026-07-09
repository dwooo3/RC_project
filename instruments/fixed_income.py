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
    """Zero-coupon bond — unified §6 metrics."""
    from instruments.fixed_income_analytics import (
        effective_duration_convexity, key_rate_durations,
    )
    r     = curve.rate(T)
    price = face * curve.discount(T)
    dv01  = price * T / 10000
    cfs   = [(T, face)]
    reprice = lambda sh: face * curve.parallel_shift(sh * 1e4).discount(T)
    eff_dur, eff_cvx = effective_duration_convexity(reprice, price)
    krd = key_rate_durations(cfs, curve, price, _price_cashflows)
    return dict(price=price, clean_price=price, dirty_price=price,
                accrued_interest=0.0, ytm=r, yield_=r,
                duration=T, mac_duration=T, mod_duration=T,
                effective_duration=eff_dur, convexity=eff_cvx,
                dv01=dv01, pv01=dv01, bpv=dv01, key_rate_durations=krd)


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

def frn(face: float, spread: float, T: float, freq: int, curve: YieldCurve,
        proj_curve: YieldCurve | None = None) -> dict:
    """
    Floating-rate note with explicit forward-coupon projection (dual-curve).

    Coupons c_i = (F_i + spread)·face·τ where F_i is the simple forward for
    [t_{i-1}, t_i] off the projection curve; redemption at T; everything
    discounted on `curve`. With proj == disc the floating leg telescopes to
    par, so the price collapses to the par-reset identity face + spread_pv —
    while a projection basis now moves the coupons the way a real reset
    forecast does. Valued at a reset date (accrued = 0); no fixing lag / stub
    conventions.
    """
    proj = proj_curve or curve
    dt = 1.0 / freq
    periods = int(round(T * freq))
    cashflows, float_pv, spread_pv = [], 0.0, 0.0
    for i in range(1, periods + 1):
        t0, t1 = (i - 1) * dt, i * dt
        df0p, df1p = proj.discount(t0), proj.discount(t1)
        fwd = (df0p / df1p - 1.0) / dt if dt > 0 else 0.0
        df = curve.discount(t1)
        cpn_float = face * fwd * dt
        cpn_spread = face * spread * dt
        float_pv += cpn_float * df
        spread_pv += cpn_spread * df
        cashflows.append((t1, cpn_float + cpn_spread + (face if i == periods else 0.0)))
    redemption_pv = face * curve.discount(T)
    price = float_pv + spread_pv + redemption_pv
    annuity = sum(dt * curve.discount(i * dt) for i in range(1, periods + 1))

    # rate DV01 by full reprice on a bumped DISCOUNT curve (projection held:
    # the index reset absorbs parallel moves; what remains is the discounting
    # of the spread leg plus the projection/discount basis)
    bumped = curve.parallel_shift(1.0)
    price_up = sum(cf * bumped.discount(t) for t, cf in cashflows)
    ir_dv01 = abs(price - price_up)

    accrued = 0.0                                       # valued at a reset date
    return dict(price=price, clean_price=price - accrued, dirty_price=price,
                accrued_interest=accrued, float_pv=float_pv, spread_pv=spread_pv,
                redemption_pv=redemption_pv,
                dv01=ir_dv01, ir_dv01=ir_dv01,
                spread_dv01=face * annuity / 10000,
                discount_margin=spread, yield_=None,
                duration=dt, annuity=annuity,
                cashflows=cashflows)


def fra(notional: float, K: float, T1: float, T2: float, curve: YieldCurve,
        proj_curve: YieldCurve | None = None) -> dict:
    """
    Forward Rate Agreement: pay fixed K, receive the simple forward set at T1 for
    [T1, T2], settled (PV) at T2. Dual-curve: forward from proj_curve, discount
    from curve (proj defaults to the discount curve = single-curve).
    """
    proj = proj_curve or curve
    tau = T2 - T1
    df1p, df2p = proj.discount(T1), proj.discount(T2)
    fwd = (df1p / df2p - 1.0) / tau if tau > 0 else 0.0   # projection-curve forward
    df2 = curve.discount(T2)                              # discount curve
    npv = notional * (fwd - K) * tau * df2
    dv01 = notional * tau * df2 / 10000
    return dict(npv=npv, forward_rate=fwd, dv01=dv01, tau=tau)


# ─────────────────────────────────────────────────────────
# Callable / putable bonds + OAS (FI-6) — BDT short-rate tree
# ─────────────────────────────────────────────────────────

def _bdt_tree(curve: YieldCurve, sigma: float, n: int, T: float):
    """
    Black-Derman-Toy short-rate binomial tree calibrated to the discount curve.
    Returns r[i][j] (short rate at step i, state j) and dt. p = 0.5; up -> j+1.
    """
    dt = T / n
    sq = np.sqrt(dt)
    r = [[0.0] * (i + 1) for i in range(n)]
    q = [1.0]                                   # Arrow-Debreu state prices at step 0
    for i in range(n):
        target = curve.discount((i + 1) * dt)

        def df_for(rm, _i=i):
            return sum(q[j] * np.exp(-rm * np.exp(2 * j * sigma * sq) * dt) for j in range(_i + 1))

        rm = brentq(lambda x: df_for(x) - target, 1e-9, 5.0)
        for j in range(i + 1):
            r[i][j] = rm * np.exp(2 * j * sigma * sq)
        qn = [0.0] * (i + 2)                     # propagate state prices forward
        for j in range(i + 1):
            d = np.exp(-r[i][j] * dt)
            qn[j] += 0.5 * q[j] * d
            qn[j + 1] += 0.5 * q[j] * d
        q = qn
    return r, dt


def callable_bond(face: float, coupon: float, T: float, freq: int, curve: YieldCurve,
                  sigma: float = 0.15, call_price: float | None = None, call_start: float = 0.0,
                  put_price: float | None = None, put_start: float = 0.0,
                  option: str = "callable", m: int = 2,
                  market_price: float | None = None) -> dict:
    """
    Callable / putable bond via a BDT tree with optimal exercise and OAS.
    OAS solves model(option) price == market_price (default: the straight value,
    so a callable returns a negative OAS reflecting the embedded option cost).
    """
    periods = int(round(T * freq))
    n = periods * m
    r, dt = _bdt_tree(curve, sigma, n, T)
    cpn = face * coupon / freq
    cpn_steps = {p * m for p in range(1, periods + 1)}

    def value(oas: float, exercise: bool) -> float:
        V = [face + cpn] * (n + 1)
        for k in range(n - 1, -1, -1):
            add = cpn if k in cpn_steps else 0.0
            t = k * dt
            Vn = [0.0] * (k + 1)
            for j in range(k + 1):
                cont = np.exp(-(r[k][j] + oas) * dt) * 0.5 * (V[j] + V[j + 1])
                v = cont + add
                if exercise and k > 0:
                    if option == "callable" and call_price is not None and t >= call_start - 1e-9:
                        v = min(v, call_price + add)
                    elif option == "putable" and put_price is not None and t >= put_start - 1e-9:
                        v = max(v, put_price + add)
                Vn[j] = v
            V = Vn
        return V[0]

    straight = value(0.0, exercise=False)
    optioned = value(0.0, exercise=True)
    mkt = market_price if market_price is not None else straight
    try:
        oas = brentq(lambda s: value(s, exercise=True) - mkt, -0.5, 0.5)
    except ValueError:
        oas = float("nan")
    return dict(price=optioned, clean_price=optioned, dirty_price=optioned, accrued_interest=0.0,
                straight_value=straight, option_value=abs(straight - optioned), oas=oas,
                sigma=sigma, market_price=mkt,
                callable_value=optioned if option == "callable" else None,
                putable_value=optioned if option == "putable" else None)


# ─────────────────────────────────────────────────────────
# Interest rate futures (FI-5)
# ─────────────────────────────────────────────────────────

def bond_future(deliverables: list, futures_price: float, repo_rate: float,
                T_delivery: float, target_bpv: float | None = None) -> dict:
    """
    Bond future with cheapest-to-deliver (CTD) analysis.
    deliverables: [{name, clean_price, accrued, conversion_factor, coupon_income, dv01}].
    Returns CTD, theoretical futures, invoice, net/gross basis, implied repo,
    futures DV01 and (optional) hedge ratio for a target BPV.
    """
    analysis = []
    for b in deliverables:
        cf = b["conversion_factor"]
        full = b["clean_price"] + b.get("accrued", 0.0)
        fwd = full * (1 + repo_rate * T_delivery) - b.get("coupon_income", 0.0)
        gross_basis = b["clean_price"] - futures_price * cf
        net_basis = fwd - futures_price * cf
        invoice = futures_price * cf + b.get("accrued", 0.0)
        implied_repo = (((futures_price * cf + b.get("coupon_income", 0.0)) / full - 1) / T_delivery
                        if full > 0 and T_delivery > 0 else 0.0)
        analysis.append({**b, "forward_price": fwd, "gross_basis": gross_basis,
                         "net_basis": net_basis, "invoice_price": invoice,
                         "implied_repo": implied_repo})
    ctd = min(analysis, key=lambda a: a["net_basis"])     # min net basis = max implied repo
    cf = ctd["conversion_factor"]
    theo = ctd["forward_price"] / cf if cf else 0.0
    futures_dv01 = ctd.get("dv01", 0.0) / cf if cf else 0.0
    hedge_ratio = (target_bpv / futures_dv01) if (target_bpv and futures_dv01) else None
    return dict(price=theo, theoretical_futures=theo, futures_price=futures_price,
                ctd=ctd.get("name", "CTD"), conversion_factor=cf,
                invoice_price=ctd["invoice_price"], net_basis=ctd["net_basis"],
                gross_basis=ctd["gross_basis"], implied_repo=ctd["implied_repo"],
                futures_dv01=futures_dv01, hedge_ratio=hedge_ratio, analysis=analysis)


def stir_future(forward_rate: float, notional: float = 1_000_000,
                tenor: float = 0.25) -> dict:
    """Short-term interest-rate future: price = 100*(1-rate); DV01 = N*tenor*1bp."""
    price = 100.0 * (1 - forward_rate)
    dv01 = notional * tenor * 0.0001
    return dict(price=price, futures_price=price, implied_rate=forward_rate,
                dv01=dv01, pv01=dv01, bpv=dv01, notional=notional, tenor=tenor)


# ─────────────────────────────────────────────────────────
# Repo / reverse repo (FI-4)
# ─────────────────────────────────────────────────────────

def repo(spot: float, repo_rate: float, T: float, coupon_income: float = 0.0,
         direction: str = "repo") -> dict:
    """
    Repo / reverse repo on bond collateral (cash-and-carry).
    spot: dirty price (cash exchanged at start). repo_rate: financing rate (simple).
    T: term in years. coupon_income: collateral coupons paid during the term.
    direction: 'repo' (finance a long) | 'reverse' (lend cash vs collateral).
    """
    financing_cost = spot * repo_rate * T
    forward_price = spot * (1 + repo_rate * T) - coupon_income
    carry = coupon_income - financing_cost            # net carry of financing the bond
    funding_dv01 = spot * T / 10000                    # sensitivity to the repo rate
    sign = 1 if direction == "repo" else -1
    return dict(price=forward_price, forward_price=forward_price, npv=sign * carry,
                repo_rate=repo_rate, financing_cost=financing_cost, carry=sign * carry,
                funding_dv01=funding_dv01, term=T, direction=direction)


# ─────────────────────────────────────────────────────────
# Money market (FI-3): deposit, commercial paper, treasury bill
# ─────────────────────────────────────────────────────────

def mm_deposit(notional: float, rate: float, T: float, curve: YieldCurve) -> dict:
    """Term money-market deposit: simple interest to maturity, PV on the curve."""
    maturity_value = notional * (1 + rate * T)
    disc = curve.discount(T)
    npv = maturity_value * disc
    dv01 = maturity_value * T * disc / 10000
    return dict(npv=npv, price=npv, clean_price=npv, dirty_price=npv,
                accrued_interest=0.0, maturity_value=maturity_value, yield_=rate,
                dv01=dv01, pv01=dv01, bpv=dv01)


def treasury_bill(face: float, discount_rate: float, T: float,
                  curve: YieldCurve | None = None) -> dict:
    """Discount T-bill: price on discount basis; discount yield, MM yield, BEY."""
    price = face * (1 - discount_rate * T)
    mmy = (face - price) / price / T if price > 0 and T > 0 else 0.0   # money-market yield
    bey = (face / price - 1) / T if price > 0 and T > 0 else 0.0        # bond-equivalent (act/365)
    dv01 = face * T / 10000
    return dict(price=price, clean_price=price, dirty_price=price, accrued_interest=0.0,
                discount_yield=discount_rate, money_market_yield=mmy, bey=bey, yield_=bey,
                dv01=dv01, pv01=dv01, bpv=dv01)


def commercial_paper(face: float, discount_rate: float, T: float,
                     curve: YieldCurve | None = None) -> dict:
    """Discount commercial paper: price, discount yield, money-market yield."""
    price = face * (1 - discount_rate * T)
    mmy = (face - price) / price / T if price > 0 and T > 0 else 0.0
    dv01 = face * T / 10000
    return dict(price=price, clean_price=price, dirty_price=price, accrued_interest=0.0,
                discount_yield=discount_rate, money_market_yield=mmy, yield_=mmy,
                dv01=dv01, pv01=dv01, bpv=dv01)


# ─────────────────────────────────────────────────────────
# Bond family (FI-2): shared metric builder + new structures
# ─────────────────────────────────────────────────────────

def metrics_from_cashflows(cashflows: list, curve: YieldCurve, face: float, freq: int) -> dict:
    """Unified §6 metric set for any deterministic bond cashflow stream."""
    from instruments.fixed_income_analytics import (
        bond_yield, effective_duration_convexity, key_rate_durations,
    )
    price = _price_cashflows(cashflows, curve)
    ytm = bond_yield(cashflows, price, freq)
    pv_t = sum(c * curve.discount(t) * t for t, c in cashflows)
    mac = pv_t / price if price else 0.0
    mod = mac / (1 + ytm / freq) if ytm == ytm else mac
    reprice = lambda sh: _price_cashflows(cashflows, curve.parallel_shift(sh * 1e4))
    eff_dur, eff_cvx = effective_duration_convexity(reprice, price)
    dv01 = (reprice(-1e-4) - reprice(1e-4)) / 2.0
    krd = key_rate_durations(cashflows, curve, price, _price_cashflows)
    return dict(price=price, clean_price=price, dirty_price=price, accrued_interest=0.0,
                ytm=ytm, yield_=ytm, mac_duration=mac, mod_duration=mod,
                effective_duration=eff_dur, convexity=eff_cvx,
                dv01=dv01, pv01=dv01, bpv=dv01, key_rate_durations=krd,
                cash_flows=cashflows)


def period_accrual(freq: int, day_count: str = "act365") -> float:
    """Per-coupon-period accrual fraction tau for a regular schedule and convention."""
    dc = str(day_count).lower().replace("/", "").replace("_", "").replace(" ", "")
    days = 365.0 / freq                                   # nominal regular-period length
    if dc in ("act360", "actual360"):
        return days / 360.0
    if dc in ("30360", "thirty360", "bond", "30360bond"):
        return 1.0 / freq
    if dc in ("actact", "actualactual"):
        return 1.0 / freq
    # act/365(F) and default
    return days / 365.0


def custom_bond(cashflows: list, curve: YieldCurve, freq: int = 2) -> dict:
    """Price an arbitrary user-supplied cashflow schedule [(t_years, amount), ...]."""
    cfs = sorted((float(t), float(a)) for t, a in cashflows)
    face = cfs[-1][1] if cfs else 0.0
    res = metrics_from_cashflows(cfs, curve, face, freq)
    res["custom"] = True
    return res


def amortizing_bond(face: float, coupon: float, T: float, freq: int,
                    curve: YieldCurve, amort_type: str = "linear",
                    day_count: str = "act365") -> dict:
    """Amortizing bond: principal repaid over life (linear or level-annuity)."""
    n = int(round(T * freq)); dt = 1.0 / freq
    cfs: list[tuple[float, float]] = []
    outstanding = face
    c = coupon * period_accrual(freq, day_count)
    if amort_type == "annuity" and c > 0:
        A = face * c / (1 - (1 + c) ** (-n))
        for i in range(1, n + 1):
            interest = outstanding * c
            principal = A - interest
            outstanding -= principal
            cfs.append((i * dt, A))
    else:
        principal = face / n
        for i in range(1, n + 1):
            interest = outstanding * c
            outstanding -= principal
            cfs.append((i * dt, principal + interest))
    res = metrics_from_cashflows(cfs, curve, face, freq)
    res["amort_type"] = amort_type
    return res


def step_bond(face: float, coupon_steps: list, T: float, freq: int,
              curve: YieldCurve, day_count: str = "act365") -> dict:
    """Step-up/step-down bond. coupon_steps: [(effective_from_year, annual_rate), ...]."""
    n = int(round(T * freq)); dt = 1.0 / freq
    tau = period_accrual(freq, day_count)
    steps = sorted(coupon_steps, key=lambda s: s[0])

    def rate_at(t):
        r = steps[0][1]
        for start, rr in steps:
            if t >= start - 1e-9:
                r = rr
        return r

    cfs = []
    for i in range(1, n + 1):
        t = i * dt
        amt = face * rate_at(t) * tau
        if i == n:
            amt += face
        cfs.append((t, amt))
    res = metrics_from_cashflows(cfs, curve, face, freq)
    res["coupon_steps"] = steps
    return res


def perpetual_bond(face: float, coupon: float, curve: YieldCurve, freq: int = 1) -> dict:
    """Perpetual / consol: infinite level coupon, value = C / y."""
    y = curve.par_rate(30, freq)
    C = face * coupon
    price = C / y if y > 0 else float("inf")
    mod = 1.0 / y if y > 0 else float("inf")
    mac = mod * (1 + y / freq)
    dv01 = C / (y * y) * 1e-4 if y > 0 else float("inf")
    return dict(price=price, clean_price=price, dirty_price=price, accrued_interest=0.0,
                ytm=y, yield_=y, mac_duration=mac, mod_duration=mod,
                effective_duration=mod, convexity=2.0 / y**2 if y > 0 else float("inf"),
                dv01=dv01, pv01=dv01, bpv=dv01, key_rate_durations={})


def inflation_linked_bond(face: float, real_coupon: float, T: float, freq: int,
                          curve: YieldCurve, base_cpi: float = 100.0,
                          current_cpi: float = 100.0, inflation_rate: float = 0.04,
                          day_count: str = "act365") -> dict:
    """
    Inflation-linked bond: principal indexed to CPI (projected at inflation_rate),
    real coupons on the indexed principal, discounted on the nominal curve.
    """
    n = int(round(T * freq)); dt = 1.0 / freq
    tau = period_accrual(freq, day_count)
    ratio0 = current_cpi / base_cpi
    cfs = []
    for i in range(1, n + 1):
        t = i * dt
        idx = ratio0 * (1 + inflation_rate) ** t
        principal_t = face * idx
        amt = principal_t * real_coupon * tau
        if i == n:
            amt += principal_t
        cfs.append((t, amt))
    res = metrics_from_cashflows(cfs, curve, face, freq)
    # inflation DV01: reprice under a +1bp inflation bump
    bumped = []
    for i in range(1, n + 1):
        t = i * dt
        idx = ratio0 * (1 + inflation_rate + 1e-4) ** t
        principal_t = face * idx
        amt = principal_t * real_coupon * tau
        if i == n:
            amt += principal_t
        bumped.append((t, amt))
    res["inflation_dv01"] = _price_cashflows(bumped, curve) - res["price"]
    res["real_dv01"] = res["dv01"]
    res["indexed_principal"] = face * ratio0
    res["index_ratio"] = ratio0
    res["real_yield"] = res["ytm"] - inflation_rate
    res["inflation_rate"] = inflation_rate
    return res


# ─────────────────────────────────────────────────────────
# Interest rate swap (IRS)
# ─────────────────────────────────────────────────────────

def irs(notional: float, fixed_rate: float, T: float, freq: int,
        curve: YieldCurve, pay_fixed: bool = True,
        proj_curve: YieldCurve | None = None) -> dict:
    """
    Vanilla IRS: fixed vs floating. Dual-curve: floating leg projected on
    proj_curve, both legs discounted on curve (proj defaults to discount curve).
    Returns fair swap rate, NPV, DV01, BPV.
    """
    proj    = proj_curve or curve
    dt      = 1.0 / freq
    periods = int(round(T * freq))
    times   = [i*dt for i in range(1, periods+1)]

    # annuity (PV of fixed leg basis) on the discount curve
    annuity = sum(dt * curve.discount(t) for t in times)
    # floating leg: simple forwards from the projection curve, each coupon
    # discounted on the discount curve. Single-curve this telescopes exactly to
    # 1 - P(T) (replacing the old P(0.001)-P(T) approximation); dual-curve it is
    # the correct projected-and-discounted sum rather than a proj-only telescope.
    float_pv = sum((proj.discount((i-1)*dt) / proj.discount(i*dt) - 1.0)
                   * curve.discount(i*dt) for i in range(1, periods+1))

    fair_rate = float_pv / annuity
    fixed_pv  = fixed_rate * annuity * notional
    float_pv_n= float_pv * notional

    npv = (float_pv_n - fixed_pv) if pay_fixed else (fixed_pv - float_pv_n)

    dv01 = notional * annuity / 10000

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
               curve1: YieldCurve, curve2: YieldCurve,
               disc_curve: YieldCurve | None = None) -> dict:
    """
    Basis swap: receive floating(curve2) + spread, pay floating(curve1).
    Legs are built from simple projected forwards on each index curve and BOTH
    discounted on a common discount curve (default curve1). The old FRN-based
    construction collapsed both legs to par (face) regardless of the curves,
    so npv ignored the basis and fair_spread was identically zero.
    """
    disc = disc_curve or curve1
    dt = 1.0 / freq
    periods = int(round(T * freq))
    pv1 = pv2 = annuity = 0.0
    for i in range(1, periods + 1):
        t0, t1 = (i - 1) * dt, i * dt
        df = disc.discount(t1)
        f1 = (curve1.discount(t0) / curve1.discount(t1) - 1.0) / dt
        f2 = (curve2.discount(t0) / curve2.discount(t1) - 1.0) / dt
        pv1 += f1 * dt * df
        pv2 += (f2 + spread) * dt * df
        annuity += dt * df
    npv = notional * (pv2 - pv1)
    # spread on leg2 that sets npv = 0 (negative when curve2 projects above curve1)
    fair_spread = (pv1 - (pv2 - spread * annuity)) / annuity if annuity > 0 else float("nan")
    return dict(npv=npv, fair_spread=fair_spread,
                leg1_pv=notional * pv1, leg2_pv=notional * pv2,
                annuity=annuity, dv01=notional * annuity / 10000)


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
              curve: YieldCurve, vol_curve, opt: str = "cap",
              proj_curve: YieldCurve | None = None) -> dict:
    """
    Cap/Floor as a strip of caplets. Dual-curve: forwards from proj_curve,
    discounting from curve (proj defaults to the discount curve).
    vol_curve: callable(T) → vol, or constant float.
    """
    proj  = proj_curve or curve
    dt    = 1.0 / freq
    total = 0.0
    total_delta = 0.0
    caplets = []
    for i in range(1, int(round(T*freq))+1):
        T1 = (i-1)*dt; T2 = i*dt
        # Market convention prices the caplet on the SIMPLE forward
        # (P(T1)/P(T2)-1)/tau, not the continuously-compounded forward
        # (curve.forward_rate default) — at 10% rates the gap is ~12bp on the
        # forward and made ATM cap == floor identically, breaking
        # cap - floor = swap parity. Vol is looked up at the caplet EXPIRY T1.
        fwd  = (proj.discount(T1) / proj.discount(T2) - 1.0) / (T2 - T1)
        disc = curve.discount(T2)
        sigma = vol_curve(T1) if callable(vol_curve) else vol_curve
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

    # Black-76 with r=0: the annuity is the numeraire and carries ALL discounting,
    # so the option must be the *undiscounted* forward value (else double-discounting
    # by disc(T_option) breaks payer-receiver parity). Cf. the caplet fix.
    g       = black76(S0, K, T_option, 0.0, sigma,
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
# CMS (Constant Maturity Swap) — convexity adjustment + swap (Phase 2)
# ─────────────────────────────────────────────────────────

def cms_convexity_adjustment(S0: float, sigma: float, T_fix: float,
                             swap_tenor: float, freq: int = 2) -> float:
    """
    CMS convexity adjustment (Hull Ch. 30 bond-yield model):
      adj = -0.5 · S0² · σ² · T_fix · G''(S0)/G'(S0),
    where G(y) prices the underlying par swap's bond at flat yield y
    (coupon = S0). G' < 0, G'' > 0, so the adjustment is positive: the CMS
    rate paid at a single date exceeds the forward swap rate.
    """
    m = freq
    n = int(round(swap_tenor * m))

    def G(y: float) -> float:
        return (sum((S0 / m) / (1 + y / m) ** i for i in range(1, n + 1))
                + 1.0 / (1 + y / m) ** n)

    h = max(1e-5, S0 * 1e-3)
    g_p = (G(S0 + h) - G(S0 - h)) / (2 * h)
    g_pp = (G(S0 + h) - 2 * G(S0) + G(S0 - h)) / (h * h)
    return -0.5 * S0**2 * sigma**2 * T_fix * g_pp / g_p


def cms_timing_adjustment(S0: float, sigma_S: float, F_lag: float,
                          sigma_F: float, rho: float, T_fix: float,
                          tau_lag: float) -> float:
    """
    Timing adjustment when the CMS rate observed at T_fix is paid at
    T_pay = T_fix + tau_lag (Hull Ch. 30.3):
      ΔS = -S0·σ_S·σ_F·ρ·T_fix·τ·F/(1 + τ·F).
    Zero when there is no payment lag.
    """
    if tau_lag <= 0 or T_fix <= 0:
        return 0.0
    return (-S0 * sigma_S * sigma_F * rho * T_fix
            * tau_lag * F_lag / (1.0 + tau_lag * F_lag))


def cms_swaplet(notional: float, T_fix: float, T_pay: float, swap_tenor: float,
                freq: int, curve: YieldCurve, sigma, tau: float | None = None,
                rho_timing: float = 1.0) -> dict:
    """
    Single CMS coupon: the swap_tenor-year swap rate observed at T_fix, paid at
    T_pay on accrual tau. Expected rate = forward swap rate + convexity adj
    + timing adj for the T_fix -> T_pay payment lag (Stage A).
    sigma: scalar swap-rate vol, or callable sigma(T_fix, swap_tenor) — e.g.
    a SwaptionCube.atm_vol lookup.
    """
    dt = 1.0 / freq
    periods = int(round(swap_tenor * freq))
    times = [T_fix + i * dt for i in range(1, periods + 1)]
    annuity = sum(dt * curve.discount(t) for t in times)
    S0 = ((curve.discount(T_fix) - curve.discount(T_fix + swap_tenor)) / annuity
          if annuity > 0 else 0.0)
    sigma_val = sigma(T_fix, swap_tenor) if callable(sigma) else float(sigma)
    adj = (cms_convexity_adjustment(S0, sigma_val, T_fix, swap_tenor, freq)
           if T_fix > 0 else 0.0)
    tau = dt if tau is None else tau
    tau_lag = max(T_pay - T_fix, 0.0)
    timing = 0.0
    if tau_lag > 1e-12 and T_fix > 0:
        F_lag = ((curve.discount(T_fix) / curve.discount(T_pay) - 1.0) / tau_lag
                 if tau_lag > 0 else 0.0)
        # forward-rate vol proxied by the swap-rate vol, rho_timing default 1
        # (both driven by the same curve) — documented approximation
        timing = cms_timing_adjustment(S0, sigma_val, F_lag, sigma_val,
                                       rho_timing, T_fix, tau_lag)
    expected = S0 + adj + timing
    pv = notional * tau * expected * curve.discount(T_pay)
    return dict(pv=pv, forward_swap_rate=S0, convexity_adjustment=adj,
                timing_adjustment=timing, expected_cms_rate=expected,
                sigma=sigma_val, T_fix=T_fix, T_pay=T_pay)


def cms_swap(notional: float, K: float, T: float, freq: int, swap_tenor: float,
             curve: YieldCurve, sigma, pay_fixed: bool = True) -> dict:
    """
    CMS swap: receive the swap_tenor-year CMS rate each period, pay fixed K.
    Each fixing carries its own convexity + timing adjustment; sigma may be a
    scalar or a callable sigma(T_fix, swap_tenor) backed by a SwaptionCube.
    """
    dt = 1.0 / freq
    n = int(round(T * freq))
    pv_cms, annuity = 0.0, 0.0
    coupons = []
    for i in range(1, n + 1):
        t_fix, t_pay = (i - 1) * dt, i * dt
        leg = cms_swaplet(notional, t_fix, t_pay, swap_tenor, freq, curve, sigma, tau=dt)
        pv_cms += leg["pv"]
        annuity += dt * curve.discount(t_pay)
        coupons.append(leg)
    pv_fixed = notional * K * annuity
    npv = (pv_cms - pv_fixed) if pay_fixed else (pv_fixed - pv_cms)
    fair = pv_cms / (notional * annuity) if annuity > 0 else float("nan")
    total_adj = sum(c["convexity_adjustment"] for c in coupons) / max(len(coupons), 1)
    total_timing = sum(c["timing_adjustment"] for c in coupons) / max(len(coupons), 1)
    return dict(npv=npv, fair_rate=fair, pv_cms_leg=pv_cms, pv_fixed_leg=pv_fixed,
                annuity=annuity, avg_convexity_adjustment=total_adj,
                avg_timing_adjustment=total_timing, coupons=coupons)


# ─────────────────────────────────────────────────────────
# CMS spread option
# ─────────────────────────────────────────────────────────

def cms_spread_option(S1: float, S2: float, K: float, T: float, r: float,
                      sigma1: float, sigma2: float, rho: float,
                      opt: str = "call") -> dict:
    """
    CMS spread option: max(CMS1 - CMS2 - K, 0) via Kirk approximation.
    """
    from instruments.multi_asset import spread_option_kirk
    return spread_option_kirk(S1, S2, K, T, r, sigma1, sigma2, rho)
