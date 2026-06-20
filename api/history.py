"""On-demand trade history for a security (MOEX ISS history API).

Daily close (+ yield for bonds, + volume) over a lookback window, fetched live
from ISS so any instrument in the catalog can show its trading history.
"""

from __future__ import annotations

import datetime


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def trade_history(category: str, secid: str, days: int = 180) -> dict:
    from infra.moex_iss.client import IssClient

    market = "shares" if category == "equities" else "bonds"
    till = datetime.date.today()
    frm = till - datetime.timedelta(days=max(7, days))
    endpoint = f"history/engines/stock/markets/{market}/securities/{secid}"
    try:
        rows = IssClient().get_block_paginated(
            endpoint, "history", {"from": frm.isoformat(), "till": till.isoformat()})
    except Exception as exc:
        return {"secid": secid, "category": category, "market": market,
                "points": [], "error": str(exc)[:140]}

    # one point per trading day — keep the most-traded board if several appear
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r.get("TRADEDATE") or r.get("tradedate")
        close = _num(r.get("CLOSE")) or _num(r.get("LEGALCLOSEPRICE"))
        if not d or close is None:
            continue
        vol = _num(r.get("VOLUME")) or 0.0
        prev = by_date.get(d)
        if prev is None or vol >= (prev.get("volume") or 0.0):
            by_date[d] = {
                "date": d, "close": close,
                "yield": _num(r.get("YIELDCLOSE")),
                "volume": vol, "numtrades": _num(r.get("NUMTRADES")),
            }
    points = [by_date[d] for d in sorted(by_date)]
    return {"secid": secid, "category": category, "market": market,
            "points": points, "count": len(points)}
