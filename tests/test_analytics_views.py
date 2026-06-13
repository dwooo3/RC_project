"""
Industry-benchmark backlog P1-P4 — analytics view-models. Headless, fixture
portfolios over the real (validated) engines. No Qt, no network.
"""
import numpy as np
import pytest

from domain.portfolio import Portfolio, Position
from infra.db.market_data_db import MarketDataDB
from services import analytics_views as av
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService
from services.risk_service import RiskService


@pytest.fixture
def book():
    return Portfolio(name="T", positions=[
        Position(id="o1", instrument="call", description="call", quantity=100,
                 params=dict(S=100.0, K=105.0, T=0.5, r=0.12, sigma=0.30)),
        Position(id="b1", instrument="bond", description="OFZ", quantity=1000,
                 params=dict(face=1000, coupon=0.12, T=5, freq=2, r=0.12)),
        Position(id="e1", instrument="equity", description="EQ", quantity=2000,
                 params=dict(S=160.0)),
    ])


@pytest.fixture
def ps(book):
    return PortfolioService(book)


# ── P1 ───────────────────────────────────────────────────

def test_risk_decomposition(ps):
    d = av.risk_decomposition(ps)
    assert d["by_factor"] and d["by_bucket"] and len(d["by_position"]) == 3
    assert d["total_mv"] > 0
    # sorted by |contribution| desc and |mv| desc
    contribs = [abs(r["contribution"]) for r in d["by_factor"]]
    assert contribs == sorted(contribs, reverse=True)
    mvs = [abs(r["mv"]) for r in d["by_position"]]
    assert mvs == sorted(mvs, reverse=True)


def test_what_if_sign_and_pct(ps):
    down = av.what_if(ps, dS=-0.10)
    up = av.what_if(ps, dS=0.10)
    assert down["pnl"] < 0 < up["pnl"]                 # long-biased book
    assert "pnl_pct" in down


def test_what_if_grid(ps):
    g = av.what_if_grid(ps, [-0.1, 0.0, 0.1], [-0.02, 0.0, 0.02])
    assert len(g["pnl_grid"]) == 3 and len(g["pnl_grid"][0]) == 3
    # zero-shock centre is ~0 P&L
    assert abs(g["pnl_grid"][1][1]) < 1e-6


def test_xva_profile():
    rs = RiskService()
    x = av.xva_profile(rs, n_sims=1500, n_grid=16)
    assert x["errors"] == []
    assert x["cva"] > 0 and x["peak_pfe"] > 0
    assert len(x["epe"]) == len(x["times"]) > 0


def test_pnl_attribution_residual(ps):
    a = av.pnl_attribution(ps, dS=-0.05, dVol=0.03, dr=0.001)
    assert a["components"] and a["components"][-1]["component"] == "residual"
    assert "explained" in a and "reported" in a


def test_var_backtest_markers():
    rng = np.random.default_rng(3)
    pnl = rng.normal(0, 1e5, 250)
    var = np.full(250, 2.33e5)
    bt = av.var_backtest(pnl, var, 0.99)
    assert bt["n_obs"] == 250
    assert len(bt["exception_index"]) == bt["n_exceptions"]
    assert bt["basel_zone"] in ("Green", "Yellow", "Red")


def test_position_drilldown(ps):
    dd = av.position_drilldown(ps, None, "o1")
    assert dd["found"] and dd["id"] == "o1"
    assert "delta" in dd["greeks"] and dd["market_value"] != 0
    assert av.position_drilldown(ps, None, "missing")["found"] is False


# ── P2 ───────────────────────────────────────────────────

def _seed_history(db, names, n=120, seed=0):
    rng = np.random.default_rng(seed)
    mkt = rng.normal(0, 0.02, n)
    for i, name in enumerate(names):
        beta = 0.5 + 0.4 * i
        prices = 100 * np.exp(np.cumsum(beta * mkt + rng.normal(0, 0.01, n)))
        db.save_time_series(f"{name}:price", "price",
                            [(f"2026-{(k // 28) + 1:02d}-{(k % 28) + 1:02d}", float(p))
                             for k, p in enumerate(prices)])


def test_factor_model():
    db = MarketDataDB(":memory:")
    _seed_history(db, ["IMOEX", "A", "B"])
    mds = MarketDataService(market_db=db)
    fm = av.factor_model(mds, ["A:price", "B:price"], "IMOEX:price")
    assert fm["n_obs"] >= 30 and len(fm["factors"]) == 2
    for f in fm["factors"]:
        assert 0 <= f["r2"] <= 1 and f["beta"] != 0
        assert f["total_vol"] >= f["idio_vol"] - 1e-6   # idio <= total


def test_scenario_library(ps):
    lib = av.scenario_library(ps)
    assert len(lib["scenarios"]) == len(av.SCENARIO_LIBRARY)
    # sorted worst-first
    pnls = [s["pnl"] for s in lib["scenarios"]]
    assert pnls == sorted(pnls)
    assert lib["worst"]["pnl"] <= lib["best"]["pnl"]


def test_krd_what_if(ps):
    out = av.krd_what_if(ps, {"2Y": 50, "5Y": 50})
    assert len(out["tenors"]) == 2


def test_liquidity_profile(ps):
    db = MarketDataDB(":memory:")
    lp = av.liquidity_profile(ps, db, "s1")
    assert 0 < lp["hhi"] <= 1
    assert lp["effective_positions"] >= 1
    assert lp["top_weights"] and lp["top_weights"][0]["weight"] >= lp["top_weights"][-1]["weight"]


# ── P3 ───────────────────────────────────────────────────

def test_risk_commentary(ps):
    c = av.risk_commentary(ps, var_value=2.5e5)
    assert "market value" in c["narrative"].lower()
    assert c["facts"]["market_value"] > 0
    assert c["facts"]["worst_scenario"] is not None


def test_risk_trend():
    db = MarketDataDB(":memory:")
    db.save_time_series("KBD:5Y", "rate", [("2026-06-08", 0.145), ("2026-06-09", 0.146)])
    t = av.risk_trend(db, "KBD:5Y")
    assert t["values"][-1] == pytest.approx(14.6)


# ── P4 ───────────────────────────────────────────────────

def test_saccr_ead():
    r = av.saccr_ead(10_000_000, 200_000, "IR", 5.0)
    assert r["ead"] == pytest.approx(1.4 * (r["replacement_cost"] + r["pfe"]))
    assert r["replacement_cost"] == 200_000          # MtM>0, no collateral
    assert r["supervisory_factor"] == 0.005          # IR
    # collateral reduces RC
    assert av.saccr_ead(1e7, 2e5, "IR", 5, collateral=1e5)["replacement_cost"] == 1e5
    # equity has a higher supervisory factor than IR
    assert av.saccr_ead(1e7, 0, "EQUITY")["addon"] > av.saccr_ead(1e7, 0, "IR")["addon"]


def test_hedge_effectiveness():
    # near-perfect inverse hedge -> effective
    item = [100, -50, 80, -30, 60]
    hedge = [-96, 48, -77, 29, -58]
    h = av.hedge_effectiveness(item, hedge)
    assert h["effective"] and 0.8 <= abs(h["dollar_offset"]) <= 1.25
    assert h["r_squared"] > 0.9
    # uncorrelated -> not effective
    bad = av.hedge_effectiveness([1, 2, 3, 4], [9, -3, 4, -8])
    assert not bad["effective"]


def test_multi_currency_consolidation():
    mc = av.multi_currency_consolidation(
        {"RUB": 1_000_000, "USD": 5_000, "CNY": 10_000},
        {"USD/RUB": 71.7, "CNY/RUB": 10.6})
    assert mc["total_base"] == pytest.approx(1_000_000 + 5_000 * 71.7 + 10_000 * 10.6)
    assert mc["base_currency"] == "RUB"
    # inverse pair resolution
    inv = av.multi_currency_consolidation({"USD": 100}, {"RUB/USD": 0.014})
    assert inv["by_currency"][0]["base_value"] == pytest.approx(100 / 0.014)
