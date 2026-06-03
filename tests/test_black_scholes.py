"""BSM / Black-76 / GK / Bachelier — validation tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest
from models.black_scholes import bsm, black76, garman_kohlhagen, bachelier


# ── BSM ──────────────────────────────────────────────────

def test_bsm_atm_call_known_value():
    """ATM call S=K=100, T=1, r=5%, σ=20% → ~10.45."""
    g = bsm(100, 100, 1.0, 0.05, 0.20)
    assert abs(g.price - 10.4506) < 0.001, f"price={g.price}"


def test_bsm_put_call_parity():
    """C - P = S*e^{-qT} - K*e^{-rT}."""
    S, K, T, r, sigma, q = 105, 100, 0.5, 0.04, 0.25, 0.01
    c = bsm(S, K, T, r, sigma, q, "call")
    p = bsm(S, K, T, r, sigma, q, "put")
    lhs = c.price - p.price
    rhs = S * np.exp(-q * T) - K * np.exp(-r * T)
    assert abs(lhs - rhs) < 1e-8, f"PCP violated: {lhs} vs {rhs}"


def test_bsm_delta_bounds():
    g_c = bsm(100, 100, 0.5, 0.05, 0.20, opt="call")
    g_p = bsm(100, 100, 0.5, 0.05, 0.20, opt="put")
    assert 0 < g_c.delta < 1
    assert -1 < g_p.delta < 0


def test_bsm_gamma_positive():
    g = bsm(100, 100, 0.5, 0.05, 0.20)
    assert g.gamma > 0


def test_bsm_vega_positive():
    g = bsm(100, 100, 0.5, 0.05, 0.20)
    assert g.vega > 0


def test_bsm_expiry_zero_intrinsic():
    g_c = bsm(110, 100, 0.0, 0.05, 0.20, opt="call")
    assert abs(g_c.price - 10.0) < 1e-9
    g_p = bsm(90, 100, 0.0, 0.05, 0.20, opt="put")
    assert abs(g_p.price - 10.0) < 1e-9


# ── Black-76 ─────────────────────────────────────────────

def test_black76_put_call_parity():
    F, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20
    c = black76(F, K, T, r, sigma, "call")
    p = black76(F, K, T, r, sigma, "put")
    disc = np.exp(-r * T)
    assert abs((c.price - p.price) - disc * (F - K)) < 1e-8


# ── Garman-Kohlhagen ─────────────────────────────────────

def test_gk_equals_bsm_with_q():
    """GK(r_d, r_f) == BSM(r=r_d, q=r_f)."""
    S, K, T, r_d, r_f, sigma = 1.08, 1.09, 0.25, 0.04, 0.02, 0.08
    gk = garman_kohlhagen(S, K, T, r_d, r_f, sigma, "call")
    bs = bsm(S, K, T, r_d, sigma, r_f, "call")
    assert abs(gk.price - bs.price) < 1e-12


def test_gk_put_call_parity():
    S, K, T, r_d, r_f, sigma = 1.08, 1.10, 0.5, 0.04, 0.02, 0.08
    c = garman_kohlhagen(S, K, T, r_d, r_f, sigma, "call")
    p = garman_kohlhagen(S, K, T, r_d, r_f, sigma, "put")
    lhs = c.price - p.price
    rhs = S * np.exp(-r_f * T) - K * np.exp(-r_d * T)
    assert abs(lhs - rhs) < 1e-8


# ── Bachelier ─────────────────────────────────────────────

def test_bachelier_atm_known_value():
    """Bachelier ATM call: C = F * sigma_n * sqrt(T/2pi) * disc."""
    F, K, T, r, sigma_n = 0.05, 0.05, 1.0, 0.02, 0.005
    g = bachelier(F, K, T, r, sigma_n, "call")
    disc = np.exp(-r * T)
    expected = disc * sigma_n * np.sqrt(T / (2 * np.pi))
    assert abs(g.price - expected) < 1e-7, f"price={g.price}, expected={expected}"


def test_bachelier_put_call_parity():
    F, K, T, r, sigma_n = 0.04, 0.05, 0.5, 0.03, 0.004
    c = bachelier(F, K, T, r, sigma_n, "call")
    p = bachelier(F, K, T, r, sigma_n, "put")
    disc = np.exp(-r * T)
    assert abs((c.price - p.price) - disc * (F - K)) < 1e-8
