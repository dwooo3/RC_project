"""Additive snapshot_key surrogate migration (recommendations §6/§34).

The integer snapshot_key is added alongside the text snapshot_id on the manifest
and the snapshot-bound fact tables: backfilled from snapshot_id, populated at
write time, and idempotent — without dropping anything or changing existing
getters.
"""
import datetime as dt

import pytest

from infra.db.market_data_db import MarketDataDB, _SNAPSHOT_KEYED


@pytest.fixture
def db():
    return MarketDataDB(":memory:")


def _snap(db, sid, day):
    db.save_snapshot_meta(snapshot_id=sid, valuation_date=dt.date(2026, 1, day),
                          source="MOEX", quality="OK", fetch_ts=dt.datetime(2026, 1, day, 10))


def test_columns_added_on_fresh_db(db):
    assert db._has_column("market_data_snapshots", "snapshot_key")
    for t in _SNAPSHOT_KEYED:
        assert db._has_column(t, "snapshot_key"), t
    assert db._has_column("option_quotes", "snapshot_key")


def test_snapshot_keys_are_assigned_and_distinct(db):
    _snap(db, "moex-2026-01-01", 1)
    _snap(db, "moex-2026-01-02", 2)
    k1 = db.snapshot_key_for("moex-2026-01-01")
    k2 = db.snapshot_key_for("moex-2026-01-02")
    assert k1 and k2 and k1 != k2


def test_resave_keeps_key_stable(db):
    _snap(db, "moex-2026-01-01", 1)
    k = db.snapshot_key_for("moex-2026-01-01")
    _snap(db, "moex-2026-01-01", 1)            # re-save (INSERT OR REPLACE)
    assert db.snapshot_key_for("moex-2026-01-01") == k


def test_fact_rows_get_snapshot_key_at_write_time(db):
    _snap(db, "moex-2026-01-02", 2)
    k = db.snapshot_key_for("moex-2026-01-02")
    db.save_curve("moex-2026-01-02", "GCURVE", method="m", nss_params=None,
                  as_of="2026-01-02", points=[(1.0, 0.1, 0.9)])
    row = db._query_one("SELECT snapshot_key FROM curve_points")
    assert row["snapshot_key"] == k


def test_backfill_fills_null_keys(db):
    _snap(db, "moex-2026-01-03", 3)
    key = db.snapshot_key_for("moex-2026-01-03")
    # insert a fact row WITHOUT a snapshot_key (simulate pre-migration data)
    db._exec("INSERT INTO fx_rates (snapshot_id, pair, rate) VALUES (?,?,?)",
             ("moex-2026-01-03", "USD/RUB", 90.0))
    assert db._query_one("SELECT snapshot_key FROM fx_rates")["snapshot_key"] is None
    db._migrate()                               # backfill
    assert db._query_one("SELECT snapshot_key FROM fx_rates")["snapshot_key"] == key


def test_migrate_is_idempotent(db):
    _snap(db, "moex-2026-01-01", 1)
    k = db.snapshot_key_for("moex-2026-01-01")
    db._migrate()
    db._migrate()
    assert db.snapshot_key_for("moex-2026-01-01") == k


def test_snapshot_id_still_present(db):
    """The migration is additive — the text key and existing getters are intact."""
    _snap(db, "moex-2026-01-01", 1)
    meta = db.get_snapshot_meta("moex-2026-01-01")
    assert meta["snapshot_id"] == "moex-2026-01-01"
    assert meta["snapshot_key"] is not None
