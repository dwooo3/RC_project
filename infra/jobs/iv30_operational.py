"""Offline IV30 rebuild and operational-readiness diagnostics.

The job deliberately performs no network calls.  It republishes canonical
``IV30:{underlying}`` rows only from snapshot-bound raw surfaces and audited
point provenance already stored by the EOD ingest.  This makes a historical
repair/backfill deterministic, idempotent and safe to run before wiring a
production scheduler.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

from infra.jobs.eod_ingest import EodIngestJob
from infra.moex_iss.vol_surface import (
    PRIMARY_IV_METHOD,
    iv30_representative,
    primary_iv_provenance_error,
    vol_lineage_diagnostics,
    vol_point_payload_error,
)


# Match the default Market Risk rolling window.  A shorter use case must opt in
# explicitly; the operational gate must not declare a 60-day series ready for
# a 500-scenario production request.
DEFAULT_MIN_SHOCKS = 500
DEFAULT_MAX_STALENESS_DAYS = 4
# PostgreSQL ``REAL`` is float4: allow one storage round-trip while still
# rejecting economically different or stale canonical values.
IV30_VALUE_REL_TOLERANCE = 1e-6
IV30_VALUE_ABS_TOLERANCE = 1e-8


def _as_date(value, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"invalid {field}: {value!r}")
    raw = value.strip()
    try:
        if len(raw) == 10:
            return date.fromisoformat(raw)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


def _date_set(values: Iterable | None, *, field: str) -> set[date]:
    if isinstance(values, (str, date)):
        values = [values]
    return {_as_date(value, field=field) for value in (values or [])}


def _required_underlying_set(values: Iterable[str] | None) -> set[str] | None:
    if values is None:
        return None
    if isinstance(values, str):
        values = [values]
    normalised = {
        str(value).removeprefix("IV30:").strip()
        for value in values
    }
    if "" in normalised:
        raise ValueError("required_underlyings must contain non-empty IDs")
    return normalised


def _validate_non_negative_int(value, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def iv30_readiness_report(
    db,
    from_date: date,
    till_date: date,
    *,
    source: str = "MOEX",
    min_shocks: int = DEFAULT_MIN_SHOCKS,
    required_underlyings: Iterable[str] | None = None,
    expected_dates: Iterable[date | str] | None = None,
    stress_dates: Iterable[date | str] | None = None,
    as_of: date | None = None,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
    require_validation_reports: bool = False,
    _inside_read_snapshot: bool = False,
) -> dict:
    """Assess whether governed IV30 history can replace a proxy.

    The union of underlyings seen anywhere in the range must cover the entire
    snapshot calendar, preventing a late-added factor from manufacturing a
    shorter window. Callers may provide an explicit fixed universe and/or an
    exchange-calendar list through ``required_underlyings`` and
    ``expected_dates``. In the absence of an explicit calendar the function
    never guesses holidays from weekdays: source manifests define the dates.
    """
    read_snapshot = getattr(db, "read_snapshot", None)
    if not _inside_read_snapshot and callable(read_snapshot):
        with read_snapshot():
            return iv30_readiness_report(
                db,
                from_date,
                till_date,
                source=source,
                min_shocks=min_shocks,
                required_underlyings=required_underlyings,
                expected_dates=expected_dates,
                stress_dates=stress_dates,
                as_of=as_of,
                max_staleness_days=max_staleness_days,
                require_validation_reports=require_validation_reports,
                _inside_read_snapshot=True,
            )

    start = _as_date(from_date, field="from_date")
    end = _as_date(till_date, field="till_date")
    if start > end:
        raise ValueError("from_date must be on or before till_date")
    min_shocks = _validate_non_negative_int(min_shocks, field="min_shocks")
    max_staleness_days = _validate_non_negative_int(
        max_staleness_days, field="max_staleness_days")
    report_as_of = _as_date(
        as_of if as_of is not None else end, field="as_of")

    manifests = db.list_snapshots_between(start, end, source=source)
    by_date: dict[date, list[dict]] = defaultdict(list)
    invalid_manifests: list[dict] = []
    for row in manifests:
        try:
            snapshot_date = _as_date(row.get("valuation_date"), field="valuation_date")
        except ValueError as exc:
            invalid_manifests.append({
                "snapshot_id": row.get("snapshot_id"),
                "reason": str(exc),
            })
            continue
        by_date[snapshot_date].append(row)

    manifest_dates = set(by_date)
    required_dates = (
        _date_set(expected_dates, field="expected_date")
        if expected_dates is not None else manifest_dates
    )
    out_of_range_expected = sorted(
        day.isoformat() for day in required_dates if day < start or day > end)
    required_dates = {day for day in required_dates if start <= day <= end}
    missing_snapshot_dates = sorted(
        day.isoformat() for day in required_dates - manifest_dates)
    duplicate_snapshot_dates = {
        day.isoformat(): sorted(str(row.get("snapshot_id")) for row in rows)
        for day, rows in sorted(by_date.items())
        if day in required_dates and len(rows) != 1
    }

    fixed_underlyings = _required_underlying_set(required_underlyings)
    requirements: dict[str, set[date]] = defaultdict(set)
    snapshot_underlyings: dict[str, list[str]] = {}
    native_by_date: dict[date, set[str]] = {}
    governed_underlyings_by_date: dict[date, set[str]] = {}
    representative_values_by_date: dict[date, dict[str, float]] = {}
    snapshot_lineage: dict[str, dict] = {}
    lineage_failures: dict[str, list[str]] = {}
    snapshot_certifications: dict[str, dict] = {}
    certification_failures: dict[str, list[str]] = {}
    empty_surface_dates: list[str] = []
    for snapshot_date, rows in sorted(by_date.items()):
        if snapshot_date not in required_dates:
            continue
        if len(rows) != 1:
            continue
        snapshot_id = rows[0].get("snapshot_id")
        raw_points = db.get_vol_points(snapshot_id)
        observations = db.get_vol_point_observations(snapshot_id)
        native = {str(point.get("underlying")) for point in raw_points
                  if point.get("underlying")}
        native_by_date[snapshot_date] = native
        snapshot_underlyings[snapshot_date.isoformat()] = sorted(native)
        if not native:
            empty_surface_dates.append(snapshot_date.isoformat())

        problems: list[str] = []
        if str(rows[0].get("quality") or "").upper() != "OK":
            problems.append("snapshot_quality_not_ok")
        lineage = vol_lineage_diagnostics(raw_points, observations)
        if raw_points and not observations:
            problems.append("vol_point_provenance_missing")
        if not lineage["key_coverage_complete"]:
            problems.append("raw_provenance_key_mismatch")
        if (lineage["invalid_raw_payloads"]
                or lineage["invalid_observation_payloads"]):
            problems.append("invalid_vol_point_payload")
        if lineage["iv_value_mismatch_keys"]:
            problems.append("raw_provenance_iv_mismatch")
        invalid_provenance = [
            primary_iv_provenance_error(point, snapshot_date)
            for point in observations
        ]
        invalid_provenance = [reason for reason in invalid_provenance if reason]
        if invalid_provenance:
            problems.append("invalid_vol_point_provenance")

        if require_validation_reports:
            from infra.jobs.data_quality import (
                QUALITY_CONTRACT_VERSION,
                snapshot_data_fingerprint,
            )

            validation = db.latest_validation_report(snapshot_id)
            try:
                validation_checks = json.loads(
                    (validation or {}).get("checks_json") or "{}")
            except (TypeError, ValueError):
                validation_checks = {}
            current_fingerprint = snapshot_data_fingerprint(db, snapshot_id)
            certification_problems = []
            if validation is None:
                certification_problems.append("validation_report_missing")
            else:
                if str(validation.get("status") or "").upper() != "OK":
                    certification_problems.append("validation_status_not_ok")
                if not bool(validation.get("production_eligible")):
                    certification_problems.append(
                        "validation_not_production_eligible")
                if (validation_checks.get("contract_version")
                        != QUALITY_CONTRACT_VERSION):
                    certification_problems.append(
                        "validation_contract_version_mismatch")
                if (validation_checks.get("snapshot_fingerprint")
                        != current_fingerprint):
                    certification_problems.append(
                        "validation_snapshot_fingerprint_mismatch")
            snapshot_certifications[snapshot_date.isoformat()] = {
                "snapshot_id": snapshot_id,
                "report_present": validation is not None,
                "report_status": (
                    validation.get("status") if validation else None),
                "production_eligible": bool(
                    (validation or {}).get("production_eligible")),
                "contract_version": validation_checks.get("contract_version"),
                "fingerprint_matches": (
                    validation_checks.get("snapshot_fingerprint")
                    == current_fingerprint
                ),
                "problems": certification_problems,
            }
            if certification_problems:
                certification_failures[snapshot_date.isoformat()] = (
                    certification_problems)

        by_underlying: dict[str, list[dict]] = defaultdict(list)
        for point in observations:
            by_underlying[str(point.get("underlying") or "")].append(point)
        governed_underlyings: set[str] = set()
        representative_quality: dict[str, str] = {}
        representative_values: dict[str, float] = {}
        for underlying in sorted(native):
            primary = [
                point for point in by_underlying.get(underlying, [])
                if point.get("method") == PRIMARY_IV_METHOD
            ]
            representative = iv30_representative(primary, snapshot_date)
            quality = str(representative.get("quality") or "")
            representative_quality[underlying] = (
                quality if representative.get("accepted")
                else f"REJECTED:{representative.get('reason', 'unknown')}"
            )
            if representative.get("accepted") and quality == "OK":
                governed_underlyings.add(underlying)
                representative_values[underlying] = float(representative["value"])
            else:
                problems.append(f"iv30_representative_not_ok:{underlying}")
        governed_underlyings_by_date[snapshot_date] = governed_underlyings
        representative_values_by_date[snapshot_date] = representative_values
        snapshot_lineage[snapshot_date.isoformat()] = {
            "snapshot_id": snapshot_id,
            "raw_points": len(raw_points),
            "provenance_points": len(observations),
            "key_coverage_complete": lineage["key_coverage_complete"],
            "payload_match_complete": lineage["payload_match_complete"],
            "invalid_raw_payloads": lineage["invalid_raw_payloads"],
            "invalid_provenance_payloads": lineage["invalid_observation_payloads"],
            "iv_value_mismatch_keys": lineage["iv_value_mismatch_keys"],
            "verified_provenance_points": sum(
                primary_iv_provenance_error(point, snapshot_date) is None
                and vol_point_payload_error(point) is None
                for point in observations
            ),
            "representative_quality": representative_quality,
            "representative_values": representative_values,
            "governed": (
                not problems
                and snapshot_date.isoformat() not in certification_failures
            ),
        }
        if problems:
            lineage_failures[snapshot_date.isoformat()] = sorted(set(problems))

    selected_universe = (
        fixed_underlyings
        if fixed_underlyings is not None
        else set().union(*native_by_date.values()) if native_by_date else set()
    )
    for underlying in selected_universe:
        requirements[underlying].update(required_dates)

    stress = _date_set(stress_dates, field="stress_date")
    factor_reports: dict[str, dict] = {}
    for underlying, factor_required_dates in sorted(requirements.items()):
        factor_id = f"IV30:{underlying}"
        rows = db.get_time_series_window(factor_id, "vol", start, end)
        values: dict[date, float] = {}
        invalid_rows: list[str] = []
        seen_level_dates: set[date] = set()
        duplicate_level_dates: set[date] = set()
        for row in rows:
            try:
                point_date = _as_date(row.get("dt"), field="time_series date")
            except ValueError:
                invalid_rows.append(str(row.get("dt")))
                continue
            if point_date in seen_level_dates:
                duplicate_level_dates.add(point_date)
            seen_level_dates.add(point_date)
            try:
                value = float(row.get("value"))
            except (TypeError, ValueError):
                invalid_rows.append(point_date.isoformat())
                continue
            if not math.isfinite(value) or not 0.01 < value < 3.0:
                invalid_rows.append(point_date.isoformat())
                continue
            values.setdefault(point_date, value)

        level_dates = set(values)
        native_dates = {
            day for day in factor_required_dates
            if underlying in native_by_date.get(day, set())
        }
        lineage_dates = {
            day for day in factor_required_dates
            if underlying in governed_underlyings_by_date.get(day, set())
        }
        value_mismatch_dates = sorted(
            day.isoformat()
            for day in factor_required_dates & level_dates & lineage_dates
            if not math.isclose(
                values[day],
                representative_values_by_date[day][underlying],
                rel_tol=IV30_VALUE_REL_TOLERANCE,
                abs_tol=IV30_VALUE_ABS_TOLERANCE,
            )
        )
        matching_value_dates = {
            day for day in factor_required_dates & level_dates & lineage_dates
            if day.isoformat() not in value_mismatch_dates
        }
        governed_level_dates = sorted(
            matching_value_dates & native_dates & lineage_dates
        )
        governed_level_set = set(governed_level_dates)
        missing_native_surface_dates = sorted(
            day.isoformat() for day in factor_required_dates - native_dates
        )
        ungoverned_lineage_dates = sorted(
            day.isoformat() for day in native_dates - lineage_dates
        )
        unexpected_level_dates = sorted(
            day.isoformat() for day in level_dates - factor_required_dates
        )
        # Count only adjacent endpoints on the canonical master calendar.
        # Missing a middle date therefore invalidates both neighbouring daily
        # shocks instead of silently turning them into one multi-day move.
        ordered_calendar = sorted(factor_required_dates)
        valid_shocks = sum(
            left in governed_level_set and right in governed_level_set
            for left, right in zip(ordered_calendar, ordered_calendar[1:])
        )
        missing_dates = sorted(
            day.isoformat() for day in factor_required_dates - level_dates)
        missing_stress_dates = sorted(
            day.isoformat() for day in stress - set(governed_level_dates))
        factor_ready = (
            not missing_dates
            and not missing_native_surface_dates
            and not ungoverned_lineage_dates
            and not value_mismatch_dates
            and not missing_stress_dates
            and not invalid_rows
            and not duplicate_level_dates
            and not unexpected_level_dates
            and valid_shocks >= min_shocks
        )
        factor_reports[factor_id] = {
            "levels": len(level_dates),
            "governed_levels": len(governed_level_dates),
            "valid_shocks": valid_shocks,
            "first_date": (
                governed_level_dates[0].isoformat() if governed_level_dates else None
            ),
            "last_date": (
                governed_level_dates[-1].isoformat() if governed_level_dates else None
            ),
            "required_snapshot_dates": len(factor_required_dates),
            "covered_snapshot_dates": len(factor_required_dates & level_dates),
            "missing_snapshot_dates": missing_dates,
            "missing_native_surface_dates": missing_native_surface_dates,
            "ungoverned_lineage_dates": ungoverned_lineage_dates,
            "representative_value_mismatch_dates": value_mismatch_dates,
            "missing_stress_dates": missing_stress_dates,
            "unexpected_level_dates": unexpected_level_dates,
            "invalid_dates": sorted(set(invalid_rows)),
            "duplicate_level_dates": sorted(
                day.isoformat() for day in duplicate_level_dates),
            "ready": factor_ready,
        }

    latest_expected = max(required_dates, default=None)
    future_expected_dates = sorted(
        day.isoformat() for day in required_dates if day > report_as_of
    )
    stored_snapshot_dates_after_as_of = sorted(
        day.isoformat() for day in manifest_dates if day > report_as_of
    )
    staleness_days = (
        (report_as_of - latest_expected).days
        if latest_expected is not None else None
    )
    freshness_ready = (
        staleness_days is not None
        and not future_expected_dates
        and 0 <= staleness_days <= max_staleness_days
    )
    ready = (
        bool(required_dates)
        and bool(factor_reports)
        and not invalid_manifests
        and not out_of_range_expected
        and not missing_snapshot_dates
        and not duplicate_snapshot_dates
        and not empty_surface_dates
        and not lineage_failures
        and not certification_failures
        and not stored_snapshot_dates_after_as_of
        and freshness_ready
        and all(report["ready"] for report in factor_reports.values())
    )
    blockers: list[str] = []
    if not required_dates:
        blockers.append("no_expected_snapshot_dates")
    if not factor_reports:
        blockers.append("no_required_iv30_factors")
    if invalid_manifests:
        blockers.append("invalid_snapshot_manifests")
    if out_of_range_expected:
        blockers.append("expected_dates_outside_requested_range")
    if missing_snapshot_dates:
        blockers.append("missing_snapshot_dates")
    if duplicate_snapshot_dates:
        blockers.append("ambiguous_snapshot_dates")
    if empty_surface_dates:
        blockers.append("empty_snapshot_surfaces")
    if lineage_failures:
        blockers.append("snapshot_iv30_lineage_not_governed")
    if certification_failures:
        blockers.append("snapshot_validation_not_current")
    if future_expected_dates:
        blockers.append("snapshot_dates_after_as_of")
    if stored_snapshot_dates_after_as_of:
        blockers.append("stored_snapshot_dates_after_as_of")
    if not freshness_ready:
        blockers.append("history_not_fresh")
    if any(not report["ready"] for report in factor_reports.values()):
        blockers.append("factor_coverage_or_depth_insufficient")

    return {
        "ready": ready,
        "source": source,
        "from": start.isoformat(),
        "till": end.isoformat(),
        "as_of": report_as_of.isoformat(),
        "minimum_valid_shocks": min_shocks,
        "expected_snapshot_dates": sorted(day.isoformat() for day in required_dates),
        "stored_snapshot_dates": sorted(day.isoformat() for day in manifest_dates),
        "missing_snapshot_dates": missing_snapshot_dates,
        "duplicate_snapshot_dates": duplicate_snapshot_dates,
        "out_of_range_expected_dates": out_of_range_expected,
        "invalid_snapshot_manifests": invalid_manifests,
        "empty_surface_dates": sorted(empty_surface_dates),
        "snapshot_lineage": snapshot_lineage,
        "snapshot_lineage_failures": lineage_failures,
        "validation_reports_required": require_validation_reports,
        "snapshot_certifications": snapshot_certifications,
        "snapshot_certification_failures": certification_failures,
        "snapshot_dates_after_as_of": future_expected_dates,
        "stored_snapshot_dates_after_as_of": stored_snapshot_dates_after_as_of,
        "snapshot_underlyings": snapshot_underlyings,
        "staleness_days": staleness_days,
        "max_staleness_days": max_staleness_days,
        "factors": factor_reports,
        "blockers": blockers,
    }


def governed_iv30_level(
    db,
    underlying: str,
    *,
    as_of: date,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
    _inside_read_snapshot: bool = False,
) -> float | None:
    """Return the newest IV30 level that passes the common consumer gate.

    This intentionally validates each candidate date against its unique MOEX
    manifest, raw grid, point provenance, production-quality representative,
    and canonical stored value.  Consumers must not treat a recent orphan row
    (or a WARN nearest-expiry representative) as governed merely because its
    timestamp and numeric range look plausible.
    """
    read_snapshot = getattr(db, "read_snapshot", None)
    if not _inside_read_snapshot and callable(read_snapshot):
        with read_snapshot():
            return governed_iv30_level(
                db,
                underlying,
                as_of=as_of,
                max_staleness_days=max_staleness_days,
                _inside_read_snapshot=True,
            )

    identity = str(underlying or "").removeprefix("IV30:").strip()
    if not identity:
        return None
    cutoff = _as_date(as_of, field="as_of")
    max_age = _validate_non_negative_int(
        max_staleness_days, field="max_staleness_days")
    rows = db.get_time_series(f"IV30:{identity}", "vol") or []
    for row in reversed(rows):
        try:
            observed = _as_date(row.get("dt"), field="time_series date")
            value = float(row.get("value"))
        except (TypeError, ValueError, OverflowError):
            continue
        age = (cutoff - observed).days
        if age < 0:
            continue
        if age > max_age:
            break
        if not math.isfinite(value) or not 0.01 < value < 3.0:
            continue
        report = iv30_readiness_report(
            db,
            observed,
            observed,
            min_shocks=0,
            required_underlyings=[identity],
            expected_dates=[observed],
            as_of=cutoff,
            max_staleness_days=max_age,
            require_validation_reports=True,
        )
        factor = (report.get("factors") or {}).get(f"IV30:{identity}") or {}
        if report.get("ready") and factor.get("ready"):
            return value
    return None


class Iv30OperationalJob:
    """Rebuild IV30 over a stored snapshot range and return readiness evidence."""

    def __init__(self, db, *, publisher=None):
        self.db = db
        self._publisher = publisher or EodIngestJob(
            db, iss_client=None
        ).publish_iv30

    def run(
        self,
        from_date: date,
        till_date: date | None = None,
        *,
        source: str = "MOEX",
        min_shocks: int = DEFAULT_MIN_SHOCKS,
        required_underlyings: Iterable[str] | None = None,
        expected_dates: Iterable[date | str] | None = None,
        stress_dates: Iterable[date | str] | None = None,
        as_of: date | None = None,
        max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
    ) -> dict:
        start = _as_date(from_date, field="from_date")
        end = _as_date(
            till_date if till_date is not None else date.today(),
            field="till_date",
        )
        if start > end:
            raise ValueError("from_date must be on or before till_date")
        min_shocks = _validate_non_negative_int(min_shocks, field="min_shocks")
        max_staleness_days = _validate_non_negative_int(
            max_staleness_days, field="max_staleness_days")
        run_as_of = _as_date(
            as_of if as_of is not None else end, field="as_of")
        calendar_filter = (
            _date_set(expected_dates, field="expected_date")
            if expected_dates is not None else None
        )
        stress_filter = _date_set(stress_dates, field="stress_date")
        underlying_filter = _required_underlying_set(required_underlyings)
        if calendar_filter is not None:
            outside_calendar = sorted(
                day.isoformat() for day in calendar_filter
                if day < start or day > end
            )
            if outside_calendar:
                raise ValueError(
                    "expected_dates must fall inside the requested range: "
                    + ", ".join(outside_calendar)
                )
            future_calendar = sorted(
                day.isoformat() for day in calendar_filter if day > run_as_of
            )
            if future_calendar:
                raise ValueError(
                    "expected_dates must not be after as_of: "
                    + ", ".join(future_calendar)
                )
        outside_stress = sorted(
            day.isoformat() for day in stress_filter
            if day < start or day > end or day > run_as_of
        )
        if outside_stress:
            raise ValueError(
                "stress_dates must fall inside the requested range and not "
                "after as_of: " + ", ".join(outside_stress)
            )
        if calendar_filter is not None:
            missing_stress = sorted(
                day.isoformat() for day in stress_filter - calendar_filter
            )
            if missing_stress:
                raise ValueError(
                    "stress_dates must be included in expected_dates: "
                    + ", ".join(missing_stress)
                )

        manifests = self.db.list_snapshots_between(start, end, source=source)
        by_date: dict[date, list[dict]] = defaultdict(list)
        invalid_manifests: list[dict] = []
        for row in manifests:
            try:
                snapshot_date = _as_date(
                    row.get("valuation_date"), field="valuation_date"
                )
            except ValueError as exc:
                invalid_manifests.append({
                    "snapshot_id": row.get("snapshot_id"),
                    "reason": str(exc),
                })
                continue
            by_date[snapshot_date].append(row)

        runs: dict[str, dict] = {}
        ambiguous: dict[str, list[str]] = {}
        errors: dict[str, str] = {}
        ignored_manifest_dates: list[str] = []
        for snapshot_date, rows in sorted(by_date.items()):
            key = snapshot_date.isoformat()
            if calendar_filter is not None and snapshot_date not in calendar_filter:
                ignored_manifest_dates.append(key)
                continue
            if snapshot_date > run_as_of:
                runs[key] = {
                    "status": "blocked",
                    "reason": "snapshot_date_after_as_of",
                    "snapshot_ids": sorted(
                        str(row.get("snapshot_id")) for row in rows
                    ),
                }
                continue
            if len(rows) != 1:
                ids = sorted(str(row.get("snapshot_id")) for row in rows)
                ambiguous[key] = ids
                runs[key] = {
                    "status": "blocked",
                    "reason": "ambiguous_snapshot_date",
                    "snapshot_ids": ids,
                }
                # Do not guess which snapshot is authoritative and do not
                # revoke an existing canonical value on an ambiguous date.
                continue
            snapshot_id = rows[0].get("snapshot_id")
            try:
                result = self._publisher(snapshot_id, snapshot_date)
                runs[key] = {"snapshot_id": snapshot_id, **result}
            except Exception as exc:  # isolate one stored date from the range
                errors[key] = str(exc)
                runs[key] = {
                    "snapshot_id": snapshot_id,
                    "status": "error",
                    "error": str(exc),
                }

        readiness = iv30_readiness_report(
            self.db,
            start,
            end,
            source=source,
            min_shocks=min_shocks,
            required_underlyings=underlying_filter,
            expected_dates=calendar_filter,
            stress_dates=stress_filter,
            as_of=run_as_of,
            max_staleness_days=max_staleness_days,
        )
        publication_issues = {
            day: {
                "status": row.get("status"),
                "reason": row.get("reason"),
                "warnings": row.get("warnings") or [],
                "rejected": sorted((row.get("rejected") or {}).keys()),
            }
            for day, row in runs.items()
            if (
                row.get("status") != "ok"
                or bool(row.get("warnings"))
                or int((row.get("quality_counts") or {}).get("WARN") or 0) > 0
                or int((row.get("quality_counts") or {}).get("rejected") or 0) > 0
            )
        }
        operational_ready = (
            readiness["ready"]
            and not invalid_manifests
            and not errors
            and not ambiguous
            and not publication_issues
        )
        return {
            "status": (
                "ready" if operational_ready
                else "blocked" if errors or ambiguous or invalid_manifests
                else "not_ready"
            ),
            "from": start.isoformat(),
            "till": end.isoformat(),
            "source": source,
            "processed_dates": sum(
                row.get("status") not in {"blocked", "error"} for row in runs.values()
            ),
            "published_dates": sum(
                int(row.get("saved") or 0) > 0 for row in runs.values()
            ),
            "revoked_or_empty_dates": sum(
                row.get("status") == "skipped" and int(row.get("saved") or 0) == 0
                for row in runs.values()
            ),
            "ambiguous_snapshot_dates": ambiguous,
            "ignored_manifest_dates": sorted(ignored_manifest_dates),
            "invalid_snapshot_manifests": invalid_manifests,
            "errors": errors,
            "publication_issues": publication_issues,
            "runs": runs,
            "readiness": readiness,
        }
