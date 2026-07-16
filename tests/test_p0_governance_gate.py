"""P0 governance: production admission and executable validation evidence."""

from __future__ import annotations

import pytest

from models import registry
from scripts import validation_program
from services.governance_service import GovernanceService
from services.pricing_service import PricingService


def _entry(status, *, tests=None, production_allowed=None) -> dict:
    entry = {
        "name": "P0 test model",
        "status": status,
        "domain": "Test",
        "tests": ["directed_identity"] if tests is None else tests,
        "notes": "test-only registry entry",
    }
    if production_allowed is not None:
        entry["production_allowed"] = production_allowed
    return entry


def test_approximation_is_not_production_allowed_by_implicit_fallback(monkeypatch):
    model_id = "warrant"
    monkeypatch.setitem(
        registry.MODEL_REGISTRY,
        model_id,
        _entry(registry.ModelStatus.APPROXIMATION),
    )
    # Even the legacy production allowlist must not act as an implicit override.
    monkeypatch.setattr(registry, "PRODUCTION_MODELS",
                        {*registry.PRODUCTION_MODELS, model_id})

    assert registry.get(model_id)["production_allowed"] is False
    assert GovernanceService().get_model(model_id).production_allowed is False
    with pytest.raises(ValueError, match="not production allowed"):
        GovernanceService().enforce_model(model_id)
    assert GovernanceService().enforce_model(
        model_id, allow_non_production=True).model_id == model_id


def test_approximation_can_only_be_enabled_by_explicit_registry_override(monkeypatch):
    model_id = "equity_swap"
    monkeypatch.setitem(
        registry.MODEL_REGISTRY,
        model_id,
        _entry(registry.ModelStatus.APPROXIMATION, production_allowed=True),
    )

    assert registry.get(model_id)["production_allowed"] is True
    assert GovernanceService().get_model(model_id).production_allowed is True
    assert GovernanceService().enforce_model(model_id).production_allowed is True


def test_all_registered_approximations_fail_closed_by_default():
    approximation_ids = [
        model_id for model_id, entry in registry.MODEL_REGISTRY.items()
        if entry["status"] == registry.ModelStatus.APPROXIMATION
    ]

    assert approximation_ids
    for model_id in approximation_ids:
        assert registry.get(model_id)["production_allowed"] is False
        with pytest.raises(ValueError, match="not production allowed"):
            GovernanceService().enforce_model(model_id)


def test_pricing_service_requires_explicit_analytical_opt_in_for_approximation():
    blocked = PricingService().price_warrant(100, 100, 1, 0.05, 0.20)
    analytical = PricingService(
        allow_non_production_models=True).price_warrant(
            100, 100, 1, 0.05, 0.20)

    assert blocked["value"] is None
    assert any("not production allowed" in error for error in blocked["errors"])
    assert analytical["value"] is not None
    assert analytical["errors"] == []
    assert analytical["model_production_allowed"] is False


def test_analytics_lab_membership_cannot_be_overridden_in_entry(monkeypatch):
    model_id = "heston_cf"
    monkeypatch.setitem(
        registry.MODEL_REGISTRY,
        model_id,
        _entry(
            registry.ModelStatus.VALIDATED,
            production_allowed=True,
        ) | {"workflow_layer": "Production", "analytics_lab_only": False},
    )
    entry = registry.get(model_id)

    assert entry["workflow_layer"] == "Research"
    assert entry["analytics_lab_only"] is True
    assert entry["production_allowed"] is False
    with pytest.raises(RuntimeError, match="production-allowed"):
        GovernanceService()


def test_production_models_follow_normalized_registry_not_legacy_allowlist(
        monkeypatch):
    model_id = "fixed_bond"
    monkeypatch.setitem(
        registry.MODEL_REGISTRY,
        model_id,
        _entry(registry.ModelStatus.VALIDATED),
    )
    monkeypatch.setattr(registry, "PRODUCTION_MODELS", set())

    assert model_id in GovernanceService().production_models()


def test_validation_gate_rejects_validated_model_without_test_map(monkeypatch):
    model_id = "p0_validated_without_map"
    monkeypatch.setitem(
        validation_program.MODEL_REGISTRY,
        model_id,
        _entry(registry.ModelStatus.VALIDATED),
    )
    monkeypatch.delitem(validation_program.TEST_MAP, model_id, raising=False)

    problems = validation_program.check_consistency()

    assert any(model_id in problem and "TEST_MAP" in problem
               for problem in problems)


def test_validation_gate_rejects_missing_declared_evidence(monkeypatch):
    model_id = "p0_validated_without_evidence"
    monkeypatch.setitem(
        validation_program.MODEL_REGISTRY,
        model_id,
        _entry(registry.ModelStatus.VALIDATED, tests=[]),
    )
    monkeypatch.setitem(
        validation_program.TEST_MAP,
        model_id,
        ["tests/test_p0_governance_gate.py"],
    )

    problems = validation_program.check_consistency()

    assert any(model_id in problem and "evidence" in problem
               for problem in problems)


def test_validation_gate_rejects_missing_evidence_file(monkeypatch):
    model_id = "p0_validated_with_missing_file"
    missing = "tests/does_not_exist_p0_governance.py"
    monkeypatch.setitem(
        validation_program.MODEL_REGISTRY,
        model_id,
        _entry(registry.ModelStatus.VALIDATED),
    )
    monkeypatch.setitem(validation_program.TEST_MAP, model_id, [missing])

    problems = validation_program.check_consistency()

    assert any(model_id in problem and missing in problem for problem in problems)


def test_validation_gate_accepts_existing_pytest_node_selector(monkeypatch):
    # Use a canonical component: the QW1 consistency gate correctly rejects
    # ad-hoc Validated IDs that are absent from taxonomy/definitions.
    model_id = "black_scholes"
    selector = (
        "tests/test_p0_governance_gate.py::"
        "test_validation_gate_accepts_existing_pytest_node_selector"
    )
    monkeypatch.setitem(validation_program.TEST_MAP, model_id, [selector])

    problems = validation_program.check_consistency()

    assert not any(model_id in problem for problem in problems)


def test_run_tests_treats_missing_mapping_as_failure(monkeypatch):
    model_id = "p0_missing_mapping"
    monkeypatch.delitem(validation_program.TEST_MAP, model_id, raising=False)

    def unexpected_subprocess(*args, **kwargs):
        raise AssertionError("pytest must not run without mapped evidence")

    monkeypatch.setattr(validation_program.subprocess, "run", unexpected_subprocess)

    assert validation_program.run_tests([model_id]) == {model_id: False}


def test_validation_runner_uses_current_interpreter_and_runtime_warning_guard(
        monkeypatch):
    calls = []
    monkeypatch.setitem(
        validation_program.TEST_MAP,
        "black_scholes",
        ["tests/test_p0_governance_gate.py"],
    )

    class Result:
        returncode = 0

    def capture(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(validation_program.subprocess, "run", capture)

    assert validation_program.run_tests(["black_scholes"]) == {
        "black_scholes": True}
    command, _ = calls[0]
    assert command[0] == validation_program.sys.executable
    assert command[1:4] == ["-m", "pytest", "-q"]
    assert "error::RuntimeWarning" in command


def test_validation_runner_deduplicates_shared_evidence(monkeypatch):
    calls = []
    selector = "tests/test_p0_governance_gate.py"
    monkeypatch.setitem(validation_program.TEST_MAP, "model_a", [selector])
    monkeypatch.setitem(validation_program.TEST_MAP, "model_b", [selector])

    class Result:
        returncode = 0

    def capture(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(validation_program.subprocess, "run", capture)

    assert validation_program.run_tests(["model_a", "model_b"]) == {
        "model_a": True, "model_b": True}
    assert len(calls) == 1
    assert calls[0].count(selector) == 1
