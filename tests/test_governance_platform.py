"""Governance platform v2 tests."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.model_governance import ModelDefinition, ModelRegistryEntry
from models import registry
from services.governance_service import GovernanceService
from services.pricing_service import PricingService
from services.risk_service import RiskService


def test_governance_returns_model_registry_entry_fields():
    entry = GovernanceService().get_model("fixed_bond")

    assert isinstance(entry, ModelRegistryEntry)
    assert isinstance(entry, ModelDefinition)
    assert entry.model_id == "fixed_bond"
    assert entry.version
    assert entry.owner
    assert entry.status == "Validated"           # fixed_bond: batch-1 2026-07
    assert entry.limitations
    assert entry.documentation_link == ""
    assert entry.validation_date is None
    assert entry.quant_review_status == "Partially Validated"


def test_governance_service_exposes_workspace_sections():
    governance = GovernanceService()

    models = governance.list_models()
    counts = governance.status_counts()
    validation = governance.validation_status()
    audit = governance.audit_trail()
    limitations = governance.limitations_report()

    assert any(model.model_id == "fixed_bond" for model in models)
    assert counts["Approximation"] > 0
    assert any(row["model_id"] == "fixed_bond" for row in validation)
    assert any(row["quant_review_status"] == "Partially Validated" for row in validation)
    assert audit and audit[0]["status"] == "Pending"
    assert any(row["model_id"] == "fixed_bond" for row in limitations)


def test_prototype_model_generates_governance_warning():
    warnings = GovernanceService().warnings_for_model("mc_lsm")

    assert any("Prototype" in warning for warning in warnings)
    assert any("not production" in warning for warning in warnings)


def test_governance_separates_production_and_research_models():
    governance = GovernanceService()

    assert "fixed_bond" in governance.production_models()
    assert "var_historical" in governance.production_models()
    assert "heston_cf" in governance.research_models()
    assert "sabr" in governance.research_models()
    assert "garch" in governance.research_models()
    assert "mc_lsm" in governance.research_models()
    assert "heston_cf" not in governance.production_models()


def test_research_models_are_analytics_lab_only_not_production_allowed():
    entry = GovernanceService().get_model("heston_cf")

    assert entry.workflow_layer == "Research"
    assert entry.analytics_lab_only is True
    assert entry.production_allowed is False
    assert entry.is_research_only


def test_pricing_service_exposes_model_metadata():
    result = PricingService().price_vanilla_option(100, 100, 1, 0.05, 0.20)

    assert result["model_id"] == "black_scholes"
    assert result["model_version"]
    assert result["model_owner"]
    assert result["model_metadata"]["model_id"] == "black_scholes"
    assert result["model_metadata"]["model_quant_review_status"] == "Fixed"
    assert result["model_limitations"]
    assert "model_documentation_link" in result
    assert isinstance(result["model_production_allowed"], bool)


def test_pricing_service_blocks_research_model_by_default():
    result = PricingService().price_vanilla_option(100, 100, 1, 0.05, 0.20, model="mc")

    assert result["model_id"] == "mc_gbm"
    assert result["model_workflow_layer"] == "Research"
    assert result["model_analytics_lab_only"] is True
    assert result["model_production_allowed"] is False
    assert result["value"] is None
    assert result["raw"] is None
    assert result["errors"]
    assert any("requires explicit allow_analytics_lab=True" in error for error in result["errors"])
    assert any("Analytics Lab" in warning for warning in result["warnings"])
    assert any("not production allowed" in warning for warning in result["warnings"])


def test_pricing_service_allows_research_model_only_when_explicitly_enabled():
    result = PricingService(allow_analytics_lab=True).price_vanilla_option(
        100, 100, 1, 0.05, 0.20, model="mc"
    )

    assert result["model_id"] == "mc_gbm"
    assert result["errors"] == []
    assert result["value"] is not None
    assert any("Analytics Lab" in warning for warning in result["warnings"])


def test_governance_blocks_placeholder_models():
    result = PricingService().price_vanilla_option(100, 100, 1, 0.05, 0.20, model="unknown")

    assert result["model_id"] == "unknown"
    assert result["value"] is None
    assert result["raw"] is None
    assert any("Placeholder" in error for error in result["errors"])


def test_governance_blocks_broken_models(monkeypatch):
    monkeypatch.setitem(
        registry.MODEL_REGISTRY,
        "broken_test_model",
        {
            "name": "Broken Test Model",
            "status": registry.ModelStatus.BROKEN,
            "domain": "Risk",
            "tests": [],
            "notes": "Injected broken model for enforcement test.",
        },
    )

    try:
        GovernanceService().enforce_model("broken_test_model")
    except ValueError as exc:
        assert "Broken" in str(exc)
    else:
        raise AssertionError("Broken model was not blocked")


def test_risk_service_checks_governance_before_calculation(monkeypatch):
    original = dict(registry.MODEL_REGISTRY["var_historical"])
    monkeypatch.setitem(
        registry.MODEL_REGISTRY,
        "var_historical",
        {
            **original,
            "status": registry.ModelStatus.BROKEN,
            "notes": "Temporarily broken for enforcement test.",
        },
    )

    returns = np.array([0.01, -0.02, 0.005, -0.015, 0.02])
    result = RiskService().historical_var(returns, 1_000_000, 0.95, 1)

    assert result["value"] is None
    assert result["raw"] is None
    assert any("Broken" in error for error in result["errors"])


def test_risk_service_exposes_model_metadata():
    returns = np.array([0.01, -0.02, 0.005, -0.015, 0.02])
    result = RiskService().historical_var(returns, 1_000_000, 0.95, 1)

    assert result["model_id"] == "var_historical"
    assert result["model_version"]
    assert result["model_owner"]
    assert result["model_metadata"]["model_id"] == "var_historical"
    assert result["model_metadata"]["model_quant_review_status"] == "Partially Validated"
    assert result["model_limitations"]
    assert "model_documentation_link" in result
    assert isinstance(result["model_production_allowed"], bool)


def test_governance_quant_review_status_values_are_canonical():
    governance = GovernanceService()
    statuses = {model.quant_review_status for model in governance.list_models()}

    assert statuses <= {"Fixed", "False Positive", "Partially Validated", "Open"}
    assert "Fixed" in statuses
    assert "False Positive" in statuses
    assert "Partially Validated" in statuses
    assert "Open" in statuses
