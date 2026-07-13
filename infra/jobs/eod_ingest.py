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

from datetime import date, datetime

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

    def publish_iv30(self, sid: str, valuation_date: date) -> dict:
        """Publish governed 30-calendar-day ATM-forward IV histories.

        ``IV30:{underlying}`` is deliberately separate from the old
        nearest-expiry ``IV:{underlying}`` series, so a methodology change
        cannot masquerade as a market shock.  Publication is fail-closed by
        trading date and uses only primary Black-76 settlement observations.
        """
        from infra.moex_iss.vol_surface import (
            PRIMARY_IV_METHOD,
            iv30_representative,
            primary_iv_provenance_error,
            vol_lineage_diagnostics,
        )

        result: dict = {
            "status": "skipped",
            "saved": 0,
            "target_days": 30,
            "snapshot_id": sid,
            "valuation_date": valuation_date.isoformat(),
            "source": "MOEX_FORTS_SETTLEMENT",
            "method": "atm_forward_total_variance_30d",
            "underlyings": {},
            "rejected": {},
            "warnings": [],
        }

        def revoke(reason: str) -> dict:
            self.db.replace_iv30_for_date(valuation_date, {})
            result["reason"] = reason
            result["quality_counts"] = {"OK": 0, "WARN": 0, "rejected": 0}
            return result

        if valuation_date.weekday() >= 5:
            return revoke("valuation_date_is_not_a_trading_weekday")

        manifest = self.db.get_snapshot_meta(sid)
        if manifest is None:
            return revoke("snapshot_manifest_missing")
        try:
            raw_manifest_date = str(manifest["valuation_date"]).strip()
            manifest_date = (
                date.fromisoformat(raw_manifest_date)
                if len(raw_manifest_date) == 10
                else datetime.fromisoformat(
                    raw_manifest_date.replace("Z", "+00:00")
                ).date()
            )
        except (KeyError, TypeError, ValueError):
            return revoke("snapshot_manifest_date_invalid")
        if manifest_date != valuation_date:
            return revoke("snapshot_manifest_date_mismatch")
        if str(manifest.get("source") or "").upper() != "MOEX":
            return revoke("snapshot_manifest_source_not_governed")
        if str(manifest.get("quality") or "").upper() != "OK":
            return revoke("snapshot_manifest_quality_not_ok")

        raw_points = self.db.get_vol_points(sid)
        rows = self.db.get_vol_point_observations(sid)
        if not raw_points:
            return revoke("no_raw_vol_surface")
        if not rows:
            return revoke("no_vol_point_provenance")
        lineage = vol_lineage_diagnostics(raw_points, rows)
        if not lineage["payload_match_complete"]:
            result["lineage"] = {
                "key_coverage_complete": lineage["key_coverage_complete"],
                "invalid_raw_payloads": lineage["invalid_raw_payloads"],
                "invalid_observation_payloads": (
                    lineage["invalid_observation_payloads"]),
                "iv_value_mismatch_keys": lineage["iv_value_mismatch_keys"],
            }
            return revoke("raw_provenance_payload_mismatch")

        by_underlying: dict[str, list[dict]] = {}
        for row in rows:
            by_underlying.setdefault(str(row.get("underlying") or "UNKNOWN"), []).append(row)

        publishable: dict[str, float] = {}
        for underlying, all_points in sorted(by_underlying.items()):
            points = [row for row in all_points
                      if row.get("method") == PRIMARY_IV_METHOD]
            if not points:
                result["rejected"][underlying] = {
                    "reason": "no_primary_black76_observations",
                }
                continue
            provenance_errors = [
                primary_iv_provenance_error(row, valuation_date)
                for row in points
            ]
            provenance_errors = [error for error in provenance_errors if error]
            if provenance_errors:
                reasons = sorted(set(provenance_errors))
                reason = (
                    "observation_date_not_verified"
                    if "observation_date_not_verified" in reasons
                    else "observation_date_mismatch"
                    if "observation_date_mismatch" in reasons
                    else reasons[0]
                )
                result["rejected"][underlying] = {
                    "reason": reason,
                    "provenance_errors": reasons,
                }
                continue
            representative = iv30_representative(points, valuation_date)
            if not representative.get("accepted"):
                result["rejected"][underlying] = representative
                continue
            if representative.get("quality") != "OK":
                result["rejected"][underlying] = {
                    **representative,
                    "reason": "representative_not_production_quality",
                }
                result["warnings"].extend(
                    f"{underlying}: {warning}"
                    for warning in representative.get("warnings", []))
                continue
            factor_id = f"IV30:{underlying}"
            publishable[underlying] = representative["value"]
            result["underlyings"][underlying] = {
                "factor_id": factor_id,
                **representative,
            }
            result["warnings"].extend(
                f"{underlying}: {warning}"
                for warning in representative.get("warnings", []))

        # One commit both revokes stale same-date values and publishes the
        # representatives that survived every provenance/methodology gate.
        self.db.replace_iv30_for_date(valuation_date, publishable)
        result["saved"] = len(publishable)
        if result["saved"]:
            result["status"] = "partial" if result["rejected"] else "ok"
        else:
            result["reason"] = "no_publishable_iv30_observations"
        result["quality_counts"] = {
            "OK": sum(row.get("quality") == "OK"
                      for row in result["underlyings"].values()),
            "WARN": sum(row.get("quality") == "WARN"
                        for row in result["underlyings"].values()),
            "rejected": len(result["rejected"]),
        }
        return result

    def _iv_history(self, sid: str, valuation_date: date) -> dict:
        """Backward-compatible alias for the public snapshot publisher."""
        return self.publish_iv30(sid, valuation_date)

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

        # RUONIA OIS curve bootstrapped from MOEX RUSFAR term rates (overwrites
        # the legacy flat fixing proxy as RUONIA_RUB).
        step("ruonia_ois", lambda: moex.ingest_ruonia_ois(sid, valuation_date))

        # cbonds RUONIA OIS reference curve (manual capture) for cross-validation.
        def _cbonds_ruonia():
            from infra.cbonds import CBONDS_AS_OF, ingest_cbonds_ruonia_ois
            if CBONDS_AS_OF > valuation_date:
                return 0
            return ingest_cbonds_ruonia_ois(self.db, sid, as_of=CBONDS_AS_OF)

        step("ruonia_ois_cbonds", _cbonds_ruonia)

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

        # Zero curve bootstrapped from OFZ-PD prices (needs schedules above).
        step("ofz_zero", lambda: moex.ingest_ofz_zero(sid, valuation_date))

        # Offshore FX funding curves (SOFR/€STR live; CNH via SOFR + MOEX crosses).
        step("fx_offshore", lambda: moex.ingest_fx_offshore(sid, valuation_date))

        # Stage V.4: commodity futures curves + dividends for the liquid names
        step("commodity_futures", lambda: moex.ingest_commodity_futures(sid, valuation_date))

        def _dividends():
            quotes = self.db.get_equity_quotes(sid)
            top = sorted(quotes, key=lambda q: q.get("volume") or 0,
                         reverse=True)[: self.bondization_top]
            return moex.ingest_dividends([q["secid"] for q in top if q.get("secid")])

        step("dividends", _dividends)

        try:
            snap = MarketDataService(market_db=self.db).moex_snapshot(
                valuation_date,
                fallback_to_demo=False,
                persist_manifest=True,
            )
            summary["snapshot"] = {
                "source": snap.source_value,
                "quality": snap.quality,
                "curves": sorted(snap.curves),
                "vol_surfaces": sorted(snap.vol_surfaces),
            }
        except Exception as exc:
            summary["snapshot"] = {"error": str(exc)}

        # Stage I.5b: publish governed constant-maturity history only after the
        # authoritative snapshot manifest exists. Legacy IV:{code} remains
        # untouched; the new methodology is published as IV30:{code}.
        step("iv_history", lambda: self.publish_iv30(sid, valuation_date))

        # Stage II.2: compute + persist a validation report (MD-002) with alerts
        try:
            from infra.jobs.data_quality import persist_quality_report
            summary["quality_report"] = persist_quality_report(self.db, sid, valuation_date)
        except Exception as exc:
            summary["quality_report"] = {"error": str(exc)}
        return summary
