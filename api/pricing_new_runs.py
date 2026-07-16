"""Durable audit log for named ``Pricing_new`` calculations.

The pricing runtime deliberately lives elsewhere.  This module only owns the
immutable run envelope that the UI needs in order to inspect and restore a
calculation: its user supplied name, exact JSON request, and complete JSON
result.  It has no FastAPI dependency, which keeps persistence independently
testable and makes the HTTP wiring a small adapter in :mod:`api.server`.

Records are written as a single versioned JSON document.  A write is committed
with ``os.replace`` only after the temporary file has been flushed and fsynced;
an interrupted write therefore leaves the previous document intact.  JSON is
strict throughout: non-finite numbers and non-JSON values fail closed instead
of being silently converted and making a run impossible to reproduce.
"""

from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
import tempfile
import threading
from typing import Any, Mapping
import uuid


SCHEMA_VERSION = 1
DEFAULT_PATH_ENV = "RC_PRICING_NEW_RUNS_PATH"
DEFAULT_PATH = Path("data/pricing_new_runs.json")


class PricingNewRunError(ValueError):
    """Base class for run-store errors suitable for an HTTP 400 response."""


class PricingNewRunNotFoundError(KeyError):
    """Raised when a requested run id does not exist (HTTP 404)."""


class PricingNewRunStoreError(RuntimeError):
    """Raised when the on-disk audit document is invalid or cannot be trusted."""


def _reject_json_constant(value: str) -> None:
    raise PricingNewRunStoreError(
        f"pricing run store contains forbidden JSON constant '{value}'"
    )


def _model_payload(value: Any) -> Any:
    """Unwrap common API DTOs without importing Pydantic.

    FastAPI callers normally pass ``request.model_dump(mode=\"json\")``.  The
    small duck-typed bridge here also accepts the model itself, as well as a
    dataclass, while the strict JSON validator below remains authoritative.
    """

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except TypeError:  # Pydantic v1 / a compatible user DTO
            return model_dump()
    dictionary = getattr(value, "dict", None)
    if callable(dictionary):
        return dictionary()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def _strict_json_copy(value: Any, *, label: str) -> Any:
    """Return a detached JSON-semantic copy, rejecting lossy values.

    Request/result data accepted by the service is exactly what can be sent
    over a standards-compliant JSON API: object keys are strings, arrays are
    lists, and every number is finite.  In particular, ``default=str`` is not
    used because it would turn implementation objects into misleading audit
    evidence.
    """

    value = _model_payload(value)

    def validate(item: Any, path: str) -> Any:
        item = _model_payload(item)
        if item is None or isinstance(item, (str, bool)):
            return item
        if isinstance(item, int):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise PricingNewRunError(
                    f"{path} must not contain NaN or Infinity"
                )
            return item
        if isinstance(item, Mapping):
            out: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise PricingNewRunError(
                        f"{path} has non-string object key {key!r}"
                    )
                child_path = f"{path}.{key}" if key else f"{path}['']"
                out[key] = validate(child, child_path)
            return out
        if isinstance(item, list):
            return [validate(child, f"{path}[{index}]")
                    for index, child in enumerate(item)]
        raise PricingNewRunError(
            f"{path} contains non-JSON value of type {type(item).__name__}"
        )

    detached = validate(value, label)
    # This is deliberately redundant with validate(): it pins the accepted
    # structure to Python's strict JSON encoder and catches future extensions.
    try:
        json.dumps(detached, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:  # pragma: no cover - safety net
        raise PricingNewRunError(f"{label} is not strict JSON: {exc}") from exc
    return detached


def canonical_json(value: Any) -> str:
    """Canonical JSON used for server-side content fingerprints."""

    strict = _strict_json_copy(value, label="content")
    return json.dumps(
        strict,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_content_hash(*, name: str, request: Mapping[str, Any],
                         result: Mapping[str, Any]) -> str:
    """Hash the immutable semantic envelope (transport metadata excluded)."""

    content = {"name": name, "request": request, "result": result}
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PricingNewRun:
    """Complete immutable audit record returned by ``create``/``get``."""

    run_id: str
    created_at: str
    name: str
    request: dict[str, Any]
    result: dict[str, Any]
    content_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "name": self.name,
            "request": copy.deepcopy(self.request),
            "result": copy.deepcopy(self.result),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class PricingNewRunSummary:
    """Lightweight history row; use ``get`` to fetch request and result."""

    run_id: str
    created_at: str
    name: str
    content_hash: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _utc_timestamp() -> str:
    return (_dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"))


def _record_from_dict(raw: Any) -> PricingNewRun:
    if not isinstance(raw, Mapping):
        raise PricingNewRunStoreError("pricing run record must be a JSON object")
    expected = {"run_id", "created_at", "name", "request", "result",
                "content_hash"}
    if set(raw) != expected:
        missing = sorted(expected - set(raw))
        extra = sorted(set(raw) - expected)
        raise PricingNewRunStoreError(
            f"invalid pricing run fields (missing={missing}, extra={extra})"
        )
    try:
        parsed_id = uuid.UUID(str(raw["run_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PricingNewRunStoreError("pricing run has invalid UUID") from exc
    if parsed_id.version != 4:
        raise PricingNewRunStoreError("pricing run id must be a UUID4")

    created_at = raw["created_at"]
    if not isinstance(created_at, str) or not created_at.endswith("Z"):
        raise PricingNewRunStoreError("pricing run has invalid UTC timestamp")
    try:
        _dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PricingNewRunStoreError("pricing run has invalid UTC timestamp") from exc

    name = raw["name"]
    if not isinstance(name, str) or not name.strip():
        raise PricingNewRunStoreError("pricing run has invalid name")
    try:
        request = _strict_json_copy(raw["request"], label="request")
        result = _strict_json_copy(raw["result"], label="result")
    except PricingNewRunError as exc:
        raise PricingNewRunStoreError(str(exc)) from exc
    if not isinstance(request, dict) or not isinstance(result, dict):
        raise PricingNewRunStoreError("pricing request and result must be objects")

    content_hash = raw["content_hash"]
    expected_hash = compute_content_hash(name=name, request=request,
                                         result=result)
    if not isinstance(content_hash, str) or content_hash != expected_hash:
        raise PricingNewRunStoreError(
            f"pricing run '{raw['run_id']}' failed content hash verification"
        )
    return PricingNewRun(
        run_id=str(parsed_id),
        created_at=created_at,
        name=name,
        request=request,
        result=result,
        content_hash=content_hash,
    )


class PricingNewRunService:
    """Thread-safe immutable run log backed by one atomic JSON document.

    ``create`` returns the full record. ``list`` returns newest-first summary
    rows so large Monte Carlo result payloads do not inflate history requests;
    ``get`` retrieves the exact request and full result required for restore.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None):
        configured = path or os.environ.get(DEFAULT_PATH_ENV) or DEFAULT_PATH
        self.path = Path(configured).expanduser()
        self._lock = threading.RLock()
        self._runs = self._load()

    def _load(self) -> list[PricingNewRun]:
        try:
            with self.path.open(encoding="utf-8") as handle:
                document = json.load(handle, parse_constant=_reject_json_constant)
        except FileNotFoundError:
            return []
        except PricingNewRunStoreError:
            raise
        except (json.JSONDecodeError, OSError) as exc:
            raise PricingNewRunStoreError(
                f"cannot read pricing run store '{self.path}': {exc}"
            ) from exc

        if not isinstance(document, Mapping):
            raise PricingNewRunStoreError("pricing run store must be a JSON object")
        if document.get("schema_version") != SCHEMA_VERSION:
            raise PricingNewRunStoreError(
                f"unsupported pricing run schema {document.get('schema_version')!r}"
            )
        raw_runs = document.get("runs")
        if not isinstance(raw_runs, list) or set(document) != {
                "schema_version", "runs"}:
            raise PricingNewRunStoreError("invalid pricing run store document")

        runs = [_record_from_dict(raw) for raw in raw_runs]
        ids = [run.run_id for run in runs]
        if len(ids) != len(set(ids)):
            raise PricingNewRunStoreError("pricing run store has duplicate run ids")
        return runs

    @staticmethod
    def _document(runs: list[PricingNewRun]) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "runs": [run.as_dict() for run in runs],
        }

    def _persist(self, runs: list[PricingNewRun]) -> None:
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=str(parent), prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    self._document(runs),
                    handle,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
            # Persist the directory entry where supported.  A failure here is
            # not allowed to invalidate a file that has already been replaced.
            try:
                directory_fd = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _detached(run: PricingNewRun) -> PricingNewRun:
        return PricingNewRun(**run.as_dict())

    def create(self, *, name: str, request: Mapping[str, Any],
               result: Mapping[str, Any]) -> PricingNewRun:
        """Atomically append one immutable named calculation."""

        if not isinstance(name, str):
            raise PricingNewRunError("name must be a string")
        name = name.strip()
        if not name:
            raise PricingNewRunError("name must not be empty")
        if len(name) > 160:
            raise PricingNewRunError("name must not exceed 160 characters")

        request_copy = _strict_json_copy(request, label="request")
        result_copy = _strict_json_copy(result, label="result")
        if not isinstance(request_copy, dict):
            raise PricingNewRunError("request must be a JSON object")
        if not isinstance(result_copy, dict):
            raise PricingNewRunError("result must be a JSON object")

        run = PricingNewRun(
            run_id=str(uuid.uuid4()),
            created_at=_utc_timestamp(),
            name=name,
            request=request_copy,
            result=result_copy,
            content_hash=compute_content_hash(
                name=name, request=request_copy, result=result_copy
            ),
        )
        with self._lock:
            next_runs = [*self._runs, run]
            self._persist(next_runs)
            self._runs = next_runs
        return self._detached(run)

    # Alias reads naturally in FastAPI route code.
    save_run = create

    def list(self, *, limit: int = 50,
             offset: int = 0) -> list[PricingNewRunSummary]:
        """Return newest-first history rows without heavy request/results."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise PricingNewRunError("limit must be an integer from 1 to 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise PricingNewRunError("offset must be a non-negative integer")
        with self._lock:
            selected = list(reversed(self._runs))[offset:offset + limit]
            return [PricingNewRunSummary(
                run_id=run.run_id,
                created_at=run.created_at,
                name=run.name,
                content_hash=run.content_hash,
            ) for run in selected]

    list_runs = list

    def get(self, run_id: str) -> PricingNewRun:
        """Return the complete immutable record for inspect/restore."""

        with self._lock:
            for run in self._runs:
                if run.run_id == run_id:
                    return self._detached(run)
        raise PricingNewRunNotFoundError(run_id)

    get_run = get

    def reload(self) -> None:
        """Reload and verify an externally replaced store document."""

        with self._lock:
            self._runs = self._load()

