"""
Digital (binary) options:
  - Cash-or-nothing (European, American)
  - Asset-or-nothing
  - Gap options
  - Supershare options
  - One-touch / No-touch (barrier digitals)
  - Double-touch
"""

import numpy as np
from scipy.stats import norm
from models.monte_carlo import gbm_paths


# ─────────────────────────────────────────────────────────
# European Digital (exact BSM)
# ─────────────────────────────────────────────────────────

def cash_or_nothing(S: float, K: float, T: float, r: float, sigma: float,
                    q: float = 0.0, opt: str = "call", cash: float = 1.0) -> dict:
    """
    Cash-or-nothing: pays `cash` if option ends in-the-money.
    delta = dPrice/dS, gamma, vega computed analytically.
    """
    if T <= 0:
        return dict(price=cash if (opt=="call" and S>K) or (opt=="put" and S<K) else 0)
    d1 = (np.log(S/K) + (r - q + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    disc = np.exp(-r*T)
    sign = 1 if opt == "call" else -1

    price = cash * disc * norm.cdf(sign*d2)
    delta = sign * cash * disc * norm.pdf(d2) / (S*sigma*np.sqrt(T))
    gamma = -cash * disc * norm.pdf(d2) * d1 / (S**2*sigma**2*T)
    vega  = -cash * disc * norm.pdf(d2) * d1 / (sigma * 100)
    theta = (cash * disc * (r*norm.cdf(sign*d2)
             + sign*norm.pdf(d2)*(r-q+0.5*sigma**2)/(sigma*np.sqrt(T)))) / (-365)

    return dict(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta, cash=cash)


def asset_or_nothing(S: float, K: float, T: float, r: float, sigma: float,
                     q: float = 0.0, opt: str = "call") -> dict:
    """Asset-or-nothing: pays S_T if ITM."""
    if T <= 0:
        return dict(price=S if (opt=="call" and S>K) or (opt=="put" and S<K) else 0)
    d1 = (np.log(S/K) + (r - q + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    disc_q = np.exp(-q*T)
    sign   = 1 if opt == "call" else -1

    price  = S * disc_q * norm.cdf(sign*d1)
    delta  = disc_q * (norm.cdf(sign*d1) + sign*norm.pdf(d1)/(sigma*np.sqrt(T)))
    gamma  = disc_q * norm.pdf(d1) * (1 - d1/(sigma*np.sqrt(T))) / (S*sigma*np.sqrt(T))
    vega   = S * disc_q * norm.pdf(d1) * np.sqrt(T) / 100  # rough

    return dict(price=price, delta=delta, gamma=gamma, vega=vega)


# ─────────────────────────────────────────────────────────
# Gap option (modified digital)
# ─────────────────────────────────────────────────────────

def gap_option(S: float, K1: float, K2: float, T: float, r: float, sigma: float,
               q: float = 0.0, opt: str = "call") -> dict:
    """
    Gap option: pays (S_T - K2) if S_T > K1 (call) or (K2 - S_T) if S_T < K1 (put).
    K1 = trigger strike, K2 = payment strike.
    """
    d1 = (np.log(S/K1) + (r - q + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    disc = np.exp(-r*T); disc_q = np.exp(-q*T)
    sign = 1 if opt == "call" else -1

    price = sign*(S*disc_q*norm.cdf(sign*d1) - K2*disc*norm.cdf(sign*d2))
    return dict(price=price, K_trigger=K1, K_payment=K2)


# ─────────────────────────────────────────────────────────
# One-touch / No-touch
# ─────────────────────────────────────────────────────────

def one_touch(S: float, H: float, T: float, r: float, sigma: float,
              q: float = 0.0, direction: str = "up",
              payment: str = "expiry", cash: float = 1.0) -> dict:
    """
    One-touch: pays `cash` if barrier H is touched before expiry.
    direction: up | down
    payment:   expiry (at T) | touch (at first touch time)
    Exact formula from Reiner-Rubinstein.
    """
    b   = r - q
    mu  = (b - sigma**2/2) / sigma**2
    lam = np.sqrt(mu**2 + 2*r/sigma**2)
    sv  = sigma*np.sqrt(T)
    eta = 1 if direction == "up" else -1

    z   = np.log(H/S)/sv + lam*sv
    x2  = np.log(S/H)/sv + (1+mu)*sv  # = -z + (1+mu+lam)*sv
    y2  = np.log(H/S)/sv + (1+mu)*sv

    if payment == "expiry":
        price = cash*(norm.cdf(eta*(np.log(H/S)/sv - lam*sv))*(H/S)**(mu+lam)
                    + norm.cdf(eta*(-np.log(H/S)/sv - lam*sv))*(H/S)**(mu-lam))
    else:  # pay at touch — rebate formula
        price = cash*((H/S)**(mu+lam)*norm.cdf(eta*z)
                     +(H/S)**(mu-lam)*norm.cdf(eta*(z - 2*lam*sv)))

    return dict(price=price, barrier=H, direction=direction, payment=payment)


def no_touch(S: float, H: float, T: float, r: float, sigma: float,
             q: float = 0.0, direction: str = "up", cash: float = 1.0) -> dict:
    """No-touch = bond - one-touch (at expiry)."""
    ot    = one_touch(S, H, T, r, sigma, q, direction, "expiry", cash)
    price = cash*np.exp(-r*T) - ot["price"]
    return dict(price=price, barrier=H, direction=direction)


def double_no_touch(S: float, L: float, U: float, T: float, r: float, sigma: float,
                    q: float = 0.0, cash: float = 1.0,
                    n_sims: int = 100_000, steps: int = 252, seed: int = 42) -> dict:
    """Double no-touch (corridor) via MC."""
    paths = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)
    S_min = paths.min(axis=1)
    S_max = paths.max(axis=1)
    alive  = (S_min > L) & (S_max < U)
    pv     = np.exp(-r*T) * cash * alive.astype(float)
    return dict(price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims), lower=L, upper=U)


# ─────────────────────────────────────────────────────────
# Supershare
# ─────────────────────────────────────────────────────────

def supershare(S: float, K_low: float, K_high: float, T: float, r: float,
               sigma: float, q: float = 0.0) -> dict:
    """
    Supershare: pays S_T / K_low if K_low < S_T < K_high.
    """
    ao_low  = asset_or_nothing(S, K_low,  T, r, sigma, q, "call")["price"]
    ao_high = asset_or_nothing(S, K_high, T, r, sigma, q, "call")["price"]
    price = (ao_low - ao_high) / K_low
    return dict(price=price, K_low=K_low, K_high=K_high)
