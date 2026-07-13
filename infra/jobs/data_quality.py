"""
Data-quality report for the local market-data DB (Stage II.2).

Summarises, for a snapshot: which components are present (curves, FX, vols,
bond schedules, history depth), how fresh the snapshot is versus today, and any
ingest errors logged for the run. Drives the daily-job alerting and a future
Data Health dashboard. Pure reads — no network.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime

from infra.moex_iss.vol_surface import (
    PRIMARY_IV_METHOD,
    iv30_representative,
    primary_iv_provenance_error,
    vol_lineage_diagnostics,
    vol_point_payload_error,
)

# Components a complete EOD snapshot is expected to carry.
EXPECTED_CURVES = ["GCURVE_RUB", "CORP_T1", "REALCURVE_OFZIN",
                   "FXFWD_USD", "KEYRATE_RUB", "RUONIA_RUB"]
EXPECTED_FX = ["USD/RUB", "EUR/RUB", "CNY/RUB"]
MIN_VOL_POINTS = 100
MIN_HISTORY_DAYS = 60
IV30_VALUE_REL_TOLERANCE = 1e-6
IV30_VALUE_ABS_TOLERANCE = 1e-8
QUALITY_CONTRACT_VERSION = "2026-07-13.snapshot-binding-v3"


def _canonical_hash_value(value):
    """Stable JSON form for unordered DB rows and cross-dialect scalar types."""
    if isinstance(value, dict):
        return {
            str(key): _canonical_hash_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set)):
        items = [_canonical_hash_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item, sort_keys=True, separators=(",", ":"), default=str),
        )
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    return value


def snapshot_data_fingerprint(
    db, snapshot_id: str, *, _inside_read_snapshot: bool = False,
) -> str:
    """Hash all stored inputs that drive snapshot quality or valuation.

    Validation reports live in an append-only audit table while the snapshot
    payload tables are currently mutable.  The fingerprint binds a report to
    the exact manifest, curves, FX, raw/provenance vol rows, bonds and canonical
    IV30 levels it certified, without requiring a destructive schema change.
    """
    read_snapshot = getattr(db, "read_snapshot", None)
    if not _inside_read_snapshot and callable(read_snapshot):
        with read_snapshot():
            return snapshot_data_fingerprint(
                db, snapshot_id, _inside_read_snapshot=True)

    meta = db.get_snapshot_meta(snapshot_id) or {}
    curves = []
    for curve_id in sorted(db.list_curve_ids(snapshot_id)):
        curves.append({
            "curve_id": curve_id,
            "header": db.get_curve(snapshot_id, curve_id) or {},
            "points": db.get_curve_points(snapshot_id, curve_id),
        })
    valuation_raw = meta.get("valuation_date")
    if isinstance(valuation_raw, datetime):
        valuation_day = valuation_raw.date().isoformat()
    elif isinstance(valuation_raw, date):
        valuation_day = valuation_raw.isoformat()
    else:
        try:
            token = str(valuation_raw or "").strip()
            valuation_day = (
                date.fromisoformat(token).isoformat()
                if len(token) == 10
                else datetime.fromisoformat(
                    token.replace("Z", "+00:00")).date().isoformat()
            )
        except ValueError:
            valuation_day = None
    iv30 = {}
    for point in db.get_vol_points(snapshot_id):
        underlying = str(point.get("underlying") or "").strip()
        if underlying and underlying not in iv30:
            iv30[underlying] = [
                row for row in db.get_time_series(f"IV30:{underlying}", "vol")
                if valuation_day is not None
                and str(row.get("dt") or "")[:10] == valuation_day
            ]
    payload = _canonical_hash_value({
        "snapshot_id": snapshot_id,
        "manifest": meta,
        "curves": curves,
        "fx": db.get_fx_rates(snapshot_id),
        "vol_points": db.get_vol_points(snapshot_id),
        "vol_observations": db.get_vol_point_observations(snapshot_id),
        "bond_quotes": db.get_bond_quotes(snapshot_id),
        "iv30": iv30,
    })
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def snapshot_quality_report(
    db,
    snapshot_id: str,
    valuation_date: date | None = None,
    *,
    _inside_read_snapshot: bool = False,
) -> dict:
    """Structured completeness/freshness/error report for one snapshot."""
    read_snapshot = getattr(db, "read_snapshot", None)
    if not _inside_read_snapshot and callable(read_snapshot):
        with read_snapshot():
            return snapshot_quality_report(
                db,
                snapshot_id,
                valuation_date,
                _inside_read_snapshot=True,
            )
    curves = set(db.list_curve_ids(snapshot_id))
    fx = db.get_fx_rates(snapshot_id)
    vol_points = db.get_vol_points(snapshot_id)
    vol_observations = db.get_vol_point_observations(snapshot_id)
    bonds = db.get_bond_quotes(snapshot_id)
    meta = db.get_snapshot_meta(snapshot_id) or {}

    def strict_day(value) -> str | None:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if not isinstance(value, str):
            return None
        raw = value.strip()
        try:
            parsed = (
                date.fromisoformat(raw)
                if len(raw) == 10
                else datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
            )
        except ValueError:
            return None
        return parsed.isoformat()

    snapshot_date = strict_day(meta.get("valuation_date"))

    missing_curves = [c for c in EXPECTED_CURVES if c not in curves]
    missing_fx = [p for p in EXPECTED_FX if p not in fx]
    vol_underlyings = {p["underlying"] for p in vol_points}
    observation_underlyings = {p["underlying"] for p in vol_observations}

    lineage = vol_lineage_diagnostics(vol_points, vol_observations)
    missing_observation_keys = lineage["missing_observation_keys"]
    extra_observation_keys = lineage["extra_observation_keys"]
    verified_vol_observations = [
        row for row in vol_observations
        if snapshot_date is not None
        and primary_iv_provenance_error(row, snapshot_date) is None
        and vol_point_payload_error(row) is None
    ]

    iv30_underlyings = []
    iv30_value_mismatch_underlyings = []
    iv30_duplicate_underlyings = []
    iv30_representative_not_ok_underlyings = []
    if snapshot_date:
        observation_day = date.fromisoformat(snapshot_date)
        for underlying in sorted(vol_underlyings):
            series = db.get_time_series(f"IV30:{underlying}", "vol")
            day_rows = [
                row for row in series
                if strict_day(row.get("dt")) == snapshot_date
            ]
            if len(day_rows) > 1:
                iv30_duplicate_underlyings.append(underlying)
                continue
            representative = iv30_representative(
                [
                    row for row in vol_observations
                    if str(row.get("underlying") or "") == underlying
                    and row.get("method") == PRIMARY_IV_METHOD
                ],
                observation_day,
            )
            if (not representative.get("accepted")
                    or representative.get("quality") != "OK"):
                iv30_representative_not_ok_underlyings.append(underlying)
                continue
            if not day_rows:
                continue
            try:
                value = float(day_rows[0].get("value"))
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(value) or not 0.01 < value < 3.0:
                continue
            if not math.isclose(
                    value, float(representative["value"]),
                    rel_tol=IV30_VALUE_REL_TOLERANCE,
                    abs_tol=IV30_VALUE_ABS_TOLERANCE):
                iv30_value_mismatch_underlyings.append(underlying)
                continue
            iv30_underlyings.append(underlying)
    iv30_missing_underlyings = sorted(vol_underlyings - set(iv30_underlyings))

    checks = {
        "contract_version": QUALITY_CONTRACT_VERSION,
        "snapshot_fingerprint": snapshot_data_fingerprint(db, snapshot_id),
        "curves_present": sorted(curves),
        "curves_missing": missing_curves,
        "fx_present": sorted(fx),
        "fx_missing": missing_fx,
        "vol_points": len(vol_points),
        "vol_underlyings": len(vol_underlyings),
        "vol_underlying_ids": sorted(vol_underlyings),
        "vol_observation_points": len(vol_observations),
        "vol_observation_points_verified": len(verified_vol_observations),
        "vol_observation_underlyings": sorted(observation_underlyings),
        "vol_key_coverage_complete": lineage["key_coverage_complete"],
        "vol_payload_match_complete": lineage["payload_match_complete"],
        "vol_keys_missing_provenance": len(missing_observation_keys),
        "vol_keys_without_raw_point": len(extra_observation_keys),
        "vol_raw_payloads_invalid": len(lineage["invalid_raw_payloads"]),
        "vol_observation_payloads_invalid": len(
            lineage["invalid_observation_payloads"]),
        "vol_iv_value_mismatches": len(lineage["iv_value_mismatch_keys"]),
        "vol_observation_date": snapshot_date or None,
        "iv30_underlyings": iv30_underlyings,
        "iv30_missing_underlyings": iv30_missing_underlyings,
        "iv30_value_mismatch_underlyings": iv30_value_mismatch_underlyings,
        "iv30_duplicate_underlyings": iv30_duplicate_underlyings,
        "iv30_representative_not_ok_underlyings": (
            iv30_representative_not_ok_underlyings
        ),
        "bond_quotes": len(bonds),
    }

    alerts: list[str] = []
    if meta.get("valuation_date") and snapshot_date is None:
        alerts.append("invalid snapshot valuation date")
    if missing_curves:
        alerts.append(f"missing curves: {', '.join(missing_curves)}")
    if missing_fx:
        alerts.append(f"missing FX: {', '.join(missing_fx)}")
    if len(vol_points) < MIN_VOL_POINTS:
        alerts.append(f"thin vol surface: {len(vol_points)} < {MIN_VOL_POINTS} points")
    if vol_points:
        if not vol_observations:
            alerts.append(
                "vol observation provenance missing: raw surface cannot feed governed IV history")
        else:
            if not lineage["key_coverage_complete"]:
                alerts.append(
                    "vol observation key coverage mismatch: "
                    f"{len(missing_observation_keys)} raw points lack provenance; "
                    f"{len(extra_observation_keys)} provenance rows lack raw points")
            if (lineage["invalid_raw_payloads"]
                    or lineage["invalid_observation_payloads"]):
                alerts.append(
                    "invalid vol point payload: "
                    f"raw={len(lineage['invalid_raw_payloads'])}, "
                    f"provenance={len(lineage['invalid_observation_payloads'])}")
            if lineage["iv_value_mismatch_keys"]:
                alerts.append(
                    "raw/provenance IV value mismatch: "
                    f"{len(lineage['iv_value_mismatch_keys'])} points")
        if vol_observations and len(verified_vol_observations) != len(vol_observations):
            alerts.append(
                "unverified vol observation date/source/basis: "
                f"{len(verified_vol_observations)}/{len(vol_observations)} points "
                f"match {snapshot_date or 'unknown snapshot date'}")
        if iv30_missing_underlyings:
            alerts.append(
                "governed IV30 representative missing for snapshot valuation date: "
                + ", ".join(iv30_missing_underlyings))
        if iv30_value_mismatch_underlyings:
            alerts.append(
                "canonical IV30 differs from recomputed representative: "
                + ", ".join(iv30_value_mismatch_underlyings))
        if iv30_duplicate_underlyings:
            alerts.append(
                "duplicate canonical IV30 levels on snapshot valuation date: "
                + ", ".join(iv30_duplicate_underlyings))
        if iv30_representative_not_ok_underlyings:
            alerts.append(
                "IV30 representative is not production-quality: "
                + ", ".join(iv30_representative_not_ok_underlyings))

    # freshness vs today
    staleness_days = None
    if meta.get("valuation_date"):
        try:
            parsed_snapshot_date = strict_day(meta["valuation_date"])
            if parsed_snapshot_date is None:
                raise ValueError("invalid snapshot valuation_date")
            vd = date.fromisoformat(parsed_snapshot_date)
            staleness_days = ((valuation_date or date.today()) - vd).days
        except ValueError:
            pass
    if staleness_days is not None and staleness_days > 4:
        alerts.append(f"stale snapshot: {staleness_days} days old")
    if staleness_days is not None and staleness_days < 0:
        alerts.append(
            f"future snapshot: {-staleness_days} days after runtime as-of")

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


def persist_quality_report(db, snapshot_id: str,
                           valuation_date: date | None = None) -> dict:
    """Compute the snapshot's quality report and persist it (MD-002) — but only
    when it differs from the latest stored one, so the audit trail doesn't bloat
    on repeated reads. Returns the freshly computed report."""
    report = snapshot_quality_report(db, snapshot_id, valuation_date)
    prev = db.latest_validation_report(snapshot_id)
    try:
        previous_checks = json.loads((prev or {}).get("checks_json") or "{}")
    except (TypeError, ValueError):
        previous_checks = {}
    changed = (prev is None
               or prev.get("status") != report["status"]
               or prev.get("completeness_pct") != report["completeness_pct"]
               or bool(prev.get("production_eligible")) != report["production_eligible"]
               or previous_checks.get("contract_version")
               != QUALITY_CONTRACT_VERSION
               or previous_checks.get("snapshot_fingerprint")
               != report["checks"]["snapshot_fingerprint"])
    if changed:
        db.save_validation_report(snapshot_id, report)
    return report


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
    vol_lineage_ready = (
        checks["vol_observation_points"] > 0
        and checks["vol_observation_points_verified"]
        == checks["vol_observation_points"]
        and checks["vol_key_coverage_complete"]
        and checks["vol_payload_match_complete"]
        and not checks["iv30_missing_underlyings"]
    )
    parts = [
        1.0 - len(checks["curves_missing"]) / max(len(EXPECTED_CURVES), 1),
        1.0 - len(checks["fx_missing"]) / max(len(EXPECTED_FX), 1),
        1.0 if checks["vol_points"] >= MIN_VOL_POINTS else checks["vol_points"] / MIN_VOL_POINTS,
        1.0 if vol_lineage_ready else 0.0,
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
    lines.append(
        f"  vol lineage: {c['vol_observation_points_verified']}/"
        f"{c['vol_observation_points']} verified; IV30 {c['iv30_underlyings']}")
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
