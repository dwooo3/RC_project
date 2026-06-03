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

def floating_lookback(S: float, T: float, r: float, sigma: float,
                      q: float = 0.0, opt: str = "call",
                      S_min: float = None, S_max: float = None) -> dict:
    """
    Floating-strike lookback.
    Call: max(S_T - S_min, 0)  — pays S_T minus minimum
    Put:  max(S_max - S_T, 0)  — pays maximum minus S_T
    S_min/S_max: running min/max so far (for path-dependent seasoning).
    """
    b  = r - q
    sv = sigma*np.sqrt(T)

    if opt == "call":
        M = S_min if S_min is not None else S
        a1 = (np.log(S/M) + (b + sigma**2/2)*T) / sv
        a2 = a1 - sv
        a3 = (np.log(S/M) + (-b + sigma**2/2)*T) / sv
        price = (S*np.exp(-q*T)*norm.cdf(a1) - M*np.exp(-r*T)*norm.cdf(a2)
                 + S*np.exp(-r*T)*(sigma**2/(2*b))
                 * ((S/M)**(-2*b/sigma**2)*norm.cdf(-a3) - np.exp(b*T)*norm.cdf(-a1)))
    else:
        M = S_max if S_max is not None else S
        b1 = (np.log(M/S) + (-b + sigma**2/2)*T) / sv
        b2 = b1 - sv
        b3 = (np.log(M/S) + (b + sigma**2/2)*T) / sv  # corrected sign
        price = (M*np.exp(-r*T)*norm.cdf(b1) - S*np.exp(-q*T)*norm.cdf(b1-sv)
                 + S*np.exp(-r*T)*(sigma**2/(2*b))
                 * (-(S/M)**(-2*b/sigma**2)*norm.cdf(b3) + np.exp(b*T)*norm.cdf(b1)))

    price = max(price, 0)
    return dict(price=price, type=f"floating_lookback_{opt}", S_extreme=M)


# ─────────────────────────────────────────────────────────
# Fixed-strike lookback
# ─────────────────────────────────────────────────────────

def fixed_lookback(S: float, K: float, T: float, r: float, sigma: float,
                   q: float = 0.0, opt: str = "call",
                   S_min: float = None, S_max: float = None) -> dict:
    """
    Fixed-strike lookback.
    Call: max(S_max - K, 0)   — call on maximum
    Put:  max(K - S_min, 0)   — put on minimum
    """
    b  = r - q
    sv = sigma*np.sqrt(T)

    if opt == "call":
        M = S_min if S_min is not None else S  # for call we track max, but start at S
        # Actually fixed call = call on maximum, track S_max
        M = S_max if S_max is not None else S
        if S >= K:
            d1 = (np.log(S/K) + (b + sigma**2/2)*T) / sv
            d2 = d1 - sv
            e1 = (np.log(S/M) + (b + sigma**2/2)*T) / sv if M > 0 else d1
            e2 = e1 - sv
            price = (S*np.exp(-q*T)*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
                     + S*np.exp(-r*T)*(sigma**2/(2*b))
                     * ((S/M)**(-2*b/sigma**2)*norm.cdf(-e1+2*b*np.sqrt(T)/sigma)
                        - np.exp(b*T)*norm.cdf(-e1)))
        else:
            d1 = (np.log(S/K) + (b + sigma**2/2)*T) / sv
            price = S*np.exp(-q*T)*norm.cdf(d1) + S*np.exp(-r*T)*(sigma**2/(2*b)) * (
                    np.exp(b*T)*norm.cdf(d1) - (sigma**2/(2*b))*np.exp(-r*T)*norm.cdf(d1-sv))
        price = max(price, max(M - K, 0))
    else:
        M = S_min if S_min is not None else S
        if S <= K:
            d1 = (np.log(K/S) + (-b + sigma**2/2)*T) / sv
            d2 = d1 - sv
            e1 = (np.log(M/S) + (-b + sigma**2/2)*T) / sv if M > 0 else d1
            price = (K*np.exp(-r*T)*norm.cdf(d1) - S*np.exp(-q*T)*norm.cdf(d2)
                     + S*np.exp(-r*T)*(sigma**2/(2*b))
                     * (norm.cdf(-e1) - (S/M)**(-2*b/sigma**2)*norm.cdf(-e1+2*b*np.sqrt(T)/sigma)))
        else:
            price = max(K - M, 0) * np.exp(-r*T)
        price = max(price, max(K - M, 0))

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
