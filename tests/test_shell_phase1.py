"""Phase 1 — shell chrome in the new light design.

Floating rounded sidebar tile (brand, flat nav, active pill, no account row),
toolbar without subtitle + per-workspace controls slot, and the SegmentedControl
primitive. Visibility is checked with ``not isHidden()`` (offscreen ``isVisible``
is unreliable).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from ui.theme import PALETTE


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_sidebar_is_floating_rounded_card(app):
    from ui.shell import GlobalNavigation, NAV_ITEMS
    nav = GlobalNavigation(lambda key: None)
    assert nav.width() == 240
    ss = nav.styleSheet()
    assert PALETTE.bg_card in ss and "border-radius:16px" in ss
    assert nav.graphicsEffect() is not None          # elevation shadow
    assert set(nav._buttons.keys()) == {k for _d, k in NAV_ITEMS}


def test_sidebar_has_no_account_or_footer(app):
    import inspect
    from ui import shell
    src = inspect.getsource(shell.GlobalNavigation)
    assert "DEMO data" not in src        # old footer removed
    assert "Dmitrii" not in src          # no account row
    assert "Market Risk Workstation" not in src  # subtitle removed


def test_sidebar_select_invokes_callback(app):
    from ui.shell import GlobalNavigation
    seen = []
    nav = GlobalNavigation(lambda key: seen.append(key))
    nav.select_key("pricing")
    assert seen[-1] == "pricing"
    assert nav._buttons["pricing"].isChecked()


def test_toolbar_drops_subtitle_and_has_controls_slot(app):
    from ui.shell import WorkspaceHeaderBar
    bar = WorkspaceHeaderBar()
    bar.set_workspace("pricing")
    assert bar.title.text() == "Pricing"
    assert bar.subtitle.isHidden()       # subtitle kept but not shown
    assert hasattr(bar, "set_controls")
    from PySide6.QtWidgets import QLabel
    probe = QLabel("X")
    bar.set_controls(probe)
    assert bar._controls.count() == 1


def test_segmented_control_switches(app):
    from ui.components import SegmentedControl
    events = []
    seg = SegmentedControl(["Fixed Income", "Options", "Equity"], on_change=events.append)
    assert seg.current_index() == 0
    seg.set_current_index(2)
    assert seg.current_index() == 2
    assert PALETTE.accent in seg._buttons[0].styleSheet()


def test_workspace_shell_regions_present(app):
    from ui.shell import WorkspaceShell
    shell = WorkspaceShell(lambda key: __import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget())
    for region in ("global_navigation", "workspace_header", "context_bar", "status_bar", "content_area"):
        assert hasattr(shell, region)
