"""
Rough volatility — rough Bergomi (Bayer-Friz-Gatheral 2016), Master-plan M2.

The variance is driven by a Riemann-Liouville fractional process with Hurst
H < 1/2 (rough):  Y_t = √(2H) ∫_0^t (t-s)^{H-1/2} dW_s,
V_t = ξ0 · exp(η Y_t − ½ η² t^{2H}),  with E[V_t]=ξ0 by the martingale term.
We discretise the Volterra integral with the EXACT kernel integral over each
step, so Var(Y_t) → t^{2H} and the same driving increments feed the spot (the
ρ-correlated leg) — keeping the spot a martingale.

Limits used for validation: η→0 ⇒ Black-Scholes with σ=√ξ0; put-call parity;
rough (small H) gives a steeper short-dated skew than smooth (H≈0.5).
"""

from __future__ import annotations

import numpy as np


def _volterra_weights(H: float, dt: float, steps: int) -> np.ndarray:
    """
    Lower-triangular convolution weights a[i,j] (j≤i) such that
    Y_{i+1} = √(2H) Σ_{j≤i} a[i,j] ΔW_j approximates the Volterra integral with
    the kernel integrated exactly over each step. a depends only on the lag i-j:
        a[i,j] = Δ^{β-1}/β · [(lag+1)^β − lag^β],  β=H+½, lag=i-j.
    """
    beta = H + 0.5
    lags = np.arange(steps)
    coef = dt ** (beta - 1) / beta * ((lags + 1.0) ** beta - lags ** beta)
    a = np.zeros((steps, steps))
    for i in range(steps):
        a[i, : i + 1] = coef[i::-1]          # weight for ΔW_j is coef at lag i-j
    return a


def rough_bergomi_paths(S0, r, q, T, H, eta, rho, xi0, n_paths, steps, seed=42):
    """
    Simulate rough Bergomi spot paths.
    H Hurst (<0.5 rough), eta vol-of-vol, rho spot-vol corr, xi0 forward variance.
    Returns S array (n_paths, steps+1).
    """
    rng = np.random.default_rng(seed)
    dt = T / steps

    Z = rng.standard_normal((n_paths, steps))
    dW1 = Z * np.sqrt(dt)                                 # driving BM increments
    a = _volterra_weights(H, dt, steps)
    Y = np.sqrt(2 * H) * (dW1 @ a.T)                     # Volterra process at t_1..t_steps

    t = np.linspace(dt, T, steps)
    V = xi0 * np.exp(eta * Y - 0.5 * eta**2 * t ** (2 * H))   # variance path

    # spot: correlated with the driving BM dW1
    dW_perp = rng.standard_normal((n_paths, steps)) * np.sqrt(dt)
    dB = rho * dW1 + np.sqrt(1 - rho**2) * dW_perp
    incr = (r - q - 0.5 * V) * dt + np.sqrt(np.maximum(V, 0)) * dB
    logS = np.log(S0) + np.cumsum(incr, axis=1)
    S = np.empty((n_paths, steps + 1))
    S[:, 0] = S0
    S[:, 1:] = np.exp(logS)
    return S


def rough_bergomi_price(S, K, T, r, q=0.0, H=0.1, eta=1.5, rho=-0.7, xi0=0.04,
                        opt="call", n_paths=40_000, steps=100, seed=42) -> dict:
    """
    European option under rough Bergomi (MC). Applies the standard martingale
    correction to the terminal spot (McCrickerd-Pakkanen): the discrete Euler
    log-spot is biased under heavy variance tails, so S_T is rescaled to enforce
    E[S_T] = S_0 e^{(r-q)T} exactly — restoring put-call parity.
    """
    paths = rough_bergomi_paths(S, r, q, T, H, eta, rho, xi0, n_paths, steps, seed)
    ST = paths[:, -1]
    ST = ST * (S * np.exp((r - q) * T) / ST.mean())     # martingale correction
    payoff = np.maximum(ST - K, 0) if opt == "call" else np.maximum(K - ST, 0)
    pv = np.exp(-r * T) * payoff
    price = float(pv.mean())
    stderr = float(pv.std() / np.sqrt(n_paths))
    return dict(price=price, stderr=stderr, n_paths=n_paths, H=H, eta=eta,
                rho=rho, xi0=xi0, model="rough_bergomi")
