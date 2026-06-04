"""Phase B — historical yields, spread calibration, corporate curves (fixtures)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pytest

from curves.yield_curve import YieldCurve
from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.ingest import MoexIngestor
from infra.moex_iss.calibration import (
    bond_tenor, tier_for, issuer_spreads, build_corporate_curve_points,
    representative_spread,
)
from services.market_data_service import MarketDataService
from instruments.fixed_income import fixed_bond

VAL = date(2026, 6, 2)


def _gcurve():
    return YieldCurve([0.5, 1, 2, 3, 5, 10],
                      [0.150, 0.148, 0.145, 0.142, 0.138, 0.132],
                      label="GCURVE_RUB", interp="cubic", rate_type="zero")


# ── calibration unit ─────────────────────────────────────

def test_bond_tenor_and_tier():
    assert bond_tenor("2028-06-02", VAL) == pytest.approx(2.0, abs=0.01)
    assert bond_tenor("2020-01-01", VAL) is None   # matured
    assert bond_tenor(None, VAL) is None
    assert tier_for(1) == "T1" and tier_for(2) == "T2" and tier_for(99) == "T3"


def test_issuer_spreads_are_ytm_minus_govt():
    g = _gcurve()
    bonds = [{"secid": "C1", "ytm": 0.165, "mat_date": "2028-06-02", "list_level": 2}]
    sp = issuer_spreads(g, bonds, VAL)[0]
    assert sp["tier"] == "T2"
    assert sp["spread"] == pytest.approx(0.165 - g.rate(sp["tenor"]), abs=1e-9)


def test_build_corporate_curve_points_requires_min_bonds():
    g = _gcurve()
    spreads = [{"secid": "C1", "tenor": 2.0, "spread": 0.02, "tier": "T2"},
               {"secid": "C2", "tenor": 3.0, "spread": 0.021, "tier": "T2"}]
    assert build_corporate_curve_points(g, spreads, "T2", min_bonds=3) == []  # only 2
    spreads.append({"secid": "C3", "tenor": 5.0, "spread": 0.022, "tier": "T2"})
    pts = build_corporate_curve_points(g, spreads, "T2", min_bonds=3)
    assert [round(t, 3) for t, _, _ in pts] == [2.0, 3.0, 5.0]
    assert pts[0][1] == pytest.approx(g.rate(2.0) + 0.02, abs=1e-9)  # govt + spread


def test_dedupe_averages_same_tenor():
    g = _gcurve()
    spreads = [{"secid": "A", "tenor": 2.0, "spread": 0.02, "tier": "T1"},
               {"secid": "B", "tenor": 2.0, "spread": 0.03, "tier": "T1"},
               {"secid": "C", "tenor": 3.0, "spread": 0.025, "tier": "T1"},
               {"secid": "D", "tenor": 5.0, "spread": 0.026, "tier": "T1"}]
    pts = build_corporate_curve_points(g, spreads, "T1", min_bonds=3)
    # 2.0 bucket averages 0.02 and 0.03 -> 0.025
    assert pts[0][1] == pytest.approx(g.rate(2.0) + 0.025, abs=1e-9)
    assert representative_spread(spreads, "T1") == pytest.approx((0.02+0.03+0.025+0.026)/4)


# ── corporate-curve ingestion from seeded DB ─────────────

def _seed_corp_db():
    db = MarketDataDB(":memory:")
    sid = MoexIngestor.snapshot_id_for(VAL)
    # government curve
    db.save_curve(sid, "GCURVE_RUB", method="points", nss_params={}, as_of=VAL,
                  points=[(0.5, 0.150, None), (1, 0.148, None), (2, 0.145, None),
                          (3, 0.142, None), (5, 0.138, None), (10, 0.132, None)])
    # three tier-2 corporate bonds with positive spreads
    corp = [("RU000C1", "2028-06-02", 0.165), ("RU000C2", "2029-06-02", 0.168),
            ("RU000C3", "2031-06-02", 0.170)]
    for secid, mat, ytm in corp:
        db.save_instrument({"secid": secid, "board": "TQCB", "type": "bond",
                            "mat_date": mat, "list_level": 2, "coupon_percent": 8.0})
        db.save_bond_quote(sid, {"secid": secid, "ytm": ytm, "volume": 1e6, "board": "TQCB"})
    return db, sid


def test_ingest_corporate_curves_builds_tier_curve():
    db, sid = _seed_corp_db()
    ing = MoexIngestor(client=None, db=db)
    n = ing.ingest_corporate_curves(sid, VAL, min_bonds=3)
    assert n == 1
    assert "CORP_T2" in db.list_curve_ids(sid)
    pts = db.get_curve_points(sid, "CORP_T2")
    assert len(pts) == 3
    # corporate zero lies above government zero at the same tenor
    g = _gcurve()
    assert pts[0]["zero_rate"] > g.rate(pts[0]["tenor"])
    meta = db.get_curve(sid, "CORP_T2")
    assert meta["method"] == "govt+spread"


def test_corporate_curve_in_moex_snapshot_and_prices_bond():
    db, sid = _seed_corp_db()
    db.save_fx_rate(sid, "USD/RUB", 74.36)  # so quality can reach OK
    MoexIngestor(client=None, db=db).ingest_corporate_curves(sid, VAL)
    svc = MarketDataService(market_db=db)
    snap = svc.moex_snapshot(VAL)
    assert snap.source_value == "MOEX"
    assert "CORP_T2" in snap.curves
    corp_curve = svc.get_curve("CORP_T2", snapshot=snap)
    res = fixed_bond(face=1000, coupon=0.08, T=5, freq=2, curve=corp_curve)
    assert res["price"] > 0


# ── historical yields ingestion ──────────────────────────

class FakeClient:
    def __init__(self, blocks): self.blocks = blocks
    def get_blocks(self, path, params=None): return self.blocks.get(path, {})
    def get_block_paginated(self, path, block, params=None, **kw):
        return self.blocks.get(path, {}).get(block, [])


def test_ingest_yield_history_writes_decimal_time_series():
    db = MarketDataDB(":memory:")
    secid = "SU26240RMFS0"
    path = f"history/engines/stock/markets/bonds/yields/{secid}"
    client = FakeClient({path: {"history": [
        {"TRADEDATE": "2026-06-02", "YIELDCLOSE": 14.20},
    ]}})
    ing = MoexIngestor(client, db)
    n = ing.ingest_yield_history(secid, VAL, VAL)
    assert n == 1
    ts = db.get_time_series(f"{secid}:yield", "yield")
    assert ts[0]["dt"] == "2026-06-02"
    assert ts[0]["value"] == pytest.approx(0.142)  # percent -> decimal


def test_ingest_yield_history_logs_error():
    db = MarketDataDB(":memory:")
    class Boom:
        def get_block_paginated(self, *a, **k): raise OSError("iss down")
    with pytest.raises(OSError):
        MoexIngestor(Boom(), db).ingest_yield_history("X", VAL, VAL)
    row = db.conn.execute("SELECT status FROM ingest_log").fetchone()
    assert row["status"] == "error"
