"""Static smoke checks for UI-to-service migration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bond_panel_uses_pricing_service_not_fixed_bond_directly():
    source = (ROOT / "app" / "panels" / "bond_panel.py").read_text()

    assert "from services.pricing_service import PricingService" in source
    assert "from instruments.fixed_income import fixed_bond" not in source
    assert "fixed_bond(" not in source
    assert "price_bond(" in source


def test_var_panel_routes_supported_paths_through_risk_service():
    source = (ROOT / "app" / "panels" / "var_panel.py").read_text()

    assert "from services.risk_service import RiskService" in source
    assert ".historical_var(" in source
    assert ".parametric_var(" in source
    assert ".stress_option(" in source
    assert "from risk.stress import stress_option" not in source
    assert "from risk.var import historical_var" not in source
    assert "from risk.var import parametric_var" not in source
