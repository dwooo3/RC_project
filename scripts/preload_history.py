"""Preload the continuously-accumulated market store (5y daily history + refs).

Idempotent: re-running only appends missing days. WAL so the bridge keeps
reading while this writes.

Usage:
    python3.14 -m scripts.preload_history bonds [years] [limit]
"""

from __future__ import annotations

import sys


def main() -> int:
    category = sys.argv[1] if len(sys.argv) > 1 else "bonds"
    years = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None

    from app import runtime
    from infra.db.market_data_db import MarketDataDB
    from infra.market_store import MarketStore
    from infra.moex_iss.client import IssClient

    path = runtime.db_path()
    if not path:
        print("no market-data DB path", flush=True)
        return 1
    db = MarketDataDB(path)
    try:
        db.conn.execute("PRAGMA journal_mode=WAL")
        db.conn.execute("PRAGMA busy_timeout=60000")
    except Exception:
        pass

    store = MarketStore(db, IssClient())
    log = lambda m: print(m, flush=True)  # noqa: E731
    if category == "bonds":
        log(f"preloading bonds: {years}y daily history + refs (limit={limit})")
        log(f"done: {store.preload_bonds(years=years, limit=limit, progress=log)}")
    elif category == "equities":
        log(f"preloading equities: {years}y daily history + refs + dividends (limit={limit})")
        log(f"done: {store.preload_equities(years=years, limit=limit, progress=log)}")
    else:
        log(f"category '{category}' not yet supported")
        return 1
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
