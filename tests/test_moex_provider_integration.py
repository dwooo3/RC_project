"""End-to-end: ingest -> MarketDataService MOEX snapshot -> pricing + gating + fallback."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pytest

from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.ingest import MoexIngestor
from services.market_data_service import MarketDataService
from instruments.fixed_income import fixed_bond

VAL = date(2026, 6, 4)

ZCYC = {
    "yearyields": [
        {"tradedate": "2026-06-04", "period": 0.25, "value": 15.5},
        {"tradedate": "2026-06-04", "period": 0.5, "value": 15.2},
        {"tradedate": "2026-06-04", "period": 1.0, "value": 14.8},
        {"tradedate": "2026-06-04", "period": 2.0, "value": 14.5},
        {"tradedate": "2026-06-04", "period": 3.0, "value": 14.2},
        {"tradedate": "2026-06-04", "period": 5.0, "value": 13.8},
        {"tradedate": "2026-06-04", "period": 10.0, "value": 13.2},
    ],
    "params": [{"tradedate": "2026-06-04", "B1": 8.0, "B2": -1.0, "B3": 2.0, "T1": 3.0}],
}
SELT = {"wap_rates": [
    {"SECID": "USDTOM_UTS", "CLOSEPRICE": 74.366, "TRADETIME": "15:29:59"},
    {"SECID": "EURRUB_TOM", "LAST": 86.27},
]}
BONDS = {"securities": [{"SECID": "SU26240RMFS0", "COUPONPERCENT": 6.9, "MATDATE": "2036-07-30",
                         "FACEVALUE": 1000.0, "ACCRUEDINT": 12.3, "YIELDATPREVWAPRICE": 14.2,
                         "PREVPRICE": 78.5, "LISTLEVEL": 1, "CURRENCYID": "SUR"}],
         "marketdata": [{"SECID": "SU26240RMFS0", "LAST": 78.6, "YIELD": 14.1, "VALTODAY": 1e6}]}


class FakeClient:
    def __init__(self, resp): self.resp = resp
    def get_blocks(self, path, params=None): return self.resp[path]


def _ingested_db(valuation_date=VAL):
    db = MarketDataDB(":memory:")
    client = FakeClient({
        "engines/stock/zcyc": ZCYC,
        "statistics/engines/currency/markets/selt/rates": SELT,
        "engines/stock/markets/bonds/boards/TQOB/securities": BONDS,
    })
    MoexIngestor(client, db).ingest_all(valuation_date)
    return db


def test_moex_snapshot_is_production_quality():
    svc = MarketDataService(market_db=_ingested_db())
    snap = svc.moex_snapshot(VAL)
    assert snap.source_value == "MOEX"
    assert snap.quality == "OK"
    assert snap.is_demo is False          # production gating: not demo/manual
    assert "GCURVE_RUB" in snap.curves
    assert snap.fx_rates["USD/RUB"] == pytest.approx(74.366)


def test_ofz_priced_on_moex_curve():
    svc = MarketDataService(market_db=_ingested_db())
    snap = svc.moex_snapshot(VAL)
    curve = svc.get_curve("GCURVE_RUB", snapshot=snap)
    res = fixed_bond(face=1000, coupon=0.069, T=10, freq=2, curve=curve)
    assert res["price"] > 0
    assert 0.0 < res["ytm"] < 0.5


def test_moex_snapshot_recorded_in_lineage_and_store():
    db = _ingested_db()
    svc = MarketDataService(market_db=db)
    snap = svc.moex_snapshot(VAL)
    lineage = svc.snapshot_lineage(snap.snapshot_id)
    assert lineage and lineage[-1]["source"] == "MOEX"
    # snapshot meta persisted to DB for reproducibility
    meta = db.get_snapshot_meta(snap.snapshot_id)
    assert meta["source"] == "MOEX" and meta["quality"] == "OK"


def test_fallback_to_demo_when_db_empty():
    svc = MarketDataService(market_db=MarketDataDB(":memory:"))
    snap = svc.moex_snapshot(VAL)
    assert snap.source_value == "DEMO"
    assert snap.is_demo is True
    assert "Not production valuation" in snap.metadata.get("warning", "")


def test_fallback_to_demo_when_no_db_configured():
    svc = MarketDataService()  # default MoexProvider has no DB
    snap = svc.moex_snapshot(VAL)
    assert snap.source_value == "DEMO"


def test_rejected_curve_falls_back_to_demo():
    db = MarketDataDB(":memory:")
    sid = f"moex-{VAL.isoformat()}"
    # rising discount factors => REJECTED by validation
    db.save_curve(sid, "GCURVE_RUB", method="points", nss_params={}, as_of=VAL,
                  points=[(1.0, 0.10, 0.90), (2.0, 0.05, 0.95), (3.0, 0.04, 0.97)])
    svc = MarketDataService(market_db=db)
    snap = svc.moex_snapshot(VAL)
    assert snap.source_value == "DEMO"  # rejected MOEX data not served as production


def test_moex_snapshot_no_fallback_raises_when_empty():
    svc = MarketDataService(market_db=MarketDataDB(":memory:"))
    with pytest.raises(Exception):
        svc.moex_snapshot(VAL, fallback_to_demo=False)
