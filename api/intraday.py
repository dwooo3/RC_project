"""Intraday candles: live MOEX ISS fetch with write-through DB accumulation.

Timeframes served: 1m / 5m / 15m / 60m. ISS only has native 1m and 60m (plus
10m, unused here) — 5m and 15m are aggregated from stored 1m bars on read.

Data flow per request:
  1. Incremental ISS fetch of the native interval (from the last stored bar,
     minus a small overlap so the previously-open bar gets rewritten).
  2. Upsert into `intraday_candles` (idempotent, PK secid+market+interval+ts) —
     so live polling *accumulates* history instead of throwing it away.
  3. Serve from the DB over the display window (deeper than the live fetch),
     aggregating 1m → 5m/15m when asked.

``ts`` is the bar open time as epoch seconds with Moscow wall-clock encoded as
UTC, so the chart's time axis shows exchange hours. A short in-process TTL
keeps the 15s UI polling from hammering ISS.
"""

from __future__ import annotations

import calendar
import time as _time
from datetime import date, timedelta
from time import strptime

# category-market → ISS (engine, market). NB: no "fx" — our FX instruments are
# CBR fixings (USDRUB/…, board=cbr), which don't trade on currency/selt under
# these secids, so intraday is honestly unsupported for them (audit A3).
_ENGINE_MARKET = {
    "bonds": ("stock", "bonds"),
    "shares": ("stock", "shares"),
    "forts": ("futures", "forts"),
    "indices": ("stock", "index"),
}

# app category → market key above (audit A10: map on the server so any client
# can pass its category directly instead of re-implementing the mapping)
_CATEGORY_MARKET = {
    "bonds": "bonds", "equities": "shares", "futures": "forts",
    "options": "forts", "commodities": "forts", "indices": "indices",
}

# requested interval → (native ISS interval to fetch/store, display window days)
_INTERVALS = {
    1: (1, 3),
    5: (1, 7),
    15: (1, 14),
    60: (60, 60),
}

_TTL = 10.0                                  # seconds; UI polls every ~15s
_FETCH_TS: dict[tuple, float] = {}           # last successful ISS fetch per key

_client = None


def _iss():
    global _client
    if _client is None:
        from infra.moex_iss.client import IssClient
        _client = IssClient()
    return _client


def _parse_ts(begin: str) -> int | None:
    try:
        return calendar.timegm(strptime(begin, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def _fetch_iss(secid: str, engine: str, iss_market: str, native: int,
               frm: str) -> list[dict]:
    """Native-interval bars from ISS since ``frm`` → intraday_candles rows."""
    rows = _iss().get_block_paginated(
        f"engines/{engine}/markets/{iss_market}/securities/{secid}/candles",
        "candles", {"interval": native, "from": frm})
    out = []
    for r in rows:
        begin = str(r.get("begin") or "")
        ts = _parse_ts(begin)
        if ts is None:
            continue
        out.append({"ts": ts, "dt": begin[:16],
                    "open": r.get("open"), "high": r.get("high"),
                    "low": r.get("low"), "close": r.get("close"),
                    "volume": r.get("volume")})
    return out


def _aggregate(rows: list[dict], minutes: int) -> list[dict]:
    """1m bars → N-minute buckets (open=first, close=last, extremes, Σvolume)."""
    step = minutes * 60
    buckets: dict[int, dict] = {}
    order: list[int] = []
    for r in sorted(rows, key=lambda r: r["ts"]):
        b = (r["ts"] // step) * step
        cur = buckets.get(b)
        if cur is None:
            buckets[b] = {**r, "ts": b}
            order.append(b)
            continue
        if r.get("high") is not None:
            cur["high"] = max(cur["high"], r["high"]) if cur.get("high") is not None else r["high"]
        if r.get("low") is not None:
            cur["low"] = min(cur["low"], r["low"]) if cur.get("low") is not None else r["low"]
        if r.get("close") is not None:
            cur["close"] = r["close"]
        if r.get("volume") is not None:
            cur["volume"] = (cur.get("volume") or 0) + r["volume"]
    for b in order:                       # bucket label = bucket open time
        t = _time.gmtime(b)
        buckets[b]["dt"] = _time.strftime("%Y-%m-%d %H:%M", t)
    return [buckets[b] for b in order]


def candles(ctx, secid: str, market: str = "bonds", interval: int = 60,
            category: str | None = None) -> dict:
    interval = int(interval)
    if interval not in _INTERVALS:
        interval = 60
    native, window_days = _INTERVALS[interval]
    if category:
        market = _CATEGORY_MARKET.get(category, market)
    em = _ENGINE_MARKET.get(market)
    if em is None:                                # fx / unknown → honestly unsupported
        return {"secid": secid, "market": market, "range": f"{interval}m",
                "points": [], "count": 0, "unsupported": True}
    engine, iss_market = em
    db = getattr(ctx, "market_db", None)
    window_start = date.today() - timedelta(days=window_days)
    window_ts = calendar.timegm(window_start.timetuple())

    key = (secid, iss_market, native)
    now = _time.monotonic()
    fetched: list[dict] = []
    if db is None or now - _FETCH_TS.get(key, 0.0) >= _TTL:
        # incremental: refetch from the last stored bar (overlap rewrites the
        # previously-open bar); first view of a security pulls the full window
        last_ts = db.intraday_max_ts(secid, market, native) if db is not None else None
        if last_ts:
            # ts is MSK-wall-clock-as-UTC → decode with gmtime, not local time
            t = _time.gmtime(max(last_ts - native * 60, window_ts))
            frm = f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
        else:
            frm = window_start.isoformat()
        try:
            fetched = _fetch_iss(secid, engine, iss_market, native, frm)
            _FETCH_TS[key] = now
            if len(_FETCH_TS) > 400:
                _FETCH_TS.clear()
        except Exception:
            fetched = []                     # network/ISS down → serve what's stored
        if fetched and db is not None:
            try:
                db.save_intraday_candles([{**r, "secid": secid, "market": market,
                                           "interval": native} for r in fetched])
            except Exception:
                pass                         # read-only/locked DB → still serve live

    if db is not None:
        rows = db.get_intraday_candles(secid, market, native, frm_ts=window_ts)
    else:
        rows = [r for r in fetched if r["ts"] >= window_ts]   # demo mode: live only
    if interval != native:
        rows = _aggregate(rows, interval)

    points = [{"date": r["dt"], "ts": r["ts"],
               "open": r["open"], "high": r["high"], "low": r["low"],
               "close": r["close"], "volume": r["volume"], "yield": None,
               "numtrades": None} for r in rows]
    return {"secid": secid, "market": market, "range": f"{interval}m",
            "points": points, "count": len(points)}
