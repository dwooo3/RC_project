"""Phase 5 gate: approval evidence + atomic capture (spec §17, §20, §26).

Exit criterion: capture works ONLY for the exact current completed run hash
and, when policy requires, only after approval of the same run by another
user. Branch coverage runs against stubbed result envelopes; one integration
case drives the real pricer end-to-end for lineage sanity.
"""

from __future__ import annotations

import pytest

from api.capture_workflow import (
    ApprovalRegistry,
    CaptureError,
    atomic_capture,
)

HASH = "a" * 64


def _envelope(inputs_hash=HASH, production=True, errors=()):
    return {
        "errors": list(errors),
        "provenance": {
            "inputs_hash": inputs_hash,
            "calculation_id": "calc-1",
            "snapshot_id": "snap-1",
            "model_version": "v1",
            "valuation_time": "2026-07-15T12:00:00+00:00",
            "production_allowed": production,
        },
    }


class _Book:
    """Records capture side effects; can be told to fail the book reprice."""

    def __init__(self, fail_reprice=False):
        self.added, self.removed, self.repriced = [], [], 0
        self.fail_reprice = fail_reprice

    def add(self, instrument, params, description, quantity):
        position = {"id": f"pos-{len(self.added) + 1}",
                    "instrument": instrument, "quantity": quantity}
        self.added.append(position)
        return position

    def remove(self, position):
        self.removed.append(position["id"])

    def reprice(self):
        self.repriced += 1
        if self.fail_reprice:
            raise RuntimeError("book blew up")


def _capture(book, *, envelope=None, quantity=1.0, expected=HASH,
             approvals=None, requested_by="alice", mapped=("eq_opt", {}, "d")):
    return atomic_capture(
        reprice=lambda: envelope or _envelope(),
        map_position=lambda: mapped,
        add_position=book.add,
        remove_position=book.remove,
        reprice_book=book.reprice,
        approvals=approvals or ApprovalRegistry(),
        quantity=quantity,
        expected_inputs_hash=expected,
        requested_by=requested_by)


# ── exact-run guarantee ──────────────────────────────────

def test_capture_succeeds_for_exact_hash_with_lineage():
    book = _Book()
    outcome = _capture(book)
    assert book.added and book.repriced == 1 and not book.removed
    lineage = outcome["lineage"]
    assert lineage["inputs_hash"] == HASH
    assert lineage["calculation_id"] == "calc-1"
    assert lineage["snapshot_id"] == "snap-1"
    assert lineage["captured_by"] == "alice"
    assert lineage["captured_at"]


def test_capture_conflicts_on_hash_drift():
    book = _Book()
    with pytest.raises(CaptureError) as err:
        _capture(book, envelope=_envelope(inputs_hash="b" * 64))
    assert err.value.code == "CAPTURE_HASH_MISMATCH"
    assert err.value.status == 409
    assert err.value.details["actual"] == "b" * 64
    assert not book.added, "conflicting capture must not touch the book"


def test_capture_without_run_hash_fails_closed():
    book = _Book()
    with pytest.raises(CaptureError) as err:
        _capture(book, expected="")
    assert err.value.code == "CAPTURE_NO_RUN"
    assert not book.added


def test_capture_refuses_failed_reprice():
    book = _Book()
    with pytest.raises(CaptureError) as err:
        _capture(book, envelope=_envelope(errors=["boom"]))
    assert err.value.code == "CAPTURE_REPRICE_FAILED"
    assert not book.added


# ── governance gates (spec §20) ──────────────────────────

def test_research_results_never_capture():
    book = _Book()
    with pytest.raises(CaptureError) as err:
        _capture(book, envelope=_envelope(production=False))
    assert err.value.code == "CAPTURE_RESEARCH_FORBIDDEN"
    assert err.value.status == 403
    assert not book.added


def test_large_quantity_requires_approval_of_same_run():
    book = _Book()
    approvals = ApprovalRegistry()
    with pytest.raises(CaptureError) as err:
        _capture(book, quantity=100.0, approvals=approvals)
    assert err.value.code == "CAPTURE_APPROVAL_REQUIRED"
    assert err.value.status == 403

    # approval of a DIFFERENT run does not unlock this one
    approvals.approve("f" * 64, "calc-x", "bob")
    with pytest.raises(CaptureError):
        _capture(book, quantity=100.0, approvals=approvals)

    approvals.approve(HASH, "calc-1", "bob")
    outcome = _capture(book, quantity=100.0, approvals=approvals)
    assert outcome["lineage"]["approved_by"] == "bob"
    assert book.added


def test_maker_checker_on_capture():
    book = _Book()
    approvals = ApprovalRegistry()
    approvals.approve(HASH, "calc-1", "bob")
    with pytest.raises(CaptureError) as err:
        _capture(book, quantity=100.0, approvals=approvals,
                 requested_by="bob")
    assert err.value.code == "GOVERNANCE_MAKER_CHECKER"
    assert not book.added


def test_small_quantity_needs_no_approval():
    book = _Book()
    outcome = _capture(book, quantity=99.9)
    assert outcome["lineage"]["approved_by"] is None
    assert book.added


# ── atomicity (spec §26 rollback) ────────────────────────

def test_book_reprice_failure_rolls_capture_back():
    book = _Book(fail_reprice=True)
    with pytest.raises(CaptureError) as err:
        _capture(book)
    assert err.value.code == "CAPTURE_BOOK_REPRICE_FAILED"
    assert err.value.status == 500
    assert book.removed == [book.added[0]["id"]], \
        "the failed capture must remove the position it inserted"


def test_unsupported_product_fails_before_book_mutation():
    book = _Book()
    with pytest.raises(CaptureError) as err:
        _capture(book, mapped=None)
    assert err.value.code == "CAPTURE_UNSUPPORTED"
    assert not book.added


# ── approval registry ────────────────────────────────────

def test_approval_registry_is_idempotent_and_persistent(tmp_path):
    path = str(tmp_path / "approvals.json")
    registry = ApprovalRegistry(path)
    first = registry.approve(HASH, "calc-1", "bob")
    again = registry.approve(HASH, "calc-1", "carol")
    assert again == first, "the first approval record is immutable evidence"

    reloaded = ApprovalRegistry(path)
    assert reloaded.find(HASH)["approved_by"] == "bob"
    assert reloaded.find("x" * 64) is None


def test_approval_requires_hash_and_user():
    registry = ApprovalRegistry()
    with pytest.raises(CaptureError):
        registry.approve("", "calc", "bob")
    with pytest.raises(CaptureError):
        registry.approve(HASH, "calc", "  ")


# ── integration: real pricer end-to-end ──────────────────

def test_integration_capture_against_real_run():
    from api.pricing_workstation import price_ws, to_position
    from services.pricing_service import PricingService

    svc = PricingService(allow_analytics_lab=True,
                         allow_non_production_models=True)
    params = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "q": 0.0,
              "sigma": 0.2, "opt": "call"}

    def reprice():
        return price_ws(svc, None, "european_option", "black_scholes",
                        dict(params))

    run = reprice()
    inputs_hash = run["provenance"]["inputs_hash"]
    assert inputs_hash, "the real pricer must produce evidence"

    book = _Book()

    def map_position():
        mapped = to_position("european_option", params,
                             engine_id="black_scholes")
        assert mapped is not None
        instrument, pos_params, desc = mapped
        return instrument, pos_params, desc

    outcome = atomic_capture(
        reprice=reprice, map_position=map_position,
        add_position=book.add, remove_position=book.remove,
        reprice_book=book.reprice, approvals=ApprovalRegistry(),
        quantity=1.0, expected_inputs_hash=inputs_hash,
        requested_by="alice")
    assert outcome["lineage"]["inputs_hash"] == inputs_hash
    assert book.added and book.repriced == 1

    # and the conflict path with a stale hash from a different run
    with pytest.raises(CaptureError) as err:
        atomic_capture(
            reprice=reprice, map_position=map_position,
            add_position=book.add, remove_position=book.remove,
            reprice_book=book.reprice, approvals=ApprovalRegistry(),
            quantity=1.0, expected_inputs_hash="0" * 64,
            requested_by="alice")
    assert err.value.code == "CAPTURE_HASH_MISMATCH"
