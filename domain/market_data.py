"""Market data domain objects.

These contracts make demo/manual data explicit without changing existing
pricing engines yet.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class MarketDataSnapshot:
    """Consistent market data set for one valuation date."""

    snapshot_id: str
    valuation_date: date
    source: str
    quality: str = "demo"
    curves: dict[str, Any] = field(default_factory=dict)
    vol_surfaces: dict[str, Any] = field(default_factory=dict)
    fx_rates: dict[str, float] = field(default_factory=dict)
    credit_spreads: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_demo(self) -> bool:
        return self.quality.lower() in {"demo", "manual"}
