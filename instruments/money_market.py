"""Money-market instruments (Этап 5, loans/MM lifecycle).

Депозиты и займы денежного рынка: простое начисление ACT/365, PV к
дисконтной ставке. Пока плоская ставка; term-structure дисконта — следующий
шаг (использовать снапшот-кривую).
"""

from __future__ import annotations

import numpy as np


def term_deposit(notional: float, deposit_rate: float, T: float, r: float,
                 basis: str = "simple", deposit: bool = True) -> dict:
    """Срочный депозит / заём МБК.

    basis="simple": погашение = notional·(1 + rate·T) (ACT/365);
    basis="continuous": notional·e^{rate·T}. PV = погашение·e^{−rT}.
    NPV депозиту = PV(погашения) − notional; заём — зеркально.
    Fair rate (NPV=0): simple → (e^{rT}−1)/T; continuous → r.
    """
    if basis == "continuous":
        redemption = notional * np.exp(deposit_rate * T)
        fair_rate = r
    else:
        redemption = notional * (1.0 + deposit_rate * T)
        fair_rate = (np.exp(r * T) - 1.0) / T if T > 0 else r
    pv = redemption * np.exp(-r * T)
    sign = 1.0 if deposit else -1.0
    npv = sign * (pv - notional)
    interest = redemption - notional
    return dict(
        npv=npv, value=npv, present_value=pv, redemption=redemption,
        interest=interest, fair_rate=fair_rate,
        dv01=sign * notional * T * np.exp(-r * T) / 10000,   # ~PV01 к ставке
        notional=notional, T=T,
    )
