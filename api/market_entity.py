"""Instrument-entity API over the continuously-accumulated market store.

Each instrument is one entity: full ISS reference + latest day stats + 5y daily
history. No snapshots — the latest value is shown with its own date.
"""

from __future__ import annotations

import datetime as _dt
import json

_RANGE_DAYS = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "5Y": 1825}


def _range_from(rng: str) -> str | None:
    days = _RANGE_DAYS.get((rng or "5Y").upper())
    if not days:
        return None                                   # ALL
    return (_dt.date.today() - _dt.timedelta(days=days)).isoformat()


def list_instruments(ctx, category: str) -> dict:
    db = ctx.market_db
    if db is None:
        return {"category": category, "instruments": [], "count": 0}
    rows = db.list_instrument_refs(category, active_only=(category == "futures"))
    out = [{
        "secid": r["secid"], "issuer_ru": r.get("issuer_ru"), "isin": r.get("isin"),
        "last": r.get("last"), "change_pct": r.get("change_pct"), "as_of": r.get("as_of"),
        "sec_type": r.get("sec_type"), "currency": r.get("currency"), "board": r.get("board"),
    } for r in rows]
    return {"category": category, "instruments": out, "count": len(out)}


def instrument(ctx, category: str, secid: str) -> dict:
    db = ctx.market_db
    ref = db.get_instrument_ref(secid) if db is not None else None
    if not ref:
        raise ValueError(f"unknown instrument {secid}")
    market = ref.get("market") or "bonds"
    out = {
        "secid": secid, "category": ref.get("category"), "issuer_ru": ref.get("issuer_ru"),
        "name_ru": ref.get("name_ru"), "isin": ref.get("isin"), "sec_type": ref.get("sec_type"),
        "list_level": ref.get("list_level"), "currency": ref.get("currency"),
        "board": ref.get("board"), "last": ref.get("last"), "change_pct": ref.get("change_pct"),
        "as_of": ref.get("as_of"),
        "fields": json.loads(ref.get("ref_json") or "[]"),    # all ISS description fields
    }
    hist = db.get_price_history(secid, market)
    if hist:
        r = hist[-1]
        out["day"] = {"date": r["dt"], "open": r["open"], "high": r["high"], "low": r["low"],
                      "close": r["close"], "volume": r["volume"], "value": r["value"],
                      "yield": r["yield"], "numtrades": r["numtrades"]}
    if ref.get("category") == "bonds":
        out["schedule"] = db.get_bond_schedule(secid)
    elif ref.get("category") == "equities":
        out["dividends"] = db.get_dividends(secid)
    elif ref.get("category") == "futures" and ref.get("asset_code"):
        out["asset_code"] = ref.get("asset_code")
        out["chain"] = [{
            "secid": c["secid"], "shortname": c.get("issuer_ru"),
            "last": c.get("last"), "change_pct": c.get("change_pct"),
            "last_trade_date": c.get("last_trade_date"), "is_active": c.get("is_active"),
        } for c in db.futures_chain(ref["asset_code"])]
    return out


def history(ctx, secid: str, market: str = "bonds", rng: str = "5Y") -> dict:
    db = ctx.market_db
    pts = db.get_price_history(secid, market, frm=_range_from(rng)) if db is not None else []
    return {
        "secid": secid, "market": market, "range": (rng or "5Y").upper(),
        "points": [{
            "date": p["dt"], "open": p["open"], "high": p["high"], "low": p["low"],
            "close": p["close"], "volume": p["volume"], "yield": p["yield"],
            "numtrades": p["numtrades"],
        } for p in pts],
        "count": len(pts),
    }
