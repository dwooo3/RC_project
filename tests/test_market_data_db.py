"""Local SQLite market-data DB — schema, writes/reads, snapshot round-trip."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, datetime

import pytest

from infra.db.market_data_db import MarketDataDB


@pytest.fixture
def db():
    d = MarketDataDB(":memory:")
    yield d
    d.close()


def test_schema_has_all_spec_tables(db):
    rows = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    for t in ("instruments", "market_data_snapshots", "yield_curves", "curve_points",
              "fx_rates", "bond_quotes", "equity_quotes", "index_values",
              "time_series", "vol_points", "ingest_log"):
        assert t in names


def test_snapshot_meta_roundtrip(db):
    db.save_snapshot_meta(
        snapshot_id="moex-2026-06-04", valuation_date=date(2026, 6, 4),
        source="MOEX", quality="OK", fetch_ts=datetime(2026, 6, 4, 18, 0, 0),
        iss_request_urls=["https://iss.moex.com/iss/engines/stock/zcyc.json"],
        metadata={"warning": ""},
    )
    meta = db.get_snapshot_meta("moex-2026-06-04")
    assert meta["source"] == "MOEX" and meta["quality"] == "OK"
    assert "zcyc" in meta["iss_request_urls"]


def test_curve_and_points_roundtrip(db):
    sid = "moex-2026-06-04"
    db.save_curve(sid, "GCURVE_RUB", method="nss",
                  nss_params={"B1": 8.0, "B2": -1.0, "B3": 2.0, "T1": 3.0},
                  as_of=date(2026, 6, 4),
                  points=[(0.25, 0.155, 0.96), (1.0, 0.145, 0.865), (5.0, 0.127, 0.53)])
    assert db.list_curve_ids(sid) == ["GCURVE_RUB"]
    pts = db.get_curve_points(sid, "GCURVE_RUB")
    assert [p["tenor"] for p in pts] == [0.25, 1.0, 5.0]
    assert pts[0]["zero_rate"] == pytest.approx(0.155)
    curve = db.get_curve(sid, "GCURVE_RUB")
    assert curve["method"] == "nss"


def test_fx_and_bond_and_timeseries_roundtrip(db):
    sid = "moex-2026-06-04"
    db.save_fx_rate(sid, "USD/RUB", 74.366, source="MOEX", trade_time="15:29:59")
    db.save_fx_rate(sid, "EUR/RUB", 86.2712, source="CBR")
    assert db.get_fx_rates(sid) == {"USD/RUB": pytest.approx(74.366), "EUR/RUB": pytest.approx(86.2712)}

    db.save_instrument({"secid": "SU26240RMFS0", "board": "TQOB", "type": "ofz",
                        "currency": "RUB", "facevalue": 1000.0, "coupon_percent": 6.9,
                        "coupon_period": 182, "mat_date": "2036-07-30"})
    db.save_bond_quote(sid, {"secid": "SU26240RMFS0", "clean_price": 78.5,
                             "accruedint": 12.3, "ytm": 0.142, "volume": 1e6, "board": "TQOB"})
    quotes = db.get_bond_quotes(sid)
    assert quotes[0]["secid"] == "SU26240RMFS0" and quotes[0]["ytm"] == pytest.approx(0.142)

    db.save_time_series("IMOEX", "price", [("2026-06-02", 3200.0), ("2026-06-03", 3215.0)])
    ts = db.get_time_series("IMOEX", "price")
    assert [p["value"] for p in ts] == [3200.0, 3215.0]


def test_ingest_log(db):
    db.log_ingest("engines/stock/zcyc", "ok", 11,
                  datetime(2026, 6, 4, 18, 0, 0), datetime(2026, 6, 4, 18, 0, 1))
    row = db.conn.execute("SELECT endpoint, status, rows FROM ingest_log").fetchone()
    assert row["status"] == "ok" and row["rows"] == 11
