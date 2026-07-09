"""
M8 — niche models. AFV (Andersen-Buffum) convertible with equity-linked default,
MBS pass-through with PSA prepayment, and the FRTB Standardised Approach (SBM
delta). Each validated identity-first against independent references and limits.
"""
import numpy as np
import pytest

from models.convertible_afv import afv_convertible, defaultable_bond
from models.mbs import mbs_cashflows, mbs_price, mbs_oas
from models.frtb import frtb_delta_charge, bucket_charge
from instruments.convertible import convertible_bond
from curves.yield_curve import YieldCurve


# ══════════════════════ AFV convertible ══════════════════════

def test_afv_conv_zero_is_defaultable_bond():
    p = afv_convertible(100, 0.3, 0.0, 100, 0.05, 2, 5.0, 0.0, 0.04,
                        lam0=0.03, alpha=0.0, recovery=0.4, N=600)["price"]
    ref = defaultable_bond(100, 0.05, 2, 5.0, 0.04, 0.03, 0.4)
    assert p == pytest.approx(ref, abs=0.05)


def test_afv_lambda_zero_is_convertible():
    curve = YieldCurve.flat(0.04)
    afv = afv_convertible(100, 0.3, 0.0, 100, 0.05, 2, 5.0, 1.0, 0.04,
                          lam0=1e-9, alpha=0.0, N=600)["price"]
    tf = convertible_bond(100, 0.3, 0.0, 100, 0.05, 2, 5.0, 1.0, curve,
                          credit_spread=1e-9, N=600)["price"]
    assert afv == pytest.approx(tf, abs=0.05)


def test_afv_deep_itm_geq_parity():
    res = afv_convertible(1000, 0.3, 0.0, 100, 0.05, 2, 5.0, 1.0, 0.04,
                          lam0=0.02, alpha=1.2, N=400)
    assert res["price"] >= res["parity"]
    assert res["price"] == pytest.approx(res["parity"], rel=0.05)


def test_afv_price_falls_with_hazard():
    prices = [afv_convertible(100, 0.3, 0.0, 100, 0.05, 2, 5.0, 1.0, 0.04,
                              lam0=l, alpha=1.2, N=400)["price"] for l in (0.0, 0.03, 0.08)]
    assert prices[0] > prices[1] > prices[2]


# ══════════════════════ MBS prepayment ══════════════════════

def test_mbs_principal_returned():
    cf = mbs_cashflows(100.0, 0.05, 0.05, 360, psa=150)
    assert cf["principal"].sum() == pytest.approx(100.0, abs=1e-3)


def test_mbs_zero_psa_par():
    p = mbs_price(100.0, 0.05, 0.05, 360, psa=0.0, disc_rate=0.05)
    assert p["price_pct"] == pytest.approx(100.0, abs=1e-6)


def test_mbs_faster_psa_shortens_wal():
    wals = [mbs_price(100.0, 0.05, 0.05, 360, psa=psa, disc_rate=0.05)["wal"]
            for psa in (0, 100, 300, 600)]
    assert all(a > b for a, b in zip(wals, wals[1:]))


def test_mbs_price_falls_with_rate():
    px = [mbs_price(100.0, 0.05, 0.05, 360, psa=100, disc_rate=dr)["price_pct"]
          for dr in (0.03, 0.05, 0.08)]
    assert px[0] > px[1] > px[2]


def test_mbs_oas_roundtrip():
    mp = mbs_price(100.0, 0.05, 0.05, 360, psa=100, disc_rate=0.06)["price"]
    oas = mbs_oas(mp, 100.0, 0.05, 0.05, 360, psa=100, disc_rate=0.05)
    assert mbs_price(100.0, 0.05, 0.05, 360, 100, disc_rate=0.05, oas=oas)["price"] == pytest.approx(mp, abs=1e-6)


# ══════════════════════ FRTB-SA ══════════════════════

def test_frtb_single_factor():
    f = [{"bucket": 1, "sensitivity": 1000.0, "risk_weight": 0.05}]
    assert frtb_delta_charge(f)["charge"] == pytest.approx(50.0)


def test_frtb_homogeneous_degree_one():
    f = [{"bucket": 1, "sensitivity": 1000, "risk_weight": 0.05},
         {"bucket": 2, "sensitivity": -500, "risk_weight": 0.08}]
    c1 = frtb_delta_charge(f)["charge"]
    f2 = [{**x, "sensitivity": 2 * x["sensitivity"]} for x in f]
    assert frtb_delta_charge(f2)["charge"] == pytest.approx(2 * c1)


def test_frtb_correlation_diversifies():
    assert bucket_charge([50, 40], 0.0) < 90                     # imperfect corr
    assert bucket_charge([50, 40], 1.0) == pytest.approx(90.0)   # perfect corr = sum
    assert bucket_charge([50, -40], 0.5) < bucket_charge([50, 40], 0.5)   # hedge


def test_frtb_scenario_max():
    f = [{"bucket": 1, "sensitivity": 1000, "risk_weight": 0.05},
         {"bucket": 2, "sensitivity": -500, "risk_weight": 0.08}]
    r = frtb_delta_charge(f)
    assert r["charge"] >= r["scenarios"]["medium"]
    assert r["charge"] == max(r["scenarios"].values())


# ══════════════════════ M0 wiring + service ══════════════════════

def test_m8_wired():
    from models import taxonomy as tax
    from models import registry as R
    assert "afv_convertible" in tax.engines_for("convertible_bond")
    assert "mbs" in tax.engines_for("mbs")
    assert tax.classify("afv_convertible")["asset_class"] == "hybrid"
    assert tax.classify("mbs")["asset_class"] == "rates"
    assert tax.classify("frtb_sba")["kind"] == "risk"
    for mid in ("afv_convertible", "mbs", "frtb_sba"):
        assert R.MODEL_REGISTRY[mid]["status"].value in ("Approximation", "Validated")


def test_m8_service_routes():
    from services.pricing_service import PricingService
    from services.risk_service import RiskService
    ps = PricingService()
    cv = ps.price_afv_convertible(100, 0.3, 0.0, 100, 0.05, 2, 5.0, 1.0, 0.04, N=300)
    assert cv["errors"] == [] and cv["value"] > 0 and cv["model_id"] == "afv_convertible"
    mb = ps.price_mbs(100.0, 0.05, 0.05, 360, psa=150, disc_rate=0.06)
    assert mb["errors"] == [] and mb["value"] > 0 and mb["raw"]["wal"] > 0
    rs = RiskService()
    fr = rs.frtb_capital([{"bucket": 1, "sensitivity": 1000, "risk_weight": 0.05},
                          {"bucket": 2, "sensitivity": -500, "risk_weight": 0.08}])
    assert fr["errors"] == [] and fr["value"] > 0 and fr["model_id"] == "frtb_sba"
