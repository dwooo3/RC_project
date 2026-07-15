"""Async job protocol contract (spec §18): ordered events, partial results,
idempotent cancel, structured failure, retry semantics.

The manager is plain Python (api/pricing_jobs.py) — no fastapi needed, so the
whole suite runs in CI. Real-pricing paths use the same svc/FLAT_CURVE fixture
as test_pricing_workstation.py; timing-sensitive paths (cancel mid-run) use a
synthetic work function so they can't flake on machine speed.
"""

from __future__ import annotations

import threading
import time

import pytest

from api.pricing_jobs import JobCancelled, JobManager, compute_inputs_hash
from api.pricing_workstation import FLAT_CURVE, ladder_ws, payoff_ws
from services.pricing_service import PricingService

BS_PARAMS = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "q": 0.0,
             "sigma": 0.2, "opt": "call"}


@pytest.fixture(scope="module")
def svc():
    return PricingService(allow_analytics_lab=True,
                          allow_non_production_models=True)


def _wait_terminal(job, timeout=30.0):
    deadline = time.time() + timeout
    while job.state not in ("completed", "failed", "cancelled", "expired"):
        assert time.time() < deadline, f"job stuck in '{job.state}'"
        time.sleep(0.01)
    return job


# ── real pricing through the job runner ──────────────────

def test_ladder_job_completes_with_ordered_events(svc):
    mgr = JobManager()
    steps = 21
    job = mgr.submit("ladder", {"case": "ordered"}, lambda hook: ladder_ws(
        svc, None, "european_option", "black_scholes", dict(BS_PARAMS),
        "S", 70.0, 130.0, steps, hook=hook))
    _wait_terminal(job)

    assert job.state == "completed"
    assert len(job.result["rows"]) == steps
    seqs = [e["seq"] for e in job.events]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs)), \
        "event seq must be strictly increasing per job"
    types = [e["type"] for e in job.events]
    assert types[:3] == ["accepted", "queued", "started"]
    assert types[-1] == "completed"
    assert "progress" in types and "partial_result" in types
    final_progress = [e for e in job.events if e["type"] == "progress"][-1]
    assert final_progress["data"]["completed"] == steps
    assert final_progress["data"]["total"] == steps


def test_partial_results_accumulate_and_are_marked_incomplete(svc):
    mgr = JobManager()
    steps = 25
    job = mgr.submit("ladder", {"case": "partial"}, lambda hook: ladder_ws(
        svc, None, "european_option", "black_scholes", dict(BS_PARAMS),
        "S", 70.0, 130.0, steps, hook=hook))
    _wait_terminal(job)

    partials = [e for e in job.events if e["type"] == "partial_result"]
    assert partials, "no partial_result events emitted"
    cursors = [p["data"]["cursor"] for p in partials]
    assert cursors == sorted(cursors), "partial cursors must be monotonic"
    assert cursors[-1] == steps
    assert all(p["data"]["incomplete"] for p in partials), \
        "partial results must be marked incomplete (spec §18)"
    # completed snapshot exposes the full result and drops the partial view
    snap = job.snapshot()
    assert snap["partial"] is None and snap["result"] is not None


def test_payoff_job_spans_both_ladders(svc):
    mgr = JobManager()
    job = mgr.submit("payoff", {"case": "payoff"}, lambda hook: payoff_ws(
        svc, None, "european_option", "black_scholes", dict(BS_PARAMS),
        steps=11, hook=hook))
    _wait_terminal(job)
    assert job.state == "completed"
    final = [e for e in job.events if e["type"] == "progress"][-1]["data"]
    assert final["total"] == 22 and final["completed"] == 22


def test_pricing_error_fails_closed_not_retryable(svc):
    mgr = JobManager()
    job = mgr.submit("ladder", {"case": "bad-product"}, lambda hook: ladder_ws(
        svc, None, "no_such_product", None, {}, "S", 1.0, 2.0, 5, hook=hook))
    _wait_terminal(job)
    assert job.state == "failed"
    assert job.error["code"] == "PRICING_ERROR"
    assert job.error["retryable"] is False
    assert job.events[-1]["type"] == "failed"
    assert job.events[-1]["data"]["message"]


# ── manager semantics on synthetic work (timing-deterministic) ──

def _slow_work(units=200, dt=0.005, fail_at=None, unexpected=False):
    def work(hook):
        for i in range(units):
            if fail_at is not None and i == fail_at:
                if unexpected:
                    raise RuntimeError("worker exploded")
                raise ValueError("bad economics")
            time.sleep(dt)
            hook(i + 1, units, {"i": i})
        return {"units": units}
    return work


def test_cancel_mid_run_keeps_partial_and_is_idempotent():
    mgr = JobManager()
    job = mgr.submit("ladder", {"case": "cancel"}, _slow_work())
    while job.progress["completed"] < 5:      # let it actually start
        time.sleep(0.005)
    assert job.request_cancel() in ("running", "cancelled")
    _wait_terminal(job)

    assert job.state == "cancelled"
    assert job.events[-1]["type"] == "cancelled"
    assert 0 < job.progress["completed"] < 200, "cancel must land mid-run"
    snap = job.snapshot()
    assert snap["partial"]["incomplete"] is True
    assert len(snap["partial"]["items"]) == job.progress["completed"]
    # idempotent: cancelling again (or a terminal job) never changes state
    assert job.request_cancel() == "cancelled"
    assert mgr.cancel(job.job_id).state == "cancelled"


def test_cancel_completed_job_is_a_noop():
    mgr = JobManager()
    job = mgr.submit("ladder", {"case": "noop"}, _slow_work(units=3, dt=0))
    _wait_terminal(job)
    assert job.state == "completed"
    assert job.request_cancel() == "completed"
    assert job.state == "completed" and job.result == {"units": 3}


def test_unexpected_failure_is_retryable_and_retry_reruns():
    mgr = JobManager()
    req = {"case": "flaky"}
    job = mgr.submit("ladder", req, _slow_work(units=10, dt=0, fail_at=4,
                                               unexpected=True))
    _wait_terminal(job)
    assert job.state == "failed"
    assert job.error["code"] == "JOB_WORKER_ERROR"
    assert job.error["retryable"] is True

    # a failed job must NOT satisfy the retry — same inputs run again
    retry = mgr.submit("ladder", req, _slow_work(units=10, dt=0))
    assert retry.job_id != job.job_id
    _wait_terminal(retry)
    assert retry.state == "completed"


def test_retry_of_completed_job_returns_same_calculation():
    mgr = JobManager()
    calls = []

    def work(hook):
        calls.append(1)
        hook(1, 1, {"i": 0})
        return {"ok": True}

    first = mgr.submit("ladder", {"case": "idem"}, work)
    _wait_terminal(first)
    again = mgr.submit("ladder", {"case": "idem"}, work)
    assert again.job_id == first.job_id, \
        "retry must not duplicate a completed calculation (spec §18)"
    assert len(calls) == 1
    # a different request is a different job
    other = mgr.submit("ladder", {"case": "idem2"}, work)
    assert other.job_id != first.job_id


def test_client_request_id_deduplicates():
    mgr = JobManager()
    a = mgr.submit("ladder", {"case": "a"}, _slow_work(units=50),
                   client_request_id="rq-1")
    b = mgr.submit("ladder", {"case": "b"}, _slow_work(units=50),
                   client_request_id="rq-1")
    assert a.job_id == b.job_id
    a.request_cancel()
    _wait_terminal(a)


def test_events_since_supports_resume_cursor():
    mgr = JobManager()
    job = mgr.submit("ladder", {"case": "cursor"}, _slow_work(units=5, dt=0))
    _wait_terminal(job)
    all_events = job.events_since(0)
    mid = all_events[len(all_events) // 2]["seq"]
    tail = job.events_since(mid)
    assert all(e["seq"] > mid for e in tail)
    assert [e["seq"] for e in all_events if e["seq"] > mid] == \
        [e["seq"] for e in tail]
    assert job.events_since(all_events[-1]["seq"]) == []


def test_wait_events_long_poll_wakes_on_new_event():
    mgr = JobManager()
    release = threading.Event()

    def work(hook):
        release.wait(5.0)
        hook(1, 1, {"i": 0})
        return {"ok": True}

    job = mgr.submit("ladder", {"case": "poll"}, work)
    # consume everything emitted so far, then block for the next event
    seen = job.events_since(0)
    cursor = seen[-1]["seq"]
    t0 = time.time()
    threading.Timer(0.05, release.set).start()
    fresh = job.wait_events(cursor, timeout=5.0)
    assert fresh, "long-poll returned empty despite new events"
    assert time.time() - t0 < 5.0
    _wait_terminal(job)


def test_hook_raises_jobcancelled_inside_worker():
    mgr = JobManager()
    seen = {}

    def work(hook):
        try:
            for i in range(100):
                time.sleep(0.005)
                hook(i + 1, 100, {"i": i})
        except JobCancelled:
            seen["raised"] = True
            raise
        return {}

    job = mgr.submit("ladder", {"case": "hook-cancel"}, work)
    while job.progress["completed"] < 3:
        time.sleep(0.005)
    job.request_cancel()
    _wait_terminal(job)
    assert job.state == "cancelled" and seen.get("raised") is True


def test_inputs_hash_is_canonical():
    h1 = compute_inputs_hash("ladder", {"b": 2, "a": 1})
    h2 = compute_inputs_hash("ladder", {"a": 1, "b": 2})
    h3 = compute_inputs_hash("grid2d", {"a": 1, "b": 2})
    assert h1 == h2 and h1 != h3
