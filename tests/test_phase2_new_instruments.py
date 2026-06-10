"""
Phase 2 — new instrument classes.
NDF, XCCY swap, inflation swaps (ZC/YoY), CMS convexity, Bermudan swaption
(Hull-White tree), convertible bond (Tsiveriotis-Fernandes).
Every pricer is pinned by identities or a closed-form/analytic cross-check.
"""
import numpy as np
import pytest

from curves.yield_curve import YieldCurve
from services.pricing_service import PricingService


@pytest.fixture(scope="module")
def svc():
    return PricingService()


@pytest.fixture(scope="module")
def flat():
    return YieldCurve.flat(0.10)


# ── NDF ──────────────────────────────────────────────────

def test_ndf_zero_at_forward_and_settle_equivalence():
    from instruments.fx import fx_forward, ndf
    S, T, r_d, r_f, N = 90.0, 0.5, 0.16, 0.05, 1_000_000
    F = S * np.exp((r_d - r_f) * T)
    # struck at the forward: zero NPV in both settlement conventions
    assert ndf(S, F, T, r_d, r_f, N, "foreign")["npv"] == pytest.approx(0.0, abs=1e-9)
    assert ndf(S, F, T, r_d, r_f, N, "domestic")["npv"] == pytest.approx(0.0, abs=1e-9)
    # domestic settlement == deliverable forward NPV
    K = 92.0
    dom = ndf(S, K, T, r_d, r_f, N, "domestic")["npv"]
    deliverable = fx_forward(S, r_d, r_f, T, N, forward_agreed=K)["npv"]
    assert dom == pytest.approx(deliverable, rel=1e-12)
    # both settlement conventions are economically identical at the fixing date
    # (N·(S_T-K)/S_T foreign units == N·(S_T-K) domestic at the same instant),
    # so their PVs must coincide: df_f·(F-K)/F·S == df_d·(F-K) via F = S·df_f/df_d
    fgn = ndf(S, K, T, r_d, r_f, N, "foreign")["npv"]
    assert fgn == pytest.approx(dom, rel=1e-12)
    # long/short antisymmetry
    assert ndf(S, K, T, r_d, r_f, N, "foreign", "short")["npv"] == pytest.approx(-fgn)


def test_ndf_service_route(svc):
    res = svc.price_ndf(90, 92, 0.5, 0.16, 0.05)
    assert res["errors"] == [] and res["model_id"] == "ndf"


# ── XCCY swap ────────────────────────────────────────────

def test_xccy_same_curves_zero_basis(flat):
    """Identical curves both sides + notional exchange -> NPV 0, fair basis 0."""
    from instruments.xccy import xccy_swap
    res = xccy_swap(90_000_000, 90.0, 5.0, 4, flat, flat, basis_spread=0.0)
    assert res["npv"] == pytest.approx(0.0, abs=1e-6)
    assert res["fair_basis_spread"] == pytest.approx(0.0, abs=1e-10)


def test_xccy_fair_basis_zeroes_npv(flat):
    from instruments.xccy import xccy_swap
    fgn = YieldCurve.flat(0.05)
    res = xccy_swap(90_000_000, 90.0, 5.0, 4, flat, fgn, basis_spread=0.0)
    fair = res["fair_basis_spread"]
    at_fair = xccy_swap(90_000_000, 90.0, 5.0, 4, flat, fgn, basis_spread=fair)
    assert at_fair["npv"] == pytest.approx(0.0, abs=1e-6)
    # with notional exchange both float legs are par in their own ccy -> basis ≈ 0
    assert fair == pytest.approx(0.0, abs=1e-10)
    # receive-domestic with a positive basis spread has positive NPV
    pos = xccy_swap(90_000_000, 90.0, 5.0, 4, flat, fgn, basis_spread=0.005)
    assert pos["npv"] > 0
    assert xccy_swap(90_000_000, 90.0, 5.0, 4, flat, fgn, basis_spread=0.005,
                     receive_domestic=False)["npv"] == pytest.approx(-pos["npv"])


def test_xccy_fixed_fixed_legs(flat):
    """Fixed-fixed XCCY with each fixed rate at its curve's par rate -> NPV ≈ 0."""
    from instruments.xccy import xccy_swap
    fgn = YieldCurve.flat(0.05)
    par_dom = flat.par_rate(5.0, 4)
    par_fgn = fgn.par_rate(5.0, 4)
    res = xccy_swap(90_000_000, 90.0, 5.0, 4, flat, fgn,
                    leg_dom="fixed", leg_fgn="fixed",
                    fixed_rate_dom=par_dom, fixed_rate_fgn=par_fgn)
    # par fixed leg + redemption = par in each currency -> both legs = notional
    assert res["npv"] == pytest.approx(0.0, abs=1.0)


def test_xccy_service_route(svc):
    res = svc.price_xccy_swap(90_000_000, 90.0, 5.0, 4, basis_spread=-0.005)
    assert res["errors"] == [] and res["model_id"] == "xccy_swap"
    assert res["raw"]["npv"] < 0          # paying away 50bp on the received leg


# ── Inflation swaps ──────────────────────────────────────

def test_zciis_fair_equals_breakeven(svc):
    from curves.inflation import breakeven_rate
    from instruments.inflation_swaps import zc_inflation_swap
    nominal, real = YieldCurve.flat(0.12), YieldCurve.flat(0.05)
    res = zc_inflation_swap(1_000_000, 0.05, 5.0, nominal, real)
    be = breakeven_rate(nominal, real, 5.0)
    assert res["fair_rate"] == pytest.approx(be, abs=1e-12)
    at_fair = zc_inflation_swap(1_000_000, be, 5.0, nominal, real)
    assert at_fair["npv"] == pytest.approx(0.0, abs=1e-6)
    # payer of fixed gains when breakeven exceeds the strike
    low_K = zc_inflation_swap(1_000_000, be - 0.01, 5.0, nominal, real)
    assert low_K["npv"] > 0
    assert low_K["inflation_dv01"] > 0


def test_yoy_swap_flat_curves(svc):
    """Flat nominal/real curves: every YoY period has the same breakeven, and the
    fair YoY rate equals the one-period compounding of it."""
    from instruments.inflation_swaps import yoy_inflation_swap
    nominal, real = YieldCurve.flat(0.12), YieldCurve.flat(0.05)
    res = yoy_inflation_swap(1_000_000, 0.07, 5.0, 1, nominal, real)
    expected_yoy = np.exp(0.12 - 0.05) - 1.0
    assert res["fair_rate"] == pytest.approx(expected_yoy, abs=1e-10)
    at_fair = yoy_inflation_swap(1_000_000, res["fair_rate"], 5.0, 1, nominal, real)
    assert at_fair["npv"] == pytest.approx(0.0, abs=1e-6)


def test_inflation_swap_service_routes(svc):
    zc = svc.price_zc_inflation_swap(1_000_000, 0.08, 5.0)
    yoy = svc.price_yoy_inflation_swap(1_000_000, 0.08, 5.0)
    assert zc["errors"] == [] and yoy["errors"] == []
    assert zc["model_id"] == yoy["model_id"] == "inflation_swap"


# ── CMS convexity ────────────────────────────────────────

def test_cms_adjustment_properties(flat):
    from instruments.fixed_income import cms_convexity_adjustment, cms_swaplet
    S0 = flat.par_rate(5.0, 2)
    adj = cms_convexity_adjustment(S0, 0.25, 1.0, 5.0, 2)
    assert adj > 0                                          # always positive
    assert cms_convexity_adjustment(S0, 0.0, 1.0, 5.0, 2) == pytest.approx(0.0)
    assert cms_convexity_adjustment(S0, 0.50, 1.0, 5.0, 2) > adj       # ↑ in vol
    assert cms_convexity_adjustment(S0, 0.25, 4.0, 5.0, 2) > adj       # ↑ in T
    # swaplet at zero vol = pure forward swap rate coupon
    leg = cms_swaplet(1_000_000, 1.0, 1.25, 5.0, 4, flat, 0.0, tau=0.25)
    assert leg["expected_cms_rate"] == pytest.approx(leg["forward_swap_rate"])
    assert leg["pv"] == pytest.approx(
        1_000_000 * 0.25 * leg["forward_swap_rate"] * flat.discount(1.25))


def test_cms_swap_service(svc):
    res = svc.price_cms_swap(1_000_000, 0.10, 5.0, 4, 5.0, 0.25)
    assert res["errors"] == []
    raw = res["raw"]
    assert raw["avg_convexity_adjustment"] > 0
    # at zero vol the fair CMS rate is lower (no convexity pickup)
    res0 = svc.price_cms_swap(1_000_000, 0.10, 5.0, 4, 5.0, 0.0)
    assert raw["fair_rate"] > res0["raw"]["fair_rate"]


# ── Bermudan swaption (HW tree) ──────────────────────────

def test_hw_tree_reprices_curve(flat):
    from models.short_rate import HullWhiteTree
    tree = HullWhiteTree(0.1, 0.012, flat, T=3.0, steps=120)
    for i in (40, 80, 120):
        assert tree.Q[i].sum() == pytest.approx(flat.discount(i * tree.dt), abs=1e-12)


def test_bermudan_single_exercise_matches_jamshidian(flat):
    from models.short_rate import HullWhite, bermudan_swaption_hw
    hw = HullWhite(0.1, 0.012, flat)
    for K in (0.08, 0.10):
        berm = bermudan_swaption_hw(1_000_000, K, [1.0], 6.0, 2, flat,
                                    0.1, 0.012, "payer", steps=200)
        eu = hw.swaption(1_000_000, K, 1.0, 5.0, 2)["payer"]
        assert berm["price"] == pytest.approx(eu, rel=5e-3), K


def test_bermudan_dominates_european(flat):
    from models.short_rate import bermudan_swaption_hw
    b1 = bermudan_swaption_hw(1_000_000, 0.10, [1.0], 6.0, 2, flat, steps=150)
    b3 = bermudan_swaption_hw(1_000_000, 0.10, [1.0, 2.0, 3.0], 6.0, 2, flat, steps=150)
    assert b3["price"] >= b1["price"] - 1e-9
    assert b3["price"] >= b3["european_lower_bound"] - 1e-9


def test_bermudan_service_route(svc):
    res = svc.price_bermudan_swaption(1_000_000, 0.10, [1.0, 2.0], 5.0, steps=100)
    assert res["errors"] == [] and res["model_id"] == "bermudan_swaption"
    assert res["value"] > 0


# ── Convertible bond ─────────────────────────────────────

def test_convertible_limits(flat):
    from instruments.convertible import convertible_bond
    from instruments.fixed_income import fixed_bond
    # deep OTM -> bond floor == straight bond at r + credit spread
    otm = convertible_bond(1.0, 0.30, 0.0, 1000, 0.05, 2, 5.0, 10.0, flat, 0.02, N=300)
    risky = fixed_bond(1000, 0.05, 5.0, 2, flat.parallel_shift(200))["price"]
    assert otm["price"] == pytest.approx(risky, rel=2e-3)
    # ratio=0 and zero spread -> riskless straight bond
    riskless = convertible_bond(100, 0.30, 0.0, 1000, 0.05, 2, 5.0, 0.0, flat, 0.0, N=300)
    dcf = fixed_bond(1000, 0.05, 5.0, 2, flat)["price"]
    assert riskless["price"] == pytest.approx(dcf, rel=1e-6)
    # deep ITM -> parity, delta -> conversion ratio
    itm = convertible_bond(1000, 0.30, 0.0, 1000, 0.05, 2, 5.0, 10.0, flat, 0.02, N=300)
    assert itm["price"] == pytest.approx(itm["parity"], rel=0.03)
    assert itm["delta"] == pytest.approx(10.0, rel=0.02)


def test_convertible_bounds_and_features(flat):
    from instruments.convertible import convertible_bond
    base = convertible_bond(100, 0.30, 0.0, 1000, 0.05, 2, 5.0, 10.0, flat, 0.02, N=300)
    assert base["price"] >= max(base["parity"], base["bond_floor"]) - 1e-9
    lo = convertible_bond(100, 0.15, 0.0, 1000, 0.05, 2, 5.0, 10.0, flat, 0.02, N=300)
    hi = convertible_bond(100, 0.45, 0.0, 1000, 0.05, 2, 5.0, 10.0, flat, 0.02, N=300)
    assert lo["price"] < base["price"] < hi["price"]
    called = convertible_bond(100, 0.30, 0.0, 1000, 0.05, 2, 5.0, 10.0, flat, 0.02,
                              call_price=1100, call_start=1.0, N=300)
    putted = convertible_bond(100, 0.30, 0.0, 1000, 0.05, 2, 5.0, 10.0, flat, 0.02,
                              put_price=950, put_start=1.0, N=300)
    assert called["price"] <= base["price"] + 1e-9
    assert putted["price"] >= base["price"] - 1e-9


def test_convertible_service_route(svc):
    res = svc.price_convertible_bond(100, 0.30, 0.0, 1000, 0.05, 2, 5.0, 10.0, N=200)
    assert res["errors"] == [] and res["model_id"] == "convertible_bond"
    assert res["raw"]["bond_floor"] < res["value"]


# ── Catalogue coverage ───────────────────────────────────

def test_new_products_in_catalogue(svc):
    from app.panels.pricing_catalogue import PRODUCTS
    ids = {p.id for p in PRODUCTS}
    for pid in ("ndf", "fx_option_smile", "xccy", "zciis", "yoyiis",
                "bermudan_swaption", "cms_swap", "cds_curve", "risky_bond",
                "convertible"):
        assert pid in ids, pid


def test_new_catalogue_products_price_with_defaults(svc):
    """Every new product must price cleanly from its default field values."""
    from app.panels.pricing_catalogue import PRODUCTS
    new_ids = {"ndf", "fx_option_smile", "xccy", "zciis", "yoyiis",
               "bermudan_swaption", "cms_swap", "cds_curve", "risky_bond",
               "convertible"}
    for p in PRODUCTS:
        if p.id not in new_ids:
            continue
        values = {f.key: f.default for f in p.fields}
        res = p.price(svc, values)
        assert res["errors"] == [], (p.id, res["errors"])
        assert res["value"] is not None, p.id
        instrument, params, desc = p.to_position(values)
        assert instrument and isinstance(params, dict) and desc, p.id
