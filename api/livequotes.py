"""Realtime quotes for a whole category from the MOEX ISS marketdata block.

One request per category returns LAST / change% / OHLC / turnover / trades for
every security on the market — powering the live watchlist prices and the
realtime "Торги за день" card (turnover + trade count aren't in candles).

A short in-process TTL keeps the UI's 15s polling from hammering ISS.
"""

from __future__ import annotations

import time as _time

# app category → ISS (engine, market); fx (CBR fixings) has no live market
_CATEGORY_ENGINE_MARKET = {
    "bonds": ("stock", "bonds"),
    "equities": ("stock", "shares"),
    "funds": ("stock", "shares"),
    "futures": ("futures", "forts"),
    "options": ("futures", "forts"),
    "commodities": ("futures", "forts"),
    "indices": ("stock", "index"),
}

_TTL = 10.0                                   # seconds; UI polls every ~15s
_CACHE: dict[str, tuple[float, dict]] = {}    # category → (fetched_at, payload)

_client = None


def _iss():
    global _client
    if _client is None:
        from infra.moex_iss.client import IssClient
        _client = IssClient()
    return _client


def _num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v


def live_quotes(category: str) -> dict:
    """secid → realtime quote for every security in the category's market."""
    pair = _CATEGORY_ENGINE_MARKET.get(category)
    if pair is None:
        return {"category": category, "quotes": {}, "count": 0}

    cached = _CACHE.get(category)
    if cached and _time.monotonic() - cached[0] < _TTL:
        return cached[1]

    engine, market = pair
    endpoint = f"engines/{engine}/markets/{market}/securities"
    try:
        # single request — the marketdata block is not paginated (it ignores
        # `start`, so get_block_paginated would loop forever)
        rows = _iss().get_blocks(endpoint, {
            "iss.only": "marketdata",
            "marketdata.columns": ("SECID,BOARDID,OPEN,HIGH,LOW,LAST,"
                                   "LASTTOPREVPRICE,VALTODAY,VOLTODAY,"
                                   "NUMTRADES,YIELD,UPDATETIME"),
        }).get("marketdata", [])
    except Exception as exc:
        return {"category": category, "quotes": {}, "count": 0,
                "error": str(exc)[:140]}

    # several boards per secid — keep the most-traded row
    quotes: dict[str, dict] = {}
    turnover: dict[str, float] = {}
    for r in rows:
        secid = r.get("SECID")
        last = _num(r.get("LAST"))
        if not secid or last is None:
            continue
        val = _num(r.get("VALTODAY")) or 0.0
        if secid in quotes and val <= turnover.get(secid, 0.0):
            continue
        turnover[secid] = val
        quotes[secid] = {
            "last": last,
            "change_pct": _num(r.get("LASTTOPREVPRICE")),
            "open": _num(r.get("OPEN")),
            "high": _num(r.get("HIGH")),
            "low": _num(r.get("LOW")),
            "value": val or None,
            "volume": _num(r.get("VOLTODAY")),
            "numtrades": _num(r.get("NUMTRADES")),
            "yield": _num(r.get("YIELD")),
            "time": r.get("UPDATETIME"),
        }

    payload = {"category": category, "quotes": quotes, "count": len(quotes)}
    _CACHE[category] = (_time.monotonic(), payload)
    return payload
