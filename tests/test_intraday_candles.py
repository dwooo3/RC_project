"""Intraday candles endpoint: ISS rows are normalised into history-shaped bars
with ts = MSK-wall-clock-as-UTC epoch (network mocked via the module cache)."""
import time as _time

from api import intraday


class _Ctx:
    market_db = None


def _seed(secid, market, interval, rows):
    engine, iss_market = intraday._ENGINE_MARKET[market]
    intraday._CACHE[(secid, engine, iss_market, interval)] = (_time.monotonic(), rows)


def test_normalises_iss_rows_to_bars():
    _seed("SU26238RMFS4", "bonds", 60, [
        {"open": 100.0, "close": 100.5, "high": 100.6, "low": 99.9, "volume": 42,
         "begin": "2026-07-02 11:00:00", "end": "2026-07-02 11:59:59"},
    ])
    out = intraday.candles(_Ctx(), "SU26238RMFS4", market="bonds", interval=60)
    assert out["count"] == 1
    p = out["points"][0]
    assert p["date"] == "2026-07-02 11:00"
    assert p["ts"] == 1782990000                     # 2026-07-02T11:00Z (MSK-as-UTC)
    assert p["close"] == 100.5 and p["volume"] == 42


def test_bad_interval_falls_back_to_60():
    _seed("X", "bonds", 60, [])
    out = intraday.candles(_Ctx(), "X", market="bonds", interval=999)
    assert out["range"] == "60m"


def test_malformed_begin_skipped():
    _seed("Y", "shares", 10, [{"open": 1, "close": 1, "high": 1, "low": 1,
                               "volume": 0, "begin": "garbage"}])
    out = intraday.candles(_Ctx(), "Y", market="shares", interval=10)
    assert out["count"] == 0


def test_fx_market_is_unsupported():
    out = intraday.candles(_Ctx(), "USDRUB", market="fx", interval=60)
    assert out.get("unsupported") is True and out["count"] == 0


def test_category_mapped_server_side():
    _seed("SBER", "shares", 10, [{"open": 1, "close": 2, "high": 2, "low": 1,
                                  "volume": 5, "begin": "2026-07-02 10:00:00"}])
    out = intraday.candles(_Ctx(), "SBER", market="bonds", interval=10, category="equities")
    assert out["count"] == 1                     # category won over the market param
