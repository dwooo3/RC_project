from __future__ import annotations

from dataclasses import dataclass
import json
import math
import threading
import uuid

import pytest

from api.pricing_new_runs import (
    PricingNewRunError,
    PricingNewRunNotFoundError,
    PricingNewRunService,
    PricingNewRunStoreError,
    canonical_json,
    compute_content_hash,
)


def _request(index: int = 1) -> dict:
    return {
        "environment_id": "prod-eod",
        "legs": [{
            "id": f"leg-{index}",
            "product_id": "american_option",
            "engine_id": "binomial_tree",
            "params": {"S": 100.0, "K": 95.0, "opt": "call"},
        }],
    }


def _result(index: int = 1) -> dict:
    return {
        "snapshot_id": "eod-2026-07-16",
        "legs": [{"id": f"leg-{index}", "value": 12.345}],
        "totals": {"pv": 12.345},
    }


def test_create_persists_exact_request_and_full_result(tmp_path):
    path = tmp_path / "nested" / "runs.json"
    request = _request()
    result = _result()
    service = PricingNewRunService(path)

    run = service.create(name="  Morning validation  ", request=request,
                         result=result)

    assert uuid.UUID(run.run_id).version == 4
    assert run.created_at.endswith("Z")
    assert run.name == "Morning validation"
    assert run.request == request
    assert run.result == result
    assert run.content_hash == compute_content_hash(
        name=run.name, request=request, result=result)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["runs"] == [run.as_dict()]
    # A new process verifies and returns the same exact record.
    assert PricingNewRunService(path).get(run.run_id) == run


def test_inputs_and_outputs_are_detached_from_callers(tmp_path):
    request = _request()
    result = _result()
    service = PricingNewRunService(tmp_path / "runs.json")
    run = service.save_run(name="Detached", request=request, result=result)

    request["legs"][0]["params"]["S"] = 999.0
    result["legs"][0]["value"] = -1.0
    run.request["legs"][0]["params"]["S"] = 777.0
    fetched = service.get_run(run.run_id)

    assert fetched.request["legs"][0]["params"]["S"] == 100.0
    assert fetched.result["legs"][0]["value"] == 12.345


def test_history_is_newest_first_and_lightweight(tmp_path):
    service = PricingNewRunService(tmp_path / "runs.json")
    runs = [service.create(name=f"Run {i}", request=_request(i),
                           result=_result(i)) for i in range(4)]

    page = service.list_runs(limit=2, offset=1)

    assert [row.run_id for row in page] == [runs[2].run_id, runs[1].run_id]
    assert page[0].as_dict() == {
        "run_id": runs[2].run_id,
        "created_at": runs[2].created_at,
        "name": "Run 2",
        "content_hash": runs[2].content_hash,
    }
    assert "result" not in page[0].as_dict()


def test_get_unknown_run_raises_typed_not_found(tmp_path):
    service = PricingNewRunService(tmp_path / "runs.json")
    with pytest.raises(PricingNewRunNotFoundError):
        service.get("unknown")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("side", ["request", "result"])
def test_nonfinite_values_fail_closed_and_are_never_persisted(
        tmp_path, bad, side):
    path = tmp_path / "runs.json"
    service = PricingNewRunService(path)
    request = _request()
    result = _result()
    (request if side == "request" else result)["bad"] = bad

    with pytest.raises(PricingNewRunError, match="NaN or Infinity"):
        service.create(name="Invalid", request=request, result=result)

    assert not path.exists()


def test_store_parser_rejects_nonfinite_json_constants(tmp_path):
    path = tmp_path / "runs.json"
    path.write_text('{"schema_version": 1, "runs": [NaN]}', encoding="utf-8")
    with pytest.raises(PricingNewRunStoreError, match="forbidden JSON constant"):
        PricingNewRunService(path)


def test_canonical_hash_is_order_independent_but_content_sensitive():
    left = {"b": [2, {"z": "Ж", "a": 1}], "a": 0}
    right = {"a": 0, "b": [2, {"a": 1, "z": "Ж"}]}
    assert canonical_json(left) == canonical_json(right)
    first = compute_content_hash(name="X", request=left, result={"pv": 1})
    reordered = compute_content_hash(name="X", request=right, result={"pv": 1})
    changed = compute_content_hash(name="X", request=right, result={"pv": 2})
    assert first == reordered
    assert first != changed


def test_tampered_record_fails_integrity_check(tmp_path):
    path = tmp_path / "runs.json"
    service = PricingNewRunService(path)
    service.create(name="Original", request=_request(), result=_result())
    document = json.loads(path.read_text(encoding="utf-8"))
    document["runs"][0]["result"]["totals"]["pv"] = 999.0
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(PricingNewRunStoreError,
                       match="content hash verification"):
        PricingNewRunService(path)


def test_failed_replace_does_not_mutate_committed_state(tmp_path, monkeypatch):
    path = tmp_path / "runs.json"
    service = PricingNewRunService(path)
    first = service.create(name="Committed", request=_request(), result=_result())
    before = path.read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("disk refused replace")

    monkeypatch.setattr("api.pricing_new_runs.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk refused"):
        service.create(name="Uncommitted", request=_request(2), result=_result(2))

    assert path.read_bytes() == before
    assert [row.run_id for row in service.list()] == [first.run_id]
    assert not list(tmp_path.glob(".*.tmp"))


def test_one_service_serializes_concurrent_creates(tmp_path):
    service = PricingNewRunService(tmp_path / "runs.json")
    errors: list[Exception] = []

    def create(index: int):
        try:
            service.create(name=f"Concurrent {index}", request=_request(index),
                           result=_result(index))
        except Exception as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)

    threads = [threading.Thread(target=create, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(service.list(limit=100)) == 12
    assert len(PricingNewRunService(service.path).list(limit=100)) == 12


@dataclass
class RequestDTO:
    environment_id: str
    legs: list[dict]


def test_dataclass_dto_is_convenient_for_api_adapter(tmp_path):
    service = PricingNewRunService(tmp_path / "runs.json")
    dto = RequestDTO(environment_id="prod-eod", legs=_request()["legs"])

    run = service.create(name="DTO", request=dto, result=_result())

    assert run.request == {"environment_id": "prod-eod", "legs": dto.legs}


@pytest.mark.parametrize("name", ["", "   ", "x" * 161])
def test_name_is_required_and_bounded(tmp_path, name):
    service = PricingNewRunService(tmp_path / "runs.json")
    with pytest.raises(PricingNewRunError):
        service.create(name=name, request=_request(), result=_result())


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(0, 0), (1001, 0), (True, 0), (5, -1), (5, True)],
)
def test_history_pagination_validation(tmp_path, limit, offset):
    service = PricingNewRunService(tmp_path / "runs.json")
    with pytest.raises(PricingNewRunError):
        service.list(limit=limit, offset=offset)

