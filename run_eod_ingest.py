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
    parser.add_argument("--equities", default=None,
                        help="comma-separated tickers for daily history (e.g. SBER,GAZP)")
    parser.add_argument("--backfill", type=int, default=0, metavar="DAYS",
                        help="instead of EOD: backfill history DAYS calendar days back "
                             "(indices, top equities, KBD per-day, CBR series)")
    parser.add_argument("--top", type=int, default=50,
                        help="backfill: how many most-liquid TQBR names (default 50)")
    parser.add_argument("--cpi-csv", default=None, metavar="PATH",
                        help="load monthly CPI index from CSV (YYYY-MM-DD,value) and exit")
    parser.add_argument("--quality", action="store_true",
                        help="print a data-quality report for the snapshot and exit")
    args = parser.parse_args()

    valuation_date = (date.fromisoformat(args.valuation_date)
                      if args.valuation_date else date.today())
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    db = MarketDataDB(args.db)

    if args.cpi_csv:
        from infra.jobs.backfill import load_cpi_csv
        n = load_cpi_csv(db, args.cpi_csv)
        print(f"OK: loaded {n} CPI points into time_series CPI_RU")
        return 0

    if args.quality:
        from infra.moex_iss.ingest import MoexIngestor
        from infra.jobs.data_quality import (
            format_report, history_depth_report, snapshot_quality_report)
        sid = MoexIngestor.snapshot_id_for(valuation_date)
        if not db.get_snapshot_meta(sid):
            meta = db.latest_snapshot_meta()
            sid = meta["snapshot_id"] if meta else sid
        report = snapshot_quality_report(db, sid, valuation_date)
        hist = history_depth_report(db)
        print(format_report(report, hist))
        return 0 if report["status"] != "FAIL" else 1

    equities = ([s.strip() for s in args.equities.split(",") if s.strip()]
                if args.equities else None)

    if args.backfill > 0:
        from datetime import timedelta

        from infra.jobs.backfill import BackfillJob
        job = BackfillJob(db, IssClient(), CbrClient())
        summary = job.run(valuation_date - timedelta(days=args.backfill),
                          valuation_date, equities=equities, top=args.top)
        print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
        failed = [k for k, v in summary["steps"].items()
                  if isinstance(v, str) and v.startswith("error")]
        print(f"\n{'OK' if not failed else 'PARTIAL'}: backfill "
              f"{summary['from']}..{summary['till']}"
              + (f", failed: {', '.join(failed)}" if failed else ""))
        return 0

    job = EodIngestJob(db, IssClient(), CbrClient(), board=args.board,
                       equities=equities if equities is not None else None)
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
