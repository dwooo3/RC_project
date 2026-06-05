"""
Shared fixed-income analytics (Phase FI-1).

Pure, reusable functions applied across all bond pricers: yield solvers
(YTM/YTC/YTP/YTW), effective & key-rate duration/convexity via curve bumps, and
spread analytics (G-spread, I-spread, ASW). Engines stay thin; these provide the
unified §6 risk-metric set.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

from curves.yield_curve import YieldCurve

Cashflows = list[tuple[float, float]]   # [(time_years, amount), ...]


# ── yield solvers ─────────────────────────────────────────
def bond_yield(cashflows: Cashflows, price: float, freq: int = 2) -> float:
    """Internal yield (YTM) solving PV(cashflows @ y) = price."""
    def f(y):
        return sum(c / (1 + y / freq) ** (freq * t) for t, c in cashflows) - price
    try:
        return brentq(f, -0.99 * freq, 1.0)
    except ValueError:
        return float("nan")


def yield_to_workout(cashflows: Cashflows, price: float, workout_t: float,
                     redemption: float, freq: int = 2) -> float:
    """
    Yield to a workout date (call/put): keep coupons strictly before workout_t,
    redeem `redemption` (call/put price incl. final coupon) at workout_t.
    """
    cfs = [(t, c) for t, c in cashflows if t < workout_t - 1e-9]
    cfs.append((workout_t, redemption))
    return bond_yield(cfs, price, freq)


def yield_to_worst(cashflows: Cashflows, price: float, freq: int,
                   call_schedule: list[tuple[float, float]] | None = None,
                   put_schedule: list[tuple[float, float]] | None = None) -> dict:
    """
    YTM plus yield to each call/put workout; YTW = min over all workouts.
    *_schedule: [(time_years, redemption_price_per_face_unit_incl_final_coupon)].
    """
    ytm = bond_yield(cashflows, price, freq)
    ytc = min((yield_to_workout(cashflows, price, t, red, freq)
               for t, red in (call_schedule or [])), default=None)
    ytp = max((yield_to_workout(cashflows, price, t, red, freq)
               for t, red in (put_schedule or [])), default=None)
    candidates = [y for y in (ytm, ytc, ytp) if y is not None and y == y]
    ytw = min(candidates) if candidates else ytm
    return {"ytm": ytm, "ytc": ytc, "ytp": ytp, "ytw": ytw}


# ── curve-bump risk ───────────────────────────────────────
def _bump_node(curve: YieldCurve, i: int, dy: float) -> YieldCurve:
    zr = np.array(curve.zero_rates, dtype=float)
    zr[i] += dy
    return YieldCurve(curve.tenors, zr, label=curve.label,
                      interp=getattr(curve, "_interp", "cubic"), rate_type="zero")


def effective_duration_convexity(reprice_shift, base_price: float, dy: float = 1e-4):
    """
    reprice_shift(shift_decimal) -> price under a parallel zero-rate shift.
    Returns (effective_duration, effective_convexity).
    """
    p_up = reprice_shift(+dy)
    p_dn = reprice_shift(-dy)
    if base_price == 0:
        return 0.0, 0.0
    eff_dur = (p_dn - p_up) / (2 * base_price * dy)
    eff_cvx = (p_up + p_dn - 2 * base_price) / (base_price * dy * dy)
    return eff_dur, eff_cvx


def key_rate_durations(cashflows: Cashflows, curve: YieldCurve, base_price: float,
                       price_on_curve, dy: float = 1e-4) -> dict[float, float]:
    """
    Per-node key-rate duration: bump each curve tenor in turn, reprice.
    price_on_curve(cashflows, curve) -> price. Sum(KRD) ~ effective duration.
    """
    krd: dict[float, float] = {}
    for i, t in enumerate(curve.tenors):
        p_up = price_on_curve(cashflows, _bump_node(curve, i, +dy))
        p_dn = price_on_curve(cashflows, _bump_node(curve, i, -dy))
        krd[float(t)] = (p_dn - p_up) / (2 * base_price * dy) if base_price else 0.0
    return krd


# ── spread analytics ──────────────────────────────────────
def g_spread(bond_ytm: float, govt_curve: YieldCurve, T: float, freq: int = 2) -> float:
    """Bond YTM minus the benchmark government par yield at the same tenor."""
    return bond_ytm - govt_curve.par_rate(T, freq)


def i_spread(bond_ytm: float, swap_curve: YieldCurve, T: float, freq: int = 2) -> float:
    """Bond YTM minus the par swap rate at the same tenor."""
    return bond_ytm - swap_curve.par_rate(T, freq)


def asw_spread(cashflows: Cashflows, dirty_price: float, face: float,
               swap_curve: YieldCurve) -> float:
    """
    Par/par asset-swap spread approximation:
        ASW = (fixed_coupon_PV - (face - dirty)) / annuity - par_swap_proxy
    Expressed as a spread over the floating leg. Uses swap-curve discounting.
    """
    annuity = sum((cashflows[k][0] - (cashflows[k - 1][0] if k else 0.0))
                  * swap_curve.discount(cashflows[k][0]) for k in range(len(cashflows)))
    if annuity <= 0:
        return float("nan")
    coupon_pv = sum(c * swap_curve.discount(t) for t, c in cashflows)
    # value of paying par-floating + receiving bond coupons, net of upfront
    upfront = face - dirty_price
    return (coupon_pv - face + upfront) / (face * annuity)
