"""Issuer credit layer (ответ на В3): z-спреды облигаций эмитента → hazard-
кривая (credit triangle λ = s/(1−R)) с recovery из рейтинговой корзины
АКРА / Эксперт РА (базовое допущение — агентства recovery не публикуют).
"""

from __future__ import annotations

from api import realbonds
from curves.hazard import hazard_curve_from_corp_spreads
from infra import ratings

_MAX_BONDS = 8          # z-spread solve is a root search per bond — cap it


def _issuer_bonds(ctx, query: str) -> list[dict]:
    """Bonds of one issuer from the continuous store. NB: issuer_ru у
    облигаций — короткое имя ВЫПУСКА («ГазпромКP6»); матчим по подстроке в
    Python — sqlite LOWER() не берёт кириллицу."""
    db = ctx.market_db
    needle = query.casefold()
    rows = db._query(                                     # noqa: SLF001
        "SELECT secid, issuer_ru FROM instrument_ref WHERE category='bonds'")
    return [r for r in rows
            if needle in (r.get("issuer_ru") or "").casefold()][:40]


def issuer_hazard_curve(ctx, query: str):
    """Build the issuer HazardCurve + metadata; reused by the /credit endpoint,
    the credit-product pricers and the XVA workstation.

    Returns (HazardCurve, meta) where meta carries issuer/rating/recovery/
    bond points/errors."""
    bonds = _issuer_bonds(ctx, query)
    if not bonds:
        raise ValueError(f"эмитент '{query}' не найден среди облигаций")
    issuer = bonds[0].get("issuer_ru") or query

    rating = ratings.lookup(ctx.market_db.conn, issuer) or ratings.lookup(
        ctx.market_db.conn, query)
    recovery = rating["recovery"] if rating else 0.30
    recovery_source = (rating or {}).get("recovery_source", "baseline")

    points, errors = [], []
    for b in bonds[:25]:
        if len(points) >= _MAX_BONDS:
            break
        try:
            r = realbonds.reprice(ctx, b["secid"])
            z = r.get("z_spread_bps")
            cfs = r.get("cashflows") or []
            t = max((cf["t"] for cf in cfs), default=None)
            if z is None or not t or t <= 0.05:
                continue
            if abs(float(z)) > 3000:
                errors.append(f"{b['secid']}: z={z:.0f}bp — неликвид/стейл, пропущен")
                continue
            points.append({"secid": b["secid"], "T": round(float(t), 3),
                           "z_spread_bps": round(float(z), 1)})
        except Exception as exc:                          # noqa: BLE001
            errors.append(f"{b['secid']}: {exc}")
    if not points:
        raise ValueError(f"не удалось получить z-спреды для '{issuer}'"
                         + (f" ({errors[0]})" if errors else ""))

    points.sort(key=lambda p: p["T"])
    tenors = [p["T"] for p in points]
    spreads = [p["z_spread_bps"] / 10000.0 for p in points]
    curve = hazard_curve_from_corp_spreads(tenors, spreads, recovery,
                                           label=f"hazard {issuer}")
    meta = {
        "issuer": issuer,
        "query": query,
        "rating": {k: rating[k] for k in ("rating", "agency", "outlook",
                                          "rating_date", "stale")} if rating else None,
        "recovery": recovery,
        "recovery_source": recovery_source,
        "bonds": points,
        "errors": errors,
    }
    return curve, meta


def issuer_hazard(ctx, query: str) -> dict:
    """Per-issuer default curve: z-spread per bond -> hazard/PD term structure."""
    curve, meta = issuer_hazard_curve(ctx, query)
    tenors = [p["T"] for p in meta["bonds"]]
    grid = sorted({round(t, 2) for t in tenors} | {1.0, 3.0, 5.0})
    grid = [t for t in grid if t <= max(tenors) + 1e-9] or tenors
    return {
        **meta,
        "recovery_note": ("базовая шкала по рейтинговой корзине — агентства "
                          "recovery rate не публикуют"
                          if meta["recovery_source"] == "baseline" else ""),
        "hazard": [{"T": t, "lambda": round(curve.hazard(t), 6)} for t in grid],
        "pd": [{"T": t, "pd": round(1.0 - curve.survival(t), 6)} for t in grid],
        "method": "credit triangle λ = z/(1−R) по z-спредам облигаций эмитента",
    }


def ratings_table(ctx) -> dict:
    rows = ratings.all_ratings(ctx.market_db.conn)
    return {"ratings": rows, "count": len(rows),
            "recovery_note": "recovery — базовое допущение по корзинам",
            "stale": sum(1 for r in rows if r["stale"])}
