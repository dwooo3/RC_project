"""Build the RUONIA OIS curves for given snapshots (or the latest few).

  RUONIA_RUB        — bootstrapped from live MOEX RUSFAR term rates
  RUONIA-OIS-CBONDS — cbonds.ru index 93204 reference (manual capture)

Usage:
    python3.14 -m scripts.build_ruonia_ois [snapshot_id ...]

With no args it targets the most recent snapshots in the DB.
"""

from __future__ import annotations

import sys
from datetime import date


def _vdate(sid: str) -> date:
    try:
        return date.fromisoformat(sid.replace("moex-", "")[:10])
    except ValueError:
        return date.today()


def main() -> int:
    from app import runtime
    from infra.cbonds import ingest_cbonds_ruonia_ois
    from infra.db.market_data_db import MarketDataDB
    from infra.moex_iss.client import IssClient
    from infra.moex_iss.ingest import MoexIngestor

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

    targets = sys.argv[1:]
    if not targets:
        rows = db._query("SELECT DISTINCT snapshot_id FROM curve_points "  # noqa: SLF001
                         "ORDER BY snapshot_id DESC LIMIT 4")
        targets = [r["snapshot_id"] for r in rows]

    moex = MoexIngestor(IssClient(), db)
    for sid in targets:
        vd = _vdate(sid)
        try:
            n = moex.ingest_ruonia_ois(sid, vd)
            print(f"{sid}: RUONIA_RUB (MOEX RUSFAR) -> {n} nodes", flush=True)
        except Exception as exc:
            print(f"{sid}: RUONIA_RUB FAILED: {exc}", flush=True)
        try:
            n = ingest_cbonds_ruonia_ois(db, sid)
            print(f"{sid}: RUONIA-OIS-CBONDS -> {n} nodes", flush=True)
        except Exception as exc:
            print(f"{sid}: cbonds FAILED: {exc}", flush=True)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
