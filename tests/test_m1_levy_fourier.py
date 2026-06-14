"""
M1 — Lévy/jump models via the Fourier COS method. Identity-first: each model's
degenerate limit equals BSM, put-call parity holds, and COS agrees with MC /
the existing Merton series. Headless.
"""
import numpy as np
import pytest

from models.black_scholes import bsm
from models import levy as L


S, K, T, r, q, SIG = 100.0, 100.0, 1.0, 0.05, 0.0, 0.20
BSM = bsm(S, K, T, r, SIG, q).price


def _parity(call, put):
    return call - put - (S * np.exp(-q * T) - K * np.exp(-r * T))


# ── COS engine sanity ────────────────────────────────────

def test_cos_engine_matches_bsm():
    assert L.cos_price_bsm(S, K, T, r, SIG) == pytest.approx(BSM, abs=1e-8)
    # across strikes
    for k in (80, 100, 120):
        assert L.cos_price_bsm(S, k, T, r, SIG, opt="put") == pytest.approx(
            bsm(S, k, T, r, SIG, q, "put").price, abs=1e-6)


# ── Merton via COS == Merton series ──────────────────────

def test_merton_cos_matches_series():
    from models.jump_diffusion import merton_price
    cos = L.merton_cos(S, K, T, r, SIG, q, 0.3, -0.1, 0.15, "call")["price"]
    ser = merton_price(S, K, T, r, SIG, q, 0.3, -0.1, 0.15, "call")["price"]
    assert cos == pytest.approx(ser, abs=1e-3)


# ── Degenerate limits -> BSM ─────────────────────────────

def test_kou_lambda_zero_is_bsm():
    assert L.kou_price(S, K, T, r, SIG, q, lam=0.0)["price"] == pytest.approx(BSM, abs=1e-3)


def test_vg_nu_to_zero_is_bsm():
    assert L.vg_price(S, K, T, r, SIG, q, nu=1e-4, theta=0.0)["price"] == pytest.approx(
        BSM, abs=2e-2)


# ── Put-call parity (all Lévy) ───────────────────────────

@pytest.mark.parametrize("name,fn", [
    ("kou", lambda o: L.kou_price(S, K, T, r, SIG, q, opt=o)["price"]),
    ("vg", lambda o: L.vg_price(S, K, T, r, SIG, q, opt=o)["price"]),
    ("nig", lambda o: L.nig_price(S, K, T, r, 15.0, -5.0, 0.5, q, o)["price"]),
])
def test_levy_put_call_parity(name, fn):
    assert _parity(fn("call"), fn("put")) == pytest.approx(0.0, abs=1e-5)


def test_cgmy_parity_loose():
    # CGMY heavy tails: parity within a few bp (Prototype, see registry note)
    c = L.cgmy_price(S, K, T, r, opt="call", N=1024)["price"]
    p = L.cgmy_price(S, K, T, r, opt="put", N=1024)["price"]
    assert _parity(c, p) == pytest.approx(0.0, abs=2e-3)


# ── MC cross-checks ──────────────────────────────────────

def test_kou_vs_mc():
    """COS Kou agrees with a direct double-exponential jump MC."""
    rng = np.random.default_rng(11)
    n = 300_000
    lam, p, eta1, eta2 = 0.5, 0.4, 10.0, 5.0
    eJ = p * eta1 / (eta1 - 1) + (1 - p) * eta2 / (eta2 + 1)
    omega = lam * (eJ - 1)
    drift = (r - q - 0.5 * SIG**2 - omega) * T
    Nj = rng.poisson(lam * T, n)
    jumps = np.zeros(n)
    for i in range(n):
        if Nj[i]:
            up = rng.random(Nj[i]) < p
            j = np.where(up, rng.exponential(1 / eta1, Nj[i]),
                         -rng.exponential(1 / eta2, Nj[i]))
            jumps[i] = j.sum()
    x = drift + SIG * np.sqrt(T) * rng.standard_normal(n) + jumps
    ST = S * np.exp(x)
    pv = np.exp(-r * T) * np.maximum(ST - K, 0)
    mc, se = pv.mean(), pv.std() / np.sqrt(n)
    cos = L.kou_price(S, K, T, r, SIG, q, lam, p, eta1, eta2, "call")["price"]
    assert cos == pytest.approx(mc, abs=4 * se + 0.02)


def test_nig_vs_subordinator_mc():
    rng = np.random.default_rng(7)
    n = 300_000
    alpha, beta, delta = 15.0, -5.0, 0.5
    g0 = np.sqrt(alpha**2 - beta**2)
    mu = r - q + delta * (np.sqrt(alpha**2 - (beta + 1)**2) - g0)
    y = rng.wald(delta * T / g0, (delta * T)**2, n)         # IG subordinator
    x = mu * T + beta * y + np.sqrt(y) * rng.standard_normal(n)
    pv = np.exp(-r * T) * np.maximum(S * np.exp(x) - K, 0)
    mc, se = pv.mean(), pv.std() / np.sqrt(n)
    cos = L.nig_price(S, K, T, r, alpha, beta, delta, q, "call")["price"]
    assert cos == pytest.approx(mc, abs=4 * se + 0.02)


# ── COS smile (calibration helper) ───────────────────────

def test_cos_smile_grid():
    cf, c1, c2 = L.cf_vg(S, T, r, q, 0.2, 0.2, -0.1)      # sigma, nu, theta
    ks = [90.0, 100.0, 110.0]
    smile = L.cos_smile(cf, c1, c2, S, ks, T, r, q, "call")
    assert len(smile) == 3 and smile[0] > smile[1] > smile[2] > 0   # monotone in K
    # matches the standalone vg_price at each strike
    for k, c in zip(ks, smile):
        assert c == pytest.approx(L.vg_price(S, k, T, r, 0.2, q, 0.2, -0.1, "call")["price"],
                                  abs=1e-9)


# ── Greeks sanity ────────────────────────────────────────

def test_levy_greeks_reasonable():
    for fn in (lambda: L.kou_price(S, K, T, r, SIG, q),
               lambda: L.vg_price(S, K, T, r, SIG, q),
               lambda: L.nig_price(S, K, T, r)):
        res = fn()
        assert 0.0 < res["delta"] < 1.0 and res["gamma"] > 0


# ── Service routing + governance gating + UI dispatch ────

def test_levy_service_lab_gated():
    from services.pricing_service import PricingService
    prod = PricingService()                              # production: lab models blocked
    blocked = prod.price_levy_option("kou", S, K, T, r, SIG, q)
    assert blocked["errors"]
    lab = PricingService(allow_analytics_lab=True)
    ok = lab.price_levy_option("kou", S, K, T, r, SIG, q, lam=0.5)
    assert ok["errors"] == [] and ok["value"] > 0


def test_levy_engines_in_taxonomy_and_params():
    from models import taxonomy as tax
    from models import parameters as P
    from models import registry as R
    for e in ("kou", "variance_gamma", "nig", "cgmy"):
        assert e in tax.engines_for("european_option")
        assert e in R.MODEL_REGISTRY
        assert P.engine_params(e)                        # has model/numerical specs
        assert tax.classify(e)["method"] == "fourier"


def test_vanilla_dispatch_to_levy():
    from app.panels.pricing_catalogue import products_by_category
    from models.parameters import engine_params
    from services.pricing_service import PricingService
    svc = PricingService(allow_analytics_lab=True)
    prod = next(p for p in products_by_category("Option") if p.id == "vanilla")
    base = {"S": 100, "K": 100, "T": 1.0, "r": 0.05, "sigma": 0.20, "q": 0.0, "opt": "call"}
    for eng in ("kou", "variance_gamma", "nig"):
        v = dict(base, __engine=eng)
        for s in engine_params(eng):
            v.setdefault(s.key, s.default)
        res = prod.price(svc, v)
        assert res["errors"] == [] and res["value"] > 0, eng
