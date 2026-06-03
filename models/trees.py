"""
Lattice models — CRR · LR · Trinomial
Greeks via bump-and-reprice using price-only helpers (no recursion).
"""

import numpy as np
from typing import Callable, Literal, Optional

ExerciseType = Literal["european", "american", "bermudan"]


# ─────────────────────────────────────────────────────────
# Internal: price-only (no Greeks) — prevents recursion
# ─────────────────────────────────────────────────────────

def _crr_price_only(S, K, T, r, sigma, q, N, opt, exercise,
                    bermudan_dates=None, payoff_fn=None) -> float:
    if T <= 0:
        if payoff_fn:
            return float(payoff_fn(np.array([S]), K)[0])
        return float(max(S - K, 0) if opt == "call" else max(K - S, 0))

    dt   = T / N
    u    = np.exp(sigma * np.sqrt(dt))
    d    = 1.0 / u
    p    = (np.exp((r - q) * dt) - d) / (u - d)
    p    = np.clip(p, 0.0, 1.0)
    disc = np.exp(-r * dt)

    j   = np.arange(N + 1)
    S_T = S * u ** (N - 2 * j)

    if payoff_fn:
        V = payoff_fn(S_T, K).astype(float)
    elif opt == "call":
        V = np.maximum(S_T - K, 0.0)
    else:
        V = np.maximum(K - S_T, 0.0)

    bermudan_steps = set()
    if bermudan_dates:
        bermudan_steps = {int(round(t / dt)) for t in bermudan_dates}

    for i in range(N - 1, -1, -1):
        V    = disc * (p * V[:-1] + (1 - p) * V[1:])
        S_i  = S * u ** (i - 2 * np.arange(i + 1))
        if payoff_fn:
            iv = payoff_fn(S_i, K).astype(float)
        elif opt == "call":
            iv = np.maximum(S_i - K, 0.0)
        else:
            iv = np.maximum(K - S_i, 0.0)
        if exercise == "american" or (exercise == "bermudan" and i in bermudan_steps):
            V = np.maximum(V, iv)

    return float(V[0])


def _lr_price_only(S, K, T, r, sigma, q, N, opt, exercise) -> float:
    if T <= 0:
        return float(max(S - K, 0) if opt == "call" else max(K - S, 0))
    if N % 2 == 0:
        N += 1

    dt  = T / N
    d1  = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2  = d1 - sigma * np.sqrt(T)

    def _pp(z, n):
        return 0.5 + np.sign(z) * np.sqrt(
            0.25 - 0.25 * np.exp(-(z / (n + 1/3 + 0.1/(n+1)))**2 * (n + 1/6)))

    h1 = _pp(d1, N); h2 = _pp(d2, N)
    p  = h2
    u  = np.exp((r - q) * dt) * h1 / h2
    d_ = (np.exp((r - q) * dt) - p * u) / (1 - p)
    disc = np.exp(-r * dt)

    j   = np.arange(N + 1)
    S_T = S * u ** (N - j) * d_ ** j
    V   = np.maximum(S_T - K, 0) if opt == "call" else np.maximum(K - S_T, 0)

    for i in range(N - 1, -1, -1):
        V = disc * (p * V[:-1] + (1 - p) * V[1:])
        if exercise == "american":
            S_i = S * u ** (i - np.arange(i + 1)) * d_ ** np.arange(i + 1)
            iv  = np.maximum(S_i - K, 0) if opt == "call" else np.maximum(K - S_i, 0)
            V   = np.maximum(V, iv)

    return float(V[0])


def _trinomial_price_only(S, K, T, r, sigma, q, N, opt, exercise,
                          payoff_fn=None) -> float:
    if T <= 0:
        return float(max(S - K, 0) if opt == "call" else max(K - S, 0))

    dt = T / N
    dx = sigma * np.sqrt(3 * dt)
    drift = (r - q - 0.5 * sigma**2) * dt

    pu  = 0.5 * ((sigma**2 * dt + drift**2) / dx**2 + drift / dx)
    pm  = 1.0 -  (sigma**2 * dt + drift**2) / dx**2
    pd  = 0.5 * ((sigma**2 * dt + drift**2) / dx**2 - drift / dx)
    pu  = max(pu, 0.0); pd = max(pd, 0.0); pm = max(pm, 0.0)
    disc = np.exp(-r * dt)

    n_nodes = 2 * N + 1
    j   = np.arange(n_nodes) - N
    S_T = S * np.exp(j * dx)

    if payoff_fn:
        V = payoff_fn(S_T, K).astype(float)
    elif opt == "call":
        V = np.maximum(S_T - K, 0.0)
    else:
        V = np.maximum(K - S_T, 0.0)

    for i in range(N - 1, -1, -1):
        n_i   = 2 * i + 1
        V_new = disc * (pu * V[2:n_i+2] + pm * V[1:n_i+1] + pd * V[:n_i])
        if exercise == "american":
            j_i = np.arange(n_i) - i
            S_i = S * np.exp(j_i * dx)
            iv  = np.maximum(S_i - K, 0) if opt == "call" else np.maximum(K - S_i, 0)
            V_new = np.maximum(V_new, iv)
        V = V_new

    return float(V[0])


# ─────────────────────────────────────────────────────────
# Public API — price + Greeks (bump-and-reprice, no recursion)
# ─────────────────────────────────────────────────────────

def binomial_crr(S: float, K: float, T: float, r: float, sigma: float,
                 q: float = 0.0, N: int = 500,
                 opt: str = "call",
                 exercise: ExerciseType = "european",
                 bermudan_dates: Optional[list] = None,
                 payoff_fn: Optional[Callable] = None) -> dict:
    """CRR binomial tree. Returns price + Greeks."""
    price = _crr_price_only(S, K, T, r, sigma, q, N, opt, exercise,
                            bermudan_dates, payoff_fn)

    eps_s = max(S * 0.005, 0.01)
    eps_v = 0.001
    eps_t = 1.0 / 365

    pu  = _crr_price_only(S + eps_s, K, T, r, sigma, q, N, opt, exercise,
                          bermudan_dates, payoff_fn)
    pd  = _crr_price_only(S - eps_s, K, T, r, sigma, q, N, opt, exercise,
                          bermudan_dates, payoff_fn)
    pvu = _crr_price_only(S, K, T, r, sigma + eps_v, q, N, opt, exercise,
                          bermudan_dates, payoff_fn)
    pvd = _crr_price_only(S, K, T, r, sigma - eps_v, q, N, opt, exercise,
                          bermudan_dates, payoff_fn)
    pt  = _crr_price_only(S, K, max(T - eps_t, 1e-6), r, sigma, q, N, opt,
                          exercise, bermudan_dates, payoff_fn)

    delta = (pu - pd) / (2 * eps_s)
    gamma = (pu - 2 * price + pd) / eps_s ** 2
    vega  = (pvu - pvd) / (2 * eps_v * 100)   # per 1% vol move
    theta = (pt - price) / eps_t / 365         # per calendar day

    return dict(price=price, delta=delta, gamma=gamma,
                vega=vega, theta=theta)


def binomial_lr(S: float, K: float, T: float, r: float, sigma: float,
                q: float = 0.0, N: int = 501,
                opt: str = "call",
                exercise: ExerciseType = "european") -> dict:
    """Leisen-Reimer binomial (N odd for best accuracy). Returns price + Greeks."""
    price = _lr_price_only(S, K, T, r, sigma, q, N, opt, exercise)
    eps   = max(S * 0.005, 0.01)

    pu = _lr_price_only(S + eps, K, T, r, sigma, q, N, opt, exercise)
    pd = _lr_price_only(S - eps, K, T, r, sigma, q, N, opt, exercise)

    delta = (pu - pd) / (2 * eps)
    gamma = (pu - 2 * price + pd) / eps ** 2

    return dict(price=price, delta=delta, gamma=gamma)


def trinomial(S: float, K: float, T: float, r: float, sigma: float,
              q: float = 0.0, N: int = 300,
              opt: str = "call",
              exercise: ExerciseType = "european",
              payoff_fn: Optional[Callable] = None) -> dict:
    """Trinomial tree. Returns price + Greeks."""
    price = _trinomial_price_only(S, K, T, r, sigma, q, N, opt, exercise, payoff_fn)
    eps   = max(S * 0.005, 0.01)

    pu = _trinomial_price_only(S + eps, K, T, r, sigma, q, N, opt, exercise, payoff_fn)
    pd = _trinomial_price_only(S - eps, K, T, r, sigma, q, N, opt, exercise, payoff_fn)

    delta = (pu - pd) / (2 * eps)
    gamma = (pu - 2 * price + pd) / eps ** 2

    return dict(price=price, delta=delta, gamma=gamma)
