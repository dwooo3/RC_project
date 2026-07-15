"""Async job protocol for workstation analytics (spec §18).

Ladder/grid/scenario runs are cell-by-cell full revaluations that can take
seconds; this module runs them on worker threads and exposes an ordered event
stream per job: accepted → queued → started → progress/partial_result* →
completed | failed | cancelled.

Deliberately no FastAPI imports: the manager is a plain-Python contract so the
CI test suite (no fastapi installed) can cover partial/cancel/fail/retry paths
directly. HTTP wiring lives in api/server.py.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

# Terminal states never change once set (cancel after completed is a no-op).
_TERMINAL = frozenset({"completed", "failed", "cancelled", "expired"})

# Emit a partial_result event roughly this many times per job, not per cell —
# the stream stays chatty enough for a progress UI without flooding it.
_PARTIAL_CHUNKS = 20


class JobCancelled(Exception):
    """Raised inside the work function when the job's cancel flag is set."""


class PricingJob:
    """One analytics run: immutable request, ordered events, guarded state."""

    def __init__(self, kind: str, request: dict, inputs_hash: str,
                 client_request_id: str | None = None):
        self.job_id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.request = request
        self.inputs_hash = inputs_hash
        self.client_request_id = client_request_id
        self.created_at = time.time()
        self.state = "queued"
        self.progress = {"completed": 0, "total": None, "unit": "cells"}
        self.partial_items: list = []          # accumulated units, in order
        self.result: dict | None = None
        self.error: dict | None = None
        self.events: list[dict] = []
        self._seq = 0
        self._cancel = threading.Event()
        self._cond = threading.Condition()

    # ── event log ────────────────────────────────────────
    def _emit(self, event_type: str, data: dict | None = None) -> None:
        with self._cond:
            self._seq += 1
            self.events.append({
                "seq": self._seq,
                "type": event_type,
                "ts": time.time(),
                "data": data or {},
            })
            self._cond.notify_all()

    def events_since(self, after_seq: int = 0) -> list[dict]:
        with self._cond:
            return [e for e in self.events if e["seq"] > after_seq]

    def wait_events(self, after_seq: int = 0, timeout: float = 25.0) -> list[dict]:
        """Long-poll: block until an event later than after_seq exists."""
        deadline = time.time() + timeout
        with self._cond:
            while True:
                fresh = [e for e in self.events if e["seq"] > after_seq]
                if fresh or self.state in _TERMINAL:
                    return fresh
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._cond.wait(remaining)

    # ── lifecycle (called by the manager/worker only) ────
    def _start(self) -> None:
        self.state = "running"
        self._emit("started")

    def _report(self, done: int, total: int, item) -> None:
        """Per-unit hook passed into the pricing loop; raises to cancel."""
        if self._cancel.is_set():
            raise JobCancelled()
        self.progress = {"completed": done, "total": total, "unit": "cells"}
        if item is not None:
            self.partial_items.append(item)
        chunk = max(1, total // _PARTIAL_CHUNKS)
        if done % chunk == 0 or done == total:
            self._emit("progress", dict(self.progress))
            self._emit("partial_result", {
                "cursor": len(self.partial_items),
                "incomplete": True,
                "items": self.partial_items[-chunk:],
            })

    def _complete(self, result: dict) -> None:
        self.state = "completed"
        self.result = result
        self._emit("completed", {"inputs_hash": self.inputs_hash})

    def _fail(self, code: str, message: str, retryable: bool) -> None:
        self.state = "failed"
        self.error = {"code": code, "message": message, "retryable": retryable}
        self._emit("failed", dict(self.error))

    def _cancelled(self) -> None:
        self.state = "cancelled"
        self._emit("cancelled", {"completed": self.progress["completed"]})

    def request_cancel(self) -> str:
        """Idempotent: terminal jobs keep their state, cancel twice is fine."""
        if self.state not in _TERMINAL:
            self._cancel.set()
        return self.state

    # ── snapshots for the API layer ──────────────────────
    def snapshot(self) -> dict:
        with self._cond:
            last_seq = self._seq
        snap = {
            "job_id": self.job_id,
            "kind": self.kind,
            "state": self.state,
            "inputs_hash": self.inputs_hash,
            "progress": dict(self.progress),
            "last_seq": last_seq,
            "error": self.error,
            "result": self.result,
            "partial": None,
        }
        if self.result is None and self.partial_items:
            snap["partial"] = {"incomplete": True,
                               "items": list(self.partial_items)}
        return snap


def compute_inputs_hash(kind: str, request: dict) -> str:
    """Canonical hash of the job intent — retry/idempotency identity."""
    canon = json.dumps({"kind": kind, "request": request},
                       sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


class JobManager:
    """Registry + worker pool. submit() deduplicates: an identical request
    (same inputs hash) that is already queued/running/completed returns the
    existing job — retry never duplicates a completed calculation (spec §18).
    Failed/cancelled jobs do NOT block a fresh run of the same inputs."""

    def __init__(self, max_workers: int = 2, retention: int = 100,
                 ttl_seconds: float = 3600.0):
        self._jobs: dict[str, PricingJob] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="pricing-job")
        self._retention = retention
        self._ttl = ttl_seconds

    def submit(self, kind: str, request: dict, work,
               client_request_id: str | None = None) -> PricingJob:
        """`work(hook)` runs on a worker thread; hook(done, total, item) is the
        per-unit callback (raises JobCancelled when cancel was requested) and
        `work` returns the final result dict."""
        inputs_hash = compute_inputs_hash(kind, request)
        with self._lock:
            self._expire_locked()
            for job in self._jobs.values():
                same_intent = (job.inputs_hash == inputs_hash
                               or (client_request_id
                                   and job.client_request_id == client_request_id))
                if same_intent and job.state in ("queued", "running", "completed"):
                    return job
            job = PricingJob(kind, request, inputs_hash, client_request_id)
            self._jobs[job.job_id] = job
            self._prune_locked()
        job._emit("accepted", {"job_id": job.job_id})
        job._emit("queued")
        self._pool.submit(self._run, job, work)
        return job

    def _run(self, job: PricingJob, work) -> None:
        if job._cancel.is_set():          # cancelled while still queued
            job._cancelled()
            return
        job._start()
        try:
            result = work(job._report)
        except JobCancelled:
            job._cancelled()
        except (KeyError, ValueError, TypeError) as exc:
            # Bad economics/params: a verbatim retry would fail identically.
            job._fail("PRICING_ERROR", str(exc), retryable=False)
        except Exception as exc:  # noqa: BLE001 — worker must never die silently
            job._fail("JOB_WORKER_ERROR", f"{type(exc).__name__}: {exc}",
                      retryable=True)
        else:
            job._complete(result)

    def get(self, job_id: str) -> PricingJob | None:
        with self._lock:
            self._expire_locked()
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> PricingJob | None:
        job = self.get(job_id)
        if job is not None:
            job.request_cancel()
        return job

    # ── retention ────────────────────────────────────────
    def _expire_locked(self) -> None:
        now = time.time()
        for job in self._jobs.values():
            if (job.state in _TERMINAL or now - job.created_at <= self._ttl):
                continue
            # Still non-terminal past TTL: mark expired so pollers see closure.
            job.state = "expired"
            job._emit("expired")

    def _prune_locked(self) -> None:
        if len(self._jobs) <= self._retention:
            return
        terminal = [j for j in self._jobs.values() if j.state in _TERMINAL]
        terminal.sort(key=lambda j: j.created_at)
        for job in terminal[:len(self._jobs) - self._retention]:
            del self._jobs[job.job_id]


MANAGER = JobManager()
