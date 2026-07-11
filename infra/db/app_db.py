"""
Application persistence (Phase 4): portfolios, positions, audit trail.

SQLite-backed, same conventions as MarketDataDB (":memory:" default for tests,
upsert semantics, dict rows). Market data already persists via MarketDataDB;
this closes the remaining in-memory gaps: the portfolio book and the audit log
now survive restarts.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any

from domain.audit import CalculationRecord
from domain.portfolio import Portfolio, Position


_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS portfolios (
        portfolio_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        base_currency TEXT NOT NULL DEFAULT 'RUB',
        owner TEXT DEFAULT '',
        market_data_snapshot_id TEXT DEFAULT '',
        metadata TEXT DEFAULT '{}',
        created_at TEXT,
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS positions (
        position_id TEXT NOT NULL,
        portfolio_id TEXT NOT NULL,
        instrument TEXT NOT NULL,
        description TEXT DEFAULT '',
        quantity REAL NOT NULL,
        params TEXT NOT NULL DEFAULT '{}',
        currency TEXT DEFAULT 'RUB',
        book TEXT DEFAULT 'Trading',
        trader TEXT DEFAULT '',
        metadata TEXT DEFAULT '{}',
        PRIMARY KEY (portfolio_id, position_id)
    )""",
    """CREATE TABLE IF NOT EXISTS audit_records (
        record_id TEXT PRIMARY KEY,
        ts TEXT,
        user_action TEXT,
        user_id TEXT,
        calculation_type TEXT,
        model_id TEXT,
        model_version TEXT,
        market_data_snapshot_id TEXT,
        inputs_hash TEXT,
        result_id TEXT,
        details TEXT DEFAULT '{}'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_records (ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_records (calculation_type)",
    """CREATE TABLE IF NOT EXISTS pricing_environments (
        env_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        updated_at TEXT
    )""",
]


class AppDB:
    """Portfolio book + audit trail persistence."""

    def __init__(self, path: str = ":memory:"):
        # check_same_thread=False: the bridge serves from a uvicorn thread pool
        # (same gotcha as MarketDataDB — a per-thread connection breaks every
        # endpoint after the first cross-thread call).
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        for stmt in _SCHEMA:
            self.conn.execute(stmt)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ── Portfolios ─────────────────────────────────────────

    def save_portfolio(self, portfolio: Portfolio) -> None:
        """Upsert the portfolio header and replace its position set."""
        self.conn.execute(
            """INSERT INTO portfolios
               (portfolio_id, name, base_currency, owner, market_data_snapshot_id,
                metadata, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(portfolio_id) DO UPDATE SET
                 name=excluded.name, base_currency=excluded.base_currency,
                 owner=excluded.owner,
                 market_data_snapshot_id=excluded.market_data_snapshot_id,
                 metadata=excluded.metadata, updated_at=excluded.updated_at""",
            (portfolio.portfolio_id, portfolio.name, portfolio.base_currency,
             portfolio.owner, portfolio.market_data_snapshot_id,
             json.dumps(portfolio.metadata, default=str),
             portfolio.created_at.isoformat() if portfolio.created_at else None,
             datetime.now().isoformat()),
        )
        self.conn.execute("DELETE FROM positions WHERE portfolio_id=?",
                          (portfolio.portfolio_id,))
        for pos in portfolio.positions:
            self.conn.execute(
                """INSERT INTO positions
                   (position_id, portfolio_id, instrument, description, quantity,
                    params, currency, book, trader, metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pos.id, portfolio.portfolio_id, pos.instrument, pos.description,
                 pos.quantity, json.dumps(pos.params, default=str), pos.currency,
                 pos.book, pos.trader, json.dumps(pos.metadata, default=str)),
            )
        self.conn.commit()

    def load_portfolio(self, portfolio_id: str) -> Portfolio:
        row = self.conn.execute(
            "SELECT * FROM portfolios WHERE portfolio_id=?", (portfolio_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Portfolio not found: {portfolio_id}")
        positions = [
            Position(
                id=p["position_id"], instrument=p["instrument"],
                description=p["description"], quantity=p["quantity"],
                params=json.loads(p["params"]), currency=p["currency"],
                book=p["book"], trader=p["trader"],
                metadata=json.loads(p["metadata"]),
            )
            for p in self.conn.execute(
                "SELECT * FROM positions WHERE portfolio_id=? ORDER BY position_id",
                (portfolio_id,),
            ).fetchall()
        ]
        return Portfolio(
            name=row["name"], positions=positions, portfolio_id=row["portfolio_id"],
            base_currency=row["base_currency"], owner=row["owner"],
            market_data_snapshot_id=row["market_data_snapshot_id"],
            metadata=json.loads(row["metadata"]),
        )

    # ── Pricing environments (A1) ──────────────────────────

    def save_environment(self, env) -> None:
        """Upsert a PricingEnvironment (domain object or dict)."""
        payload = env.to_dict() if hasattr(env, "to_dict") else dict(env)
        self.conn.execute(
            """INSERT INTO pricing_environments (env_id, payload, updated_at)
               VALUES (?,?,?)
               ON CONFLICT(env_id) DO UPDATE SET
                 payload=excluded.payload, updated_at=excluded.updated_at""",
            (payload["env_id"], json.dumps(payload, default=str),
             datetime.now().isoformat()))
        self.conn.commit()

    def load_environment(self, env_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT payload FROM pricing_environments WHERE env_id=?",
            (env_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_environments(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM pricing_environments ORDER BY env_id").fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def delete_environment(self, env_id: str) -> None:
        self.conn.execute("DELETE FROM pricing_environments WHERE env_id=?", (env_id,))
        self.conn.commit()

    def list_portfolios(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT portfolio_id, name, base_currency, owner, updated_at,"
            " (SELECT COUNT(*) FROM positions p WHERE p.portfolio_id = portfolios.portfolio_id)"
            " AS n_positions FROM portfolios ORDER BY portfolio_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_portfolio(self, portfolio_id: str) -> None:
        self.conn.execute("DELETE FROM positions WHERE portfolio_id=?", (portfolio_id,))
        self.conn.execute("DELETE FROM portfolios WHERE portfolio_id=?", (portfolio_id,))
        self.conn.commit()

    # ── Audit trail ────────────────────────────────────────

    def save_audit_record(self, record: CalculationRecord) -> None:
        ts = getattr(record, "timestamp", None) or getattr(record, "created_at", None)
        self.conn.execute(
            """INSERT OR REPLACE INTO audit_records
               (record_id, ts, user_action, user_id, calculation_type, model_id,
                model_version, market_data_snapshot_id, inputs_hash, result_id, details)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (record.record_id,
             ts.isoformat() if hasattr(ts, "isoformat") else str(ts or datetime.now().isoformat()),
             record.user_action, record.user_id, record.calculation_type,
             record.model_id, record.model_version, record.market_data_snapshot_id,
             record.inputs_hash, record.result_id,
             json.dumps(record.details, default=str)),
        )
        self.conn.commit()

    def load_audit_records(self, calculation_type: str | None = None,
                           model_id: str | None = None,
                           limit: int = 1000) -> list[dict[str, Any]]:
        sql = "SELECT * FROM audit_records"
        clauses, params = [], []
        if calculation_type:
            clauses.append("calculation_type=?"); params.append(calculation_type)
        if model_id:
            clauses.append("model_id=?"); params.append(model_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["details"] = json.loads(d["details"])
            out.append(d)
        return out

    def audit_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0]
