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
    if category == "bonds":
        _enrich_bonds(ctx, out)                      # YTM + G-spread (audit B1/B2)
    elif category == "equities":
        _enrich_equities(ctx, out)                   # trailing dividend yield (B5)
    return {"category": category, "instruments": out, "count": len(out)}


def _enrich_equities(ctx, rows: list[dict]) -> None:
    """Trailing-12m dividend yield from the dividends table (181 issuers)."""
    db = ctx.market_db
    frm = (_dt.date.today() - _dt.timedelta(days=365)).isoformat()
    sums = db.dividend_sums_since(frm)
    for r in rows:
        s = sums.get(r["secid"])
        last = r.get("last")
        if s and last:
            r["div_yield_pct"] = round(s / float(last) * 100.0, 2)


def _gcurve_zero(points: list[dict]):
    """Linear zero-rate interpolator over GCURVE (tenor, zero_rate decimal)."""
    pts = sorted((float(p["tenor"]), float(p["zero_rate"])) for p in points
                 if p.get("zero_rate") is not None)
    if not pts:
        return None

    def zero(t: float) -> float:
        if t <= pts[0][0]:
            return pts[0][1]
        for (t0, z0), (t1, z1) in zip(pts, pts[1:]):
            if t0 <= t <= t1:
                return z0 + (z1 - z0) * (t - t0) / (t1 - t0)
        return pts[-1][1]
    return zero


def _enrich_bonds(ctx, rows: list[dict]) -> None:
    """Attach ytm (bond_quotes, %) and g_spread_bp (YTM − GCURVE zero at maturity,
    b.p.) to bond list rows. Everything is already in the store — one quotes map,
    one maturity map and one curve read per request."""
    db = ctx.market_db
    try:
        sid = ctx.snapshot.snapshot_id
    except Exception:
        return
    quotes = {q["secid"]: q for q in db.get_bond_quotes(sid)}
    mats = db.bond_maturities()
    zero = _gcurve_zero(db.get_curve_points(sid, "GCURVE_RUB"))
    today = _dt.date.today()
    for r in rows:
        q = quotes.get(r["secid"])
        if not q or q.get("ytm") is None:
            continue
        ytm = float(q["ytm"])                        # stored as a decimal fraction
        if not (-0.5 < ytm < 2.0):                   # junk quotes out (>200%)
            continue
        r["ytm"] = round(ytm * 100.0, 2)             # expose as percent
        mat = mats.get(r["secid"])
        if zero is None or not mat:
            continue
        try:
            t = (_dt.date.fromisoformat(str(mat)[:10]) - today).days / 365.0
        except ValueError:
            continue
        if t > 1e-3:
            r["g_spread_bp"] = round((ytm - zero(t)) * 1e4, 1)


def search(ctx, q: str, limit: int = 20) -> dict:
    """Global instrument search (C1): secid / ISIN / issuer across instrument_ref
    plus the index registry. Python-side lower() so Cyrillic matching works
    (sqlite LIKE is ASCII-only case-insensitive)."""
    db = ctx.market_db
    ql = (q or "").strip().lower()
    if db is None or len(ql) < 2:
        return {"query": q, "results": []}
    scored = []
    for r in db.all_instrument_refs():
        secid = str(r.get("secid") or "").lower()
        issuer = str(r.get("issuer_ru") or "").lower()
        rest = f"{r.get('isin') or ''} {r.get('name_ru') or ''}".lower()
        # rank: exact/prefix ticker or issuer beats a substring buried in the name
        if secid.startswith(ql) or issuer.startswith(ql):
            rank = 0
        elif ql in secid or ql in issuer:
            rank = 1
        elif ql in rest:
            rank = 2
        else:
            continue
        scored.append((rank, issuer, {
            "secid": r["secid"], "category": r.get("category"),
            "issuer_ru": r.get("issuer_ru"), "isin": r.get("isin"),
            "last": r.get("last"), "change_pct": r.get("change_pct")}))
    for base, name in _INDICES.items():
        if ql in base.lower() or ql in name.lower():
            pts = db.last_two_points(f"{base}:price")
            if pts:
                rank = 0 if (base.lower().startswith(ql) or name.lower().startswith(ql)) else 1
                scored.append((rank, name.lower(), {
                    "secid": base, "category": "indices", "issuer_ru": name,
                    "isin": None, "last": pts[0]["value"], "change_pct": None}))
    scored.sort(key=lambda s: (s[0], s[1]))
    return {"query": q, "results": [s[2] for s in scored[:limit]]}


def refdata(ctx) -> dict:
    """Unified reference look-ups (§8): currencies, boards, sources."""
    db = ctx.market_db
    if db is None:
        return {"currencies": [], "boards": [], "sources": []}
    return {"currencies": db.list_ref_currencies(), "boards": db.list_ref_boards(),
            "sources": db.list_ref_sources()}


def _commodity_futures(db) -> list[dict]:
    """Active futures whose asset_code is a commodity (per commodity_quotes)."""
    assets = set(db.list_commodity_assets())
    rows = db.list_instrument_refs("futures", active_only=True)
    return [r for r in rows if (r.get("asset_code") in assets)]


# Explicit index registry (audit A2). MOEX deliberately absent — MOEX:price in
# time_series is the *share* of Moscow Exchange from the equity backfill, not an
# index. Only registered ids with stored points are listed.
_INDICES = {
    "IMOEX": "Индекс МосБиржи",
    "RTSI": "Индекс РТС",
    "RGBI": "Индекс гособлигаций",
    "RUCBTRNS": "Индекс корп. облигаций",
    "RVI": "Индекс волатильности",
    "RUSFAR": "RUSFAR (ставка)",
}


def _list_indices(ctx) -> dict:
    """Indices live in time_series (e.g. IMOEX:price). List each registered index
    with its latest value as an instrument-like row for the entity browser."""
    db = ctx.market_db
    out = []
    for base, name in _INDICES.items():
        pts = db.last_two_points(f"{base}:price")
        if not pts:
            continue
        last = pts[0]["value"]
        prev = pts[1]["value"] if len(pts) > 1 else None
        chg = ((last - prev) / prev * 100.0) if (last and prev) else None
        out.append({"secid": base, "issuer_ru": name, "isin": None, "last": last,
                    "change_pct": chg, "as_of": pts[0]["dt"],
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

    fetch_ts = str(meta.get("fetch_ts") or "")
    return {
        "available": True,
        "as_of": meta.get("valuation_date"),
        "source": meta.get("source"),
        "updated": fetch_ts[11:16] if len(fetch_ts) >= 16 else None,   # HH:MM
        "tiles": tiles,
        "fx": [{"pair": p, "rate": r} for p, r in sorted(fx.items())],
        "indicators": _overview_indicators(db),
    }


def _overview_indicators(db) -> list[dict]:
    """Headline market indicators for the Overview strip (C2): key indices from
    the registry + Brent (active futures) + USD/RUB fixing."""
    out = []
    for base in ("IMOEX", "RGBI", "RVI"):
        pts = db.last_two_points(f"{base}:price")
        if not pts:
            continue
        last = pts[0]["value"]
        prev = pts[1]["value"] if len(pts) > 1 else None
        chg = ((last - prev) / prev * 100.0) if (last and prev) else None
        out.append({"key": base, "category": "indices", "label": _INDICES.get(base, base),
                    "value": last, "change_pct": chg})
    try:
        br = [r for r in db.list_instrument_refs("futures", active_only=True)
              if r.get("asset_code") == "BR" and r.get("last")]
        if br:
            out.append({"key": br[0]["secid"], "category": "futures", "label": "Brent",
                        "value": br[0]["last"], "change_pct": br[0].get("change_pct")})
    except Exception:
        pass
    usd = db.get_instrument_ref("USDRUB")
    if usd and usd.get("last"):
        out.append({"key": "USDRUB", "category": "fx", "label": "USD/RUB",
                    "value": usd["last"], "change_pct": usd.get("change_pct")})
    return out


def _stats_from_closes(closes: list[tuple]) -> dict | None:
    """(dt_iso, close) → 52w high/low, 30d realized vol (annualized, %) and max
    drawdown over the trailing year — cheap analytics on stored history (B6)."""
    import math
    pts = [(d, c) for d, c in closes if c]
    if len(pts) < 20:
        return None
    year_ago = (_dt.date.today() - _dt.timedelta(days=365)).isoformat()
    yr = [c for d, c in pts if d >= year_ago] or [c for _, c in pts]
    tail = [c for _, c in pts][-31:]
    rets = [math.log(b / a) for a, b in zip(tail, tail[1:]) if a > 0 and b > 0]
    rv = None
    if len(rets) >= 10:
        m = sum(rets) / len(rets)
        var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
        rv = round(math.sqrt(var * 252) * 100.0, 2)
    peak, dd = yr[0], 0.0
    for c in yr:
        peak = max(peak, c)
        dd = min(dd, c / peak - 1.0)
    return {"hi_52w": max(yr), "lo_52w": min(yr),
            "rv_30d_pct": rv, "max_dd_pct": round(dd * 100.0, 2)}


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
        name = _INDICES.get(secid, secid)
        return {"secid": secid, "category": "indices", "issuer_ru": name, "name_ru": name,
                "isin": None, "sec_type": "index", "list_level": None, "currency": "RUB",
                "board": None, "last": last["value"], "change_pct": chg, "as_of": last["dt"],
                "fields": [], "day": {"date": last["dt"], "close": last["value"], "open": None,
                                      "high": None, "low": None, "volume": None, "value": None,
                                      "yield": None, "numtrades": None},
                "stats": _stats_from_closes([(p["dt"], p["value"]) for p in series])}
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
        out["stats"] = _stats_from_closes([(h["dt"], h.get("close")) for h in hist])
    if ref.get("category") == "bonds":
        out["schedule"] = db.get_bond_schedule(secid)
        out["schedule_versions"] = db.get_bond_schedule_versions(secid)
        row = {"secid": secid}
        _enrich_bonds(ctx, [row])                     # ytm + g_spread for the detail pane
        out["ytm"] = row.get("ytm")
        out["g_spread_bp"] = row.get("g_spread_bp")
        try:
            q = db.get_bond_quote(ctx.snapshot.snapshot_id, secid) or {}
            out["accrued"] = q.get("accruedint")
            out["wap"] = q.get("wap_price")
        except Exception:
            pass
    elif ref.get("category") == "equities":
        out["dividends"] = db.get_dividends(secid)
        row = {"secid": secid, "last": ref.get("last")}
        _enrich_equities(ctx, [row])
        out["div_yield_pct"] = row.get("div_yield_pct")
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
