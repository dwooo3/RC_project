"""CBR client + ingestion (Phase D) — key rate & RUONIA, fixtures only."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from datetime import date

import pytest

from infra.cbr.client import CbrClient, parse_rate_records
from infra.cbr.ingest import CbrIngestor
from infra.db.market_data_db import MarketDataDB
from services.market_data_service import MarketDataService

VAL = date(2026, 6, 2)


def test_parse_rate_records_json_percent_to_decimal():
    payload = json.dumps([{"date": "2026-06-02", "value": "21,00"},
                          {"date": "2026-06-01", "value": 21.0}])
    recs = parse_rate_records(payload)
    assert ("2026-06-02", 0.21) in recs
    assert all(0 < v < 1 for _, v in recs)


def test_parse_rate_records_xml():
    xml = ('<Record date="2026-06-02"><Ruonia>15,30</Ruonia></Record>'
           '<Record date="2026-06-01"><Ruonia>15,25</Ruonia></Record>')
    recs = parse_rate_records(xml)
    assert any(d == "2026-06-02" and abs(v - 0.153) < 1e-9 for d, v in recs)


def _client(records):
    return CbrClient(fetch=lambda url: json.dumps(
        [{"date": d, "value": v * 100} for d, v in records]))


def test_ingest_key_rate_curve_and_series():
    db = MarketDataDB(":memory:")
    sid = "moex-2026-06-02"
    client = _client([("2026-06-02", 0.21), ("2026-06-01", 0.21)])
    n = CbrIngestor(client, db).ingest_key_rate(sid, VAL)
    assert n == 2
    assert "KEYRATE_RUB" in db.list_curve_ids(sid)
    pts = db.get_curve_points(sid, "KEYRATE_RUB")
    assert all(abs(p["zero_rate"] - 0.21) < 1e-9 for p in pts)        # flat
    dfs = [p["discount_factor"] for p in pts]
    assert all(b < a for a, b in zip(dfs, dfs[1:]))                    # valid DFs
    assert db.get_time_series("CBR_KEYRATE:rate", "rate")


def test_ingest_ruonia_curve():
    db = MarketDataDB(":memory:")
    sid = "moex-2026-06-02"
    client = _client([("2026-06-02", 0.153)])
    CbrIngestor(client, db).ingest_ruonia(sid, VAL)
    assert "RUONIA_RUB" in db.list_curve_ids(sid)
    meta = db.get_curve(sid, "RUONIA_RUB")
    assert meta["method"] == "cbr_flat"


def test_cbr_curves_appear_in_moex_snapshot():
    db = MarketDataDB(":memory:")
    sid = "moex-2026-06-02"
    # minimum for an OK-ish snapshot: a govt curve + fx, plus CBR curves
    db.save_curve(sid, "GCURVE_RUB", method="points", nss_params={}, as_of=VAL,
                  points=[(0.5, 0.15, None), (1, 0.148, None), (2, 0.145, None),
                          (5, 0.138, None), (10, 0.132, None)])
    db.save_fx_rate(sid, "USD/RUB", 74.36)
    CbrIngestor(_client([("2026-06-02", 0.21)]), db).ingest_key_rate(sid, VAL)
    CbrIngestor(_client([("2026-06-02", 0.153)]), db).ingest_ruonia(sid, VAL)
    snap = MarketDataService(market_db=db).moex_snapshot(VAL)
    assert "KEYRATE_RUB" in snap.curves
    assert "RUONIA_RUB" in snap.curves
    assert snap.curves["KEYRATE_RUB"].rate(1.0) == pytest.approx(0.21, abs=1e-6)
