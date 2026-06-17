"""
FORTS option-surface consumption layer: smile extraction, forward estimate,
smile cleaning, 25Δ RR/BF, and the calibrator wiring. Synthetic surfaces give
exact round-trips; the live-data tests skip gracefully without a market DB
(self-implied FORTS equity wings are liquidity-limited — see
MODEL_MARKET_DATA_REQUIREMENTS.md §5).
"""
import numpy as np
import pytest

from infra.moex_iss.options_surface import (smile_at_expiry, estimate_forward,
                                            clean_smile, rr_bf_25delta)
from models.heston import sabr_vol, sabr_calibrate


def _sabr_surface(F, T, alpha, beta, rho, nu, expiry="2026-12-16"):
    strikes = list(np.linspace(0.7 * F, 1.3 * F, 13))
    pts = [{"expiry": expiry, "strike": K, "iv": sabr_vol(F, K, T, alpha, beta, rho, nu)}
           for K in strikes]
    return {"underlying": "TEST", "points": pts}


# ── consumption layer (synthetic, exact) ─────────────────

def test_smile_extraction_and_sabr_roundtrip():
    F, T = 100.0, 0.5
    surf = _sabr_surface(F, T, 0.30, 0.5, -0.4, 0.6)
    sm = smile_at_expiry(surf)
    assert len(sm["strikes"]) == 13 and sm["expiry"] == "2026-12-16"
    cal = sabr_calibrate(sm["ivs"], F, sm["strikes"], T, beta=0.5)
    assert cal["rmse"] < 1e-4
    assert cal["alpha"] == pytest.approx(0.30, abs=2e-3)
    assert cal["rho"] == pytest.approx(-0.40, abs=2e-3)
    assert cal["nu"] == pytest.approx(0.60, abs=2e-3)


def test_estimate_forward_vertex():
    # symmetric smile (rho=0) -> vertex at the forward
    surf = _sabr_surface(100.0, 0.5, 0.30, 0.5, 0.0, 0.6)
    sm = smile_at_expiry(surf)
    assert estimate_forward(sm["strikes"], sm["ivs"]) == pytest.approx(100.0, abs=2.0)


def test_clean_smile_drops_garbage():
    strikes = [80, 90, 100, 110, 120, 130]
    ivs = [0.25, 0.22, 0.20, 0.22, 0.26, 9.9]      # last = garbage
    s, v, F = clean_smile(strikes, ivs, iv_hi=1.5, band=0.5)
    assert 9.9 not in v and 130 not in s
    assert F == pytest.approx(100.0, abs=1e-9)


def test_rr_bf_skew_sign_and_flat():
    F, T = 100.0, 0.5
    sm = smile_at_expiry(_sabr_surface(F, T, 0.30, 0.5, -0.4, 0.6))   # rho<0
    rb = rr_bf_25delta(sm, T, F)
    assert rb["rr_25"] < 0                          # downward skew
    flat = {"strikes": list(np.linspace(70, 130, 13)), "ivs": [0.25] * 13}
    rbf = rr_bf_25delta(flat, T, F)
    assert abs(rbf["rr_25"]) < 1e-6 and abs(rbf["bf_25"]) < 1e-6


# ── live-data wiring (graceful skip) ─────────────────────

def _live():
    from app.runtime import market_service, is_live
    return (market_service(), True) if is_live() else (None, False)


def test_live_option_smile_extraction():
    ms, live = _live()
    if not live:
        pytest.skip("no live market DB")
    from app.runtime import active_snapshot
    snap = active_snapshot(ms)
    found = [k[:-6] for k in snap.vol_surfaces if k.endswith("_FORTS")]
    assert found, "no FORTS surfaces in live snapshot"
    got = [u for u in found if ms.get_option_smile(u, snapshot=snap)]
    assert got, "no extractable smile"
    sm = ms.get_option_smile(got[0], snapshot=snap)
    assert len(sm["strikes"]) >= 5 and sm["forward"] > 0 and sm["T"] > 0


def test_live_fx_rr_bf_sane():
    ms, live = _live()
    if not live:
        pytest.skip("no live market DB")
    rb = ms.get_fx_rr_bf("Si")
    if not rb:
        pytest.skip("no Si FX smile in snapshot")
    assert 0.02 < rb["atm_vol"] < 1.0              # sane FX vol
    assert abs(rb["rr_25"]) < 0.5 and rb["forward"] > 0


def test_sabr_from_market_service():
    from services.pricing_service import PricingService
    ms, live = _live()
    if not live:
        pytest.skip("no live market DB")
    from app.runtime import active_snapshot
    snap = active_snapshot(ms)
    und = next((k[:-6] for k in snap.vol_surfaces
                if k.endswith("_FORTS") and ms.get_option_smile(k[:-6], snapshot=snap)), None)
    if not und:
        pytest.skip("no calibratable underlying")
    res = PricingService().calibrate_sabr_from_market(und)
    assert res["errors"] == [] and res["n_strikes"] >= 5 and res["alpha"] > 0
