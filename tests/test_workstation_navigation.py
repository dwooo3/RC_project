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
