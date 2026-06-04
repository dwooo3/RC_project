"""
End-of-day market-data ingestion job (Phase E).

Orchestrates all ISS + CBR ingestors for a single valuation date, persists to the
local DB, then materialises the governed MOEX snapshot. Each step is isolated so
one failing source does not abort the run (errors are captured in the summary and
in ingest_log). Idempotent — every write is an upsert.

Operationally this is the unit a scheduler / cron / systemd timer invokes once per
EOD for one valuation date (e.g. 2026-06-02).
"""

from __future__ import annotations

from datetime import date

from infra.cbr.ingest import CbrIngestor
from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.ingest import MoexIngestor
from services.market_data_service import MarketDataService

DEFAULT_INDICES = ["IMOEX", "RVI"]
DEFAULT_EQUITIES = ["SBER"]


class EodIngestJob:
    def __init__(self, db: MarketDataDB, iss_client, cbr_client=None, *,
                 board: str = "TQOB", indices=None, equities=None):
        self.db = db
        self.iss_client = iss_client
        self.cbr_client = cbr_client
        self.board = board
        self.indices = list(indices if indices is not None else DEFAULT_INDICES)
        self.equities = list(equities if equities is not None else DEFAULT_EQUITIES)

    def run(self, valuation_date: date | None = None) -> dict:
        valuation_date = valuation_date or date.today()
        sid = MoexIngestor.snapshot_id_for(valuation_date)
        moex = MoexIngestor(self.iss_client, self.db)
        summary: dict = {"valuation_date": valuation_date.isoformat(),
                         "snapshot_id": sid, "steps": {}}

        def step(name, fn):
            try:
                summary["steps"][name] = fn()
            except Exception as exc:  # isolate per-source failures
                summary["steps"][name] = f"error: {exc}"

        step("gcurve", lambda: moex.ingest_gcurve(sid, valuation_date))
        step("fx", lambda: moex.ingest_fx(sid, valuation_date))
        step("bonds", lambda: moex.ingest_bonds(sid, valuation_date, board=self.board))
        step("corporate", lambda: moex.ingest_corporate_curves(sid, valuation_date))
        step("equity_quotes", lambda: moex.ingest_equity_quotes(sid, valuation_date))
        step("vol_surface", lambda: moex.ingest_option_vol_surface(sid, valuation_date))
        for idx in self.indices:
            step(f"index:{idx}",
                 lambda idx=idx: moex.ingest_index_history(idx, valuation_date, valuation_date))
        for sec in self.equities:
            step(f"equity:{sec}",
                 lambda sec=sec: moex.ingest_equity_history(sec, valuation_date, valuation_date))

        if self.cbr_client is not None:
            cbr = CbrIngestor(self.cbr_client, self.db)
            step("cbr_key_rate", lambda: cbr.ingest_key_rate(sid, valuation_date))
            step("cbr_ruonia", lambda: cbr.ingest_ruonia(sid, valuation_date))

        try:
            snap = MarketDataService(market_db=self.db).moex_snapshot(valuation_date)
            summary["snapshot"] = {
                "source": snap.source_value,
                "quality": snap.quality,
                "curves": sorted(snap.curves),
                "vol_surfaces": sorted(snap.vol_surfaces),
            }
        except Exception as exc:
            summary["snapshot"] = {"error": str(exc)}
        return summary
