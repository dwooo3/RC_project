"""Market data platform service."""

import json
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol

import numpy as np

from curves import russia
from curves.yield_curve import YieldCurve
from domain.market_data import (
    MarketDataMode,
    MarketDataSnapshot,
    MarketDataSource,
    MarketDataStore,
)
from infra.moex_iss.validation import (
    QUALITY_OK,
    QUALITY_REJECTED,
    assess_quality,
    is_production_quality,
    validate_curve_points,
    validate_fx,
)


class NoProductionMarketDataError(RuntimeError):
    """Raised in production mode when no production-eligible snapshot is available
    (instead of silently falling back to DEMO)."""


class MarketDataProvider(Protocol):
    """Interface for market data provider adapters."""

    source: MarketDataSource

    def load_snapshot(self, valuation_date: date | None = None, **kwargs) -> MarketDataSnapshot:
        """Load a governed snapshot from the provider."""


class ProviderInterface:
    """Base class for provider interfaces that are intentionally not integrated yet."""

    source: MarketDataSource

    def load_snapshot(self, valuation_date: date | None = None, **kwargs) -> MarketDataSnapshot:
        raise NotImplementedError(f"{self.source.value} provider interface is prepared but not implemented")


class MoexProvider(ProviderInterface):
    """Assemble a governed MOEX snapshot from the local market-data DB.

    Reads curve points + FX written by the ingestion ETL, validates them,
    derives a quality verdict, and returns a MarketDataSnapshot(source=MOEX).
    Normal loads are read-only: an existing authoritative manifest is preserved
    byte-for-byte.  Ingestion jobs may explicitly request manifest publication.
    REJECTED data raises so it cannot feed valuations. Without a DB the provider
    stays a no-op (NotImplementedError -> DEMO fallback)."""

    source = MarketDataSource.MOEX

    def __init__(self, db=None):
        self.db = db

    def load_snapshot(
        self,
        valuation_date: date | None = None,
        *,
        db=None,
        persist_manifest: bool = False,
        require_manifest: bool = False,
        **kwargs,
    ) -> MarketDataSnapshot:
        db = db or self.db
        if db is None:
            raise NotImplementedError("MOEX provider requires a local market-data DB")
        inside_read_snapshot = bool(kwargs.pop("_inside_read_snapshot", False))
        read_snapshot = getattr(db, "read_snapshot", None)
        if require_manifest and persist_manifest:
            raise ValueError(
                "production snapshot validation cannot persist its manifest")
        if (require_manifest and not inside_read_snapshot
                and callable(read_snapshot)):
            with read_snapshot():
                return self.load_snapshot(
                    valuation_date,
                    db=db,
                    persist_manifest=False,
                    require_manifest=True,
                    _inside_read_snapshot=True,
                    **kwargs,
                )
        valuation_date = valuation_date or date.today()
        snapshot_id = f"moex-{valuation_date.isoformat()}"

        def strict_day(value, label: str) -> date:
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            if not isinstance(value, str):
                raise ValueError(f"{label} is not a valid ISO date")
            raw = value.strip()
            try:
                return (
                    date.fromisoformat(raw)
                    if len(raw) == 10
                    else datetime.fromisoformat(
                        raw.replace("Z", "+00:00")
                    ).date()
                )
            except ValueError as exc:
                raise ValueError(f"{label} is not a valid ISO date") from exc

        def json_value(raw, fallback):
            if raw in (None, ""):
                return fallback
            if isinstance(raw, type(fallback)):
                return raw
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError):
                return fallback
            return decoded if isinstance(decoded, type(fallback)) else fallback

        curve_ids = db.list_curve_ids(snapshot_id)
        if not curve_ids:
            raise KeyError(f"No MOEX market data ingested for {snapshot_id}")

        curves: dict[str, YieldCurve] = {}
        curve_errors: list[str] = []
        as_of: date | None = None
        for curve_id in curve_ids:
            points = db.get_curve_points(snapshot_id, curve_id)
            triples = [(p["tenor"], p["zero_rate"], p["discount_factor"]) for p in points]
            errs = validate_curve_points(triples)
            curve_meta = db.get_curve(snapshot_id, curve_id) or {}
            curve_as_of = None
            if curve_meta.get("as_of") in (None, ""):
                errs.append("curve observation date is missing")
            else:
                try:
                    curve_as_of = strict_day(
                        curve_meta["as_of"], f"{curve_id} observation date")
                except ValueError as exc:
                    errs.append(str(exc))
                if curve_as_of is not None and curve_as_of > valuation_date:
                    errs.append(
                        f"curve observation date {curve_as_of.isoformat()} is after "
                        f"valuation date {valuation_date.isoformat()}")
            curve_errors.extend(f"{curve_id}: {e}" for e in errs)
            if not errs:
                curves[curve_id] = YieldCurve(
                    [p["tenor"] for p in points],
                    [p["zero_rate"] for p in points],
                    label=curve_id,
                    interp="cubic" if len(points) >= 3 else "linear",
                    source=MarketDataSource.MOEX,
                    valuation_date=curve_as_of,
                    rate_type="zero",
                    metadata={
                        "source": "MOEX",
                        "snapshot_id": snapshot_id,
                        "as_of": curve_as_of.isoformat(),
                    },
                )
            if curve_as_of is not None and (
                    curve_id == "GCURVE_RUB" or as_of is None):
                as_of = curve_as_of

        fx_rates = db.get_fx_rates(snapshot_id)
        fx_errors = validate_fx(fx_rates)

        from infra.moex_iss.vol_surface import build_vol_surfaces
        vol_surfaces = build_vol_surfaces(db.get_vol_points(snapshot_id))

        present = set()
        if "GCURVE_RUB" in curves:
            present.add("GCURVE_RUB")
        if fx_rates:
            present.add("FX")
        quality, warnings = assess_quality(
            valuation_date=valuation_date,
            as_of=as_of,
            curve_errors=curve_errors,
            fx_errors=fx_errors,
            expected_components={"GCURVE_RUB", "FX"},
            present_components=present,
        )
        if quality == QUALITY_REJECTED:
            raise ValueError(f"MOEX snapshot rejected: {'; '.join(warnings)}")

        manifest = db.get_snapshot_meta(snapshot_id)
        if require_manifest and manifest is None:
            raise ValueError(f"MOEX snapshot {snapshot_id} has no authoritative manifest")
        computed_metadata = {
            "quality_warnings": warnings,
            "iss_request_urls": [],
            "trade_date": as_of.isoformat() if as_of else "",
        }
        if warnings:
            computed_metadata["warning"] = "; ".join(warnings)

        if manifest is not None:
            manifest_date = strict_day(
                manifest.get("valuation_date"), "manifest valuation date")
            if manifest_date != valuation_date:
                raise ValueError(
                    f"manifest valuation date {manifest_date.isoformat()} does not "
                    f"match requested {valuation_date.isoformat()}")
            if str(manifest.get("source") or "").upper() != "MOEX":
                raise ValueError("snapshot manifest source is not MOEX")
            manifest_quality = str(manifest.get("quality") or "").upper()
            if manifest_quality == QUALITY_REJECTED:
                raise ValueError("snapshot manifest is REJECTED")
            # Never promote an authoritative WARN/STALE/PARTIAL manifest merely
            # because a later read can still reconstruct curve and FX objects.
            effective_quality = (
                quality if quality != QUALITY_OK else manifest_quality
            )
            metadata = json_value(manifest.get("metadata"), {})
            iss_urls = json_value(manifest.get("iss_request_urls"), [])
        else:
            effective_quality = quality
            metadata = computed_metadata
            iss_urls = []

        if require_manifest:
            from infra.jobs.data_quality import (
                QUALITY_CONTRACT_VERSION,
                snapshot_quality_report,
            )
            quality_report = db.latest_validation_report(snapshot_id)
            report_checks = json_value(
                (quality_report or {}).get("checks_json"), {})
            current_report = snapshot_quality_report(
                db, snapshot_id, valuation_date=date.today())
            current_checks = current_report.get("checks") or {}
            if (not quality_report
                    or str(quality_report.get("status") or "").upper() != "OK"
                    or not bool(quality_report.get("production_eligible"))
                    or report_checks.get("contract_version")
                    != QUALITY_CONTRACT_VERSION
                    or report_checks.get("snapshot_fingerprint")
                    != current_checks.get("snapshot_fingerprint")
                    or str(current_report.get("status") or "").upper() != "OK"
                    or not bool(current_report.get("production_eligible"))):
                raise ValueError(
                    f"MOEX snapshot {snapshot_id} has no current production-eligible "
                    "validation report")

        if persist_manifest:
            persisted_metadata = dict(metadata)
            persisted_metadata.setdefault("quality_warnings", warnings)
            persisted_metadata.setdefault(
                "trade_date", as_of.isoformat() if as_of else "")
            db.save_snapshot_meta(
                snapshot_id=snapshot_id,
                valuation_date=valuation_date,
                source=MarketDataSource.MOEX.value,
                quality=effective_quality,
                fetch_ts=(manifest or {}).get("fetch_ts") or datetime.now(),
                iss_request_urls=iss_urls,
                metadata=persisted_metadata,
            )
            metadata = persisted_metadata

        return MarketDataSnapshot(
            snapshot_id=snapshot_id,
            valuation_date=valuation_date,
            source=MarketDataSource.MOEX,
            quality=effective_quality,
            curves=curves,
            fx_rates=fx_rates,
            vol_surfaces=vol_surfaces,
            source_details={
                "provider": "MOEX ISS",
                "trade_date": metadata.get(
                    "trade_date", as_of.isoformat() if as_of else ""),
                "manifest_present": manifest is not None or persist_manifest,
            },
            metadata=metadata,
        )


class BloombergProvider(ProviderInterface):
    source = MarketDataSource.BLOOMBERG


class ReutersProvider(ProviderInterface):
    source = MarketDataSource.REUTERS


class MarketDataService:
    """Own market data snapshots, sources, and typed market data containers."""

    def __init__(
        self,
        store: MarketDataStore | None = None,
        providers: dict[MarketDataSource, MarketDataProvider] | None = None,
        market_db=None,
        mode: MarketDataMode | str = MarketDataMode.RESEARCH,
    ):
        self.store = store or MarketDataStore()
        self.market_db = market_db
        self.mode = MarketDataMode(str(mode).lower()) if not isinstance(mode, MarketDataMode) else mode
        self.last_fallback_used = False        # True when the last resolve fell back to DEMO
        self.providers: dict[MarketDataSource, MarketDataProvider] = {
            MarketDataSource.MOEX: MoexProvider(db=market_db),
            MarketDataSource.BLOOMBERG: BloombergProvider(),
            MarketDataSource.REUTERS: ReutersProvider(),
        }
        if providers:
            self.providers.update(providers)

    def _source(self, source: MarketDataSource | str) -> MarketDataSource:
        if isinstance(source, MarketDataSource):
            return source
        return MarketDataSource(str(source).upper())

    def create_snapshot(
        self,
        *,
        snapshot_id: str,
        valuation_date: date | None = None,
        source: MarketDataSource | str = MarketDataSource.MANUAL,
        quality: str | None = None,
        curves: dict[str, YieldCurve] | None = None,
        vol_surfaces: dict[str, Any] | None = None,
        fx_rates: dict[str, float] | None = None,
        credit_curves: dict[str, Any] | None = None,
        credit_spreads: dict[str, float] | None = None,
        source_details: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> MarketDataSnapshot:
        """Create and optionally store one governed market data snapshot."""
        valuation_date = valuation_date or date.today()
        source_enum = self._source(source)
        snapshot = MarketDataSnapshot(
            snapshot_id=snapshot_id,
            valuation_date=valuation_date,
            source=source_enum,
            quality=quality or source_enum.value,
            curves=curves or {},
            vol_surfaces=vol_surfaces or {},
            fx_rates=dict(fx_rates or {}),
            credit_curves=credit_curves or {},
            credit_spreads=dict(credit_spreads or {}),
            source_details=source_details or {},
            metadata=metadata or {},
        )
        return self.store.save(snapshot) if persist else snapshot

    def demo_snapshot(self, valuation_date: date | None = None) -> MarketDataSnapshot:
        valuation_date = valuation_date or date.today()
        curves = {
            "flat_rub": self.flat_curve(
                0.10,
                label="Demo RUB flat",
                source=MarketDataSource.DEMO,
                valuation_date=valuation_date,
            ),
            "ofz_demo": self.ofz_curve(valuation_date=valuation_date),
            "ruonia_demo": self.ruonia_curve(valuation_date=valuation_date),
            "cbr_key_demo": self.cbr_key_rate_curve(valuation_date=valuation_date),
            "corp_1t_demo": self.corporate_curve("1st", valuation_date=valuation_date),
            "corp_hy_demo": self.corporate_curve("HY", valuation_date=valuation_date),
            "ofzin_real_demo": self.real_curve(valuation_date=valuation_date),
        }
        # Hazard curves bootstrapped from the demo corporate spread term structure
        # over OFZ. Tenors capped at 10y: beyond that the steep demo z-spread grid
        # is not a feasible par-CDS curve (the 15-20y quotes are arbitrageable
        # against the shorter ones), so the long end is left to flat extrapolation.
        hazard_curves = {
            "hazard_1t_demo": self.hazard_curve_from_spreads(
                russia.OFZ_TENORS_DEFAULT[3:9],           # 1y .. 10y
                russia.CORP_SPREAD_1T[3:9],
                disc_curve=curves["ofz_demo"], recovery=0.4,
                label="Hazard 1st tier demo",
            ),
            # HY capped at 7y: the 10y demo quote (19%) is already infeasible
            # against the shorter ones. clamp guards against future quote edits.
            "hazard_hy_demo": self.hazard_curve_from_spreads(
                russia.OFZ_TENORS_DEFAULT[3:8],           # 1y .. 7y
                russia.CORP_SPREAD_HY[3:8],
                disc_curve=curves["ofz_demo"], recovery=0.3,
                label="Hazard HY demo",
                on_infeasible="clamp",
            ),
        }
        return self.create_snapshot(
            snapshot_id=f"demo-{valuation_date.isoformat()}",
            valuation_date=valuation_date,
            source=MarketDataSource.DEMO,
            curves=curves,
            fx_rates={"USD/RUB": 90.0, "EUR/RUB": 98.0},
            vol_surfaces={
                "equity_flat_demo": {"type": "flat", "vol": 0.20},
                "fx_usdrub_demo": {"type": "rr_bf", "atm": 0.18, "rr": -0.025, "bf": 0.008},
                "swaption_cube_demo": self.swaption_cube_demo(curves["cbr_key_demo"]),
                "caplet_strip_demo": self.caplet_strip_demo(curves["cbr_key_demo"]),
            },
            credit_spreads={"corp_1t": 0.0100, "corp_hy": 0.0300},
            credit_curves={
                "corp_1t_demo": {"base_curve_id": "ofz_demo", "spread": 0.0100},
                "corp_hy_demo": {"base_curve_id": "ofz_demo", "spread": 0.0300},
                **hazard_curves,
            },
            source_details={"provider": "RiskCalc demo defaults"},
            metadata={"warning": "Demo/manual market data. Not production valuation."},
        )

    def snapshot_from_curves(
        self,
        curves: dict[str, YieldCurve],
        snapshot_id: str,
        source: MarketDataSource | str = MarketDataSource.MANUAL,
        valuation_date: date | None = None,
        quality: str | None = None,
        metadata: dict | None = None,
    ) -> MarketDataSnapshot:
        """Create a governed snapshot from service-owned curve objects."""
        return self.create_snapshot(
            snapshot_id=snapshot_id,
            valuation_date=valuation_date,
            source=source,
            quality=quality,
            curves=curves,
            metadata=metadata or {},
        )

    def manual_snapshot(
        self,
        snapshot_id: str,
        valuation_date: date | None = None,
        curves: dict[str, YieldCurve] | None = None,
        fx_rates: dict[str, float] | None = None,
        vol_surfaces: dict[str, Any] | None = None,
        credit_curves: dict[str, Any] | None = None,
        credit_spreads: dict[str, float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MarketDataSnapshot:
        """Create a manual market data snapshot from user-provided data."""
        return self.create_snapshot(
            snapshot_id=snapshot_id,
            valuation_date=valuation_date,
            source=MarketDataSource.MANUAL,
            curves=curves,
            fx_rates=fx_rates,
            vol_surfaces=vol_surfaces,
            credit_curves=credit_curves,
            credit_spreads=credit_spreads,
            metadata=metadata,
        )

    def csv_snapshot(
        self,
        snapshot_id: str,
        valuation_date: date | None = None,
        curves: dict[str, YieldCurve] | None = None,
        fx_rates: dict[str, float] | None = None,
        vol_surfaces: dict[str, Any] | None = None,
        credit_curves: dict[str, Any] | None = None,
        credit_spreads: dict[str, float] | None = None,
        source_file: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MarketDataSnapshot:
        """Create a CSV-sourced snapshot from already parsed CSV data."""
        source_details = {"provider": "CSV", "file": source_file}
        return self.create_snapshot(
            snapshot_id=snapshot_id,
            valuation_date=valuation_date,
            source=MarketDataSource.CSV,
            curves=curves,
            fx_rates=fx_rates,
            vol_surfaces=vol_surfaces,
            credit_curves=credit_curves,
            credit_spreads=credit_spreads,
            source_details=source_details,
            metadata=metadata,
        )

    def load_provider_snapshot(
        self,
        source: MarketDataSource | str,
        valuation_date: date | None = None,
        **kwargs,
    ) -> MarketDataSnapshot:
        """Load a snapshot through a registered provider interface."""
        source_enum = self._source(source)
        if source_enum not in self.providers:
            raise NotImplementedError(f"{source_enum.value} uses a local snapshot factory, not a provider adapter")
        provider = self.providers[source_enum]
        snapshot = provider.load_snapshot(valuation_date=valuation_date, **kwargs)
        return self.store.save(snapshot)

    def best_available_snapshot(self, valuation_date: date | None = None) -> MarketDataSnapshot:
        """
        Return the most useful snapshot for the app/services: the latest real MOEX
        snapshot persisted in the DB (or the one for valuation_date), else the DEMO
        snapshot. In PRODUCTION mode it never falls back silently — it raises
        NoProductionMarketDataError instead (MD-001).
        """
        self.last_fallback_used = False
        production = self.mode == MarketDataMode.PRODUCTION
        if self.market_db is None:
            if production:
                raise NoProductionMarketDataError("no market DB in production mode")
            self.last_fallback_used = True
            return self.demo_snapshot(valuation_date)
        try:
            if valuation_date is None:
                meta = self.market_db.latest_snapshot_meta(source=MarketDataSource.MOEX.value)
                if meta and meta.get("valuation_date"):
                    valuation_date = date.fromisoformat(str(meta["valuation_date"])[:10])
            if valuation_date is not None:
                return self.moex_snapshot(valuation_date)
            if production:
                raise NoProductionMarketDataError("no MOEX snapshot in the store")
        except NoProductionMarketDataError:
            raise
        except Exception:
            if production:
                raise NoProductionMarketDataError("could not resolve a production MOEX snapshot")
        self.last_fallback_used = True
        return self.demo_snapshot()

    def moex_snapshot(
        self,
        valuation_date: date | None = None,
        *,
        fallback_to_demo: bool | None = None,
        persist_manifest: bool = False,
    ) -> MarketDataSnapshot:
        """
        Return a production MOEX snapshot from the local DB, or fall back to the
        DEMO snapshot when MOEX data is unavailable / rejected. The fallback is
        allowed in DEMO/RESEARCH mode but forbidden in PRODUCTION (MD-001); when
        ``fallback_to_demo`` is left None it is derived from the mode.
        """
        if fallback_to_demo is None:
            fallback_to_demo = self.mode != MarketDataMode.PRODUCTION
        try:
            snap = self.load_provider_snapshot(
                MarketDataSource.MOEX,
                valuation_date,
                persist_manifest=persist_manifest,
                require_manifest=(self.mode == MarketDataMode.PRODUCTION),
            )
            if (self.mode == MarketDataMode.PRODUCTION
                    and not is_production_quality(snap.quality)):
                raise ValueError(
                    f"MOEX snapshot quality '{snap.quality}' is not production-ready")
            self.last_fallback_used = False
            return snap
        except Exception:
            if not fallback_to_demo:
                raise NoProductionMarketDataError(
                    f"no production MOEX snapshot for {valuation_date or 'latest'}")
            self.last_fallback_used = True
            return self.demo_snapshot(valuation_date)

    def flat_curve(
        self,
        rate: float,
        label: str = "Manual flat curve",
        source: MarketDataSource | str = MarketDataSource.MANUAL,
        valuation_date: date | None = None,
    ) -> YieldCurve:
        source_value = source.value if isinstance(source, MarketDataSource) else str(source).upper()
        return YieldCurve.flat(
            rate,
            label=label,
            source=source,
            valuation_date=valuation_date,
            metadata={"source": source_value},
        )

    def curve_from_rates(
        self,
        tenors: list[float],
        rates: list[float],
        label: str,
        source: MarketDataSource | str = MarketDataSource.MANUAL,
        valuation_date: date | None = None,
        interp: str = "linear",
        rate_type: str = "zero",
    ) -> YieldCurve:
        source_value = source.value if isinstance(source, MarketDataSource) else str(source).upper()
        return YieldCurve(
            tenors,
            rates,
            label=label,
            interp=interp,
            source=source,
            valuation_date=valuation_date,
            rate_type=rate_type,
            metadata={"source": source_value},
        )

    def ofz_curve(self, valuation_date: date | None = None) -> YieldCurve:
        return self.curve_from_rates(
            russia.OFZ_TENORS_DEFAULT,
            russia.OFZ_RATES_DEFAULT,
            label="OFZ G-curve demo",
            source=MarketDataSource.DEMO,
            valuation_date=valuation_date,
            interp="cubic",
            rate_type="zero_demo",
        )

    def ruonia_curve(self, valuation_date: date | None = None) -> YieldCurve:
        return self.curve_from_rates(
            russia.RUONIA_TENORS_DEFAULT,
            russia.RUONIA_RATES_DEFAULT,
            label="RUONIA OIS demo",
            source=MarketDataSource.DEMO,
            valuation_date=valuation_date,
            rate_type="zero_demo",
        )

    def cbr_key_rate_curve(self, valuation_date: date | None = None) -> YieldCurve:
        tenors = [0.003, 0.083, 0.25, 0.5, 1.0, 2.0]
        rates = [russia.CBR_KEY_RATE_DEFAULT] * len(tenors)
        return self.curve_from_rates(
            tenors,
            rates,
            label="CBR key rate demo",
            source=MarketDataSource.DEMO,
            valuation_date=valuation_date,
            rate_type="policy_demo",
        )

    def real_curve(self, valuation_date: date | None = None) -> YieldCurve:
        """OFZ-IN real (inflation-adjusted) zero curve — demo levels."""
        return self.curve_from_rates(
            russia.OFZIN_REAL_TENORS_DEFAULT,
            russia.OFZIN_REAL_RATES_DEFAULT,
            label="OFZ-IN real demo",
            source=MarketDataSource.DEMO,
            valuation_date=valuation_date,
            rate_type="real_zero_demo",
        )

    # Bootstraps are deterministic in their inputs; demo_snapshot() is called on
    # every curve fallback, so cache by quote/curve fingerprint (process-wide).
    _hazard_cache: dict = {}

    def hazard_curve_from_spreads(
        self,
        tenors: list[float],
        spreads: list[float],
        disc_curve: YieldCurve,
        recovery: float = 0.4,
        label: str = "hazard curve",
        on_infeasible: str = "raise",
    ):
        """Bootstrap a piecewise-constant hazard curve from CDS/z-spread quotes."""
        from curves.hazard import bootstrap_hazard_curve

        key = (tuple(tenors), tuple(spreads), recovery, on_infeasible,
               tuple(disc_curve.tenors), tuple(disc_curve.zero_rates))
        cached = MarketDataService._hazard_cache.get(key)
        if cached is not None:
            return cached
        curve = bootstrap_hazard_curve(
            list(tenors), list(spreads), disc_curve,
            recovery=recovery, label=label, on_infeasible=on_infeasible,
        )
        MarketDataService._hazard_cache[key] = curve
        return curve

    # Stage A: demo rates-vol structures (cached — SABR calibration per node)
    _rates_vol_cache: dict = {}

    def swaption_cube_demo(self, curve: YieldCurve):
        """Demo RUB swaption cube: ATM matrix + SABR smiles at liquid nodes."""
        from risk.vol_cube import SwaptionCube

        key = ("cube", tuple(curve.tenors), tuple(curve.zero_rates))
        cached = MarketDataService._rates_vol_cache.get(key)
        if cached is not None:
            return cached
        expiries = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0]
        tenors = [1.0, 2.0, 5.0, 10.0]
        # high-rate regime: short-expiry vols elevated, decaying with expiry/tenor
        atm = [[0.42, 0.40, 0.36, 0.33],
               [0.40, 0.38, 0.34, 0.31],
               [0.37, 0.35, 0.32, 0.29],
               [0.33, 0.31, 0.29, 0.27],
               [0.30, 0.29, 0.27, 0.25],
               [0.27, 0.26, 0.25, 0.23]]

        from models.short_rate import _forward_swap_rate

        def fwd(e, t):
            return _forward_swap_rate(curve, e, t, 2)[0]

        smile_quotes = {}
        for (e, t, atm_v) in ((1.0, 5.0, 0.32), (2.0, 5.0, 0.29), (1.0, 1.0, 0.37)):
            F = fwd(e, t)
            # receiver skew typical for high-rate markets: low strikes richer
            smile_quotes[(e, t)] = [(0.7 * F, atm_v + 0.045), (0.85 * F, atm_v + 0.02),
                                    (F, atm_v), (1.15 * F, atm_v - 0.005),
                                    (1.3 * F, atm_v + 0.005)]
        cube = SwaptionCube.calibrate(expiries, tenors, atm, smile_quotes, fwd,
                                      label="RUB swaption cube demo")
        MarketDataService._rates_vol_cache[key] = cube
        return cube

    def caplet_strip_demo(self, curve: YieldCurve):
        """Demo caplet ATM vol strip with one smile node."""
        from risk.vol_cube import CapletVolStrip

        key = ("strip", tuple(curve.tenors), tuple(curve.zero_rates))
        cached = MarketDataService._rates_vol_cache.get(key)
        if cached is not None:
            return cached
        expiries = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0]
        atm = [0.45, 0.42, 0.38, 0.33, 0.30, 0.27]

        def fwd(e):
            return (curve.discount(e) / curve.discount(e + 0.25) - 1.0) / 0.25

        F1 = fwd(1.0)
        smile = {1.0: [(0.7 * F1, 0.42), (F1, 0.38), (1.3 * F1, 0.375)]}
        strip = CapletVolStrip.calibrate(expiries, atm, smile, fwd,
                                         label="RUB caplet strip demo")
        MarketDataService._rates_vol_cache[key] = strip
        return strip

    def get_swaption_cube(self, cube_id: str = "swaption_cube_demo",
                          snapshot: MarketDataSnapshot | None = None):
        """Resolve a SwaptionCube stored in snapshot.vol_surfaces."""
        from risk.vol_cube import SwaptionCube

        snapshot = snapshot or self.demo_snapshot()
        obj = snapshot.vol_surfaces[cube_id]
        if not isinstance(obj, SwaptionCube):
            raise TypeError(f"vol surface {cube_id} is not a SwaptionCube")
        return obj

    def get_hazard_curve(self, hazard_id: str, snapshot: MarketDataSnapshot | None = None):
        """Resolve a HazardCurve object stored in snapshot.credit_curves."""
        from curves.hazard import HazardCurve

        snapshot = snapshot or self.demo_snapshot()
        obj = snapshot.credit_curves[hazard_id]
        if not isinstance(obj, HazardCurve):
            raise TypeError(f"credit curve {hazard_id} is not a HazardCurve (got {type(obj).__name__})")
        return obj

    def corporate_curve(
        self,
        tier: str = "1st",
        valuation_date: date | None = None,
    ) -> YieldCurve:
        base = self.ofz_curve(valuation_date=valuation_date)
        spread_key = {"1st": russia.CORP_SPREAD_1T, "HY": russia.CORP_SPREAD_HY}.get(
            tier, russia.CORP_SPREAD_1T
        )
        rates = [base.rate(T) + s for T, s in zip(russia.OFZ_TENORS_DEFAULT, spread_key)]
        return self.curve_from_rates(
            russia.OFZ_TENORS_DEFAULT,
            rates,
            label=f"Corporate {tier} demo",
            source=MarketDataSource.DEMO,
            valuation_date=valuation_date,
            rate_type="zero_demo",
        )

    def get_curve(
        self,
        curve_id: str = "flat_rub",
        snapshot: MarketDataSnapshot | None = None,
    ) -> YieldCurve:
        snapshot = snapshot or self.demo_snapshot()
        return snapshot.curves[curve_id]

    def get_snapshot(self, snapshot_id: str, version: int | None = None) -> MarketDataSnapshot:
        return self.store.get(snapshot_id, version)

    def resolve_pinned_snapshot(self, snapshot_id: str) -> MarketDataSnapshot:
        """Resolve one *pinned* snapshot without broad fallback or latest lookup.

        Resolution is intentionally bounded for reproducible pricing-run replay:

        1. return the exact id already owned by the in-memory ``MarketDataStore``;
        2. reconstruct an exact canonical MOEX id from its authoritative DB manifest;
        3. deterministically rebuild an exact ``demo-YYYY-MM-DD`` snapshot.

        Manual/CSV/provider snapshots are only replayable while their full object is
        present in ``MarketDataStore``. Their payload is not persisted by the market DB,
        so guessing one after restart would silently change valuation inputs and is
        therefore rejected. This method never calls ``best_available_snapshot`` and
        never substitutes the latest snapshot or DEMO for a missing MOEX/manual id.
        """
        if not isinstance(snapshot_id, str):
            raise TypeError("snapshot_id must be a string")
        if not snapshot_id or snapshot_id != snapshot_id.strip():
            raise ValueError("snapshot_id must be a non-empty exact identifier")
        # A strict pinned resolve never performs fallback, including on failure.
        self.last_fallback_used = False

        try:
            snapshot = self.store.get(snapshot_id)
        except KeyError:
            snapshot = None
        if snapshot is not None:
            self.last_fallback_used = False
            return snapshot

        if snapshot_id.startswith("demo-"):
            raw_date = snapshot_id[len("demo-"):]
            try:
                valuation_date = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise KeyError(
                    f"Pinned snapshot is unavailable or malformed: {snapshot_id}"
                ) from exc
            if len(raw_date) != 10 or valuation_date.isoformat() != raw_date:
                raise KeyError(
                    f"Pinned snapshot is unavailable or malformed: {snapshot_id}"
                )
            rebuilt = self.demo_snapshot(valuation_date)
            if rebuilt.snapshot_id != snapshot_id:  # defensive factory contract
                raise RuntimeError("demo snapshot factory returned a different id")
            self.last_fallback_used = False
            return rebuilt

        if self.market_db is None:
            raise KeyError(f"Pinned snapshot is unavailable: {snapshot_id}")

        def reconstruct_moex() -> MarketDataSnapshot:
            manifest = self.market_db.get_snapshot_meta(snapshot_id)
            if manifest is None:
                raise KeyError(
                    f"Pinned snapshot has no authoritative DB manifest: {snapshot_id}"
                )
            source = str(manifest.get("source") or "").upper()
            if source != MarketDataSource.MOEX.value:
                raise KeyError(
                    f"Pinned {source or 'UNKNOWN'} snapshot cannot be reconstructed "
                    f"after restart: {snapshot_id}"
                )
            try:
                valuation_date = self._basket_day(manifest.get("valuation_date"))
            except ValueError as exc:
                raise KeyError(
                    f"Pinned MOEX snapshot has invalid manifest date: {snapshot_id}"
                ) from exc
            expected_id = f"moex-{valuation_date.isoformat()}"
            if snapshot_id != expected_id:
                raise KeyError(
                    f"Pinned MOEX snapshot id/date mismatch: {snapshot_id} != {expected_id}"
                )

            # Use the local authoritative adapter directly. ``require_manifest=False``
            # deliberately avoids reclassifying a historical snapshot by today's
            # freshness; the manifest is required and validated above, and the provider
            # still validates curves, FX, source, manifest date and REJECTED status.
            rebuilt = MoexProvider(db=self.market_db).load_snapshot(
                valuation_date,
                db=self.market_db,
                persist_manifest=False,
                require_manifest=False,
            )
            if (rebuilt.snapshot_id != snapshot_id
                    or rebuilt.valuation_date != valuation_date
                    or rebuilt.source_value != MarketDataSource.MOEX.value):
                raise RuntimeError(
                    f"MOEX provider returned a different pinned snapshot for {snapshot_id}"
                )
            return rebuilt

        read_snapshot = getattr(self.market_db, "read_snapshot", None)
        try:
            if callable(read_snapshot):
                with read_snapshot():
                    rebuilt = reconstruct_moex()
            else:
                rebuilt = reconstruct_moex()
        except KeyError:
            raise
        except Exception as exc:
            raise KeyError(
                f"Pinned MOEX snapshot could not be safely reconstructed: {snapshot_id}"
            ) from exc

        self.last_fallback_used = False
        return self.store.save(rebuilt)

    def resolve_snapshot(self, snapshot_id: str) -> MarketDataSnapshot:
        """Compatibility alias for :meth:`resolve_pinned_snapshot`."""
        return self.resolve_pinned_snapshot(snapshot_id)

    def latest_snapshot(self) -> MarketDataSnapshot:
        return self.store.latest()

    def list_snapshot_versions(self, snapshot_id: str) -> list[MarketDataSnapshot]:
        return self.store.list_versions(snapshot_id)

    def snapshot_lineage(self, snapshot_id: str) -> list[dict[str, Any]]:
        """Return version lineage metadata owned by MarketDataStore."""
        return [
            {
                "snapshot_id": snapshot.snapshot_id,
                "version": snapshot.version,
                "source": snapshot.source_value,
                "quality": snapshot.quality,
                "created_at": snapshot.created_at,
                "created_by": snapshot.created_by,
                "parent_snapshot_id": snapshot.parent_snapshot_id,
                "valuation_date": snapshot.valuation_date,
            }
            for snapshot in self.store.list_versions(snapshot_id)
        ]

    def get_returns(
        self,
        factor_id: str,
        kind: str = "price",
        method: str = "log",
    ) -> np.ndarray:
        """
        Build a returns series from the local time_series store for a risk factor
        (e.g. "IMOEX:price", "SBER:price"). Feeds VaR / backtest / stress
        (architecture §10.4). Requires a configured market_db.
        """
        if self.market_db is None:
            raise RuntimeError("get_returns requires a configured market_db (Phase C time series)")
        rows = self.market_db.get_time_series(factor_id, kind)
        prices = np.array([r["value"] for r in rows], dtype=float)
        if prices.size < 2 or np.any(prices <= 0):
            return prices[1:] - prices[:-1] if prices.size >= 2 else np.array([])
        if method == "log":
            return np.diff(np.log(prices))
        return prices[1:] / prices[:-1] - 1.0

    # ── Basket underlyings for structured products ────────────────────
    #
    # Surfaces the *real* instrument universe (equities, bonds, indices) that a
    # structured note can be written on, and resolves a chosen basket to the spot /
    # vol / income / correlation inputs the pricing engine needs. Falls back to a
    # small demo universe + default risk parameters when no market DB is wired, so
    # the structured-note product prices in tests and demo mode too.

    _INDEX_LABELS = {
        "IMOEX": "MOEX Russia Index",
        "RTSI": "RTS Index",
        "RGBI": "OFZ Govt Bond Index",
        "RUCBTRNS": "Corp Bond Index (TR)",
        "RVI": "Volatility Index (RVI)",
    }

    _DEMO_UNIVERSE = [
        {"secid": "SBER", "kind": "equity", "label": "Sberbank", "spot": 322.4, "vol": 0.32, "income": 0.10},
        {"secid": "GAZP", "kind": "equity", "label": "Gazprom", "spot": 112.5, "vol": 0.34, "income": 0.0},
        {"secid": "LKOH", "kind": "equity", "label": "Lukoil", "spot": 4699.5, "vol": 0.28, "income": 0.12},
        {"secid": "GMKN", "kind": "equity", "label": "Nornickel", "spot": 110.0, "vol": 0.30, "income": 0.08},
        {"secid": "IMOEX", "kind": "index", "label": "MOEX Russia Index", "spot": 2515.3, "vol": 0.22, "income": 0.0},
        {"secid": "RGBI", "kind": "index", "label": "OFZ Govt Bond Index", "spot": 105.0, "vol": 0.06, "income": 0.0},
        {"secid": "SU26238RMFS4", "kind": "bond", "label": "OFZ-PD 26238", "spot": 56.5, "vol": 0.07, "income": 0.147},
        {"secid": "SU26254RMFS1", "kind": "bond", "label": "OFZ-PD 26254", "spot": 91.9, "vol": 0.07, "income": 0.149},
    ]

    def basket_universe(self, kind: str = "all", limit: int = 60) -> list[dict[str, Any]]:
        """Real instruments selectable as basket underlyings, grouped by kind.

        ``kind``: "equity" | "bond" | "index" | "all". Each entry is
        ``{"secid", "kind", "label"}``. Equities are restricted to liquid names that
        carry a price history (so vol / correlation are estimable). Without a market
        DB a small demo universe is returned.
        """
        if self.market_db is None:
            return [dict(secid=u["secid"], kind=u["kind"], label=u["label"])
                    for u in self._DEMO_UNIVERSE if kind in ("all", u["kind"])]

        out: list[dict[str, Any]] = []
        meta = self.market_db.latest_snapshot_meta()
        sid = meta["snapshot_id"] if meta else None
        history = self._price_factor_ids()

        if kind in ("equity", "all") and sid:
            for row in self.market_db.get_equity_quotes(sid):
                secid = row.get("secid")
                if secid in history and (row.get("last") or row.get("prevprice")):
                    out.append({"secid": secid, "kind": "equity", "label": secid})
            out.sort(key=lambda d: d["secid"])
        if kind in ("index", "all"):
            for idx, label in self._INDEX_LABELS.items():
                if idx in history:
                    out.append({"secid": idx, "kind": "index", "label": label})
        if kind in ("bond", "all") and sid:
            bonds = sorted(self.market_db.get_calibration_bonds(sid),
                           key=lambda b: -(b.get("volume") or 0))
            for row in bonds[:limit]:
                label = row.get("issuer") or row["secid"]
                out.append({"secid": row["secid"], "kind": "bond", "label": str(label)})
        return out

    def _price_factor_ids(self) -> set[str]:
        """SECIDs that have a daily price history in the local store (for vol/corr)."""
        if self.market_db is None:
            return set()
        try:
            rows = self.market_db._query(
                "SELECT DISTINCT factor_id FROM time_series WHERE kind='price'")
            return {r["factor_id"].replace(":price", "") for r in rows}
        except Exception:
            return set()

    def basket_market_inputs(
        self,
        specs: list[dict[str, Any]],
        T: float,
        *,
        default_vol: dict[str, float] | None = None,
        snapshot: MarketDataSnapshot | None = None,
        include_evidence: bool = False,
        min_vol_samples: int = 20,
        min_corr_samples: int = 20,
        _inside_read_snapshot: bool = False,
    ) -> tuple[list, "np.ndarray"] | tuple[list, "np.ndarray", dict[str, Any]]:
        """Resolve a basket against one immutable snapshot/as-of boundary.

        ``specs`` is a list of ``{"secid", "kind", "weight"}``. Spot, annualised vol
        and income (dividend yield for equities, carry/YTM for bonds) come from the
        market store. Historical observations strictly after the selected snapshot's
        ``valuation_date`` are excluded. Correlations use returns aligned by observation
        date (never by array tail length), with explicit defaults where aligned history
        is insufficient.

        The legacy two-value return contract is preserved. Set ``include_evidence`` to
        receive ``(constituents, correlation, evidence)``. The evidence contains the
        source/effective date/sample count/fallback reason for every resolved value,
        the exact canonical numerical inputs, and their deterministic SHA-256 hash.
        """
        from instruments.structured.basket_note import Constituent

        if not np.isfinite(float(T)) or float(T) <= 0:
            raise ValueError("basket maturity T must be positive and finite")
        if min_vol_samples < 2 or min_corr_samples < 2:
            raise ValueError("basket history sample thresholds must be at least 2")

        # A basket resolution spans snapshot tables, histories and dividends. Hold a
        # repeatable DB view so a concurrent ingest cannot produce a hybrid bundle.
        read_snapshot = getattr(self.market_db, "read_snapshot", None)
        if (self.market_db is not None and not _inside_read_snapshot
                and callable(read_snapshot)):
            with read_snapshot():
                return self.basket_market_inputs(
                    specs,
                    T,
                    default_vol=default_vol,
                    snapshot=snapshot,
                    include_evidence=include_evidence,
                    min_vol_samples=min_vol_samples,
                    min_corr_samples=min_corr_samples,
                    _inside_read_snapshot=True,
                )

        default_vol = default_vol or {"equity": 0.30, "index": 0.20, "bond": 0.07}
        demo = {u["secid"]: u for u in self._DEMO_UNIVERSE}
        context = self._basket_snapshot_context(snapshot)
        sid = context["snapshot_id"]
        as_of = date.fromisoformat(context["valuation_date"])

        constituents = []
        price_level_series: list[dict[date, float]] = []
        constituent_evidence: list[dict[str, Any]] = []
        for index, spec in enumerate(specs):
            secid = str(spec["secid"]).strip()
            if not secid:
                raise ValueError("basket constituent secid is required")
            kind = str(spec.get("kind", "equity")).lower()
            weight = float(spec.get("weight", 1.0))
            if not np.isfinite(weight):
                raise ValueError(f"basket weight for {secid} must be finite")
            spot, vol, income, levels, item_evidence = self._resolve_instrument_as_of(
                secid,
                kind,
                weight,
                sid,
                as_of,
                default_vol,
                demo,
                min_vol_samples,
            )
            constituents.append(Constituent(name=secid, kind=kind, spot=spot,
                                            weight=weight, vol=vol, income=income))
            price_level_series.append(levels)
            item_evidence["index"] = index
            constituent_evidence.append(item_evidence)

        corr, correlation_evidence = self._estimate_aligned_correlation(
            [c.name for c in constituents],
            [c.kind for c in constituents],
            price_level_series,
            as_of,
            min_corr_samples,
        )
        resolved_inputs = {
            "snapshot_id": context["snapshot_id"],
            "valuation_date": context["valuation_date"],
            "T": float(T),
            "constituents": [
                {
                    "name": c.name,
                    "kind": c.kind,
                    "spot": float(c.spot),
                    "weight": float(c.weight),
                    "vol": float(c.vol),
                    "income": float(c.income),
                }
                for c in constituents
            ],
            "correlation": corr.astype(float).tolist(),
        }
        canonical = json.dumps(
            resolved_inputs,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

        fallback_flags = []
        for item in constituent_evidence:
            label = f"constituents[{item['index']}]:{item['secid']}"
            for field in ("spot", "vol", "income"):
                detail = item[field]
                if detail["fallback"]:
                    fallback_flags.append(
                        f"{label}.{field}:{detail['source']}:{detail['reason']}"
                    )
        for pair in correlation_evidence["pairs"]:
            if pair["fallback"]:
                fallback_flags.append(
                    f"correlation[{pair['left_index']},{pair['right_index']}]:"
                    f"{pair['source']}:{pair['reason']}"
                )
        if context["fallback"]:
            fallback_flags.append(
                f"snapshot:{context['source']}:{context['reason']}"
            )

        evidence = {
            "schema_version": 1,
            "snapshot": context,
            "history_cutoff": as_of.isoformat(),
            "history_policy": {
                "returns": "log",
                "annualization": 252,
                "minimum_vol_samples": int(min_vol_samples),
                "minimum_correlation_samples": int(min_corr_samples),
                "correlation_alignment": "pairwise_date_intersection",
                "future_observations": "excluded",
            },
            "constituents": constituent_evidence,
            "correlation": correlation_evidence,
            "fallback_used": bool(fallback_flags),
            "fallback_flags": sorted(fallback_flags),
            "resolved_inputs": resolved_inputs,
            "resolved_inputs_hash": sha256(canonical.encode("utf-8")).hexdigest(),
        }
        if include_evidence:
            return constituents, corr, evidence
        return constituents, corr

    @staticmethod
    def _basket_day(value: Any) -> date:
        """Normalise an observation timestamp to its calendar day."""
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("empty observation date")
        try:
            return date.fromisoformat(raw) if len(raw) == 10 else datetime.fromisoformat(
                raw.replace("Z", "+00:00")
            ).date()
        except ValueError as exc:
            raise ValueError(f"invalid observation date: {raw}") from exc

    def _basket_snapshot_context(
        self, snapshot: MarketDataSnapshot | None,
    ) -> dict[str, Any]:
        """Resolve one authoritative snapshot identity without reading latest later."""
        if snapshot is not None:
            valuation_date = self._basket_day(snapshot.valuation_date)
            return {
                "snapshot_id": str(snapshot.snapshot_id),
                "valuation_date": valuation_date.isoformat(),
                "source": snapshot.source_value,
                "quality": str(snapshot.quality),
                "selection": "explicit",
                "fallback": False,
                "reason": "caller supplied governed snapshot",
            }

        meta = self.market_db.latest_snapshot_meta() if self.market_db is not None else None
        if meta:
            return {
                "snapshot_id": str(meta["snapshot_id"]),
                "valuation_date": self._basket_day(meta["valuation_date"]).isoformat(),
                "source": str(meta.get("source") or "UNKNOWN").upper(),
                "quality": str(meta.get("quality") or ""),
                "selection": "latest_market_db_snapshot",
                "fallback": False,
                "reason": "no explicit snapshot; selected latest stored snapshot once",
            }

        valuation_date = date.today()
        return {
            "snapshot_id": f"demo-{valuation_date.isoformat()}",
            "valuation_date": valuation_date.isoformat(),
            "source": MarketDataSource.DEMO.value,
            "quality": MarketDataSource.DEMO.value,
            "selection": "demo_fallback",
            "fallback": True,
            "reason": "no explicit or stored market-data snapshot",
        }

    def _price_history_as_of(
        self, secid: str, as_of: date,
    ) -> tuple[dict[date, float], dict[date, float], dict[str, int]]:
        """Positive price levels and dated log returns, strictly cut at ``as_of``."""
        levels: dict[date, float] = {}
        invalid = 0
        future = 0
        if self.market_db is not None:
            try:
                rows = self.market_db.get_time_series(f"{secid}:price", "price")
            except Exception:
                rows = []
                invalid += 1
            for row in rows:
                try:
                    observed = self._basket_day(row.get("dt"))
                    value = float(row.get("value"))
                except (TypeError, ValueError, OverflowError):
                    invalid += 1
                    continue
                if observed > as_of:
                    future += 1
                    continue
                if not np.isfinite(value) or value <= 0:
                    invalid += 1
                    continue
                levels[observed] = value

        ordered = sorted(levels.items())
        returns = {
            ordered[index][0]: float(np.log(ordered[index][1] / ordered[index - 1][1]))
            for index in range(1, len(ordered))
        }
        return levels, returns, {
            "level_count": len(levels),
            "return_count": len(returns),
            "future_observations_excluded": future,
            "invalid_observations_excluded": invalid,
        }

    @staticmethod
    def _fallback_detail(source: str, reason: str, *, effective_date=None,
                         sample_count: int = 0, **extra) -> dict[str, Any]:
        return {
            "source": source,
            "effective_date": effective_date,
            "sample_count": int(sample_count),
            "fallback": True,
            "reason": reason,
            **extra,
        }

    def _resolve_instrument_as_of(
        self,
        secid: str,
        kind: str,
        weight: float,
        sid: str,
        as_of: date,
        default_vol: dict[str, float],
        demo: dict[str, dict[str, Any]],
        min_vol_samples: int,
    ) -> tuple[float, float, float, dict[date, float], dict[str, Any]]:
        levels, returns, history_counts = self._price_history_as_of(secid, as_of)
        history_dates = sorted(levels)
        history_spot = levels[history_dates[-1]] if history_dates else None
        history_effective = history_dates[-1].isoformat() if history_dates else None
        demo_row = demo.get(secid)

        quote = None
        if kind == "bond":
            quote = self._bond_quote(secid, sid)

        spot = None
        spot_evidence = None
        if kind == "equity" and self.market_db is not None and sid:
            try:
                candidate = self.market_db.get_equity_spot(sid, secid)
                if candidate is not None and np.isfinite(float(candidate)) and float(candidate) > 0:
                    spot = float(candidate)
                    spot_evidence = {
                        "source": "equity_quotes",
                        "effective_date": as_of.isoformat(),
                        "sample_count": 1,
                        "fallback": False,
                        "reason": "quote belongs to selected snapshot",
                    }
            except Exception:
                spot = None
        elif kind == "bond" and quote:
            candidate = quote.get("clean_price")
            try:
                candidate = float(candidate)
            except (TypeError, ValueError, OverflowError):
                candidate = None
            if candidate is not None and np.isfinite(candidate) and candidate > 0:
                spot = candidate
                spot_evidence = {
                    "source": "bond_quotes",
                    "effective_date": as_of.isoformat(),
                    "sample_count": 1,
                    "fallback": False,
                    "reason": "quote belongs to selected snapshot",
                }

        if spot is None and history_spot is not None:
            spot = float(history_spot)
            spot_evidence = {
                "source": "time_series",
                "effective_date": history_effective,
                "sample_count": history_counts["level_count"],
                "fallback": False,
                "reason": "latest eligible price observation on or before snapshot",
            }
        if spot is None and demo_row:
            spot = float(demo_row["spot"])
            spot_evidence = self._fallback_detail(
                "demo_universe",
                "no eligible snapshot quote or as-of price history",
                effective_date=as_of.isoformat(),
            )
        if spot is None:
            spot = 100.0
            spot_evidence = self._fallback_detail(
                "generic_spot_default",
                "instrument has no eligible snapshot quote, history or demo value",
                effective_date=as_of.isoformat(),
            )

        return_dates = sorted(returns)
        return_values = np.array([returns[day] for day in return_dates], dtype=float)
        vol = None
        if return_values.size >= min_vol_samples:
            candidate = float(return_values.std(ddof=1) * np.sqrt(252))
            if np.isfinite(candidate) and candidate > 0:
                vol = candidate
        if vol is not None:
            vol_evidence = {
                "source": "time_series_log_returns",
                "effective_date": return_dates[-1].isoformat(),
                "start_date": return_dates[0].isoformat(),
                "end_date": return_dates[-1].isoformat(),
                "sample_count": int(return_values.size),
                "fallback": False,
                "reason": "annualised sample volatility from eligible history",
            }
        else:
            configured = float(
                demo_row.get("vol", default_vol.get(kind, 0.30))
                if demo_row else default_vol.get(kind, 0.30)
            )
            if not np.isfinite(configured) or configured <= 0:
                raise ValueError(f"default volatility for {secid} must be positive and finite")
            vol = configured
            reason = (
                f"only {return_values.size} eligible returns; minimum is {min_vol_samples}"
                if return_values.size < min_vol_samples
                else "eligible returns have zero or non-finite sample volatility"
            )
            vol_evidence = self._fallback_detail(
                "demo_volatility" if demo_row else "configured_default_volatility",
                reason,
                effective_date=as_of.isoformat(),
                sample_count=int(return_values.size),
                start_date=return_dates[0].isoformat() if return_dates else None,
                end_date=return_dates[-1].isoformat() if return_dates else None,
            )

        if kind == "equity":
            income, income_evidence = self._dividend_yield_as_of(secid, spot, as_of)
            if income_evidence["fallback"] and demo_row:
                income = float(demo_row.get("income", 0.0))
                income_evidence = self._fallback_detail(
                    "demo_income",
                    "no eligible trailing dividend history",
                    effective_date=as_of.isoformat(),
                )
        elif kind == "bond" and quote and quote.get("ytm") is not None:
            try:
                candidate = float(quote["ytm"])
            except (TypeError, ValueError, OverflowError):
                candidate = None
            if candidate is not None and np.isfinite(candidate):
                income = candidate
                income_evidence = {
                    "source": "bond_quote_ytm",
                    "effective_date": as_of.isoformat(),
                    "sample_count": 1,
                    "fallback": False,
                    "reason": "YTM belongs to selected snapshot bond quote",
                }
            else:
                income, income_evidence = self._default_income(kind, demo_row, as_of)
        else:
            income, income_evidence = self._default_income(kind, demo_row, as_of)

        spot_evidence["value"] = float(spot)
        vol_evidence["value"] = float(vol)
        income_evidence["value"] = float(income)
        evidence = {
            "secid": secid,
            "kind": kind,
            "weight": float(weight),
            "spot": spot_evidence,
            "vol": vol_evidence,
            "income": income_evidence,
            "history": {
                **history_counts,
                "cutoff": as_of.isoformat(),
                "first_level_date": history_dates[0].isoformat() if history_dates else None,
                "last_level_date": history_effective,
            },
        }
        return float(spot), float(vol), float(income), levels, evidence

    def _bond_quote(self, secid, sid):
        if self.market_db is None or sid is None:
            return None
        try:
            return self.market_db._query_one(
                f"SELECT clean_price, ytm FROM bond_quotes WHERE snapshot_id="
                f"{self.market_db.ph} AND secid={self.market_db.ph}", (sid, secid))
        except Exception:
            return None

    def _dividend_yield_as_of(
        self, secid: str, spot: float, as_of: date,
    ) -> tuple[float, dict[str, Any]]:
        """Trailing 12-month dividend yield with a strict snapshot cutoff."""
        if self.market_db is None or not spot:
            return 0.0, self._fallback_detail(
                "zero_income_default", "market database or valid spot is unavailable",
                effective_date=as_of.isoformat())
        try:
            divs = self.market_db.get_dividends(secid)
        except Exception:
            divs = []
        cutoff_start = as_of - timedelta(days=365)
        eligible: list[tuple[date, float]] = []
        invalid = 0
        future = 0
        stale = 0
        for row in divs:
            try:
                observed = self._basket_day(row.get("registry_date"))
                value = float(row.get("value"))
            except (TypeError, ValueError, OverflowError):
                invalid += 1
                continue
            if observed > as_of:
                future += 1
            elif observed < cutoff_start:
                stale += 1
            elif np.isfinite(value):
                eligible.append((observed, value))
            else:
                invalid += 1
        eligible.sort()
        if not eligible:
            return 0.0, self._fallback_detail(
                "zero_income_default",
                "no dividend observations in trailing 365 days at snapshot cutoff",
                effective_date=as_of.isoformat(),
                future_observations_excluded=future,
                stale_observations_excluded=stale,
                invalid_observations_excluded=invalid,
            )
        recent = sum(value for _, value in eligible)
        result = min(max(recent / spot, 0.0), 0.5)
        return float(result), {
            "source": "dividend_history_ttm",
            "effective_date": eligible[-1][0].isoformat(),
            "start_date": eligible[0][0].isoformat(),
            "end_date": eligible[-1][0].isoformat(),
            "sample_count": len(eligible),
            "fallback": False,
            "reason": "sum of trailing 365-day dividends divided by resolved spot",
            "future_observations_excluded": future,
            "stale_observations_excluded": stale,
            "invalid_observations_excluded": invalid,
        }

    def _default_income(
        self, kind: str, demo_row: dict[str, Any] | None, as_of: date,
    ) -> tuple[float, dict[str, Any]]:
        if demo_row:
            return float(demo_row.get("income", 0.0)), self._fallback_detail(
                "demo_income",
                f"no eligible snapshot {kind} income/carry input",
                effective_date=as_of.isoformat(),
            )
        return 0.0, self._fallback_detail(
            "zero_income_default",
            f"no eligible snapshot {kind} income/carry input",
            effective_date=as_of.isoformat(),
        )

    def _estimate_aligned_correlation(
        self,
        names: list[str],
        kinds: list[str],
        price_level_series: list[dict[date, float]],
        as_of: date,
        min_samples: int,
    ) -> tuple["np.ndarray", dict[str, Any]]:
        """Pairwise empirical correlation on exact return-date intersections."""
        n = len(names)
        corr = np.eye(n)
        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                # Intersect *price-level* dates first, then calculate both return
                # legs over the exact same intervals. Intersecting independently
                # calculated return end-dates can accidentally compare a one-day
                # return with a multi-day return when one factor has a missing day.
                shared_level_dates = sorted(
                    set(price_level_series[i]).intersection(price_level_series[j])
                )
                left_levels = np.array(
                    [price_level_series[i][day] for day in shared_level_dates], dtype=float
                )
                right_levels = np.array(
                    [price_level_series[j][day] for day in shared_level_dates], dtype=float
                )
                left = np.diff(np.log(left_levels))
                right = np.diff(np.log(right_levels))
                return_dates = shared_level_dates[1:]
                rho = None
                reason = ""
                if left.size >= min_samples:
                    c = np.corrcoef(left, right)[0, 1]
                    if np.isfinite(c):
                        rho = float(np.clip(c, -0.95, 0.95))
                    else:
                        reason = "aligned returns have zero or non-finite variance"
                else:
                    reason = (
                        f"only {left.size} aligned returns; minimum is {min_samples}"
                    )
                if rho is None:
                    same = kinds[i] == kinds[j]
                    rho = (0.5 if same and kinds[i] != "bond"
                           else 0.6 if same else 0.2)
                    source = "configured_asset_class_default"
                    fallback = True
                else:
                    source = "aligned_time_series_log_returns"
                    fallback = False
                    reason = "Pearson correlation on exact return-date intersection"
                corr[i, j] = corr[j, i] = rho
                pairs.append({
                    "left_index": i,
                    "right_index": j,
                    "left": names[i],
                    "right": names[j],
                    "value": float(rho),
                    "source": source,
                    "effective_date": return_dates[-1].isoformat() if return_dates else None,
                    "start_date": return_dates[0].isoformat() if return_dates else None,
                    "end_date": return_dates[-1].isoformat() if return_dates else None,
                    "sample_count": int(left.size),
                    "aligned_level_count": len(shared_level_dates),
                    "fallback": fallback,
                    "reason": reason,
                    "cutoff": as_of.isoformat(),
                })
        return corr, {
            "method": "pearson_log_returns_from_pairwise_aligned_price_levels",
            "matrix": corr.astype(float).tolist(),
            "sample_count": min((pair["sample_count"] for pair in pairs), default=0),
            "fallback": any(pair["fallback"] for pair in pairs),
            "pairs": pairs,
        }

    def historical_correlation(
        self,
        factor_ids: list[str],
        *,
        as_of: date | None = None,
        lookback: int = 252,
        method: str = "pearson",
        decay: float = 0.97,
        min_samples: int = 20,
        fallback_policy: str = "error",
        prior_matrix: list[list[float]] | None = None,
    ) -> dict[str, Any]:
        """Calibrate a correlation matrix from aligned stored price history.

        Unlike the legacy basket resolver (which always uses the full history
        available before the snapshot), this explicit calibration API supports
        a bounded lookback and exponentially weighted covariance.  The returned
        evidence records the exact pairwise windows and the matrix adjustment,
        making the result suitable for a reproducible pricing attachment.
        """
        if isinstance(factor_ids, (str, bytes)) or not isinstance(
                factor_ids, (list, tuple)):
            raise ValueError("factor_ids must be a sequence of factor ids")
        names = [str(item).strip() for item in factor_ids]
        if not names or any(not item for item in names):
            raise ValueError("factor_ids must contain at least one non-empty id")
        if len(names) > 50:
            raise ValueError("factor_ids supports at most 50 factors")
        if len(set(names)) != len(names):
            raise ValueError("factor_ids must be unique")
        if isinstance(lookback, bool) or int(lookback) != lookback or not 2 <= int(lookback) <= 10_000:
            raise ValueError("lookback must be an integer in [2, 10000]")
        lookback = int(lookback)
        method = str(method).lower()
        if method not in {"pearson", "ewma"}:
            raise ValueError("method must be 'pearson' or 'ewma'")
        if not np.isfinite(float(decay)) or not 0.0 < float(decay) < 1.0:
            raise ValueError("decay must be in (0, 1)")
        if isinstance(min_samples, bool) or int(min_samples) != min_samples or int(min_samples) < 2:
            raise ValueError("min_samples must be an integer >= 2")
        min_samples = int(min_samples)
        if min_samples > lookback:
            raise ValueError("min_samples must not exceed lookback")
        fallback_policy = str(fallback_policy).strip().lower()
        if fallback_policy not in {"error", "prior"}:
            raise ValueError("fallback_policy must be 'error' or 'prior'")
        cutoff = self._basket_day(as_of or date.today())
        prior = None
        if fallback_policy == "prior":
            try:
                prior = np.asarray(prior_matrix, dtype=float)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("prior_matrix must be numeric") from exc
            if (prior.shape != (len(names), len(names))
                    or not np.all(np.isfinite(prior))
                    or not np.allclose(prior, prior.T, atol=1e-12, rtol=0.0)
                    or not np.allclose(np.diag(prior), 1.0, atol=1e-12, rtol=0.0)
                    or np.any(np.abs(prior) > 1.0)):
                raise ValueError("prior_matrix is not a valid correlation matrix")

        supported_kinds = {"price", "fix", "yield", "rate"}
        levels: list[dict[date, float]] = []
        series_evidence: list[dict[str, Any]] = []
        transforms: list[str] = []
        for token in names:
            head, separator, suffix = token.rpartition(":")
            if separator and head and suffix.lower() in supported_kinds:
                factor_id, kind = token, suffix.lower()
            else:
                factor_id, kind = f"{token}:price", "price"
            factor_levels: dict[date, float] = {}
            invalid = future = 0
            if factor_id == f"{token}:price":
                factor_levels, _unused_returns, quality = (
                    self._price_history_as_of(token, cutoff))
                invalid = int(quality.get("invalid_observations_excluded", 0))
                future = int(quality.get("future_observations_excluded", 0))
            else:
                rows = []
                if self.market_db is not None:
                    try:
                        rows = self.market_db.get_time_series(factor_id, kind)
                    except Exception:
                        invalid += 1
                for row in rows:
                    try:
                        observed = self._basket_day(row.get("dt"))
                        value = float(row.get("value"))
                    except (TypeError, ValueError, OverflowError):
                        invalid += 1
                        continue
                    if observed > cutoff:
                        future += 1
                        continue
                    if (not np.isfinite(value)
                            or (kind in {"price", "fix"} and value <= 0.0)):
                        invalid += 1
                        continue
                    factor_levels[observed] = value
            transform = "log_return" if kind in {"price", "fix"} else "absolute_change"
            canonical_levels = [
                (day.isoformat(), float(value))
                for day, value in sorted(factor_levels.items())
            ]
            levels.append(factor_levels)
            transforms.append(transform)
            series_evidence.append({
                "requested_id": token,
                "factor_id": factor_id,
                "kind": kind,
                "transform": transform,
                "level_count": len(factor_levels),
                "future_observations_excluded": future,
                "invalid_observations_excluded": invalid,
                "first_date": canonical_levels[0][0] if canonical_levels else None,
                "last_date": canonical_levels[-1][0] if canonical_levels else None,
                "series_hash": sha256(json.dumps(
                    canonical_levels, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False,
                ).encode("utf-8")).hexdigest(),
            })
        matrix = np.eye(len(names), dtype=float)
        pairs: list[dict[str, Any]] = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                shared = sorted(set(levels[i]).intersection(levels[j]))[-(lookback + 1):]
                left_levels = np.asarray([levels[i][d] for d in shared], dtype=float)
                right_levels = np.asarray([levels[j][d] for d in shared], dtype=float)
                calendar_days = np.asarray([
                    max((cur - prev).days, 1)
                    for prev, cur in zip(shared, shared[1:])
                ], dtype=float)
                left = (np.diff(np.log(left_levels))
                        if transforms[i] == "log_return"
                        else np.diff(left_levels)) / np.sqrt(calendar_days)
                right = (np.diff(np.log(right_levels))
                         if transforms[j] == "log_return"
                         else np.diff(right_levels)) / np.sqrt(calendar_days)
                rho = None
                reason = ""
                effective_sample_size = float(left.size)
                if left.size >= min_samples:
                    left_variance = float(np.var(left))
                    right_variance = float(np.var(right))
                    if (not np.isfinite(left_variance)
                            or not np.isfinite(right_variance)
                            or left_variance <= 1e-24
                            or right_variance <= 1e-24):
                        value = np.nan
                        reason = "zero_or_nonfinite_variance"
                    elif method == "pearson":
                        value = float(np.corrcoef(left, right)[0, 1])
                    else:
                        weights = float(decay) ** np.arange(left.size - 1, -1, -1)
                        weights /= weights.sum()
                        effective_sample_size = float(1.0 / np.sum(weights ** 2))
                        lm = float(np.dot(weights, left)); rm = float(np.dot(weights, right))
                        cov = float(np.dot(weights, (left - lm) * (right - rm)))
                        lv = float(np.dot(weights, (left - lm) ** 2))
                        rv = float(np.dot(weights, (right - rm) ** 2))
                        value = cov / np.sqrt(lv * rv) if lv > 0 and rv > 0 else np.nan
                    if np.isfinite(value):
                        rho = float(np.clip(value, -0.999, 0.999))
                    elif not reason:
                        reason = "zero_or_nonfinite_weighted_variance"
                else:
                    reason = "insufficient_samples"
                fallback = rho is None
                if fallback:
                    if fallback_policy == "error":
                        raise ValueError(
                            f"correlation {names[i]}/{names[j]} cannot be "
                            f"calibrated: {reason} (samples={left.size})")
                    rho = float(prior[i, j])
                matrix[i, j] = matrix[j, i] = rho
                pairs.append({
                    "left": names[i], "right": names[j],
                    "value": float(matrix[i, j]), "sample_count": int(left.size),
                    "aligned_level_count": len(shared),
                    "start_date": shared[1].isoformat() if len(shared) > 1 else None,
                    "end_date": shared[-1].isoformat() if len(shared) > 1 else None,
                    "max_calendar_gap_days": int(calendar_days.max())
                    if calendar_days.size else None,
                    "gap_normalization": "change_divided_by_sqrt_calendar_days",
                    "effective_sample_size": effective_sample_size,
                    "fallback": fallback,
                    "fallback_source": "prior_matrix" if fallback else None,
                    "reason": reason if fallback else "calibrated",
                })
        # Numerical projection keeps the matrix usable by Cholesky-based MC.
        from instruments.structured.basket_note import nearest_correlation
        adjusted = nearest_correlation(matrix)
        raw_min_eigenvalue = float(np.linalg.eigvalsh(matrix).min())
        adjusted_min_eigenvalue = float(np.linalg.eigvalsh(adjusted).min())
        for pair in pairs:
            i = names.index(pair["left"]); j = names.index(pair["right"])
            pair["adjusted_value"] = float(adjusted[i, j])
        adjustment = float(np.linalg.norm(adjusted - matrix, ord="fro"))
        matrix_hash = sha256(json.dumps(
            adjusted.tolist(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")).hexdigest()
        return {
            "factor_ids": names,
            "as_of": cutoff.isoformat(),
            "lookback": lookback,
            "method": method,
            "decay": float(decay),
            "min_samples": int(min_samples),
            "fallback_policy": fallback_policy,
            "raw_matrix": matrix.tolist(),
            "matrix": adjusted.tolist(),
            "matrix_hash": matrix_hash,
            "adjustment_frobenius": adjustment,
            "raw_min_eigenvalue": raw_min_eigenvalue,
            "adjusted_min_eigenvalue": adjusted_min_eigenvalue,
            "adjustment_material": adjustment > 0.05,
            "pairs": pairs,
            "series": series_evidence,
            "fallback": any(item["fallback"] for item in pairs),
        }

    def get_fx_rate(self, pair: str, snapshot: MarketDataSnapshot | None = None) -> float:
        snapshot = snapshot or self.demo_snapshot()
        return snapshot.fx_rates[pair]

    def get_vol_surface(self, surface_id: str, snapshot: MarketDataSnapshot | None = None) -> Any:
        snapshot = snapshot or self.demo_snapshot()
        surface = snapshot.vol_surfaces[surface_id]
        # Raw listed-option grids ({UND}_FORTS) carry only points + a single
        # median vol. Lazily upgrade them to a SABR-calibrated, interpolated
        # surface so pricing/risk get a real smile + term structure instead of a
        # flat median. Cached on the surface dict; falls back to the raw dict when
        # the points are too thin to calibrate.
        if isinstance(surface, dict) and surface.get("type") == "grid" and surface.get("points"):
            cached = surface.get("_calibrated")
            if cached is None:
                from risk.vol_surface import calibrated_surface_from_points
                cached = calibrated_surface_from_points(
                    surface["points"], snapshot.valuation_date, label=surface_id) or surface
                surface["_calibrated"] = cached
            return cached
        return surface

    def get_commodity_curve(self, asset: str,
                            snapshot: MarketDataSnapshot | None = None) -> dict:
        """Real commodity futures strip {time_to_expiry_years: settle} from the
        market store (commodity_quotes). Empty if no DB / no quotes. Feeds the
        Schwartz-Smith / Gibson-Schwartz models on live MOEX-FORTS futures."""
        snapshot = snapshot or self.best_available_snapshot()
        if self.market_db is None:
            return {}
        from datetime import date as _date
        rows = self.market_db.get_commodity_quotes(snapshot.snapshot_id, asset)
        val = snapshot.valuation_date
        out = {}
        for q in rows:
            try:
                exp = _date.fromisoformat(str(q["expiry"]))
                T = (exp - val).days / 365.0
                if T > 0 and q.get("settle"):
                    out[round(T, 6)] = float(q["settle"])
            except (ValueError, KeyError, TypeError):
                continue
        return dict(sorted(out.items()))

    def get_option_smile(self, underlying: str, expiry: str | None = None,
                         snapshot: MarketDataSnapshot | None = None) -> dict:
        """One expiry's smile from the live FORTS surface {UND}_FORTS: strikes,
        implied vols, time-to-expiry and an ATM-forward estimate. Feeds SABR /
        Heston / local-vol calibration on real MOEX option data."""
        from infra.moex_iss.options_surface import (smile_at_expiry, year_fraction,
                                                    clean_smile)
        snapshot = snapshot or self.best_available_snapshot()
        surf = snapshot.vol_surfaces.get(f"{underlying}_FORTS")
        if not surf:
            return {}
        sm = smile_at_expiry(surf, expiry)
        if not sm or len(sm.get("strikes", [])) < 3:
            return {}
        # self-implied FORTS smiles carry illiquid deep-OTM garbage → clean first
        strikes, ivs, fwd = clean_smile(sm["strikes"], sm["ivs"])
        if len(strikes) < 5:
            return {}
        sm["strikes"], sm["ivs"], sm["forward"] = strikes, ivs, fwd
        sm["T"] = year_fraction(sm["expiry"], snapshot.valuation_date)
        return sm

    def get_fx_rr_bf(self, asset: str, expiry: str | None = None,
                     snapshot: MarketDataSnapshot | None = None) -> dict:
        """25Δ ATM / risk-reversal / butterfly from the live FX option smile
        (asset = Si, CNY, Eu). Feeds the Vanna-Volga model on real data."""
        from infra.moex_iss.options_surface import rr_bf_25delta
        sm = self.get_option_smile(asset, expiry, snapshot)
        if not sm:
            return {}
        rb = rr_bf_25delta(sm, sm["T"], sm["forward"])
        rb["expiry"], rb["T"] = sm["expiry"], sm["T"]
        return rb

    def get_credit_curve(self, curve_id: str, snapshot: MarketDataSnapshot | None = None) -> Any:
        snapshot = snapshot or self.demo_snapshot()
        return snapshot.credit_curves[curve_id]

    def get_credit_spread(self, spread_id: str, snapshot: MarketDataSnapshot | None = None) -> float:
        snapshot = snapshot or self.demo_snapshot()
        return snapshot.credit_spreads[spread_id]
