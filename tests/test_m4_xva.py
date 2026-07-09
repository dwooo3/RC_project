"""
M4 — XVA suite. Netting sets, two-way CSA collateral, and the full valuation
adjustment family (CVA/DVA/FVA/MVA/KVA). Identity-first: single-trade exposure
matches risk/exposure.py, offsetting trades net to ~0, zero threshold + MPoR
collateralises to ~0, every adjustment is 0 at zero spread and linear in it.
"""
import numpy as np
import pytest

from curves.yield_curve import YieldCurve
from curves.hazard import HazardCurve
from risk.xva import (simulate_irs_portfolio, collateralize, exposure_profiles,
                      initial_margin_profile, xva_suite,
                      funding_value_adjustment, capital_value_adjustment)
from risk.exposure import irs_exposure_profile


@pytest.fixture(scope="module")
def curve():
    return YieldCurve.flat(0.06)


@pytest.fixture(scope="module")
def hazards():
    return HazardCurve.flat(0.03, recovery=0.4), HazardCurve.flat(0.01, recovery=0.4)


@pytest.fixture(scope="module")
def sim(curve):
    tr = dict(notional=1e7, fixed_rate=0.06, T=5.0, freq=2, pay_fixed=True)
    return simulate_irs_portfolio([tr], curve, n_sims=8000, n_grid=24, seed=1)


# ── exposure cube ────────────────────────────────────────

def test_single_trade_matches_exposure_profile(curve):
    """The cube's EPE reproduces the standalone risk/exposure.py profile."""
    tr = dict(notional=1e7, fixed_rate=0.06, T=5.0, freq=2, pay_fixed=True)
    sim = simulate_irs_portfolio([tr], curve, n_sims=6000, n_grid=20, seed=1)
    new = exposure_profiles(sim["times"], sim["mtm"])["epe"]
    old = irs_exposure_profile(1e7, 0.06, 5.0, 2, curve, n_sims=6000, n_grid=20, seed=1)
    assert new.max() == pytest.approx(old["epe"].max(), rel=1e-9)


def test_netting_benefit(curve):
    """A payer + an offsetting receiver net to ~0 exposure."""
    pay = dict(notional=1e7, fixed_rate=0.06, T=5.0, freq=2, pay_fixed=True)
    rec = dict(notional=1e7, fixed_rate=0.06, T=5.0, freq=2, pay_fixed=False)
    s = simulate_irs_portfolio([pay, rec], curve, n_sims=6000, n_grid=20, seed=1)
    netted = exposure_profiles(s["times"], s["mtm"])["epe"].max()
    standalone = sum(exposure_profiles(s["times"], c)["epe"].max() for c in s["per_trade"])
    assert netted < 1e-6 * standalone               # essentially perfect netting


# ── collateral ───────────────────────────────────────────

def test_zero_threshold_zero_mpor_collateralises_both_sides(sim):
    c = collateralize(sim["times"], sim["mtm"], threshold=0.0, mta=0.0, mpor=0.0)
    p = exposure_profiles(sim["times"], c)
    assert p["epe"].max() < 1e-6 and abs(p["ene"].min()) < 1e-6


def test_collateral_monotone_in_mpor(sim):
    peaks = [exposure_profiles(sim["times"],
             collateralize(sim["times"], sim["mtm"], 0.0, 0.0, m))["epe"].max()
             for m in (0.0, 1 / 52, 4 / 52, 13 / 52)]
    assert all(b > a for a, b in zip(peaks, peaks[1:]))


def test_large_threshold_is_uncollateralised(sim):
    big = collateralize(sim["times"], sim["mtm"], threshold=1e15, mta=0.0, mpor=2 / 52)
    assert (exposure_profiles(sim["times"], big)["epe"].max()
            == pytest.approx(exposure_profiles(sim["times"], sim["mtm"])["epe"].max()))


def test_initial_margin_positive(sim):
    im = initial_margin_profile(sim["times"], sim["mtm"], mpor=2 / 52)
    assert im.max() > 0 and (im >= 0).all()


# ── XVA suite identities ─────────────────────────────────

def test_zero_spread_zero_adjustments(sim, curve, hazards):
    cp, own = hazards
    r = xva_suite(sim, curve, cp, own, funding_spread=0.0, cost_of_capital=0.0)
    assert r["fva"] == pytest.approx(0.0) and r["mva"] == pytest.approx(0.0)
    assert r["kva"] == pytest.approx(0.0)
    assert r["cva"] > 0                              # credit still charged


def test_fva_mva_linear_in_funding_spread(sim, curve, hazards):
    cp, own = hazards
    a = xva_suite(sim, curve, cp, own, funding_spread=0.01)
    b = xva_suite(sim, curve, cp, own, funding_spread=0.02)
    assert b["fva"] == pytest.approx(2 * a["fva"], rel=1e-9)
    assert b["mva"] == pytest.approx(2 * a["mva"], rel=1e-9)


def test_kva_linear_in_cost_of_capital(sim, curve, hazards):
    cp, _ = hazards
    k1 = xva_suite(sim, curve, cp, cost_of_capital=0.10)["kva"]
    k2 = xva_suite(sim, curve, cp, cost_of_capital=0.20)["kva"]
    assert k2 == pytest.approx(2 * k1, rel=1e-9) and k1 > 0


def test_collateral_reduces_cva_and_fva(sim, curve, hazards):
    cp, own = hazards
    unc = xva_suite(sim, curve, cp, own, funding_spread=0.01)
    col = xva_suite(sim, curve, cp, own, funding_spread=0.01,
                    csa=dict(threshold=0.0, mta=0.0, mpor=2 / 52))
    assert col["cva"] < unc["cva"]
    assert abs(col["fva"]) < abs(unc["fva"])
    assert col["peak_epe"] < unc["peak_epe"]


def test_cva_increasing_in_hazard(sim, curve):
    lo = xva_suite(sim, curve, HazardCurve.flat(0.01))["cva"]
    hi = xva_suite(sim, curve, HazardCurve.flat(0.05))["cva"]
    assert hi > lo


# ── M0 wiring + service ──────────────────────────────────

def test_xva_wired():
    from models import taxonomy as tax
    from models import registry as R
    assert tax.classify("xva_suite")["asset_class"] == "risk"
    assert R.MODEL_REGISTRY["xva_suite"]["status"].value in ("Approximation", "Validated")


def test_xva_service_route():
    from services.risk_service import RiskService
    rs = RiskService()
    trades = [dict(notional=1_000_000, fixed_rate=0.13, T=5.0, freq=4, pay_fixed=True)]
    res = rs.xva_netting_set(trades, funding_spread=0.01, cost_of_capital=0.10,
                             n_sims=1500, n_grid=16)
    assert res["errors"] == [] and res["model_id"] == "xva_suite"
    assert res["raw"]["cva"] > 0 and res["raw"]["kva"] > 0


# ── M4c: AMC (Longstaff-Schwartz) ────────────────────────

def test_amc_single_exercise_is_jamshidian(curve):
    from risk.xva import amc_bermudan_swaption
    from models.short_rate import HullWhite
    hw = HullWhite(0.1, 0.012, curve)
    for opt in ("payer", "receiver"):
        amc = amc_bermudan_swaption(1_000_000, 0.06, [2.0], 5.0, 2, curve,
                                    0.1, 0.012, opt, n_sims=50_000, seed=7)
        jam = hw.swaption(1_000_000, 0.06, 2.0, 3.0, 2)[opt]
        assert amc["price"] == pytest.approx(jam, abs=4 * amc["stderr"])


def test_amc_matches_hw_tree(curve):
    from risk.xva import amc_bermudan_swaption
    from models.short_rate import bermudan_swaption_hw
    ex = [1.0, 2.0, 3.0, 4.0]
    for opt in ("payer", "receiver"):
        amc = amc_bermudan_swaption(1_000_000, 0.06, ex, 5.0, 2, curve,
                                    0.1, 0.012, opt, n_sims=60_000, seed=7)
        tree = bermudan_swaption_hw(1_000_000, 0.06, ex, 5.0, 2, curve, 0.1, 0.012,
                                    opt, steps=300)
        assert amc["price"] == pytest.approx(tree["price"], rel=0.01)


def test_amc_bermudan_geq_european(curve):
    from risk.xva import amc_bermudan_swaption
    from models.short_rate import HullWhite
    berm = amc_bermudan_swaption(1_000_000, 0.06, [1.0, 2.0, 3.0, 4.0], 5.0, 2,
                                 curve, 0.1, 0.012, "payer", n_sims=50_000, seed=7)
    eur = HullWhite(0.1, 0.012, curve).swaption(1_000_000, 0.06, 4.0, 1.0, 2)["payer"]
    assert berm["price"] >= eur


def test_amc_wired_and_service():
    from models import taxonomy as tax
    from models import registry as R
    from services.pricing_service import PricingService
    assert tax.classify("amc")["asset_class"] == "rates"
    assert R.MODEL_REGISTRY["amc"]["status"].value in ("Approximation", "Validated")
    res = PricingService().price_amc_bermudan_swaption(
        1_000_000, 0.05, [1.0, 2.0, 3.0], 4.0, n_sims=10_000)
    assert res["errors"] == [] and res["value"] > 0 and res["model_id"] == "amc"
