"""Live intraday candles from MOEX ISS (Market Data section).

Unlike the EOD store, this is a live fetch: GET /iss/.../candles with interval
1 (1m) / 10 (10m) / 60 (1h), normalised into the same bar shape the history
endpoint uses, plus ``ts`` — the bar's open time as epoch seconds with Moscow
wall-clock encoded as UTC, so the chart's time axis shows exchange hours.
A short in-process TTL cache keeps the 15s UI polling from hammering ISS.
"""

from __future__ import annotations

import calendar
import time as _time
from datetime import date, timedelta
from time import strptime

# category-market → ISS (engine, market)
_ENGINE_MARKET = {
    "bonds": ("stock", "bonds"),
    "shares": ("stock", "shares"),
    "forts": ("futures", "forts"),
    "fx": ("currency", "selt"),
    "indices": ("stock", "index"),
}

# lookback per interval — enough bars to fill the pane without paging forever
_LOOKBACK_DAYS = {1: 2, 10: 10, 60: 45}

_TTL = 10.0                                  # seconds; UI polls every ~15s
_CACHE: dict[tuple, tuple[float, list]] = {}

_client = None


def _iss():
    global _client
    if _client is None:
        from infra.moex_iss.client import IssClient
        _client = IssClient()
    return _client


def candles(ctx, secid: str, market: str = "bonds", interval: int = 60) -> dict:
    interval = int(interval)
    if interval not in _LOOKBACK_DAYS:
        interval = 60
    engine, iss_market = _ENGINE_MARKET.get(market, ("stock", "bonds"))
    key = (secid, engine, iss_market, interval)
    now = _time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        rows = hit[1]
    else:
        frm = (date.today() - timedelta(days=_LOOKBACK_DAYS[interval])).isoformat()
        try:
            rows = _iss().get_block_paginated(
                f"engines/{engine}/markets/{iss_market}/securities/{secid}/candles",
                "candles", {"interval": interval, "from": frm})
        except Exception:
            rows = []                        # network/ISS down → empty, UI shows placeholder
        if len(_CACHE) > 200:
            _CACHE.clear()
        _CACHE[key] = (now, rows)

    points = []
    for r in rows:
        begin = str(r.get("begin") or "")
        try:
            ts = calendar.timegm(strptime(begin, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        points.append({
            "date": begin[:16], "ts": ts,
            "open": r.get("open"), "high": r.get("high"), "low": r.get("low"),
            "close": r.get("close"), "volume": r.get("volume"), "yield": None,
            "numtrades": None,
        })
    return {"secid": secid, "market": market, "range": f"{interval}m",
            "points": points, "count": len(points)}
