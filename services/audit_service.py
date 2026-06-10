"""In-memory audit foundation for reproducible calculations."""

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from domain.audit import AuditRecord, CalculationRecord


class AuditService:
    """Owns audit records and deterministic input hashing.

    Pass an AppDB (infra.db.app_db) as `db` to persist every record; in-memory
    behaviour is unchanged when db is None (Phase 4).
    """

    def __init__(self, db=None):
        self._records: list[AuditRecord] = []
        self.db = db

    @property
    def records(self) -> list[AuditRecord]:
        return list(self._records)

    def record_calculation(
        self,
        *,
        user_action: str,
        calculation_type: str,
        model_id: str,
        model_version: str,
        market_data_snapshot_id: str = "",
        inputs: Any = None,
        user_id: str = "system",
        result_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> CalculationRecord:
        inputs_hash = self.hash_inputs(inputs)
        record = CalculationRecord(
            record_id=f"calc_{uuid4().hex}",
            user_action=user_action,
            user_id=user_id,
            calculation_type=calculation_type,
            model_id=model_id,
            model_version=model_version,
            market_data_snapshot_id=market_data_snapshot_id,
            inputs_hash=inputs_hash,
            result_id=result_id,
            details=details or {},
        )
        self._records.append(record)
        if self.db is not None:
            try:
                self.db.save_audit_record(record)
            except Exception:
                record.details.setdefault("warnings", []).append(
                    "Audit record could not be persisted to AppDB.")
        return record

    def hash_inputs(self, inputs: Any) -> str:
        payload = self._normalize(inputs)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(encoded.encode("utf-8")).hexdigest()

    def audit_trail(self) -> list[dict[str, Any]]:
        return [
            record.as_dict() if hasattr(record, "as_dict") else asdict(record)
            for record in self._records
        ]

    def _normalize(self, value: Any) -> Any:
        if is_dataclass(value):
            return self._normalize(asdict(value))
        if isinstance(value, dict):
            return {str(key): self._normalize(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, (list, tuple)):
            return [self._normalize(item) for item in value]
        if isinstance(value, set):
            return sorted(self._normalize(item) for item in value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if hasattr(value, "tolist"):
            return self._normalize(value.tolist())
        if hasattr(value, "item"):
            return self._normalize(value.item())
        if hasattr(value, "value"):
            return value.value
        return value
