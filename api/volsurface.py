"""Volatility-surface API (Market section).

Surfaces come from the self-implied option IVs in ``vol_points`` (latest
snapshot). Each underlying's surface is a family of smiles (IV vs strike) per
expiry — rendered as charts + a table, styled like the option board. An OTC
section is planned later.
"""

from __future__ import annotations


def list_underlyings(ctx) -> dict:
    db = ctx.market_db
    rows = db.vol_surface_underlyings() if db is not None else []
    return {
        "as_of": (db.latest_vol_snapshot() or "").replace("moex-", "") if db is not None else "",
        "underlyings": [{"code": r["underlying"], "expiries": r["expiries"], "points": r["points"]}
                        for r in rows],
        "count": len(rows),
    }


def surface(ctx, underlying: str) -> dict:
    db = ctx.market_db
    pts = db.vol_surface_points(underlying) if db is not None else []
    by_exp: dict[str, list] = {}
    for p in pts:
        if p.get("iv") is None or p.get("strike") is None:
            continue
        by_exp.setdefault(p["expiry"], []).append({"strike": float(p["strike"]), "iv": float(p["iv"])})

    expiries = []
    for exp in sorted(by_exp):
        smile = sorted(by_exp[exp], key=lambda x: x["strike"])
        strikes = [s["strike"] for s in smile]
        mid = (min(strikes) + max(strikes)) / 2 if strikes else 0.0
        atm = min(smile, key=lambda s: abs(s["strike"] - mid))["iv"] if smile else None
        expiries.append({"expiry": exp, "atm": atm, "points": smile})

    return {"underlying": underlying, "expiries": expiries}
