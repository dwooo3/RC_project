"""
Carr-Madan FFT option pricing, gap-closing batch 2.

Prices a whole strip of European calls in one FFT from the characteristic
function φ(u)=E[e^{iu·ln S_T}] of any model, via the Carr-Madan (1999) damped
transform:

    C(k) = e^{-αk}/π · ∫₀^∞ Re[e^{-iuk}·ζ(u)] du,
    ζ(u) = e^{-rT}·φ(u-(α+1)i) / (α²+α-u²+i(2α+1)u)

A Simpson-weighted FFT evaluates C(k) on a log-strike grid; we interpolate to
the requested strike. Validated against Black-Scholes (Gaussian φ) and the
Heston CF pricer.
"""

from __future__ import annotations

import numpy as np


def cf_bsm(S, T, r, q, sigma):
    """Characteristic function of ln S_T under BSM."""
    def phi(u):
        mu = np.log(S) + (r - q - 0.5 * sigma**2) * T
        return np.exp(1j * u * mu - 0.5 * sigma**2 * T * u**2)
    return phi


def cf_heston(S, T, r, q, v0, kappa, theta, sigma, rho):
    """Heston characteristic function of ln S_T (little-trap form)."""
    def phi(u):
        xi = kappa - rho * sigma * 1j * u
        dd = np.sqrt(xi**2 + sigma**2 * (1j * u + u**2))
        g = (xi - dd) / (xi + dd)
        exp_dt = np.exp(-dd * T)
        C = ((r - q) * 1j * u * T + kappa * theta / sigma**2
             * ((xi - dd) * T - 2 * np.log((1 - g * exp_dt) / (1 - g))))
        D = (xi - dd) / sigma**2 * ((1 - exp_dt) / (1 - g * exp_dt))
        return np.exp(C + D * v0 + 1j * u * np.log(S))
    return phi


def carr_madan(phi, K, T, r, opt="call", alpha=1.5, N=4096, eta=0.25):
    """Carr-Madan FFT price of a European option for log-price CF `phi`."""
    lam = 2 * np.pi / (N * eta)
    b = N * lam / 2
    u = np.arange(N) * eta
    # Simpson weights
    w = (3 + (-1) ** np.arange(1, N + 1)) / 3.0
    w[0] = 1 / 3.0
    psi = (np.exp(-r * T) * phi(u - (alpha + 1) * 1j)
           / (alpha**2 + alpha - u**2 + 1j * (2 * alpha + 1) * u))
    x = np.exp(1j * b * u) * psi * eta * w
    fft = np.real(np.fft.fft(x))
    ks = -b + lam * np.arange(N)
    calls = np.exp(-alpha * ks) / np.pi * fft
    lnK = np.log(K)
    call = float(np.interp(lnK, ks, calls))
    if opt == "call":
        return call
    # put via parity needs the forward; recover S from phi(-i)=E[S_T]e^{?}...
    # simpler: caller uses BSM/Heston parity. Here return call; put handled by wrapper.
    return call


def carr_madan_bsm(S, K, T, r, sigma, q=0.0, opt="call", **kw) -> float:
    c = carr_madan(cf_bsm(S, T, r, q, sigma), K, T, r, "call", **kw)
    if opt == "call":
        return c
    return c - S * np.exp(-q * T) + K * np.exp(-r * T)


def carr_madan_heston(S, K, T, r, q, v0, kappa, theta, sigma, rho, opt="call", **kw) -> float:
    c = carr_madan(cf_heston(S, T, r, q, v0, kappa, theta, sigma, rho), K, T, r, "call", **kw)
    if opt == "call":
        return c
    return c - S * np.exp(-q * T) + K * np.exp(-r * T)
