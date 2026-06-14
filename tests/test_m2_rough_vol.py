"""
M2 — rough volatility (rough Bergomi) + stoch-vol promotion guards.
Identity-first: η→0 ⇒ BSM, martingale parity, rough skew steeper than smooth;
plus registry guards that the promoted stoch-vol models carry tests.
"""
import numpy as np
import pytest

from models.black_scholes import bsm
from models.implied_vol import implied_vol_bsm
from models.rough_vol import rough_bergomi_price, _volterra_weights


S, K, T, r, q, XI0 = 100.0, 100.0, 1.0, 0.05, 0.0, 0.04


# ── Volterra variance scale ──────────────────────────────

def test_volterra_variance_scale():
    """Var(Y_T) tracks the Riemann-Liouville target t^{2H} (within discretisation)."""
    for H in (0.2, 0.3, 0.4):
        a = _volterra_weights(H, 1.0 / 300, 300)
        var_YT = 2 * H * (a[-1] ** 2).sum() * (1.0 / 300)
        assert var_YT == pytest.approx(1.0 ** (2 * H), rel=0.1), H


# ── η→0 ⇒ BSM ────────────────────────────────────────────

def test_eta_zero_is_bsm():
    bs = bsm(S, K, T, r, np.sqrt(XI0), q).price
    res = rough_bergomi_price(S, K, T, r, q, H=0.1, eta=1e-4, rho=-0.7,
                              xi0=XI0, opt="call", n_paths=60_000, steps=100)
    assert res["price"] == pytest.approx(bs, abs=4 * res["stderr"] + 0.02)


# ── Martingale put-call parity ───────────────────────────

def test_put_call_parity_martingale():
    c = rough_bergomi_price(S, K, T, r, q, 0.1, 1.5, -0.7, XI0, "call", 80_000, 100)
    p = rough_bergomi_price(S, K, T, r, q, 0.1, 1.5, -0.7, XI0, "put", 80_000, 100)
    parity = c["price"] - p["price"] - (S * np.exp(-q * T) - K * np.exp(-r * T))
    assert parity == pytest.approx(0.0, abs=1e-6)          # correction makes it exact


# ── Rough skew steeper than smooth ───────────────────────

def test_rough_skew_steeper_than_smooth():
    def iv(strike, H):
        pr = rough_bergomi_price(S, strike, 0.25, r, q, H, 1.8, -0.7, XI0,
                                 "put", 100_000, 80)["price"]
        return implied_vol_bsm(pr, S, strike, 0.25, r, q, "put")
    rough_skew = iv(90, 0.1) - iv(100, 0.1)
    smooth_skew = iv(90, 0.45) - iv(100, 0.45)
    assert rough_skew > smooth_skew > 0                    # roughness steepens skew


# ── Greeks / monotonicity ────────────────────────────────

def test_rough_bergomi_increasing_in_xi0():
    lo = rough_bergomi_price(S, K, T, r, q, 0.1, 1.5, -0.7, 0.02, "call", 60_000, 100)["price"]
    hi = rough_bergomi_price(S, K, T, r, q, 0.1, 1.5, -0.7, 0.08, "call", 60_000, 100)["price"]
    assert hi > lo                                         # more variance -> dearer call


# ── Promotion guards (M2: Prototype -> Approximation) ────

def test_stoch_vol_promoted():
    from models import registry as R
    for m in ("heston_cf", "sabr", "bates", "rough_bergomi"):
        e = R.MODEL_REGISTRY[m]
        assert e["status"].value == "Approximation", m
        assert len(e["tests"]) > 0, m                      # tests synced (F2)
        assert R.can_promote_to_validated(m)               # eligible for Validated


def test_rough_bergomi_wired():
    from models import taxonomy as tax
    from models import parameters as P
    assert "rough_bergomi" in tax.engines_for("european_option")
    assert tax.classify("rough_bergomi")["model_family"] == "stoch_vol"
    keys = {s.key for s in P.engine_params("rough_bergomi")}
    assert {"H", "eta", "rho", "xi0"} <= keys


# ── Service routing + lab gating + UI dispatch ───────────

def test_rough_bergomi_service_lab_gated():
    from services.pricing_service import PricingService
    blocked = PricingService().price_rough_bergomi_option(S, K, T, r)
    assert blocked["errors"]
    ok = PricingService(allow_analytics_lab=True).price_rough_bergomi_option(
        S, K, T, r, q, 0.1, 1.5, -0.7, XI0, "call", 20_000, 60)
    assert ok["errors"] == [] and ok["value"] > 0


def test_vanilla_dispatch_to_rough_bergomi():
    from app.panels.pricing_catalogue import products_by_category
    from models.parameters import engine_params
    from services.pricing_service import PricingService
    svc = PricingService(allow_analytics_lab=True)
    prod = next(p for p in products_by_category("Option") if p.id == "vanilla")
    assert "rough_bergomi" in prod.engines()
    v = {"S": 100, "K": 100, "T": 1.0, "r": 0.05, "sigma": 0.20, "q": 0.0,
         "opt": "call", "__engine": "rough_bergomi"}
    for s in engine_params("rough_bergomi"):
        v.setdefault(s.key, s.default)
    v["n_paths"] = 20_000
    res = prod.price(svc, v)
    assert res["errors"] == [] and res["value"] > 0
