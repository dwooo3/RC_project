"""
Convertible bond — Tsiveriotis-Fernandes (1998) on a CRR equity tree (Phase 2).

The value at each node splits into an equity component (paid in shares or cash
the issuer chooses to deliver via conversion — discounted risk-free) and a debt
component (contractual cash promises — discounted at risk-free + credit
spread). Handles voluntary conversion, issuer call (with forced conversion),
holder put, discrete coupons, and continuous dividend yield.
"""

import numpy as np

from curves.yield_curve import YieldCurve


def convertible_bond(S: float, sigma: float, q: float,
                     face: float, coupon: float, freq: int, T: float,
                     conv_ratio: float, curve: YieldCurve,
                     credit_spread: float = 0.02,
                     call_price: float | None = None, call_start: float = 0.0,
                     put_price: float | None = None, put_start: float = 0.0,
                     N: int = 400) -> dict:
    """
    Tsiveriotis-Fernandes convertible bond.
    conv_ratio: shares per bond. call/put prices are clean redemption amounts.
    Returns price, bond floor, parity, conversion premium, and equity delta.
    """
    if conv_ratio < 0:
        raise ValueError("conv_ratio must be non-negative")

    dt = T / N
    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    cpn = face * coupon / freq
    coupon_steps = {int(round(k * N / (T * freq))) for k in range(1, int(round(T * freq)) + 1)}

    # per-step risk-free discount from the curve's forward factors; credit add-on
    df_step = np.array([curve.discount((i + 1) * dt) / curve.discount(i * dt)
                        for i in range(N)])
    cs_step = np.exp(-credit_spread * dt)
    # risk-neutral up-probability per step (forward growth e^{(r_f - q)dt})
    growth = np.array([1.0 / df_step[i] * np.exp(-q * dt) for i in range(N)])
    p = (growth - d) / (u - d)
    p = np.clip(p, 0.0, 1.0)

    def _solve(ratio: float):
        j = np.arange(N + 1)
        S_T = S * u ** (N - 2.0 * j)
        redemption = face + (cpn if N in coupon_steps else 0.0)
        conv = ratio * S_T
        V = np.maximum(conv, redemption)
        E = np.where(conv >= redemption, conv, 0.0)     # equity component
        D = V - E                                        # debt component

        for i in range(N - 1, -1, -1):
            S_i = S * u ** (i - 2.0 * np.arange(i + 1))
            pi = p[i]
            E = df_step[i] * (pi * E[:-1] + (1 - pi) * E[1:])
            D = df_step[i] * cs_step * (pi * D[:-1] + (1 - pi) * D[1:])
            if i in coupon_steps and i > 0:
                D = D + cpn                              # contractual cash -> debt
            V = E + D
            t = i * dt
            conv_val = ratio * S_i

            if call_price is not None and t >= call_start - 1e-12 and i > 0:
                # issuer calls when continuation > call; holder may force conversion
                called = V > call_price + 1e-12
                forced = np.where(conv_val >= call_price, conv_val, call_price)
                E = np.where(called, np.where(conv_val >= call_price, forced, 0.0), E)
                D = np.where(called, np.where(conv_val >= call_price, 0.0, call_price), D)
                V = E + D
            if put_price is not None and t >= put_start - 1e-12 and i > 0:
                putted = V < put_price - 1e-12
                E = np.where(putted, 0.0, E)
                D = np.where(putted, put_price, D)
                V = E + D
            # voluntary conversion
            converted = conv_val > V + 1e-12
            E = np.where(converted, conv_val, E)
            D = np.where(converted, 0.0, D)
            V = E + D
        return float(V[0])

    price = _solve(conv_ratio)
    bond_floor = _solve(0.0)
    parity = conv_ratio * S
    conversion_premium = price / parity - 1.0 if parity > 0 else float("inf")

    eps = S * 0.01
    dt_scale = conv_ratio  # reuse _solve with bumped spot via closure rebuild
    def _solve_at(S0: float):
        nonlocal S
        S_orig = S
        S = S0
        try:
            return _solve(conv_ratio)
        finally:
            S = S_orig
    delta = (_solve_at(S + eps) - _solve_at(S - eps)) / (2 * eps)

    return dict(price=price, clean_price=price, dirty_price=price, accrued_interest=0.0,
                bond_floor=bond_floor, parity=parity,
                conversion_premium=conversion_premium,
                option_value=price - max(bond_floor, 0.0),
                delta=delta, conv_ratio=conv_ratio,
                credit_spread=credit_spread)
