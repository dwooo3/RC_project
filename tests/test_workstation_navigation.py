"""Workstation shell and navigation architecture tests."""


def test_main_navigation_matches_approved_information_architecture():
    from app.main_window import NAV_ITEMS

    assert NAV_ITEMS == [
        ("Dashboard", "dashboard"),
        ("Portfolio", "portfolio"),
        ("Risk", "risk"),
        ("Market Data", "market"),
        ("Pricing", "pricing"),
        ("Governance", "governance"),
        ("Analytics Lab", "analytics"),
    ]


def test_governance_workspace_is_first_class_panel():
    import inspect
    import app.panels.governance_workspace as governance_workspace

    assert hasattr(governance_workspace, "GovernanceWorkspace")
    source = inspect.getsource(governance_workspace)
    assert "from services.governance_service import GovernanceService" in source
    assert 'tabs.addTab(self._model_registry_tab(), "Model Registry")' in source
    assert 'tabs.addTab(self._validation_status_tab(), "Validation Status")' in source
    assert 'tabs.addTab(self._audit_trail_tab(), "Audit Trail")' in source
    assert 'tabs.addTab(self._limitations_tab(), "Limitations")' in source
    assert "Quant Review Status" in source
    assert "Fixed / False Positive / Partially Validated / Open" in source
    assert "from models" not in source
    assert "MODEL_REGISTRY" not in source


def test_workspace_shell_exports_required_shell_regions():
    import inspect
    from ui.shell import WorkspaceShell

    source = inspect.getsource(WorkspaceShell)

    assert "self.global_navigation" in source
    assert "self.workspace_header" in source
    assert "self.content_area" in source


def test_main_window_uses_workspace_shell_not_inline_navigation():
    import inspect
    import app.main_window as main_window

    source = inspect.getsource(main_window)

    assert "WorkspaceShell" in source
    assert "class Sidebar" not in source
    assert "QStackedWidget" not in source


def test_portfolio_workspace_uses_portfolio_service_boundary_only():
    import inspect
    import app.panels.portfolio_panel as portfolio_panel

    source = inspect.getsource(portfolio_panel)

    assert "from services.portfolio_service import PortfolioService" in source
    assert "from domain.portfolio import Position" in source
    assert 'tabs.addTab(self._portfolio_overview_section(), "Portfolio Overview")' in source
    assert 'tabs.addTab(self._positions_grid_section(), "Positions Grid")' in source
    assert 'tabs.addTab(self._exposure_dashboard_section(), "Exposure Dashboard")' in source
    assert 'tabs.addTab(self._scenario_dashboard_section(), "Scenario Dashboard")' in source
    assert 'tabs.addTab(self._pnl_explain_dashboard_section(), "PnL Explain Dashboard")' in source
    assert "PortfolioService.run_scenario()" in source
    assert "RiskFactorExposure" in source
    assert "PnL Explain" in source
    assert "Scenario Analysis" not in source
    assert "from models" not in source
    assert "from instruments" not in source
    assert "from risk" not in source
    assert "from curves" not in source


def test_risk_workspace_uses_unified_risk_service_boundary_only():
    import inspect
    import app.panels.risk_workspace as risk_workspace

    source = inspect.getsource(risk_workspace)

    assert "from services.risk_service import RiskService" in source
    assert 'tabs.addTab(self._var_tab(), "VaR")' in source
    assert 'tabs.addTab(self._stress_tab(), "Stress")' in source
    assert 'tabs.addTab(self._backtesting_tab(), "Backtesting")' in source
    assert 'tabs.addTab(self._capital_tab(), "Capital")' in source
    assert "from app.panels.var_panel" not in source
    assert "from app.panels.histvar_panel" not in source
    assert "from app.panels.stress_panel" not in source
    assert "from risk" not in source


def test_market_data_workspace_uses_market_data_service_boundary_only():
    import inspect
    import app.panels.market_workspace as market_workspace

    source = inspect.getsource(market_workspace)

    assert "from services.market_data_service import MarketDataService" in source
    assert 'tabs.addTab(self._curve_explorer_tab(), "Curve Explorer")' in source
    assert 'tabs.addTab(self._fx_explorer_tab(), "FX Explorer")' in source
    assert 'tabs.addTab(self._vol_surface_explorer_tab(), "Vol Surface Explorer")' in source
    assert 'tabs.addTab(self._credit_curve_explorer_tab(), "Credit Curve Explorer")' in source
    assert "snapshot_lineage" in source
    assert "MarketDataStore" in source
    assert "Quality" in source
    assert "Lineage" in source
    assert "from app.panels.yield_curve_panel" not in source
    assert "from app.panels.volsurface_panel" not in source
    assert "from curves" not in source
    assert "YieldCurve" not in source
    assert "MarketDataSnapshot" not in source
    assert "MarketDataSource" not in source


def test_pricing_workspace_uses_pricing_service_boundary_only():
    import inspect
    import app.panels.pricing_workspace as pricing_workspace

    source = inspect.getsource(pricing_workspace)

    # Service boundary preserved (provenance shown per result in the detail screen)
    assert "from services.pricing_service import PricingService" in source
    # Interactive instrument hub: 7 category tabs driven by the product catalogue
    assert "from app.panels.pricing_catalogue import CATEGORIES" in source
    assert "PricingDetailScreen" in source
    assert "for category in CATEGORIES" in source

    # The 7 categories each expose at least one service-backed product
    from app.panels.pricing_catalogue import CATEGORIES, products_by_category
    assert CATEGORIES == ["Fixed Income", "Option", "Equity", "FX", "Swaps",
                          "Structured Notes", "Credit"]
    for category in CATEGORIES:
        assert products_by_category(category), f"{category} has no products"
    # Service boundary preserved: no direct engine imports (UI submodules are fine).
    assert "from models" not in source
    assert "from instruments" not in source
    assert "from curves" not in source
    assert "from risk." not in source


def test_analytics_lab_workspace_is_research_boundary_only():
    import inspect
    import app.panels.analytics_workspace as analytics_workspace

    source = inspect.getsource(analytics_workspace)

    assert "from services.governance_service import GovernanceService" in source
    assert 'tabs.addTab(self._section_tab("Rates Models"), "Rates Models")' in source
    assert 'tabs.addTab(self._section_tab("Volatility Models"), "Volatility Models")' in source
    assert 'tabs.addTab(self._section_tab("Monte Carlo"), "Monte Carlo")' in source
    assert 'tabs.addTab(self._section_tab("Research Sandbox"), "Research Sandbox")' in source
    assert '"PRODUCTION"' in source
    assert '"RESEARCH"' in source
    assert "allow_analytics_lab=True" in source
    assert "from app.panels" not in source
    assert "from models" not in source
    assert "from instruments" not in source
    assert "from curves" not in source
    assert "from risk" not in source
