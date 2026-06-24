"""
CBR ingestion (Phase D) — key rate and RUONIA into the local market-data DB.

Both feed:
  - time_series (kind='rate') for history / risk factors;
  - a short flat curve (KEYRATE_RUB / RUONIA_RUB, source CBR) usable as a policy /
    overnight anchor and as the seed for a future RUONIA OIS dual-curve.

A genuine RUONIA OIS term structure needs OIS swap quotes (not just the fixing);
until those exist the curve is a fixing-anchored flat proxy, clearly labelled.
"""

from __future__ import annotations

import math
from datetime import date, datetime

from infra.cbr.client import CbrClient
from infra.db.market_data_db import MarketDataDB

# Short-end tenors for the flat policy / overnight curves (years).
_SHORT_TENORS = [0.003, 0.083, 0.25, 0.5, 1.0, 2.0]


class CbrIngestor:
    def __init__(self, client: CbrClient, db: MarketDataDB):
        self.client = client
        self.db = db

    @staticmethod
    def _latest(records: list[tuple[str, float]]) -> tuple[str, float] | None:
        return max(records, key=lambda r: r[0]) if records else None

    def _ingest_rate(self, *, snapshot_id, valuation_date, records, factor_id,
                     curve_id, label, endpoint, write_curve: bool = True) -> int:
        started = datetime.now()
        try:
            self.db.save_time_series(factor_id, "rate", records)
            latest = self._latest(records)
            if write_curve and latest is not None:
                as_of, rate = latest
                points = [(t, rate, math.exp(-rate * t)) for t in _SHORT_TENORS]
                self.db.save_curve(
                    snapshot_id, curve_id, method="cbr_flat",
                    nss_params={"anchor_rate": rate, "label": label},
                    as_of=as_of, points=points,
                )
            self.db.log_ingest(endpoint, "ok", len(records), started, datetime.now())
            return len(records)
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    def ingest_key_rate(self, snapshot_id: str, valuation_date: date,
                        from_date: date | None = None, till_date: date | None = None) -> int:
        from_date = from_date or valuation_date
        records = self.client.get_key_rate(from_date, till_date)
        return self._ingest_rate(
            snapshot_id=snapshot_id, valuation_date=valuation_date, records=records,
            factor_id="CBR_KEYRATE:rate", curve_id="KEYRATE_RUB",
            label="CBR key rate", endpoint="cbr/key_rate",
        )

    def ingest_ruonia(self, snapshot_id: str, valuation_date: date,
                      from_date: date | None = None, till_date: date | None = None) -> int:
        from_date = from_date or valuation_date
        records = self.client.get_ruonia(from_date, till_date)
        # Only the time_series (the O/N fixing history) — the RUONIA_RUB *curve*
        # is now the OIS bootstrap from MOEX RUSFAR (MoexIngestor.ingest_ruonia_ois),
        # not a flat fixing proxy.
        return self._ingest_rate(
            snapshot_id=snapshot_id, valuation_date=valuation_date, records=records,
            factor_id="RUONIA:rate", curve_id="RUONIA_RUB",
            label="RUONIA O/N fixing", endpoint="cbr/ruonia", write_curve=False,
        )
