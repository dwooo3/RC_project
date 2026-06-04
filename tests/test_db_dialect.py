"""Phase E — SQLite/Postgres dialect portability of the market-data DB."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infra.db.market_data_db import MarketDataDB, _schema_statements, _TABLES


def test_schema_serial_pk_differs_by_dialect():
    sqlite_sql = "\n".join(_schema_statements("sqlite"))
    pg_sql = "\n".join(_schema_statements("postgres"))
    assert "AUTOINCREMENT" in sqlite_sql and "BIGSERIAL" not in sqlite_sql
    assert "BIGSERIAL PRIMARY KEY" in pg_sql and "AUTOINCREMENT" not in pg_sql
    # all other tables identical across dialects (only ingest_log PK differs)
    assert sqlite_sql.count("CREATE TABLE") == pg_sql.count("CREATE TABLE")


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


def test_external_connection_injection_uses_given_dialect():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # inject an existing connection; dialect stays sqlite here, proving the
    # connection-injection path (used to pass a psycopg connection in prod).
    db = MarketDataDB(conn=conn, dialect="sqlite")
    db.save_fx_rate("s1", "USD/RUB", 74.0)
    assert db.get_fx_rates("s1") == {"USD/RUB": 74.0}
