"""
M7 — credit models. ISDA standard CDS, structural models (Merton / Black-Cox /
KMV) and the one-factor Gaussian copula for baskets and CDO tranches. Each
validated identity-first against independent references and known limits.
"""
import numpy as np
import pytest
from scipy.stats import norm

from instruments.credit import (cds_upfront, cds_spread_from_upfront,
                                isda_flat_hazard, isda_cds_legs)
from models.structural_credit import merton, kmv_calibrate, black_cox
from models.credit_portfolio import (kth_to_default_prob, portfolio_expected_loss,
                                     cdo_tranche, basket_mc)
from models.black_scholes import bsm


# ══════════════════════ ISDA CDS ══════════════════════

def test_par_coupon_zero_upfront():
    u = cds_upfront(1e7, 0.01, 0.01, 5.0, 4, 0.03, 0.4)
    assert abs(u["upfront"]) < 1.0                      # coupon == quote -> ~0


def test_upfront_spread_roundtrip():
    u = cds_upfront(1e7, 0.01, 0.015, 5.0, 4, 0.03, 0.4)
    s = cds_spread_from_upfront(1e7, 0.01, u["points_upfront"], 5.0, 4, 0.03, 0.4)
    assert s == pytest.approx(0.015, abs=1e-9)
    assert u["upfront"] > 0                             # quote > coupon -> buyer pays


def test_calibrated_par_matches_quote():
    h = isda_flat_hazard(0.015, 5, 4, 0.03, 0.4)
    par = isda_cds_legs(h, 0.0, 5, 4, 0.03, 0.4)["par_spread"]
    assert par == pytest.approx(0.015, abs=1e-8)
    assert h * 0.6 == pytest.approx(0.015, rel=0.05)    # credit triangle


# ══════════════════════ Structural ══════════════════════

def test_merton_equity_is_bs_call():
    m = merton(120, 100, 1.0, 0.05, 0.25)
    bs = bsm(120, 100, 1.0, 0.05, 0.25, 0.0, "call").price
    assert m["equity"] == pytest.approx(bs, abs=1e-8)
    assert m["pd"] == pytest.approx(norm.cdf(-m["distance_to_default"]), abs=1e-12)


def test_merton_spread_monotonic():
    sp = [merton(120, D, 1, 0.05, 0.25)["credit_spread"] for D in (60, 100, 140)]
    assert sp[0] < sp[1] < sp[2]                        # rises with leverage
    sv = [merton(120, 100, 1, 0.05, s)["credit_spread"] for s in (0.1, 0.25, 0.5)]
    assert sv[0] < sv[1] < sv[2]                        # rises with vol
    assert merton(120, 60, 1, 0.05, 0.25)["credit_spread"] < 0.001   # low leverage


def test_kmv_calibration_roundtrip():
    V0, D, T, r, sV = 120, 100, 1.0, 0.05, 0.25
    m = merton(V0, D, T, r, sV)
    sq = sV * np.sqrt(T)
    d1 = (np.log(V0 / D) + (r + 0.5 * sV**2) * T) / sq
    sigma_E = norm.cdf(d1) * sV * V0 / m["equity"]
    cal = kmv_calibrate(m["equity"], sigma_E, D, T, r)
    assert cal["asset_value"] == pytest.approx(V0, rel=1e-4)
    assert cal["asset_vol"] == pytest.approx(sV, rel=1e-4)


def test_black_cox_pd_geq_merton():
    bc = black_cox(120, 100, 1.0, 0.05, 0.25)
    m = merton(120, 100, 1.0, 0.05, 0.25)
    assert bc["pd"] >= m["pd"]
    assert black_cox(120, 100, 1.0, 0.05, 0.25, barrier=1e-3)["pd"] < 1e-6


# ══════════════════════ Gaussian copula ══════════════════════

@pytest.fixture(scope="module")
def pool():
    return [0.05] * 20


def test_portfolio_el_correlation_independent(pool):
    els = [portfolio_expected_loss(pool, rho, 0.4) for rho in (0.0, 0.3, 0.6)]
    for el in els:
        assert el == pytest.approx(0.05 * 0.6, abs=1e-6)


def test_tranches_sum_to_portfolio_el(pool):
    rho, R = 0.3, 0.4
    edges = [0, 0.03, 0.07, 0.10, 0.15, 1 - R]
    total = sum(cdo_tranche(pool, rho, K1, K2, R)["expected_tranche_loss"] * (K2 - K1)
                for K1, K2 in zip(edges, edges[1:]))
    assert total == pytest.approx(portfolio_expected_loss(pool, rho, R), abs=1e-6)


def test_recursion_matches_mc(pool):
    for k in (1, 2, 5):
        rec = kth_to_default_prob(pool, 0.3, k)
        mc = basket_mc(pool, 0.3, k, 0.4, 300_000, 1)["kth_prob"]
        assert rec == pytest.approx(mc, abs=4e-3)


def test_ftd_zero_correlation_formula(pool):
    p = 0.05
    assert kth_to_default_prob(pool, 1e-7, 1) == pytest.approx(1 - (1 - p)**20, abs=1e-4)


def test_correlation_skew(pool):
    R = 0.4
    eq = [cdo_tranche(pool, r, 0.0, 0.03, R)["expected_tranche_loss"] for r in (0.1, 0.4, 0.7)]
    sen = [cdo_tranche(pool, r, 0.15, 0.6, R)["expected_tranche_loss"] for r in (0.1, 0.4, 0.7)]
    ftd = [kth_to_default_prob(pool, r, 1) for r in (0.1, 0.4, 0.7)]
    assert eq[0] > eq[1] > eq[2]                        # equity loss falls with rho
    assert sen[0] < sen[1] < sen[2]                     # senior loss rises with rho
    assert ftd[0] > ftd[1] > ftd[2]                     # FTD falls with rho


# ══════════════════════ M0 wiring + service ══════════════════════

def test_m7_wired():
    from models import taxonomy as tax
    from models import registry as R
    for mid in ("cds_isda", "merton_structural", "black_cox", "kmv", "gaussian_copula"):
        assert tax.classify(mid)["asset_class"] == "credit"
        assert R.MODEL_REGISTRY[mid]["status"].value in ("Approximation", "Validated")
    assert tax.classify("merton_structural")["model_family"] == "structural"
    assert tax.classify("gaussian_copula")["model_family"] == "copula"
    assert "gaussian_copula" in tax.engines_for("cdo_tranche")


def test_m7_service_routes():
    from services.pricing_service import PricingService
    svc = PricingService()
    cds = svc.price_isda_cds(1e7, 0.01, 0.015, 5.0)
    assert cds["errors"] == [] and cds["value"] > 0 and cds["model_id"] == "cds_isda"
    st = svc.price_structural_credit("merton", 120, 100, 1.0, 0.05, 0.25)
    assert st["errors"] == [] and st["raw"]["pd"] > 0
    tr = svc.price_cdo_tranche([0.05] * 20, 0.3, 0.0, 0.03, 0.4)
    assert tr["errors"] == [] and tr["value"] > 0
    kt = svc.price_kth_to_default([0.05] * 20, 0.3, 1)
    assert kt["errors"] == [] and 0 < kt["value"] < 1
