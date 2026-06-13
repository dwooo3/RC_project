#!/usr/bin/env python3
"""
ISS/CBR API structure smoke test (Stage II.3).

Probes the live endpoints the ingest depends on and asserts the response still
carries the blocks/columns the parsers expect — catching MOEX API changes
before they silently break an EOD run. Network-tolerant: if the endpoints are
unreachable (e.g. geo-blocked CI runner) it exits 0 with SKIPPED, so it never
red-flags CI for connectivity. A genuine structural drift exits 2.

Run: python3.14 scripts/smoke_iss.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.cbr.client import CbrClient
from infra.moex_iss.client import IssClient

# endpoint -> (block, columns that MUST be present)
CHECKS = [
    ("engines/stock/zcyc", {"iss.only": "yearyields"}, "yearyields", {"period", "value"}),
    ("engines/stock/markets/bonds/boards/TQOB/securities",
     {"iss.only": "securities"}, "securities", {"SECID", "MATDATE"}),
    ("engines/stock/markets/shares/boards/TQBR/securities",
     {"iss.only": "securities,marketdata"}, "securities", {"SECID", "PREVPRICE"}),
    ("engines/futures/markets/options/securities",
     {"iss.only": "securities"}, "securities", {"SECID", "SHORTNAME"}),
    ("engines/futures/markets/forts/securities",
     {"iss.only": "securities"}, "securities", {"SECID", "ASSETCODE", "LASTTRADEDATE"}),
]


def _is_network_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("urlopen", "timed out", "connection", "resolve",
                                "ssl", "refused", "unreachable", "403", "failed after"))


def main() -> int:
    iss = IssClient()
    drift: list[str] = []
    checked = 0
    for path, params, block, required in CHECKS:
        try:
            blocks = iss.get_blocks(path, params)
        except Exception as exc:
            if _is_network_error(exc):
                print(f"SKIP {path}: network unavailable ({str(exc)[:60]})")
                return 0
            drift.append(f"{path}: fetch error {exc}")
            continue
        rows = blocks.get(block, [])
        if not rows:
            drift.append(f"{path}: block '{block}' empty/missing")
            continue
        missing = required - set(rows[0].keys())
        if missing:
            drift.append(f"{path}: '{block}' missing columns {sorted(missing)}")
        else:
            checked += 1
            print(f"OK   {path}: {block} has {sorted(required)}")

    # CBR HTML tables
    try:
        from datetime import date, timedelta
        c = CbrClient()
        till = date.today()
        kr = c.get_key_rate(till - timedelta(days=14), till)
        if kr:
            checked += 1
            print(f"OK   cbr/KeyRate: {len(kr)} rows, last={kr[-1]}")
        else:
            drift.append("cbr/KeyRate: parsed 0 rows (HTML layout changed?)")
    except Exception as exc:
        if not _is_network_error(exc):
            drift.append(f"cbr/KeyRate: {exc}")

    if drift:
        print("\nAPI DRIFT DETECTED:")
        for d in drift:
            print(f"  - {d}")
        return 2
    print(f"\nSMOKE OK: {checked} endpoints structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
