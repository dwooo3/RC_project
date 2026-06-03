"""
Asian options:
  - Geometric Asian — exact closed-form (Kemna-Vorst)
  - Arithmetic Asian — MC with control variate
  - Fixed & floating strike variants
  - Continuous & discrete averaging
"""

import numpy as np
from scipy.stats import norm
from models.monte_carlo import gbm_paths


# ─────────────────────────────────────────────────────────
# Geometric Asian — closed-form (Kemna-Vorst)
# ─────────────────────────────────────────────────────────

def geometric_asian_continuous(S: float, K: float, T: float, r: float,
                                sigma: float, q: float = 0.0,
                                opt: str = "call") -> dict:
    """
    Geometric average rate (price) option — continuous monitoring.
    Exactly equivalent to BSM with adjusted parameters.
    """
    sigma_g = sigma / np.sqrt(3)
    b       = r - q
    b_g     = 0.5 * (b - sigma**2/6)
    d1 = (np.log(S/K) + (b_g + 0.5*sigma_g**2)*T) / (sigma_g*np.sqrt(T))
    d2 = d1 - sigma_g*np.sqrt(T)

    disc = np.exp(-r*T)
    sign = 1 if opt == "call" else -1
    price = sign * (S*np.exp((b_g - b)*T)*norm.cdf(sign*d1) - K*disc*norm.cdf(sign*d2))
    delta = np.exp((b_g - b)*T) * norm.cdf(sign*d1) * sign
    gamma = np.exp((b_g - b)*T) * norm.pdf(d1) / (S*sigma_g*np.sqrt(T))
    vega  = S * np.exp((b_g - b)*T) * norm.pdf(d1) * np.sqrt(T) / np.sqrt(3) / 100
    theta = (-S*np.exp((b_g-b)*T)*norm.pdf(d1)*sigma_g/(2*np.sqrt(T))
             - sign*r*K*disc*norm.cdf(sign*d2)
             + sign*(b_g-b)*S*np.exp((b_g-b)*T)*norm.cdf(sign*d1)) / 365

    return dict(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta,
                model="geometric_asian_continuous")


def geometric_asian_discrete(S: float, K: float, T: float, r: float,
                              sigma: float, q: float = 0.0, n: int = 12,
                              opt: str = "call") -> dict:
    """
    Geometric average rate option — discrete monitoring (n fixings).
    """
    dt   = T / n
    sigma_g = sigma * np.sqrt((n+1)*(2*n+1)/(6*n**2))
    b_g  = (r - q - sigma**2/2) * (n+1)/(2*n) + sigma_g**2/2
    d1   = (np.log(S/K) + (b_g + 0.5*sigma_g**2)*T) / (sigma_g*np.sqrt(T))
    d2   = d1 - sigma_g*np.sqrt(T)
    disc = np.exp(-r*T)
    sign = 1 if opt == "call" else -1

    price = sign*(S*np.exp((b_g - r)*T)*norm.cdf(sign*d1) - K*disc*norm.cdf(sign*d2))
    return dict(price=price, model="geometric_asian_discrete", n_fixings=n)


# ─────────────────────────────────────────────────────────
# Arithmetic Asian — Monte Carlo with geometric control variate
# ─────────────────────────────────────────────────────────

def arithmetic_asian(S: float, K: float, T: float, r: float, sigma: float,
                     q: float = 0.0, n: int = 12, opt: str = "call",
                     n_sims: int = 100_000,
                     averaging: str = "fixed",   # fixed | floating
                     seed: int = 42) -> dict:
    """
    Arithmetic average rate option via MC + geometric control variate.
    averaging:
      fixed    — payoff = max(A - K, 0)
      floating — payoff = max(S_T - A, 0)  [call] / max(A - S_T, 0) [put]
    """
    paths = gbm_paths(S, r, q, sigma, T, n, n_sims, seed=seed)
    disc  = np.exp(-r*T)

    arith_avg = paths[:, 1:].mean(axis=1)
    geom_avg  = np.exp(np.log(paths[:, 1:]).mean(axis=1))
    S_T       = paths[:, -1]

    if averaging == "fixed":
        sign = 1 if opt == "call" else -1
        arith_payoff = np.maximum(sign*(arith_avg - K), 0)
        geom_payoff  = np.maximum(sign*(geom_avg  - K), 0)
        # geometric closed-form for control variate
        geo_cf = geometric_asian_discrete(S, K, T, r, sigma, q, n, opt)["price"]
    else:  # floating
        if opt == "call":
            arith_payoff = np.maximum(S_T - arith_avg, 0)
            geom_payoff  = np.maximum(S_T - geom_avg,  0)
        else:
            arith_payoff = np.maximum(arith_avg - S_T, 0)
            geom_payoff  = np.maximum(geom_avg  - S_T, 0)
        geo_cf = disc * geom_payoff.mean()  # no closed-form, use MC geometric as proxy

    # control variate correction
    pv_arith = disc * arith_payoff
    pv_geom  = disc * geom_payoff
    beta     = np.cov(pv_arith, pv_geom)[0,1] / np.var(pv_geom)
    pv_cv    = pv_arith - beta*(pv_geom - geo_cf)

    price  = pv_cv.mean()
    stderr = pv_cv.std() / np.sqrt(n_sims)
    return dict(price=price, stderr=stderr, n_sims=n_sims, n_fixings=n,
                averaging=averaging, model="arithmetic_asian_mc")
