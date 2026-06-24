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


def _overnight_anchor(db, sid: str, cid: str) -> float | None:
    """O/N rate (continuous) used to anchor the short end of a curve on the grid.

    OFZ (GCURVE) is anchored at the CBR key rate; RUONIA curves at the RUONIA
    overnight fixing. Others get no anchor (short end held flat).
    """
    if cid in ("GCURVE_RUB", "ZCB_OFZ_RUB"):
        pts = db.get_curve_points(sid, "KEYRATE_RUB")
        return float(pts[0]["zero_rate"]) if pts and pts[0].get("zero_rate") is not None else None
    if cid.startswith("RUONIA"):
        series = db.get_time_series("RUONIA:rate", "rate")
        if series:
            return float(series[-1]["value"])
    return None


def curves(ctx, snapshot_id: str | None = None) -> dict:
    from api.curve_grid import standardize_curve

    db = ctx.market_db
    sid = snapshot_id or ctx.snapshot.snapshot_id
    out = []
    if db is not None:
        for cid in sorted(db.list_curve_ids(sid)):
            native = []
            for p in db.get_curve_points(sid, cid):
                t = p.get("tenor")
                if t is None:
                    continue
                native.append((
                    float(t),
                    float(p["zero_rate"]) if p.get("zero_rate") is not None else None,
                    float(p["discount_factor"]) if p.get("discount_factor") is not None else None,
                ))
            native.sort(key=lambda x: x[0])
            if not native:
                continue
            # Standardise onto the canonical pillar grid (display only).
            std = standardize_curve(native, overnight_rate=_overnight_anchor(db, sid, cid))
            if len(std) >= 2:
                points = [{"tenor": p["tenor"], "zero": p["zero"], "discount": p["discount"]} for p in std]
            else:                                  # fallback: native nodes as-is
                points = [{"tenor": t, "zero": z, "discount": d} for (t, z, d) in native]
            out.append({"id": cid, "label": CURVE_LABELS.get(cid, cid), "points": points})
    return {"snapshot_id": sid, "curves": out}
