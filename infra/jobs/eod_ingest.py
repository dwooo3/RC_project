"""
End-of-day market-data ingestion job (Phase E + Stage I).

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

DEFAULT_INDICES = ["IMOEX", "RVI", "RGBI", "RUCBTRNS"]
DEFAULT_EQUITIES = ["SBER"]


class EodIngestJob:
    def __init__(self, db: MarketDataDB, iss_client, cbr_client=None, *,
                 board: str = "TQOB", indices=None, equities=None,
                 corp_board: str = "TQCB", bondization_top: int = 80):
        self.db = db
        self.iss_client = iss_client
        self.cbr_client = cbr_client
        self.board = board
        self.corp_board = corp_board
        self.bondization_top = bondization_top
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
        # Stage I.2: corp bonds feed the corporate-curve calibration
        step("bonds_corp", lambda: moex.ingest_bonds(sid, valuation_date, board=self.corp_board))
        step("corporate", lambda: moex.ingest_corporate_curves(sid, valuation_date))
        # Stage I.3: real curve from OFZ-IN linkers
        step("real_curve", lambda: moex.ingest_real_curve(sid, valuation_date))
        step("equity_quotes", lambda: moex.ingest_equity_quotes(sid, valuation_date))
        # Stage I.5: self-implied option vol surfaces
        step("vol_surface", lambda: moex.ingest_option_vol_surface(sid, valuation_date))
        for idx in self.indices:
            step(f"index:{idx}",
                 lambda idx=idx: moex.ingest_index_history(idx, valuation_date, valuation_date))
        for sec in self.equities:
            step(f"equity:{sec}",
                 lambda sec=sec: moex.ingest_equity_history(sec, valuation_date, valuation_date))

        official: dict[str, float] = {}
        if self.cbr_client is not None:
            cbr = CbrIngestor(self.cbr_client, self.db)
            step("cbr_key_rate", lambda: cbr.ingest_key_rate(sid, valuation_date))
            step("cbr_ruonia", lambda: cbr.ingest_ruonia(sid, valuation_date))

            # Stage I.4: official USD/EUR/CNY fixes (no exchange spot since 2024)
            def _official():
                rates = self.cbr_client.get_official_rates(valuation_date)
                market = self.db.get_fx_rates(sid)
                for pair, rate in rates.items():
                    if pair not in market:           # market quote wins over fix
                        self.db.save_fx_rate(sid, pair, rate, source="CBR")
                official.update(rates)
                return len(rates)

            step("cbr_official_fx", _official)

        # Stage I.4: FX forward curves from futures strips (anchored on fixes)
        def _fx_futures():
            spots = {**official, **self.db.get_fx_rates(sid)}
            return moex.ingest_fx_futures(sid, valuation_date, spot_rates=spots)

        step("fx_futures", _fx_futures)

        # Stage I.6: bondization for OFZ + the most liquid corp bonds
        def _bondization():
            quotes = self.db.get_bond_quotes(sid)
            ofz = [q["secid"] for q in quotes if q.get("board") == self.board]
            corp = sorted(
                (q for q in quotes if q.get("board") == self.corp_board),
                key=lambda q: q.get("volume") or 0, reverse=True,
            )[: self.bondization_top]
            secids = ofz + [q["secid"] for q in corp]
            return moex.ingest_bondization(secids)

        step("bondization", _bondization)

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
