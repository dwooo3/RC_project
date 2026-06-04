"""Market data domain objects.

These contracts make demo/manual data explicit without changing existing
pricing engines yet.
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any


class MarketDataSource(str, Enum):
    DEMO = "DEMO"
    MANUAL = "MANUAL"
    CSV = "CSV"
    MOEX = "MOEX"
    BLOOMBERG = "BLOOMBERG"
    REUTERS = "REUTERS"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class MarketDataSnapshot:
    """Consistent market data set for one valuation date."""

    snapshot_id: str
    valuation_date: date
    source: MarketDataSource | str
    quality: str = MarketDataSource.DEMO.value
    version: int = 1
    created_at: datetime = field(default_factory=_utc_now)
    created_by: str = "MarketDataService"
    parent_snapshot_id: str = ""
    curves: dict[str, Any] = field(default_factory=dict)
    vol_surfaces: dict[str, Any] = field(default_factory=dict)
    fx_rates: dict[str, float] = field(default_factory=dict)
    credit_curves: dict[str, Any] = field(default_factory=dict)
    credit_spreads: dict[str, float] = field(default_factory=dict)
    source_details: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.version < 1:
            raise ValueError("market data snapshot version must be positive")
        if self.created_at.tzinfo is None:
            raise ValueError("market data snapshot created_at must be timezone-aware")
        if not self.snapshot_id:
            raise ValueError("market data snapshot_id is required")

    @property
    def source_value(self) -> str:
        return self.source.value if isinstance(self.source, MarketDataSource) else str(self.source).upper()

    @property
    def is_demo(self) -> bool:
        return self.quality.upper() in {
            MarketDataSource.DEMO.value,
            MarketDataSource.MANUAL.value,
        }

    def next_version(self) -> "MarketDataSnapshot":
        """Return a copy with incremented version and timestamp."""
        return replace(self, version=self.version + 1, created_at=_utc_now())


class MarketDataStore:
    """In-memory market data snapshot store with version ownership."""

    def __init__(self):
        self._snapshots: dict[str, list[MarketDataSnapshot]] = {}

    def save(self, snapshot: MarketDataSnapshot) -> MarketDataSnapshot:
        versions = self._snapshots.setdefault(snapshot.snapshot_id, [])
        if any(existing.version == snapshot.version for existing in versions):
            snapshot = replace(
                snapshot,
                version=max(existing.version for existing in versions) + 1,
                parent_snapshot_id=snapshot.parent_snapshot_id or snapshot.snapshot_id,
                created_at=_utc_now(),
            )
        versions.append(snapshot)
        versions.sort(key=lambda item: item.version)
        return snapshot

    def get(self, snapshot_id: str, version: int | None = None) -> MarketDataSnapshot:
        versions = self._snapshots.get(snapshot_id)
        if not versions:
            raise KeyError(f"Market data snapshot not found: {snapshot_id}")
        if version is None:
            return versions[-1]
        for snapshot in versions:
            if snapshot.version == version:
                return snapshot
        raise KeyError(f"Market data snapshot not found: {snapshot_id} v{version}")

    def list_versions(self, snapshot_id: str) -> list[MarketDataSnapshot]:
        return list(self._snapshots.get(snapshot_id, []))

    def latest(self) -> MarketDataSnapshot:
        snapshots = [versions[-1] for versions in self._snapshots.values() if versions]
        if not snapshots:
            raise KeyError("No market data snapshots are stored")
        return max(snapshots, key=lambda item: item.created_at)

    def list_by_source(self, source: MarketDataSource | str) -> list[MarketDataSnapshot]:
        source_value = source.value if isinstance(source, MarketDataSource) else str(source).upper()
        return [
            snapshot
            for versions in self._snapshots.values()
            for snapshot in versions
            if snapshot.source_value == source_value
        ]
