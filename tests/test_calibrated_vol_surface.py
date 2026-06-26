"""SABR-calibrated multi-tenor vol surface for pricing/risk.

Covers risk.vol_surface.calibrated_surface_from_points + the pricer wiring
(get_vol_surface upgrades raw FORTS grids; _vol_from_surface interpolates a real
smile/term structure and expands rr/bf quote sets) — so options price off an
adequate surface instead of a flat median vol.
"""
import math
from datetime import date

import pytest

from risk.vol_surface import calibrated_surface_from_points, CalibratedSurface
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService


VAL = date(2026, 1, 1)


def _smile_points(expiry: str, F: float, atm: float) -> list[dict]:
    """Synthetic convex smile around forward F for one expiry."""
    pts = []
    for m in (0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20):
        iv = atm + 0.5 * math.log(m) ** 2          # symmetric convex smile
        pts.append({"expiry": expiry, "strike": F * m, "iv": iv})
    return pts


def _grid_surface(points: list[dict], underlying="TEST") -> dict:
    import statistics
    return {"type": "grid", "source": "MOEX_FORTS", "underlying": underlying,
            "points": points, "median_vol": statistics.median(p["iv"] for p in points),
            "n_points": len(points)}


@pytest.fixture(scope="module")
def points():
    return _smile_points("2026-02-01", 10000.0, 0.20) + \
           _smile_points("2026-05-01", 10000.0, 0.25)


# ── surface construction ─────────────────────────────────

def test_builds_calibrated_surface(points):
    surf = calibrated_surface_from_points(points, VAL, label="TEST_FORTS")
    assert isinstance(surf, CalibratedSurface)
    assert surf.diagnostics["n_expiries"] == 2
    assert surf.diagnostics["fit_model"] == "SABR(beta=1)"
    # the fit reproduces the synthetic smile tightly
    assert all(s["rmse"] is not None and s["rmse"] < 0.02 for s in surf.diagnostics["slices"])


def test_surface_has_a_real_smile(points):
    surf = calibrated_surface_from_points(points, VAL)
    T = surf.slices[0]["T"]
    atm = surf.get_vol(10000.0, T)
    wing_put = surf.get_vol(8500.0, T)
    wing_call = surf.get_vol(11500.0, T)
    assert wing_put > atm and wing_call > atm          # convex: wings above ATM
    assert atm == pytest.approx(0.20, abs=0.02)


def test_surface_has_term_structure(points):
    surf = calibrated_surface_from_points(points, VAL)
    t0, t1 = surf.slices[0]["T"], surf.slices[1]["T"]
    v0 = surf.get_vol(10000.0, t0)
    v1 = surf.get_vol(10000.0, t1)
    vmid = surf.get_vol(10000.0, 0.5 * (t0 + t1))
    assert v1 > v0                                      # rising ATM term structure
    assert min(v0, v1) - 1e-9 <= vmid <= max(v0, v1) + 1e-9


def test_mixed_scale_expiry_rejected(points):
    glitch = _smile_points("2026-03-01", 1_000_000.0, 0.30)   # 100x scale glitch
    surf = calibrated_surface_from_points(points + glitch, VAL)
    assert surf.diagnostics["n_expiries"] == 2                # glitch dropped
    assert surf.diagnostics["rejected_points"] >= len(glitch)


def test_thin_points_return_none():
    thin = [{"expiry": "2026-02-01", "strike": 100.0, "iv": 0.2}]
    assert calibrated_surface_from_points(thin, VAL) is None


# ── pricer wiring ────────────────────────────────────────

@pytest.fixture(scope="module")
def svc():
    return PricingService()


def _snapshot_with(svc_md: MarketDataService, surfaces: dict):
    return svc_md.manual_snapshot("manual-test", valuation_date=VAL,
                                  vol_surfaces=surfaces)


def test_get_vol_surface_upgrades_grid(points):
    md = MarketDataService()
    snap = _snapshot_with(md, {"TEST_FORTS": _grid_surface(points)})
    surf = md.get_vol_surface("TEST_FORTS", snap)
    assert isinstance(surf, CalibratedSurface)            # not the raw dict
    # cached on second call
    assert md.get_vol_surface("TEST_FORTS", snap) is surf


def test_vanilla_prices_off_smile_not_median(svc, points):
    md = svc.market_data
    snap = _snapshot_with(md, {"TEST_FORTS": _grid_surface(points)})
    T = 0.1
    atm = svc.price_vanilla_option(10000, 10000, T, 0.0, sigma=None, opt="call",
                                   model="black76", snapshot=snap, vol_surface_id="TEST_FORTS")
    wing = svc.price_vanilla_option(10000, 8500, T, 0.0, sigma=None, opt="call",
                                    model="black76", snapshot=snap, vol_surface_id="TEST_FORTS")
    assert atm["errors"] == [] and wing["errors"] == []
    # strike-dependent vol → the two legs use DIFFERENT sigmas (a real smile)
    assert wing["raw"]["sigma_used"] > atm["raw"]["sigma_used"]
    # and no "using median vol" degradation warning
    assert not any("median vol" in w for w in atm["warnings"])


def test_rr_bf_surface_prices_with_skew(svc):
    demo = svc.market_data.demo_snapshot()
    low = svc.price_vanilla_option(90, 80, 0.5, 0.05, sigma=None, opt="call",
                                   snapshot=demo, vol_surface_id="fx_usdrub_demo")
    high = svc.price_vanilla_option(90, 100, 0.5, 0.05, sigma=None, opt="call",
                                    snapshot=demo, vol_surface_id="fx_usdrub_demo")
    assert low["errors"] == [] and high["errors"] == []   # was: Unsupported surface
    # negative RR (put skew) → lower strikes carry higher vol
    assert low["raw"]["sigma_used"] > high["raw"]["sigma_used"]


def test_flat_surface_regression(svc):
    demo = svc.market_data.demo_snapshot()
    res = svc.price_vanilla_option(100, 100, 1.0, 0.05, sigma=None, opt="call",
                                   snapshot=demo, vol_surface_id="equity_flat_demo")
    assert res["errors"] == []
    assert res["raw"]["sigma_used"] == pytest.approx(0.20)
