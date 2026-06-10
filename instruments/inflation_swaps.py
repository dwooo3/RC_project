"""
Inflation swaps (Phase 2) — priced off the (nominal, real) curve pair
introduced in Phase 1 (curves.inflation).

- Zero-coupon inflation swap (ZCIIS): at T exchange fixed (1+K)^T - 1 for
  I(T)/I(0) - 1. The fair K equals the curve breakeven exactly (identity).
- Year-on-year swap (YoYIIS): each period exchanges fixed K for the YoY index
  ratio I(t_i)/I(t_{i-1}) - 1. Period ratios are projected from forward
  breakevens; the YoY convexity adjustment is NOT applied (registry note).
"""

import numpy as np

from curves.yield_curve import YieldCurve
from curves.inflation import breakeven_rate


def zc_inflation_swap(notional: float, K: float, T: float,
                      nominal_curve: YieldCurve, real_curve: YieldCurve,
                      pay_fixed: bool = True) -> dict:
    """
    Zero-coupon inflation swap. Inflation-leg projection from the curve pair:
    E[I(T)/I(0)] = exp((r_nom - r_real)·T). NPV from the fixed payer's side.
    """
    df = nominal_curve.discount(T)
    index_growth = np.exp((nominal_curve.rate(T) - real_curve.rate(T)) * T)
    fixed_growth = (1.0 + K) ** T
    npv = notional * df * (index_growth - fixed_growth)
    if not pay_fixed:
        npv = -npv
    fair = breakeven_rate(nominal_curve, real_curve, T)
    # inflation DV01: +1bp parallel breakeven (real curve -1bp at fixed nominal)
    bumped_growth = np.exp((nominal_curve.rate(T) - (real_curve.rate(T) - 1e-4)) * T)
    inf_dv01 = notional * df * (bumped_growth - index_growth) * (1 if pay_fixed else -1)
    return dict(npv=npv, fair_rate=fair, index_growth=index_growth,
                fixed_growth=fixed_growth, inflation_dv01=inf_dv01,
                breakeven=fair, pay_fixed=pay_fixed)


def yoy_inflation_swap(notional: float, K: float, T: float, freq: int,
                       nominal_curve: YieldCurve, real_curve: YieldCurve,
                       pay_fixed: bool = True) -> dict:
    """
    Year-on-year inflation swap: per period receive [I(t_i)/I(t_{i-1}) - 1],
    pay K·tau. Period index ratios from forward breakevens (no convexity
    adjustment — needs an inflation vol model).
    """
    dt = 1.0 / freq
    n = int(round(T * freq))
    pv_inflation, annuity = 0.0, 0.0
    periods = []
    for i in range(1, n + 1):
        t0, t1 = (i - 1) * dt, i * dt
        growth0 = np.exp((nominal_curve.rate(t0) - real_curve.rate(t0)) * t0) if t0 > 0 else 1.0
        growth1 = np.exp((nominal_curve.rate(t1) - real_curve.rate(t1)) * t1)
        yoy = growth1 / growth0 - 1.0                 # period inflation
        df = nominal_curve.discount(t1)
        pv_inflation += yoy * df
        annuity += dt * df
        periods.append(dict(t=t1, yoy=yoy, df=df))
    npv = notional * (pv_inflation - K * annuity)
    if not pay_fixed:
        npv = -npv
    fair = pv_inflation / annuity if annuity > 0 else float("nan")
    return dict(npv=npv, fair_rate=fair, annuity=annuity,
                pv_inflation_leg=notional * pv_inflation,
                pv_fixed_leg=notional * K * annuity,
                periods=periods, pay_fixed=pay_fixed)
