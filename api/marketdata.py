"""Market-data browser support: snapshot list + raw curve term-structures.

Lets the Market Data screen pick a snapshot date and view every curve's stored
nodes (tenor / zero rate / discount factor) as a table + marked chart points.
"""

from __future__ import annotations

from api.instruments import CURVE_LABELS


def snapshots(ctx) -> dict:
    db = ctx.market_db
    active = ctx.snapshot.snapshot_id
    rows = db.list_snapshots() if db is not None else []
    out = [
        {"snapshot_id": r["snapshot_id"],
         "valuation_date": str(r.get("valuation_date") or "")[:10],
         "source": r.get("source"), "quality": r.get("quality"),
         "active": r["snapshot_id"] == active}
        for r in rows
    ]
    if not any(s["active"] for s in out):
        out.insert(0, {"snapshot_id": active, "valuation_date": str(getattr(ctx.snapshot, "valuation_date", "") or "")[:10],
                       "source": "active", "quality": "", "active": True})
    return {"active": active, "snapshots": out}


def curves(ctx, snapshot_id: str | None = None) -> dict:
    db = ctx.market_db
    sid = snapshot_id or ctx.snapshot.snapshot_id
    out = []
    if db is not None:
        for cid in sorted(db.list_curve_ids(sid)):
            points = []
            for p in db.get_curve_points(sid, cid):
                t = p.get("tenor")
                if t is None:
                    continue
                points.append({
                    "tenor": float(t),
                    "zero": float(p["zero_rate"]) if p.get("zero_rate") is not None else None,
                    "discount": float(p["discount_factor"]) if p.get("discount_factor") is not None else None,
                })
            points.sort(key=lambda x: x["tenor"])
            if points:
                out.append({"id": cid, "label": CURVE_LABELS.get(cid, cid), "points": points})
    return {"snapshot_id": sid, "curves": out}
