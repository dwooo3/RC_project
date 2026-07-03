"""Daily append + quote refresh + backfill: the continuous store catches up to
the calendar via market-wide EOD requests (network mocked)."""
import datetime as _dt

from infra.db.market_data_db import MarketDataDB
from infra.market_store import MarketStore


class _FakeIss:
    """Serves canned market-wide EOD rows keyed by (path-ish, date)."""
    def __init__(self, by_date=None, by_range=None):
        self.by_date = by_date or {}
        self.by_range = by_range or []
        self.calls = []

    def get_block_paginated(self, path, block, params):
        self.calls.append((path, dict(params)))
        if "date" in params:
            return self.by_date.get(params["date"], [])
        return self.by_range                      # per-security range fetch (backfill)

    def get_blocks(self, path, params=None):
        return {}


def _db():
    db = MarketDataDB(":memory:")
    db.init_schema()
    return db


def _seed_day(db, secid, market, dt, close=100.0):
    db.save_price_history([{"secid": secid, "market": market, "dt": dt,
                            "open": close, "high": close, "low": close, "close": close,
                            "volume": 1, "value": 1, "yield": None, "numtrades": 1}])


def _eod(secid, dt, close, volume=10):
    return {"SECID": secid, "TRADEDATE": dt, "OPEN": close - 1, "HIGH": close + 1,
            "LOW": close - 2, "CLOSE": close, "VOLUME": volume, "VALUE": volume * close,
            "YIELDCLOSE": 14.0, "NUMTRADES": 5}


def test_append_daily_fills_gap_to_today():
    db = _db()
    today = _dt.date(2026, 7, 4)
    _seed_day(db, "OFZ1", "bonds", "2026-07-01")
    iss = _FakeIss(by_date={
        "2026-07-02": [_eod("OFZ1", "2026-07-02", 101.0), _eod("OFZ2", "2026-07-02", 90.0)],
        "2026-07-03": [_eod("OFZ1", "2026-07-03", 102.0)],
        "2026-07-04": [],
    })
    store = MarketStore(db, iss)
    out = store.append_daily(markets=("bonds",), today=today)
    assert out["bonds"]["days"] == 3 and out["bonds"]["rows_added"] == 3
    hist = db.get_price_history("OFZ1", "bonds")
    assert [h["dt"] for h in hist] == ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert hist[-1]["close"] == 102.0 and hist[-1]["yield"] == 14.0
    # per-board endpoint hit once per missing date per board (TQOB+TQCB)
    dates = [p["date"] for _, p in iss.calls]
    assert dates.count("2026-07-02") == 2


def test_append_daily_dedups_boards_by_volume():
    db = _db()
    _seed_day(db, "X", "shares", "2026-07-01")
    thin = _eod("X", "2026-07-02", 50.0, volume=1)
    fat = _eod("X", "2026-07-02", 55.0, volume=100)
    iss = _FakeIss(by_date={"2026-07-02": [thin, fat]})
    MarketStore(db, iss).append_daily(markets=("shares",), today=_dt.date(2026, 7, 2))
    hist = db.get_price_history("X", "shares")
    assert hist[-1]["close"] == 55.0              # most-traded board won


def test_append_daily_skips_empty_store():
    db = _db()
    iss = _FakeIss()
    out = MarketStore(db, iss).append_daily(markets=("bonds",), today=_dt.date(2026, 7, 4))
    assert out == {} and iss.calls == []          # nothing to anchor on → preload instead


def test_refresh_last_change_updates_ref_quotes():
    db = _db()
    db.save_instrument_ref({"secid": "OFZ1", "category": "bonds", "market": "bonds",
                            "board": "TQOB", "isin": None, "issuer_ru": "ОФЗ", "name_ru": "ОФЗ",
                            "sec_type": None, "list_level": None, "currency": "RUB",
                            "asset_code": None, "last_trade_date": None, "is_active": 1,
                            "last": None, "change_pct": None, "as_of": None,
                            "day_json": "{}", "ref_json": "[]"})
    today = _dt.date.today()
    d1 = (today - _dt.timedelta(days=1)).isoformat()
    _seed_day(db, "OFZ1", "bonds", d1, close=100.0)
    _seed_day(db, "OFZ1", "bonds", today.isoformat(), close=102.0)
    n = MarketStore(db, _FakeIss()).refresh_last_change(markets=("bonds",))
    assert n == 1
    ref = db.get_instrument_ref("OFZ1")
    assert ref["last"] == 102.0 and abs(ref["change_pct"] - 2.0) < 1e-9
    assert ref["as_of"] == today.isoformat()


def test_backfill_extends_backwards_only():
    db = _db()
    db.save_instrument_ref({"secid": "OFZ1", "category": "bonds", "market": "bonds",
                            "board": "TQOB", "isin": None, "issuer_ru": "ОФЗ", "name_ru": "ОФЗ",
                            "sec_type": None, "list_level": None, "currency": "RUB",
                            "asset_code": None, "last_trade_date": None, "is_active": 1,
                            "last": None, "change_pct": None, "as_of": None,
                            "day_json": "{}", "ref_json": "[]"})
    _seed_day(db, "OFZ1", "bonds", "2026-07-01")
    iss = _FakeIss(by_range=[_eod("OFZ1", "2020-03-02", 95.0)])
    out = MarketStore(db, iss).backfill("bonds", years=8)
    assert out["rows_added"] == 1
    hist = db.get_price_history("OFZ1", "bonds")
    assert hist[0]["dt"] == "2020-03-02" and hist[-1]["dt"] == "2026-07-01"
    # the range request ends the day BEFORE the first stored bar
    _, params = iss.calls[-1]
    assert params["till"] == "2026-06-30"
