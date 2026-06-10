"""
Phase 4 — platform: persistence (AppDB), full-reprice VaR, exposure/CVA.
"""
import numpy as np
import pytest

from domain.portfolio import Portfolio, Position
from infra.db.app_db import AppDB
from services.audit_service import AuditService
from services.portfolio_service import PortfolioService
from services.risk_service import RiskService


@pytest.fixture()
def db():
    return AppDB(":memory:")


def _sample_portfolio() -> Portfolio:
    return Portfolio(
        name="Test Book",
        positions=[
            Position(id="p1", instrument="call", description="SBER call",
                     quantity=10,
                     params=dict(S=100.0, K=105.0, T=1.0, r=0.10, sigma=0.30)),
            Position(id="p2", instrument="bond", description="OFZ 5y",
                     quantity=100,
                     params=dict(face=1000.0, coupon=0.12, T=5.0, freq=2, r=0.12)),
            Position(id="p3", instrument="equity", description="GAZP",
                     quantity=1000, params=dict(S=160.0)),
        ],
    )


# ── Persistence ──────────────────────────────────────────

def test_portfolio_round_trip(db):
    svc = PortfolioService(_sample_portfolio())
    pid = svc.save_to_db(db)
    loaded = PortfolioService.load_from_db(db, pid)
    assert loaded.portfolio.name == "Test Book"
    assert len(loaded.positions) == 3
    by_id = {p.id: p for p in loaded.positions}
    assert by_id["p1"].params["K"] == 105.0
    assert by_id["p2"].quantity == 100
    assert by_id["p1"].type.value == "option"
    # loaded book reprices identically to the original
    v0 = svc.price_all().total_market_value
    v1 = loaded.price_all().total_market_value
    assert v1 == pytest.approx(v0, rel=1e-12)


def test_portfolio_update_and_listing(db):
    svc = PortfolioService(_sample_portfolio())
    svc.save_to_db(db)
    svc.remove("p3")
    svc.save_to_db(db)                       # upsert replaces the position set
    loaded = PortfolioService.load_from_db(db, svc.portfolio.portfolio_id)
    assert len(loaded.positions) == 2
    listing = db.list_portfolios()
    assert listing[0]["n_positions"] == 2
    db.delete_portfolio(svc.portfolio.portfolio_id)
    assert db.list_portfolios() == []
    with pytest.raises(KeyError):
        db.load_portfolio("missing")


def test_audit_records_persist(db):
    audit = AuditService(db=db)
    audit.record_calculation(
        user_action="test", calculation_type="pricing", model_id="black_scholes",
        model_version="1.0", inputs={"S": 100}, result_id="r1")
    audit.record_calculation(
        user_action="test2", calculation_type="risk", model_id="var_historical",
        model_version="1.0", inputs={"n": 250}, result_id="r2")
    assert db.audit_count() == 2
    rows = db.load_audit_records(calculation_type="pricing")
    assert len(rows) == 1 and rows[0]["model_id"] == "black_scholes"
    assert rows[0]["inputs_hash"] == audit.records[0].inputs_hash


def test_governed_pricing_lands_in_audit_db(db):
    from services.pricing_service import PricingService
    audit = AuditService(db=db)
    svc = PricingService(audit=audit)
    svc.price_vanilla_option(100, 100, 1.0, 0.05, 0.2)
    assert db.audit_count() >= 1
    rows = db.load_audit_records(model_id="black_scholes")
    assert rows and rows[0]["calculation_type"] == "vanilla_option_pricing"


# ── Full-reprice VaR ─────────────────────────────────────

@pytest.fixture(scope="module")
def factor_history():
    rng = np.random.default_rng(7)
    n = 120
    return dict(
        eq=rng.normal(0.0, 0.02, n),          # daily equity returns
        ir=rng.normal(0.0, 0.0015, n),        # daily absolute rate moves
        vol=rng.normal(0.0, 0.01, n),         # daily vol-point moves
    )


def test_full_reprice_var_linear_position(factor_history):
    """A pure equity position is linear: full-reprice VaR == historical VaR."""
    book = Portfolio(name="EQ", positions=[
        Position(id="e1", instrument="equity", description="idx", quantity=1000,
                 params=dict(S=100.0))])
    ps = PortfolioService(book)
    rs = RiskService(market_data=ps.market_data, audit=ps.audit)
    res = rs.full_reprice_var(ps, factor_history["eq"], factor_history["ir"],
                              factor_history["vol"], confidence=0.99)
    assert res["errors"] == []
    base = 1000 * 100.0
    expected = float(np.quantile(-(base * factor_history["eq"]), 0.99))
    assert res["value"] == pytest.approx(expected, rel=1e-9)


def test_full_reprice_var_option_convexity(factor_history):
    """Long call convexity: full-reprice 99% VaR is BELOW the delta-linear VaR."""
    book = Portfolio(name="OPT", positions=[
        Position(id="o1", instrument="call", description="call", quantity=100,
                 params=dict(S=100.0, K=100.0, T=1.0, r=0.10, sigma=0.30))])
    ps = PortfolioService(book)
    rs = RiskService(market_data=ps.market_data, audit=ps.audit)
    res = rs.full_reprice_var(ps, factor_history["eq"],
                              np.zeros_like(factor_history["eq"]),
                              confidence=0.99)
    assert res["errors"] == []
    # delta-linear comparison
    ps.price_all()
    delta = ps.positions[0].delta
    linear_var = float(np.quantile(-(delta * 100.0 * factor_history["eq"]), 0.99))
    assert res["value"] < linear_var          # gamma cushions the downside
    assert res["raw"]["expected_shortfall"] >= res["value"]


def test_full_reprice_var_governed_failure():
    rs = RiskService()
    ps = PortfolioService(Portfolio(name="empty"))
    res = rs.full_reprice_var(ps, [0.01] * 10, [0.0] * 10)   # too few scenarios
    assert res["errors"]


# ── Exposure / CVA ───────────────────────────────────────

def test_irs_exposure_profile_shape():
    from curves.yield_curve import YieldCurve
    from risk.exposure import irs_exposure_profile
    curve = YieldCurve.flat(0.10)
    par = curve.par_rate(5.0, 4)
    prof = irs_exposure_profile(1_000_000, par, 5.0, 4, curve,
                                n_sims=2000, n_grid=20, seed=5)
    epe, times = prof["epe"], prof["times"]
    assert epe[0] == pytest.approx(0.0, abs=1e-6)        # par swap starts at zero
    assert epe.max() > 0                                  # exposure builds up
    assert epe[-1] == pytest.approx(0.0, abs=1e-6)        # nothing left at maturity
    assert np.argmax(epe) < len(epe) - 1                  # humped, not monotone
    assert np.all(prof["pfe95"] >= epe - 1e-9)            # PFE dominates EPE
    assert np.all(prof["pfe99"] >= prof["pfe95"] - 1e-9)
    # payer/receiver mirror: EPE_payer ≈ -ENE_receiver on the same seed
    rec = irs_exposure_profile(1_000_000, par, 5.0, 4, curve,
                               pay_fixed=False, n_sims=2000, n_grid=20, seed=5)
    assert prof["epe"][5] == pytest.approx(-rec["ene"][5], rel=1e-9)


def test_fx_forward_exposure_profile():
    from risk.exposure import fx_forward_exposure_profile
    prof = fx_forward_exposure_profile(90.0, 90.0 * np.exp(0.11 * 1.0), 1.0,
                                       0.16, 0.05, 0.18, n_sims=4000, n_grid=12)
    assert prof["epe"].max() > 0
    assert np.all(prof["pfe95"] >= prof["epe"] - 1e-9)


def test_cva_properties():
    from curves.hazard import HazardCurve
    from curves.yield_curve import YieldCurve
    from risk.exposure import cva_from_profile, irs_exposure_profile
    curve = YieldCurve.flat(0.10)
    par = curve.par_rate(5.0, 4)
    prof = irs_exposure_profile(1_000_000, par, 5.0, 4, curve,
                                n_sims=2000, n_grid=20, seed=5)
    lo = cva_from_profile(prof["times"], prof["epe"],
                          HazardCurve.flat(0.01, recovery=0.4), curve)
    hi = cva_from_profile(prof["times"], prof["epe"],
                          HazardCurve.flat(0.05, recovery=0.4), curve)
    assert 0 < lo["cva"] < hi["cva"]                       # increasing in hazard
    rec_hi = cva_from_profile(prof["times"], prof["epe"],
                              HazardCurve.flat(0.05, recovery=0.8), curve)
    assert rec_hi["cva"] < hi["cva"]                       # decreasing in recovery
    both = cva_from_profile(prof["times"], prof["epe"],
                            HazardCurve.flat(0.05, recovery=0.4), curve,
                            ene=prof["ene"],
                            own_hazard_curve=HazardCurve.flat(0.05, recovery=0.4))
    assert both["dva"] > 0 and both["bcva"] == pytest.approx(
        both["cva"] - both["dva"])


def test_cva_irs_service_route():
    rs = RiskService()
    res = rs.cva_irs(1_000_000, 0.13, 5.0, 4, n_sims=1500, n_grid=16)
    assert res["errors"] == []
    assert res["model_id"] == "cva_exposure"
    assert res["value"] > 0
    assert res["raw"]["pd_horizon"] > 0
    # HY counterparty carries more CVA than 1st tier
    hy = rs.cva_irs(1_000_000, 0.13, 5.0, 4, hazard_id="hazard_hy_demo",
                    n_sims=1500, n_grid=16)
    assert hy["value"] > res["value"]
