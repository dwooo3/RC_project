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

import json
import sqlite3
from datetime import date, datetime
from typing import Any


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
         "fetch_ts", "iss_request_urls", "metadata"], ["snapshot_id"]),
    "yield_curves": (["snapshot_id", "curve_id", "method", "nss_params", "as_of"],
                     ["snapshot_id", "curve_id"]),
    "curve_points": (["snapshot_id", "curve_id", "tenor", "zero_rate", "discount_factor"],
                     ["snapshot_id", "curve_id", "tenor"]),
    "fx_rates": (["snapshot_id", "pair", "rate", "source", "trade_time"],
                 ["snapshot_id", "pair"]),
    "bond_quotes": (["snapshot_id", "secid", "clean_price", "dirty_price", "wap_price",
                     "accruedint", "ytm", "volume", "board"], ["snapshot_id", "secid"]),
    "equity_quotes": (["snapshot_id", "secid", "last", "prevprice", "board", "volume"],
                      ["snapshot_id", "secid"]),
    "index_values": (["snapshot_id", "indexid", "value", "trade_date"],
                     ["snapshot_id", "indexid"]),
    "time_series": (["factor_id", "dt", "value", "kind"], ["factor_id", "dt", "kind"]),
    "vol_points": (["snapshot_id", "underlying", "expiry", "strike", "iv"],
                   ["snapshot_id", "underlying", "expiry", "strike"]),
    "bond_coupons": (["secid", "coupon_date", "value", "value_prc"],
                     ["secid", "coupon_date"]),
    "bond_amortizations": (["secid", "amort_date", "value", "face_remaining"],
                           ["secid", "amort_date"]),
    "bond_offers": (["secid", "offer_date", "price", "offer_type"],
                    ["secid", "offer_date"]),
    "commodity_quotes": (["snapshot_id", "asset", "secid", "expiry", "settle",
                          "open_interest", "volume"],
                         ["snapshot_id", "secid"]),
    "dividends": (["secid", "registry_date", "value", "currency"],
                  ["secid", "registry_date"]),
}


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
        f"""CREATE TABLE IF NOT EXISTS ingest_log (
            run_id {serial_pk}, endpoint TEXT, status TEXT, rows INTEGER,
            started_at TEXT, finished_at TEXT, error TEXT)""",
    ]


class MarketDataDB:
    """Dialect-aware persistence (SQLite default, PostgreSQL-compatible)."""

    def __init__(self, path: str = ":memory:", *, conn=None, dialect: str = "sqlite"):
        if conn is not None:
            self.conn = conn
            self.dialect = dialect
        else:
            self.conn = sqlite3.connect(path)
            self.conn.row_factory = sqlite3.Row
            self.dialect = "sqlite"
        self.ph = "%s" if self.dialect == "postgres" else "?"
        self.init_schema()

    def init_schema(self) -> None:
        for stmt in _schema_statements(self.dialect):
            self._exec(stmt)

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
        columns, conflict = _TABLES[table]
        sql = self._upsert_sql(table, columns, conflict)
        self._exec(sql, [row.get(c) for c in columns])

    def _upsert_many(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        columns, conflict = _TABLES[table]
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
        self._upsert("market_data_snapshots", {
            "snapshot_id": snapshot_id, "valuation_date": _iso(valuation_date),
            "source": source, "quality": quality, "created_at": datetime.now().isoformat(),
            "fetch_ts": _iso(fetch_ts), "iss_request_urls": json.dumps(iss_request_urls or []),
            "metadata": json.dumps(metadata or {}),
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

    def get_time_series(self, factor_id, kind=None) -> list[dict]:
        if kind:
            return self._query(
                f"SELECT dt, value FROM time_series WHERE factor_id={self.ph} AND kind={self.ph} ORDER BY dt",
                (factor_id, kind))
        return self._query(
            f"SELECT dt, value FROM time_series WHERE factor_id={self.ph} ORDER BY dt", (factor_id,))
