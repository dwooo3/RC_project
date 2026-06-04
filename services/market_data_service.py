"""Market data platform service."""

from datetime import date
from typing import Any, Protocol

from curves import russia
from curves.yield_curve import YieldCurve
from domain.market_data import MarketDataSnapshot, MarketDataSource, MarketDataStore
from infra.moex_iss.validation import (
    QUALITY_REJECTED, assess_quality, validate_curve_points, validate_fx,
)


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
    derives a quality verdict, persists snapshot lineage metadata, and returns a
    MarketDataSnapshot(source=MOEX). REJECTED data raises so the service falls
    back to DEMO (it must not feed production valuations). Without a DB the
    provider stays a no-op (NotImplementedError -> DEMO fallback)."""

    source = MarketDataSource.MOEX

    def __init__(self, db=None):
        self.db = db

    def load_snapshot(self, valuation_date: date | None = None, *, db=None, **kwargs) -> MarketDataSnapshot:
        from datetime import datetime, date as _date

        db = db or self.db
        if db is None:
            raise NotImplementedError("MOEX provider requires a local market-data DB")
        valuation_date = valuation_date or _date.today()
        snapshot_id = f"moex-{valuation_date.isoformat()}"

        curve_ids = db.list_curve_ids(snapshot_id)
        if not curve_ids:
            raise KeyError(f"No MOEX market data ingested for {snapshot_id}")

        curves: dict[str, YieldCurve] = {}
        curve_errors: list[str] = []
        as_of: _date | None = None
        for curve_id in curve_ids:
            points = db.get_curve_points(snapshot_id, curve_id)
            triples = [(p["tenor"], p["zero_rate"], p["discount_factor"]) for p in points]
            errs = validate_curve_points(triples)
            curve_errors.extend(f"{curve_id}: {e}" for e in errs)
            if not errs:
                curves[curve_id] = YieldCurve(
                    [p["tenor"] for p in points],
                    [p["zero_rate"] for p in points],
                    label=curve_id,
                    interp="cubic" if len(points) >= 3 else "linear",
                    source=MarketDataSource.MOEX,
                    valuation_date=valuation_date,
                    rate_type="zero",
                    metadata={"source": "MOEX"},
                )
            meta = db.get_curve(snapshot_id, curve_id)
            if meta and meta.get("as_of") and as_of is None:
                try:
                    as_of = _date.fromisoformat(str(meta["as_of"])[:10])
                except ValueError:
                    as_of = None

        fx_rates = db.get_fx_rates(snapshot_id)
        fx_errors = validate_fx(fx_rates)

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

        meta_row = db.get_snapshot_meta(snapshot_id) or {}
        iss_urls = []
        metadata = {
            "quality_warnings": warnings,
            "iss_request_urls": iss_urls,
            "trade_date": as_of.isoformat() if as_of else "",
        }
        if warnings:
            metadata["warning"] = "; ".join(warnings)
        db.save_snapshot_meta(
            snapshot_id=snapshot_id, valuation_date=valuation_date,
            source=MarketDataSource.MOEX.value, quality=quality,
            fetch_ts=datetime.now(), iss_request_urls=iss_urls, metadata=metadata,
        )
        return MarketDataSnapshot(
            snapshot_id=snapshot_id,
            valuation_date=valuation_date,
            source=MarketDataSource.MOEX,
            quality=quality,
            curves=curves,
            fx_rates=fx_rates,
            source_details={"provider": "MOEX ISS", "trade_date": metadata["trade_date"]},
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
    ):
        self.store = store or MarketDataStore()
        self.market_db = market_db
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
        }
        return self.create_snapshot(
            snapshot_id=f"demo-{valuation_date.isoformat()}",
            valuation_date=valuation_date,
            source=MarketDataSource.DEMO,
            curves=curves,
            fx_rates={"USD/RUB": 90.0, "EUR/RUB": 98.0},
            vol_surfaces={"equity_flat_demo": {"type": "flat", "vol": 0.20}},
            credit_spreads={"corp_1t": 0.0100, "corp_hy": 0.0300},
            credit_curves={
                "corp_1t_demo": {"base_curve_id": "ofz_demo", "spread": 0.0100},
                "corp_hy_demo": {"base_curve_id": "ofz_demo", "spread": 0.0300},
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

    def moex_snapshot(
        self,
        valuation_date: date | None = None,
        *,
        fallback_to_demo: bool = True,
    ) -> MarketDataSnapshot:
        """
        Return a production MOEX snapshot from the local DB, or fall back to the
        DEMO snapshot (with its 'Not production valuation' warning) when MOEX
        data is unavailable / rejected. Never raises under fallback.
        """
        try:
            return self.load_provider_snapshot(MarketDataSource.MOEX, valuation_date)
        except Exception:
            if not fallback_to_demo:
                raise
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

    def get_fx_rate(self, pair: str, snapshot: MarketDataSnapshot | None = None) -> float:
        snapshot = snapshot or self.demo_snapshot()
        return snapshot.fx_rates[pair]

    def get_vol_surface(self, surface_id: str, snapshot: MarketDataSnapshot | None = None) -> Any:
        snapshot = snapshot or self.demo_snapshot()
        return snapshot.vol_surfaces[surface_id]

    def get_credit_curve(self, curve_id: str, snapshot: MarketDataSnapshot | None = None) -> Any:
        snapshot = snapshot or self.demo_snapshot()
        return snapshot.credit_curves[curve_id]

    def get_credit_spread(self, spread_id: str, snapshot: MarketDataSnapshot | None = None) -> float:
        snapshot = snapshot or self.demo_snapshot()
        return snapshot.credit_spreads[spread_id]
