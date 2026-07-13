"""Opt-in real PostgreSQL transaction contract for governed IV30 storage.

The default suite skips this module's test.  CI/operations can supply an
isolated disposable database through ``RISKCALC_TEST_POSTGRES_DSN``; the test
then creates and drops its own uniquely named schema.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta

import pytest

from infra.db.market_data_db import MarketDataDB


VAL = date(2026, 6, 10)


def _points(*, forward=100.0, include_middle=False) -> list[dict]:
    strikes = (90.0, 100.0, 110.0) if include_middle else (90.0, 110.0)
    return [{
        "underlying": "TEST",
        "expiry": (VAL + timedelta(days=30)).isoformat(),
        "strike": strike,
        "iv": 0.25,
        "forward": forward,
        "tenor_days": 30,
        "open_interest": 100.0,
        "observation_date": VAL.isoformat(),
        "source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
        "method": "black76_settlement",
        "observation_status": "verified",
        "option_price_date": VAL.isoformat(),
        "forward_date": VAL.isoformat(),
        "option_price_source": "MOEX_FORTS_OPTION_SETTLEMENT",
        "forward_source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
        "option_price_basis": "settlement",
        "forward_basis": "underlying_settlement",
    } for strike in strikes]


def test_real_postgres_raw_provenance_and_iv30_rollback_contract():
    dsn = os.getenv("RISKCALC_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set RISKCALC_TEST_POSTGRES_DSN for the opt-in integration test")
    psycopg = pytest.importorskip("psycopg")
    sql = pytest.importorskip("psycopg.sql")
    schema = f"riskcalc_iv30_{uuid.uuid4().hex}"

    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    db = None
    try:
        db = MarketDataDB.from_postgres_dsn(
            dsn, options=f"-c search_path={schema},public"
        )
        snapshot_id = f"moex-{VAL.isoformat()}"
        db.save_snapshot_meta(
            snapshot_id=snapshot_id,
            valuation_date=VAL,
            source="MOEX",
            quality="OK",
            fetch_ts=datetime(2026, 6, 10, 19, 30),
        )
        db.replace_vol_surface(snapshot_id, _points())
        assert len(db.get_vol_points(snapshot_id)) == 2
        assert len(db.get_vol_point_observations(snapshot_id)) == 2

        # Fail in the second table after the raw grid has been inserted.  The
        # complete raw+provenance replacement must roll back to the old pair.
        db._exec(  # noqa: SLF001 - integration contract fault injection
            "ALTER TABLE vol_point_observations ADD CONSTRAINT "
            "ck_iv30_test_positive_forward CHECK (forward > 0)"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            db.replace_vol_surface(
                snapshot_id, _points(forward=-1.0, include_middle=True)
            )
        assert len(db.get_vol_points(snapshot_id)) == 2
        assert len(db.get_vol_point_observations(snapshot_id)) == 2
        assert all(
            row["forward"] == 100.0
            for row in db.get_vol_point_observations(snapshot_id)
        )

        # Likewise, a bad row after the same-date delete must not revoke or
        # partially replace the previously published canonical representative.
        db.replace_iv30_for_date(VAL, {"TEST": 0.25})
        db._exec(  # noqa: SLF001 - integration contract fault injection
            "ALTER TABLE time_series ADD CONSTRAINT "
            "ck_iv30_test_value CHECK (kind <> 'vol' OR value < 1.0)"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            db.replace_iv30_for_date(VAL, {"A": 0.30, "Z_BAD": 2.0})
        assert db.get_time_series("IV30:TEST", "vol") == [
            {"dt": VAL.isoformat(), "value": 0.25}
        ]
        assert db.get_time_series("IV30:A", "vol") == []
        assert db.get_time_series("IV30:Z_BAD", "vol") == []

        # The production multi-table read contract must really be repeatable
        # and read-only on psycopg's implicit transaction, not merely express
        # those words in a nested BEGIN that PostgreSQL ignores.
        db.save_time_series("READ_SNAPSHOT", "test", [(VAL, 1.0)])
        with psycopg.connect(
            dsn,
            options=f"-c search_path={schema},public",
        ) as writer:
            with db.read_snapshot():
                isolation = db._query_one(  # noqa: SLF001 - contract probe
                    "SHOW transaction_isolation"
                )
                read_only = db._query_one(  # noqa: SLF001 - contract probe
                    "SHOW transaction_read_only"
                )
                first = db.get_time_series("READ_SNAPSHOT", "test")
                writer.execute(
                    "UPDATE time_series SET value=2.0 "
                    "WHERE factor_id='READ_SNAPSHOT' AND kind='test'"
                )
                writer.commit()
                second = db.get_time_series("READ_SNAPSHOT", "test")

                assert isolation["transaction_isolation"] == "repeatable read"
                assert read_only["transaction_read_only"] == "on"
                assert first == second == [{"dt": VAL.isoformat(), "value": 1.0}]

        assert db.get_time_series("READ_SNAPSHOT", "test") == [
            {"dt": VAL.isoformat(), "value": 2.0}
        ]
    finally:
        if db is not None:
            db.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
