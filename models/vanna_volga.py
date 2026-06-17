"""
Vanna-Volga FX smile, gap-closing batch 3.

Builds an implied-vol smile from the three market pillars FX desks quote — ATM,
25Δ risk reversal and 25Δ butterfly (i.e. the 25Δ call and put vols) — by the
Vanna-Volga construction (Castagna-Mercurio 2007). The first-order term is the
log-strike Lagrange interpolation that passes through the three pillars exactly;
the second-order term adds the vanna/volga hedging cost.

Validated: the smile reproduces the three pillar vols, and a flat input (all
three vols equal) collapses to that flat vol (→ Garman-Kohlhagen).
"""

from __future__ import annotations

import numpy as np

from models.black_scholes import garman_kohlhagen


def _d12(S, K, T, r_d, r_f, sigma):
    sq = sigma * np.sqrt(T)
    d1 = (np.log(S / K) + (r_d - r_f + 0.5 * sigma**2) * T) / sq
    return d1, d1 - sq


def vv_implied_vol(S, K, T, r_d, r_f, K_atm, sig_atm, K_put, sig_put,
                   K_call, sig_call, second_order=True) -> float:
    """Vanna-Volga implied vol at strike K from the three 25Δ pillars."""
    lK = np.log
    K1, K2, K3 = K_put, K_atm, K_call
    s1, s2, s3 = sig_put, sig_atm, sig_call
    # log-strike Lagrange weights (exact at the pillars)
    y1 = lK(K2 / K) * lK(K3 / K) / (lK(K2 / K1) * lK(K3 / K1))
    y2 = lK(K / K1) * lK(K3 / K) / (lK(K2 / K1) * lK(K3 / K2))
    y3 = lK(K / K1) * lK(K / K2) / (lK(K3 / K1) * lK(K3 / K2))
    sigma_1 = y1 * s1 + y2 * s2 + y3 * s3               # first order (pillar-exact)
    if not second_order:
        return float(sigma_1)
    d1K, d2K = _d12(S, K, T, r_d, r_f, s2)
    D1 = sigma_1 - s2
    d1_1, d2_1 = _d12(S, K1, T, r_d, r_f, s2)
    d1_3, d2_3 = _d12(S, K3, T, r_d, r_f, s2)
    D2 = (y1 * d1_1 * d2_1 * (s1 - s2)**2 + y3 * d1_3 * d2_3 * (s3 - s2)**2)
    disc = s2**2 + d1K * d2K * (2 * s2 * D1 + D2)
    if disc <= 0:
        return float(sigma_1)
    return float(s2 + (-s2 + np.sqrt(disc)) / (d1K * d2K))


def vv_price(S, K, T, r_d, r_f, K_atm, sig_atm, K_put, sig_put, K_call, sig_call,
             opt="call", second_order=True) -> dict:
    """Garman-Kohlhagen price at the Vanna-Volga implied vol for strike K."""
    sig = vv_implied_vol(S, K, T, r_d, r_f, K_atm, sig_atm, K_put, sig_put,
                         K_call, sig_call, second_order)
    g = garman_kohlhagen(S, K, T, r_d, r_f, sig, opt)
    return dict(price=g.price, implied_vol=sig)
