"""Governed Moscow Exchange trading-calendar provider and resolver.

The authoritative input is MOEX's machine-readable calendar endpoint, not a
weekday heuristic and not the set of dates where a price happened to arrive.
Every persisted version contains one explicit row per calendar date.  Weekend
additional sessions (``reason=W``) are collapsed onto their official
``trade_session_date`` so they never create a second contractual business day.

This module deliberately has no pricing imports.  Product engines can consume
the resolver later without coupling calendar ingestion to valuation code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable


CALENDAR_CONTRACT = "moex_trading_calendar_v1"
MOEX_CALENDAR_IDS = {
    "stock": "MOEX_STOCK",
    "futures": "MOEX_FUTURES",
    "currency": "MOEX_CURRENCY",
}
_REASONS = {None, "H", "W", "N", "T"}


class MoexCalendarError(ValueError):
    """Base error for an invalid or unavailable governed calendar."""


class MoexCalendarDataError(MoexCalendarError):
    """The exchange payload is structurally or semantically invalid."""


class MoexCalendarCoverageError(MoexCalendarError):
    """A requested date cannot be proved by the persisted calendar version."""


def _day(value: Any, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise MoexCalendarDataError(f"{field} must be an ISO date")
    token = value.strip()
    try:
        if len(token) == 10:
            return date.fromisoformat(token)
        return datetime.fromisoformat(token.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise MoexCalendarDataError(f"{field} must be an ISO date") from exc


def _value(row: dict, *names: str):
    for name in names:
        if name in row:
            return row[name]
        upper = name.upper()
        if upper in row:
            return row[upper]
    return None


def _flag(value: Any, *, tradedate: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if value in (0, 1, "0", "1"):
        return int(value)
    raise MoexCalendarDataError(
        f"calendar {tradedate}: is_traded must be 0 or 1")


def _expected_dates(start: date, end: date) -> list[str]:
    if start > end:
        raise MoexCalendarCoverageError(
            "from_date must be on or before till_date")
    out = []
    cursor = start
    while cursor <= end:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def normalise_calendar_days(
    rows: Iterable[dict],
    *,
    market: str,
    from_date,
    till_date,
) -> list[dict]:
    """Validate and canonicalise one full ``show_all_days=1`` response."""
    market = str(market or "").strip().lower()
    if market not in MOEX_CALENDAR_IDS:
        raise MoexCalendarDataError(
            f"unsupported MOEX calendar market {market!r}")
    start = _day(from_date, field="from_date")
    end = _day(till_date, field="till_date")
    expected = _expected_dates(start, end)
    by_date: dict[str, dict] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise MoexCalendarDataError("calendar row must be an object")
        tradedate = _day(
            _value(raw, "tradedate"), field="tradedate").isoformat()
        if tradedate in by_date:
            raise MoexCalendarDataError(
                f"duplicate trading calendar date {tradedate}")
        is_traded = _flag(
            _value(raw, "is_traded", f"{market}_workday"),
            tradedate=tradedate,
        )
        raw_session = _value(
            raw, "trade_session_date", f"{market}_trade_session_date")
        session = (
            _day(raw_session, field="trade_session_date").isoformat()
            if raw_session not in (None, "") else None
        )
        raw_reason = _value(raw, "reason", f"{market}_reason")
        reason = str(raw_reason or "").strip().upper() or None
        if reason not in _REASONS:
            raise MoexCalendarDataError(
                f"calendar {tradedate}: unsupported reason {reason!r}")
        if reason == "W" and (is_traded != 1 or session is None):
            raise MoexCalendarDataError(
                f"calendar {tradedate}: W requires is_traded=1 and "
                "trade_session_date")
        if session is not None and session < tradedate:
            raise MoexCalendarDataError(
                f"calendar {tradedate}: trade_session_date cannot be earlier")
        if is_traded == 0 and session is not None:
            raise MoexCalendarDataError(
                f"calendar {tradedate}: closed day cannot map to a session")
        if reason == "W" and session == tradedate:
            raise MoexCalendarDataError(
                f"calendar {tradedate}: W must map to a later session")
        raw_update = _value(raw, "updatetime")
        by_date[tradedate] = {
            "tradedate": tradedate,
            "is_traded": is_traded,
            "trade_session_date": session,
            "reason": reason,
            "updatetime": (
                str(raw_update).strip()
                if raw_update not in (None, "") else None),
        }

    missing = sorted(set(expected) - set(by_date))
    outside = sorted(set(by_date) - set(expected))
    if missing or outside:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing[:5]))
        if outside:
            details.append("outside range " + ", ".join(outside[:5]))
        raise MoexCalendarCoverageError(
            "MOEX calendar does not fully cover the requested interval: "
            + "; ".join(details))

    # A weekend session is part of a named future trading session.  Require
    # that target to exist and be open in the same governed payload; callers
    # should request a wider range rather than infer a target beyond coverage.
    for tradedate, row in by_date.items():
        target = row["trade_session_date"]
        if row["is_traded"] and target is not None:
            target_row = by_date.get(target)
            if target_row is None:
                raise MoexCalendarCoverageError(
                    f"calendar {tradedate}: trade_session_date {target} is "
                    "outside governed coverage")
            if target_row["is_traded"] != 1:
                raise MoexCalendarDataError(
                    f"calendar {tradedate}: mapped session {target} is not open")
    return [by_date[token] for token in expected]


def calendar_payload_hash(
    *,
    calendar_id: str,
    market: str,
    from_date,
    till_date,
    days: Iterable[dict],
) -> str:
    """Hash only economic calendar semantics, independent of row ordering.

    ``updatetime`` is retained as source evidence but deliberately excluded:
    a transport refresh that does not change a trading decision must not cut a
    new calculation-relevant version.
    """
    start = _day(from_date, field="from_date").isoformat()
    end = _day(till_date, field="till_date").isoformat()
    semantic = [
        {
            "tradedate": str(row["tradedate"]),
            "is_traded": int(row["is_traded"]),
            "trade_session_date": row.get("trade_session_date"),
            "reason": row.get("reason"),
        }
        for row in days
    ]
    semantic.sort(key=lambda row: row["tradedate"])
    payload = {
        "contract": CALENDAR_CONTRACT,
        "calendar_id": str(calendar_id).strip().upper(),
        "market": str(market).strip().lower(),
        "from_date": start,
        "till_date": end,
        "days": semantic,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MoexCalendarPayload:
    calendar_id: str
    market: str
    from_date: str
    till_date: str
    days: tuple[dict, ...]
    payload_hash: str
    source: str
    source_url: str
    fetched_at: str
    source_updated_at: str | None


class MoexCalendarProvider:
    """Fetch and validate MOEX ``calendars/<market>`` through an injected client."""

    def __init__(self, client):
        self.client = client

    def fetch(
        self,
        from_date,
        till_date,
        *,
        market: str = "stock",
        calendar_id: str | None = None,
        fetched_at=None,
    ) -> MoexCalendarPayload:
        market = str(market or "").strip().lower()
        if market not in MOEX_CALENDAR_IDS:
            raise MoexCalendarDataError(
                f"unsupported MOEX calendar market {market!r}")
        start = _day(from_date, field="from_date")
        end = _day(till_date, field="till_date")
        _expected_dates(start, end)
        resolved_id = str(
            calendar_id or MOEX_CALENDAR_IDS[market]).strip().upper()
        if not resolved_id:
            raise MoexCalendarDataError("calendar_id is required")
        endpoint = f"calendars/{market}"
        # MOEX documents calendar filtering within one calendar year.  Split a
        # long-dated product interval into deterministic annual requests, then
        # validate the union as one governed version.
        rows = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(end, date(chunk_start.year, 12, 31))
            params = {
                "show_all_days": 1,
                "iss.only": "off_days",
                "from": chunk_start.isoformat(),
                "till": chunk_end.isoformat(),
            }
            rows.extend(self.client.get_block_paginated(
                endpoint, "off_days", params, page_size=1))
            chunk_start = chunk_end + timedelta(days=1)
        days = normalise_calendar_days(
            rows, market=market, from_date=start, till_date=end)
        digest = calendar_payload_hash(
            calendar_id=resolved_id,
            market=market,
            from_date=start,
            till_date=end,
            days=days,
        )
        updates = sorted(
            row["updatetime"] for row in days if row.get("updatetime"))
        timestamp = fetched_at or datetime.now(timezone.utc)
        fetched_token = (
            timestamp.isoformat() if isinstance(timestamp, (date, datetime))
            else str(timestamp)
        )
        base_url = str(
            getattr(self.client, "base_url", "https://iss.moex.com/iss")
        ).rstrip("/")
        return MoexCalendarPayload(
            calendar_id=resolved_id,
            market=market,
            from_date=start.isoformat(),
            till_date=end.isoformat(),
            days=tuple(days),
            payload_hash=digest,
            source="MOEX",
            source_url=f"{base_url}/{endpoint}",
            fetched_at=fetched_token,
            source_updated_at=updates[-1] if updates else None,
        )


class MoexCalendarResolver:
    """Fail-closed business-session and BDC operations for one DB version."""

    def __init__(self, version: dict, days: Iterable[dict]):
        if not isinstance(version, dict):
            raise MoexCalendarDataError("calendar version metadata is required")
        self.calendar_id = str(version.get("calendar_id") or "").strip().upper()
        self.market = str(version.get("market") or "").strip().lower()
        try:
            self.version = int(version.get("version"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise MoexCalendarDataError(
                "calendar version must be a positive integer") from exc
        if self.version < 1 or not self.calendar_id:
            raise MoexCalendarDataError("invalid calendar version identity")
        self.from_date = _day(version.get("from_date"), field="from_date")
        self.till_date = _day(version.get("till_date"), field="till_date")
        normalised = normalise_calendar_days(
            days,
            market=self.market,
            from_date=self.from_date,
            till_date=self.till_date,
        )
        expected_hash = calendar_payload_hash(
            calendar_id=self.calendar_id,
            market=self.market,
            from_date=self.from_date,
            till_date=self.till_date,
            days=normalised,
        )
        stored_hash = str(version.get("payload_hash") or "").strip().lower()
        if stored_hash != expected_hash:
            raise MoexCalendarDataError(
                "persisted calendar payload hash does not match its day rows")
        if int(version.get("row_count") or -1) != len(normalised):
            raise MoexCalendarDataError(
                "persisted calendar row_count does not match its day rows")
        self.payload_hash = expected_hash
        self._days = {row["tradedate"]: row for row in normalised}
        self._sessions = {
            (row.get("trade_session_date") or row["tradedate"])
            for row in normalised if row["is_traded"] == 1
        }
        self.evidence = {
            "contract": CALENDAR_CONTRACT,
            "calendar_id": self.calendar_id,
            "version": self.version,
            "market": self.market,
            "from_date": self.from_date.isoformat(),
            "till_date": self.till_date.isoformat(),
            "payload_hash": self.payload_hash,
            "source": version.get("source"),
            "source_url": version.get("source_url"),
            "fetched_at": version.get("fetched_at"),
            "source_updated_at": version.get("source_updated_at"),
            "row_count": len(normalised),
            "session_count": len(self._sessions),
        }

    @classmethod
    def from_db(
        cls, db, calendar_id: str = "MOEX_STOCK", version: int | None = None,
    ) -> "MoexCalendarResolver":
        metadata = db.get_trading_calendar_version(calendar_id, version)
        if metadata is None:
            suffix = "latest" if version is None else str(version)
            raise MoexCalendarCoverageError(
                f"calendar {calendar_id} version {suffix} is unavailable")
        rows = db.get_trading_calendar_days(
            metadata["calendar_id"], int(metadata["version"]))
        return cls(metadata, rows)

    def _covered_day(self, value) -> tuple[date, dict]:
        parsed = _day(value, field="date")
        row = self._days.get(parsed.isoformat())
        if row is None:
            raise MoexCalendarCoverageError(
                f"date {parsed.isoformat()} is outside calendar "
                f"{self.calendar_id} v{self.version} coverage")
        return parsed, row

    def calendar_day_is_traded(self, value) -> bool:
        """Whether trades occur on this physical calendar date."""
        _parsed, row = self._covered_day(value)
        return bool(row["is_traded"])

    def session_date_for(self, value) -> date | None:
        """Map a physical trading date to its official trade-session date."""
        parsed, row = self._covered_day(value)
        if row["is_traded"] != 1:
            return None
        return _day(
            row.get("trade_session_date") or parsed,
            field="trade_session_date",
        )

    def is_business_day(self, value) -> bool:
        """Whether ``value`` is a distinct contractual MOEX session date."""
        parsed, _row = self._covered_day(value)
        return parsed.isoformat() in self._sessions

    def business_sessions(self, from_date, till_date) -> list[date]:
        start, _ = self._covered_day(from_date)
        end, _ = self._covered_day(till_date)
        if start > end:
            raise MoexCalendarCoverageError(
                "from_date must be on or before till_date")
        return [
            date.fromisoformat(token)
            for token in sorted(self._sessions)
            if start.isoformat() <= token <= end.isoformat()
        ]

    def adjust(self, value, convention: str = "following") -> date:
        raw, _ = self._covered_day(value)
        key = str(convention or "").strip().lower().replace("_", "-")
        if key in {"none", "unadjusted"}:
            return raw
        if key not in {
                "following", "modified-following", "preceding",
                "modified-preceding"}:
            raise MoexCalendarDataError(
                f"unsupported business-day convention {convention!r}")
        if self.is_business_day(raw):
            return raw

        direction = 1 if key in {"following", "modified-following"} else -1
        adjusted = raw
        while True:
            adjusted += timedelta(days=direction)
            self._covered_day(adjusted)
            if self.is_business_day(adjusted):
                break
        if key == "modified-following" and adjusted.month != raw.month:
            return self.adjust(raw, "preceding")
        if key == "modified-preceding" and adjusted.month != raw.month:
            return self.adjust(raw, "following")
        return adjusted

    def advance_business_days(self, value, days: int) -> date:
        if isinstance(days, bool) or not isinstance(days, int):
            raise MoexCalendarDataError("days must be an integer")
        current, _ = self._covered_day(value)
        if days == 0:
            return self.adjust(current, "following")
        direction = 1 if days > 0 else -1
        remaining = abs(days)
        while remaining:
            current += timedelta(days=direction)
            self._covered_day(current)
            if self.is_business_day(current):
                remaining -= 1
        return current
