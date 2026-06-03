"""Market data service skeleton."""

from datetime import date

from curves.yield_curve import YieldCurve
from domain.market_data import MarketDataSnapshot


class MarketDataService:
    """Create governed market data snapshots from existing demo sources."""

    def demo_snapshot(self, valuation_date: date | None = None) -> MarketDataSnapshot:
        valuation_date = valuation_date or date.today()
        return MarketDataSnapshot(
            snapshot_id=f"demo-{valuation_date.isoformat()}",
            valuation_date=valuation_date,
            source="Demo / Manual",
            quality="demo",
            curves={"flat_rub": YieldCurve.flat(0.10, label="Demo RUB flat")},
            metadata={"warning": "Demo/manual market data. Not production valuation."},
        )

    def get_curve(
        self,
        curve_id: str = "flat_rub",
        snapshot: MarketDataSnapshot | None = None,
    ) -> YieldCurve:
        snapshot = snapshot or self.demo_snapshot()
        return snapshot.curves[curve_id]
