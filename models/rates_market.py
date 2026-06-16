"""
Swap Market Model (SMM), gap-closing batch 4.

The dual of the LIBOR market model: the forward swap rate S(t) is modelled
lognormal (optionally displaced for skew) under its annuity measure, so a
European swaption is *exactly* Black-76 on the annuity numeraire,

    PS = N · A(0) · Black76(S0+θ, K+θ, T_opt, σ)

with A(0)=Σ τ_i P(0,T_i). Validated: the SMM swaption equals the desk Black-76
swaption (and the LMM Rebonato/Black swaption), and a zero displacement is the
standard lognormal SMM.
"""

from __future__ import annotations

from models.short_rate import _forward_swap_rate
from models.black_scholes import black76


def smm_swaption(curve, notional, K, T_opt, T_swap, freq=2, sigma=0.20,
                 shift=0.0, opt="payer") -> dict:
    """European swaption under the (displaced) swap market model."""
    S0, annuity = _forward_swap_rate(curve, T_opt, T_swap, freq)
    g = black76(S0 + shift, K + shift, T_opt, 0.0, sigma,
                "call" if opt == "payer" else "put")
    return dict(price=notional * annuity * g.price, forward=S0, annuity=annuity)
