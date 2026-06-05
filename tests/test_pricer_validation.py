"""Sanity validation of all PricingService pricers — parities, bounds, monotonicity."""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")

from services.pricing_service import PricingService


@pytest.fixture
def s():
    return PricingService()


def V(res):
    return res["value"]


# ── Vanilla: put-call parity ─────────────────────────────
def test_vanilla_put_call_parity(s):
    a = dict(S=100, K=100, T=1, r=0.05, sigma=0.2, q=0.0)
    c = V(s.price_vanilla_option(**a, opt="call"))
    p = V(s.price_vanilla_option(**a, opt="put"))
    assert c - p == pytest.approx(100 * math.exp(-0.0) - 100 * math.exp(-0.05), abs=0.05)


# ── Barrier: in-out parity and KO < vanilla ──────────────
def test_barrier_in_out_parity(s):
    base = dict(S=100, K=100, H=90, T=1, r=0.05, sigma=0.2, q=0.0, opt="call")
    ko = V(s.price_barrier_option(**base, barrier_type="down-out"))
    ki = V(s.price_barrier_option(**base, barrier_type="down-in"))
    vanilla = V(s.price_vanilla_option(S=100, K=100, T=1, r=0.05, sigma=0.2, opt="call"))
    assert ko + ki == pytest.approx(vanilla, abs=0.05)
    assert ko < vanilla


# ── Asian geometric < vanilla ────────────────────────────
def test_asian_cheaper_than_vanilla(s):
    asian = V(s.price_asian_option(100, 100, 1, 0.05, 0.2, averaging="geometric"))
    vanilla = V(s.price_vanilla_option(100, 100, 1, 0.05, 0.2, opt="call"))
    assert 0 < asian < vanilla


# ── Digital cash bounded by discounted notional ──────────
def test_digital_cash_bounds(s):
    d = V(s.price_digital_option(100, 100, 1, 0.05, 0.2, style="cash", cash=1.0))
    assert 0 < d < math.exp(-0.05)


# ── Lookback >= vanilla ──────────────────────────────────
def test_lookback_ge_vanilla(s):
    lb = V(s.price_lookback_option(100, 1, 0.05, 0.2, opt="call", strike_type="floating"))
    vanilla = V(s.price_vanilla_option(100, 100, 1, 0.05, 0.2, opt="call"))
    assert lb >= vanilla - 1e-6


# ── Bond: monotone in coupon (up) and rate (down) ────────
def test_bond_monotonicity(s):
    def bond(coupon, r):
        return V(s.price_bond(1000, coupon, 10, 2, curve=s.market_data.flat_curve(r)))
    assert bond(0.08, 0.10) > bond(0.05, 0.10)      # higher coupon -> higher price
    assert bond(0.06, 0.08) > bond(0.06, 0.12)      # higher rate -> lower price


# ── FRN near par, monotone in spread ─────────────────────
def test_frn_near_par_and_spread_monotone(s):
    def frn(spread):
        return V(s.price_frn(1000, spread, 5, 2, curve=s.market_data.flat_curve(0.10)))
    assert 700 < frn(0.0) < 1300
    assert frn(0.02) > frn(0.0)


# ── Cap/Floor: non-negative, cap down in K, floor up in K ─
def test_cap_floor_monotonicity(s):
    def cap(K):
        return V(s.price_cap_floor(1_000_000, K, 3, 2, 0.20, "cap", curve=s.market_data.flat_curve(0.10)))
    def floor(K):
        return V(s.price_cap_floor(1_000_000, K, 3, 2, 0.20, "floor", curve=s.market_data.flat_curve(0.10)))
    assert cap(0.08) >= cap(0.12) >= 0
    assert floor(0.12) >= floor(0.08) >= 0


# ── Swaption: non-negative, increasing in vol ────────────
def test_swaption_increasing_in_vol(s):
    def sw(vol):
        return V(s.price_swaption(1_000_000, 0.10, 1, 5, 2, vol, "payer",
                                  curve=s.market_data.flat_curve(0.10)))
    assert sw(0.30) >= sw(0.15) >= 0


# ── FX forward covered interest parity ───────────────────
def test_fx_forward_parity(s):
    raw = s.price_fx_forward(90, 0.10, 0.04, 1.0)["raw"]
    fwd = raw.get("forward")
    assert fwd == pytest.approx(90 * math.exp((0.10 - 0.04) * 1.0), rel=1e-3)


# ── FX option: increasing in vol ─────────────────────────
def test_fx_option_increasing_in_vol(s):
    lo = V(s.price_fx_option(90, 92, 1, 0.10, 0.04, 0.10, opt="call"))
    hi = V(s.price_fx_option(90, 92, 1, 0.10, 0.04, 0.25, opt="call"))
    assert hi > lo > 0


# ── Spread option: non-negative, down in K ───────────────
def test_spread_option_monotone_in_strike(s):
    def sp(K):
        return V(s.price_spread_option(100, 100, K, 1, 0.05, 0.2, 0.25, 0.4))
    assert sp(2) >= sp(8) >= 0


# ── IRS: fair-rate NPV near zero ─────────────────────────
def test_irs_fair_rate_zero_npv(s):
    curve = s.market_data.flat_curve(0.10)
    res = s.price_irs(1_000_000, 0.10, 5, 4, curve=curve)
    # at a flat 10% curve, a 10% fixed swap is close to fair
    assert abs(res["value"]) < 0.05 * 1_000_000


# ── CDS: positive fair spread ────────────────────────────
def test_cds_fair_spread_positive(s):
    res = s.price_cds(1_000_000, 0.01, 5, 4, hazard=0.02, r=0.05)
    assert res["raw"]["fair_spread"] > 0


# ── Autocall: finite, positive, bounded ──────────────────
def test_autocall_finite_bounded(s):
    res = s.price_autocall_phoenix(100, 0.05, 0.0, 0.20, 3.0, [1, 2, 3], 1.0, 0.70, 0.65, 0.10,
                                   n_sims=5000, steps=50)
    v = res["value"]
    assert v is not None and math.isfinite(v) and 0 < v < 300


# ── Fixed Income expansion: ZCB + FRA ────────────────────
def test_zero_coupon_bond_equals_discounted_face(s):
    import math as _m
    r, T, face = 0.10, 5.0, 1000.0
    res = s.price_bond(face, 0.0, T, 1, curve=s.market_data.flat_curve(r))
    assert res["value"] == pytest.approx(face * _m.exp(-r * T), rel=1e-6)


def test_fra_zero_at_fair_and_sign(s):
    curve = s.market_data.flat_curve(0.10)
    fair = s.price_fra(1_000_000, 0.10, 1, 1.5, curve=curve)["raw"]["forward_rate"]
    at_fair = s.price_fra(1_000_000, fair, 1, 1.5, curve=curve)["value"]
    assert abs(at_fair) < 1.0                       # NPV ~ 0 at the fair forward
    # pay-fixed below fair -> positive NPV (receive higher floating)
    assert s.price_fra(1_000_000, fair - 0.01, 1, 1.5, curve=curve)["value"] > 0


# ── FI-2: amortizing / step / perpetual / inflation-linked ──
def test_amortizing_bond_shorter_duration_than_bullet(s):
    curve = s.market_data.flat_curve(0.10)
    amo = s.price_amortizing_bond(1000, 0.07, 10, 2, "linear", curve=curve)
    bullet = s.price_bond(1000, 0.07, 10, 2, curve=curve)
    assert amo["value"] > 0
    assert amo["raw"]["effective_duration"] < bullet["raw"]["effective_duration"]


def test_step_bond_prices_and_unified_metrics(s):
    res = s.price_step_bond(1000, 0.05, 0.08, 3, 6, 2, curve=s.market_data.flat_curve(0.10))
    assert res["value"] > 0
    assert "key_rate_durations" in res["raw"] and res["raw"]["effective_duration"] > 0


def test_perpetual_equals_coupon_over_yield(s):
    curve = s.market_data.flat_curve(0.09)
    res = s.price_perpetual_bond(1000, 0.08, 1, curve=curve)
    y = curve.par_rate(30, 1)
    assert res["value"] == pytest.approx(1000 * 0.08 / y, rel=1e-6)


def test_inflation_linked_indexation_and_inflation_dv01(s):
    res = s.price_inflation_linked_bond(1000, 0.03, 10, 2, base_cpi=100, current_cpi=110,
                                        inflation_rate=0.04, curve=s.market_data.flat_curve(0.12))
    raw = res["raw"]
    assert raw["indexed_principal"] == pytest.approx(1100.0)   # face*110/100
    assert "inflation_dv01" in raw and "real_yield" in raw
    assert res["value"] > 0


# ── FI-3: money market ───────────────────────────────────
def test_deposit_npv_and_dv01(s):
    res = s.price_deposit(1_000_000, 0.10, 0.25, curve=s.market_data.flat_curve(0.10))
    assert res["value"] > 0
    assert res["raw"]["dv01"] > 0 and res["raw"]["maturity_value"] > 1_000_000


def test_treasury_bill_discount_and_bey(s):
    res = s.price_treasury_bill(1000, 0.09, 0.25)
    raw = res["raw"]
    assert res["value"] == pytest.approx(1000 * (1 - 0.09 * 0.25))
    assert raw["discount_yield"] == pytest.approx(0.09)
    assert raw["bey"] > raw["discount_yield"]          # BEY > discount yield
    assert raw["money_market_yield"] > 0


def test_commercial_paper_price_below_face(s):
    res = s.price_commercial_paper(1000, 0.11, 0.25)
    assert 0 < res["value"] < 1000
    assert res["raw"]["money_market_yield"] > 0


# ── FI-4: repo / reverse repo ────────────────────────────
def test_repo_forward_carry_funding(s):
    res = s.price_repo(1000, 0.10, 0.25, coupon_income=0.0, direction="repo")
    raw = res["raw"]
    assert res["value"] == pytest.approx(1000 * (1 + 0.10 * 0.25))   # forward price
    assert raw["financing_cost"] == pytest.approx(25.0)
    assert raw["carry"] < 0                                          # no coupon -> negative carry
    assert raw["funding_dv01"] > 0


def test_reverse_repo_flips_carry_sign(s):
    rp = s.price_repo(1000, 0.10, 0.25, 0.0, "repo")["raw"]["carry"]
    rev = s.price_repo(1000, 0.10, 0.25, 0.0, "reverse")["raw"]["carry"]
    assert rev == pytest.approx(-rp)


# ── FI-5: interest rate futures ──────────────────────────
def test_bond_future_ctd_and_invoice(s):
    deliv = [{"name": "B1", "clean_price": 98, "accrued": 1.0, "conversion_factor": 0.9,
              "coupon_income": 0.0, "dv01": 0.08}]
    res = s.price_bond_future(deliv, futures_price=108, repo_rate=0.08, T_delivery=0.25,
                              target_bpv=1000)
    raw = res["raw"]
    assert raw["ctd"] == "B1"
    assert raw["invoice_price"] == pytest.approx(108 * 0.9 + 1.0)
    assert raw["futures_dv01"] == pytest.approx(0.08 / 0.9)
    assert raw["hedge_ratio"] == pytest.approx(1000 / (0.08 / 0.9))


def test_bond_future_picks_min_net_basis(s):
    deliv = [
        {"name": "cheap", "clean_price": 95, "accrued": 0, "conversion_factor": 0.95,
         "coupon_income": 0, "dv01": 0.07},
        {"name": "rich", "clean_price": 99, "accrued": 0, "conversion_factor": 0.92,
         "coupon_income": 0, "dv01": 0.08},
    ]
    res = s.price_bond_future(deliv, 103, 0.05, 0.25)
    assert res["raw"]["ctd"] in ("cheap", "rich")
    # CTD must have the minimum net basis in the basket
    nb = {a["name"]: a["net_basis"] for a in res["raw"]["analysis"]}
    assert res["raw"]["net_basis"] == pytest.approx(min(nb.values()))


def test_stir_future_price_and_dv01(s):
    res = s.price_stir_future(0.10, 1_000_000, 0.25)
    assert res["value"] == pytest.approx(90.0)        # 100 - 10
    assert res["raw"]["dv01"] == pytest.approx(25.0)  # 1e6*0.25*1bp


# ── FI-6: callable / putable + OAS ───────────────────────
def test_callable_below_straight_and_oas_negative(s):
    res = s.price_callable_bond(1000, 0.08, 5, 2, sigma=0.15, call_price=1000, call_start=2,
                                option="callable", curve=s.market_data.flat_curve(0.07))
    raw = res["raw"]
    assert raw["callable_value"] < raw["straight_value"]    # option costs the holder
    assert raw["option_value"] > 0
    assert raw["oas"] < 1e-6                                 # OAS to straight price is <= 0


def test_putable_above_straight_and_oas_positive(s):
    res = s.price_callable_bond(1000, 0.06, 5, 2, sigma=0.15, put_price=1000, put_start=2,
                                option="putable", curve=s.market_data.flat_curve(0.07))
    raw = res["raw"]
    assert raw["putable_value"] > raw["straight_value"]     # put benefits the holder
    assert raw["oas"] > -1e-6


def test_bdt_tree_reprices_straight_bond(s):
    curve = s.market_data.flat_curve(0.07)
    cb = s.price_callable_bond(1000, 0.08, 5, 2, sigma=0.15, call_price=1000, call_start=2,
                               option="callable", curve=curve)["raw"]
    bullet = s.price_bond(1000, 0.08, 5, 2, curve=curve)["value"]
    assert cb["straight_value"] == pytest.approx(bullet, rel=0.02)   # tree ~ DCF
