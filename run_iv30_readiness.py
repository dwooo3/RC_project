#!/usr/bin/env python3
"""Read-only CLI for IV30 rollout readiness and schedule observability.

Examples::

    python run_iv30_readiness.py check --config config/iv30_rollout.json \
        --db data/market_data.sqlite --as-of 2026-07-13
    python run_iv30_readiness.py schedule-status \
        --config config/iv30_rollout.json --now 2026-07-13T19:45:00

Neither command invokes the IV30 publisher or an external scheduler.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from infra.db.market_data_db import MarketDataDB
from infra.jobs.iv30_rollout import (
    SCHEMA_VERSION,
    RolloutConfigError,
    assess_iv30_readiness,
    ensure_finite_json,
    load_rollout_config,
    parse_iso_date,
    parse_local_datetime,
    schedule_status,
)


EXIT_READY = 0
EXIT_NOT_READY = 2
EXIT_CONFIG = 64
EXIT_RUNTIME = 70


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise RolloutConfigError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description="Read-only IV30 rollout readiness and schedule status"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser(
        "check",
        help="assess governed IV30 history through a read-only SQLite handle",
    )
    check.add_argument("--config", required=True, help="rollout JSON config")
    check.add_argument(
        "--db",
        required=True,
        help="existing SQLite database (opened mode=ro; never created)",
    )
    check.add_argument(
        "--as-of",
        default=None,
        help="freshness date, YYYY-MM-DD (default: current local date)",
    )

    status = commands.add_parser(
        "schedule-status",
        help="report EodSchedule.is_due without invoking any job",
    )
    status.add_argument("--config", required=True, help="rollout JSON config")
    status.add_argument(
        "--now",
        default=None,
        help="naive local ISO datetime (default: current local time)",
    )
    status.add_argument(
        "--last-run",
        default=None,
        help="optional naive local ISO datetime of the last successful run",
    )
    return parser


def _emit(payload: dict) -> None:
    ensure_finite_json(payload)
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )


def _error_payload(command: str | None, *, status: str, message: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command or "unknown",
        "status": status,
        "error": {"message": message},
    }


def main(
    argv: list[str] | None = None,
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> int:
    """Run the bounded CLI; injectable clocks keep contract tests deterministic."""
    command: str | None = None
    try:
        args = _build_parser().parse_args(argv)
        command = args.command
        config = load_rollout_config(args.config)

        if command == "check":
            if args.as_of is not None:
                as_of = parse_iso_date(args.as_of, field="as_of")
            else:
                as_of = today if today is not None else date.today()
                if isinstance(as_of, datetime) or not isinstance(as_of, date):
                    raise RolloutConfigError(
                        "current local date must be an explicit date"
                    )

            db = MarketDataDB.from_sqlite_readonly(args.db)
            try:
                result = assess_iv30_readiness(db, config, as_of=as_of)
            finally:
                db.close()
            _emit(result)
            return EXIT_READY if result["ready"] else EXIT_NOT_READY

        observed_at = (
            parse_local_datetime(args.now, field="now")
            if args.now is not None
            else now if now is not None else datetime.now()
        )
        if not isinstance(observed_at, datetime):
            raise RolloutConfigError("current local time must be a datetime")
        last_run = (
            parse_local_datetime(args.last_run, field="last_run")
            if args.last_run is not None
            else None
        )
        result = schedule_status(config, now=observed_at, last_run=last_run)
        _emit(result)
        return EXIT_READY if result["due"] else EXIT_NOT_READY
    except RolloutConfigError as exc:
        _emit(_error_payload(
            command,
            status="config_error",
            message=str(exc),
        ))
        return EXIT_CONFIG
    except Exception as exc:
        _emit(_error_payload(
            command,
            status="runtime_error",
            message=str(exc),
        ))
        return EXIT_RUNTIME


if __name__ == "__main__":
    raise SystemExit(main())
