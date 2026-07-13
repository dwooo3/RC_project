"""MR-8B local orchestration: deterministic rebuild and readiness evidence."""

from __future__ import annotations

import struct
import threading
from datetime import date, datetime, timedelta

import pytest

from infra.db.market_data_db import MarketDataDB
from infra.jobs.iv30_operational import Iv30OperationalJob, iv30_readiness_report


DAYS = [date(2026, 6, 8) + timedelta(days=offset) for offset in range(3)]


def _point(day: date, strike: float, *, underlying="TEST", status="verified",
           iv=0.25) -> dict:
    return {
        "underlying": underlying,
        "expiry": (day + timedelta(days=30)).isoformat(),
        "strike": strike,
        "iv": iv,
        "forward": 100.0,
        "tenor_days": 30,
        "open_interest": 100.0,
        "observation_date": day.isoformat(),
        "source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
        "method": "black76_settlement",
        "observation_status": status,
        "option_price_date": day.isoformat(),
        "forward_date": day.isoformat(),
        "option_price_source": "MOEX_FORTS_OPTION_SETTLEMENT",
        "forward_source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
        "option_price_basis": "settlement",
        "forward_basis": "underlying_settlement",
    }


def _seed_snapshot(db, day: date, *, snapshot_id=None, status="verified") -> str:
    snapshot_id = snapshot_id or f"moex-{day.isoformat()}"
    db.save_snapshot_meta(
        snapshot_id=snapshot_id,
        valuation_date=day,
        source="MOEX",
        quality="OK",
        fetch_ts=datetime.combine(day, datetime.min.time()),
    )
    db.replace_vol_surface(
        snapshot_id,
        [_point(day, 90.0, status=status), _point(day, 110.0, status=status)],
    )
    return snapshot_id


def test_operational_backfill_is_idempotent_and_proves_depth():
    db = MarketDataDB(":memory:")
    for day in DAYS:
        _seed_snapshot(db, day)
    db.replace_iv30_for_date(DAYS[0], {"ROGUE": 0.80})
    job = Iv30OperationalJob(db)

    first = job.run(
        DAYS[0], DAYS[-1], min_shocks=2, expected_dates=DAYS,
        stress_dates=[DAYS[0], DAYS[-1]],
    )
    second = job.run(
        DAYS[0], DAYS[-1], min_shocks=2, expected_dates=DAYS,
        stress_dates=[DAYS[0], DAYS[-1]],
    )

    assert first["status"] == second["status"] == "ready"
    assert first["processed_dates"] == first["published_dates"] == 3
    assert first["readiness"]["ready"] is True
    factor = first["readiness"]["factors"]["IV30:TEST"]
    assert factor["levels"] == 3
    assert factor["valid_shocks"] == 2
    assert factor["covered_snapshot_dates"] == 3
    assert db.get_time_series("IV30:ROGUE", "vol") == []
    assert len(db.get_time_series("IV30:TEST", "vol")) == 3


def test_operational_backfill_revokes_timestamped_rogue_same_day_level():
    db = MarketDataDB(":memory:")
    _seed_snapshot(db, DAYS[0])
    db.save_time_series(
        "IV30:ROGUE", "vol", [(f"{DAYS[0].isoformat()}T12:00:00", 0.80)]
    )

    result = Iv30OperationalJob(db).run(
        DAYS[0], DAYS[0], min_shocks=0, expected_dates=[DAYS[0]]
    )

    assert result["status"] == "ready"
    assert db.get_time_series("IV30:ROGUE", "vol") == []


def test_operational_backfill_revokes_unverified_day_and_fails_closed():
    db = MarketDataDB(":memory:")
    _seed_snapshot(db, DAYS[0])
    _seed_snapshot(db, DAYS[1], status="missing_forward_date")
    db.replace_iv30_for_date(DAYS[0], {"TEST": 0.40})
    db.replace_iv30_for_date(DAYS[1], {"TEST": 0.40})

    result = Iv30OperationalJob(db).run(
        DAYS[0], DAYS[1], min_shocks=0, expected_dates=DAYS[:2]
    )

    assert result["status"] == "not_ready"
    assert result["revoked_or_empty_dates"] == 1
    assert result["runs"][DAYS[1].isoformat()]["status"] == "skipped"
    factor = result["readiness"]["factors"]["IV30:TEST"]
    assert factor["missing_snapshot_dates"] == [DAYS[1].isoformat()]
    assert db.get_time_series("IV30:TEST", "vol") == [
        {"dt": DAYS[0].isoformat(), "value": pytest.approx(0.25)}
    ]


def test_readiness_accepts_explicit_calendar_and_reports_missing_snapshot():
    db = MarketDataDB(":memory:")
    for day in DAYS[:2]:
        _seed_snapshot(db, day)
    Iv30OperationalJob(db).run(DAYS[0], DAYS[1], min_shocks=1)

    report = iv30_readiness_report(
        db,
        DAYS[0],
        DAYS[-1],
        min_shocks=1,
        expected_dates=DAYS,
    )

    assert report["ready"] is False
    assert report["missing_snapshot_dates"] == [DAYS[-1].isoformat()]
    assert "missing_snapshot_dates" in report["blockers"]
    assert report["factors"]["IV30:TEST"]["valid_shocks"] == 1


def test_orphan_iv30_level_cannot_manufacture_governed_shock_depth():
    db = MarketDataDB(":memory:")
    for day in DAYS[:2]:
        _seed_snapshot(db, day)
    Iv30OperationalJob(db).run(DAYS[0], DAYS[1], min_shocks=1)
    db.save_time_series("IV30:TEST", "vol", [(DAYS[2].isoformat(), 0.26)])

    report = iv30_readiness_report(
        db, DAYS[0], DAYS[2], min_shocks=2, as_of=DAYS[2]
    )

    factor = report["factors"]["IV30:TEST"]
    assert report["ready"] is False
    assert factor["levels"] == 3
    assert factor["governed_levels"] == 2
    assert factor["valid_shocks"] == 1
    assert factor["unexpected_level_dates"] == [DAYS[2].isoformat()]


def test_underlying_added_mid_window_does_not_get_a_shorter_ready_calendar():
    db = MarketDataDB(":memory:")
    for index, day in enumerate(DAYS):
        snapshot_id = _seed_snapshot(db, day)
        if index:
            db.replace_vol_surface(
                snapshot_id,
                [
                    _point(day, 90.0), _point(day, 110.0),
                    _point(day, 90.0, underlying="B"),
                    _point(day, 110.0, underlying="B"),
                ],
            )
    result = Iv30OperationalJob(db).run(
        DAYS[0], DAYS[-1], min_shocks=1, expected_dates=DAYS
    )

    factor = result["readiness"]["factors"]["IV30:B"]
    assert result["status"] == "not_ready"
    assert factor["missing_native_surface_dates"] == [DAYS[0].isoformat()]
    assert factor["valid_shocks"] == 1
    assert factor["ready"] is False


def test_middle_surface_gap_is_not_counted_as_one_multiday_shock():
    db = MarketDataDB(":memory:")
    for index, day in enumerate(DAYS):
        snapshot_id = _seed_snapshot(db, day)
        if index != 1:
            db.replace_vol_surface(
                snapshot_id,
                [
                    _point(day, 90.0), _point(day, 110.0),
                    _point(day, 90.0, underlying="B"),
                    _point(day, 110.0, underlying="B"),
                ],
            )
    result = Iv30OperationalJob(db).run(
        DAYS[0], DAYS[-1], min_shocks=1, expected_dates=DAYS
    )

    factor = result["readiness"]["factors"]["IV30:B"]
    assert factor["governed_levels"] == 2
    assert factor["valid_shocks"] == 0
    assert factor["missing_native_surface_dates"] == [DAYS[1].isoformat()]
    assert factor["ready"] is False


def test_explicit_calendar_prevents_extra_snapshot_lookahead_depth():
    db = MarketDataDB(":memory:")
    for day in DAYS:
        _seed_snapshot(db, day)
    Iv30OperationalJob(db).run(DAYS[0], DAYS[-1], min_shocks=2)

    report = iv30_readiness_report(
        db,
        DAYS[0],
        DAYS[-1],
        min_shocks=2,
        expected_dates=DAYS[:2],
        as_of=DAYS[1],
    )

    factor = report["factors"]["IV30:TEST"]
    assert report["ready"] is False
    assert factor["valid_shocks"] == 1
    assert factor["unexpected_level_dates"] == [DAYS[2].isoformat()]
    assert report["stored_snapshot_dates_after_as_of"] == [DAYS[2].isoformat()]


def test_readiness_requires_snapshot_quality_and_raw_provenance_lineage():
    db = MarketDataDB(":memory:")
    snapshot_id = "moex-fail"
    db.save_snapshot_meta(
        snapshot_id=snapshot_id,
        valuation_date=DAYS[0],
        source="MOEX",
        quality="FAIL",
        fetch_ts=datetime.combine(DAYS[0], datetime.min.time()),
    )
    for strike in (90.0, 110.0):
        db.save_vol_point(
            snapshot_id, "TEST", (DAYS[0] + timedelta(days=30)), strike, 0.25
        )
    db.replace_iv30_for_date(DAYS[0], {"TEST": 0.25})

    report = iv30_readiness_report(
        db, DAYS[0], DAYS[0], min_shocks=0, expected_dates=[DAYS[0]]
    )

    failures = report["snapshot_lineage_failures"][DAYS[0].isoformat()]
    assert report["ready"] is False
    assert "snapshot_quality_not_ok" in failures
    assert "vol_point_provenance_missing" in failures
    assert "snapshot_iv30_lineage_not_governed" in report["blockers"]


def test_readiness_rejects_canonical_level_that_differs_from_recomputed_iv30():
    db = MarketDataDB(":memory:")
    _seed_snapshot(db, DAYS[0])
    db.replace_iv30_for_date(DAYS[0], {"TEST": 0.99})

    report = iv30_readiness_report(
        db, DAYS[0], DAYS[0], min_shocks=0, expected_dates=[DAYS[0]]
    )

    factor = report["factors"]["IV30:TEST"]
    assert report["ready"] is False
    assert factor["governed_levels"] == 0
    assert factor["representative_value_mismatch_dates"] == [DAYS[0].isoformat()]
    assert "factor_coverage_or_depth_insufficient" in report["blockers"]


def test_readiness_rejects_raw_provenance_iv_payload_mismatch():
    db = MarketDataDB(":memory:")
    snapshot_id = _seed_snapshot(db, DAYS[0])
    db.replace_iv30_for_date(DAYS[0], {"TEST": 0.25})
    db.save_vol_point(
        snapshot_id,
        "TEST",
        (DAYS[0] + timedelta(days=30)).isoformat(),
        90.0,
        0.99,
    )

    report = iv30_readiness_report(
        db, DAYS[0], DAYS[0], min_shocks=0, expected_dates=[DAYS[0]]
    )

    lineage = report["snapshot_lineage"][DAYS[0].isoformat()]
    failures = report["snapshot_lineage_failures"][DAYS[0].isoformat()]
    assert report["ready"] is False
    assert lineage["key_coverage_complete"] is True
    assert lineage["payload_match_complete"] is False
    assert lineage["iv_value_mismatch_keys"] == [
        f"TEST|{(DAYS[0] + timedelta(days=30)).isoformat()}|90"
    ]
    assert "raw_provenance_iv_mismatch" in failures


def test_readiness_rejects_invalid_point_even_when_keys_and_iv_match():
    db = MarketDataDB(":memory:")
    snapshot_id = _seed_snapshot(db, DAYS[0])
    db.replace_vol_surface(
        snapshot_id,
        [
            _point(DAYS[0], 90.0),
            _point(DAYS[0], 100.0, iv=None),
            _point(DAYS[0], 110.0),
        ],
    )
    db.replace_iv30_for_date(DAYS[0], {"TEST": 0.25})

    report = iv30_readiness_report(
        db, DAYS[0], DAYS[0], min_shocks=0, expected_dates=[DAYS[0]]
    )

    lineage = report["snapshot_lineage"][DAYS[0].isoformat()]
    failures = report["snapshot_lineage_failures"][DAYS[0].isoformat()]
    assert report["ready"] is False
    assert lineage["key_coverage_complete"] is True
    assert lineage["payload_match_complete"] is False
    assert lineage["invalid_raw_payloads"] == ["1:invalid_iv"]
    assert lineage["invalid_provenance_payloads"] == ["1:invalid_iv"]
    assert "invalid_vol_point_payload" in failures


def test_readiness_accepts_one_postgres_real_storage_roundtrip():
    db = MarketDataDB(":memory:")
    snapshot_id = "moex-float4"
    value = 0.3130547851390364
    db.save_snapshot_meta(
        snapshot_id=snapshot_id,
        valuation_date=DAYS[0],
        source="MOEX",
        quality="OK",
        fetch_ts=datetime.combine(DAYS[0], datetime.min.time()),
    )
    db.replace_vol_surface(
        snapshot_id,
        [_point(DAYS[0], 90.0, iv=value), _point(DAYS[0], 110.0, iv=value)],
    )
    float4_value = struct.unpack("!f", struct.pack("!f", value))[0]
    db.replace_iv30_for_date(DAYS[0], {"TEST": float4_value})

    report = iv30_readiness_report(
        db, DAYS[0], DAYS[0], min_shocks=0, expected_dates=[DAYS[0]]
    )

    assert report["ready"] is True
    assert report["factors"]["IV30:TEST"][
        "representative_value_mismatch_dates"
    ] == []


def test_partial_publisher_cannot_return_top_level_ready():
    db = MarketDataDB(":memory:")
    for day in DAYS:
        _seed_snapshot(db, day)
    assert Iv30OperationalJob(db).run(
        DAYS[0], DAYS[-1], min_shocks=2
    )["status"] == "ready"

    partial = Iv30OperationalJob(
        db,
        publisher=lambda snapshot_id, valuation_date: {
            "snapshot_id": snapshot_id,
            "valuation_date": valuation_date.isoformat(),
            "status": "partial",
            "saved": 1,
            "warnings": [],
            "rejected": {"OTHER": {"reason": "test"}},
            "quality_counts": {"OK": 1, "WARN": 0, "rejected": 1},
        },
    ).run(DAYS[0], DAYS[-1], min_shocks=2)

    assert partial["readiness"]["ready"] is True
    assert partial["status"] == "not_ready"
    assert set(partial["publication_issues"]) == {
        day.isoformat() for day in DAYS
    }


def test_ambiguous_snapshot_date_is_blocked_without_mutating_canonical_value():
    db = MarketDataDB(":memory:")
    _seed_snapshot(db, DAYS[0], snapshot_id="moex-a")
    _seed_snapshot(db, DAYS[0], snapshot_id="moex-b")
    db.replace_iv30_for_date(DAYS[0], {"TEST": 0.42})

    result = Iv30OperationalJob(db).run(
        DAYS[0], DAYS[0], min_shocks=0, expected_dates=[DAYS[0]]
    )

    assert result["status"] == "blocked"
    assert result["processed_dates"] == 0
    assert result["ambiguous_snapshot_dates"][DAYS[0].isoformat()] == [
        "moex-a", "moex-b",
    ]
    assert result["readiness"]["duplicate_snapshot_dates"]
    assert db.get_time_series("IV30:TEST", "vol") == [
        {"dt": DAYS[0].isoformat(), "value": 0.42}
    ]


def test_generic_factor_date_replace_is_scoped_and_prevalidates_duplicates():
    db = MarketDataDB(":memory:")
    day = DAYS[0].isoformat()
    db.save_time_series("IV_30:A", "vol", [(day, 0.20)])
    db.save_time_series("IVX30:KEEP", "vol", [(day, 0.90)])
    db.save_time_series("IV_30:RATE", "rate", [(day, 0.10)])

    db.replace_factor_levels_for_date("vol", "IV_30:", day, {"B": 0.30})

    assert db.get_time_series("IV_30:A", "vol") == []
    assert db.get_time_series("IV_30:B", "vol") == [{"dt": day, "value": 0.30}]

    for invalid_date in (None, "2026-02-30", "2026-06-08garbage"):
        with pytest.raises(ValueError, match="ISO date"):
            db.replace_factor_levels_for_date(
                "vol", "IV_30:", invalid_date, {"B": 0.99}
            )
    assert db.get_time_series("IV_30:B", "vol") == [{"dt": day, "value": 0.30}]
    assert db.get_time_series("IVX30:KEEP", "vol") == [{"dt": day, "value": 0.90}]
    assert db.get_time_series("IV_30:RATE", "rate") == [{"dt": day, "value": 0.10}]

    with pytest.raises(ValueError, match="duplicate factor id"):
        db.replace_factor_levels_for_date(
            "vol", "IV_30:", day, {"B": 0.40, "IV_30:B": 0.50}
        )
    assert db.get_time_series("IV_30:B", "vol") == [{"dt": day, "value": 0.30}]


def test_time_series_window_includes_timestamp_rows_through_end_of_day():
    db = MarketDataDB(":memory:")
    db.save_time_series(
        "IV30:TEST",
        "vol",
        [
            ("2026-06-08T23:59:59", 0.25),
            ("2026-06-09T00:00:00", 0.26),
        ],
    )

    assert db.get_time_series_window(
        "IV30:TEST", "vol", "2026-06-08", "2026-06-08"
    ) == [{"dt": "2026-06-08T23:59:59", "value": 0.25}]
    with pytest.raises(ValueError, match="from_date"):
        db.get_time_series_window(
            "IV30:TEST", "vol", "2026-06-09", "2026-06-08"
        )


def test_readiness_rejects_duplicate_date_and_timestamp_levels():
    db = MarketDataDB(":memory:")
    _seed_snapshot(db, DAYS[0])
    db.replace_iv30_for_date(DAYS[0], {"TEST": 0.25})
    db.save_time_series(
        "IV30:TEST", "vol", [(f"{DAYS[0].isoformat()}T12:00:00", 0.25)]
    )

    report = iv30_readiness_report(
        db, DAYS[0], DAYS[0], min_shocks=0, expected_dates=[DAYS[0]]
    )

    factor = report["factors"]["IV30:TEST"]
    assert report["ready"] is False
    assert factor["duplicate_level_dates"] == [DAYS[0].isoformat()]
    assert factor["ready"] is False


def test_postgres_factor_replace_sql_contract_without_external_server():
    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=()):
            self.calls.append(("execute", sql, params))

        def executemany(self, sql, rows):
            self.calls.append(("executemany", sql, rows))

    class Connection:
        def __init__(self):
            self.cur = Cursor()
            self.commits = 0
            self.rollbacks = 0

        def cursor(self):
            return self.cur

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    conn = Connection()
    db = object.__new__(MarketDataDB)
    db.conn = conn
    db.dialect = "postgres"
    db.ph = "%s"
    db._lock = threading.RLock()
    db._read_snapshot_depth = 0

    db.replace_factor_levels_for_date(
        "vol", "IV_30:", DAYS[0], {"TEST": 0.25}
    )

    delete = conn.cur.calls[0]
    upsert = conn.cur.calls[1]
    assert delete[0] == "execute"
    assert "kind=%s" in delete[1]
    assert "dt>=%s" in delete[1] and "dt<%s" in delete[1]
    assert "factor_id LIKE %s" in delete[1] and "?" not in delete[1]
    assert delete[2] == (
        "vol",
        DAYS[0].isoformat(),
        (DAYS[0] + timedelta(days=1)).isoformat(),
        r"IV\_30:%",
    )
    assert upsert[0] == "executemany"
    assert "ON CONFLICT (factor_id,dt,kind) DO UPDATE SET" in upsert[1]
    assert conn.commits == 1 and conn.rollbacks == 0


def test_snapshot_range_is_inclusive_for_timestamp_manifest_and_future_is_blocked():
    db = MarketDataDB(":memory:")
    snapshot_id = "moex-timestamp"
    db.save_snapshot_meta(
        snapshot_id=snapshot_id,
        valuation_date=datetime(2026, 6, 8, 23, 59),
        source="MOEX",
        quality="OK",
        fetch_ts=datetime(2026, 6, 8, 23, 59),
    )
    db.replace_vol_surface(
        snapshot_id, [_point(DAYS[0], 90.0), _point(DAYS[0], 110.0)]
    )
    assert db.list_snapshots_between(DAYS[0], DAYS[0], source="MOEX")[0][
        "snapshot_id"
    ] == snapshot_id
    Iv30OperationalJob(db).run(DAYS[0], DAYS[0], min_shocks=0)

    report = iv30_readiness_report(
        db, DAYS[0], DAYS[0], min_shocks=0,
        expected_dates=[DAYS[0]], as_of=DAYS[0] - timedelta(days=1),
    )

    assert report["ready"] is False
    assert report["snapshot_dates_after_as_of"] == [DAYS[0].isoformat()]
    assert "snapshot_dates_after_as_of" in report["blockers"]


def test_operational_arguments_are_fail_fast():
    db = MarketDataDB(":memory:")
    with pytest.raises(ValueError, match="from_date"):
        Iv30OperationalJob(db).run(DAYS[-1], DAYS[0])
    with pytest.raises(ValueError, match="expected_date"):
        iv30_readiness_report(
            db, DAYS[0], DAYS[-1], expected_dates=["2026-06-08garbage"]
        )
    with pytest.raises(ValueError, match="min_shocks"):
        iv30_readiness_report(db, DAYS[0], DAYS[-1], min_shocks=-1)

    class AutocommitConnection:
        autocommit = True

    with pytest.raises(ValueError, match="autocommit=False"):
        MarketDataDB(conn=AutocommitConnection(), dialect="postgres")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_shocks": -1},
        {"max_staleness_days": -1},
        {"expected_dates": ["2026-06-08garbage"]},
        {"stress_dates": ["2026-06-08garbage"]},
        {"as_of": "2026-06-08garbage"},
        {"as_of": ""},
        {"required_underlyings": [""]},
    ],
)
def test_operational_invalid_arguments_never_call_publisher(kwargs):
    db = MarketDataDB(":memory:")
    _seed_snapshot(db, DAYS[0])
    calls = []

    def publisher(snapshot_id, valuation_date):
        calls.append((snapshot_id, valuation_date))
        return {"status": "ok", "saved": 1}

    with pytest.raises(ValueError):
        Iv30OperationalJob(db, publisher=publisher).run(
            DAYS[0], DAYS[0], **kwargs
        )

    assert calls == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expected_dates": [DAYS[0] - timedelta(days=1)]},
        {"expected_dates": [DAYS[-1] + timedelta(days=1)]},
        {"stress_dates": [DAYS[-1] + timedelta(days=1)]},
        {"expected_dates": [DAYS[0]], "stress_dates": [DAYS[1]]},
    ],
)
def test_operational_out_of_range_calendar_never_calls_publisher(kwargs):
    db = MarketDataDB(":memory:")
    _seed_snapshot(db, DAYS[0])
    calls = []

    with pytest.raises(ValueError):
        Iv30OperationalJob(
            db, publisher=lambda *args: calls.append(args)
        ).run(DAYS[0], DAYS[-1], **kwargs)

    assert calls == []
