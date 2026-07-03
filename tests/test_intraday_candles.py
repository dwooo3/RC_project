"""Intraday candles: ISS rows are normalised into history-shaped bars with
ts = MSK-wall-clock-as-UTC epoch, written through to intraday_candles, and
5m/15m are aggregated from stored 1m bars (network mocked via a fake client)."""
import datetime as _dt

from api import intraday
from infra.db.market_data_db import MarketDataDB


def _today_begin(hh, mm):
    d = _dt.date.today().isoformat()
    return f"{d} {hh:02d}:{mm:02d}:00"


class _FakeIss:
    """Canned ISS candles; counts calls to assert the TTL/fetch behaviour."""
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def get_block_paginated(self, path, block, params):
        self.calls += 1
        self.last_params = params
        return self.rows


class _Ctx:
    def __init__(self, db=None):
        self.market_db = db


def _install(rows):
    fake = _FakeIss(rows)
    intraday._client = fake
    intraday._FETCH_TS.clear()
    return fake


def _db():
    db = MarketDataDB(":memory:")
    db.init_schema()
    return db


def test_normalises_and_stores_bars():
    fake = _install([
        {"open": 100.0, "close": 100.5, "high": 100.6, "low": 99.9, "volume": 42,
         "begin": _today_begin(11, 0), "end": _today_begin(11, 59)},
    ])
    db = _db()
    out = intraday.candles(_Ctx(db), "SU26238RMFS4", market="bonds", interval=60)
    assert out["count"] == 1
    p = out["points"][0]
    assert p["date"].endswith("11:00")
    assert p["close"] == 100.5 and p["volume"] == 42
    # write-through: the bar is persisted under the native interval
    stored = db.get_intraday_candles("SU26238RMFS4", "bonds", 60)
    assert len(stored) == 1 and stored[0]["close"] == 100.5
    assert fake.calls == 1
    # second call inside the TTL serves from the DB without re-fetching
    out2 = intraday.candles(_Ctx(db), "SU26238RMFS4", market="bonds", interval=60)
    assert out2["count"] == 1 and fake.calls == 1


def test_5m_aggregated_from_1m():
    fake = _install([
        {"open": 10, "close": 11, "high": 12, "low": 9, "volume": 1, "begin": _today_begin(10, 0)},
        {"open": 11, "close": 12, "high": 13, "low": 10, "volume": 2, "begin": _today_begin(10, 1)},
        {"open": 12, "close": 13, "high": 15, "low": 11, "volume": 3, "begin": _today_begin(10, 4)},
        {"open": 13, "close": 14, "high": 14, "low": 12, "volume": 4, "begin": _today_begin(10, 5)},
    ])
    out = intraday.candles(_Ctx(_db()), "SBER", market="shares", interval=5)
    assert fake.last_params["interval"] == 1            # fetched native 1m
    assert out["count"] == 2                            # 10:00–10:04 and 10:05
    b0, b1 = out["points"]
    assert b0["open"] == 10 and b0["close"] == 13       # first/last of the bucket
    assert b0["high"] == 15 and b0["low"] == 9          # extremes
    assert b0["volume"] == 6                            # Σ volume
    assert b1["open"] == 13 and b1["volume"] == 4
    assert b0["date"].endswith("10:00") and b1["date"].endswith("10:05")


def test_15m_bucket_boundaries():
    _install([
        {"open": 1, "close": 2, "high": 2, "low": 1, "volume": 1, "begin": _today_begin(10, 14)},
        {"open": 2, "close": 3, "high": 3, "low": 2, "volume": 1, "begin": _today_begin(10, 15)},
    ])
    out = intraday.candles(_Ctx(_db()), "SBER", market="shares", interval=15)
    assert out["count"] == 2                            # 10:00 and 10:15 buckets


def test_incremental_fetch_from_last_stored_bar():
    fake = _install([
        {"open": 1, "close": 2, "high": 2, "low": 1, "volume": 1, "begin": _today_begin(11, 0)},
    ])
    db = _db()
    intraday.candles(_Ctx(db), "X", market="bonds", interval=60)
    intraday._FETCH_TS.clear()                          # force TTL expiry
    intraday.candles(_Ctx(db), "X", market="bonds", interval=60)
    assert fake.calls == 2
    # second fetch starts at the stored bar's day, not the full window
    assert fake.last_params["from"] == _dt.date.today().isoformat()


def test_bad_interval_falls_back_to_60():
    _install([])
    out = intraday.candles(_Ctx(_db()), "X", market="bonds", interval=999)
    assert out["range"] == "60m"


def test_malformed_begin_skipped():
    _install([{"open": 1, "close": 1, "high": 1, "low": 1, "volume": 0, "begin": "garbage"}])
    out = intraday.candles(_Ctx(_db()), "Y", market="shares", interval=60)
    assert out["count"] == 0


def test_fx_market_is_unsupported():
    out = intraday.candles(_Ctx(None), "USDRUB", market="fx", interval=60)
    assert out.get("unsupported") is True and out["count"] == 0


def test_category_mapped_server_side():
    _install([{"open": 1, "close": 2, "high": 2, "low": 1, "volume": 5,
               "begin": _today_begin(10, 0)}])
    out = intraday.candles(_Ctx(_db()), "SBER", market="bonds", interval=60, category="equities")
    assert out["count"] == 1                     # category won over the market param
    assert out["market"] == "shares"


def test_no_db_serves_live_bars():
    _install([{"open": 1, "close": 2, "high": 2, "low": 1, "volume": 5,
               "begin": _today_begin(10, 0)}])
    out = intraday.candles(_Ctx(None), "SBER", market="shares", interval=60)
    assert out["count"] == 1
