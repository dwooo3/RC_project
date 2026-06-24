"""Backfill N years of historical market data into time_series.

Fills the historical store the risk/backtesting layer needs over a multi-year
window: index closes (IMOEX/RVI/RGBI/RUCBTRNS/RUSFAR*), top-liquid equity
closes, КБД (GCURVE) zero-rate history per business day, and CBR key
rate / RUONIA. Every write is an idempotent upsert, so re-running is safe.

Usage:
    python3.14 -m scripts.backfill_history [years] [top_equities]

Defaults: years=5, top_equities=50.

WAL journal mode is enabled so the running FastAPI bridge can keep reading the
same SQLite file while this writes.
"""

from __future__ import annotations

import sys
from datetime import date


def main() -> int:
    years = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    from app import runtime
    from infra.cbr.client import CbrClient
    from infra.db.market_data_db import MarketDataDB
    from infra.jobs.backfill import BackfillJob
    from infra.moex_iss.client import IssClient

    path = runtime.db_path()
    if not path:
        print("no market-data DB path (RISKCALC_DB unset and default missing)", flush=True)
        return 1

    till = date.today()
    frm = till.replace(year=till.year - years)
    print(f"backfill window: {frm.isoformat()} -> {till.isoformat()} "
          f"(top {top} equities)", flush=True)

    db = MarketDataDB(path)
    db.init_schema()
    # Concurrent-access friendly: WAL lets the bridge read while we write.
    try:
        db.conn.execute("PRAGMA journal_mode=WAL")
        db.conn.execute("PRAGMA busy_timeout=60000")
    except Exception as exc:  # noqa: BLE001 — best-effort tuning
        print(f"pragma tuning skipped: {exc}", flush=True)

    job = BackfillJob(db, IssClient(), CbrClient())
    summary = job.run(frm, till, top=top)

    print("=== backfill summary ===", flush=True)
    for name, res in summary.get("steps", {}).items():
        print(f"  {name}: {res}", flush=True)
    print(f"indices: {summary.get('indices')}", flush=True)
    print(f"equities: {len(summary.get('equities', []))} names", flush=True)

    rows = db._query("SELECT COUNT(*) AS n, COUNT(DISTINCT factor_id) AS f "  # noqa: SLF001
                     "FROM time_series")[0]
    print(f"time_series now: {rows['n']} rows across {rows['f']} factors", flush=True)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
