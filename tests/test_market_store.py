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


class _RangeIss:
    """Range-aware history stub exposing every contractual price basis."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.history_calls = []

    def get_blocks(self, path, params=None):
        if path.startswith("securities/") and not path.endswith("/dividends"):
            return {"description": [
                {"name": "SHORTNAME", "title": "Name", "value": "Test"},
            ]}
        return {}

    def get_block_paginated(self, path, block, params=None, **kw):
        params = dict(params or {})
        self.history_calls.append((params["from"], params["till"]))
        return [
            dict(row) for row in self.rows
            if params["from"] <= row["TRADEDATE"] <= params["till"]
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


class _FakeOptions:
    """Options stub: Si calls/puts at two strikes + one expired contract."""
    def get_blocks(self, path, params=None):
        if path == "engines/futures/markets/options/securities":
            base = {"ASSETCODE": "Si", "LASTTRADEDATE": "2099-09-17",
                    "CENTRALSTRIKE": 76500.0, "UNDERLYINGASSET": "SiU9"}
            return {"securities": [
                {"SECID": "SiC76", "OPTIONTYPE": "C", "STRIKE": 76000.0, **base},
                {"SECID": "SiP76", "OPTIONTYPE": "P", "STRIKE": 76000.0, **base},
                {"SECID": "SiC77", "OPTIONTYPE": "C", "STRIKE": 77000.0, **base},
                {"SECID": "SiCold", "OPTIONTYPE": "C", "STRIKE": 50000.0,
                 "ASSETCODE": "Si", "LASTTRADEDATE": "2020-01-01", "CENTRALSTRIKE": 76500.0},
            ], "marketdata": [
                {"SECID": "SiC76", "LAST": 30, "OPENPOSITION": 9814},
                {"SECID": "SiP76", "LAST": 0, "OPENPOSITION": 3128},
                {"SECID": "SiC77", "LAST": 0, "OPENPOSITION": 11866},
            ]}
        return {}


def test_preload_options_chain():
    from api.market_entity import _option_chain

    db = MarketDataDB(":memory:")
    summ = MarketStore(db, _FakeOptions()).preload_options()
    assert summ["underlyings"] == 1 and summ["options"] == 3   # expired dropped
    assert [r["secid"] for r in db.list_instrument_refs("options")] == ["Si"]
    grouped = _option_chain(db.get_option_chain("Si"))
    assert len(grouped) == 1                                   # one live expiry
    e = grouped[0]
    assert e["central_strike"] == 76500.0
    strikes = {s["strike"]: s for s in e["strikes"]}
    assert strikes[76000.0]["call"]["oi"] == 9814 and strikes[76000.0]["put"]["oi"] == 3128
    assert strikes[77000.0]["put"] is None                    # only a call at 77000


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


def _exact_history_row(day: str, close: float) -> dict:
    return {
        "SECID": "SBER",
        "BOARDID": "TQBR",
        "TRADEDATE": day,
        "CLOSE": close,
        "LEGALCLOSEPRICE": close + 0.1,
        "WAPRICE": close - 0.1,
        "VOLUME": 100.0,
    }


def test_preload_backfills_empty_exact_fixings_behind_existing_price_history():
    db = MarketDataDB(":memory:")
    today = dt.date(2026, 7, 22)
    target = "2025-07-22"
    db.save_price_history([{
        "secid": "SBER", "market": "shares", "dt": today.isoformat(),
        "close": 110.0,
    }])
    iss = _RangeIss([
        _exact_history_row(target, 90.0),
        _exact_history_row("2026-01-15", 100.0),
        _exact_history_row(today.isoformat(), 110.0),
    ])

    # No forward price-history append is needed, but the independent exact
    # fixing cursor must still trigger a full-depth operational backfill.
    added = MarketStore(db, iss).preload_equity(
        "SBER", "TQBR", years=1, today=today)

    assert added == 0
    assert iss.history_calls == [(target, today.isoformat())]
    coverage = db.contract_fixing_coverage(
        "SBER:price", source="MOEX", board="TQBR", session="")
    assert coverage["first_date"] == target
    assert coverage["last_date"] == today.isoformat()
    assert coverage["date_count"] == 3
    legal = db.get_contract_fixings_window(
        "SBER:price", target, today,
        price_basis="LEGALCLOSEPRICE", source="MOEX", board="TQBR",
    )
    assert [row["observed_date"] for row in legal] == [
        target, "2026-01-15", today.isoformat(),
    ]
    assert db.price_history_min_dt("SBER", "shares") == target

    # Exact boundary coverage is an independent idempotent cursor: a repeat
    # preload does not download the already governed range again.
    iss.history_calls.clear()
    assert MarketStore(db, iss).preload_equity(
        "SBER", "TQBR", years=1, today=today) == 0
    assert iss.history_calls == []


def test_preload_backfills_only_missing_old_exact_fixing_range():
    db = MarketDataDB(":memory:")
    today = dt.date(2026, 7, 22)
    target = "2025-07-22"
    db.save_price_history([{
        "secid": "SBER", "market": "shares", "dt": today.isoformat(),
        "close": 110.0,
    }])
    iss = _RangeIss([
        _exact_history_row(target, 90.0),
        _exact_history_row("2026-01-15", 100.0),
        _exact_history_row(today.isoformat(), 110.0),
    ])
    store = MarketStore(db, iss)
    # Simulate recent rows written by append_daily after contract_fixings was
    # introduced, while the older price_history predates the immutable ledger.
    assert store._save_contract_fixings([
        _exact_history_row(today.isoformat(), 110.0)
    ]) == 3
    iss.history_calls.clear()

    added_dates = store.backfill_contract_fixings(
        "SBER", "shares", "TQBR", years=1, today=today)

    assert added_dates == 2
    assert iss.history_calls == [(target, "2026-07-21")]
    coverage = db.contract_fixing_coverage(
        "SBER:price", source="MOEX", board="TQBR", session="")
    assert coverage["first_date"] == target
    assert coverage["last_date"] == today.isoformat()
    assert coverage["date_count"] == 3
