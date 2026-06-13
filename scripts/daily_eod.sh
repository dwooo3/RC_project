#!/bin/bash
# Daily EOD market-data ingest wrapper (Stage II.1).
# Invoked by launchd ~19:30 MSK on weekdays. Runs today's EOD ingest, then
# backfills any business days missed since the last stored snapshot, and writes
# a timestamped log. Self-contained: resolves its own repo root and Python.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${RISKCALC_PYTHON:-/usr/local/bin/python3.14}"
LOG_DIR="$REPO/data/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y-%m-%d)"
LOG="$LOG_DIR/eod_${STAMP}.log"

cd "$REPO" || exit 1
{
  echo "=== EOD ingest $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  # Catch up to 7 calendar days of missed business days (idempotent upserts),
  # then run today's EOD with the quality report.
  "$PY" run_eod_ingest.py --backfill 7 --top 50
  "$PY" run_eod_ingest.py
  echo "--- quality ---"
  "$PY" run_eod_ingest.py --quality
  echo "=== done $(date '+%H:%M:%S') ==="
} >>"$LOG" 2>&1

# Surface a one-line status to stdout (captured by launchd's StandardOutPath).
tail -n 3 "$LOG"
