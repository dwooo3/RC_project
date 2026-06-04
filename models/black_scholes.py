"""
Closed-form pricing models:
  - Black-Scholes-Merton (equity options)
  - Black-76 (futures/forward options, caps/floors, swaptions)
  - Garman-Kohlhagen (FX options)
  - Bachelier (normal model, rates/spreads)
"""

import numpy as np
from scipy.stats import norm
from dataclasses import dataclass, field
from typing import Literal


OptionType = Literal["call", "put"]


# ─────────────────────────────────────────────────────────
# Greeks container
# ─────────────────────────────────────────────────────────

@dataclass
class Greeks:
    price:  float = 0.0
    delta:  float = 0.0
    gamma:  float = 0.0
    vega:   float = 0.0   # per 1% σ move
    theta:  float = 0.0   # per calendar day
    rho:    float = 0.0   # per 1% r move
    # second/third order
    vanna:  float = 0.0   # dDelta/dVol
    volga:  float = 0.0   # d²Price/dVol² (vomma)
    charm:  float = 0.0   # dDelta/dt
    speed:  float = 0.0   # dGamma/dS
    color:  float = 0.0   # dGamma/dt
    ultima: float = 0.0   # d³Price/dVol³
    zomma:  float = 0.0   # dGamma/dVol

    def as_dict(self):
        return self.__dict__


# ─────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────

def _d1d2(F, K, T, sigma):
    """d1 and d2 for log-normal models."""
    if T <= 0 or sigma <= 0 or F <= 0 or K <= 0:
        return np.nan, np.nan
    sv = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sv**2) / sv
    d2 = d1 - sv
    return d1, d2


# ─────────────────────────────────────────────────────────
# Black-Scholes-Merton
# ─────────────────────────────────────────────────────────

def bsm(S: float, K: float, T: float, r: float, sigma: float,
        q: float = 0.0, opt: OptionType = "call") -> Greeks:
    """
    Black-Scholes-Merton with continuous dividend yield q.
    Returns full Greeks including second/third order.
    """
    if T <= 0:
        intrinsic = max(S - K, 0) if opt == "call" else max(K - S, 0)
        g = Greeks(); g.price = intrinsic
        # Expiry delta boundary: call -> +1 if ITM, put -> -1 if ITM (was 0 for puts).
        if opt == "call":
            g.delta = 1.0 if S > K else 0.0
        else:
            g.delta = -1.0 if S < K else 0.0
        return g

    F   = S * np.exp((r - q) * T)
    disc = np.exp(-r * T)
    dq  = np.exp(-q * T)
    d1, d2 = _d1d2(F, K, T, sigma)
    sv  = sigma * np.sqrt(T)

    Nd1, Nd2   = norm.cdf(d1), norm.cdf(d2)
    nd1        = norm.pdf(d1)

    sign = 1 if opt == "call" else -1

    price = sign * disc * (F * norm.cdf(sign * d1) - K * norm.cdf(sign * d2))
    delta = sign * dq * norm.cdf(sign * d1)
    gamma = dq * nd1 / (S * sv)
    vega  = S * dq * nd1 * np.sqrt(T) / 100
    theta = (-(S * dq * nd1 * sigma) / (2 * np.sqrt(T))
             - sign * r * K * disc * norm.cdf(sign * d2)
             + sign * q * S * dq * norm.cdf(sign * d1)) / 365
    rho   = sign * K * T * disc * norm.cdf(sign * d2) / 100

    # higher-order Greeks
    vanna  = -dq * nd1 * d2 / sigma
    volga  = S * dq * nd1 * np.sqrt(T) * d1 * d2 / sigma / 10000  # per 1%^2 (consistent with vega per 1%)
    charm  = -dq * (nd1 * ((r - q) / (sigma * np.sqrt(T)) - d2 / (2 * T))
                    + sign * q * norm.cdf(sign * d1)) / 365
    speed  = -gamma / S * (d1 / sv + 1)
    color  = -dq * nd1 / (2 * S * T * sv) * (
                2 * (r - q) * T + 1 + d1 * d2) / 365
    zomma  = gamma * (d1 * d2 - 1) / sigma
    ultima = -vega * 100 / sigma**2 * (d1 * d2 * (1 - d1 * d2) + d1**2 + d2**2)

    return Greeks(price=price, delta=delta, gamma=gamma, vega=vega,
                  theta=theta, rho=rho, vanna=vanna, volga=volga,
                  charm=charm, speed=speed, color=color,
                  zomma=zomma, ultima=ultima)


# ─────────────────────────────────────────────────────────
# Black-76 (forward/futures model)
# ─────────────────────────────────────────────────────────

def black76(F: float, K: float, T: float, r: float, sigma: float,
            opt: OptionType = "call") -> Greeks:
    """Black-76: price options on forwards, futures, rates."""
    if T <= 0:
        intrinsic = max(F - K, 0) if opt == "call" else max(K - F, 0)
        g = Greeks(); g.price = intrinsic; return g

    disc = np.exp(-r * T)
    d1, d2 = _d1d2(F, K, T, sigma)
    sv = sigma * np.sqrt(T)
    nd1 = norm.pdf(d1)
    sign = 1 if opt == "call" else -1

    price = disc * sign * (F * norm.cdf(sign * d1) - K * norm.cdf(sign * d2))
    delta = disc * sign * norm.cdf(sign * d1)
    gamma = disc * nd1 / (F * sv)
    vega  = disc * F * nd1 * np.sqrt(T) / 100
    theta = disc * (F * nd1 * sigma / (2 * np.sqrt(T))
                    + sign * r * (F * norm.cdf(sign * d1)
                                  - K * norm.cdf(sign * d2))) / (-365)
    rho   = -T * price / 100
    vanna = -disc * nd1 * d2 / sigma
    volga = vega * 100 * d1 * d2 / sigma

    return Greeks(price=price, delta=delta, gamma=gamma, vega=vega,
                  theta=theta, rho=rho, vanna=vanna, volga=volga)


# ─────────────────────────────────────────────────────────
# Garman-Kohlhagen (FX options)
# ─────────────────────────────────────────────────────────

def garman_kohlhagen(S: float, K: float, T: float, r_d: float, r_f: float,
                     sigma: float, opt: OptionType = "call") -> Greeks:
    """
    FX option pricing. S = spot in domestic/foreign units.
    r_d = domestic rate, r_f = foreign rate (= dividend yield).
    """
    return bsm(S=S, K=K, T=T, r=r_d, sigma=sigma, q=r_f, opt=opt)


# ─────────────────────────────────────────────────────────
# Bachelier (Normal model)
# ─────────────────────────────────────────────────────────

def bachelier(F: float, K: float, T: float, r: float, sigma_n: float,
              opt: OptionType = "call") -> Greeks:
    """
    Normal (Bachelier) model — useful for near-zero or negative rates.
    sigma_n is absolute (not percentage) volatility.
    """
    if T <= 0:
        intrinsic = max(F - K, 0) if opt == "call" else max(K - F, 0)
        g = Greeks(); g.price = intrinsic; return g

    disc = np.exp(-r * T)
    sv   = sigma_n * np.sqrt(T)
    d    = (F - K) / sv
    sign = 1 if opt == "call" else -1

    price = disc * (sign * (F - K) * norm.cdf(sign * d) + sv * norm.pdf(d))
    delta = disc * sign * norm.cdf(sign * d)
    gamma = disc * norm.pdf(d) / sv
    vega  = disc * np.sqrt(T) * norm.pdf(d) / 100
    theta = (-disc * sigma_n * norm.pdf(d) / (2 * np.sqrt(T))
             + r * price) / 365

    return Greeks(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta)
