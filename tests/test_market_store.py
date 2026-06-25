"""Continuously-accumulated market store: price_history + instrument_ref + MarketStore."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import datetime as dt

from infra.db.market_data_db import MarketDataDB
from infra.market_store import MarketStore


def test_price_history_idempotent_accumulation():
    db = MarketDataDB(":memory:")
    rows = [{"secid": "X", "market": "bonds", "dt": "2026-06-24", "close": 100.5, "volume": 10}]
    db.save_price_history(rows)
    db.save_price_history(rows)                       # re-run adds nothing
    assert len(db.get_price_history("X", "bonds")) == 1
    db.save_price_history([{"secid": "X", "market": "bonds", "dt": "2026-06-25", "close": 101.0}])
    h = db.get_price_history("X", "bonds")
    assert [r["dt"] for r in h] == ["2026-06-24", "2026-06-25"]
    assert db.price_history_max_dt("X", "bonds") == "2026-06-25"


def test_price_history_range_filter():
    db = MarketDataDB(":memory:")
    db.save_price_history([{"secid": "X", "market": "bonds", "dt": d, "close": 100.0}
                           for d in ("2026-01-01", "2026-03-01", "2026-06-01")])
    assert len(db.get_price_history("X", "bonds", frm="2026-02-15")) == 2


def test_instrument_ref_upsert_and_list():
    db = MarketDataDB(":memory:")
    db.save_instrument_ref({"secid": "X", "category": "bonds", "issuer_ru": "ОФЗ 26238", "last": 90.0})
    db.save_instrument_ref({"secid": "X", "category": "bonds", "issuer_ru": "ОФЗ 26238", "last": 91.0})
    assert db.get_instrument_ref("X")["last"] == 91.0   # latest wins
    assert [r["secid"] for r in db.list_instrument_refs("bonds")] == ["X"]


class _FakeIss:
    """ISS stub: a description block + a 3-day history block."""
    def get_blocks(self, path, params=None):
        if path.startswith("securities/"):
            return {"description": [
                {"name": "ISIN", "title": "ISIN", "value": "RU00X"},
                {"name": "SHORTNAME", "title": "Кратк.", "value": "ОФЗ 26238"},
                {"name": "TYPENAME", "title": "Тип", "value": "Государственная облигация"},
            ]}
        return {}

    def get_block_paginated(self, path, block, params=None, **kw):
        return [
            {"TRADEDATE": "2026-06-23", "CLOSE": 99.0, "VOLUME": 5, "YIELDCLOSE": 15.0},
            {"TRADEDATE": "2026-06-24", "CLOSE": 100.0, "VOLUME": 7, "YIELDCLOSE": 14.9},
        ]


class _FakeForts:
    """FORTS stub: 3 Si contracts (2 live, 1 expired) + description + history."""
    def get_blocks(self, path, params=None):
        if path == "engines/futures/markets/forts/securities":
            return {"securities": [
                {"SECID": "SiU9", "SHORTNAME": "Si-9.99", "ASSETCODE": "Si",
                 "LASTTRADEDATE": "2099-09-17", "PREVSETTLEPRICE": 76000},
                {"SECID": "SiZ9", "SHORTNAME": "Si-12.99", "ASSETCODE": "Si",
                 "LASTTRADEDATE": "2099-12-17", "PREVSETTLEPRICE": 78000},
                {"SECID": "SiM0", "SHORTNAME": "Si-6.20", "ASSETCODE": "Si",
                 "LASTTRADEDATE": "2020-06-01", "PREVSETTLEPRICE": 60000},
            ], "marketdata": [
                {"SECID": "SiU9", "LAST": 76373, "OPENPOSITION": 11_000_000},
                {"SECID": "SiZ9", "LAST": 78140, "OPENPOSITION": 2_000_000},
                {"SECID": "SiM0", "LAST": None, "OPENPOSITION": 0},
            ]}
        if path.startswith("securities/"):
            return {"description": [{"name": "SHORTNAME", "title": "x", "value": "Si-9.99"},
                                    {"name": "ASSETCODE", "title": "x", "value": "Si"},
                                    {"name": "TYPENAME", "title": "x", "value": "Фьючерс"}]}
        return {}

    def get_block_paginated(self, path, block, params=None, **kw):
        return [{"TRADEDATE": "2026-06-24", "CLOSE": 76373, "VOLUME": 1000}]


def test_preload_futures_active_and_chain():
    db = MarketDataDB(":memory:")
    summ = MarketStore(db, _FakeForts()).preload_futures(years=1)
    assert summ["assets"] == 1 and summ["contracts"] == 3
    actives = db.list_instrument_refs("futures", active_only=True)
    assert [a["secid"] for a in actives] == ["SiU9"]      # live + max OI
    assert len(db.futures_chain("Si")) == 3               # full chain in card
    assert len(db.get_price_history("SiU9", "forts")) == 1  # history only for active
    assert db.get_price_history("SiM0", "forts") == []


def test_market_store_preload_bond_idempotent():
    db = MarketDataDB(":memory:")
    st = MarketStore(db, _FakeIss())
    today = dt.date(2026, 6, 24)
    n1 = st.preload_bond("SU26238RMFS4", "TQOB", years=1, today=today)
    assert n1 == 2
    ref = db.get_instrument_ref("SU26238RMFS4")
    assert ref["issuer_ru"] == "ОФЗ 26238"
    assert ref["last"] == 100.0
    assert abs(ref["change_pct"] - (100.0 - 99.0) / 99.0 * 100) < 1e-9
    n2 = st.preload_bond("SU26238RMFS4", "TQOB", years=1, today=today)
    assert n2 == 0                                    # append-missing: nothing new
