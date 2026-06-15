"""
M-calib — rate-model calibration phase. The G2++ analytic swaption (validated
vs the forward-measure MC and the η→0 Hull-White limit), plus identity-first
calibration: the LMM caplet strip recovers its vols exactly, and G2++ / LMM /
BK / Cheyette round-trip — calibrating to a surface the model itself generated
reprices it to numerical tolerance.
"""
import numpy as np
import pytest
from scipy.optimize import brentq

from curves.yield_curve import YieldCurve
from risk.vol_cube import SwaptionCube, CapletVolStrip
from models.short_rate import _forward_swap_rate, HullWhite
from models.black_scholes import black76
from models.g2pp import G2pp
from models.lmm import LMM
from models.black_karasinski import BlackKarasinski
from models import rate_calibration as RC


@pytest.fixture(scope="module")
def curve():
    return YieldCurve.flat(0.05)


# ══════════════════════ G2++ analytic swaption ══════════════════════

def test_g2pp_analytic_vs_mc(curve):
    g = G2pp(curve, 0.1, 0.01, 0.3, 0.012, -0.7)
    for To, Ts in [(1, 5), (2, 5), (5, 5)]:
        for K in (0.04, 0.05, 0.06):
            an = g.swaption_analytic(1_000_000, K, To, Ts, 2, "payer")
            mc = g.swaption(1_000_000, K, To, Ts, 2, "payer", n_sims=200_000, seed=3)
            assert an == pytest.approx(mc["price"], abs=4 * mc["stderr"]), (To, Ts, K)


def test_g2pp_analytic_eta_zero_is_hw(curve):
    """η→0 analytic G2++ payer collapses to the HW1F Jamshidian price."""
    g1 = G2pp(curve, 0.1, 0.01, 5.0, 1e-7, 0.0)
    hw = HullWhite(0.1, 0.01, curve)
    # η→0 is a degenerate limit for the 2-factor integral (σy→0 makes the
    # integrand a sharp step), so it needs a finer x-grid — it converges cleanly.
    for K in (0.04, 0.05, 0.06):
        an = g1.swaption_analytic(1_000_000, K, 1.0, 5.0, 2, "payer", n_x=256)
        assert an == pytest.approx(hw.swaption(1_000_000, K, 1.0, 5.0, 2)["payer"], rel=1e-3)


def test_g2pp_analytic_parity(curve):
    g = G2pp(curve, 0.1, 0.01, 0.3, 0.012, -0.7)
    K, To, Ts = 0.05, 2.0, 5.0
    pay = g.swaption_analytic(1_000_000, K, To, Ts, 2, "payer")
    rec = g.swaption_analytic(1_000_000, K, To, Ts, 2, "receiver")
    ti = [To + i * 0.5 for i in range(1, 11)]
    ann = sum(0.5 * curve.discount(t) for t in ti)
    S0 = (curve.discount(To) - curve.discount(ti[-1])) / ann
    assert pay - rec == pytest.approx(1_000_000 * ann * (S0 - K), abs=1e-3)


def test_g2pp_mc_forward_measure_fix(curve):
    """The fixed MC (forward-measure means) matches analytic at long expiry,
    where the old risk-neutral-mean MC was biased."""
    g = G2pp(curve, 0.1, 0.01, 0.3, 0.012, -0.7)
    an = g.swaption_analytic(1_000_000, 0.05, 5.0, 5.0, 2, "payer")
    mc = g.swaption(1_000_000, 0.05, 5.0, 5.0, 2, "payer", n_sims=300_000, seed=3)
    assert an == pytest.approx(mc["price"], abs=4 * mc["stderr"])


# ══════════════════════ calibration helpers ══════════════════════

@pytest.fixture(scope="module")
def grid():
    return [1.0, 2.0, 5.0], [2.0, 5.0]


def _cube_from(curve, expiries, tenors, price_fn):
    vols = np.zeros((len(expiries), len(tenors)))
    for i, e in enumerate(expiries):
        for j, t in enumerate(tenors):
            S0, ann = _forward_swap_rate(curve, e, t, 2)
            p = price_fn(S0, e, t)
            vols[i, j] = brentq(lambda v: ann * black76(S0, S0, e, 0, v, "call").price - p,
                                1e-4, 3.0)
    return SwaptionCube(expiries, tenors, vols)


# ══════════════════════ round-trip calibrations ══════════════════════

def test_g2pp_calibration_roundtrip(curve, grid):
    expiries, tenors = grid
    instruments = [(e, t) for e in expiries for t in tenors]
    true = dict(a=0.05, sigma=0.007, b=0.5, eta=0.011, rho=-0.6)
    g = G2pp(curve, **true)
    cube = _cube_from(curve, expiries, tenors,
                      lambda K, To, Ts: g.swaption_analytic(1.0, K, To, Ts, 2, "payer"))
    cal = RC.calibrate_g2pp(curve, cube, instruments, 2, 1.0, n_x=48)
    assert cal["converged"] and cal["rmse"] < 1e-6
    for k in ("a", "sigma", "b", "eta", "rho"):
        assert cal[k] == pytest.approx(true[k], abs=2e-3), k


def test_lmm_caplet_exact_recovery(curve):
    strip = CapletVolStrip([0.5, 1, 2, 3, 4, 4.5], [0.30, 0.28, 0.25, 0.23, 0.22, 0.21])
    lc = RC.calibrate_lmm_caplets(curve, strip, end=5.0, freq=2)
    for v, r in zip(lc["vols"], lc["resets"]):
        assert v == pytest.approx(strip.vol(r), abs=1e-12)


def test_lmm_swaption_calibration_roundtrip(curve, grid):
    expiries, tenors = grid
    instruments = [(e, t) for e in expiries for t in tenors]
    lm = LMM(curve, 0.0, 10.0, 2, vol=0.22, corr_beta=0.10)

    def px(K, To, Ts):
        a = int(round(To * 2)); b = int(round((To + Ts) * 2))
        return lm.swaption_black(1.0, K, a, b, "payer")

    cube = _cube_from(curve, expiries, tenors, px)
    cal = RC.calibrate_lmm_swaptions(curve, cube, instruments, 2, 1.0, end=10.0)
    assert cal["converged"] and cal["rmse"] < 1e-6
    assert cal["vol"] == pytest.approx(0.22, abs=1e-3)
    assert cal["corr_beta"] == pytest.approx(0.10, abs=5e-3)


def test_bk_calibration_roundtrip(curve):
    # multiple expiries (same tenor): the vol term structure identifies mean
    # reversion `a`, which ATM swaptions at a single expiry barely constrain.
    instruments = [(1.0, 3.0), (3.0, 3.0), (5.0, 3.0)]
    def px(K, To, Ts):
        return BlackKarasinski(0.08, 0.22, curve, To + Ts, 12).swaption(
            1.0, K, To, Ts, 2, "payer")["price"]
    cube = _cube_from(curve, [1.0, 3.0, 5.0], [3.0], px)
    cal = RC.calibrate_bk(curve, cube, instruments, 2, 1.0, steps_per_year=12)
    assert cal["converged"] and cal["rmse"] < 1e-4
    assert cal["a"] == pytest.approx(0.08, abs=1e-2)
    assert cal["sigma"] == pytest.approx(0.22, abs=5e-3)


def test_cheyette_calibration_is_hull_white(curve, grid):
    expiries, tenors = grid
    instruments = [(e, t) for e in expiries for t in tenors]
    hw = HullWhite(0.06, 0.009, curve)
    cube = _cube_from(curve, expiries, tenors,
                      lambda K, To, Ts: hw.swaption(1.0, K, To, Ts, 2)["payer"])
    cal = RC.calibrate_cheyette(curve, cube, instruments, 2, 1.0)
    assert cal["rmse"] < 1e-4
    assert cal["a"] == pytest.approx(0.06, abs=2e-3)
    assert cal["sigma"] == pytest.approx(0.009, abs=2e-4)
    assert cal["skew"] == 0.0


# ══════════════════════ service routing ══════════════════════

def test_calibration_service_route(curve, grid):
    from services.pricing_service import PricingService
    expiries, tenors = grid
    instruments = [(e, t) for e in expiries for t in tenors]
    lm = LMM(curve, 0.0, 10.0, 2, vol=0.22, corr_beta=0.10)

    def px(K, To, Ts):
        a = int(round(To * 2)); b = int(round((To + Ts) * 2))
        return lm.swaption_black(1.0, K, a, b, "payer")

    cube = _cube_from(curve, expiries, tenors, px)
    svc = PricingService()
    res = svc.calibrate_rate_model("lmm", instruments, freq=2, curve=curve, cube=cube)
    assert res["errors"] == [] and res["rmse"] < 1e-6


def test_g2pp_service_analytic_default(curve):
    from services.pricing_service import PricingService
    res = PricingService().price_g2pp_swaption(1_000_000, 0.05, 2.0, 5.0, curve=curve)
    assert res["errors"] == [] and res["value"] > 0
