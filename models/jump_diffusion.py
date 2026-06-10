"""
Jump-diffusion models (Phase 3).

- Merton (1976) lognormal jump-diffusion: exact Poisson-mixture series of BSM
  prices; jump-MC cross-check (terminal sampling, exact in distribution).
- Bates (1996) = Heston stochastic vol + Merton jumps, semi-analytic via the
  characteristic function (Gil-Pelaez, reusing the Heston CF).
"""

import numpy as np
from scipy.integrate import quad

from models.black_scholes import bsm
from models.heston import _heston_cf


# ─────────────────────────────────────────────────────────
# Merton jump-diffusion
# ─────────────────────────────────────────────────────────

def merton_price(S: float, K: float, T: float, r: float, sigma: float,
                 q: float = 0.0, lam: float = 0.1, mu_j: float = -0.1,
                 delta_j: float = 0.15, opt: str = "call",
                 max_terms: int = 60) -> dict:
    """
    Merton jump-diffusion: jumps ~ lognormal(mu_j, delta_j²), intensity lam.
    Price = Poisson mixture of BSM prices with per-term adjusted (r_n, sigma_n).
    Greeks are the same mixture of BSM Greeks (vega w.r.t. the diffusion vol).
    """
    k = np.exp(mu_j + 0.5 * delta_j**2) - 1.0     # mean jump size
    lam_p = lam * (1.0 + k)
    price = delta = gamma = vega = 0.0
    weight_sum = 0.0
    for n in range(max_terms):
        log_w = -lam_p * T + n * np.log(max(lam_p * T, 1e-300)) - sum(
            np.log(i) for i in range(1, n + 1))
        w = np.exp(log_w) if lam_p * T > 0 else (1.0 if n == 0 else 0.0)
        if n > 0 and w < 1e-14 and weight_sum > 0.999:
            break
        sigma_n = np.sqrt(sigma**2 + n * delta_j**2 / T)
        r_n = r - lam * k + n * np.log(1.0 + k) / T
        g = bsm(S, K, T, r_n, sigma_n, q, opt)
        price += w * g.price
        delta += w * g.delta
        gamma += w * g.gamma
        vega += w * g.vega * (sigma / sigma_n)    # chain rule to diffusion vol
        weight_sum += w
    return dict(price=price, delta=delta, gamma=gamma, vega=vega,
                lam=lam, mu_j=mu_j, delta_j=delta_j, n_terms=n + 1,
                model="merton_jump")


def merton_mc(S: float, K: float, T: float, r: float, sigma: float,
              q: float = 0.0, lam: float = 0.1, mu_j: float = -0.1,
              delta_j: float = 0.15, opt: str = "call",
              n_sims: int = 200_000, seed: int = 42) -> dict:
    """European Merton price via exact terminal sampling (Poisson + normals)."""
    rng = np.random.default_rng(seed)
    k = np.exp(mu_j + 0.5 * delta_j**2) - 1.0
    N = rng.poisson(lam * T, n_sims)
    Z = rng.standard_normal(n_sims)
    Zj = rng.standard_normal(n_sims)
    drift = (r - q - 0.5 * sigma**2 - lam * k) * T
    jumps = N * mu_j + delta_j * np.sqrt(N) * Zj
    S_T = S * np.exp(drift + sigma * np.sqrt(T) * Z + jumps)
    pay = np.maximum(S_T - K, 0) if opt == "call" else np.maximum(K - S_T, 0)
    pv = np.exp(-r * T) * pay
    return dict(price=pv.mean(), stderr=pv.std() / np.sqrt(n_sims), n_sims=n_sims)


# ─────────────────────────────────────────────────────────
# Bates (Heston + jumps)
# ─────────────────────────────────────────────────────────

def _bates_cf(phi, S, v0, r, q, kappa, theta, xi, rho, T,
              lam, mu_j, delta_j):
    """CF of log(S_T) under Bates: Heston CF × compensated jump factor."""
    k = np.exp(mu_j + 0.5 * delta_j**2) - 1.0
    jump = np.exp(T * lam * (np.exp(1j * phi * mu_j - 0.5 * delta_j**2 * phi**2) - 1.0)
                  - 1j * phi * lam * k * T)
    return _heston_cf(phi, S, v0, r, q, kappa, theta, xi, rho, T) * jump


def bates_price(S: float, K: float, T: float, r: float, q: float,
                v0: float, kappa: float, theta: float, xi: float, rho: float,
                lam: float = 0.1, mu_j: float = -0.1, delta_j: float = 0.15,
                opt: str = "call") -> dict:
    """Bates (1996) price via Gil-Pelaez inversion of the Bates CF."""
    disc = np.exp(-r * T)
    log_K = np.log(K)

    def cf(phi):
        return _bates_cf(phi, S, v0, r, q, kappa, theta, xi, rho, T,
                         lam, mu_j, delta_j)

    cf_minus_i = cf(-1j)

    def integrand_P1(phi):
        return np.real(np.exp(-1j * phi * log_K) * cf(phi - 1j) / (1j * phi * cf_minus_i))

    def integrand_P2(phi):
        return np.real(np.exp(-1j * phi * log_K) * cf(phi) / (1j * phi))

    I1, _ = quad(integrand_P1, 1e-6, 200, limit=500, epsabs=1e-7)
    I2, _ = quad(integrand_P2, 1e-6, 200, limit=500, epsabs=1e-7)
    P1, P2 = 0.5 + I1 / np.pi, 0.5 + I2 / np.pi

    call = S * np.exp(-q * T) * P1 - K * disc * P2
    price = max(call, 0.0) if opt == "call" else max(call - S * np.exp(-q * T) + K * disc, 0.0)
    dq = np.exp(-q * T)
    return dict(price=price, delta=dq * P1 if opt == "call" else dq * (P1 - 1),
                v0=v0, kappa=kappa, theta=theta, xi=xi, rho=rho,
                lam=lam, mu_j=mu_j, delta_j=delta_j, model="bates")
