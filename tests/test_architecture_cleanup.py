"""
Regression tests for the structural cleanup (CURRENT_ISSUES_AND_REMEDIATION.md).

Scope (no quantitative model changes):
  1. analytics_workspace status sourced via GovernanceService (parity with registry).
  2. curves.russia no longer depends on instruments (price_ofz moved to pricing layer).
  3. Historical VaR consolidated behind a single RiskService.var(method=...) entry.
  4. CI workflow + requirements.txt presence.
"""
import sys, os, ast
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import numpy as np
import pytest

warnings.filterwarnings("ignore")

ROOT = os.path.join(os.path.dirname(__file__), "..")


# ─────────────────────────────────────────────────────────
# 2. curves.russia must not import the pricing layer
# ─────────────────────────────────────────────────────────

def test_curves_russia_has_no_instruments_dependency():
    src = open(os.path.join(ROOT, "curves", "russia.py")).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("instruments"), \
                f"curves.russia must not import {node.module}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("instruments")


def test_price_ofz_moved_to_pricing_layer():
    import curves.russia as russia
    assert not hasattr(russia, "price_ofz")
    from instruments.fixed_income import price_ofz  # noqa: F401


def test_price_ofz_prices_a_bond():
    from instruments.fixed_income import price_ofz
    from curves.yield_curve import YieldCurve
    crv = YieldCurve([0.5, 1, 2, 3, 5, 10],
                     [0.15, 0.145, 0.138, 0.133, 0.127, 0.12])
    res = price_ofz(1000, 0.08, 5, 2, crv)
    assert res["dirty_price"] > 0
    assert "ytm" in res and "mod_duration" in res
    assert res["clean_price"] == pytest.approx(res["dirty_price"], abs=1e-9)  # accrued_days=0


# ─────────────────────────────────────────────────────────
# 1. Governance-routed status parity (no PySide6 needed)
# ─────────────────────────────────────────────────────────

def test_governance_status_matches_registry_for_analytics_keys():
    from models.registry import MODEL_REGISTRY, ModelStatus
    from services.governance_service import GovernanceService
    gov = GovernanceService()
    for key in ["binomial_crr", "mc_gbm", "heston_cf", "short_rate", "placeholder", "garch"]:
        raw = MODEL_REGISTRY.get(key, {}).get("status", ModelStatus.PLACEHOLDER)
        expected = raw.value if hasattr(raw, "value") else str(raw)
        assert gov.get_model(key).status == expected


def test_analytics_workspace_does_not_import_raw_registry():
    src = open(os.path.join(ROOT, "app", "panels", "analytics_workspace.py")).read()
    tree = ast.parse(src)
    imports_registry = any(
        isinstance(n, ast.ImportFrom) and n.module == "models.registry"
        for n in ast.walk(tree)
    )
    assert not imports_registry, "analytics_workspace should route via GovernanceService"
    assert "GovernanceService" in src


# ─────────────────────────────────────────────────────────
# 3. Unified VaR dispatcher — pure delegation, no quant change
# ─────────────────────────────────────────────────────────

@pytest.fixture
def returns():
    return np.random.default_rng(0).normal(0, 0.01, 500)


def test_var_dispatcher_matches_individual_methods(returns):
    from services.risk_service import RiskService
    rs = RiskService()
    assert rs.var(returns, 1e6, method="historical")["value"] == \
        rs.historical_var(returns, 1e6)["value"]
    assert rs.var(returns, 1e6, method="parametric")["value"] == \
        rs.parametric_var(returns, 1e6)["value"]
    assert rs.var(returns, 1e6, method="monte_carlo")["value"] == \
        rs.monte_carlo_var(returns, 1e6)["value"]
    assert rs.var(returns, 1e6, method="evt")["value"] == \
        rs.evt_var(returns, 1e6, 0.95)["value"]


def test_var_dispatcher_aliases(returns):
    from services.risk_service import RiskService
    rs = RiskService()
    assert rs.var(returns, 1e6, method="HS")["value"] == \
        rs.var(returns, 1e6, method="historical")["value"]
    assert rs.var(returns, 1e6, method="mc")["value"] == \
        rs.var(returns, 1e6, method="monte_carlo")["value"]


def test_var_dispatcher_unknown_method_returns_error(returns):
    from services.risk_service import RiskService
    rs = RiskService()
    res = rs.var(returns, 1e6, method="does_not_exist")
    assert res.get("errors") or res.get("error") or res.get("value") is None


# ─────────────────────────────────────────────────────────
# 4. CI + requirements artefacts present
# ─────────────────────────────────────────────────────────

def test_requirements_file_lists_core_deps():
    req = open(os.path.join(ROOT, "requirements.txt")).read().lower()
    for dep in ("numpy", "scipy", "pyside6", "matplotlib", "pytest"):
        assert dep in req


def test_ci_workflow_present():
    wf = os.path.join(ROOT, ".github", "workflows", "tests.yml")
    assert os.path.exists(wf)
    content = open(wf).read()
    assert "pytest" in content
