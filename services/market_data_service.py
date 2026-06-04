"""Market data service skeleton."""

from datetime import date

from curves import russia
from curves.yield_curve import YieldCurve
from domain.market_data import MarketDataSnapshot, MarketDataSource


class MarketDataService:
    """Create governed market data snapshots from existing demo sources."""

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
        return MarketDataSnapshot(
            snapshot_id=f"demo-{valuation_date.isoformat()}",
            valuation_date=valuation_date,
            source=MarketDataSource.DEMO,
            quality=MarketDataSource.DEMO.value,
            curves=curves,
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
        valuation_date = valuation_date or date.today()
        source_value = source.value if isinstance(source, MarketDataSource) else str(source).upper()
        return MarketDataSnapshot(
            snapshot_id=snapshot_id,
            valuation_date=valuation_date,
            source=source,
            quality=quality or source_value,
            curves=curves,
            metadata=metadata or {},
        )

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
