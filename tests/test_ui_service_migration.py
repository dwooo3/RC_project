"""Static smoke checks for UI-to-service migration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET_PANELS = [
    "bond_panel.py",
    "var_panel.py",
    "histvar_panel.py",
    "stress_panel.py",
]


def _panel_source(panel_name: str) -> str:
    return (ROOT / "app" / "panels" / panel_name).read_text()


def test_wave1_panels_do_not_import_raw_engines():
    forbidden = [
        "from models.",
        "import models",
        "from instruments.",
        "import instruments",
        "from curves.",
        "import curves",
        "from risk.",
        "import risk",
    ]

    for panel_name in TARGET_PANELS:
        source = _panel_source(panel_name)
        for token in forbidden:
            assert token not in source, f"{panel_name} still contains {token}"


def test_wave1_panels_do_not_construct_market_data_snapshots_directly():
    forbidden = ["MarketDataSnapshot", "MarketDataSource", "YieldCurve("]

    for panel_name in TARGET_PANELS:
        source = _panel_source(panel_name)
        for token in forbidden:
            assert token not in source, f"{panel_name} still constructs market data directly"


def test_bond_panel_uses_pricing_service_not_fixed_bond_directly():
    source = _panel_source("bond_panel.py")

    assert "from services.pricing_service import PricingService" in source
    assert "from services.market_data_service import MarketDataService" in source
    assert "from instruments.fixed_income import fixed_bond" not in source
    assert "fixed_bond(" not in source
    assert "price_bond(" in source


def test_var_panel_routes_var_and_stress_paths_through_risk_service():
    source = _panel_source("var_panel.py")

    assert "from services.risk_service import RiskService" in source
    assert ".historical_var(" in source
    assert ".parametric_var(" in source
    assert ".monte_carlo_var(" in source
    assert ".evt_var(" in source
    assert ".stress_option(" in source


def test_histvar_and_stress_panels_route_through_risk_service():
    hist_source = _panel_source("histvar_panel.py")
    stress_source = _panel_source("stress_panel.py")

    assert "from services.risk_service import RiskService" in hist_source
    assert ".historical_pnl_var(" in hist_source
    assert ".age_weighted_pnl_var(" in hist_source
    assert "from services.risk_service import RiskService" in stress_source
    assert ".stress_option(" in stress_source
    assert ".reverse_stress_option(" in stress_source
