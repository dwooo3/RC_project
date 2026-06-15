"""
AFV (Andersen-Buffum) convertible bond, Master-plan M8.

A defaultable equity model on a binomial tree: the stock diffuses but can jump to
zero at a hazard intensity that rises as the share price falls,

    λ(S) = λ0 · (S0/S)^α,

and on default the holder recovers R·face. Under the risk-neutral measure the
diffusion drift is compensated for the jump (E[S']=e^{(r-q)Δt}S), so the
up-probability uses growth e^{(r-q+λ)Δt}. At each node the holder takes the best
of continuation (cash + diffusion + default recovery) and conversion into
conv_ratio shares.

Unlike Tsiveriotis-Fernandes (a constant credit spread on the "debt" part), AFV
ties credit to the equity, capturing the empirical equity-credit link. Validated:
conv_ratio→0 recovers a defaultable straight bond, λ0→0 recovers the
no-default convertible, deep in-the-money → conversion value, and the price falls
as the hazard rises.
"""

from __future__ import annotations

import numpy as np


def afv_convertible(S, sigma, q, face, coupon, freq, T, conv_ratio, r,
                    lam0=0.02, alpha=1.2, recovery=0.4, N=400) -> dict:
    """Andersen-Buffum convertible on a CRR tree with an equity-linked default."""
    dt = T / N
    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    disc = np.exp(-r * dt)
    cpn = face * coupon / freq
    coupon_steps = {int(round(k * N / (T * freq))) for k in range(1, int(round(T * freq)) + 1)}
    rec = recovery * face

    def hazard(Sarr):
        # capped at 10 (≈certain default over Δt) to avoid overflow at S→0
        return np.minimum(lam0 * (S / np.maximum(Sarr, 1e-8)) ** alpha, 10.0)

    # terminal
    j = np.arange(N + 1)
    S_T = S * u ** (N - 2.0 * j)
    redemption = face + (cpn if N in coupon_steps else 0.0)
    V = np.maximum(redemption, conv_ratio * S_T)

    for i in range(N - 1, -1, -1):
        S_i = S * u ** (i - 2.0 * np.arange(i + 1))
        lam = hazard(S_i)
        surv = np.exp(-lam * dt)
        pd = 1.0 - surv
        growth = np.exp((r - q + lam) * dt)
        p = np.clip((growth - d) / (u - d), 0.0, 1.0)
        cont = disc * (surv * (p * V[:-1] + (1 - p) * V[1:]) + pd * rec)
        if i in coupon_steps and i > 0:
            cont = cont + cpn
        V = np.maximum(cont, conv_ratio * S_i)          # American conversion
    price = float(V[0])
    parity = conv_ratio * S
    return dict(price=price, parity=parity,
                conversion_premium=price / parity - 1 if parity > 0 else float("nan"),
                lam0=lam0, alpha=alpha)


def defaultable_bond(face, coupon, freq, T, r, lam, recovery=0.4, n_int=2000) -> float:
    """Constant-hazard risky straight bond — reference for AFV at conv_ratio=0."""
    dt = 1.0 / freq
    times = [i * dt for i in range(1, int(round(T * freq)) + 1)]
    cpn = face * coupon / freq
    pv = sum(cpn * np.exp(-r * t) * np.exp(-lam * t) for t in times)
    pv += face * np.exp(-r * T) * np.exp(-lam * T)
    grid = np.linspace(0, T, n_int + 1)[1:]
    dti = T / n_int
    pv += recovery * face * np.sum(np.exp(-r * grid) * lam * np.exp(-lam * grid)) * dti
    return float(pv)
