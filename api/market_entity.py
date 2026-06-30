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
    if category == "indices":
        return _list_indices(ctx)
    if category == "commodities":
        rows = _commodity_futures(db)
    else:
        rows = db.list_instrument_refs(category, active_only=(category == "futures"))
    out = [{
        "secid": r["secid"], "issuer_ru": r.get("issuer_ru"), "isin": r.get("isin"),
        "last": r.get("last"), "change_pct": r.get("change_pct"), "as_of": r.get("as_of"),
        "sec_type": r.get("sec_type"), "currency": r.get("currency"), "board": r.get("board"),
    } for r in rows]
    return {"category": category, "instruments": out, "count": len(out)}


def _commodity_futures(db) -> list[dict]:
    """Active futures whose asset_code is a commodity (per commodity_quotes)."""
    assets = set(db.list_commodity_assets())
    rows = db.list_instrument_refs("futures", active_only=True)
    return [r for r in rows if (r.get("asset_code") in assets)]


def _list_indices(ctx) -> dict:
    """Indices live in time_series (e.g. IMOEX:price). List each with its latest
    value as an instrument-like row so the entity browser can render them."""
    db = ctx.market_db
    out = []
    for r in db.list_time_series_factors():
        fid, kind = r["factor_id"], (r.get("kind") or "")
        base = fid.rsplit(":", 1)[0]
        if not (fid.endswith(":index") or base in ("IMOEX", "MOEX", "RTSI", "RGBI", "RTS", "MCXSM")):
            continue
        series = db.get_time_series(fid, kind) or db.get_time_series(fid)
        last = series[-1]["value"] if series else None
        prev = series[-2]["value"] if len(series) > 1 else None
        chg = ((last - prev) / prev * 100.0) if (last and prev) else None
        out.append({"secid": base, "issuer_ru": base, "isin": None, "last": last,
                    "change_pct": chg, "as_of": series[-1]["dt"] if series else None,
                    "sec_type": "index", "currency": "RUB", "board": None})
    out.sort(key=lambda x: x["secid"])
    return {"category": "indices", "instruments": out, "count": len(out)}


def overview(ctx) -> dict:
    """Market Data landing: asset-class tiles (counts) + key FX + as-of line.
    Navigational summary — no quality/control content (that lives in Data Controls)."""
    db = ctx.market_db
    if db is None:
        return {"available": False}
    try:
        sid = ctx.snapshot.snapshot_id
    except Exception:
        sid = (db.latest_snapshot_meta() or {}).get("snapshot_id")
    meta = (db.get_snapshot_meta(sid) if sid else {}) or {}

    tiles = []
    for key, label in (("bonds", "Bonds"), ("equities", "Equities"),
                       ("futures", "Futures"), ("options", "Options")):
        tiles.append({"key": key, "label": label,
                      "count": db.count_instrument_refs(key, active_only=(key == "futures"))})
    tiles.append({"key": "commodities", "label": "Commodities", "count": len(_commodity_futures(db))})
    tiles.append({"key": "indices", "label": "Indices", "count": _list_indices(ctx)["count"]})
    try:
        fx = db.get_fx_rates(sid) or {}
    except Exception:
        fx = {}
    tiles.append({"key": "fx", "label": "FX", "count": len(fx)})
    try:
        curves = db.list_curve_ids(sid)
    except Exception:
        curves = []
    tiles.append({"key": "curves", "label": "Curves", "count": len(curves)})
    try:
        vp = len(db.get_vol_points(sid))
    except Exception:
        vp = 0
    tiles.append({"key": "vols", "label": "Volatility", "count": vp})

    return {
        "available": True,
        "as_of": meta.get("valuation_date"),
        "source": meta.get("source"),
        "tiles": tiles,
        "fx": [{"pair": p, "rate": r} for p, r in sorted(fx.items())],
    }


def _index_series(db, secid: str) -> list[dict]:
    return (db.get_time_series(f"{secid}:price", "price")
            or db.get_time_series(f"{secid}:index", "index")
            or db.get_time_series(secid))


def instrument(ctx, category: str, secid: str) -> dict:
    db = ctx.market_db
    if category == "indices":                                  # indices live in time_series
        series = _index_series(db, secid) if db is not None else []
        if not series:
            raise ValueError(f"unknown index {secid}")
        last, prev = series[-1], (series[-2] if len(series) > 1 else None)
        chg = ((last["value"] - prev["value"]) / prev["value"] * 100.0) if prev else None
        return {"secid": secid, "category": "indices", "issuer_ru": secid, "name_ru": secid,
                "isin": None, "sec_type": "index", "list_level": None, "currency": "RUB",
                "board": None, "last": last["value"], "change_pct": chg, "as_of": last["dt"],
                "fields": [], "day": {"date": last["dt"], "close": last["value"], "open": None,
                                      "high": None, "low": None, "volume": None, "value": None,
                                      "yield": None, "numtrades": None}}
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
    elif ref.get("category") == "options":
        out["asset_code"] = secid
        out["option_chain"] = _option_chain(db.get_option_chain(secid))
    out["versions"] = db.get_instrument_versions(secid)      # reference-change history
    return out


def _option_chain(rows: list[dict]) -> list[dict]:
    """Group flat option quotes into [{expiry, central_strike, strikes:[{strike, call, put}]}]."""
    by_exp: dict[str, dict] = {}
    for o in rows:
        e = by_exp.setdefault(o["expiry"], {"expiry": o["expiry"],
                                            "central_strike": o.get("central_strike"), "strikes": {}})
        if o.get("central_strike"):
            e["central_strike"] = o["central_strike"]
        s = e["strikes"].setdefault(o["strike"], {"strike": o["strike"], "call": None, "put": None})
        side = {"last": o.get("last"), "oi": o.get("oi")}
        s["call" if o.get("opt_type") == "C" else "put"] = side
    out = []
    for e in sorted(by_exp.values(), key=lambda x: x["expiry"] or ""):
        strikes = sorted(e["strikes"].values(), key=lambda x: x["strike"] or 0)
        out.append({"expiry": e["expiry"], "central_strike": e["central_strike"], "strikes": strikes})
    return out


def history(ctx, secid: str, market: str = "bonds", rng: str = "5Y") -> dict:
    db = ctx.market_db
    if market == "indices":                                    # close-only series from time_series
        frm = _range_from(rng)
        rows = _index_series(db, secid) if db is not None else []
        pts = [{"date": p["dt"], "open": None, "high": None, "low": None,
                "close": p["value"], "volume": None, "yield": None, "numtrades": None}
               for p in rows if (not frm or p["dt"] >= frm)]
        return {"secid": secid, "market": "indices", "range": (rng or "5Y").upper(),
                "points": pts, "count": len(pts)}
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
