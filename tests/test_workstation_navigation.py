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
    import app.panels.governance_workspace as governance_workspace

    assert hasattr(governance_workspace, "GovernanceWorkspace")


def test_workspace_shell_exports_required_shell_regions():
    import inspect
    from ui.shell import WorkspaceShell

    source = inspect.getsource(WorkspaceShell)

    assert "self.global_navigation" in source
    assert "self.workspace_header" in source
    assert "self.context_bar" in source
    assert "self.status_bar" in source
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
    assert "from models" not in source
    assert "from instruments" not in source
    assert "from risk" not in source
    assert "from curves" not in source
