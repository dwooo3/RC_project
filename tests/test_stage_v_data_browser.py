"""
Stage V.4 + Data Browser: commodity/dividend ingest and the dataset catalogue
that backs the spreadsheet-style Market Data browser. Fixture-based, no network.
"""
from datetime import date

import pytest

from infra.db.market_data_db import MarketDataDB
from services.market_data_service import MarketDataService
from services import market_views as mv


# ── Commodity futures ingest ─────────────────────────────

class _FakeIss:
    def __init__(self, blocks):
        self.blocks = blocks

    def get_blocks(self, path, params=None):
        for k, v in self.blocks.items():
            if k in path:
                return v
        return {}


def test_ingest_commodity_futures():
    from infra.moex_iss.ingest import MoexIngestor
    db = MarketDataDB(":memory:")
    iss = _FakeIss({"forts/securities": {
        "securities": [
            {"SECID": "BRN6", "ASSETCODE": "BR", "LASTTRADEDATE": "2026-07-01",
             "PREVSETTLEPRICE": 86.82, "PREVOPENPOSITION": 747680},
            {"SECID": "GDM6", "ASSETCODE": "GOLD", "LASTTRADEDATE": "2026-06-30",
             "PREVSETTLEPRICE": 4212.4},
            {"SECID": "SiM6", "ASSETCODE": "Si", "LASTTRADEDATE": "2026-06-19",
             "PREVSETTLEPRICE": 73000},          # FX, not commodity -> skipped
        ],
        "marketdata": []}})
    n = MoexIngestor(iss, db).ingest_commodity_futures("s1", date(2026, 6, 13))
    assert n == 2
    cq = db.get_commodity_quotes("s1")
    assert {r["asset"] for r in cq} == {"BR", "GOLD"}
    br = db.get_commodity_quotes("s1", "BR")[0]
    assert br["settle"] == pytest.approx(86.82)
    assert br["open_interest"] == pytest.approx(747680)


def test_ingest_dividends():
    from infra.moex_iss.ingest import MoexIngestor
    db = MarketDataDB(":memory:")
    iss = _FakeIss({"dividends": {"dividends": [
        {"registryclosedate": "2024-07-10", "value": 33.3, "currencyid": "RUB"},
        {"registryclosedate": "2025-07-18", "value": 34.84, "currencyid": "RUB"}]}})
    n = MoexIngestor(iss, db).ingest_dividends(["SBER"])
    assert n == 1
    d = db.get_dividends("SBER")
    assert len(d) == 2 and d[-1]["value"] == pytest.approx(34.84)


def test_commodity_dividend_persistence_roundtrip():
    db = MarketDataDB(":memory:")
    db.save_commodity_quotes("s1", [{"asset": "NG", "secid": "NGM6",
                                     "expiry": "2026-07-01", "settle": 3.1,
                                     "open_interest": 1000, "volume": 50}])
    assert db.get_commodity_quotes("s1", "NG")[0]["settle"] == pytest.approx(3.1)
    db.save_dividends("LKOH", [{"registry_date": "2025-06-03", "value": 541.0,
                               "currency": "RUB"}])
    assert db.get_dividends("LKOH")[0]["value"] == pytest.approx(541.0)


# ── Dataset catalogue / table (Data Browser) ─────────────

def _seeded_db(sid="demo-2026-06-13"):
    db = MarketDataDB(":memory:")
    db.save_bond_quote(sid, {"secid": "SU26238RMFS4", "clean_price": 60.0,
                             "ytm": 0.15, "volume": 1e6, "board": "TQOB"})
    db.save_equity_quote(sid, {"secid": "SBER", "last": 322.4, "prevprice": 321.2,
                               "board": "TQBR", "volume": 5e8})
    db.save_commodity_quotes(sid, [{"asset": "BR", "secid": "BRN6",
                                    "expiry": "2026-07-01", "settle": 86.82,
                                    "open_interest": 747680, "volume": 1e5}])
    db.save_dividends("SBER", [{"registry_date": "2025-07-18", "value": 34.84,
                               "currency": "RUB"}])
    db.save_vol_point(sid, "Si", "2026-08-09", 90000.0, 0.4)
    db.save_time_series("SBER:price", "price", [("2026-06-10", 322.0)])
    return db, sid


@pytest.fixture(scope="module")
def demo():
    return MarketDataService().demo_snapshot(date(2026, 6, 13))


def test_dataset_catalog_lists_nonempty(demo):
    db, _ = _seeded_db()
    cat = mv.dataset_catalog(db, demo)
    keys = {d["key"] for d in cat}
    assert {"curves", "fx", "bonds", "equities", "commodity",
            "dividends", "vol", "history"} <= keys
    counts = {d["key"]: d["count"] for d in cat}
    assert counts["bonds"] == 1 and counts["commodity"] == 1
    assert all(d["count"] > 0 for d in cat)             # no empty sheets listed


def test_dataset_catalog_demo_without_db(demo):
    cat = mv.dataset_catalog(None, demo)
    keys = {d["key"] for d in cat}
    assert "curves" in keys and "fx" in keys            # snapshot-only datasets
    assert "bonds" not in keys                          # needs a DB


def test_dataset_table_each_key(demo):
    db, _ = _seeded_db()
    for d in mv.dataset_catalog(db, demo):
        t = mv.dataset_table(db, demo, d["key"])
        assert t["columns"] and isinstance(t["rows"], list)
        assert t["title"]
        # every row matches the column count
        for row in t["rows"]:
            assert len(row) == len(t["columns"])


def test_dataset_table_commodity_content(demo):
    db, _ = _seeded_db()
    t = mv.dataset_table(db, demo, "commodity")
    assert t["columns"] == ["Asset", "Expiry", "Settle", "Open Interest"]
    assert t["rows"][0][0] == "BR"
    assert "86.82" in t["rows"][0][2]


def test_dataset_table_equities_change_pct(demo):
    db, _ = _seeded_db()
    t = mv.dataset_table(db, demo, "equities")
    sber = next(r for r in t["rows"] if r[0] == "SBER")
    assert "+0.37%" in sber[3]                          # (322.4/321.2 - 1)


def test_dataset_table_unknown_key(demo):
    t = mv.dataset_table(None, demo, "nonsense")
    assert t["rows"] == [] and t["columns"] == []
