"""
Real-rate / inflation curve construction (Phase 1).

A real curve (e.g. from OFZ-IN linkers) plus the nominal curve defines the
breakeven inflation term structure via the Fisher relation in continuous
compounding:  be(T) = exp(r_nom(T) - r_real(T)) - 1.
Index-ratio projection then replaces the flat inflation-rate assumption in
inflation-linked bond pricing.
"""

import numpy as np

from curves.yield_curve import YieldCurve


def breakeven_rate(nominal_curve: YieldCurve, real_curve: YieldCurve, T: float) -> float:
    """Annualized breakeven inflation for maturity T (Fisher, continuous zeros)."""
    return float(np.exp(nominal_curve.rate(T) - real_curve.rate(T)) - 1.0)


def breakeven_curve(nominal_curve: YieldCurve, real_curve: YieldCurve,
                    tenors=None) -> dict:
    """Breakeven inflation term structure {T: be(T)}."""
    tenors = tenors if tenors is not None else [1, 2, 3, 5, 7, 10]
    return {T: breakeven_rate(nominal_curve, real_curve, T) for T in tenors}


def real_curve_from_breakeven(nominal_curve: YieldCurve, tenors, breakevens,
                              label: str = "real from breakeven",
                              **curve_kwargs) -> YieldCurve:
    """Build a real zero curve from the nominal curve and breakeven quotes."""
    rates = [nominal_curve.rate(T) - np.log(1.0 + be)
             for T, be in zip(tenors, breakevens)]
    return YieldCurve(tenors, rates, label=label, **curve_kwargs)


def index_ratio(nominal_curve: YieldCurve, real_curve: YieldCurve, T: float,
                base_ratio: float = 1.0) -> float:
    """
    Risk-neutral projected CPI index ratio I(T)/I(base):
    I(T)/I(0) = exp((r_nom(T) - r_real(T)) * T), seasoning via base_ratio.
    """
    if T <= 0:
        return base_ratio
    return float(base_ratio * np.exp((nominal_curve.rate(T) - real_curve.rate(T)) * T))


def inflation_linked_bond_curve(face: float, real_coupon: float, T: float, freq: int,
                                nominal_curve: YieldCurve, real_curve: YieldCurve,
                                base_cpi: float = 100.0, current_cpi: float = 100.0,
                                day_count: str = "act365") -> dict:
    """
    Inflation-linked bond priced off the (nominal, real) curve pair: cashflows are
    indexed by the curve-implied index ratio and discounted on the nominal curve —
    equivalent to discounting real cashflows on the real curve. Replaces the flat
    assumed-inflation projection.
    """
    from instruments.fixed_income import metrics_from_cashflows, period_accrual

    n = int(round(T * freq))
    dt = 1.0 / freq
    tau = period_accrual(freq, day_count)
    ratio0 = current_cpi / base_cpi

    def cashflows(real_bump: float = 0.0) -> list:
        cfs = []
        for i in range(1, n + 1):
            t = i * dt
            idx = ratio0 * np.exp((nominal_curve.rate(t) - (real_curve.rate(t) + real_bump)) * t)
            principal_t = face * idx
            amt = principal_t * real_coupon * tau
            if i == n:
                amt += principal_t
            cfs.append((t, amt))
        return cfs

    res = metrics_from_cashflows(cashflows(), nominal_curve, face, freq)
    # inflation DV01: +1bp breakeven == -1bp real rate at fixed nominal
    res["inflation_dv01"] = (
        sum(a * nominal_curve.discount(t) for t, a in cashflows(real_bump=-1e-4))
        - res["price"]
    )
    res["real_dv01"] = -res["inflation_dv01"]
    res["index_ratio"] = ratio0
    res["indexed_principal"] = face * ratio0
    res["real_yield"] = real_curve.rate(T)
    res["breakeven_inflation"] = breakeven_rate(nominal_curve, real_curve, T)
    res["projection"] = "curve_pair"
    return res
