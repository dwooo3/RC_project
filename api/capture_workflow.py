"""Phase 5: approval evidence + atomic trade capture (spec §17, §20).

Capture is allowed ONLY for the exact completed run the user is looking at:
the server reprices the request on its frozen context and compares the
authoritative inputs_hash with the one the client captured against — any
drift is a 409 conflict, never a silent recapture. When policy demands it
(large quantity), capture additionally requires an approval record for the
SAME inputs_hash from a different user (maker≠checker). Research results
never capture (§20). Position insertion + book repricing are atomic: a
failing book reprice rolls the position back.

No FastAPI imports — the whole workflow is plain Python for the CI suite;
HTTP wiring lives in api/server.py.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile


class CaptureError(ValueError):
    """Structured capture failure: code + HTTP status the API layer maps."""

    def __init__(self, code: str, message: str, status: int = 400,
                 details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}

    def payload(self) -> dict:
        return {"code": self.code, "message": str(self), **self.details}


# Policy (spec §20): quantities at/above the threshold require an approval
# of the same run by a different user before capture.
DEFAULT_POLICY = {"approval_min_quantity": 100.0}


class ApprovalRegistry:
    """Immutable approval evidence keyed by the server inputs_hash."""

    def __init__(self, path: str | None = None):
        self.path = path
        self._records: dict[str, dict] = {}
        if path:
            try:
                with open(path, encoding="utf-8") as fh:
                    self._records = json.load(fh)
            except (FileNotFoundError, json.JSONDecodeError):
                self._records = {}

    def _save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self._records, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def approve(self, inputs_hash: str, calculation_id: str,
                user: str) -> dict:
        """Record approval evidence; idempotent for the same hash (the first
        approval stands — approvals are immutable audit records)."""
        if not inputs_hash:
            raise CaptureError("CAPTURE_NO_RUN",
                               "нет inputs_hash — сначала выполни расчёт")
        if not str(user).strip():
            raise CaptureError("GOVERNANCE_NO_USER",
                               "approve требует имени согласующего")
        existing = self._records.get(inputs_hash)
        if existing is not None:
            return existing
        record = {
            "inputs_hash": inputs_hash,
            "calculation_id": calculation_id,
            "approved_by": str(user),
            "approved_at": _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds"),
        }
        self._records[inputs_hash] = record
        self._save()
        return record

    def find(self, inputs_hash: str) -> dict | None:
        return self._records.get(inputs_hash)


def atomic_capture(*, reprice, map_position, add_position, remove_position,
                   reprice_book, approvals: ApprovalRegistry,
                   quantity: float, expected_inputs_hash: str,
                   requested_by: str = "user",
                   policy: dict | None = None) -> dict:
    """Capture the CURRENT completed run into the book — atomically.

    ``reprice()`` re-executes the exact pricing request on the frozen
    context and returns the normalized result envelope (with provenance).
    ``map_position()`` returns (instrument, params, description) or None.
    ``add_position/remove_position/reprice_book`` mutate the book.
    """
    policy = {**DEFAULT_POLICY, **(policy or {})}
    if not expected_inputs_hash:
        raise CaptureError(
            "CAPTURE_NO_RUN",
            "capture без inputs_hash запрещён — сначала выполни расчёт и "
            "захватывай именно его", status=400)

    result = reprice()
    if result.get("errors"):
        raise CaptureError("CAPTURE_REPRICE_FAILED",
                           f"переоценка перед capture не удалась: "
                           f"{result['errors'][0]}", status=400)
    prov = result.get("provenance") or {}
    actual_hash = prov.get("inputs_hash") or ""

    # Exact-run guarantee (phase 5 exit criterion): the book only ever takes
    # the run the user saw — hash drift means the inputs changed underneath.
    if actual_hash != expected_inputs_hash:
        raise CaptureError(
            "CAPTURE_HASH_MISMATCH",
            "inputs изменились с момента расчёта — пересчитай и повтори capture",
            status=409,
            details={"expected": expected_inputs_hash, "actual": actual_hash})

    # Research results never enter the book (spec §20).
    if not prov.get("production_allowed", False):
        raise CaptureError(
            "CAPTURE_RESEARCH_FORBIDDEN",
            "research/approximation-результат не подлежит capture "
            "(модель не допущена в прод)", status=403)

    approval = approvals.find(actual_hash)
    if quantity >= float(policy["approval_min_quantity"]):
        if approval is None:
            raise CaptureError(
                "CAPTURE_APPROVAL_REQUIRED",
                f"quantity ≥ {policy['approval_min_quantity']:g} требует "
                "согласования этого расчёта (approve run)", status=403,
                details={"inputs_hash": actual_hash})
        if approval["approved_by"] == requested_by:
            raise CaptureError(
                "GOVERNANCE_MAKER_CHECKER",
                "maker≠checker: согласовавший не может сам захватывать",
                status=403)

    mapped = map_position()
    if mapped is None:
        raise CaptureError("CAPTURE_UNSUPPORTED",
                           "продукт не поддерживается портфельной переоценкой",
                           status=400)
    instrument, params, description = mapped

    position = add_position(instrument, params, description, quantity)
    try:
        reprice_book()
    except Exception as exc:
        # Atomicity (spec §26): a book that cannot reprice with the new
        # position must not keep it.
        try:
            remove_position(position)
        finally:
            pass
        raise CaptureError(
            "CAPTURE_BOOK_REPRICE_FAILED",
            f"книга не переоценилась с новой позицией — capture откатен: {exc}",
            status=500) from exc

    return {
        "position": position,
        "lineage": {
            "calculation_id": prov.get("calculation_id", ""),
            "inputs_hash": actual_hash,
            "snapshot_id": prov.get("snapshot_id", ""),
            "model_version": prov.get("model_version", ""),
            "valuation_time": prov.get("valuation_time", ""),
            "approved_by": (approval or {}).get("approved_by"),
            "approved_at": (approval or {}).get("approved_at"),
            "captured_by": requested_by,
            "captured_at": _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds"),
        },
    }
