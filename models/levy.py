"""
Lévy / jump models via the Fourier COS method (Master-plan M1).

A single COS pricer (Fang-Oosterlee 2008) values a European option from any
risk-neutral characteristic function of the log-return x = ln(S_T/S_0):
    Merton, Kou (double-exponential), Variance Gamma, CGMY, NIG — plus GBM as a
sanity anchor. Each model supplies (cf, c1, c2): its CF and the first two
cumulants of the log-return (for the truncation interval). All CFs carry the
martingale compensator so E[S_T] = S_0 e^{(r-q)T}.

COS converges exponentially for these smooth CFs, so a few hundred terms price
to machine-ish accuracy and the same CF calibrates fast against a smile.
"""

from __future__ import annotations

import numpy as np
from scipy.special import gamma as gamma_fn


# ── COS engine ───────────────────────────────────────────

def _chi_psi(a, b, c, d, k):
    """Analytic COS payoff integrals χ_k(c,d) and ψ_k(c,d)."""
    bma = b - a
    kpi = k * np.pi / bma
    # ψ
    psi = np.empty_like(k, dtype=float)
    psi[0] = d - c
    psi[1:] = (np.sin(kpi[1:] * (d - a)) - np.sin(kpi[1:] * (c - a))) / kpi[1:]
    # χ
    chi = (1.0 / (1.0 + kpi**2)) * (
        np.cos(kpi * (d - a)) * np.exp(d) - np.cos(kpi * (c - a)) * np.exp(c)
        + kpi * np.sin(kpi * (d - a)) * np.exp(d)
        - kpi * np.sin(kpi * (c - a)) * np.exp(c))
    return chi, psi


def cos_price(cf, c1, c2, S, K, T, r, q, opt="call", N=256, L=12.0) -> float:
    """
    European option price via the COS method.
    cf:  characteristic function of x=ln(S_T/S_0) under the pricing measure,
         callable cf(u) -> complex (vectorised over real u).
    c1,c2: first two cumulants of x (interval = [c1 - L√c2, c1 + L√c2]).
    """
    c2 = max(float(c2), 1e-12)
    a = c1 - L * np.sqrt(c2)
    b = c1 + L * np.sqrt(c2)
    k = np.arange(N)
    u = k * np.pi / (b - a)
    x = np.log(S / K)

    if opt == "call":
        chi, psi = _chi_psi(a, b, 0.0, b, k)
        Uk = 2.0 / (b - a) * (chi - psi)
    else:
        chi, psi = _chi_psi(a, b, a, 0.0, k)
        Uk = 2.0 / (b - a) * (-chi + psi)

    phi = cf(u)
    terms = np.real(phi * np.exp(1j * u * (x - a))) * Uk
    terms[0] *= 0.5
    price = K * np.exp(-r * T) * np.sum(terms)
    return float(max(price, 0.0))


# ── Characteristic functions (x = ln(S_T/S_0)) + cumulants ──

def cf_gbm(S, T, r, q, sigma):
    drift = r - q - 0.5 * sigma**2
    cf = lambda u: np.exp(1j * u * drift * T - 0.5 * sigma**2 * u**2 * T)
    return cf, drift * T, sigma**2 * T


def cf_merton(S, T, r, q, sigma, lam, mu_j, delta_j):
    omega = lam * (np.exp(mu_j + 0.5 * delta_j**2) - 1.0)        # compensator
    drift = r - q - 0.5 * sigma**2 - omega
    def cf(u):
        diff = 1j * u * drift - 0.5 * sigma**2 * u**2
        jump = lam * (np.exp(1j * u * mu_j - 0.5 * delta_j**2 * u**2) - 1.0)
        return np.exp(T * (diff + jump))
    c1 = (drift + lam * mu_j) * T
    c2 = (sigma**2 + lam * (mu_j**2 + delta_j**2)) * T
    return cf, c1, c2


def cf_kou(S, T, r, q, sigma, lam, p, eta1, eta2):
    """Kou double-exponential: p up-jumps rate η1>1, (1-p) down-jumps rate η2>0."""
    eJ = p * eta1 / (eta1 - 1.0) + (1.0 - p) * eta2 / (eta2 + 1.0)
    omega = lam * (eJ - 1.0)
    drift = r - q - 0.5 * sigma**2 - omega
    def cf(u):
        diff = 1j * u * drift - 0.5 * sigma**2 * u**2
        jump = lam * (p * eta1 / (eta1 - 1j * u) + (1 - p) * eta2 / (eta2 + 1j * u) - 1.0)
        return np.exp(T * (diff + jump))
    mean_j = p / eta1 - (1 - p) / eta2
    var_j = p * 2 / eta1**2 + (1 - p) * 2 / eta2**2
    c1 = (drift + lam * mean_j) * T
    c2 = (sigma**2 + lam * var_j) * T
    return cf, c1, c2


def cf_vg(S, T, r, q, sigma, nu, theta):
    """Variance Gamma (σ vol, ν variance rate, θ skew)."""
    omega = (1.0 / nu) * np.log(1.0 - theta * nu - 0.5 * sigma**2 * nu)
    def cf(u):
        return (np.exp(1j * u * (r - q + omega) * T)
                * (1.0 - 1j * u * theta * nu + 0.5 * sigma**2 * nu * u**2) ** (-T / nu))
    c1 = (r - q + omega + theta) * T
    c2 = (sigma**2 + nu * theta**2) * T
    return cf, c1, c2


def cf_nig(S, T, r, q, alpha, beta, delta):
    """Normal Inverse Gaussian (α tail, β skew, δ scale); |β|<α.

    Martingale drift μ chosen so cf(-i)=e^{(r-q)T}: μ = r-q + δ(√(α²-(β+1)²)-√(α²-β²)).
    """
    g0 = np.sqrt(alpha**2 - beta**2)
    mu = r - q + delta * (np.sqrt(alpha**2 - (beta + 1.0)**2) - g0)
    def cf(u):
        return np.exp(1j * u * mu * T
                      + delta * T * (g0 - np.sqrt(alpha**2 - (beta + 1j * u)**2)))
    c1 = mu * T + delta * T * beta / g0
    c2 = delta * T * alpha**2 / g0**3
    return cf, c1, c2


def cf_cgmy(S, T, r, q, C, G, M, Y):
    """CGMY (C activity, G/M down/up decay, Y∈(0,2) fine structure)."""
    base = C * gamma_fn(-Y) * ((M - 1.0) ** Y - M**Y + (G + 1.0) ** Y - G**Y)
    omega = -base                                               # compensator: drift offset
    def cf(u):
        psi = C * gamma_fn(-Y) * ((M - 1j * u) ** Y - M**Y + (G + 1j * u) ** Y - G**Y)
        return np.exp(1j * u * (r - q + omega) * T + T * psi)
    c1 = (r - q + omega) * T + C * T * gamma_fn(1 - Y) * (M ** (Y - 1) - G ** (Y - 1))
    c2 = C * T * gamma_fn(2 - Y) * (M ** (Y - 2) + G ** (Y - 2))
    return cf, c1, c2


# ── Pricers (thin wrappers over the COS engine) ──────────

def _greeks_fd(price_fn, S):
    h = S * 1e-3
    delta = (price_fn(S + h) - price_fn(S - h)) / (2 * h)
    gamma = (price_fn(S + h) - 2 * price_fn(S) + price_fn(S - h)) / h**2
    return delta, gamma


def _price_at(cf_builder, K, T, r, q, opt, N):
    """Helper: S -> COS price, rebuilding the CF at the bumped spot."""
    return lambda s: cos_price(*cf_builder(s), S=s, K=K, T=T, r=r, q=q, opt=opt, N=N)


def merton_cos(S, K, T, r, sigma, q=0.0, lam=0.3, mu_j=-0.1, delta_j=0.15,
               opt="call", N=256) -> dict:
    build = lambda s: cf_merton(s, T, r, q, sigma, lam, mu_j, delta_j)
    fn = _price_at(build, K, T, r, q, opt, N)
    d, g = _greeks_fd(fn, S)
    return dict(price=fn(S), delta=d, gamma=g, model="merton_cos")


def kou_price(S, K, T, r, sigma, q=0.0, lam=0.5, p=0.4, eta1=10.0, eta2=5.0,
              opt="call", N=256) -> dict:
    build = lambda s: cf_kou(s, T, r, q, sigma, lam, p, eta1, eta2)
    fn = _price_at(build, K, T, r, q, opt, N)
    d, g = _greeks_fd(fn, S)
    return dict(price=fn(S), delta=d, gamma=g, model="kou")


def vg_price(S, K, T, r, sigma, q=0.0, nu=0.2, theta=-0.1, opt="call", N=256) -> dict:
    build = lambda s: cf_vg(s, T, r, q, sigma, nu, theta)
    fn = _price_at(build, K, T, r, q, opt, N)
    d, g = _greeks_fd(fn, S)
    return dict(price=fn(S), delta=d, gamma=g, model="variance_gamma")


def nig_price(S, K, T, r, alpha=15.0, beta=-5.0, delta=0.5, q=0.0,
              opt="call", N=256) -> dict:
    build = lambda s: cf_nig(s, T, r, q, alpha, beta, delta)
    fn = _price_at(build, K, T, r, q, opt, N)
    d, g = _greeks_fd(fn, S)
    return dict(price=fn(S), delta=d, gamma=g, model="nig")


def cgmy_price(S, K, T, r, C=0.1, G=5.0, M=5.0, Y=0.8, q=0.0,
               opt="call", N=512) -> dict:
    build = lambda s: cf_cgmy(s, T, r, q, C, G, M, Y)
    fn = _price_at(build, K, T, r, q, opt, N)
    d, g = _greeks_fd(fn, S)
    return dict(price=fn(S), delta=d, gamma=g, model="cgmy")


def cos_price_bsm(S, K, T, r, sigma, q=0.0, opt="call", N=256) -> float:
    """GBM via COS — for testing the engine against the Black-Scholes closed form."""
    cf, c1, c2 = cf_gbm(S, T, r, q, sigma)
    return cos_price(cf, c1, c2, S, K, T, r, q, opt, N)


def cos_smile(cf, c1, c2, S, strikes, T, r, q, opt="call", N=256) -> list:
    """
    Price a whole strike grid with COS (calibration helper). COS reuses the CF
    across strikes cheaply, so this replaces a Carr-Madan FFT for our grid sizes
    while staying numerically robust.
    """
    return [cos_price(cf, c1, c2, S, float(k), T, r, q, opt, N) for k in strikes]
