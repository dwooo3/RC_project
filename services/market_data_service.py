"""Market data platform service."""

import json
from datetime import date, datetime
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
    ) -> tuple[list, "np.ndarray"]:
        """Resolve chosen basket members to (constituents, correlation matrix).

        ``specs`` is a list of ``{"secid", "kind", "weight"}``. Spot, annualised vol
        and income (dividend yield for equities, carry/YTM for bonds) come from the
        market store; the correlation matrix is estimated from overlapping log-return
        history, with sensible defaults where history is missing. Everything degrades
        gracefully to defaults in demo mode.
        """
        from instruments.structured.basket_note import Constituent

        default_vol = default_vol or {"equity": 0.30, "index": 0.20, "bond": 0.07}
        demo = {u["secid"]: u for u in self._DEMO_UNIVERSE}
        meta = self.market_db.latest_snapshot_meta() if self.market_db else None
        sid = meta["snapshot_id"] if meta else None

        constituents = []
        returns: dict[str, np.ndarray] = {}
        for spec in specs:
            secid = spec["secid"]
            kind = spec.get("kind", "equity")
            weight = float(spec.get("weight", 1.0))
            spot, vol, income = self._resolve_instrument(secid, kind, sid, default_vol, demo, returns)
            constituents.append(Constituent(name=secid, kind=kind, spot=spot,
                                            weight=weight, vol=vol, income=income))

        corr = self._estimate_correlation([c.name for c in constituents],
                                          [c.kind for c in constituents], returns)
        return constituents, corr

    def _resolve_instrument(self, secid, kind, sid, default_vol, demo, returns):
        """Spot / vol / income for one instrument, recording its return series."""
        spot = None
        income = 0.0
        vol = default_vol.get(kind, 0.30)

        series = None
        if self.market_db is not None:
            try:
                rows = self.market_db.get_time_series(f"{secid}:price", "price")
                prices = np.array([r["value"] for r in rows if r.get("value")], dtype=float)
                if prices.size >= 2 and np.all(prices > 0):
                    series = np.diff(np.log(prices))
                    spot = float(prices[-1])
                    vol = float(series.std(ddof=1) * np.sqrt(252)) or vol
            except Exception:
                series = None

        if kind == "equity":
            if spot is None and sid is not None:
                try:
                    spot = self.market_db.get_equity_spot(sid, secid)
                except Exception:
                    spot = None
            income = self._dividend_yield(secid, spot)
        elif kind == "bond":
            b = self._bond_quote(secid, sid)
            if b:
                spot = spot if spot is not None else b.get("clean_price") or 100.0
                income = float(b.get("ytm") or 0.0)
            else:
                spot = spot if spot is not None else 100.0

        if spot is None or spot <= 0:
            d = demo.get(secid)
            spot = (d["spot"] if d else 100.0)
            if d:
                vol = d.get("vol", vol)
                income = d.get("income", income)
        if series is not None:
            returns[secid] = series
        return float(spot), float(vol), float(income)

    def _bond_quote(self, secid, sid):
        if self.market_db is None or sid is None:
            return None
        try:
            return self.market_db._query_one(
                f"SELECT clean_price, ytm FROM bond_quotes WHERE snapshot_id="
                f"{self.market_db.ph} AND secid={self.market_db.ph}", (sid, secid))
        except Exception:
            return None

    def _dividend_yield(self, secid, spot):
        """Trailing 12-month dividend yield from the dividend history, else 0."""
        if self.market_db is None or not spot:
            return 0.0
        try:
            divs = self.market_db.get_dividends(secid)
        except Exception:
            return 0.0
        if not divs:
            return 0.0
        amounts = sorted((d for d in divs if d.get("value")), key=lambda d: d.get("dt", ""))
        recent = sum(float(d["value"]) for d in amounts[-2:])  # ~last year of payouts
        return min(recent / spot, 0.5) if spot else 0.0

    def _estimate_correlation(self, names, kinds, returns) -> "np.ndarray":
        """Pairwise correlation from overlapping return history; defaults elsewhere."""
        n = len(names)
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                ri, rj = returns.get(names[i]), returns.get(names[j])
                rho = None
                if ri is not None and rj is not None:
                    m = min(ri.size, rj.size)
                    if m >= 20:
                        c = np.corrcoef(ri[-m:], rj[-m:])[0, 1]
                        if np.isfinite(c):
                            rho = float(np.clip(c, -0.95, 0.95))
                if rho is None:
                    same = kinds[i] == kinds[j]
                    rho = (0.5 if same and kinds[i] != "bond"
                           else 0.6 if same else 0.2)
                corr[i, j] = corr[j, i] = rho
        return corr

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
