"""Lattice models — no recursion + convergence tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from models.trees import binomial_crr, binomial_lr, trinomial
from models.black_scholes import bsm


def _bsm_price(S, K, T, r, sigma, opt="call"):
    return bsm(S, K, T, r, sigma, 0.0, opt).price


# ── No RecursionError ────────────────────────────────────

def test_crr_no_recursion_european():
    res = binomial_crr(100, 100, 1.0, 0.05, 0.20, N=50)
    assert "price" in res and res["price"] > 0


def test_crr_no_recursion_american():
    res = binomial_crr(100, 100, 1.0, 0.05, 0.20, N=50, exercise="american")
    assert "price" in res


def test_lr_no_recursion():
    res = binomial_lr(100, 100, 1.0, 0.05, 0.20, N=51)
    assert "price" in res and res["price"] > 0


def test_trinomial_no_recursion():
    res = trinomial(100, 100, 1.0, 0.05, 0.20, N=50)
    assert "price" in res and res["price"] > 0


# ── Convergence to BSM ───────────────────────────────────

@pytest.mark.parametrize("S,K,T,r,sigma,opt", [
    (100, 100, 1.0, 0.05, 0.20, "call"),
    (100, 110, 0.5, 0.03, 0.25, "put"),
    (90,  100, 0.25, 0.05, 0.30, "call"),
])
def test_crr_european_converges_to_bsm(S, K, T, r, sigma, opt):
    tree = binomial_crr(S, K, T, r, sigma, N=500, opt=opt, exercise="european")
    ref  = _bsm_price(S, K, T, r, sigma, opt)
    assert abs(tree["price"] - ref) < 0.05, (
        f"CRR={tree['price']:.4f} BSM={ref:.4f} diff={abs(tree['price']-ref):.4f}")


def test_lr_european_converges_to_bsm():
    tree = binomial_lr(100, 100, 1.0, 0.05, 0.20, N=101, opt="call")
    ref  = _bsm_price(100, 100, 1.0, 0.05, 0.20, "call")
    assert abs(tree["price"] - ref) < 0.02


def test_trinomial_european_converges_to_bsm():
    tree = trinomial(100, 100, 1.0, 0.05, 0.20, N=200, opt="call")
    ref  = _bsm_price(100, 100, 1.0, 0.05, 0.20, "call")
    assert abs(tree["price"] - ref) < 0.05


# ── American put >= European put ─────────────────────────

def test_crr_american_put_ge_european_put():
    eur = binomial_crr(100, 110, 1.0, 0.05, 0.20, opt="put", exercise="european", N=200)
    ame = binomial_crr(100, 110, 1.0, 0.05, 0.20, opt="put", exercise="american", N=200)
    assert ame["price"] >= eur["price"] - 1e-8


# ── Greeks are finite ────────────────────────────────────

def test_crr_greeks_finite():
    res = binomial_crr(100, 100, 0.5, 0.05, 0.20, N=100)
    for key in ("delta", "gamma", "vega", "theta"):
        assert key in res
        assert abs(res[key]) < 1e6, f"{key}={res[key]} out of range"
