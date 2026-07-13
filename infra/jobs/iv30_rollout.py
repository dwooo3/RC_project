"""Read-only IV30 rollout readiness and schedule observability.

This module intentionally has no publisher or scheduler-runner entry point.  It
only reads governed history, evaluates the production gate and reports whether
an external scheduler window is due.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from infra.jobs.iv30_operational import (
    DEFAULT_MAX_STALENESS_DAYS,
    DEFAULT_MIN_SHOCKS,
    iv30_readiness_report,
)
from infra.jobs.scheduler import EodSchedule


SCHEMA_VERSION = "riskcalc.iv30_rollout.v1"
_RUN_TIME_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
_TOP_LEVEL_FIELDS = {
    "source",
    "from",
    "till",
    "expected_dates",
    "required_underlyings",
    "stress_dates",
    "min_shocks",
    "max_staleness_days",
    "schedule",
}
_SCHEDULE_FIELDS = {"run_time", "weekdays_only"}


class RolloutConfigError(ValueError):
    """The rollout command cannot safely interpret its configuration."""


@dataclass(frozen=True)
class Iv30RolloutConfig:
    """Validated, side-effect-free inputs for IV30 readiness assessment."""

    from_date: date
    till_date: date
    source: str = "MOEX"
    expected_dates: tuple[date, ...] | None = None
    required_underlyings: tuple[str, ...] | None = None
    stress_dates: tuple[date, ...] = ()
    min_shocks: int = DEFAULT_MIN_SHOCKS
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS
    schedule_run_time: str = "19:00"
    schedule_weekdays_only: bool = True

    @property
    def has_explicit_calendar(self) -> bool:
        return bool(self.expected_dates)

    @property
    def has_fixed_universe(self) -> bool:
        return bool(self.required_underlyings)

    @property
    def has_production_source(self) -> bool:
        return self.source == "MOEX"

    @property
    def production_gate(self) -> bool:
        return (
            self.has_production_source
            and self.has_explicit_calendar
            and self.has_fixed_universe
        )


def parse_iso_date(value: Any, *, field: str) -> date:
    """Parse one strict ``YYYY-MM-DD`` value for a CLI/config boundary."""
    if not isinstance(value, str) or len(value) != 10:
        raise RolloutConfigError(f"{field} must be an ISO date (YYYY-MM-DD)")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RolloutConfigError(
            f"{field} must be an ISO date (YYYY-MM-DD)"
        ) from exc
    if parsed.isoformat() != value:
        raise RolloutConfigError(f"{field} must be an ISO date (YYYY-MM-DD)")
    return parsed


def parse_local_datetime(value: Any, *, field: str) -> datetime:
    """Parse a naive local timestamp, matching ``EodSchedule`` semantics."""
    if not isinstance(value, str) or not value.strip():
        raise RolloutConfigError(f"{field} must be an ISO local datetime")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RolloutConfigError(f"{field} must be an ISO local datetime") from exc
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        raise RolloutConfigError(
            f"{field} must not contain a timezone offset; schedule time is local"
        )
    return parsed


def _date_list(value: Any, *, field: str) -> tuple[date, ...]:
    if not isinstance(value, list):
        raise RolloutConfigError(f"{field} must be a JSON array of ISO dates")
    parsed = tuple(parse_iso_date(item, field=field) for item in value)
    if len(set(parsed)) != len(parsed):
        raise RolloutConfigError(f"{field} must not contain duplicate dates")
    return tuple(sorted(parsed))


def _underlying_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RolloutConfigError("required_underlyings must be a JSON array")
    normalised: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise RolloutConfigError(
                "required_underlyings must contain non-empty string IDs"
            )
        underlying = item.removeprefix("IV30:").strip()
        if not underlying:
            raise RolloutConfigError(
                "required_underlyings must contain non-empty string IDs"
            )
        normalised.append(underlying)
    if len(set(normalised)) != len(normalised):
        raise RolloutConfigError(
            "required_underlyings must not contain duplicate IDs"
        )
    return tuple(sorted(normalised))


def _non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RolloutConfigError(f"{field} must be a non-negative integer")
    return value


def parse_rollout_config(payload: Any) -> Iv30RolloutConfig:
    """Validate a decoded JSON config without opening a database."""
    if not isinstance(payload, Mapping):
        raise RolloutConfigError("rollout config must be a JSON object")
    unknown = sorted(set(payload) - _TOP_LEVEL_FIELDS)
    if unknown:
        raise RolloutConfigError(
            "unknown rollout config fields: " + ", ".join(unknown)
        )
    if "from" not in payload or "till" not in payload:
        raise RolloutConfigError("rollout config requires 'from' and 'till'")

    from_date = parse_iso_date(payload["from"], field="from")
    till_date = parse_iso_date(payload["till"], field="till")
    if from_date > till_date:
        raise RolloutConfigError("from must be on or before till")

    source = payload.get("source", "MOEX")
    if not isinstance(source, str) or not source.strip():
        raise RolloutConfigError("source must be a non-empty string")
    source = source.strip().upper()

    expected_dates = (
        _date_list(payload["expected_dates"], field="expected_dates")
        if "expected_dates" in payload
        else None
    )
    required_underlyings = (
        _underlying_list(payload["required_underlyings"])
        if "required_underlyings" in payload
        else None
    )
    stress_dates = _date_list(
        payload.get("stress_dates", []), field="stress_dates"
    )

    for field, values in (
        ("expected_dates", expected_dates or ()),
        ("stress_dates", stress_dates),
    ):
        outside = [
            item.isoformat()
            for item in values
            if item < from_date or item > till_date
        ]
        if outside:
            raise RolloutConfigError(
                f"{field} must fall inside from..till: " + ", ".join(outside)
            )
    if expected_dates is not None:
        missing_stress = sorted(set(stress_dates) - set(expected_dates))
        if missing_stress:
            raise RolloutConfigError(
                "stress_dates must be included in expected_dates: "
                + ", ".join(item.isoformat() for item in missing_stress)
            )

    min_shocks = _non_negative_int(
        payload.get("min_shocks", DEFAULT_MIN_SHOCKS), field="min_shocks"
    )
    max_staleness_days = _non_negative_int(
        payload.get("max_staleness_days", DEFAULT_MAX_STALENESS_DAYS),
        field="max_staleness_days",
    )

    schedule = payload.get("schedule", {})
    if not isinstance(schedule, Mapping):
        raise RolloutConfigError("schedule must be a JSON object")
    unknown_schedule = sorted(set(schedule) - _SCHEDULE_FIELDS)
    if unknown_schedule:
        raise RolloutConfigError(
            "unknown schedule fields: " + ", ".join(unknown_schedule)
        )
    run_time = schedule.get("run_time", "19:00")
    if not isinstance(run_time, str) or _RUN_TIME_RE.fullmatch(run_time) is None:
        raise RolloutConfigError("schedule.run_time must use 24-hour HH:MM")
    weekdays_only = schedule.get("weekdays_only", True)
    if not isinstance(weekdays_only, bool):
        raise RolloutConfigError("schedule.weekdays_only must be a boolean")

    return Iv30RolloutConfig(
        from_date=from_date,
        till_date=till_date,
        source=source,
        expected_dates=expected_dates,
        required_underlyings=required_underlyings,
        stress_dates=stress_dates,
        min_shocks=min_shocks,
        max_staleness_days=max_staleness_days,
        schedule_run_time=run_time,
        schedule_weekdays_only=weekdays_only,
    )


def load_rollout_config(path: str | Path) -> Iv30RolloutConfig:
    """Load and validate a JSON config; all failures are configuration errors."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RolloutConfigError(f"cannot load rollout config: {exc}") from exc
    return parse_rollout_config(payload)


def ensure_finite_json(value: Any, *, path: str = "$") -> None:
    """Fail closed if an observability payload is not strict finite JSON."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite number at {path}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"non-string JSON key at {path}")
            ensure_finite_json(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            ensure_finite_json(item, path=f"{path}[{index}]")
        return
    raise TypeError(f"non-JSON value at {path}: {type(value).__name__}")


def assess_iv30_readiness(
    db,
    config: Iv30RolloutConfig,
    *,
    as_of: date,
) -> dict:
    """Build a stable read-only production-gate status payload."""
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise RolloutConfigError("as_of must be an explicit date")

    report = iv30_readiness_report(
        db,
        config.from_date,
        config.till_date,
        source=config.source,
        min_shocks=config.min_shocks,
        required_underlyings=(
            config.required_underlyings or None
        ),
        expected_dates=config.expected_dates or None,
        stress_dates=config.stress_dates or None,
        as_of=as_of,
        max_staleness_days=config.max_staleness_days,
        require_validation_reports=config.production_gate,
    )
    gate_blockers: list[str] = []
    if not config.has_production_source:
        gate_blockers.append("production_gate_requires_moex_source")
    if not config.has_explicit_calendar:
        gate_blockers.append("production_gate_requires_explicit_expected_dates")
    if not config.has_fixed_universe:
        gate_blockers.append("production_gate_requires_nonempty_fixed_universe")

    readiness_ready = bool(report.get("ready"))
    ready = config.production_gate and readiness_ready
    factors = report.get("factors") or {}
    blockers = sorted(set(report.get("blockers") or ()) | set(gate_blockers))
    result = {
        "schema_version": SCHEMA_VERSION,
        "command": "check",
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "readiness_ready": readiness_ready,
        "production_gate": config.production_gate,
        "diagnostic_only": not config.production_gate,
        "source": config.source,
        "window": {
            "from": config.from_date.isoformat(),
            "till": config.till_date.isoformat(),
            "as_of": as_of.isoformat(),
        },
        "requirements": {
            "minimum_valid_shocks": config.min_shocks,
            "max_staleness_days": config.max_staleness_days,
            "expected_dates_configured": config.expected_dates is not None,
            "expected_dates_count": len(config.expected_dates or ()),
            "fixed_universe_configured": config.required_underlyings is not None,
            "required_underlyings": list(config.required_underlyings or ()),
            "stress_dates": [item.isoformat() for item in config.stress_dates],
        },
        "blockers": blockers,
        "metrics": {
            "expected_snapshot_dates": len(
                report.get("expected_snapshot_dates") or ()
            ),
            "stored_snapshot_dates": len(
                report.get("stored_snapshot_dates") or ()
            ),
            "missing_snapshot_dates": len(
                report.get("missing_snapshot_dates") or ()
            ),
            "required_factors": len(factors),
            "ready_factors": sum(
                bool(factor.get("ready")) for factor in factors.values()
            ),
            "staleness_days": report.get("staleness_days"),
        },
        "details": {
            "missing_snapshot_dates": report.get("missing_snapshot_dates") or [],
            "duplicate_snapshot_dates": (
                report.get("duplicate_snapshot_dates") or {}
            ),
            "out_of_range_expected_dates": (
                report.get("out_of_range_expected_dates") or []
            ),
            "invalid_snapshot_manifests": (
                report.get("invalid_snapshot_manifests") or []
            ),
            "empty_surface_dates": report.get("empty_surface_dates") or [],
            "snapshot_lineage_failures": (
                report.get("snapshot_lineage_failures") or {}
            ),
            "snapshot_certification_failures": (
                report.get("snapshot_certification_failures") or {}
            ),
            "snapshot_dates_after_as_of": (
                report.get("snapshot_dates_after_as_of") or []
            ),
            "stored_snapshot_dates_after_as_of": (
                report.get("stored_snapshot_dates_after_as_of") or []
            ),
            "factors": factors,
        },
    }
    ensure_finite_json(result)
    return result


def schedule_status(
    config: Iv30RolloutConfig,
    *,
    now: datetime,
    last_run: datetime | None = None,
) -> dict:
    """Report due status through ``EodSchedule.is_due`` without invoking a job."""
    for field, value in (("now", now), ("last_run", last_run)):
        if value is None:
            continue
        if not isinstance(value, datetime):
            raise RolloutConfigError(f"{field} must be a datetime")
        if value.tzinfo is not None and value.utcoffset() is not None:
            raise RolloutConfigError(
                f"{field} must be a naive local datetime"
            )

    schedule = EodSchedule(
        run_time=config.schedule_run_time,
        weekdays_only=config.schedule_weekdays_only,
    )
    due = schedule.is_due(now, last_run)
    scheduled_for = schedule.scheduled_for(now.date())
    if due:
        reason = "due"
    elif config.schedule_weekdays_only and now.weekday() >= 5:
        reason = "weekend"
    elif now < scheduled_for:
        reason = "before_scheduled_time"
    elif last_run is not None and last_run >= scheduled_for:
        reason = "already_run"
    else:  # defensive: keep a stable reason if EodSchedule gains another rule
        reason = "not_due"

    result = {
        "schema_version": SCHEMA_VERSION,
        "command": "schedule-status",
        "status": "due" if due else "not_due",
        "due": due,
        "reason": reason,
        "observed_at": now.isoformat(timespec="seconds"),
        "last_run": (
            last_run.isoformat(timespec="seconds") if last_run is not None else None
        ),
        "schedule": {
            "run_time": config.schedule_run_time,
            "weekdays_only": config.schedule_weekdays_only,
            "scheduled_for": scheduled_for.isoformat(timespec="seconds"),
        },
    }
    ensure_finite_json(result)
    return result
