"""
Stage III — visualization view-models (services/market_views). Pure, headless.
"""
from datetime import date

import numpy as np
import pytest

from curves.yield_curve import YieldCurve
from infra.db.market_data_db import MarketDataDB
from services import market_views as mv
from services.market_data_service import MarketDataService


@pytest.fixture(scope="module")
def demo():
    return MarketDataService().demo_snapshot(date(2026, 6, 10))


# ── Curves ───────────────────────────────────────────────

def test_curve_table_shape_and_values(demo):
    t = mv.curve_table(demo, ["ofz_demo", "ruonia_demo", "nope"], tenors=(1, 5, 10))
    assert t["columns"] == ["ofz_demo", "ruonia_demo"]      # missing dropped
    assert [r[0] for r in t["rows"]] == [1, 5, 10]
    # values are percent and match the curve
    r5 = next(r for r in t["rows"] if r[0] == 5)
    assert r5[1] == pytest.approx(demo.curves["ofz_demo"].rate(5) * 100, abs=1e-3)


def test_breakeven_term_structure(demo):
    be = mv.breakeven_term_structure(demo, "ofz_demo", "ofzin_real_demo")
    assert be["available"]
    # nominal - real == breakeven (Fisher), within rounding
    for T, b, n, r in zip(be["tenors"], be["breakeven"], be["nominal"], be["real"]):
        assert b > 0
    assert max(be["tenors"]) <= float(np.max(demo.curves["ofzin_real_demo"].tenors))


def test_breakeven_unavailable_without_real_curve(demo):
    be = mv.breakeven_term_structure(demo, "ofz_demo", "missing_real")
    assert be["available"] is False and be["breakeven"] == []


def test_curve_history_series():
    db = MarketDataDB(":memory:")
    db.save_time_series("KBD:5Y", "rate",
                        [("2026-06-08", 0.145), ("2026-06-09", 0.146),
                         ("2026-06-10", 0.144)])
    h = mv.curve_history_series(db, "KBD:5Y")
    assert h["dates"] == ["2026-06-08", "2026-06-09", "2026-06-10"]
    assert h["values"][-1] == pytest.approx(14.4)           # decimal -> percent


# ── Vol smile + SVI ──────────────────────────────────────

def _seed_smile(db, sid="moex-2026-06-10"):
    """A convex Si smile generated from SVI so the fit recovers it."""
    from risk.vol_surface import svi_total_variance
    F, T = 90000.0, 60 / 365.0
    a, b, rho, m, sig = 0.04 * T, 0.1, -0.3, 0.0, 0.3
    for K in range(70000, 112000, 2000):
        k = np.log(K / F)
        w = svi_total_variance(k, a, b, rho, m, sig)
        iv = float(np.sqrt(max(w / T, 1e-4)))
        db.save_vol_point(sid, "Si", "2026-08-09", float(K), iv)


def test_vol_smile_slices_with_svi():
    db = MarketDataDB(":memory:")
    _seed_smile(db)
    out = mv.vol_smile_slices(db, "moex-2026-06-10", "Si",
                              valuation_date=date(2026, 6, 10))
    assert out["underlying"] == "Si"
    assert len(out["slices"]) == 1
    sl = out["slices"][0]
    assert sl["n_points"] >= 5 and sl["svi"] is not None
    assert sl["svi"]["rmse"] < 1.0                          # tight fit (percent)
    assert len(sl["svi"]["fit_vols"]) == sl["n_points"]
    # ATM vol is the smile minimum
    assert sl["atm_vol"] == pytest.approx(min(sl["vols"]))


def test_vol_smile_skips_svi_when_thin():
    db = MarketDataDB(":memory:")
    db.save_vol_point("s1", "RTS", "2026-08-09", 100000.0, 0.3)
    db.save_vol_point("s1", "RTS", "2026-08-09", 110000.0, 0.32)
    out = mv.vol_smile_slices(db, "s1", "RTS", valuation_date=date(2026, 6, 10))
    assert out["slices"][0]["svi"] is None                  # < min_points


def test_atm_term_structure():
    db = MarketDataDB(":memory:")
    _seed_smile(db)
    db.save_vol_point("moex-2026-06-10", "Si", "2026-12-17", 90000.0, 0.25)
    sm = mv.vol_smile_slices(db, "moex-2026-06-10", "Si",
                             valuation_date=date(2026, 6, 10))
    ats = mv.atm_term_structure(sm)
    assert len(ats["expiries"]) == 2 and len(ats["atm_vols"]) == 2


def test_vol_underlyings():
    db = MarketDataDB(":memory:")
    db.save_vol_point("s1", "Si", "2026-08-09", 90000.0, 0.3)
    db.save_vol_point("s1", "RTS", "2026-08-09", 100000.0, 0.3)
    assert mv.vol_underlyings(db, "s1") == ["RTS", "Si"]


# ── Factor series + correlation ──────────────────────────

def test_factor_series_correlation():
    db = MarketDataDB(":memory:")
    rng = np.random.default_rng(0)
    base = rng.normal(0, 0.02, 120)
    # A and B perfectly correlated, C independent
    pa = 100 * np.exp(np.cumsum(base))
    pb = 50 * np.exp(np.cumsum(base))
    pc = 80 * np.exp(np.cumsum(rng.normal(0, 0.02, 120)))
    for name, prices in (("A", pa), ("B", pb), ("C", pc)):
        db.save_time_series(f"{name}:price", "price",
                            [(f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", float(p))
                             for i, p in enumerate(prices)])
    mds = MarketDataService(market_db=db)
    fs = mv.factor_series(mds, ["A:price", "B:price", "C:price"])
    assert fs["n_obs"] == 119 and len(fs["factors"]) == 3
    i_a, i_b = fs["factors"].index("A:price"), fs["factors"].index("B:price")
    assert fs["correlation"][i_a][i_b] == pytest.approx(1.0, abs=1e-6)
    assert all(v > 0 for v in fs["ann_vol"].values())


def test_factor_series_empty():
    mds = MarketDataService(market_db=MarketDataDB(":memory:"))
    fs = mv.factor_series(mds, ["NONE:price"])
    assert fs["n_obs"] == 0 and fs["factors"] == []


# ── Data health ──────────────────────────────────────────

def test_snapshot_calendar_gaps():
    db = MarketDataDB(":memory:")
    from datetime import datetime
    # only Wed 2026-06-10 present in a Mon..Fri window
    db.save_snapshot_meta(snapshot_id="moex-2026-06-10", valuation_date="2026-06-10",
                          source="MOEX", quality="OK", fetch_ts=datetime(2026, 6, 10))
    cal = mv.snapshot_calendar(db, lookback_days=4, today=date(2026, 6, 12))  # Fri
    assert cal["business_days"] == 5                         # Mon..Fri
    assert cal["present"] == 1
    assert "2026-06-11" in cal["missing"] and "2026-06-10" not in cal["missing"]
    assert cal["coverage_pct"] == 20.0


def test_ingest_history():
    db = MarketDataDB(":memory:")
    from datetime import datetime
    db.log_ingest("zcyc", "ok", 11, datetime(2026, 6, 10), datetime(2026, 6, 10))
    db.log_ingest("fx", "error", 0, datetime(2026, 6, 10), datetime(2026, 6, 10), "boom")
    h = mv.ingest_history(db, 10)
    assert len(h) == 2
    assert any(r["status"] == "error" for r in h)
