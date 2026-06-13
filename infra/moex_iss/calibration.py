"""
Corporate-curve calibration from bonds (MOEX_MARKET_DATA_INTEGRATION_PROMPT.md
§2 Credit, §8 Phase B).

Issuer/sector spread term-structures are derived from traded corporate bond YTMs
relative to the government zero-coupon curve (КБД / GCURVE_RUB):

    spread_i = YTM_i - GCURVE_RUB.zero(tenor_i)
    corp_zero(tenor) = GCURVE_RUB.zero(tenor) + spread(tenor)

Bonds are grouped into tiers by listing level (LISTLEVEL 1/2/3 -> T1/T2/T3), a
robust proxy for credit quality. Pure functions; ingestion wires them to the DB.
"""

from __future__ import annotations

from datetime import date


TIER_BY_LIST_LEVEL = {1: "T1", 2: "T2", 3: "T3"}


def bond_tenor(mat_date: str, valuation_date: date) -> float | None:
    """ACT/365 year fraction from valuation date to maturity (None if invalid/past)."""
    try:
        mat = date.fromisoformat(str(mat_date)[:10])
    except (TypeError, ValueError):
        return None
    days = (mat - valuation_date).days
    return days / 365.0 if days > 0 else None


def tier_for(list_level) -> str:
    try:
        return TIER_BY_LIST_LEVEL.get(int(list_level), "T3")
    except (TypeError, ValueError):
        return "T3"


def issuer_spreads(gcurve, bonds: list[dict], valuation_date: date) -> list[dict]:
    """
    Per-bond spread vs the government curve.

    bonds: rows with secid, ytm (decimal), mat_date, list_level.
    Returns rows {secid, tenor, spread, tier} for bonds with a valid tenor.
    """
    out: list[dict] = []
    for b in bonds:
        tenor = bond_tenor(b.get("mat_date"), valuation_date)
        ytm = b.get("ytm")
        if tenor is None or ytm is None:
            continue
        govt = gcurve.rate(tenor)
        out.append({
            "secid": b.get("secid"),
            "tenor": tenor,
            "spread": float(ytm) - float(govt),
            "tier": tier_for(b.get("list_level")),
        })
    return out


def _dedupe_average(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Average values at duplicate tenors; return sorted by tenor."""
    buckets: dict[float, list[float]] = {}
    for tenor, value in points:
        buckets.setdefault(round(tenor, 6), []).append(value)
    return sorted((t, sum(v) / len(v)) for t, v in buckets.items())


def build_corporate_curve_points(
    gcurve,
    spreads: list[dict],
    tier: str,
    *,
    min_bonds: int = 3,
) -> list[tuple[float, float, float | None]]:
    """
    Build (tenor, zero_rate, df=None) points for one tier.

    Returns [] when the tier has fewer than ``min_bonds`` bonds (insufficient to
    calibrate a curve). Discount factors are left None and validated downstream.
    """
    tier_rows = [(s["tenor"], s["spread"]) for s in spreads if s["tier"] == tier]
    if len(tier_rows) < min_bonds:
        return []
    averaged = _dedupe_average(tier_rows)
    if len(averaged) < min_bonds:
        return []
    return [(tenor, gcurve.rate(tenor) + spread, None) for tenor, spread in averaged]


def representative_spread(spreads: list[dict], tier: str) -> float | None:
    """Mean spread for a tier (e.g. for credit_spreads metadata)."""
    vals = [s["spread"] for s in spreads if s["tier"] == tier]
    return (sum(vals) / len(vals)) if vals else None


# ── Stage I.2: bucketed calibration for wide universes (TQCB ~2-3k bonds) ──

TENOR_BUCKETS = (0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0)


def build_corporate_curve_points_bucketed(
    gcurve,
    spreads: list[dict],
    tier: str,
    *,
    buckets: tuple = TENOR_BUCKETS,
    min_bonds_per_bucket: int = 3,
    min_buckets: int = 3,
    spread_bounds: tuple = (-0.02, 0.30),
) -> list[tuple[float, float, float | None]]:
    """
    Robust tier curve from a wide bond universe: per-bond spreads are snapped
    to the nearest tenor bucket, hard-bounded (kills stale/defaulted prints),
    then reduced by the bucket MEDIAN. Raw-tenor averaging (the small-universe
    builder above) produces a noisy, non-monotonic mess on thousands of TQCB
    quotes; bucketed medians survive it.
    """
    import statistics

    by_bucket: dict[float, list[float]] = {}
    for s in spreads:
        if s["tier"] != tier:
            continue
        sp = s["spread"]
        if not (spread_bounds[0] <= sp <= spread_bounds[1]):
            continue
        bucket = min(buckets, key=lambda b: abs(b - s["tenor"]))
        if s["tenor"] > buckets[-1] * 1.5:
            continue                                  # beyond the calibrated grid
        by_bucket.setdefault(bucket, []).append(sp)

    pts = []
    for bucket in buckets:
        vals = by_bucket.get(bucket, [])
        if len(vals) < min_bonds_per_bucket:
            continue
        med = statistics.median(vals)
        pts.append((bucket, gcurve.rate(bucket) + med, None))
    return pts if len(pts) >= min_buckets else []
