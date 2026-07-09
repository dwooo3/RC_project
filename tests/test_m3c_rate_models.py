"""
M3c — closing the rate-model space. Black-Karasinski (lognormal short rate),
Cheyette (quasi-Gaussian HJM), and the cross-currency basis bootstrap. Each is
validated identity-first, plus M0 wiring + service routing.
"""
import numpy as np
import pytest

from curves.yield_curve import YieldCurve
from models.black_karasinski import BlackKarasinski
from models.cheyette import Cheyette
from models.short_rate import HullWhite
from curves.xccy_curve import (bootstrap_xccy_curve, xccy_basis_swap_npv,
                               implied_fx_forwards)


# ══════════════════════ Black-Karasinski ══════════════════════

@pytest.fixture(scope="module")
def bk():
    return BlackKarasinski(0.1, 0.20, YieldCurve.flat(0.08), T=6.0, steps_per_year=24)


def test_bk_curve_reprice(bk):
    curve = YieldCurve.flat(0.08)
    for t in (1, 2, 3, 5, 6):
        i = int(round(t / bk.dt))
        assert bk.discount_to_zero(i) == pytest.approx(curve.discount(t), abs=1e-12)


def test_bk_positive_rates(bk):
    rmin = min(bk.short_rate(i, j) for i in range(bk.steps + 1)
               for j in range(-bk.j_max, bk.j_max + 1))
    assert rmin > 0.0


def test_bk_payer_receiver_parity(bk):
    """σ-free identity guaranteed by curve repricing."""
    curve = YieldCurve.flat(0.08)
    N, K, To, Ts, freq = 1_000_000, 0.08, 2.0, 4.0, 2
    pay = bk.swaption(N, K, To, Ts, freq, "payer")["price"]
    rec = bk.swaption(N, K, To, Ts, freq, "receiver")["price"]
    times = [To + i / freq for i in range(1, int(Ts * freq) + 1)]
    ann0 = sum((1 / freq) * curve.discount(t) for t in times)
    S0 = (curve.discount(To) - curve.discount(times[-1])) / ann0
    assert pay - rec == pytest.approx(N * ann0 * (S0 - K), abs=1e-2)


def test_bk_sigma_zero_is_intrinsic():
    curve = YieldCurve.flat(0.08)
    N, To, Ts, freq = 1_000_000, 2.0, 4.0, 2
    times = [To + i / freq for i in range(1, int(Ts * freq) + 1)]
    ann0 = sum((1 / freq) * curve.discount(t) for t in times)
    S0 = (curve.discount(To) - curve.discount(times[-1])) / ann0
    bk0 = BlackKarasinski(0.1, 1e-4, curve, To + Ts, 24)
    for K in (0.06, 0.10):
        pay = bk0.swaption(N, K, To, Ts, freq, "payer")["price"]
        assert pay == pytest.approx(N * ann0 * max(S0 - K, 0.0), abs=1.0)


def test_bk_monotone_in_vol():
    curve = YieldCurve.flat(0.08)
    prices = [BlackKarasinski(0.1, s, curve, 6.0, 24)
              .swaption(1_000_000, 0.08, 2.0, 4.0, 2, "payer")["price"]
              for s in (0.05, 0.15, 0.30)]
    assert prices[0] < prices[1] < prices[2]


# ══════════════════════ Cheyette ══════════════════════

@pytest.fixture(scope="module")
def curve06():
    return YieldCurve.flat(0.06)


def test_cheyette_bond_reconstruction(curve06):
    ch = Cheyette(curve06, 0.1, 0.01, skew=0.0)
    for T in (1, 5, 10):
        assert ch.bond(0.0, T, 0.0, 0.0) == pytest.approx(curve06.discount(T), abs=1e-14)


def test_cheyette_const_vol_is_hull_white(curve06):
    """Constant local vol collapses to one-factor Hull-White."""
    a, sig = 0.1, 0.01
    ch = Cheyette(curve06, a, sig, skew=0.0)
    hw = HullWhite(a, sig, curve06)
    N, To, Ts, freq = 1_000_000, 2.0, 5.0, 2
    for K in (0.05, 0.06, 0.07):
        mc = ch.swaption(N, K, To, Ts, freq, "payer", n_sims=200_000, steps=80, seed=5)
        jam = hw.swaption(N, K, To, Ts, freq)["payer"]
        assert mc["price"] == pytest.approx(jam, abs=4 * mc["stderr"]), K


def test_cheyette_payer_receiver_parity(curve06):
    ch = Cheyette(curve06, 0.1, 0.01, skew=0.0)
    N, K, To, Ts, freq = 1_000_000, 0.06, 2.0, 5.0, 2
    pay = ch.swaption(N, K, To, Ts, freq, "payer", n_sims=200_000, steps=80, seed=5)
    rec = ch.swaption(N, K, To, Ts, freq, "receiver", n_sims=200_000, steps=80, seed=5)
    times = [To + i / freq for i in range(1, int(Ts * freq) + 1)]
    ann0 = sum((1 / freq) * curve06.discount(t) for t in times)
    S0 = (curve06.discount(To) - curve06.discount(times[-1])) / ann0
    parity = pay["price"] - rec["price"] - N * ann0 * (S0 - K)
    assert parity == pytest.approx(0.0, abs=3 * (pay["stderr"] + rec["stderr"]) + 50)


def test_cheyette_monotone_skew(curve06):
    """The skew parameter monotonically tilts the swaption smile slope."""
    from models.short_rate import _forward_swap_rate
    from models.black_scholes import black76
    from scipy.optimize import brentq
    To, Ts, freq = 2.0, 5.0, 2
    S0, ann = _forward_swap_rate(curve06, To, Ts, freq)

    def slope(skew):
        ch = Cheyette(curve06, 0.1, 0.01, skew=skew)
        vols = []
        for K in (0.05, 0.07):
            p = ch.swaption(1.0, K, To, Ts, freq, "payer",
                            n_sims=400_000, steps=80, seed=9)["price"]
            vols.append(brentq(lambda v: ann * black76(S0, K, To, 0, v, "call").price - p,
                               1e-4, 2.0))
        return vols[1] - vols[0]

    assert slope(-3.0) < slope(0.0) < slope(3.0)


# ══════════════════════ XCCY basis curve ══════════════════════

@pytest.fixture(scope="module")
def xccy_setup():
    dom = YieldCurve.flat(0.12)
    forc = YieldCurve.flat(0.04)
    tenors = [1, 2, 3, 5, 7, 10]
    basis = [-25, -30, -35, -40, -45, -50]
    return dom, forc, 90.0, tenors, basis


def test_xccy_par_reprice(xccy_setup):
    dom, forc, S0, tenors, basis = xccy_setup
    xc = bootstrap_xccy_curve(dom, forc, S0, tenors, basis, freq=4)
    for T, b in zip(tenors, basis):
        assert xccy_basis_swap_npv(dom, forc, xc, S0, T, b, freq=4) == pytest.approx(0.0, abs=1e-9)


def test_xccy_par_reprice_nonflat():
    dom = YieldCurve.from_par_rates([1, 2, 3, 5, 7, 10],
                                    [0.14, 0.13, 0.125, 0.12, 0.118, 0.115])
    forc = YieldCurve.from_par_rates([1, 2, 3, 5, 7, 10],
                                     [0.045, 0.044, 0.043, 0.042, 0.041, 0.040])
    tenors, basis = [1, 2, 3, 5, 7, 10], [-25, -30, -35, -40, -45, -50]
    xc = bootstrap_xccy_curve(dom, forc, 90.0, tenors, basis, freq=2)
    for T, b in zip(tenors, basis):
        assert xccy_basis_swap_npv(dom, forc, xc, 90.0, T, b, freq=2) == pytest.approx(0.0, abs=1e-9)


def test_xccy_zero_basis_is_foreign(xccy_setup):
    dom, forc, S0, tenors, _ = xccy_setup
    xc = bootstrap_xccy_curve(dom, forc, S0, tenors, [0] * len(tenors), freq=4)
    for T in (1, 2, 5, 10):
        assert xc.discount(T) == pytest.approx(forc.discount(T), abs=1e-10)


def test_xccy_basis_sign(xccy_setup):
    dom, forc, S0, tenors, basis = xccy_setup
    xc = bootstrap_xccy_curve(dom, forc, S0, tenors, basis, freq=4)
    assert xc.discount(5) > forc.discount(5)        # negative foreign-leg basis


def test_xccy_cip_forwards_monotone(xccy_setup):
    dom, forc, S0, tenors, basis = xccy_setup
    xc = bootstrap_xccy_curve(dom, forc, S0, tenors, basis, freq=4)
    fwds = list(implied_fx_forwards(dom, xc, S0, tenors).values())
    assert all(f > S0 for f in fwds)                # dom rate > for rate -> F > S0
    assert all(b > a for a, b in zip(fwds, fwds[1:]))


# ══════════════════════ M0 wiring + service ══════════════════════

def test_m3c_wired():
    from models import taxonomy as tax
    from models import parameters as P
    from models import registry as R
    for mid in ("bk", "cheyette"):
        assert mid in tax.engines_for("swaption")
        assert tax.classify(mid)["asset_class"] == "rates"
        assert R.MODEL_REGISTRY[mid]["status"].value in ("Approximation", "Validated")
    assert {"a", "sigma"} <= {s.key for s in P.engine_params("bk")}
    assert "skew" in {s.key for s in P.engine_params("cheyette")}
    assert tax.classify("xccy_curve")["asset_class"] == "fx"
    assert "xccy_curve" in R.MODEL_REGISTRY


def test_m3c_service_routes():
    from services.pricing_service import PricingService
    svc = PricingService()
    bk = svc.price_bk_swaption(1_000_000, 0.10, 1.0, 4.0, steps_per_year=12)
    assert bk["errors"] == [] and bk["value"] > 0 and bk["model_id"] == "bk"
    ch = svc.price_cheyette_swaption(1_000_000, 0.10, 1.0, 4.0, n_sims=20_000, steps=40)
    assert ch["errors"] == [] and ch["value"] > 0 and ch["model_id"] == "cheyette"
    xc = svc.build_xccy_curve(90.0, [1, 2, 5], [-25, -30, -40])
    assert xc["errors"] == [] and len(xc["fx_forwards"]) == 3


def test_swaption_engine_dispatch_m3c():
    from app.panels.pricing_catalogue import products_by_category
    from services.pricing_service import PricingService
    svc = PricingService()
    prod = next(p for p in products_by_category("Swaps") if p.id == "swaption")
    assert {"bk", "cheyette"} <= set(prod.engines())
    base = {"notional": 1_000_000, "K": 0.10, "T_option": 1.0, "T_swap": 4.0,
            "freq": 2, "sigma": 0.20, "r": 0.10, "opt": "payer"}
    bk = prod.price(svc, dict(base, __engine="bk", a=0.1, sigma=0.20, steps_per_year=12))
    ch = prod.price(svc, dict(base, __engine="cheyette", a=0.1, sigma=0.01, skew=0.0,
                              n_sims=20_000, steps=40))
    assert bk["errors"] == [] and bk["value"] > 0
    assert ch["errors"] == [] and ch["value"] > 0
