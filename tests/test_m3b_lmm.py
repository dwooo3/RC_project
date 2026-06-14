"""
M3b — LIBOR market model (LMM/BGM). Identity-first: curve reprice, the
defining Black-caplet identity (analytic + non-zero-drift MC under the terminal
measure), caplet/swaption parity, swaption MC vs Rebonato, the decorrelation
identity (swaption vol < cap vol); plus M0 wiring + service routing.
"""
import numpy as np
import pytest

from curves.yield_curve import YieldCurve
from models.lmm import LMM


@pytest.fixture(scope="module")
def curve():
    return YieldCurve.flat(0.05)


@pytest.fixture(scope="module")
def m(curve):
    return LMM(curve, start=0.0, end=5.0, freq=2, vol=0.20, corr_beta=0.1)


# ── Curve fit ────────────────────────────────────────────

def test_curve_reprice(m):
    """Forward rates rebuild the discount curve exactly."""
    P = np.concatenate([[1.0], np.cumprod(1.0 / (1.0 + m.tau * m.L0))])
    assert np.max(np.abs(P - m.P0)) < 1e-13


# ── Black caplet identity ────────────────────────────────

def test_caplet_parity(m):
    k, K = 5, 0.06
    c = m.caplet_black(k, K, "call")
    p = m.caplet_black(k, K, "put")
    assert c - p == pytest.approx(m.P0[k + 1] * m.tau[k] * (m.L0[k] - K), abs=1e-14)


@pytest.mark.parametrize("k", [3, 6, 9])
def test_caplet_mc_equals_black(m, k):
    """The defining identity: a caplet priced under the terminal T_N measure
    (non-zero drift, numeraire rebuilt from sim rates) recovers the Black price."""
    K = m.L0[k]                                       # ATM
    blk = m.caplet_black(k, K, "call")
    mc = m.caplet_mc(k, K, "call", n_sims=200_000, steps=2 * int(m.reset[k]) + 4, seed=7)
    assert mc["price"] == pytest.approx(blk, abs=4 * mc["stderr"])


# ── Swaption ─────────────────────────────────────────────

def test_swaption_mc_vs_rebonato(m):
    a, b = 2, 10                                      # 1y into 4y
    for K in (0.045, 0.05, 0.055):
        mc = m.swaption(1_000_000, K, a, b, "payer", n_sims=200_000, steps=16, seed=11)
        blk = m.swaption_black(1_000_000, K, a, b, "payer")
        assert mc["price"] == pytest.approx(blk, abs=4 * mc["stderr"] + 0.005 * blk), K


def test_swaption_parity(m, curve):
    a, b, K = 2, 10, 0.05
    S0, ann = m._swap(a, b)
    pay = m.swaption(1_000_000, K, a, b, "payer", n_sims=200_000, steps=16, seed=11)
    rec = m.swaption(1_000_000, K, a, b, "receiver", n_sims=200_000, steps=16, seed=11)
    parity = pay["price"] - rec["price"] - 1_000_000 * ann * (S0 - K)
    assert parity == pytest.approx(0.0, abs=3 * (pay["stderr"] + rec["stderr"]) + 50)


def test_decorrelation_lowers_swaption_vol(curve):
    """Perfect correlation -> swaption vol == cap vol; decorrelation lowers it."""
    a, b = 2, 10
    full = LMM(curve, 0.0, 5.0, 2, vol=0.20, corr_beta=1e-9)
    dec = LMM(curve, 0.0, 5.0, 2, vol=0.20, corr_beta=0.1)
    assert full.rebonato_swaption_vol(a, b) == pytest.approx(0.20, abs=1e-3)
    assert dec.rebonato_swaption_vol(a, b) < 0.20


def test_degenerate_correlation_repaired(curve):
    """An all-ones (rank-1) correlation input is repaired to positive-definite."""
    m = LMM(curve, 0.0, 5.0, 2, vol=0.20, corr=np.ones((10, 10)))
    np.linalg.cholesky(m.corr)                        # must not raise
    assert np.allclose(np.diag(m.corr), 1.0)


# ── M0 wiring + service ──────────────────────────────────

def test_lmm_wired():
    from models import taxonomy as tax
    from models import parameters as P
    from models import registry as R
    assert "lmm" in tax.engines_for("swaption")
    assert "lmm" in tax.engines_for("cap_floor")
    cls = tax.classify("lmm")
    assert cls["asset_class"] == "rates" and cls["model_family"] == "market_model"
    assert {"vol", "corr_beta"} <= {s.key for s in P.engine_params("lmm")}
    assert R.MODEL_REGISTRY["lmm"]["status"].value == "Approximation"


def test_lmm_service_routes():
    from services.pricing_service import PricingService
    svc = PricingService()
    sw = svc.price_lmm_swaption(1_000_000, 0.10, 1.0, 4.0, n_sims=20_000, steps=12)
    assert sw["errors"] == [] and sw["value"] > 0 and sw["model_id"] == "lmm"
    cap = svc.price_lmm_cap(1_000_000, 0.10, 3.0, vol=0.25)
    assert cap["errors"] == [] and cap["value"] > 0


def test_swaption_engine_dispatch_lmm():
    from app.panels.pricing_catalogue import products_by_category
    from services.pricing_service import PricingService
    svc = PricingService()
    prod = next(p for p in products_by_category("Swaps") if p.id == "swaption")
    assert "lmm" in prod.engines()
    base = {"notional": 1_000_000, "K": 0.10, "T_option": 1.0, "T_swap": 4.0,
            "freq": 2, "sigma": 0.20, "r": 0.10, "opt": "payer"}
    res = prod.price(svc, dict(base, __engine="lmm", vol=0.20, corr_beta=0.1,
                               n_sims=20_000, steps=12))
    assert res["errors"] == [] and res["value"] > 0
