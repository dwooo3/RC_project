"""
Local market-data database per MOEX_MARKET_DATA_INTEGRATION_PROMPT.md §3.

Schema maps onto domain.MarketDataSnapshot / MarketDataStore for reproducibility
(snapshot_id + valuation_date + ISS request URLs + fetch timestamp).

Phase E: the same schema targets SQLite (default) and PostgreSQL. The dialect
abstraction below switches placeholders (``?`` vs ``%s``), upsert syntax
(``INSERT OR REPLACE`` vs ``ON CONFLICT ... DO UPDATE``) and the autoincrement
PK (``AUTOINCREMENT`` vs ``BIGSERIAL``). Pass a psycopg connection +
``dialect='postgres'`` to use Postgres; SQLite behaviour is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime
from typing import Any

# Reference fields that define an instrument *version* (excludes daily-changing
# quote fields: last / change_pct / day_json / as_of / is_active) so a new version
# is cut only when the descriptive reference actually changes.
_REF_VERSION_FIELDS = ("category", "market", "board", "isin", "issuer_ru", "name_ru",
                       "sec_type", "list_level", "currency", "asset_code",
                       "last_trade_date", "ref_json")


def _iso(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


# table -> (columns, conflict-key columns) for upserts
_TABLES = {
    "instruments": (
        ["secid", "isin", "board", "type", "currency", "facevalue", "coupon_percent",
         "coupon_period", "next_coupon", "mat_date", "offer_date", "lot_size",
         "list_level", "issuer", "sector", "static_json"], ["secid"]),
    "market_data_snapshots": (
        ["snapshot_id", "valuation_date", "source", "quality", "created_at",
         "fetch_ts", "iss_request_urls", "metadata", "snapshot_key"], ["snapshot_id"]),
    "yield_curves": (["snapshot_id", "curve_id", "method", "nss_params", "as_of", "snapshot_key"],
                     ["snapshot_id", "curve_id"]),
    "curve_points": (["snapshot_id", "curve_id", "tenor", "zero_rate", "discount_factor", "snapshot_key"],
                     ["snapshot_id", "curve_id", "tenor"]),
    "fx_rates": (["snapshot_id", "pair", "rate", "source", "trade_time", "snapshot_key"],
                 ["snapshot_id", "pair"]),
    "bond_quotes": (["snapshot_id", "secid", "clean_price", "dirty_price", "wap_price",
                     "accruedint", "ytm", "volume", "board", "snapshot_key"], ["snapshot_id", "secid"]),
    "equity_quotes": (["snapshot_id", "secid", "last", "prevprice", "board", "volume", "snapshot_key"],
                      ["snapshot_id", "secid"]),
    "index_values": (["snapshot_id", "indexid", "value", "trade_date", "snapshot_key"],
                     ["snapshot_id", "indexid"]),
    "time_series": (["factor_id", "dt", "value", "kind"], ["factor_id", "dt", "kind"]),
    "vol_points": (["snapshot_id", "underlying", "expiry", "strike", "iv", "snapshot_key"],
                   ["snapshot_id", "underlying", "expiry", "strike"]),
    "bond_coupons": (["secid", "coupon_date", "value", "value_prc"],
                     ["secid", "coupon_date"]),
    "bond_amortizations": (["secid", "amort_date", "value", "face_remaining"],
                           ["secid", "amort_date"]),
    "bond_offers": (["secid", "offer_date", "price", "offer_type"],
                    ["secid", "offer_date"]),
    "commodity_quotes": (["snapshot_id", "asset", "secid", "expiry", "settle",
                          "open_interest", "volume", "snapshot_key"],
                         ["snapshot_id", "secid"]),
    "dividends": (["secid", "registry_date", "value", "currency"],
                  ["secid", "registry_date"]),
    # Continuously-accumulated store (no snapshots): one row per security per day.
    "price_history": (
        ["secid", "market", "dt", "open", "high", "low", "close",
         "volume", "value", "yield", "numtrades"],
        ["secid", "market", "dt"]),
    # Option chain quotes (current snapshot, one row per option contract).
    "option_quotes": (
        ["secid", "asset_code", "expiry", "strike", "opt_type", "last", "settle",
         "oi", "volume", "central_strike", "underlying", "snapshot_key"],
        ["secid"]),
    # Full per-instrument reference (latest ISS description + day stats).
    "instrument_ref": (
        ["secid", "category", "market", "board", "isin", "issuer_ru", "name_ru",
         "sec_type", "list_level", "currency", "asset_code", "last_trade_date",
         "is_active", "last", "change_pct", "as_of", "day_json", "ref_json"],
        ["secid"]),
}


# Snapshot-bound fact tables that carry a lightweight integer snapshot_key
# alongside the text snapshot_id (additive surrogate; see _migrate).
_SNAPSHOT_KEYED = ("yield_curves", "curve_points", "fx_rates", "bond_quotes",
                   "equity_quotes", "index_values", "vol_points", "commodity_quotes")


def _schema_statements(dialect: str) -> list[str]:
    serial_pk = "BIGSERIAL PRIMARY KEY" if dialect == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return [
        """CREATE TABLE IF NOT EXISTS instruments (
            secid TEXT PRIMARY KEY, isin TEXT, board TEXT, type TEXT, currency TEXT,
            facevalue REAL, coupon_percent REAL, coupon_period INTEGER, next_coupon TEXT,
            mat_date TEXT, offer_date TEXT, lot_size REAL, list_level INTEGER,
            issuer TEXT, sector TEXT, static_json TEXT)""",
        """CREATE TABLE IF NOT EXISTS market_data_snapshots (
            snapshot_id TEXT PRIMARY KEY, valuation_date TEXT NOT NULL, source TEXT NOT NULL,
            quality TEXT NOT NULL, created_at TEXT NOT NULL, fetch_ts TEXT NOT NULL,
            iss_request_urls TEXT, metadata TEXT)""",
        """CREATE TABLE IF NOT EXISTS yield_curves (
            snapshot_id TEXT NOT NULL, curve_id TEXT NOT NULL, method TEXT, nss_params TEXT,
            as_of TEXT, PRIMARY KEY (snapshot_id, curve_id))""",
        """CREATE TABLE IF NOT EXISTS curve_points (
            snapshot_id TEXT NOT NULL, curve_id TEXT NOT NULL, tenor REAL NOT NULL,
            zero_rate REAL NOT NULL, discount_factor REAL,
            PRIMARY KEY (snapshot_id, curve_id, tenor))""",
        """CREATE TABLE IF NOT EXISTS fx_rates (
            snapshot_id TEXT NOT NULL, pair TEXT NOT NULL, rate REAL NOT NULL, source TEXT,
            trade_time TEXT, PRIMARY KEY (snapshot_id, pair))""",
        """CREATE TABLE IF NOT EXISTS bond_quotes (
            snapshot_id TEXT NOT NULL, secid TEXT NOT NULL, clean_price REAL, dirty_price REAL,
            wap_price REAL, accruedint REAL, ytm REAL, volume REAL, board TEXT,
            PRIMARY KEY (snapshot_id, secid))""",
        """CREATE TABLE IF NOT EXISTS equity_quotes (
            snapshot_id TEXT NOT NULL, secid TEXT NOT NULL, last REAL, prevprice REAL,
            board TEXT, volume REAL, PRIMARY KEY (snapshot_id, secid))""",
        # DEPRECATED: index levels now live in `time_series` (kind='index'). Kept
        # for backward compatibility with old snapshots; not written by current
        # ingest and excluded from data-health completeness. Drop in a migration.
        """CREATE TABLE IF NOT EXISTS index_values (
            snapshot_id TEXT NOT NULL, indexid TEXT NOT NULL, value REAL, trade_date TEXT,
            PRIMARY KEY (snapshot_id, indexid))""",
        """CREATE TABLE IF NOT EXISTS time_series (
            factor_id TEXT NOT NULL, dt TEXT NOT NULL, value REAL, kind TEXT NOT NULL,
            PRIMARY KEY (factor_id, dt, kind))""",
        "CREATE INDEX IF NOT EXISTS idx_time_series_factor ON time_series (factor_id, dt)",
        """CREATE TABLE IF NOT EXISTS vol_points (
            snapshot_id TEXT NOT NULL, underlying TEXT NOT NULL, expiry TEXT NOT NULL,
            strike REAL NOT NULL, iv REAL,
            PRIMARY KEY (snapshot_id, underlying, expiry, strike))""",
        """CREATE TABLE IF NOT EXISTS bond_coupons (
            secid TEXT NOT NULL, coupon_date TEXT NOT NULL, value REAL, value_prc REAL,
            PRIMARY KEY (secid, coupon_date))""",
        """CREATE TABLE IF NOT EXISTS bond_amortizations (
            secid TEXT NOT NULL, amort_date TEXT NOT NULL, value REAL, face_remaining REAL,
            PRIMARY KEY (secid, amort_date))""",
        """CREATE TABLE IF NOT EXISTS bond_offers (
            secid TEXT NOT NULL, offer_date TEXT NOT NULL, price REAL, offer_type TEXT,
            PRIMARY KEY (secid, offer_date))""",
        """CREATE TABLE IF NOT EXISTS commodity_quotes (
            snapshot_id TEXT NOT NULL, asset TEXT NOT NULL, secid TEXT NOT NULL,
            expiry TEXT, settle REAL, open_interest REAL, volume REAL,
            PRIMARY KEY (snapshot_id, secid))""",
        """CREATE TABLE IF NOT EXISTS dividends (
            secid TEXT NOT NULL, registry_date TEXT NOT NULL, value REAL, currency TEXT,
            PRIMARY KEY (secid, registry_date))""",
        """CREATE TABLE IF NOT EXISTS price_history (
            secid TEXT NOT NULL, market TEXT NOT NULL, dt TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL, value REAL,
            yield REAL, numtrades REAL, PRIMARY KEY (secid, market, dt))""",
        "CREATE INDEX IF NOT EXISTS idx_price_history_secid ON price_history (secid, dt)",
        """CREATE TABLE IF NOT EXISTS instrument_ref (
            secid TEXT PRIMARY KEY, category TEXT, market TEXT, board TEXT, isin TEXT,
            issuer_ru TEXT, name_ru TEXT, sec_type TEXT, list_level INTEGER, currency TEXT,
            asset_code TEXT, last_trade_date TEXT, is_active INTEGER, last REAL,
            change_pct REAL, as_of TEXT, day_json TEXT, ref_json TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_instrument_ref_cat ON instrument_ref (category)",
        """CREATE TABLE IF NOT EXISTS option_quotes (
            secid TEXT PRIMARY KEY, asset_code TEXT, expiry TEXT, strike REAL,
            opt_type TEXT, last REAL, settle REAL, oi REAL, volume REAL,
            central_strike REAL, underlying TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_option_quotes_asset ON option_quotes (asset_code, expiry, strike)",
        f"""CREATE TABLE IF NOT EXISTS ingest_log (
            run_id {serial_pk}, endpoint TEXT, status TEXT, rows INTEGER,
            started_at TEXT, finished_at TEXT, error TEXT)""",
        # Versioned instrument reference (recommendations §7.2/§34): a new row is
        # cut only when the descriptive reference changes; the open version has
        # valid_to=NULL. instrument_ref stays the live "latest" view.
        """CREATE TABLE IF NOT EXISTS instrument_versions (
            secid TEXT NOT NULL, version INTEGER NOT NULL, valid_from TEXT NOT NULL,
            valid_to TEXT, source TEXT, payload_hash TEXT NOT NULL, fields_json TEXT,
            created_at TEXT, PRIMARY KEY (secid, version))""",
        "CREATE INDEX IF NOT EXISTS idx_instrument_versions_open ON instrument_versions (secid, valid_to)",
        # Versioned bond schedule (§7.3): a new version when the coupon /
        # amortization / offer schedule changes. bond_coupons/_amortizations/_offers
        # stay the live "latest" rows.
        """CREATE TABLE IF NOT EXISTS bond_schedule_versions (
            secid TEXT NOT NULL, version INTEGER NOT NULL, valid_from TEXT NOT NULL,
            valid_to TEXT, payload_hash TEXT NOT NULL, n_coupons INTEGER, n_amort INTEGER,
            n_offers INTEGER, schedule_json TEXT, created_at TEXT,
            PRIMARY KEY (secid, version))""",
        "CREATE INDEX IF NOT EXISTS idx_bond_schedule_versions_open ON bond_schedule_versions (secid, valid_to)",
        # Unified reference look-ups (§8): single source of truth for the codes
        # used across the store. Seeded from existing data + kept current on ingest.
        "CREATE TABLE IF NOT EXISTS ref_currencies (code TEXT PRIMARY KEY, name TEXT)",
        "CREATE TABLE IF NOT EXISTS ref_boards (board TEXT PRIMARY KEY, market TEXT)",
        "CREATE TABLE IF NOT EXISTS ref_sources (code TEXT PRIMARY KEY, name TEXT)",
    ]


# Display names for the currency codes seen in the store (unknown → code).
_CURRENCY_NAMES = {
    "SUR": "Российский рубль", "RUB": "Российский рубль", "USD": "Доллар США",
    "EUR": "Евро", "CNY": "Китайский юань", "GBP": "Фунт стерлингов",
    "CHF": "Швейцарский франк", "JPY": "Японская иена", "HKD": "Гонконгский доллар",
    "TRY": "Турецкая лира", "KZT": "Казахстанский тенге", "BYN": "Белорусский рубль",
    "AED": "Дирхам ОАЭ", "GLD": "Золото", "SLV": "Серебро",
}
_SOURCE_NAMES = {"MOEX": "Московская биржа", "CBR": "Банк России"}


class MarketDataDB:
    """Dialect-aware persistence (SQLite default, PostgreSQL-compatible)."""

    def __init__(self, path: str = ":memory:", *, conn=None, dialect: str = "sqlite"):
        if conn is not None:
            self.conn = conn
            self.dialect = dialect
        else:
            # check_same_thread=False: the API bridge serves requests from a
            # uvicorn thread pool and rebinds this connection after a background
            # ingest, so the (read-mostly) connection must be usable cross-thread.
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.dialect = "sqlite"
        self.ph = "%s" if self.dialect == "postgres" else "?"
        self.init_schema()

    def init_schema(self) -> None:
        for stmt in _schema_statements(self.dialect):
            self._exec(stmt)
        self._migrate()

    # -- additive migrations (idempotent, non-destructive) ----------------
    def _has_column(self, table: str, col: str) -> bool:
        return any(c["name"] == col for c in self.table_columns(table))

    def _add_column(self, table: str, col: str, decl: str) -> None:
        if not self._has_column(table, col):
            self._exec(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    def _migrate(self) -> None:
        """Lightweight integer snapshot_key surrogate (recommendations §6/§34).

        Adds snapshot_key to market_data_snapshots and the snapshot-bound fact
        tables, backfilled from snapshot_id. Fully additive — snapshot_id stays,
        every existing getter is unchanged — and idempotent (only NULLs filled),
        so it is safe to run on every connect.
        """
        if self.dialect != "sqlite":
            return
        self._migrate_snapshot_key()
        self._migrate_instrument_versions()
        self._migrate_schedule_versions()
        self._migrate_refdata()

    def _migrate_snapshot_key(self) -> None:
        # 1. surrogate key on the snapshot manifest
        self._add_column("market_data_snapshots", "snapshot_key", "INTEGER")
        pending = self._query(
            "SELECT snapshot_id FROM market_data_snapshots WHERE snapshot_key IS NULL "
            "ORDER BY valuation_date, snapshot_id")
        if pending:
            base = (self._query_one(
                "SELECT COALESCE(MAX(snapshot_key), 0) AS m FROM market_data_snapshots") or {}).get("m", 0)
            for i, r in enumerate(pending, start=1):
                self._exec("UPDATE market_data_snapshots SET snapshot_key=? WHERE snapshot_id=?",
                           (base + i, r["snapshot_id"]))
        self._exec("CREATE UNIQUE INDEX IF NOT EXISTS idx_snap_key "
                   "ON market_data_snapshots(snapshot_key)")
        # 2. snapshot_key on the snapshot-bound fact tables (join-backfilled)
        for t in _SNAPSHOT_KEYED:
            self._add_column(t, "snapshot_key", "INTEGER")
            self._exec(f"UPDATE {t} SET snapshot_key=(SELECT s.snapshot_key "
                       f"FROM market_data_snapshots s WHERE s.snapshot_id={t}.snapshot_id) "
                       f"WHERE snapshot_key IS NULL")
            self._exec(f"CREATE INDEX IF NOT EXISTS idx_{t}_snapkey ON {t}(snapshot_key)")
        # 3. option_quotes is the *current* chain → stamp the latest snapshot_key
        self._add_column("option_quotes", "snapshot_key", "INTEGER")
        latest = self._latest_snapshot_key()
        if latest is not None:
            self._exec("UPDATE option_quotes SET snapshot_key=? WHERE snapshot_key IS NULL", (latest,))
        self._exec("CREATE INDEX IF NOT EXISTS idx_option_quotes_snapkey ON option_quotes(snapshot_key)")

    def _migrate_instrument_versions(self) -> None:
        """Seed version 1 for every instrument that has no reference history yet."""
        refs = self._query("SELECT * FROM instrument_ref WHERE secid NOT IN "
                           "(SELECT DISTINCT secid FROM instrument_versions)")
        for r in refs:
            self._record_instrument_version(r)

    def _migrate_refdata(self) -> None:
        """Seed the unified reference look-ups from existing data (idempotent)."""
        for r in self._query("SELECT DISTINCT currency FROM instrument_ref WHERE currency IS NOT NULL"):
            self._ref_currency(r["currency"])
        for r in self._query("SELECT DISTINCT board, market FROM instrument_ref WHERE board IS NOT NULL"):
            self._ref_board(r["board"], r.get("market"))
        for code, name in _SOURCE_NAMES.items():
            self._exec(f"INSERT OR IGNORE INTO ref_sources (code, name) VALUES ({self._placeholders(2)})",
                       (code, name))

    def _ref_currency(self, code) -> None:
        if code:
            self._exec(f"INSERT OR IGNORE INTO ref_currencies (code, name) VALUES ({self._placeholders(2)})",
                       (code, _CURRENCY_NAMES.get(str(code), str(code))))

    def _ref_board(self, board, market=None) -> None:
        if board:
            self._exec(f"INSERT OR IGNORE INTO ref_boards (board, market) VALUES ({self._placeholders(2)})",
                       (board, market))

    def list_ref_currencies(self) -> list[dict]:
        return self._query("SELECT code, name FROM ref_currencies ORDER BY code")

    def list_ref_boards(self) -> list[dict]:
        return self._query("SELECT board, market FROM ref_boards ORDER BY board")

    def list_ref_sources(self) -> list[dict]:
        return self._query("SELECT code, name FROM ref_sources ORDER BY code")

    def _migrate_schedule_versions(self) -> None:
        """Seed version 1 for every bond that has a schedule but no version yet."""
        rows = self._query(
            "SELECT DISTINCT secid FROM ("
            "  SELECT secid FROM bond_coupons UNION"
            "  SELECT secid FROM bond_amortizations UNION"
            "  SELECT secid FROM bond_offers) "
            "WHERE secid NOT IN (SELECT DISTINCT secid FROM bond_schedule_versions)")
        for r in rows:
            self._record_schedule_version(r["secid"])

    def _resolve_snapshot_key(self, snapshot_id) -> int:
        row = self._query_one(
            f"SELECT snapshot_key FROM market_data_snapshots WHERE snapshot_id={self.ph}", (snapshot_id,))
        if row and row.get("snapshot_key") is not None:
            return int(row["snapshot_key"])
        return (self._latest_snapshot_key() or 0) + 1          # new snapshot → next key

    def _latest_snapshot_key(self):
        row = self._query_one("SELECT MAX(snapshot_key) AS k FROM market_data_snapshots")
        return int(row["k"]) if row and row.get("k") is not None else None

    def _with_snapshot_key(self, table: str, row: dict) -> dict:
        """Stamp snapshot_key from snapshot_id (snapshot-bound tables) or the latest
        snapshot (option_quotes = current chain) so new writes stay consistent."""
        if table in _SNAPSHOT_KEYED and row.get("snapshot_id"):
            return {**row, "snapshot_key": self._resolve_snapshot_key(row["snapshot_id"])}
        if table == "option_quotes":
            return {**row, "snapshot_key": self._latest_snapshot_key()}
        return row

    def snapshot_key_for(self, snapshot_id) -> int | None:
        row = self._query_one(
            f"SELECT snapshot_key FROM market_data_snapshots WHERE snapshot_id={self.ph}", (snapshot_id,))
        return int(row["snapshot_key"]) if row and row.get("snapshot_key") is not None else None

    def close(self) -> None:
        self.conn.close()

    # -- dialect-aware primitives -----------------------------------------
    def _placeholders(self, n: int) -> str:
        return ",".join([self.ph] * n)

    def _upsert_sql(self, table: str, columns: list[str], conflict: list[str]) -> str:
        cols = ",".join(columns)
        vals = self._placeholders(len(columns))
        if self.dialect == "postgres":
            updates = ",".join(f"{c}=EXCLUDED.{c}" for c in columns if c not in conflict)
            tail = (f" ON CONFLICT ({','.join(conflict)}) DO UPDATE SET {updates}"
                    if updates else f" ON CONFLICT ({','.join(conflict)}) DO NOTHING")
            return f"INSERT INTO {table} ({cols}) VALUES ({vals}){tail}"
        return f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({vals})"

    def _upsert(self, table: str, row: dict) -> None:
        row = self._with_snapshot_key(table, row)
        columns, conflict = _TABLES[table]
        sql = self._upsert_sql(table, columns, conflict)
        self._exec(sql, [row.get(c) for c in columns])

    def _upsert_many(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        columns, conflict = _TABLES[table]
        if table in _SNAPSHOT_KEYED or table == "option_quotes":
            rows = [self._with_snapshot_key(table, r) for r in rows]
        sql = self._upsert_sql(table, columns, conflict)
        self._execmany(sql, [[r.get(c) for c in columns] for r in rows])

    def _exec(self, sql: str, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        self.conn.commit()
        return cur

    def _execmany(self, sql: str, rows):
        cur = self.conn.cursor()
        cur.executemany(sql, rows)
        self.conn.commit()
        return cur

    @staticmethod
    def _rowdict(cur, row) -> dict:
        if row is None:
            return {}
        try:
            return dict(row)            # sqlite3.Row / RealDictRow
        except (TypeError, ValueError):
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))

    def _query(self, sql: str, params=()) -> list[dict]:
        cur = self._exec(sql, params)
        return [self._rowdict(cur, r) for r in cur.fetchall()]

    def _query_one(self, sql: str, params=()) -> dict | None:
        cur = self._exec(sql, params)
        row = cur.fetchone()
        return self._rowdict(cur, row) if row is not None else None

    # -- writes ------------------------------------------------------------
    def save_snapshot_meta(self, *, snapshot_id, valuation_date, source, quality,
                           fetch_ts, iss_request_urls=None, metadata=None) -> None:
        # Keep the snapshot's integer key stable across re-saves (INSERT OR REPLACE
        # rewrites the row, so the surrogate must be carried explicitly).
        self._upsert("market_data_snapshots", {
            "snapshot_id": snapshot_id, "valuation_date": _iso(valuation_date),
            "source": source, "quality": quality, "created_at": datetime.now().isoformat(),
            "fetch_ts": _iso(fetch_ts), "iss_request_urls": json.dumps(iss_request_urls or []),
            "metadata": json.dumps(metadata or {}),
            "snapshot_key": self._resolve_snapshot_key(snapshot_id),
        })

    def save_curve(self, snapshot_id, curve_id, *, method, nss_params, as_of, points) -> None:
        self._upsert("yield_curves", {
            "snapshot_id": snapshot_id, "curve_id": curve_id, "method": method,
            "nss_params": json.dumps(nss_params or {}), "as_of": _iso(as_of) if as_of else None,
        })
        self._upsert_many("curve_points", [
            {"snapshot_id": snapshot_id, "curve_id": curve_id, "tenor": float(t),
             "zero_rate": float(z), "discount_factor": (float(df) if df is not None else None)}
            for (t, z, df) in points
        ])

    def delete_curve(self, snapshot_id, curve_id) -> None:
        """Drop a curve and its points so a re-ingest with different tenors
        does not leave stale nodes behind (curve_points upsert is per-tenor)."""
        self._exec(f"DELETE FROM curve_points WHERE snapshot_id={self.ph} AND curve_id={self.ph}",
                   (snapshot_id, curve_id))
        self._exec(f"DELETE FROM yield_curves WHERE snapshot_id={self.ph} AND curve_id={self.ph}",
                   (snapshot_id, curve_id))

    def save_fx_rate(self, snapshot_id, pair, rate, source="MOEX", trade_time=None) -> None:
        self._upsert("fx_rates", {"snapshot_id": snapshot_id, "pair": pair,
                                  "rate": float(rate), "source": source, "trade_time": trade_time})

    def save_instrument(self, row: dict) -> None:
        self._upsert("instruments", row)

    def save_bond_quote(self, snapshot_id, row: dict) -> None:
        self._upsert("bond_quotes", {"snapshot_id": snapshot_id, **{
            k: row.get(k) for k in ("secid", "clean_price", "dirty_price", "wap_price",
                                    "accruedint", "ytm", "volume", "board")}})

    def save_equity_quote(self, snapshot_id, row: dict) -> None:
        self._upsert("equity_quotes", {"snapshot_id": snapshot_id, **{
            k: row.get(k) for k in ("secid", "last", "prevprice", "board", "volume")}})

    def save_index_value(self, snapshot_id, indexid, value, trade_date) -> None:
        self._upsert("index_values", {"snapshot_id": snapshot_id, "indexid": indexid,
                                      "value": value, "trade_date": trade_date})

    def save_vol_point(self, snapshot_id, underlying, expiry, strike, iv) -> None:
        self._upsert("vol_points", {"snapshot_id": snapshot_id, "underlying": underlying,
                                    "expiry": str(expiry), "strike": float(strike),
                                    "iv": (float(iv) if iv is not None else None)})

    def save_time_series(self, factor_id, kind, points) -> None:
        self._upsert_many("time_series", [
            {"factor_id": factor_id, "dt": dt, "value": float(v), "kind": kind}
            for (dt, v) in points
        ])

    def save_bond_schedule(self, secid, *, coupons=None, amortizations=None,
                           offers=None) -> None:
        """Persist a bondization schedule (coupons / amortization / offers)."""
        self._upsert_many("bond_coupons", [
            {"secid": secid, "coupon_date": str(c["date"]), "value": c.get("value"),
             "value_prc": c.get("value_prc")} for c in (coupons or [])])
        self._upsert_many("bond_amortizations", [
            {"secid": secid, "amort_date": str(a["date"]), "value": a.get("value"),
             "face_remaining": a.get("face_remaining")} for a in (amortizations or [])])
        self._upsert_many("bond_offers", [
            {"secid": secid, "offer_date": str(o["date"]), "price": o.get("price"),
             "offer_type": o.get("offer_type")} for o in (offers or [])])
        self._record_schedule_version(secid)        # version-on-change (stored form)

    @staticmethod
    def _schedule_hash(sched: dict) -> str:
        blob = json.dumps(sched, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def _record_schedule_version(self, secid) -> None:
        sched = self.get_bond_schedule(secid)       # stored, already sorted
        counts = (len(sched["coupons"]), len(sched["amortizations"]), len(sched["offers"]))
        if not any(counts):
            return                                  # nothing scheduled → no version
        h = self._schedule_hash(sched)
        cur = self._query_one(
            f"SELECT version, payload_hash FROM bond_schedule_versions "
            f"WHERE secid={self.ph} AND valid_to IS NULL", (secid,))
        if cur and cur.get("payload_hash") == h:
            return                                  # unchanged
        today = datetime.now().date().isoformat()
        if cur:
            self._exec(f"UPDATE bond_schedule_versions SET valid_to={self.ph} "
                       f"WHERE secid={self.ph} AND valid_to IS NULL", (today, secid))
            version = int(cur["version"]) + 1
        else:
            version = 1
        self._exec(
            f"INSERT INTO bond_schedule_versions "
            f"(secid, version, valid_from, valid_to, payload_hash, n_coupons, n_amort, "
            f"n_offers, schedule_json, created_at) VALUES ({self._placeholders(10)})",
            (secid, version, today, None, h, counts[0], counts[1], counts[2],
             json.dumps(sched, ensure_ascii=False, default=str), datetime.now().isoformat()))

    def get_bond_schedule_versions(self, secid) -> list[dict]:
        return self._query(
            f"SELECT version, valid_from, valid_to, n_coupons, n_amort, n_offers "
            f"FROM bond_schedule_versions WHERE secid={self.ph} ORDER BY version", (secid,))

    def save_commodity_quotes(self, snapshot_id, rows: list[dict]) -> None:
        self._upsert_many("commodity_quotes", [
            {"snapshot_id": snapshot_id, "asset": r["asset"], "secid": r["secid"],
             "expiry": r.get("expiry"), "settle": r.get("settle"),
             "open_interest": r.get("open_interest"), "volume": r.get("volume")}
            for r in rows])

    def get_commodity_quotes(self, snapshot_id, asset: str | None = None) -> list[dict]:
        if asset:
            return self._query(
                f"SELECT * FROM commodity_quotes WHERE snapshot_id={self.ph} AND asset={self.ph} "
                f"ORDER BY expiry", (snapshot_id, asset))
        return self._query(
            f"SELECT * FROM commodity_quotes WHERE snapshot_id={self.ph} ORDER BY asset, expiry",
            (snapshot_id,))

    def save_option_quotes(self, rows: list[dict]) -> None:
        self._upsert_many("option_quotes", rows)

    def get_option_chain(self, asset_code) -> list[dict]:
        return self._query(
            f"SELECT secid, expiry, strike, opt_type, last, settle, oi, volume, "
            f"central_strike, underlying FROM option_quotes WHERE asset_code={self.ph} "
            f"ORDER BY expiry, strike", (asset_code,))

    def save_dividends(self, secid, rows: list[dict]) -> None:
        self._upsert_many("dividends", [
            {"secid": secid, "registry_date": str(r["registry_date"]),
             "value": r.get("value"), "currency": r.get("currency")}
            for r in rows if r.get("registry_date")])

    def get_dividends(self, secid) -> list[dict]:
        return self._query(
            f"SELECT registry_date, value, currency FROM dividends WHERE secid={self.ph} "
            f"ORDER BY registry_date", (secid,))

    def get_bond_schedule(self, secid) -> dict:
        return {
            "coupons": self._query(
                f"SELECT coupon_date, value, value_prc FROM bond_coupons "
                f"WHERE secid={self.ph} ORDER BY coupon_date", (secid,)),
            "amortizations": self._query(
                f"SELECT amort_date, value, face_remaining FROM bond_amortizations "
                f"WHERE secid={self.ph} ORDER BY amort_date", (secid,)),
            "offers": self._query(
                f"SELECT offer_date, price, offer_type FROM bond_offers "
                f"WHERE secid={self.ph} ORDER BY offer_date", (secid,)),
        }

    def log_ingest(self, endpoint, status, rows, started_at, finished_at, error="") -> None:
        self._exec(
            f"INSERT INTO ingest_log (endpoint, status, rows, started_at, finished_at, error) "
            f"VALUES ({self._placeholders(6)})",
            (endpoint, status, rows, _iso(started_at), _iso(finished_at), error),
        )

    # -- reads -------------------------------------------------------------
    def get_snapshot_meta(self, snapshot_id) -> dict | None:
        return self._query_one(
            f"SELECT * FROM market_data_snapshots WHERE snapshot_id={self.ph}", (snapshot_id,))

    def latest_snapshot_meta(self, source: str | None = None) -> dict | None:
        """Most recent stored snapshot (optionally filtered by source)."""
        if source:
            return self._query_one(
                f"SELECT * FROM market_data_snapshots WHERE source={self.ph} "
                f"ORDER BY valuation_date DESC LIMIT 1", (source,))
        return self._query_one(
            "SELECT * FROM market_data_snapshots ORDER BY valuation_date DESC LIMIT 1")

    def recent_ingest_log(self, limit: int = 40) -> list[dict]:
        return self._query(
            f"SELECT endpoint, status, rows, started_at, finished_at, error "
            f"FROM ingest_log ORDER BY run_id DESC LIMIT {int(limit)}")

    def get_curve(self, snapshot_id, curve_id) -> dict | None:
        return self._query_one(
            f"SELECT * FROM yield_curves WHERE snapshot_id={self.ph} AND curve_id={self.ph}",
            (snapshot_id, curve_id))

    def get_curve_points(self, snapshot_id, curve_id) -> list[dict]:
        return self._query(
            f"SELECT tenor, zero_rate, discount_factor FROM curve_points "
            f"WHERE snapshot_id={self.ph} AND curve_id={self.ph} ORDER BY tenor",
            (snapshot_id, curve_id))

    def list_curve_ids(self, snapshot_id) -> list[str]:
        return [r["curve_id"] for r in self._query(
            f"SELECT curve_id FROM yield_curves WHERE snapshot_id={self.ph}", (snapshot_id,))]

    def get_fx_rates(self, snapshot_id) -> dict[str, float]:
        return {r["pair"]: r["rate"] for r in self._query(
            f"SELECT pair, rate FROM fx_rates WHERE snapshot_id={self.ph}", (snapshot_id,))}

    def get_fx_quotes(self, snapshot_id) -> list[dict]:
        return self._query(
            f"SELECT pair, rate, source, trade_time FROM fx_rates WHERE snapshot_id={self.ph} ORDER BY pair",
            (snapshot_id,))

    def get_all_dividends(self, limit: int = 2000) -> list[dict]:
        return self._query(
            f"SELECT secid, registry_date, value, currency FROM dividends "
            f"ORDER BY registry_date DESC LIMIT {int(limit)}")

    def list_snapshots(self) -> list[dict]:
        return self._query(
            "SELECT snapshot_id, valuation_date, source, quality FROM market_data_snapshots "
            "ORDER BY valuation_date DESC")

    def get_bond_quotes(self, snapshot_id) -> list[dict]:
        return self._query(f"SELECT * FROM bond_quotes WHERE snapshot_id={self.ph}", (snapshot_id,))

    def get_calibration_bonds(self, snapshot_id) -> list[dict]:
        return self._query(
            f"""SELECT b.secid AS secid, b.ytm AS ytm, b.volume AS volume,
                       i.mat_date AS mat_date, i.list_level AS list_level,
                       i.coupon_percent AS coupon_percent, i.issuer AS issuer
                FROM bond_quotes b JOIN instruments i ON b.secid = i.secid
                WHERE b.snapshot_id={self.ph} AND b.ytm IS NOT NULL AND i.mat_date IS NOT NULL""",
            (snapshot_id,))

    def get_real_bonds(self, snapshot_id, board=None, limit=None) -> list[dict]:
        """Tradeable bonds = market quote joined with the instrument reference."""
        sql = (
            f"SELECT b.secid, b.clean_price, b.dirty_price, b.accruedint, b.ytm, b.volume, b.board, "
            f"i.isin, i.facevalue, i.coupon_percent, i.coupon_period, i.next_coupon, i.mat_date, "
            f"i.offer_date, i.issuer, i.list_level, i.currency "
            f"FROM bond_quotes b LEFT JOIN instruments i ON b.secid = i.secid "
            f"WHERE b.snapshot_id={self.ph} AND b.clean_price IS NOT NULL"
        )
        params = [snapshot_id]
        if board:
            sql += f" AND b.board={self.ph}"
            params.append(board)
        sql += " ORDER BY b.volume DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self._query(sql, tuple(params))

    def get_bond_ref(self, secid) -> dict | None:
        return self._query_one(f"SELECT * FROM instruments WHERE secid={self.ph}", (secid,))

    def get_bond_quote(self, snapshot_id, secid) -> dict | None:
        return self._query_one(
            f"SELECT * FROM bond_quotes WHERE snapshot_id={self.ph} AND secid={self.ph}",
            (snapshot_id, secid))

    def get_equity_quotes(self, snapshot_id) -> list[dict]:
        return self._query(f"SELECT * FROM equity_quotes WHERE snapshot_id={self.ph}", (snapshot_id,))

    def get_equity_spot(self, snapshot_id, secid) -> float | None:
        row = self._query_one(
            f"SELECT last, prevprice FROM equity_quotes WHERE snapshot_id={self.ph} AND secid={self.ph}",
            (snapshot_id, secid))
        if not row:
            return None
        return row["last"] if row.get("last") is not None else row.get("prevprice")

    def get_vol_points(self, snapshot_id) -> list[dict]:
        return self._query(
            f"SELECT underlying, expiry, strike, iv FROM vol_points WHERE snapshot_id={self.ph} "
            f"ORDER BY underlying, expiry, strike", (snapshot_id,))

    def latest_vol_snapshot(self) -> str | None:
        row = self._query_one("SELECT MAX(snapshot_id) AS s FROM vol_points")
        return row["s"] if row and row.get("s") else None

    def vol_surface_underlyings(self) -> list[dict]:
        sid = self.latest_vol_snapshot()
        if not sid:
            return []
        return self._query(
            f"SELECT underlying, COUNT(DISTINCT expiry) AS expiries, COUNT(*) AS points "
            f"FROM vol_points WHERE snapshot_id={self.ph} GROUP BY underlying "
            f"ORDER BY points DESC", (sid,))

    def vol_surface_points(self, underlying) -> list[dict]:
        sid = self.latest_vol_snapshot()
        if not sid:
            return []
        return self._query(
            f"SELECT expiry, strike, iv FROM vol_points WHERE snapshot_id={self.ph} "
            f"AND underlying={self.ph} ORDER BY expiry, strike", (sid, underlying))

    def get_time_series(self, factor_id, kind=None) -> list[dict]:
        if kind:
            return self._query(
                f"SELECT dt, value FROM time_series WHERE factor_id={self.ph} AND kind={self.ph} ORDER BY dt",
                (factor_id, kind))
        return self._query(
            f"SELECT dt, value FROM time_series WHERE factor_id={self.ph} ORDER BY dt", (factor_id,))

    def list_time_series_factors(self) -> list[dict]:
        """Catalog of stored historical series: id, kind, point count, span."""
        return self._query(
            "SELECT factor_id, kind, COUNT(*) AS points, "
            "MIN(dt) AS start, MAX(dt) AS end "
            "FROM time_series GROUP BY factor_id, kind ORDER BY factor_id")

    # -- continuously-accumulated store (price_history + instrument_ref) ----
    def save_price_history(self, rows: list[dict]) -> None:
        """Idempotent append of daily OHLCV rows (PK secid+market+dt)."""
        self._upsert_many("price_history", rows)

    def price_history_max_dt(self, secid, market) -> str | None:
        row = self._query_one(
            f"SELECT MAX(dt) AS dt FROM price_history WHERE secid={self.ph} AND market={self.ph}",
            (secid, market))
        return row["dt"] if row else None

    def get_price_history(self, secid, market=None, frm=None, till=None) -> list[dict]:
        sql = ("SELECT dt, open, high, low, close, volume, value, yield, numtrades "
               "FROM price_history WHERE secid=" + self.ph)
        params = [secid]
        if market:
            sql += f" AND market={self.ph}"
            params.append(market)
        if frm:
            sql += f" AND dt>={self.ph}"
            params.append(frm)
        if till:
            sql += f" AND dt<={self.ph}"
            params.append(till)
        sql += " ORDER BY dt"
        return self._query(sql, tuple(params))

    def save_instrument_ref(self, row: dict) -> None:
        self._record_instrument_version(row)        # version-on-change (before the upsert)
        self._ref_currency(row.get("currency"))     # keep reference look-ups current
        self._ref_board(row.get("board"), row.get("market"))
        self._upsert("instrument_ref", row)

    def _ref_hash(self, row: dict) -> str:
        payload = {k: row.get(k) for k in _REF_VERSION_FIELDS}
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def _record_instrument_version(self, row: dict, *, source: str = "MOEX") -> None:
        """Cut a new reference version iff the descriptive payload changed."""
        secid = row.get("secid")
        if not secid:
            return
        h = self._ref_hash(row)
        cur = self._query_one(
            f"SELECT version, payload_hash FROM instrument_versions "
            f"WHERE secid={self.ph} AND valid_to IS NULL", (secid,))
        if cur and cur.get("payload_hash") == h:
            return                                   # unchanged → no new version
        as_of = row.get("as_of") or datetime.now().date().isoformat()
        if cur:
            self._exec(f"UPDATE instrument_versions SET valid_to={self.ph} "
                       f"WHERE secid={self.ph} AND valid_to IS NULL", (as_of, secid))
            version = int(cur["version"]) + 1
        else:
            version = 1
        payload = {k: row.get(k) for k in _REF_VERSION_FIELDS}
        self._exec(
            f"INSERT INTO instrument_versions "
            f"(secid, version, valid_from, valid_to, source, payload_hash, fields_json, created_at) "
            f"VALUES ({self._placeholders(8)})",
            (secid, version, as_of, None, source, h,
             json.dumps(payload, ensure_ascii=False, default=str), datetime.now().isoformat()))

    def get_instrument_versions(self, secid) -> list[dict]:
        return self._query(
            f"SELECT version, valid_from, valid_to, source, payload_hash "
            f"FROM instrument_versions WHERE secid={self.ph} ORDER BY version", (secid,))

    def get_instrument_ref(self, secid) -> dict | None:
        return self._query_one(
            f"SELECT * FROM instrument_ref WHERE secid={self.ph}", (secid,))

    def list_instrument_refs(self, category, *, active_only=False) -> list[dict]:
        sql = f"SELECT * FROM instrument_ref WHERE category={self.ph}"
        params = [category]
        if active_only:
            sql += " AND is_active=1"
        sql += " ORDER BY issuer_ru, secid"
        return self._query(sql, tuple(params))

    def table_columns(self, table: str) -> list[dict]:
        if not table.isidentifier():
            return []
        return [{"name": r["name"], "type": r["type"]}
                for r in self._query(f"PRAGMA table_info({table})")]

    def table_count(self, table: str) -> int:
        if not table.isidentifier():
            return 0
        row = self._query_one(f"SELECT COUNT(*) AS n FROM {table}")
        return int(row["n"]) if row else 0

    def table_rows(self, table: str, limit: int = 200) -> list[dict]:
        if not table.isidentifier():
            return []
        return self._query(f"SELECT * FROM {table} LIMIT {int(limit)}")

    def count_instrument_refs(self, category, *, active_only=False) -> int:
        sql = f"SELECT COUNT(*) AS n FROM instrument_ref WHERE category={self.ph}"
        if active_only:
            sql += " AND is_active=1"
        row = self._query_one(sql, (category,))
        return int(row["n"]) if row else 0

    def list_commodity_assets(self) -> list[str]:
        return [r["asset"] for r in self._query(
            "SELECT DISTINCT asset FROM commodity_quotes ORDER BY asset")]

    def futures_chain(self, asset_code) -> list[dict]:
        return self._query(
            f"SELECT * FROM instrument_ref WHERE asset_code={self.ph} ORDER BY last_trade_date",
            (asset_code,))
