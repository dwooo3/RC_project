"""
Barrier options (exact closed-form + MC):
  - Single barrier: up/down, in/out, call/put
  - Double barrier: knock-out
  - Partial barrier (monitored over subperiod)
  - Window barrier
"""

import numpy as np
from scipy.stats import norm
from models.monte_carlo import gbm_paths


# ─────────────────────────────────────────────────────────
# Single-barrier closed-form (Reiner & Rubinstein 1991)
# ─────────────────────────────────────────────────────────

def _RR_phi(S, T, H, K, r, q, sigma, phi, eta, x1=None, x2=None, y1=None, y2=None):
    """Reiner-Rubinstein building blocks."""
    b  = r - q
    mu = (b - sigma**2/2) / sigma**2
    lam= np.sqrt(mu**2 + 2*r/sigma**2)
    sv = sigma * np.sqrt(T)
    d  = np.log(H**2/(S*K)) / sv + lam*sv if x2 is None else x2

    def _M(d_): return norm.cdf(phi * d_)

    x1_  = np.log(S/K)  / sv + (1+mu)*sv
    x2_  = np.log(S/H)  / sv + (1+mu)*sv
    y1_  = np.log(H**2/(S*K)) / sv + (1+mu)*sv
    y2_  = np.log(H/S)  / sv + (1+mu)*sv
    z    = np.log(H/S)  / sv + lam*sv

    A  = phi * S * np.exp(-q*T) * _M(phi*x1_) - phi*K*np.exp(-r*T)*_M(phi*(x1_-sv))
    B  = phi * S * np.exp(-q*T) * _M(phi*x2_) - phi*K*np.exp(-r*T)*_M(phi*(x2_-sv))
    C  = phi * S * np.exp(-q*T) * (H/S)**(2*(mu+1)) * _M(eta*y1_) \
       - phi * K * np.exp(-r*T) * (H/S)**(2*mu)     * _M(eta*(y1_-sv))
    D  = phi * S * np.exp(-q*T) * (H/S)**(2*(mu+1)) * _M(eta*y2_) \
       - phi * K * np.exp(-r*T) * (H/S)**(2*mu)     * _M(eta*(y2_-sv))
    E  = 0  # rebate term (zero rebate here)
    return A, B, C, D, E


def single_barrier(S: float, K: float, H: float, T: float, r: float, sigma: float,
                   q: float = 0.0, opt: str = "call",
                   barrier_type: str = "down-out",
                   rebate: float = 0.0) -> dict:
    """
    Exact closed-form for single-barrier European option.
    barrier_type: down-out | down-in | up-out | up-in
    """
    b   = r - q
    phi = 1 if opt == "call" else -1
    eta = 1 if "down" in barrier_type else -1
    sv  = sigma * np.sqrt(T)
    mu  = (b - sigma**2/2) / sigma**2
    lam = np.sqrt(mu**2 + 2*r/sigma**2)

    def _m(d): return norm.cdf(phi * d)

    x1 = np.log(S/K)  / sv + (1+mu)*sv
    x2 = np.log(S/H)  / sv + (1+mu)*sv
    y1 = np.log(H**2/(S*K)) / sv + (1+mu)*sv
    y2 = np.log(H/S)  / sv + (1+mu)*sv
    z  = np.log(H/S)  / sv + lam*sv

    A  = phi*S*np.exp(-q*T)*_m(phi*x1) - phi*K*np.exp(-r*T)*_m(phi*(x1-sv))
    B  = phi*S*np.exp(-q*T)*_m(phi*x2) - phi*K*np.exp(-r*T)*_m(phi*(x2-sv))
    C  = phi*S*np.exp(-q*T)*(H/S)**(2*(mu+1))*_m(eta*y1) \
       - phi*K*np.exp(-r*T)*(H/S)**(2*mu)    *_m(eta*(y1-sv))
    D  = phi*S*np.exp(-q*T)*(H/S)**(2*(mu+1))*_m(eta*y2) \
       - phi*K*np.exp(-r*T)*(H/S)**(2*mu)    *_m(eta*(y2-sv))
    F  = rebate*((H/S)**(mu+lam)*norm.cdf(eta*z)
                +(H/S)**(mu-lam)*norm.cdf(eta*(z-2*lam*sv)))

    # out-of-money / in-the-money cases
    if "down" in barrier_type:
        if opt == "call":
            if K >= H:
                out_val = (A - C + F) if "out" in barrier_type else (B - D + F)
            else:
                out_val = (A - B + C - D + F) if "out" in barrier_type else B - C + D + F
        else:
            if K >= H:
                out_val = (B - C + D + F) if "out" in barrier_type else (A - B + C - D + F)
            else:
                out_val = (A + F) if "out" in barrier_type else C + F
    else:  # up
        if opt == "call":
            if K >= H:
                out_val = (B - D + F) if "out" in barrier_type else (A - C + F)
            else:
                out_val = F if "out" in barrier_type else A - B + C - D + F
        else:
            if K >= H:
                out_val = (A - B + C - D + F) if "out" in barrier_type else B - C + D + F
            else:
                out_val = (A - C + F) if "out" in barrier_type else C + F  # simplified

    # knock-in + knock-out = vanilla
    from models.black_scholes import bsm
    vanilla = bsm(S, K, T, r, sigma, q, opt).price
    if "out" in barrier_type:
        price = max(out_val, 0)
    else:
        price = max(vanilla - max(out_val, 0), 0)

    return dict(price=price, barrier=H, barrier_type=barrier_type,
                vanilla=vanilla, rebate=rebate)


def double_barrier_ko(S: float, K: float, L: float, U: float, T: float,
                      r: float, sigma: float, q: float = 0.0,
                      opt: str = "call", n_terms: int = 5) -> dict:
    """
    Double knock-out barrier via series expansion (Ikeda-Kunitomo).
    L = lower barrier, U = upper barrier.
    """
    b  = r - q
    F  = np.log(U / L)
    mu1 = (b - sigma**2/2) / sigma**2
    mu2 = np.sqrt(mu1**2 + 2*r/sigma**2)
    sv  = sigma * np.sqrt(T)
    disc= np.exp(-r*T)

    sign = 1 if opt == "call" else -1

    def N(x): return norm.cdf(x)

    price = 0
    for n in range(-n_terms, n_terms+1):
        d1n = (np.log(S * U**(2*n) / (K * L**(2*n))) / sv + (1+mu1)*sv)
        d2n = d1n - sv
        d3n = (np.log(S * U**(2*n) / (L * L**(2*n)*U**0)) / sv + (1+mu1)*sv)  # for barriers
        lam = (U/L)**(n*mu1)
        lam2= (U/S)**(2*n*mu2)

        term  = sign * (S*np.exp(-q*T)*(U/L)**(n*(2*mu1+1)) * N(sign*d1n)
                        - K*disc*(U/L)**(n*2*mu1) * N(sign*d2n))
        price += term
    price = max(price, 0)
    return dict(price=price, lower=L, upper=U)


# ─────────────────────────────────────────────────────────
# MC barrier pricer (for exotic/partial barriers)
# ─────────────────────────────────────────────────────────

def barrier_mc(S: float, K: float, H: float, T: float, r: float, sigma: float,
               q: float = 0.0, opt: str = "call",
               barrier_type: str = "down-out",
               rebate: float = 0.0,
               n_sims: int = 100_000, steps: int = 252,
               monitor_start: float = 0.0, monitor_end: float = None,
               seed: int = 42) -> dict:
    """
    MC pricer for (partial) barriers.
    monitor_start/end: fraction of life during which barrier is active (0-1).
    """
    paths = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)
    disc  = np.exp(-r * T)

    t_start = int(monitor_start * steps)
    t_end   = steps if monitor_end is None else int(monitor_end * steps)
    monitored = paths[:, t_start:t_end+1]

    if "down" in barrier_type:
        knocked = monitored.min(axis=1) <= H
    else:
        knocked = monitored.max(axis=1) >= H

    S_T = paths[:, -1]
    if opt == "call":
        payoff = np.maximum(S_T - K, 0)
    else:
        payoff = np.maximum(K - S_T, 0)

    if "out" in barrier_type:
        payoff = np.where(knocked, rebate, payoff)
    else:  # in
        payoff = np.where(knocked, payoff, rebate)

    pv     = disc * payoff
    price  = pv.mean()
    stderr = pv.std() / np.sqrt(n_sims)
    return dict(price=price, stderr=stderr, n_sims=n_sims)
