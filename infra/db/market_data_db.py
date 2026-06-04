"""
Local market-data database (SQLite) per MOEX_MARKET_DATA_INTEGRATION_PROMPT.md §3.

Schema is designed to map onto domain.MarketDataSnapshot / MarketDataStore and to
make every calculation reproducible (snapshot_id + valuation_date + ISS request
URLs + fetch timestamp). SQLite now; the same DDL/queries target Postgres later
(Phase E) — no SQLite-only features are used.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    secid TEXT PRIMARY KEY,
    isin TEXT, board TEXT, type TEXT, currency TEXT,
    facevalue REAL, coupon_percent REAL, coupon_period INTEGER,
    next_coupon TEXT, mat_date TEXT, offer_date TEXT,
    lot_size REAL, list_level INTEGER, issuer TEXT, sector TEXT,
    static_json TEXT
);

CREATE TABLE IF NOT EXISTS market_data_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    valuation_date TEXT NOT NULL,
    source TEXT NOT NULL,
    quality TEXT NOT NULL,
    created_at TEXT NOT NULL,
    fetch_ts TEXT NOT NULL,
    iss_request_urls TEXT,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS yield_curves (
    snapshot_id TEXT NOT NULL,
    curve_id TEXT NOT NULL,
    method TEXT,
    nss_params TEXT,
    as_of TEXT,
    PRIMARY KEY (snapshot_id, curve_id)
);

CREATE TABLE IF NOT EXISTS curve_points (
    snapshot_id TEXT NOT NULL,
    curve_id TEXT NOT NULL,
    tenor REAL NOT NULL,
    zero_rate REAL NOT NULL,
    discount_factor REAL,
    PRIMARY KEY (snapshot_id, curve_id, tenor)
);

CREATE TABLE IF NOT EXISTS fx_rates (
    snapshot_id TEXT NOT NULL,
    pair TEXT NOT NULL,
    rate REAL NOT NULL,
    source TEXT,
    trade_time TEXT,
    PRIMARY KEY (snapshot_id, pair)
);

CREATE TABLE IF NOT EXISTS bond_quotes (
    snapshot_id TEXT NOT NULL,
    secid TEXT NOT NULL,
    clean_price REAL, dirty_price REAL, wap_price REAL,
    accruedint REAL, ytm REAL, volume REAL, board TEXT,
    PRIMARY KEY (snapshot_id, secid)
);

CREATE TABLE IF NOT EXISTS equity_quotes (
    snapshot_id TEXT NOT NULL,
    secid TEXT NOT NULL,
    last REAL, prevprice REAL, board TEXT, volume REAL,
    PRIMARY KEY (snapshot_id, secid)
);

CREATE TABLE IF NOT EXISTS index_values (
    snapshot_id TEXT NOT NULL,
    indexid TEXT NOT NULL,
    value REAL,
    trade_date TEXT,
    PRIMARY KEY (snapshot_id, indexid)
);

CREATE TABLE IF NOT EXISTS time_series (
    factor_id TEXT NOT NULL,
    dt TEXT NOT NULL,
    value REAL,
    kind TEXT NOT NULL,
    PRIMARY KEY (factor_id, dt, kind)
);
CREATE INDEX IF NOT EXISTS idx_time_series_factor ON time_series (factor_id, dt);

CREATE TABLE IF NOT EXISTS vol_points (
    snapshot_id TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiry TEXT NOT NULL,
    strike REAL NOT NULL,
    iv REAL,
    PRIMARY KEY (snapshot_id, underlying, expiry, strike)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT, status TEXT, rows INTEGER,
    started_at TEXT, finished_at TEXT, error TEXT
);
"""


def _iso(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


class MarketDataDB:
    """Thin SQLite persistence for MOEX market data."""

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- writes ------------------------------------------------------------
    def save_snapshot_meta(
        self,
        *,
        snapshot_id: str,
        valuation_date: date,
        source: str,
        quality: str,
        fetch_ts: datetime,
        iss_request_urls: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO market_data_snapshots
               (snapshot_id, valuation_date, source, quality, created_at, fetch_ts,
                iss_request_urls, metadata)
               VALUES (?,?,?,?,?,?,?,?)""",
            (snapshot_id, _iso(valuation_date), source, quality,
             datetime.now().isoformat(), _iso(fetch_ts),
             json.dumps(iss_request_urls or []), json.dumps(metadata or {})),
        )
        self.conn.commit()

    def save_curve(self, snapshot_id: str, curve_id: str, *, method: str,
                   nss_params: dict | None, as_of: date | str | None,
                   points: list[tuple[float, float, float | None]]) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO yield_curves (snapshot_id, curve_id, method, nss_params, as_of)
               VALUES (?,?,?,?,?)""",
            (snapshot_id, curve_id, method, json.dumps(nss_params or {}),
             _iso(as_of) if as_of else None),
        )
        self.conn.executemany(
            """INSERT OR REPLACE INTO curve_points
               (snapshot_id, curve_id, tenor, zero_rate, discount_factor) VALUES (?,?,?,?,?)""",
            [(snapshot_id, curve_id, float(t), float(z), (float(df) if df is not None else None))
             for (t, z, df) in points],
        )
        self.conn.commit()

    def save_fx_rate(self, snapshot_id: str, pair: str, rate: float,
                     source: str = "MOEX", trade_time: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO fx_rates (snapshot_id, pair, rate, source, trade_time) VALUES (?,?,?,?,?)",
            (snapshot_id, pair, float(rate), source, trade_time),
        )
        self.conn.commit()

    def save_instrument(self, row: dict) -> None:
        cols = ["secid", "isin", "board", "type", "currency", "facevalue",
                "coupon_percent", "coupon_period", "next_coupon", "mat_date",
                "offer_date", "lot_size", "list_level", "issuer", "sector", "static_json"]
        values = [row.get(c) for c in cols]
        self.conn.execute(
            f"INSERT OR REPLACE INTO instruments ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            values,
        )
        self.conn.commit()

    def save_bond_quote(self, snapshot_id: str, row: dict) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO bond_quotes
               (snapshot_id, secid, clean_price, dirty_price, wap_price, accruedint, ytm, volume, board)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (snapshot_id, row["secid"], row.get("clean_price"), row.get("dirty_price"),
             row.get("wap_price"), row.get("accruedint"), row.get("ytm"),
             row.get("volume"), row.get("board")),
        )
        self.conn.commit()

    def save_time_series(self, factor_id: str, kind: str,
                         points: list[tuple[str, float]]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO time_series (factor_id, dt, value, kind) VALUES (?,?,?,?)",
            [(factor_id, dt, float(v), kind) for (dt, v) in points],
        )
        self.conn.commit()

    def log_ingest(self, endpoint: str, status: str, rows: int,
                   started_at: datetime, finished_at: datetime, error: str = "") -> None:
        self.conn.execute(
            """INSERT INTO ingest_log (endpoint, status, rows, started_at, finished_at, error)
               VALUES (?,?,?,?,?,?)""",
            (endpoint, status, rows, _iso(started_at), _iso(finished_at), error),
        )
        self.conn.commit()

    # -- reads -------------------------------------------------------------
    def get_snapshot_meta(self, snapshot_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM market_data_snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_curve(self, snapshot_id: str, curve_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM yield_curves WHERE snapshot_id=? AND curve_id=?",
            (snapshot_id, curve_id),
        ).fetchone()
        return dict(row) if row else None

    def get_curve_points(self, snapshot_id: str, curve_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tenor, zero_rate, discount_factor FROM curve_points "
            "WHERE snapshot_id=? AND curve_id=? ORDER BY tenor",
            (snapshot_id, curve_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_curve_ids(self, snapshot_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT curve_id FROM yield_curves WHERE snapshot_id=?", (snapshot_id,)
        ).fetchall()
        return [r["curve_id"] for r in rows]

    def get_fx_rates(self, snapshot_id: str) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT pair, rate FROM fx_rates WHERE snapshot_id=?", (snapshot_id,)
        ).fetchall()
        return {r["pair"]: r["rate"] for r in rows}

    def get_bond_quotes(self, snapshot_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM bond_quotes WHERE snapshot_id=?", (snapshot_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_time_series(self, factor_id: str, kind: str | None = None) -> list[dict]:
        if kind:
            rows = self.conn.execute(
                "SELECT dt, value FROM time_series WHERE factor_id=? AND kind=? ORDER BY dt",
                (factor_id, kind),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT dt, value FROM time_series WHERE factor_id=? ORDER BY dt", (factor_id,)
            ).fetchall()
        return [dict(r) for r in rows]
