"""Weekly (1w) aggregation of the daily price_history for /md/history."""
from api.market_entity import _weekly, history
from infra.db.market_data_db import MarketDataDB


def _p(date, o, h, lo, c, v=1.0, y=None):
    return {"date": date, "open": o, "high": h, "low": lo, "close": c,
            "volume": v, "value": v * 10, "yield": y, "numtrades": 1}


def test_weekly_buckets_by_iso_week():
    pts = [
        _p("2026-06-22", 100, 102, 99, 101),     # Mon
        _p("2026-06-24", 101, 105, 100, 104, y=14.0),
        _p("2026-06-26", 104, 104, 98, 99),      # Fri
        _p("2026-06-29", 99, 100, 97, 98),       # next Mon
    ]
    weeks = _weekly(pts)
    assert len(weeks) == 2
    w = weeks[0]
    assert w["date"] == "2026-06-22"             # dated by Monday
    assert w["open"] == 100 and w["close"] == 99  # first open / last close
    assert w["high"] == 105 and w["low"] == 98    # extremes
    assert w["volume"] == 3 and w["numtrades"] == 3
    assert w["yield"] == 14.0                     # last non-null yield
    assert weeks[1]["date"] == "2026-06-29" and weeks[1]["close"] == 98


def test_history_interval_1w():
    db = MarketDataDB(":memory:")
    db.init_schema()
    db.save_price_history([
        {"secid": "S", "market": "bonds", "dt": "2026-06-22", "open": 1, "high": 2,
         "low": 1, "close": 2, "volume": 1, "value": 1, "yield": None, "numtrades": 1},
        {"secid": "S", "market": "bonds", "dt": "2026-06-23", "open": 2, "high": 3,
         "low": 2, "close": 3, "volume": 1, "value": 1, "yield": None, "numtrades": 1},
    ])

    class _Ctx:
        market_db = db

    out = history(_Ctx(), "S", market="bonds", rng="ALL", interval="1w")
    assert out["interval"] == "1w" and out["count"] == 1
    assert out["points"][0]["close"] == 3


def test_history_default_is_daily():
    class _Ctx:
        market_db = None

    out = history(_Ctx(), "S", market="bonds", rng="1Y")
    assert out["interval"] == "1d" and out["count"] == 0
