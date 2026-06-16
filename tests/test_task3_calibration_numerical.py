"""
Task-3 hardening: market-surface calibrations (LMM time-dependent vol,
Cheyette skew, Schwartz-Smith, CDO base correlation), the Heston ADI with the
Hout-Foulon v=0 boundary, and the FRTB vega/curvature/DRC extensions. All
validated identity-first (round-trip recovery / closed-form references).
"""
import numpy as np
import pytest
from scipy.optimize import brentq

from curves.yield_curve import YieldCurve
from risk.vol_cube import CapletVolStrip
from models.black_scholes import black76
from models.short_rate import _forward_swap_rate


# ══════════════════════ calibrations ══════════════════════

def test_lmm_instantaneous_vol_bootstrap():
    from models.rate_calibration import calibrate_lmm_instantaneous_vol
    curve = YieldCurve.flat(0.05)
    strip = CapletVolStrip([0.5, 1, 2, 3, 4, 4.5], [0.30, 0.28, 0.25, 0.23, 0.22, 0.21])
    r = calibrate_lmm_instantaneous_vol(curve, strip, end=5.0, freq=2)
    assert r["arb_free"]
    for k, t in enumerate(r["resets"]):
        if t > 0:
            assert r["implied_caplet_vol"][k] == pytest.approx(strip.vol(t), abs=1e-10)


def test_cheyette_skew_calibration_roundtrip():
    from models.cheyette import Cheyette
    from models.rate_calibration import calibrate_cheyette_skew
    curve = YieldCurve.flat(0.05)
    a, sig, To, Ts, freq = 0.1, 0.01, 2.0, 5.0, 2
    S0, ann = _forward_swap_rate(curve, To, Ts, freq)
    true_skew = 2.5
    ch = Cheyette(curve, a, sig, skew=true_skew)
    strikes = [0.04, 0.05, 0.06]
    mkt = [brentq(lambda v: ann * black76(S0, K, To, 0, v, "call").price
                  - ch.swaption(1.0, K, To, Ts, freq, "payer", 150_000, 80, 11)["price"],
                  1e-4, 3.0) for K in strikes]
    cal = calibrate_cheyette_skew(curve, a, sig, To, Ts, strikes, mkt, freq,
                                  n_sims=150_000, steps=80, seed=11)
    assert cal["converged"] and cal["skew"] == pytest.approx(true_skew, abs=0.2)


def test_schwartz_smith_calibration_roundtrip():
    from models.commodity import SchwartzSmith
    from models.market_calibration import calibrate_schwartz_smith
    true = SchwartzSmith(chi0=0.1, xi0=np.log(60), kappa=1.4, sigma_chi=0.35,
                         mu_xi=0.02, sigma_xi=0.12, rho=0.25, r=0.04)
    tn = [0.25, 0.5, 1, 2, 3, 5]
    fut = [true.futures(T) for T in tn]
    vt = [0.25, 0.5, 1, 2, 3]
    vm = [np.sqrt(true.futures_log_var(T, T) / T) for T in vt]
    cs = calibrate_schwartz_smith(tn, fut, vt, vm, r=0.04, spot=true.spot)
    assert cs["converged"] and cs["rmse"] < 1e-6
    for T, f in zip(tn, fut):
        assert cs["model"].futures(T) == pytest.approx(f, rel=1e-6)


def test_base_correlation_flat_pool_is_flat():
    from models.market_calibration import calibrate_base_correlation, base_tranche_el
    pds = [0.05] * 50
    dets = [0.03, 0.07, 0.10, 0.15, 0.30]
    targets = [base_tranche_el(pds, 0.30, K) for K in dets]
    bc = calibrate_base_correlation(pds, dets, targets)
    for K in dets:
        assert bc[K] == pytest.approx(0.30, abs=2e-3)


def test_base_correlation_recovers_skew():
    """A market priced off detachment-varying correlations is recovered."""
    from models.market_calibration import calibrate_base_correlation, base_tranche_el
    pds = [0.04] * 60
    dets = [0.05, 0.15, 0.30]
    true_corr = [0.20, 0.35, 0.55]
    targets = [base_tranche_el(pds, rho, K) for rho, K in zip(true_corr, dets)]
    bc = calibrate_base_correlation(pds, dets, targets)
    for K, rho in zip(dets, true_corr):
        assert bc[K] == pytest.approx(rho, abs=2e-3)


# ══════════════════════ Heston ADI (Hout-Foulon) ══════════════════════

@pytest.mark.parametrize("K", [90, 100, 110])
def test_heston_adi_matches_cf(K):
    from models.adi import heston_adi
    from models.heston import heston_price
    args = dict(S0=100, K=K, T=1.0, r=0.03, q=0.0, v0=0.04, kappa=1.5,
                theta=0.04, sigma=0.3, rho=-0.6, opt="call")
    cf = heston_price(100, K, 1.0, 0.03, 0.0, 0.04, 1.5, 0.04, 0.3, -0.6, "call")["price"]
    adi = heston_adi(**args, NS=100, Nv=50, Nt=70)
    assert adi == pytest.approx(cf, rel=0.015)


def test_heston_adi_put_call_parity():
    from models.adi import heston_adi
    kw = dict(S0=100, K=100, T=1.0, r=0.03, q=0.0, v0=0.04, kappa=1.5,
              theta=0.04, sigma=0.3, rho=-0.6, NS=90, Nv=45, Nt=60)
    c = heston_adi(**kw, opt="call")
    p = heston_adi(**kw, opt="put")
    assert c - p == pytest.approx(100 * np.exp(0) - 100 * np.exp(-0.03), abs=0.05)


# ══════════════════════ FRTB vega / curvature / DRC ══════════════════════

def test_frtb_vega_equals_delta_math():
    from models.frtb import frtb_vega_charge, frtb_delta_charge
    f = [{"bucket": 1, "sensitivity": 2000, "risk_weight": 0.1},
         {"bucket": 2, "sensitivity": -500, "risk_weight": 0.1}]
    assert frtb_vega_charge(f)["charge"] == pytest.approx(frtb_delta_charge(f)["charge"])


def test_frtb_curvature_nonneg_and_scales():
    from models.frtb import frtb_curvature_charge, curvature_cvr
    assert curvature_cvr(100, 92, 95, -5.0, 0.1) > 0          # convex -> positive
    cf = [{"bucket": 1, "cvr": 8.0}, {"bucket": 1, "cvr": 5.0}, {"bucket": 2, "cvr": -3.0}]
    c1 = frtb_curvature_charge(cf)["charge"]
    c2 = frtb_curvature_charge([{**x, "cvr": 2 * x["cvr"]} for x in cf])["charge"]
    assert c1 >= 0 and c2 == pytest.approx(2 * c1, rel=1e-9)


def test_frtb_drc_hedge_benefit():
    from models.frtb import frtb_drc_charge
    single = frtb_drc_charge([{"bucket": 1, "jtd": 1000, "risk_weight": 0.08}])["charge"]
    assert single == pytest.approx(80.0)
    hedged = frtb_drc_charge([{"bucket": 1, "jtd": 1000, "risk_weight": 0.08},
                              {"bucket": 1, "jtd": -1000, "risk_weight": 0.08}])["charge"]
    assert hedged < single                              # partial hedge offset
    nohedge = frtb_drc_charge([{"bucket": 1, "jtd": 1000, "risk_weight": 0.08},
                               {"bucket": 2, "jtd": -1000, "risk_weight": 0.08}])["charge"]
    assert nohedge == pytest.approx(single)             # different bucket = no offset


def test_frtb_total_sums_components():
    from models.frtb import frtb_capital
    d = [{"bucket": 1, "sensitivity": 1000, "risk_weight": 0.05}]
    cf = [{"bucket": 1, "cvr": 6.0}]
    drc = [{"bucket": 1, "jtd": 1000, "risk_weight": 0.08}]
    r = frtb_capital(delta_factors=d, vega_factors=d, curvature_factors=cf, drc_factors=drc)
    assert r["sbm"] == pytest.approx(r["delta"] + r["vega"] + r["curvature"])
    assert r["total"] == pytest.approx(r["sbm"] + r["drc"])


# ══════════════════════ service routes ══════════════════════

def test_task3_service_routes():
    from services.pricing_service import PricingService
    from services.risk_service import RiskService
    ps = PricingService()
    # Heston ADI engine
    h = ps.price_heston_adi(100, 100, 1.0, 0.03, 0.0, 0.04, 1.5, 0.04, 0.3, -0.6,
                            NS=80, Nv=40, Nt=50)
    assert h["errors"] == [] and h["value"] > 0 and h["model_id"] == "adi"
    # commodity calibration
    from models.commodity import SchwartzSmith
    true = SchwartzSmith(chi0=0.05, xi0=np.log(55), kappa=1.2, sigma_chi=0.3,
                         mu_xi=0.0, sigma_xi=0.15, rho=0.2, r=0.04)
    tn = [0.25, 0.5, 1, 2, 3]
    cc = ps.calibrate_commodity("schwartz_smith", tn, [true.futures(T) for T in tn],
                                tn, [np.sqrt(true.futures_log_var(T, T) / T) for T in tn],
                                r=0.04, spot=true.spot)
    assert cc["errors"] == [] and cc["rmse"] < 1e-5
    # base correlation
    from models.market_calibration import base_tranche_el
    pds = [0.05] * 40
    bc = ps.calibrate_base_correlation(pds, [0.05, 0.15], [base_tranche_el(pds, 0.3, 0.05),
                                                           base_tranche_el(pds, 0.3, 0.15)])
    assert bc["errors"] == [] and abs(bc["base_correlation"][0.05] - 0.3) < 2e-3
    # FRTB full via risk service
    rs = RiskService()
    fr = rs.frtb_capital([{"bucket": 1, "sensitivity": 1000, "risk_weight": 0.05}],
                         vega_factors=[{"bucket": 1, "sensitivity": 500, "risk_weight": 0.1}],
                         curvature_factors=[{"bucket": 1, "cvr": 6.0}],
                         drc_factors=[{"bucket": 1, "jtd": 1000, "risk_weight": 0.08}])
    assert fr["errors"] == [] and fr["raw"]["total"] > 0
