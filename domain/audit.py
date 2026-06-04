"""Audit and reproducibility contracts."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AuditRecord:
    """Base audit event for user-visible workflow actions."""

    record_id: str
    user_action: str
    timestamp: datetime = field(default_factory=_utc_now)
    user_id: str = "system"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalculationRecord(AuditRecord):
    """Reproducibility record for a service calculation."""

    calculation_type: str = ""
    model_id: str = ""
    model_version: str = ""
    market_data_snapshot_id: str = ""
    inputs_hash: str = ""
    result_id: str = ""

    @property
    def snapshot_id(self) -> str:
        return self.market_data_snapshot_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "calculation_id": self.record_id,
            "user_action": self.user_action,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "calculation_type": self.calculation_type,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "snapshot_id": self.market_data_snapshot_id,
            "market_data_snapshot_id": self.market_data_snapshot_id,
            "inputs_hash": self.inputs_hash,
            "result_id": self.result_id,
            "details": dict(self.details),
        }
