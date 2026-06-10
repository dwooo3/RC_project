"""
Lookback options (exact closed-form + MC):
  - Fixed strike lookback call/put
  - Floating strike lookback call/put
  - Partial-time lookback (monitoring subperiod)
"""

import numpy as np
from scipy.stats import norm
from models.monte_carlo import gbm_paths


# ─────────────────────────────────────────────────────────
# Floating-strike lookback (Goldman-Sosin-Gatto 1979)
# ─────────────────────────────────────────────────────────

def _carry(b: float) -> float:
    """Cost of carry guarded away from the b=0 singularity of the σ²/(2b) term."""
    return b if abs(b) > 1e-6 else (1e-6 if b >= 0 else -1e-6)


def floating_lookback(S: float, T: float, r: float, sigma: float,
                      q: float = 0.0, opt: str = "call",
                      S_min: float = None, S_max: float = None) -> dict:
    """
    Floating-strike lookback (Goldman-Sosin-Gatto / Haug §4.15.1).
    Call: pays S_T - min   Put: pays max - S_T
    S_min/S_max: running extreme so far (seasoned contracts).
    """
    b  = _carry(r - q)
    sv = sigma*np.sqrt(T)
    k  = sigma**2 / (2*b)
    dq, dr = np.exp(-q*T), np.exp(-r*T)

    if opt == "call":
        M = S_min if S_min is not None else S
        a1 = (np.log(S/M) + (b + sigma**2/2)*T) / sv
        a2 = a1 - sv
        price = (S*dq*norm.cdf(a1) - M*dr*norm.cdf(a2)
                 + S*dr*k*((S/M)**(-1/k)*norm.cdf(-a1 + 2*b*np.sqrt(T)/sigma)
                           - np.exp(b*T)*norm.cdf(-a1)))
    else:
        # Exact identity: floating put = fixed-strike call(K=M) + M e^{-rT} - S e^{-qT}
        # (payoff M_T - S_T with M_T = max(M, future max) >= M always), which pins the
        # correction-term arguments to e1, not the b1 of the often-mistranscribed GSG form.
        M = S_max if S_max is not None else S
        e1 = (np.log(S/M) + (b + sigma**2/2)*T) / sv
        e2 = e1 - sv
        price = (M*dr*norm.cdf(-e2) - S*dq*norm.cdf(-e1)
                 + S*dr*k*(-(S/M)**(-1/k)*norm.cdf(e1 - 2*b*np.sqrt(T)/sigma)
                           + np.exp(b*T)*norm.cdf(e1)))

    price = max(price, 0)
    return dict(price=price, type=f"floating_lookback_{opt}", S_extreme=M)


# ─────────────────────────────────────────────────────────
# Fixed-strike lookback (Conze-Viswanathan 1991)
# ─────────────────────────────────────────────────────────

def fixed_lookback(S: float, K: float, T: float, r: float, sigma: float,
                   q: float = 0.0, opt: str = "call",
                   S_min: float = None, S_max: float = None) -> dict:
    """
    Fixed-strike lookback (Conze-Viswanathan / Haug §4.15.2).
    Call: pays max(S_max - K, 0)   Put: pays max(K - S_min, 0)
    """
    b  = _carry(r - q)
    sv = sigma*np.sqrt(T)
    k  = sigma**2 / (2*b)
    dq, dr = np.exp(-q*T), np.exp(-r*T)
    two_b = 2*b*np.sqrt(T)/sigma

    if opt == "call":
        M = S_max if S_max is not None else S
        if K > M:
            d1 = (np.log(S/K) + (b + sigma**2/2)*T) / sv
            d2 = d1 - sv
            price = (S*dq*norm.cdf(d1) - K*dr*norm.cdf(d2)
                     + S*dr*k*(-(S/K)**(-1/k)*norm.cdf(d1 - two_b)
                               + np.exp(b*T)*norm.cdf(d1)))
        else:
            e1 = (np.log(S/M) + (b + sigma**2/2)*T) / sv
            e2 = e1 - sv
            price = ((M - K)*dr + S*dq*norm.cdf(e1) - M*dr*norm.cdf(e2)
                     + S*dr*k*(-(S/M)**(-1/k)*norm.cdf(e1 - two_b)
                               + np.exp(b*T)*norm.cdf(e1)))
    else:
        M = S_min if S_min is not None else S
        if K < M:
            f1 = (np.log(S/K) + (b + sigma**2/2)*T) / sv
            f2 = f1 - sv
            price = (K*dr*norm.cdf(-f2) - S*dq*norm.cdf(-f1)
                     + S*dr*k*((S/K)**(-1/k)*norm.cdf(-f1 + two_b)
                               - np.exp(b*T)*norm.cdf(-f1)))
        else:
            g1 = (np.log(S/M) + (b + sigma**2/2)*T) / sv
            g2 = g1 - sv
            price = ((K - M)*dr + M*dr*norm.cdf(-g2) - S*dq*norm.cdf(-g1)
                     + S*dr*k*((S/M)**(-1/k)*norm.cdf(-g1 + two_b)
                               - np.exp(b*T)*norm.cdf(-g1)))

    price = max(price, 0)
    return dict(price=price, type=f"fixed_lookback_{opt}", strike=K)


# ─────────────────────────────────────────────────────────
# MC lookback pricer
# ─────────────────────────────────────────────────────────

def lookback_mc(S: float, K: float, T: float, r: float, sigma: float,
                q: float = 0.0, opt: str = "call",
                style: str = "floating",
                n_sims: int = 100_000, steps: int = 252, seed: int = 42) -> dict:
    """MC pricer for lookback options."""
    paths = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)
    S_T   = paths[:, -1]
    S_max = paths.max(axis=1)
    S_min = paths.min(axis=1)
    disc  = np.exp(-r*T)

    if style == "floating":
        if opt == "call":
            payoff = np.maximum(S_T - S_min, 0)
        else:
            payoff = np.maximum(S_max - S_T, 0)
    else:  # fixed
        if opt == "call":
            payoff = np.maximum(S_max - K, 0)
        else:
            payoff = np.maximum(K - S_min, 0)

    pv     = disc * payoff
    price  = pv.mean()
    stderr = pv.std() / np.sqrt(n_sims)
    return dict(price=price, stderr=stderr, n_sims=n_sims, style=style)
