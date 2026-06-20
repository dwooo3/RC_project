"""Instrument catalog for the Market Data screen.

Lists every instrument loaded into the active snapshot by category, as a generic
table (columns + display rows) plus a full per-instrument specification for the
detail popup. Supports board filtering and column sorting over the whole set
(sort keys are raw values; display cells are formatted). The SwiftUI side renders
the columns/rows generically.
"""

from __future__ import annotations


def _f(value, digits=2):
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value, digits=2):
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _raw_pct(value, digits=2):
    """Format a value already expressed in percent (e.g. coupon 13.0 -> '13.00%')."""
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _spec(pairs) -> list[dict]:
    return [{"label": label, "value": ("—" if value is None else str(value))} for label, value in pairs]


def categories(ctx) -> dict:
    db = ctx.market_db
    sid = ctx.snapshot.snapshot_id
    out = []
    if db is not None:
        out = [
            {"id": "bonds", "label": "Bonds", "count": len(db.get_real_bonds(sid, limit=None))},
            {"id": "equities", "label": "Equities", "count": len(db.get_equity_quotes(sid))},
            {"id": "commodities", "label": "Commodities", "count": len(db.get_commodity_quotes(sid))},
            {"id": "fx", "label": "FX", "count": len(db.get_fx_rates(sid))},
        ]
    return {"categories": [c for c in out if c["count"] > 0]}


def catalog(ctx, category: str, search: str | None = None, limit: int = 500,
            board: str | None = None, sort: str | None = None, desc: bool = False) -> dict:
    db = ctx.market_db
    sid = ctx.snapshot.snapshot_id
    if db is None:
        return {"category": category, "columns": [], "rows": [], "boards": []}
    builder = {
        "bonds": _bonds, "equities": _equities,
        "commodities": _commodities, "fx": _fx,
    }.get(category)
    if builder is None:
        return {"category": category, "columns": [], "rows": [], "boards": []}
    try:
        columns, rows = builder(db, sid)
    except Exception as exc:  # never 500 the catalog over one bad row
        return {"category": category, "columns": [], "rows": [], "boards": [], "error": str(exc)}

    boards = sorted({r["board"] for r in rows if r.get("board")})

    if board:
        rows = [r for r in rows if r.get("board") == board]
    needle = (search or "").lower().strip()
    if needle:
        rows = [r for r in rows if needle in " ".join(str(c) for c in r["cells"]).lower()]

    if sort:
        keys = [c["key"] for c in columns]
        if sort in keys:
            idx = keys.index(sort)

            def sort_key(r):
                v = r.get("sort", [None] * len(keys))[idx] if idx < len(r.get("sort", [])) else None
                missing = v is None
                if isinstance(v, str):
                    return (missing, 0.0, v.lower())
                return (missing, float(v) if v is not None else 0.0, "")

            rows = sorted(rows, key=sort_key, reverse=desc)

    rows = rows[:limit]
    clean = [{"id": r["id"], "cells": r["cells"], "spec": r["spec"]} for r in rows]
    return {"category": category, "columns": columns, "rows": clean,
            "boards": boards, "count": len(clean)}


def _bonds(db, sid):
    columns = [{"key": k, "label": v} for k, v in [
        ("secid", "SECID"), ("issuer", "Issuer"), ("board", "Board"),
        ("coupon", "Coupon"), ("mat", "Maturity"), ("clean", "Clean"), ("ytm", "YTM")]]
    rows = []
    for r in sorted(db.get_real_bonds(sid, limit=None), key=lambda x: -(x.get("volume") or 0)):
        rows.append({
            "id": r["secid"], "board": r.get("board"),
            "cells": [r["secid"], r.get("issuer") or "", r.get("board") or "",
                      _raw_pct(r.get("coupon_percent")), r.get("mat_date") or "—",
                      _f(r.get("clean_price")), _pct(r.get("ytm"))],
            "sort": [r["secid"], r.get("issuer") or "", r.get("board") or "",
                     _num(r.get("coupon_percent")), r.get("mat_date") or "",
                     _num(r.get("clean_price")), _num(r.get("ytm"))],
            "spec": _spec([
                ("SECID", r.get("secid")), ("ISIN", r.get("isin")), ("Issuer", r.get("issuer")),
                ("Board", r.get("board")), ("Currency", r.get("currency")),
                ("Face value", r.get("facevalue")), ("Coupon %", r.get("coupon_percent")),
                ("Coupon period (days)", r.get("coupon_period")), ("Next coupon", r.get("next_coupon")),
                ("Maturity", r.get("mat_date")), ("Offer date", r.get("offer_date")),
                ("List level", r.get("list_level")), ("Clean price", r.get("clean_price")),
                ("Accrued", r.get("accruedint")), ("YTM", r.get("ytm")), ("Volume", r.get("volume")),
            ]),
        })
    return columns, rows


def _equities(db, sid):
    columns = [{"key": k, "label": v} for k, v in [
        ("secid", "SECID"), ("board", "Board"), ("last", "Last"),
        ("prev", "Prev"), ("chg", "Chg %"), ("vol", "Volume")]]
    rows = []
    for r in sorted(db.get_equity_quotes(sid), key=lambda x: -(x.get("volume") or 0)):
        last, prev = r.get("last"), r.get("prevprice")
        chg = ((last - prev) / prev * 100) if (last and prev) else None
        rows.append({
            "id": r["secid"], "board": r.get("board"),
            "cells": [r["secid"], r.get("board") or "", _f(last), _f(prev),
                      (f"{chg:+.2f}%" if chg is not None else "—"), _f(r.get("volume"), 0)],
            "sort": [r["secid"], r.get("board") or "", _num(last), _num(prev), chg, _num(r.get("volume"))],
            "spec": _spec([
                ("SECID", r.get("secid")), ("Board", r.get("board")), ("Last", last),
                ("Previous", prev), ("Change %", round(chg, 3) if chg is not None else None),
                ("Volume", r.get("volume")),
            ]),
        })
    return columns, rows


def _commodities(db, sid):
    columns = [{"key": k, "label": v} for k, v in [
        ("asset", "Asset"), ("secid", "Contract"), ("expiry", "Expiry"),
        ("settle", "Settle"), ("oi", "Open int"), ("vol", "Volume")]]
    rows = []
    for r in sorted(db.get_commodity_quotes(sid), key=lambda x: (x.get("asset") or "", x.get("expiry") or "")):
        rows.append({
            "id": r.get("secid") or f"{r.get('asset')}-{r.get('expiry')}", "board": r.get("asset"),
            "cells": [r.get("asset") or "", r.get("secid") or "", r.get("expiry") or "—",
                      _f(r.get("settle")), _f(r.get("open_interest"), 0), _f(r.get("volume"), 0)],
            "sort": [r.get("asset") or "", r.get("secid") or "", r.get("expiry") or "",
                     _num(r.get("settle")), _num(r.get("open_interest")), _num(r.get("volume"))],
            "spec": _spec([
                ("Asset", r.get("asset")), ("Contract", r.get("secid")), ("Expiry", r.get("expiry")),
                ("Settle", r.get("settle")), ("Open interest", r.get("open_interest")), ("Volume", r.get("volume")),
            ]),
        })
    return columns, rows


def _fx(db, sid):
    columns = [{"key": k, "label": v} for k, v in [("pair", "Pair"), ("rate", "Rate")]]
    rows = []
    for pair, rate in sorted(db.get_fx_rates(sid).items()):
        rows.append({
            "id": pair, "board": None,
            "cells": [pair, _f(rate, 4)],
            "sort": [pair, _num(rate)],
            "spec": _spec([("Pair", pair), ("Rate", rate)]),
        })
    return columns, rows
