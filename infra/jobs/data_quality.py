"""
Data-quality report for the local market-data DB (Stage II.2).

Summarises, for a snapshot: which components are present (curves, FX, vols,
bond schedules, history depth), how fresh the snapshot is versus today, and any
ingest errors logged for the run. Drives the daily-job alerting and a future
Data Health dashboard. Pure reads — no network.
"""

from __future__ import annotations

from datetime import date

# Components a complete EOD snapshot is expected to carry.
EXPECTED_CURVES = ["GCURVE_RUB", "CORP_T1", "REALCURVE_OFZIN",
                   "FXFWD_USD", "KEYRATE_RUB", "RUONIA_RUB"]
EXPECTED_FX = ["USD/RUB", "EUR/RUB", "CNY/RUB"]
MIN_VOL_POINTS = 100
MIN_HISTORY_DAYS = 60


def snapshot_quality_report(db, snapshot_id: str,
                            valuation_date: date | None = None) -> dict:
    """Structured completeness/freshness/error report for one snapshot."""
    curves = set(db.list_curve_ids(snapshot_id))
    fx = db.get_fx_rates(snapshot_id)
    vol_points = db.get_vol_points(snapshot_id)
    bonds = db.get_bond_quotes(snapshot_id)

    missing_curves = [c for c in EXPECTED_CURVES if c not in curves]
    missing_fx = [p for p in EXPECTED_FX if p not in fx]
    vol_underlyings = {p["underlying"] for p in vol_points}

    checks = {
        "curves_present": sorted(curves),
        "curves_missing": missing_curves,
        "fx_present": sorted(fx),
        "fx_missing": missing_fx,
        "vol_points": len(vol_points),
        "vol_underlyings": len(vol_underlyings),
        "bond_quotes": len(bonds),
    }

    alerts: list[str] = []
    if missing_curves:
        alerts.append(f"missing curves: {', '.join(missing_curves)}")
    if missing_fx:
        alerts.append(f"missing FX: {', '.join(missing_fx)}")
    if len(vol_points) < MIN_VOL_POINTS:
        alerts.append(f"thin vol surface: {len(vol_points)} < {MIN_VOL_POINTS} points")

    # freshness vs today
    meta = db.get_snapshot_meta(snapshot_id) or {}
    staleness_days = None
    if meta.get("valuation_date"):
        try:
            vd = date.fromisoformat(str(meta["valuation_date"])[:10])
            staleness_days = ((valuation_date or date.today()) - vd).days
        except ValueError:
            pass
    if staleness_days is not None and staleness_days > 4:
        alerts.append(f"stale snapshot: {staleness_days} days old")

    # ingest errors for context (last run)
    errors = [r for r in db.recent_ingest_log(60)
              if r.get("status") in ("error",) and r.get("error")]

    score = _completeness_score(checks)
    status = "OK" if not alerts else ("WARN" if score >= 0.7 else "FAIL")
    # Production-eligible only when the COMPUTED report passes (not just the
    # snapshot's metadata `quality` field, which can read OK on a partial load)
    # and the data comes from a real provider. WARN (e.g. stale) needs override.
    source = str(meta.get("source", "?"))
    is_demo = source.upper() in ("DEMO", "MANUAL")
    return {
        "snapshot_id": snapshot_id,
        "source": meta.get("source", "?"),
        "quality": meta.get("quality", "?"),
        "valuation_date": meta.get("valuation_date"),
        "staleness_days": staleness_days,
        "completeness_pct": round(score * 100, 1),
        "checks": checks,
        "alerts": alerts,
        "ingest_errors": [f"{r['endpoint']}: {r['error'][:120]}" for r in errors[:8]],
        "status": status,
        "is_demo": is_demo,
        "production_eligible": status == "OK" and not is_demo,
    }


def history_depth_report(db, factors: list[str] | None = None) -> dict:
    """Per-factor time_series depth, flagging series below MIN_HISTORY_DAYS."""
    rows = db._query(  # noqa: SLF001 — internal job
        "SELECT factor_id, kind, COUNT(*) n, MIN(dt) lo, MAX(dt) hi "
        "FROM time_series GROUP BY factor_id, kind ORDER BY n DESC")
    if factors:
        rows = [r for r in rows if r["factor_id"] in factors]
    thin = [r["factor_id"] for r in rows if r["n"] < MIN_HISTORY_DAYS]
    return {
        "n_series": len(rows),
        "total_points": sum(r["n"] for r in rows),
        "deepest": [(r["factor_id"], r["n"]) for r in rows[:5]],
        "thin_series": thin,
        "alerts": ([f"{len(thin)} series below {MIN_HISTORY_DAYS} days"] if thin else []),
    }


def _completeness_score(checks: dict) -> float:
    parts = [
        1.0 - len(checks["curves_missing"]) / max(len(EXPECTED_CURVES), 1),
        1.0 - len(checks["fx_missing"]) / max(len(EXPECTED_FX), 1),
        1.0 if checks["vol_points"] >= MIN_VOL_POINTS else checks["vol_points"] / MIN_VOL_POINTS,
        1.0 if checks["bond_quotes"] > 0 else 0.0,
    ]
    return sum(parts) / len(parts)


def format_report(report: dict, history: dict | None = None) -> str:
    """Human-readable one-screen summary for CLI / logs."""
    lines = [
        f"Snapshot {report['snapshot_id']}  [{report['status']}]  "
        f"source={report['source']} quality={report['quality']} "
        f"complete={report['completeness_pct']}%",
    ]
    if report.get("staleness_days") is not None:
        lines.append(f"  freshness: {report['staleness_days']} days old")
    c = report["checks"]
    lines.append(f"  curves: {len(c['curves_present'])} present"
                 + (f", missing {c['curves_missing']}" if c["curves_missing"] else ""))
    lines.append(f"  fx: {c['fx_present']}"
                 + (f", missing {c['fx_missing']}" if c["fx_missing"] else ""))
    lines.append(f"  vol: {c['vol_points']} points / {c['vol_underlyings']} underlyings")
    lines.append(f"  bonds: {c['bond_quotes']} quotes")
    if history:
        lines.append(f"  history: {history['n_series']} series, "
                     f"{history['total_points']} points; deepest {history['deepest'][:3]}")
        if history["thin_series"]:
            lines.append(f"  thin history: {len(history['thin_series'])} series")
    for a in report["alerts"]:
        lines.append(f"  ALERT: {a}")
    for e in report["ingest_errors"]:
        lines.append(f"  ingest-error: {e}")
    return "\n".join(lines)
