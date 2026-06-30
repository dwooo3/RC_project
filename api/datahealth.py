"""Data-health API (Market section).

Surfaces the *computed* validation status of the active snapshot (completeness /
freshness / production-eligibility) plus a summary of recent ingest runs, so the
user can see what actually loaded — partial loads and ingest failures no longer
hide behind a metadata ``quality=OK``. Addresses the audit's MD-008/MD-009.
"""

from __future__ import annotations


def validation(ctx, snapshot_id: str | None = None) -> dict:
    """Persisted validation report (MD-002) for a snapshot + its audit history.
    Computes + persists a fresh report (deduped), then returns it with history."""
    db = ctx.market_db
    if db is None:
        return {"available": False}
    if not snapshot_id:
        try:
            snapshot_id = ctx.snapshot.snapshot_id
        except Exception:
            snapshot_id = (db.latest_snapshot_meta() or {}).get("snapshot_id")
    if not snapshot_id:
        return {"available": False}
    from infra.jobs.data_quality import persist_quality_report
    report = persist_quality_report(db, snapshot_id)
    return {
        "available": True,
        "snapshot_id": snapshot_id,
        "status": report["status"],
        "production_eligible": report["production_eligible"],
        "completeness_pct": report["completeness_pct"],
        "freshness_days": report["staleness_days"],
        "alerts": report["alerts"],
        "history": db.list_validation_reports(snapshot_id),
    }


def health(ctx) -> dict:
    db = ctx.market_db
    if db is None:
        return {"available": False}

    try:
        snapshot_id = ctx.snapshot.snapshot_id
    except Exception:
        meta = db.latest_snapshot_meta() or {}
        snapshot_id = meta.get("snapshot_id")
    if not snapshot_id:
        return {"available": False}

    from infra.jobs.data_quality import snapshot_quality_report
    report = snapshot_quality_report(db, snapshot_id)

    # ingest run summary + recent failures (with timestamps)
    log = db.recent_ingest_log(80)
    counts: dict[str, int] = {}
    for r in log:
        counts[r.get("status", "?")] = counts.get(r.get("status", "?"), 0) + 1
    failures = [
        {"endpoint": r.get("endpoint", ""), "error": (r.get("error") or "")[:200],
         "at": r.get("finished_at") or r.get("started_at")}
        for r in log if r.get("status") == "error" and r.get("error")
    ][:12]

    return {
        "available": True,
        "snapshot_id": report["snapshot_id"],
        "source": report["source"],
        "valuation_date": report["valuation_date"],
        "status": report["status"],
        "production_eligible": report["production_eligible"],
        "is_demo": report["is_demo"],
        "completeness_pct": report["completeness_pct"],
        "staleness_days": report["staleness_days"],
        "alerts": report["alerts"],
        "checks": report["checks"],
        "ingest": {"ok": counts.get("ok", 0), "error": counts.get("error", 0),
                   "skipped": counts.get("skipped", 0)},
        "failures": failures,
    }
