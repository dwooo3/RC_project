"""
M3a — G2++ two-factor Gaussian short rate. Identity-first: curve reprice,
ZCB-option parity, η→0 collapse to one-factor Hull-White, swaption MC vs HW1F
Jamshidian, payer-receiver parity; plus M0 wiring + service routing.
"""
import numpy as np
import pytest

from curves.yield_curve import YieldCurve
from models.g2pp import G2pp
from models.short_rate import HullWhite


@pytest.fixture(scope="module")
def curve():
    return YieldCurve.flat(0.10)


@pytest.fixture(scope="module")
def g2(curve):
    return G2pp(curve, a=0.1, sigma=0.01, b=0.3, eta=0.012, rho=-0.7)


# ── Curve fit ────────────────────────────────────────────

def test_curve_reprice(g2, curve):
    for T in (0.5, 1, 5, 10, 20):
        assert g2.bond_price(0.0, T) == pytest.approx(curve.discount(T), abs=1e-12)


# ── ZCB option ───────────────────────────────────────────

def test_zcb_option_parity(g2, curve):
    To, Tb, K = 1.0, 5.0, 0.65
    c = g2.zcb_option(To, Tb, K, "call")
    p = g2.zcb_option(To, Tb, K, "put")
    assert c - p == pytest.approx(curve.discount(Tb) - K * curve.discount(To), abs=1e-12)
    assert c > 0 and p > 0


def test_eta_zero_collapses_to_hw1f(curve):
    """η→0 (second factor killed) must match one-factor Hull-White ZCB option."""
    g1 = G2pp(curve, a=0.1, sigma=0.01, b=5.0, eta=1e-7, rho=0.0)
    hw = HullWhite(0.1, 0.01, curve)
    for opt in ("call", "put"):
        assert g1.zcb_option(1.0, 5.0, 0.65, opt) == pytest.approx(
            hw.bond_option(1.0, 5.0, 0.65, opt), abs=1e-6)


# ── Swaption ─────────────────────────────────────────────

def test_swaption_mc_vs_hw1f(curve):
    """Single-factor G2++ swaption (exact sampling) matches HW1F Jamshidian."""
    g1 = G2pp(curve, a=0.1, sigma=0.01, b=5.0, eta=1e-7, rho=0.0)
    hw = HullWhite(0.1, 0.01, curve)
    for K in (0.08, 0.10):
        mc = g1.swaption(1_000_000, K, 1.0, 5.0, 2, "payer", n_sims=100_000)
        jam = hw.swaption(1_000_000, K, 1.0, 5.0, 2)["payer"]
        assert mc["price"] == pytest.approx(jam, abs=4 * mc["stderr"] + 5), K


def test_swaption_payer_receiver_parity(g2, curve):
    pay = g2.swaption(1_000_000, 0.10, 1.0, 5.0, 2, "payer", n_sims=100_000)
    rec = g2.swaption(1_000_000, 0.10, 1.0, 5.0, 2, "receiver", n_sims=100_000)
    ann = sum(0.5 * curve.discount(1 + i * 0.5) for i in range(1, 11))
    S0 = (curve.discount(1) - curve.discount(6)) / ann
    parity = pay["price"] - rec["price"] - 1_000_000 * ann * (S0 - 0.10)
    assert parity == pytest.approx(0.0, abs=3 * (pay["stderr"] + rec["stderr"]) + 50)


def test_two_factor_decorrelation_matters(curve):
    """A 2-factor model with rho!=±1 gives a different swaption than 1-factor."""
    g2 = G2pp(curve, 0.1, 0.01, 0.3, 0.012, -0.7)
    g1 = G2pp(curve, 0.1, 0.01, 5.0, 1e-7, 0.0)
    p2 = g2.swaption(1_000_000, 0.10, 1.0, 5.0, 2, "payer", n_sims=100_000)["price"]
    p1 = g1.swaption(1_000_000, 0.10, 1.0, 5.0, 2, "payer", n_sims=100_000)["price"]
    assert abs(p2 - p1) > 100        # the second factor changes the price


# ── M0 wiring + service ──────────────────────────────────

def test_g2pp_wired():
    from models import taxonomy as tax
    from models import parameters as P
    from models import registry as R
    assert "g2pp" in tax.engines_for("swaption")
    assert tax.classify("g2pp")["asset_class"] == "rates"
    assert {"a", "sigma", "b", "eta", "rho"} <= {s.key for s in P.engine_params("g2pp")}
    assert R.MODEL_REGISTRY["g2pp"]["status"].value == "Approximation"


def test_g2pp_service_route():
    from services.pricing_service import PricingService
    res = PricingService().price_g2pp_swaption(1_000_000, 0.10, 1.0, 5.0, n_sims=20_000)
    assert res["errors"] == [] and res["value"] > 0
    assert res["model_id"] == "g2pp"


def test_swaption_engine_dispatch():
    from app.panels.pricing_catalogue import products_by_category
    from services.pricing_service import PricingService
    svc = PricingService()
    prod = next(p for p in products_by_category("Swaps") if p.id == "swaption")
    assert "g2pp" in prod.engines()
    base = {"notional": 1_000_000, "K": 0.10, "T_option": 1.0, "T_swap": 5.0,
            "freq": 2, "sigma": 0.20, "r": 0.10, "opt": "payer"}
    black = prod.price(svc, dict(base, __engine="swaption"))
    g2 = prod.price(svc, dict(base, __engine="g2pp", a=0.1, sigma=0.01, b=0.3,
                              eta=0.012, rho=-0.7, n_sims=20_000))
    assert black["errors"] == [] and g2["errors"] == []
    assert black["value"] > 0 and g2["value"] > 0
