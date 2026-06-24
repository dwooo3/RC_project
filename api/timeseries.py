"""Historical time-series browser support (the 5-year backfill store).

Surfaces everything in the ``time_series`` table — index closes, equity closes,
КБД zero-rate tenors, CBR key rate / RUONIA — grouped for the Market Data
"History" section so any stored series can be charted and tabulated over a date
range. Snapshot-independent: history spans all dates, not one valuation date.
"""

from __future__ import annotations

# Index factors get their own group; everything else priced is an equity.
_INDEX_IDS = {"IMOEX", "RVI", "RGBI", "RUCBTRNS",
              "RUSFAR", "RUSFAR1W", "RUSFAR1M", "RUSFAR3M"}


def _base_id(factor_id: str) -> str:
    for suffix in (":price", ":rate", ":index"):
        if factor_id.endswith(suffix):
            return factor_id[: -len(suffix)]
    return factor_id


def _group_of(factor_id: str, kind: str) -> str:
    base = _base_id(factor_id)
    if kind == "rate" or base.startswith(("KBD:", "CBR_", "RUONIA")):
        return "rates"
    if base in _INDEX_IDS:
        return "indices"
    return "equities"


def _label(factor_id: str) -> str:
    base = _base_id(factor_id)
    if base.startswith("KBD:"):
        return "KBD " + base[4:]                      # KBD:5Y -> KBD 5Y
    if base in ("CBR_KEY_RATE", "CBR_KEYRATE"):
        return "CBR key rate"
    if base.startswith("RUSFAR") and len(base) > 6:
        return "RUSFAR " + base[6:]                   # RUSFAR1W -> RUSFAR 1W
    return base


_GROUP_LABELS = {"indices": "Indices", "equities": "Equities", "rates": "Rates & curve"}
_GROUP_ORDER = ["indices", "rates", "equities"]


def catalog(ctx) -> dict:
    """Available historical series, grouped (indices / rates / equities)."""
    db = ctx.market_db
    rows = db.list_time_series_factors() if db is not None else []
    groups: dict[str, list] = {g: [] for g in _GROUP_ORDER}
    for r in rows:
        fid, kind = r["factor_id"], r.get("kind") or ""
        if not (r.get("points") or 0):
            continue
        g = _group_of(fid, kind)
        groups.setdefault(g, []).append({
            "id": fid,
            "label": _label(fid),
            "kind": kind,
            "is_rate": kind == "rate" or _base_id(fid).startswith(("KBD:", "CBR_", "RUONIA")),
            "points": int(r["points"]),
            "start": str(r.get("start") or "")[:10],
            "end": str(r.get("end") or "")[:10],
        })
    out = []
    for g in _GROUP_ORDER:
        # Dedup series that resolve to the same label (e.g. CBR_KEY_RATE vs
        # CBR_KEYRATE:rate from different ingestors), keeping the longer one.
        best: dict[str, dict] = {}
        for s in groups.get(g, []):
            cur = best.get(s["label"])
            if cur is None or s["points"] > cur["points"]:
                best[s["label"]] = s
        series = sorted(best.values(), key=lambda s: s["label"])
        if series:
            out.append({"id": g, "label": _GROUP_LABELS[g], "series": series})
    return {"groups": out, "count": sum(len(g["series"]) for g in out)}


def series(ctx, factor_id: str, frm: str | None = None, till: str | None = None) -> dict:
    """Points for one series over an optional [frm, till] ISO date window."""
    db = ctx.market_db
    raw = db.get_time_series(factor_id) if db is not None else []
    is_rate = _base_id(factor_id).startswith(("KBD:", "CBR_", "RUONIA"))
    points = []
    for r in raw:
        d = str(r.get("dt") or "")[:10]
        v = r.get("value")
        if not d or v is None:
            continue
        if frm and d < frm:
            continue
        if till and d > till:
            continue
        points.append({"date": d, "value": float(v)})
    return {
        "factor_id": factor_id,
        "label": _label(factor_id),
        "is_rate": is_rate,
        "unit": "%" if is_rate else "",
        "points": points,
        "count": len(points),
    }
