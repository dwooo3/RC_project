#!/usr/bin/env python3
"""
CLI runner for the EOD market-data ingest (MOEX ISS + CBR).

Usage:
    python3.14 run_eod_ingest.py                # today, data/market_data.sqlite
    python3.14 run_eod_ingest.py 2026-06-09     # specific valuation date
    python3.14 run_eod_ingest.py 2026-06-09 --db path/to.sqlite

After a successful run, MarketDataService(market_db=MarketDataDB(<db>))
.moex_snapshot(<date>) returns the REAL governed snapshot instead of the demo
fallback, and the app picks it up through the Market Data workspace.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit("RiskCalc requires Python 3.10+ "
             "(on this machine: /usr/local/bin/python3.14).")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from infra.cbr.client import CbrClient
from infra.db.market_data_db import MarketDataDB
from infra.jobs.eod_ingest import EodIngestJob
from infra.moex_iss.client import IssClient


def main() -> int:
    parser = argparse.ArgumentParser(description="RiskCalc EOD market-data ingest")
    parser.add_argument("valuation_date", nargs="?", default=None,
                        help="YYYY-MM-DD (default: today)")
    parser.add_argument("--db", default="data/market_data.sqlite",
                        help="SQLite path (default: data/market_data.sqlite)")
    parser.add_argument("--board", default="TQOB", help="bond board (default TQOB)")
    args = parser.parse_args()

    valuation_date = (date.fromisoformat(args.valuation_date)
                      if args.valuation_date else date.today())
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    db = MarketDataDB(args.db)
    job = EodIngestJob(db, IssClient(), CbrClient(), board=args.board)
    summary = job.run(valuation_date)

    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    failed = [k for k, v in summary["steps"].items()
              if isinstance(v, str) and v.startswith("error")]
    snap = summary.get("snapshot", {})
    ok = "error" not in snap
    print(f"\n{'OK' if ok else 'FAILED'}: snapshot {summary['snapshot_id']} "
          f"quality={snap.get('quality', '—')}"
          + (f", failed steps: {', '.join(failed)}" if failed else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
