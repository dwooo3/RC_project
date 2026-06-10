"""
Phase 1 — market data wired into pricing.
Covers: hazard-curve bootstrap + CDS/risky bond on the curve, real/inflation
curve + linker repricing, dual-curve service routing, Malz FX smile, and
vol-surface-aware vanilla / term-structure cap pricing.
"""
import numpy as np
import pytest

from curves.yield_curve import YieldCurve
from curves.hazard import HazardCurve, bootstrap_hazard_curve, cds_legs
from services.pricing_service import PricingService


@pytest.fixture(scope="module")
def disc():
    return YieldCurve.flat(0.12)


@pytest.fixture(scope="module")
def svc():
    return PricingService()


# ── Hazard curve + bootstrap ─────────────────────────────

def test_hazard_curve_basics():
    hc = HazardCurve([1, 3, 5], [0.01, 0.02, 0.03], recovery=0.4)
    assert hc.hazard(0.5) == 0.01 and hc.hazard(2.0) == 0.02 and hc.hazard(10.0) == 0.03
    assert hc.cumulative(3.0) == pytest.approx(0.01 + 0.02 * 2)
    # survival monotone decreasing
    ts = np.linspace(0.1, 12, 50)
    qs = [hc.survival(t) for t in ts]
    assert all(a >= b for a, b in zip(qs, qs[1:]))
    assert hc.default_prob(1.0, 3.0) == pytest.approx(hc.survival(1.0) - hc.survival(3.0))


def test_bootstrap_round_trip(disc):
    """Each quoted CDS must reprice to zero NPV on the bootstrapped curve."""
    tenors = [1.0, 3.0, 5.0, 7.0]
    spreads = [0.010, 0.012, 0.014, 0.016]
    hc = bootstrap_hazard_curve(tenors, spreads, disc, recovery=0.4)
    for T, s in zip(tenors, spreads):
        legs = cds_legs(s, T, 4, hc, disc, 0.4)
        assert legs["protection_pv"] - legs["premium_pv"] == pytest.approx(0.0, abs=1e-12), T


def test_bootstrap_flat_spread_credit_triangle(disc):
    """Flat spread term structure -> hazard ≈ s/(1-R) in every bucket."""
    hc = bootstrap_hazard_curve([1, 3, 5], [0.012] * 3, disc, recovery=0.4)
    for h in hc.hazards:
        assert h == pytest.approx(0.012 / 0.6, rel=0.03)


def test_bootstrap_infeasible_quote_raise_and_clamp(disc):
    """A long-end quote inconsistent with shorter ones must raise (or clamp on request)."""
    tenors = [1.0, 5.0, 10.0]
    spreads = [0.05, 0.30, 0.50]      # 50% par spread at 10y is unreachable
    with pytest.raises(ValueError, match="infeasible"):
        bootstrap_hazard_curve(tenors, spreads, disc, recovery=0.4)
    hc = bootstrap_hazard_curve(tenors, spreads, disc, recovery=0.4,
                                on_infeasible="clamp")
    assert 10.0 in hc.metadata["infeasible_tenors"]
    assert "warning" in hc.metadata
    # earlier feasible buckets are still exact
    legs = cds_legs(0.05, 1.0, 4, hc, disc, 0.4)
    assert legs["protection_pv"] - legs["premium_pv"] == pytest.approx(0.0, abs=1e-12)


def test_cds_curve_flat_matches_legacy_flat(disc):
    """Curve pricer on a flat hazard ≈ legacy flat-hazard CDS (no accrual term)."""
    from instruments.credit import cds, cds_curve
    hc = HazardCurve.flat(0.02, recovery=0.4)
    new = cds_curve(10_000_000, 0.01, 5.0, 4, hc, disc, 0.4)
    old = cds(10_000_000, 0.01, 5.0, 4, 0.02, 0.12, 0.4)
    # legacy has no accrual-on-default and a flat continuous discount; ~1% agreement
    assert new["fair_spread"] == pytest.approx(old["fair_spread"], rel=0.02)
    assert new["protection_pv"] == pytest.approx(old["protection_pv"], rel=0.02)


def test_survival_curve_from_spreads_now_bootstraps(disc):
    from instruments.credit import survival_curve_from_spreads
    res = survival_curve_from_spreads([1, 3, 5], [0.01, 0.012, 0.014],
                                      recovery=0.4, r_curve=disc)
    assert "curve" in res and isinstance(res["curve"], HazardCurve)
    # bootstrapped hazards differ from the naive s/(1-R) triangle beyond bucket 1
    assert res["hazards"][0] == pytest.approx(0.01 / 0.6, rel=0.05)


# ── Risky bond ───────────────────────────────────────────

def test_risky_bond_zero_hazard_equals_riskless(disc):
    from instruments.credit import risky_bond
    hc0 = HazardCurve([1, 5, 10], [0.0, 0.0, 0.0], recovery=0.4)
    res = risky_bond(100, 0.12, 5.0, 2, disc, hc0)
    assert res["price"] == pytest.approx(res["riskless_price"], abs=1e-9)
    assert res["credit_spread"] == pytest.approx(0.0, abs=1e-8)
    assert res["expected_loss"] == pytest.approx(0.0, abs=1e-9)


def test_risky_bond_monotonicity(disc):
    from instruments.credit import risky_bond
    p = [risky_bond(100, 0.12, 5.0, 2, disc,
                    HazardCurve.flat(h, recovery=0.4))["price"]
         for h in (0.005, 0.02, 0.05)]
    assert p[0] > p[1] > p[2]                      # price falls with hazard
    r_low = risky_bond(100, 0.12, 5.0, 2, disc, HazardCurve.flat(0.02, recovery=0.2))
    r_high = risky_bond(100, 0.12, 5.0, 2, disc, HazardCurve.flat(0.02, recovery=0.6))
    assert r_high["price"] > r_low["price"]        # price rises with recovery
    mid = risky_bond(100, 0.12, 5.0, 2, disc, HazardCurve.flat(0.02, recovery=0.4))
    assert mid["cs01"] < 0                         # long credit loses on spread widening
    assert mid["credit_spread"] > 0


# ── Inflation: real curve + linker ───────────────────────

def test_breakeven_round_trip():
    from curves.inflation import breakeven_rate, real_curve_from_breakeven
    nominal = YieldCurve.flat(0.12)
    tenors = [1, 2, 5, 10]
    bes = [0.07, 0.072, 0.075, 0.08]
    real = real_curve_from_breakeven(nominal, tenors, bes, label="real")
    for T, be in zip(tenors, bes):
        assert breakeven_rate(nominal, real, T) == pytest.approx(be, abs=1e-10)


def test_linker_curve_pair_matches_flat_when_breakeven_flat():
    """Real curve with flat breakeven == legacy flat-inflation projection."""
    from curves.inflation import inflation_linked_bond_curve, real_curve_from_breakeven
    from instruments.fixed_income import inflation_linked_bond
    nominal = YieldCurve.flat(0.12)
    be = 0.06
    real = real_curve_from_breakeven(nominal, [1, 2, 3, 5, 7, 10], [be] * 6)
    new = inflation_linked_bond_curve(1000, 0.025, 5.0, 2, nominal, real)
    old = inflation_linked_bond(1000, 0.025, 5.0, 2, nominal, inflation_rate=be)
    assert new["price"] == pytest.approx(old["price"], rel=1e-9)
    assert new["breakeven_inflation"] == pytest.approx(be, abs=1e-10)
    assert new["inflation_dv01"] > 0               # linker gains when breakeven rises


def test_linker_service_route(svc):
    res = svc.price_inflation_linked_bond_real(1000, 0.025, 5.0, 2)
    assert res["errors"] == [] and res["value"] is not None
    assert res["raw"]["projection"] == "curve_pair"
    assert 0.0 < res["raw"]["breakeven_inflation"] < 0.20


# ── Dual-curve service routing ───────────────────────────

def test_irs_dual_curve_service(svc):
    single = svc.price_irs(1_000_000, 0.14, 3.0, 4, curve_id="cbr_key_demo")
    dual = svc.price_irs(1_000_000, 0.14, 3.0, 4, curve_id="cbr_key_demo",
                         proj_curve_id="ruonia_demo")
    assert single["errors"] == [] and dual["errors"] == []
    assert dual["raw"]["fair_rate"] != pytest.approx(single["raw"]["fair_rate"], abs=1e-6)
    # RUONIA demo curve is below the CBR key curve -> projected fair rate is lower
    assert dual["raw"]["fair_rate"] < single["raw"]["fair_rate"]


def test_cap_floor_term_structure_and_parity(svc):
    """Cap-floor parity must hold for a vol TERM STRUCTURE too (parity is vol-free)."""
    term = [(0.5, 0.32), (1.0, 0.30), (2.0, 0.27), (3.0, 0.25)]
    cap = svc.price_cap_floor(1_000_000, 0.10, 3.0, 4, term, "cap")
    floor = svc.price_cap_floor(1_000_000, 0.10, 3.0, 4, term, "floor")
    assert cap["errors"] == [] and floor["errors"] == []
    curve = svc.market_data.get_curve("flat_rub")
    swap = sum(0.25 * curve.discount(i * 0.25)
               * ((curve.discount((i - 1) * 0.25) / curve.discount(i * 0.25) - 1) / 0.25 - 0.10)
               for i in range(1, 13)) * 1_000_000
    assert cap["value"] - floor["value"] == pytest.approx(swap, abs=1e-6)


# ── Vol surface into vanilla ─────────────────────────────

def test_vanilla_priced_from_flat_surface(svc):
    by_sigma = svc.price_vanilla_option(100, 100, 1.0, 0.05, 0.20)
    by_surface = svc.price_vanilla_option(100, 100, 1.0, 0.05, sigma=None,
                                          vol_surface_id="equity_flat_demo")
    assert by_surface["errors"] == []
    assert by_surface["value"] == pytest.approx(by_sigma["value"], abs=1e-12)
    assert by_surface["raw"]["sigma_used"] == pytest.approx(0.20)


def test_vanilla_requires_sigma_or_surface(svc):
    res = svc.price_vanilla_option(100, 100, 1.0, 0.05, sigma=None)
    assert res["errors"]                            # governed error, not an exception


# ── FX smile (Malz) ──────────────────────────────────────

def test_malz_smile_quote_anchors():
    from instruments.fx import fx_smile_vol_delta
    atm, rr, bf = 0.18, -0.025, 0.008
    assert fx_smile_vol_delta(atm, rr, bf, 0.50) == pytest.approx(atm)
    assert fx_smile_vol_delta(atm, rr, bf, 0.25) == pytest.approx(atm + bf + rr / 2)
    assert fx_smile_vol_delta(atm, rr, bf, 0.75) == pytest.approx(atm + bf - rr / 2)


def test_fx_vol_for_strike_consistency():
    from instruments.fx import fx_smile_vol_delta, fx_vol_for_strike
    from scipy.stats import norm
    S, T, r_d, r_f = 90.0, 1.0, 0.16, 0.04
    atm, rr, bf = 0.18, -0.025, 0.008
    K = 95.0
    sigma = fx_vol_for_strike(S, K, T, r_d, r_f, atm, rr, bf)
    d1 = (np.log(S / K) + (r_d - r_f + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    assert sigma == pytest.approx(fx_smile_vol_delta(atm, rr, bf, norm.cdf(d1)), abs=1e-9)
    # negative RR (RUB put skew): low-delta calls (high strikes) carry LOWER vol
    sig_low_strike = fx_vol_for_strike(S, 75.0, T, r_d, r_f, atm, rr, bf)
    sig_high_strike = fx_vol_for_strike(S, 110.0, T, r_d, r_f, atm, rr, bf)
    assert sig_low_strike > sig_high_strike


def test_fx_option_smile_service_route(svc):
    direct = svc.price_fx_option_smile(90, 95, 1.0, 0.16, 0.04,
                                       atm=0.18, rr=-0.025, bf=0.008)
    from_surface = svc.price_fx_option_smile(90, 95, 1.0, 0.16, 0.04,
                                             vol_surface_id="fx_usdrub_demo")
    assert direct["errors"] == [] and from_surface["errors"] == []
    assert direct["value"] == pytest.approx(from_surface["value"], abs=1e-12)
    assert direct["raw"]["smile_model"] == "malz"


# ── Service routing of credit ────────────────────────────

def test_cds_curve_service_route(svc):
    res = svc.price_cds_curve(10_000_000, 0.012, 5.0, 4)
    assert res["errors"] == []
    assert res["model_id"] == "cds_curve"
    assert res["raw"]["fair_spread"] > 0


def test_risky_bond_service_route(svc):
    res = svc.price_risky_bond(1000, 0.13, 5.0, 2)
    assert res["errors"] == []
    raw = res["raw"]
    assert raw["price"] < raw["riskless_price"]
    assert raw["credit_spread"] > 0
    # HY hazard curve must price the same bond lower
    hy = svc.price_risky_bond(1000, 0.13, 5.0, 2, hazard_id="hazard_hy_demo")
    assert hy["raw"]["price"] < raw["price"]
