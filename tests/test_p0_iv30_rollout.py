"""MR-8B2 bounded rollout: read-only CLI, gate and schedule contracts."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime, timedelta

import pytest

import infra.jobs.iv30_rollout as rollout
import run_iv30_readiness as cli
from infra.db.market_data_db import MarketDataDB
from infra.jobs.data_quality import (
    QUALITY_CONTRACT_VERSION,
    snapshot_data_fingerprint,
)


DAYS = (date(2026, 6, 1), date(2026, 6, 2))


def _point(day: date, strike: float) -> dict:
    return {
        "underlying": "TEST",
        "expiry": (day + timedelta(days=30)).isoformat(),
        "strike": strike,
        "iv": 0.25,
        "forward": 100.0,
        "tenor_days": 30,
        "open_interest": 100.0,
        "observation_date": day.isoformat(),
        "source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
        "method": "black76_settlement",
        "observation_status": "verified",
        "option_price_date": day.isoformat(),
        "forward_date": day.isoformat(),
        "option_price_source": "MOEX_FORTS_OPTION_SETTLEMENT",
        "forward_source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
        "option_price_basis": "settlement",
        "forward_basis": "underlying_settlement",
    }


def _seed_ready_database(path, days=DAYS) -> None:
    db = MarketDataDB(str(path))
    try:
        for day in days:
            snapshot_id = f"moex-{day.isoformat()}"
            db.save_snapshot_meta(
                snapshot_id=snapshot_id,
                valuation_date=day,
                source="MOEX",
                quality="OK",
                fetch_ts=datetime.combine(day, datetime.min.time()),
            )
            db.replace_vol_surface(
                snapshot_id,
                [_point(day, 90.0), _point(day, 110.0)],
            )
            # Direct fixture seeding only: the bounded CLI must never run a publisher.
            db.replace_iv30_for_date(day, {"TEST": 0.25})
            db.save_validation_report(snapshot_id, {
                "status": "OK",
                "production_eligible": True,
                "completeness_pct": 100.0,
                "staleness_days": 0,
                "alerts": [],
                "checks": {
                    "contract_version": QUALITY_CONTRACT_VERSION,
                    "snapshot_fingerprint": snapshot_data_fingerprint(
                        db, snapshot_id
                    ),
                },
            })
    finally:
        db.close()


def _config_payload(*, governed: bool = True) -> dict:
    payload = {
        "source": "MOEX",
        "from": DAYS[0].isoformat(),
        "till": DAYS[-1].isoformat(),
        "min_shocks": 1,
        "max_staleness_days": 0,
        "schedule": {"run_time": "19:00", "weekdays_only": True},
    }
    if governed:
        payload.update({
            "expected_dates": [day.isoformat() for day in DAYS],
            "required_underlyings": ["TEST"],
        })
    return payload


def _write_config(tmp_path, payload: dict):
    path = tmp_path / "iv30-rollout.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_readonly_factory_bypasses_schema_initialisation_and_reads(tmp_path, monkeypatch):
    path = tmp_path / "market data.sqlite"
    writer = MarketDataDB(str(path))
    writer.save_time_series(
        "IV30:TEST", "vol", [(DAYS[0].isoformat(), 0.25)]
    )
    writer.close()

    def forbidden_init(_self):
        raise AssertionError("read-only factory must not initialise or migrate schema")

    monkeypatch.setattr(MarketDataDB, "init_schema", forbidden_init)
    reader = MarketDataDB.from_sqlite_readonly(path)
    try:
        assert reader.conn.execute("PRAGMA query_only").fetchone()[0] == 1
        assert reader.get_time_series("IV30:TEST", "vol") == [
            {"dt": DAYS[0].isoformat(), "value": 0.25}
        ]
    finally:
        reader.close()


def test_readonly_factory_does_not_create_a_missing_database(tmp_path):
    missing = tmp_path / "missing.sqlite"

    with pytest.raises(sqlite3.OperationalError):
        MarketDataDB.from_sqlite_readonly(missing)

    assert not missing.exists()


def test_readonly_factory_leaves_no_persistent_sidecars_after_close(tmp_path):
    path = tmp_path / "market.sqlite"
    writer = MarketDataDB(str(path))
    writer.close()
    before = {item.name for item in tmp_path.iterdir()}

    reader = MarketDataDB.from_sqlite_readonly(path)
    reader.close()

    assert {item.name for item in tmp_path.iterdir()} == before


def test_readonly_factory_refuses_active_wal_without_shared_memory(tmp_path):
    path = tmp_path / "market.sqlite"
    writer = MarketDataDB(str(path))
    writer.close()
    wal_path = tmp_path / "market.sqlite-wal"
    wal_path.write_bytes(b"not-an-empty-wal")
    shm_path = tmp_path / "market.sqlite-shm"

    with pytest.raises(RuntimeError, match="without an existing -shm"):
        MarketDataDB.from_sqlite_readonly(path)

    assert not shm_path.exists()


def test_read_snapshot_is_repeatable_across_concurrent_wal_commit(tmp_path):
    path = tmp_path / "market.sqlite"
    writer = MarketDataDB(str(path))
    reader = None
    try:
        assert writer.conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.save_time_series(
            "IV30:TEST", "vol", [(DAYS[0].isoformat(), 0.25)]
        )
        reader = MarketDataDB(str(path))

        with reader.read_snapshot():
            first = reader.get_time_series("IV30:TEST", "vol")
            writer.save_time_series(
                "IV30:TEST", "vol", [(DAYS[0].isoformat(), 0.50)]
            )
            second = reader.get_time_series("IV30:TEST", "vol")

        assert first == second == [
            {"dt": DAYS[0].isoformat(), "value": 0.25}
        ]
        assert reader.get_time_series("IV30:TEST", "vol") == [
            {"dt": DAYS[0].isoformat(), "value": 0.50}
        ]
    finally:
        if reader is not None:
            reader.close()
        writer.close()


def test_readonly_snapshot_blocks_mixed_rollback_journal_bundle(tmp_path):
    path = tmp_path / "market.sqlite"
    seed = MarketDataDB(str(path))
    seed.save_time_series("A", "test", [(DAYS[0].isoformat(), 1.0)])
    seed.save_time_series("B", "test", [(DAYS[0].isoformat(), 1.0)])
    seed.close()
    writer = sqlite3.connect(path, timeout=0)
    reader = MarketDataDB.from_sqlite_readonly(path)
    try:
        with reader.read_snapshot():
            first = reader.get_time_series("A", "test")
            writer.execute(
                "UPDATE time_series SET value=2.0 WHERE factor_id IN ('A', 'B')"
            )
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                writer.commit()
            second = reader.get_time_series("B", "test")

        assert first == second == [
            {"dt": DAYS[0].isoformat(), "value": 1.0}
        ]
    finally:
        writer.rollback()
        writer.close()
        reader.close()


def test_readonly_factory_rejects_mutating_methods(tmp_path):
    path = tmp_path / "market.sqlite"
    _seed_ready_database(path)
    reader = MarketDataDB.from_sqlite_readonly(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader.replace_iv30_for_date(DAYS[0], {"TEST": 0.50})
    finally:
        reader.close()

    verifier = MarketDataDB.from_sqlite_readonly(path)
    try:
        assert verifier.get_time_series("IV30:TEST", "vol")[0]["value"] == 0.25
    finally:
        verifier.close()


@pytest.mark.parametrize(
    ("expected_dates", "underlyings", "production_gate"),
    [
        (None, None, False),
        ([], ["TEST"], False),
        ([DAYS[0].isoformat()], [], False),
        ([DAYS[0].isoformat()], ["TEST"], True),
    ],
)
def test_production_gate_requires_calendar_and_nonempty_fixed_universe(
        expected_dates, underlyings, production_gate):
    payload = {
        "from": DAYS[0].isoformat(),
        "till": DAYS[0].isoformat(),
        "min_shocks": 0,
    }
    if expected_dates is not None:
        payload["expected_dates"] = expected_dates
    if underlyings is not None:
        payload["required_underlyings"] = underlyings

    config = rollout.parse_rollout_config(payload)

    assert config.production_gate is production_gate


def test_non_moex_source_is_diagnostic_only(monkeypatch):
    payload = _config_payload()
    payload["source"] = "manual"
    config = rollout.parse_rollout_config(payload)

    monkeypatch.setattr(rollout, "iv30_readiness_report", lambda *_a, **_kw: {
        "ready": True,
        "blockers": [],
        "factors": {"IV30:TEST": {"ready": True}},
        "expected_snapshot_dates": [day.isoformat() for day in DAYS],
        "stored_snapshot_dates": [day.isoformat() for day in DAYS],
        "missing_snapshot_dates": [],
        "staleness_days": 0,
    })

    result = rollout.assess_iv30_readiness(
        object(), config, as_of=DAYS[-1]
    )

    assert config.source == "MANUAL"
    assert result["readiness_ready"] is True
    assert result["production_gate"] is result["ready"] is False
    assert result["blockers"] == ["production_gate_requires_moex_source"]


def test_invalid_config_is_rejected_before_database_open(tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path, {
        "till": DAYS[-1].isoformat(),
        "required_underlyings": ["TEST"],
    })
    opened = []

    def forbidden_open(_path):
        opened.append(True)
        raise AssertionError("database opened before config validation")

    monkeypatch.setattr(
        cli.MarketDataDB, "from_sqlite_readonly", forbidden_open
    )
    exit_code = cli.main([
        "check", "--config", str(config_path), "--db", str(tmp_path / "missing")
    ])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == cli.EXIT_CONFIG == 64
    assert payload["status"] == "config_error"
    assert opened == []


def test_cli_ready_emits_stable_json_and_exit_zero(tmp_path, capsys):
    db_path = tmp_path / "market.sqlite"
    _seed_ready_database(db_path)
    config_path = _write_config(tmp_path, _config_payload())

    exit_code = cli.main([
        "check",
        "--config", str(config_path),
        "--db", str(db_path),
        "--as-of", DAYS[-1].isoformat(),
    ])
    raw = capsys.readouterr().out
    payload = json.loads(raw)

    assert exit_code == cli.EXIT_READY == 0
    assert set(payload) == {
        "schema_version", "command", "status", "ready", "readiness_ready",
        "production_gate", "diagnostic_only", "source", "window",
        "requirements", "blockers", "metrics", "details",
    }
    assert payload["schema_version"] == rollout.SCHEMA_VERSION
    assert payload["status"] == "ready"
    assert payload["ready"] is payload["readiness_ready"] is True
    assert payload["production_gate"] is True
    assert payload["diagnostic_only"] is False
    assert payload["window"]["as_of"] == DAYS[-1].isoformat()
    assert payload["metrics"]["ready_factors"] == 1
    assert payload["blockers"] == []
    assert "NaN" not in raw and "Infinity" not in raw


def test_cli_rejects_history_mutated_after_validation(tmp_path, capsys):
    db_path = tmp_path / "market.sqlite"
    _seed_ready_database(db_path)
    writer = MarketDataDB(str(db_path))
    try:
        writer.replace_iv30_for_date(DAYS[0], {"TEST": 0.50})
    finally:
        writer.close()
    config_path = _write_config(tmp_path, _config_payload())

    exit_code = cli.main([
        "check",
        "--config", str(config_path),
        "--db", str(db_path),
        "--as-of", DAYS[-1].isoformat(),
    ])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == cli.EXIT_NOT_READY == 2
    assert payload["ready"] is False
    assert "snapshot_validation_not_current" in payload["blockers"]
    assert payload["details"]["snapshot_certification_failures"][
        DAYS[0].isoformat()
    ] == ["validation_snapshot_fingerprint_mismatch"]


def test_manifest_derived_check_is_diagnostic_only_and_exit_two(tmp_path, capsys):
    db_path = tmp_path / "market.sqlite"
    _seed_ready_database(db_path)
    config_path = _write_config(tmp_path, _config_payload(governed=False))

    exit_code = cli.main(
        ["check", "--config", str(config_path), "--db", str(db_path)],
        today=DAYS[-1],
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == cli.EXIT_NOT_READY == 2
    assert payload["readiness_ready"] is True
    assert payload["ready"] is False
    assert payload["diagnostic_only"] is True
    assert payload["blockers"] == [
        "production_gate_requires_explicit_expected_dates",
        "production_gate_requires_nonempty_fixed_universe",
    ]


def test_missing_database_is_runtime_error_and_is_not_created(tmp_path, capsys):
    missing = tmp_path / "missing.sqlite"
    config_path = _write_config(tmp_path, _config_payload())

    exit_code = cli.main([
        "check", "--config", str(config_path), "--db", str(missing)
    ], today=DAYS[-1])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == cli.EXIT_RUNTIME == 70
    assert payload["status"] == "runtime_error"
    assert not missing.exists()


def test_assessment_always_forwards_explicit_as_of(monkeypatch):
    config = rollout.parse_rollout_config(_config_payload())
    captured = {}

    def fake_report(_db, _from, _till, **kwargs):
        captured.update(kwargs)
        return {
            "ready": False,
            "blockers": ["history_not_fresh"],
            "factors": {},
            "expected_snapshot_dates": [],
            "stored_snapshot_dates": [],
            "missing_snapshot_dates": [],
            "staleness_days": None,
        }

    monkeypatch.setattr(rollout, "iv30_readiness_report", fake_report)

    rollout.assess_iv30_readiness(object(), config, as_of=DAYS[-1])

    assert captured["as_of"] == DAYS[-1]
    assert captured["expected_dates"] == DAYS
    assert captured["required_underlyings"] == ("TEST",)
    assert captured["require_validation_reports"] is True


@pytest.mark.parametrize(
    ("now", "last_run", "due", "reason"),
    [
        (datetime(2026, 6, 2, 19, 30), None, True, "due"),
        (datetime(2026, 6, 2, 18, 59), None, False, "before_scheduled_time"),
        (datetime(2026, 6, 6, 19, 30), None, False, "weekend"),
        (
            datetime(2026, 6, 2, 19, 30),
            datetime(2026, 6, 2, 19, 5),
            False,
            "already_run",
        ),
    ],
)
def test_schedule_status_is_a_pure_due_probe(now, last_run, due, reason):
    config = rollout.parse_rollout_config(_config_payload())

    result = rollout.schedule_status(config, now=now, last_run=last_run)

    assert result["due"] is due
    assert result["reason"] == reason
    assert "run_if_due" not in rollout.__dict__


def test_schedule_cli_never_opens_database(tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path, _config_payload())

    def forbidden_open(_path):
        raise AssertionError("schedule-status must not open a database")

    monkeypatch.setattr(
        cli.MarketDataDB, "from_sqlite_readonly", forbidden_open
    )
    exit_code = cli.main([
        "schedule-status",
        "--config", str(config_path),
        "--now", "2026-06-02T19:30:00",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == cli.EXIT_READY == 0
    assert payload["command"] == "schedule-status"
    assert payload["status"] == "due"


def test_nonfinite_observability_payload_fails_with_finite_runtime_json(
        tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path, _config_payload())

    class FakeDb:
        def close(self):
            return None

    monkeypatch.setattr(
        cli.MarketDataDB,
        "from_sqlite_readonly",
        lambda _path: FakeDb(),
    )
    monkeypatch.setattr(
        cli,
        "assess_iv30_readiness",
        lambda _db, _config, *, as_of: {"ready": True, "bad": math.nan},
    )

    exit_code = cli.main([
        "check",
        "--config", str(config_path),
        "--db", str(tmp_path / "unused.sqlite"),
        "--as-of", DAYS[-1].isoformat(),
    ])
    raw = capsys.readouterr().out
    payload = json.loads(raw)

    assert exit_code == cli.EXIT_RUNTIME == 70
    assert payload["status"] == "runtime_error"
    assert "non-finite number" in payload["error"]["message"]
    assert "NaN" not in raw and "Infinity" not in raw


@pytest.mark.parametrize(
    "patch",
    [
        {"schedule": {"run_time": "24:00"}},
        {"min_shocks": True},
        {"required_underlyings": [""]},
        {"unexpected": "field"},
    ],
)
def test_config_validation_rejects_unsafe_or_ambiguous_values(patch):
    payload = _config_payload()
    payload.update(patch)

    with pytest.raises(rollout.RolloutConfigError):
        rollout.parse_rollout_config(payload)
