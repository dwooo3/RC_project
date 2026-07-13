"""Phase E — SQLite/Postgres dialect portability of the market-data DB."""
import os
import sys
import threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infra.db.market_data_db import (
    MarketDataDB,
    _SNAPSHOT_KEYED,
    _TABLES,
    _postgres_additive_migration_statements,
    _schema_statements,
)


def test_schema_serial_pk_differs_by_dialect():
    sqlite_sql = "\n".join(_schema_statements("sqlite"))
    pg_sql = "\n".join(_schema_statements("postgres"))
    assert "AUTOINCREMENT" in sqlite_sql and "BIGSERIAL" not in sqlite_sql
    assert "BIGSERIAL PRIMARY KEY" in pg_sql and "AUTOINCREMENT" not in pg_sql
    # all other tables identical across dialects (only ingest_log PK differs)
    assert sqlite_sql.count("CREATE TABLE") == pg_sql.count("CREATE TABLE")


def test_fresh_postgres_schema_contains_every_snapshot_key_write_column():
    statements = _schema_statements("postgres")
    keyed_tables = ("market_data_snapshots", *_SNAPSHOT_KEYED, "option_quotes")
    for table in keyed_tables:
        ddl = next(sql for sql in statements
                   if f"CREATE TABLE IF NOT EXISTS {table} " in sql)
        assert "snapshot_key" in ddl, table
        if table == "market_data_snapshots":
            assert "snapshot_key INTEGER UNIQUE" in ddl

    observations = next(
        sql for sql in statements
        if "CREATE TABLE IF NOT EXISTS vol_point_observations " in sql
    )
    for column in (
        "option_price_date", "forward_date", "option_price_source",
        "forward_source", "option_price_basis", "forward_basis",
    ):
        assert column in observations


def test_existing_postgres_schema_has_idempotent_additive_upgrade_contract():
    sql = "\n".join(_postgres_additive_migration_statements())
    keyed_tables = ("market_data_snapshots", *_SNAPSHOT_KEYED, "option_quotes")
    for table in keyed_tables:
        assert (
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS snapshot_key INTEGER"
            in sql
        ), table
        assert f"ON {table}(snapshot_key)" in sql, table
    for column in (
        "option_price_date", "forward_date", "option_price_source",
        "forward_source", "option_price_basis", "forward_basis",
    ):
        assert (
            "ALTER TABLE vol_point_observations "
            f"ADD COLUMN IF NOT EXISTS {column} TEXT"
        ) in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "UPDATE market_data_snapshots AS target" in sql
    assert "UPDATE vol_point_observations AS target" in sql
    assert "?" not in sql and "PRAGMA" not in sql and "INSERT OR IGNORE" not in sql


def test_sqlite_upsert_syntax():
    db = MarketDataDB(":memory:")
    cols, conflict = _TABLES["fx_rates"]
    sql = db._upsert_sql("fx_rates", cols, conflict)
    assert sql.startswith("INSERT OR REPLACE INTO fx_rates")
    assert "?" in sql and "%s" not in sql


def test_postgres_upsert_syntax():
    db = MarketDataDB(":memory:")
    db.dialect, db.ph = "postgres", "%s"  # exercise the PG branch of the SQL builder
    cols, conflict = _TABLES["fx_rates"]
    sql = db._upsert_sql("fx_rates", cols, conflict)
    assert sql.startswith("INSERT INTO fx_rates")
    assert "ON CONFLICT (snapshot_id,pair) DO UPDATE SET" in sql
    assert "rate=EXCLUDED.rate" in sql
    assert "%s" in sql and "?" not in sql


def test_postgres_upsert_do_nothing_when_only_keys():
    db = MarketDataDB(":memory:")
    db.dialect, db.ph = "postgres", "%s"
    # a hypothetical all-key table => DO NOTHING (no non-key columns to update)
    sql = db._upsert_sql("t", ["a", "b"], ["a", "b"])
    assert "DO NOTHING" in sql


def test_reference_insert_if_absent_is_native_in_each_dialect():
    db = MarketDataDB(":memory:")
    sqlite_sql = db._insert_ignore_sql(  # noqa: SLF001 - SQL contract
        "ref_currencies", ["code", "name"], ["code"]
    )
    assert sqlite_sql.startswith("INSERT OR IGNORE INTO ref_currencies")
    assert "?" in sqlite_sql and "%s" not in sqlite_sql

    db.dialect, db.ph = "postgres", "%s"
    postgres_sql = db._insert_ignore_sql(  # noqa: SLF001 - SQL contract
        "ref_currencies", ["code", "name"], ["code"]
    )
    assert postgres_sql.startswith("INSERT INTO ref_currencies")
    assert "ON CONFLICT (code) DO NOTHING" in postgres_sql
    assert "%s" in postgres_sql
    assert "INSERT OR IGNORE" not in postgres_sql and "?" not in postgres_sql


def test_external_connection_injection_uses_given_dialect():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # inject an existing connection; dialect stays sqlite here, proving the
    # connection-injection path (used to pass a psycopg connection in prod).
    db = MarketDataDB(conn=conn, dialect="sqlite")
    db.save_fx_rate("s1", "USD/RUB", 74.0)
    assert db.get_fx_rates("s1") == {"USD/RUB": 74.0}


def test_postgres_migration_runs_reference_and_version_backfills():
    db = object.__new__(MarketDataDB)
    db.dialect = "postgres"
    calls = []
    db._migrate_postgres_additive = lambda: calls.append("additive")
    db._migrate_instrument_versions = lambda: calls.append("instrument_versions")
    db._migrate_schedule_versions = lambda: calls.append("schedule_versions")
    db._migrate_refdata = lambda: calls.append("refdata")

    db._migrate()

    assert calls == [
        "additive", "instrument_versions", "schedule_versions", "refdata",
    ]


def test_postgres_raw_table_browser_uses_backend_physical_row_identity():
    db = object.__new__(MarketDataDB)
    db.dialect = "postgres"
    captured = []
    db._query = lambda sql: captured.append(sql) or []

    db.table_rows("ingest_log", newest_first=True)

    assert "ORDER BY ctid DESC" in captured[0]
    assert "rowid" not in captured[0]


def test_postgres_read_snapshot_sets_transaction_characteristics_once():
    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=()):
            self.calls.append((sql, params))

    class Connection:
        def __init__(self):
            self.cur = Cursor()
            self.rollbacks = 0

        def cursor(self):
            return self.cur

        def rollback(self):
            self.rollbacks += 1

    conn = Connection()
    db = object.__new__(MarketDataDB)
    db.conn = conn
    db.dialect = "postgres"
    db.ph = "%s"
    db._lock = threading.RLock()
    db._read_snapshot_depth = 0

    with db.read_snapshot():
        with db.read_snapshot():
            assert db._read_snapshot_depth == 2

    assert conn.cur.calls == [(
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        (),
    )]
    assert conn.rollbacks == 1
