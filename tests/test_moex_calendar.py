"""Governed MOEX machine-readable calendar and exact fixing contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib

import pytest

from infra.db.market_data_db import MarketDataDB
from infra.moex_calendar import (
    MoexCalendarCoverageError,
    MoexCalendarDataError,
    MoexCalendarProvider,
    MoexCalendarResolver,
    calendar_payload_hash,
    normalise_calendar_days,
)
from infra.moex_iss.ingest import MoexIngestor


class _CalendarIss:
    base_url = "https://iss.moex.com/iss"

    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def get_block_paginated(self, path, block, params, **kwargs):
        self.calls.append((path, block, dict(params), dict(kwargs)))
        return deepcopy([
            row for row in self.rows
            if params["from"] <= row["tradedate"] <= params["till"]
        ])


@pytest.fixture
def db():
    value = MarketDataDB(":memory:")
    yield value
    value.close()


def _physical_rows(start: date, end: date, overrides=None) -> list[dict]:
    overrides = overrides or {}
    rows = []
    cursor = start
    while cursor <= end:
        row = {
            "tradedate": cursor.isoformat(),
            "is_traded": 1 if cursor.weekday() < 5 else 0,
            "trade_session_date": None,
            "reason": "N" if cursor.weekday() < 5 else "H",
            "updatetime": "2025-01-01 10:00:00",
        }
        row.update(overrides.get(cursor.isoformat(), {}))
        rows.append(row)
        cursor += timedelta(days=1)
    return rows


def _weekend_session_rows() -> tuple[date, date, list[dict]]:
    start, end = date(2025, 2, 28), date(2025, 3, 4)
    rows = _physical_rows(start, end, {
        "2025-03-01": {
            "is_traded": 1,
            "trade_session_date": "2025-03-03",
            "reason": "W",
            "updatetime": "2025-03-01 10:25:04",
        },
    })
    return start, end, rows


def test_stock_calendar_ingest_is_versioned_and_collapses_weekend_session(db):
    start, end, rows = _weekend_session_rows()
    client = _CalendarIss(list(reversed(rows)))

    stored = MoexIngestor(client, db).ingest_stock_calendar(
        start, end, fetched_at=datetime(2025, 2, 1, 12, 0, 0))

    assert stored["created"] is True
    assert stored["version"] == 1
    assert stored["calendar_id"] == "MOEX_STOCK"
    assert len(stored["payload_hash"]) == 64
    assert client.calls == [(
        "calendars/stock",
        "off_days",
        {
            "show_all_days": 1,
            "iss.only": "off_days",
            "from": "2025-02-28",
            "till": "2025-03-04",
        },
        {"page_size": 1},
    )]

    calendar = MoexCalendarResolver.from_db(db)
    assert calendar.calendar_day_is_traded(date(2025, 3, 1)) is True
    assert calendar.session_date_for(date(2025, 3, 1)) == date(2025, 3, 3)
    assert calendar.is_business_day(date(2025, 3, 1)) is False
    assert calendar.business_sessions(start, end) == [
        date(2025, 2, 28), date(2025, 3, 3), date(2025, 3, 4),
    ]
    assert calendar.adjust(date(2025, 3, 1), "following") == date(2025, 3, 3)
    assert calendar.adjust(date(2025, 3, 1), "preceding") == date(2025, 2, 28)
    assert calendar.evidence["session_count"] == 3
    assert calendar.evidence["payload_hash"] == stored["payload_hash"]


def test_transferred_working_weekend_is_a_distinct_business_session(db):
    start, end = date(2025, 4, 25), date(2025, 4, 27)
    rows = _physical_rows(start, end, {
        "2025-04-26": {"is_traded": 1, "reason": "T"},
    })
    client = _CalendarIss(rows)
    MoexIngestor(client, db).ingest_stock_calendar(
        start, end, calendar_id="MOEX_STOCK_TRANSFER")

    calendar = MoexCalendarResolver.from_db(db, "MOEX_STOCK_TRANSFER")
    assert calendar.calendar_day_is_traded("2025-04-26") is True
    assert calendar.session_date_for("2025-04-26") == date(2025, 4, 26)
    assert calendar.is_business_day("2025-04-26") is True
    assert calendar.business_sessions(start, end) == [
        date(2025, 4, 25), date(2025, 4, 26),
    ]
    assert calendar.adjust("2025-04-27", "preceding") == date(2025, 4, 26)


def test_holiday_and_modified_following_use_governed_coverage(db):
    start, end = date(2026, 1, 30), date(2026, 2, 2)
    rows = _physical_rows(start, end)
    MoexIngestor(_CalendarIss(rows), db).ingest_stock_calendar(
        start, end, calendar_id="MOEX_STOCK_MONTH_END")
    calendar = MoexCalendarResolver.from_db(db, "MOEX_STOCK_MONTH_END")

    assert calendar.calendar_day_is_traded("2026-01-31") is False
    assert calendar.session_date_for("2026-01-31") is None
    assert calendar.adjust("2026-01-31", "following") == date(2026, 2, 2)
    assert calendar.adjust("2026-01-31", "modified_following") == date(2026, 1, 30)
    with pytest.raises(MoexCalendarCoverageError, match="outside calendar"):
        calendar.advance_business_days("2026-02-02", 1)


def test_calendar_ingest_fails_closed_on_gap_or_null_flag_and_logs_error(db):
    start, end, rows = _weekend_session_rows()
    missing = [row for row in rows if row["tradedate"] != "2025-03-02"]
    with pytest.raises(MoexCalendarCoverageError, match="missing 2025-03-02"):
        MoexIngestor(_CalendarIss(missing), db).ingest_stock_calendar(start, end)
    assert db.get_trading_calendar_version("MOEX_STOCK") is None

    bad = deepcopy(rows)
    bad[0]["is_traded"] = None
    with pytest.raises(MoexCalendarDataError, match="is_traded"):
        MoexIngestor(_CalendarIss(bad), db).ingest_stock_calendar(start, end)
    assert [row["status"] for row in db.recent_ingest_log()] == ["error", "error"]


def test_weekend_session_target_must_be_inside_open_coverage():
    rows = [{
        "tradedate": "2025-03-01",
        "is_traded": 1,
        "trade_session_date": "2025-03-03",
        "reason": "W",
    }]
    with pytest.raises(MoexCalendarCoverageError, match="outside governed coverage"):
        MoexCalendarProvider(_CalendarIss(rows)).fetch(
            date(2025, 3, 1), date(2025, 3, 1))


def test_calendar_hash_is_order_and_transport_timestamp_invariant():
    start, end, rows = _weekend_session_rows()
    canonical = normalise_calendar_days(
        rows, market="stock", from_date=start, till_date=end)
    first = calendar_payload_hash(
        calendar_id="MOEX_STOCK", market="stock",
        from_date=start, till_date=end, days=canonical)
    changed_updates = deepcopy(list(reversed(canonical)))
    for row in changed_updates:
        row["updatetime"] = "2099-01-01 00:00:00"
    second = calendar_payload_hash(
        calendar_id="MOEX_STOCK", market="stock",
        from_date=start, till_date=end, days=changed_updates)
    assert first == second

    changed_semantics = deepcopy(canonical)
    changed_semantics[0]["reason"] = "T"
    third = calendar_payload_hash(
        calendar_id="MOEX_STOCK", market="stock",
        from_date=start, till_date=end, days=changed_semantics)
    assert third != first


def test_provider_splits_cross_year_range_and_hashes_one_payload():
    start, end = date(2025, 12, 30), date(2026, 1, 2)
    rows = _physical_rows(start, end)
    client = _CalendarIss(rows)

    payload = MoexCalendarProvider(client).fetch(start, end)

    assert len(payload.days) == 4
    assert [(call[2]["from"], call[2]["till"]) for call in client.calls] == [
        ("2025-12-30", "2025-12-31"),
        ("2026-01-01", "2026-01-02"),
    ]
    assert payload.payload_hash == calendar_payload_hash(
        calendar_id="MOEX_STOCK", market="stock",
        from_date=start, till_date=end, days=payload.days)


def test_identical_calendar_is_idempotent_and_revision_cuts_version(db):
    start, end, rows = _weekend_session_rows()
    ingestor = MoexIngestor(_CalendarIss(rows), db)
    first = ingestor.ingest_stock_calendar(start, end)
    repeated = ingestor.ingest_stock_calendar(start, end)
    assert repeated["created"] is False
    assert repeated["version"] == first["version"] == 1

    revised = deepcopy(rows)
    revised[0]["reason"] = "T"
    second = MoexIngestor(_CalendarIss(revised), db).ingest_stock_calendar(
        start, end)
    assert second["created"] is True and second["version"] == 2
    assert [row["version"] for row in
            db.list_trading_calendar_versions("MOEX_STOCK")] == [1, 2]
    assert MoexCalendarResolver.from_db(db, version=1).payload_hash == first[
        "payload_hash"]
    assert MoexCalendarResolver.from_db(db).payload_hash == second["payload_hash"]


def test_resolver_detects_persisted_calendar_tampering(db):
    start, end, rows = _weekend_session_rows()
    MoexIngestor(_CalendarIss(rows), db).ingest_stock_calendar(start, end)
    db._exec(  # noqa: SLF001 - deliberate corruption probe
        "UPDATE trading_calendar_days SET reason='T' "
        "WHERE calendar_id='MOEX_STOCK' AND version=1 "
        "AND tradedate='2025-02-28'")
    with pytest.raises(MoexCalendarDataError, match="payload hash"):
        MoexCalendarResolver.from_db(db)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_contract_fixings_are_exact_immutable_and_basis_specific(db):
    close_hash = _digest("SBER close response")
    legal_hash = _digest("SBER legal close response")
    rows = [
        {
            "factor_id": "SBER:price", "observed_date": "2026-07-01",
            "value": 321.5, "price_basis": "close", "board": "tqbr",
            "session": "trading_day_total", "source": "moex",
            "fetched_at": "2026-07-02T00:10:00", "payload_hash": close_hash,
        },
        {
            "factor_id": "SBER:price", "observed_date": "2026-07-02",
            "value": 324.0, "price_basis": "close", "board": "tqbr",
            "session": "trading_day_total", "source": "moex",
            "fetched_at": "2026-07-03T00:10:00", "payload_hash": close_hash,
        },
        {
            "factor_id": "SBER:price", "observed_date": "2026-07-02",
            "value": 323.8, "price_basis": "legal_close", "board": "tqbr",
            "session": "trading_day_total", "source": "moex",
            "fetched_at": "2026-07-03T00:10:00", "payload_hash": legal_hash,
        },
    ]
    assert db.save_contract_fixings(rows) == 3
    assert db.save_contract_fixings(rows) == 0

    exact = db.get_contract_fixings_window(
        "SBER:price", "2026-07-01", "2026-07-02",
        price_basis="close", board="TQBR", session="TRADING_DAY_TOTAL",
        source="MOEX")
    assert [(row["observed_date"], row["value"]) for row in exact] == [
        ("2026-07-01", 321.5), ("2026-07-02", 324.0),
    ]
    assert db.get_contract_fixing(
        "SBER:price", "2026-06-30", price_basis="CLOSE", board="TQBR",
        session="TRADING_DAY_TOTAL", source="MOEX") is None
    assert db.get_contract_fixing(
        "SBER:price", "2026-07-02", price_basis="LEGAL_CLOSE", board="TQBR",
        session="TRADING_DAY_TOTAL", source="MOEX")["value"] == 323.8


def test_contract_fixing_identity_conflict_and_bad_hash_fail_closed(db):
    row = {
        "factor_id": "IMOEX:price", "observed_date": "2026-07-01",
        "value": 2800.0, "price_basis": "CLOSE", "source": "MOEX",
        "fetched_at": "2026-07-02T00:00:00", "payload_hash": _digest("one"),
    }
    assert db.save_contract_fixings([row]) == 1
    with pytest.raises(ValueError, match="already exists"):
        db.save_contract_fixings([{**row, "value": 2801.0,
                                   "payload_hash": _digest("two")}])
    assert db.get_contract_fixing(
        "IMOEX:price", "2026-07-01", price_basis="CLOSE",
        source="MOEX")["value"] == 2800.0

    with pytest.raises(ValueError, match="SHA-256"):
        db.save_contract_fixings([{**row, "observed_date": "2026-07-02",
                                   "payload_hash": "not-a-hash"}])


def test_schema_contains_calendar_and_contract_fixing_tables(db):
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {row["name"] for row in rows}
    assert {
        "trading_calendar_versions", "trading_calendar_days",
        "contract_fixings",
    }.issubset(names)
