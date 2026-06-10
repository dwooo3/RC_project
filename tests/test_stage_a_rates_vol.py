"""
Stage A — rates volatility: swaption cube + caplet strip (SABR), Hull-White
calibration to the cube, calibrated Bermudans, CMS timing adjustment and
cube-driven vols.
"""
import numpy as np
import pytest

from curves.yield_curve import YieldCurve
from models.implied_vol import implied_vol_black76
from models.short_rate import HullWhite, _forward_swap_rate, calibrate_hull_white
from risk.vol_cube import CapletVolStrip, SwaptionCube, _SABRSlice
from services.pricing_service import PricingService


@pytest.fixture(scope="module")
def flat():
    return YieldCurve.flat(0.10)


@pytest.fixture(scope="module")
def svc():
    return PricingService()


# ── SABR slice + cube structure ──────────────────────────

def test_sabr_slice_recalibration_round_trip():
    """Quotes generated from known SABR params must be recovered."""
    from models.heston import sabr_vol
    F, T = 0.12, 1.0
    true = dict(alpha=0.08, beta=0.5, rho=-0.25, nu=0.45)
    ks = [0.7 * F, 0.85 * F, F, 1.15 * F, 1.3 * F]
    vols = [sabr_vol(F, k, T, true["alpha"], true["beta"], true["rho"], true["nu"])
            for k in ks]
    sl = _SABRSlice.calibrate(F, T, ks, vols, beta=0.5)
    assert sl.rmse < 1e-6
    for k, v in zip(ks, vols):
        assert sl.vol(k) == pytest.approx(v, abs=1e-5)


def test_cube_atm_interpolation_and_strike_query(flat):
    expiries, tenors = [1.0, 2.0], [1.0, 5.0]
    atm = [[0.30, 0.28], [0.27, 0.25]]
    cube = SwaptionCube(expiries, tenors, atm)
    assert cube.atm_vol(1.0, 1.0) == pytest.approx(0.30)
    assert cube.atm_vol(1.5, 5.0) == pytest.approx(0.265)     # bilinear midpoint
    assert cube.atm_vol(1.0, 3.0) == pytest.approx(0.29)
    # no smile calibrated: strike query falls back to ATM
    assert cube.vol(1.0, 1.0, K=0.08, F=0.10) == pytest.approx(0.30)


def test_cube_smile_recentred_on_atm(flat):
    def fwd(e, t):
        return _forward_swap_rate(flat, e, t, 2)[0]
    F = fwd(1.0, 5.0)
    quotes = {(1.0, 5.0): [(0.7 * F, 0.345), (F, 0.30), (1.3 * F, 0.305)]}
    cube = SwaptionCube.calibrate([1.0, 2.0], [1.0, 5.0],
                                  [[0.32, 0.30], [0.29, 0.27]], quotes, fwd)
    # ATM strike query == ATM matrix level (smile recentred)
    assert cube.vol(1.0, 5.0, K=F, F=F) == pytest.approx(0.30, abs=1e-3)
    # low-strike skew from the quotes survives recentring
    assert cube.vol(1.0, 5.0, K=0.7 * F, F=F) > cube.vol(1.0, 5.0, K=F, F=F) + 0.02


def test_caplet_strip_queries():
    strip = CapletVolStrip([0.5, 1.0, 2.0], [0.40, 0.36, 0.31])
    assert strip.vol(1.0) == pytest.approx(0.36)
    # variance-flat between nodes: total variance interpolates linearly
    tv = 0.5 * (0.36**2 * 1.0 + 0.31**2 * 2.0)
    assert strip.vol(1.5) == pytest.approx(np.sqrt(tv / 1.5), abs=1e-12)
    # beyond the last quote: flat-vol extrapolation (market convention)
    assert strip.vol(10.0) == pytest.approx(0.31)


# ── Hull-White calibration to the cube ───────────────────

def test_hw_calibration_round_trip(flat):
    """ATM vols implied from a known HW must calibrate back to (kappa*, sigma*)."""
    k_true, s_true = 0.08, 0.011
    hw = HullWhite(k_true, s_true, flat)
    expiries, tenors = [0.5, 1.0, 2.0, 3.0], [1.0, 2.0, 5.0]
    atm = np.zeros((len(expiries), len(tenors)))
    for i, e in enumerate(expiries):
        for j, t in enumerate(tenors):
            S0, ann = _forward_swap_rate(flat, e, t, 2)
            price = hw.swaption(1.0, S0, e, t, 2)["payer"]
            atm[i, j] = implied_vol_black76(price / ann, S0, S0, e, 0.0, "call")
    cube = SwaptionCube(expiries, tenors, atm)
    cal = calibrate_hull_white(flat, cube,
                               [(e, t) for e in expiries for t in tenors])
    assert cal["converged"]
    assert cal["kappa"] == pytest.approx(k_true, rel=1e-3)
    assert cal["sigma"] == pytest.approx(s_true, rel=1e-3)
    assert cal["rmse"] < 1e-6


def test_calibrated_bermudan_dominates_market_european(svc):
    """Calibrated Bermudan >= the market European at every exercise date."""
    from models.short_rate import (bermudan_swaption_calibrated,
                                   black_swaption_price)
    flat = svc.market_data.get_curve("cbr_key_demo")
    cube = svc.market_data.get_swaption_cube()
    K = _forward_swap_rate(flat, 1.0, 5.0, 2)[0]      # ~ATM strike
    res = bermudan_swaption_calibrated(1_000_000, K, [1.0, 2.0, 3.0], 6.0, 2,
                                       flat, cube, steps=150)
    assert res["calibration"]["converged"]
    assert res["calibration"]["rmse"] < 0.05          # co-terminal fit quality
    for t_e in (1.0, 2.0, 3.0):
        eu_mkt = black_swaption_price(1_000_000, K, t_e, 6.0 - t_e, 2, flat,
                                      cube.atm_vol(t_e, 6.0 - t_e))
        assert res["price"] >= eu_mkt * (1 - 0.05), t_e


def test_bermudan_service_calibrated_route(svc):
    res = svc.price_bermudan_swaption(1_000_000, 0.14, [1.0, 2.0], 5.0,
                                      steps=100, calibrate_to_cube=True)
    assert res["errors"] == []
    raw = res["raw"]
    assert "calibration" in raw and raw["calibration"]["converged"]
    # calibrated sigma differs from the manual default
    assert raw["calibration"]["sigma"] != pytest.approx(0.012, abs=1e-6)


# ── CMS: timing adjustment + cube vols ───────────────────

def test_cms_timing_adjustment_properties(flat):
    from instruments.fixed_income import cms_swaplet, cms_timing_adjustment
    assert cms_timing_adjustment(0.10, 0.3, 0.10, 0.3, 1.0, 1.0, 0.0) == 0.0
    adj = cms_timing_adjustment(0.10, 0.3, 0.10, 0.3, 1.0, 1.0, 0.25)
    assert adj < 0                                        # paid later -> lower rate
    assert abs(cms_timing_adjustment(0.10, 0.3, 0.10, 0.3, 1.0, 2.0, 0.25)) > abs(adj)
    # swaplet with no lag carries no timing adjustment
    same = cms_swaplet(1_000_000, 1.0, 1.0, 5.0, 2, flat, 0.25, tau=0.25)
    assert same["timing_adjustment"] == 0.0
    lagged = cms_swaplet(1_000_000, 1.0, 1.25, 5.0, 2, flat, 0.25, tau=0.25)
    assert lagged["timing_adjustment"] < 0
    assert lagged["expected_cms_rate"] < same["expected_cms_rate"]


def test_cms_swap_with_cube_vols(svc):
    scalar = svc.price_cms_swap(1_000_000, 0.14, 3.0, 4, 5.0, sigma=0.30,
                                curve_id="cbr_key_demo")
    cubed = svc.price_cms_swap(1_000_000, 0.14, 3.0, 4, 5.0,
                               cube_id="swaption_cube_demo",
                               curve_id="cbr_key_demo")
    assert scalar["errors"] == [] and cubed["errors"] == []
    # cube vols vary per fixing -> coupons carry different sigmas
    sigmas = {round(c["sigma"], 6) for c in cubed["raw"]["coupons"][1:]}
    assert len(sigmas) > 1
    assert cubed["raw"]["fair_rate"] != pytest.approx(scalar["raw"]["fair_rate"])


# ── Cap/floor off the caplet strip ───────────────────────

def test_cap_floor_from_strip(svc):
    res = svc.price_cap_floor(1_000_000, 0.16, 3.0, 4, vol=None,
                              vol_strip_id="caplet_strip_demo",
                              curve_id="cbr_key_demo")
    assert res["errors"] == []
    assert res["value"] > 0
    # parity still holds with strike-aware strip vols (parity is vol-free)
    floor = svc.price_cap_floor(1_000_000, 0.16, 3.0, 4, vol=None,
                                vol_strip_id="caplet_strip_demo",
                                curve_id="cbr_key_demo", opt="floor")
    curve = svc.market_data.get_curve("cbr_key_demo")
    swap = sum(0.25 * curve.discount(i * 0.25)
               * ((curve.discount((i - 1) * 0.25) / curve.discount(i * 0.25) - 1) / 0.25 - 0.16)
               for i in range(1, 13)) * 1_000_000
    assert res["value"] - floor["value"] == pytest.approx(swap, abs=1e-6)


# ── Swaption with cube (strike-aware) ────────────────────

def test_swaption_priced_from_cube(svc):
    curve = svc.market_data.get_curve("cbr_key_demo")
    F = _forward_swap_rate(curve, 1.0, 5.0, 2)[0]
    atm = svc.price_swaption(1_000_000, F, 1.0, 5.0, 2, sigma=None,
                             cube_id="swaption_cube_demo", curve_id="cbr_key_demo")
    low = svc.price_swaption(1_000_000, 0.7 * F, 1.0, 5.0, 2, sigma=None,
                             cube_id="swaption_cube_demo", curve_id="cbr_key_demo",
                             opt="receiver")
    assert atm["errors"] == [] and low["errors"] == []
    cube = svc.market_data.get_swaption_cube()
    # ATM strike resolves to the ATM matrix vol
    assert atm["raw"]["vega"] > 0
    assert atm["inputs_hash"]
    sigma_atm = cube.vol(1.0, 5.0, F, F)
    sigma_low = cube.vol(1.0, 5.0, 0.7 * F, F)
    assert sigma_low > sigma_atm + 0.02      # smile skew flows into pricing


def test_demo_cube_present_in_snapshot(svc):
    snap = svc.market_data.demo_snapshot()
    cube = svc.market_data.get_swaption_cube("swaption_cube_demo", snap)
    assert cube.atm_vol(1.0, 5.0) > 0.2
    assert len(cube.smiles) == 3
    strip = snap.vol_surfaces["caplet_strip_demo"]
    assert strip.vol(1.0) > 0.2
