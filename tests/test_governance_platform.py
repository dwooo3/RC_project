"""Governance platform v2 tests."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.model_governance import ModelDefinition, ModelRegistryEntry
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
    assert entry.status == "Approximation"
    assert entry.limitations
    assert entry.documentation_link == ""
    assert entry.validation_date is None


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
    assert result["model_limitations"]
    assert "model_documentation_link" in result
    assert isinstance(result["model_production_allowed"], bool)


def test_pricing_service_warns_when_research_model_is_requested():
    result = PricingService().price_vanilla_option(100, 100, 1, 0.05, 0.20, model="mc")

    assert result["model_id"] == "mc_gbm"
    assert result["model_workflow_layer"] == "Research"
    assert result["model_analytics_lab_only"] is True
    assert result["model_production_allowed"] is False
    assert any("Analytics Lab" in warning for warning in result["warnings"])
    assert any("not production allowed" in warning for warning in result["warnings"])


def test_risk_service_exposes_model_metadata():
    returns = np.array([0.01, -0.02, 0.005, -0.015, 0.02])
    result = RiskService().historical_var(returns, 1_000_000, 0.95, 1)

    assert result["model_id"] == "var_historical"
    assert result["model_version"]
    assert result["model_owner"]
    assert result["model_metadata"]["model_id"] == "var_historical"
    assert result["model_limitations"]
    assert "model_documentation_link" in result
    assert isinstance(result["model_production_allowed"], bool)
