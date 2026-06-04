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


def test_theme_ownership_lives_under_ui_theme():
    assert theme.PALETTE.bg0 == "#0f0f11"
    assert isinstance(theme.APP_STYLE, str)
    assert isinstance(theme.LIGHT_STYLE, str)


def test_dashboard_uses_shared_cards_not_local_duplicate_card_classes():
    import app.panels.dashboard_panel as dashboard_panel

    source = inspect.getsource(dashboard_panel)

    assert "class _KpiCard" not in source
    assert "class _NavCard" not in source
    assert "KpiCard(" in source
    assert "QuickNavCard(" in source
    assert "StatusChip(" in source


def test_app_widgets_reexports_shared_components_for_backward_compatibility():
    import app.widgets as widgets

    assert widgets.MetricCard is components.KpiCard
    assert widgets.Banner is components.WarningBanner
    assert widgets.ModelStatusBadge is components.StatusChip
