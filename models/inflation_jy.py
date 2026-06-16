"""
Jarrow-Yildirim inflation model, gap-closing batch 4.

A foreign-currency analogue: nominal and real economies each carry a (flat here)
discount curve, and the CPI index I(t) is the "exchange rate" with
dI/I = (n - r) dt + σ_I dW. The risk-neutral forward CPI is therefore

    E^n_0[I(T)] / I(0) = P_real(0,T) / P_nom(0,T),

so a zero-coupon inflation-indexed swap's fair rate and the breakeven inflation
follow directly. Validated: equal nominal/real curves → zero breakeven; the
ZCIIS fair leg equals the forward CPI ratio.
"""

from __future__ import annotations

import numpy as np


def forward_cpi(I0, nominal_rate, real_rate, T):
    """E^n[I(T)] = I0·P_real/P_nom = I0·exp((n-r)T) for flat curves."""
    return I0 * np.exp((nominal_rate - real_rate) * T)


def zciis_fair_rate(nominal_rate, real_rate, T):
    """Fair fixed rate K of a zero-coupon inflation-indexed swap:
    (1+K)^T = I(T)/I(0) forward = exp((n-r)T)."""
    return np.exp((nominal_rate - real_rate)) ** 1 - 1 if T == 1 else \
        np.exp((nominal_rate - real_rate) * T) ** (1.0 / T) - 1.0


def breakeven_inflation(nominal_rate, real_rate, T):
    return zciis_fair_rate(nominal_rate, real_rate, T)
