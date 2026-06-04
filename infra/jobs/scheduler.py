"""
Lightweight EOD scheduler (Phase E).

Decides when the EOD ingest job is due. Designed to be driven by an external
trigger that polls (cron, systemd timer, a long-running supervisor, or the
Claude Code /schedule routine) — the due-logic is pure and unit-testable; the
optional run_forever loop is the background-runner convenience.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable


class EodSchedule:
    """Fires once per (week)day at a configured local time."""

    def __init__(self, run_time: str = "19:00", weekdays_only: bool = True):
        hour, minute = run_time.split(":")
        self.hour = int(hour)
        self.minute = int(minute)
        self.weekdays_only = weekdays_only

    def scheduled_for(self, day) -> datetime:
        return datetime(day.year, day.month, day.day, self.hour, self.minute)

    def is_due(self, now: datetime, last_run: datetime | None = None) -> bool:
        if self.weekdays_only and now.weekday() >= 5:  # Sat/Sun
            return False
        scheduled = self.scheduled_for(now.date())
        if now < scheduled:
            return False
        if last_run is not None and last_run >= scheduled:
            return False
        return True


def run_if_due(
    schedule: EodSchedule,
    job: Callable[[], object],
    now: datetime | None = None,
    last_run: datetime | None = None,
) -> tuple[bool, object | None]:
    """Run ``job`` exactly once if the schedule is due. Returns (ran, result)."""
    now = now or datetime.now()
    if schedule.is_due(now, last_run):
        return True, job()
    return False, None


def run_forever(
    schedule: EodSchedule,
    job: Callable[[], object],
    poll_seconds: int = 300,
) -> None:  # pragma: no cover - background loop
    """Background supervisor: poll and run the job when due (one run per window)."""
    last_run: datetime | None = None
    while True:
        ran, _ = run_if_due(schedule, job, datetime.now(), last_run)
        if ran:
            last_run = datetime.now()
        time.sleep(poll_seconds)
