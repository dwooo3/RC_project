"""UI replatforming architecture tests."""

import inspect

from ui import components
from ui import theme


def test_shared_ui_component_library_exports_required_components():
    assert hasattr(components, "WorkspacePage")
    assert hasattr(components, "WorkspaceCard")
    assert hasattr(components, "KpiCard")
    assert hasattr(components, "StatusChip")
    assert hasattr(components, "WarningBanner")
    assert hasattr(components, "CommandBar")
    assert hasattr(components, "ContextDrawer")
    assert hasattr(components, "DenseTable")
    assert hasattr(components, "KpiStrip")


def test_theme_ownership_lives_under_ui_theme():
    # Active palette is the new light theme (design migration v1); the historical
    # dark values are preserved on the DARK palette.
    assert theme.PALETTE is theme.LIGHT
    assert theme.DARK.bg0 == "#0B0D10"
    assert theme.DARK.bg_topbar == "#0F1216"
    assert theme.DARK.accent == "#D97757"
    assert theme.PALETTE.accent == "#D9633F"
    assert isinstance(theme.APP_STYLE, str)
    assert isinstance(theme.LIGHT_STYLE, str)
    assert isinstance(theme.WORKSTATION_STYLE, str)


def test_dashboard_uses_shared_cards_not_local_duplicate_card_classes():
    import app.panels.dashboard_panel as dashboard_panel

    source = inspect.getsource(dashboard_panel)

    assert "class _KpiCard" not in source
    assert "class _NavCard" not in source
    assert "KpiStrip(" in source
    assert "WorkstationPanel(" in source
    assert "DenseTable(" in source
    assert "StatusChip(" in source


def test_app_widgets_reexports_shared_components_for_backward_compatibility():
    import app.widgets as widgets

    assert widgets.MetricCard is components.KpiCard
    assert widgets.Banner is components.WarningBanner
    assert widgets.ModelStatusBadge is components.StatusChip
