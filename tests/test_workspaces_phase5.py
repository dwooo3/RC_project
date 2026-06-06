"""Phase 5 — light language rolled out to the standard workspaces.

The shell toolbar owns the page title, so WorkstationWorkspace no longer renders a
duplicate title; section panels and KPI tiles float with an elevation shadow; all
six product workspaces construct and render light.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QLabel

from ui.theme import PALETTE


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_workspace_header_omits_empty_title(app):
    from ui.components import WorkspaceHeader
    hdr = WorkspaceHeader("", "", chips=[QLabel("DEMO")], actions=[])
    labels = [w.text() for w in hdr.findChildren(QLabel)]
    assert labels == ["DEMO"]            # no title/subtitle labels, only the chip


def test_workstation_workspace_has_no_duplicate_title(app):
    from ui.layouts import WorkstationWorkspace
    from ui.components import WorkspaceHeader
    ws = WorkstationWorkspace("Risk", "should not be shown")
    # With no chips/actions, no header (hence no title) is rendered at all.
    assert ws.findChildren(WorkspaceHeader) == []


def test_panels_and_kpis_are_elevated(app):
    from ui.components import WorkstationPanel, KpiCard
    assert WorkstationPanel("X").graphicsEffect() is not None
    assert KpiCard("MV", "1.0").graphicsEffect() is not None


def test_cards_use_light_surface(app):
    from ui.components import WorkstationPanel
    assert PALETTE.bg_card in WorkstationPanel("X").styleSheet()


@pytest.mark.parametrize("key", ["dashboard", "portfolio", "risk", "market",
                                 "governance", "analytics"])
def test_each_workspace_constructs(app, key):
    from app.main_window import MainWindow
    win = MainWindow()
    win.shell.select_workspace(key)
    panel = win.shell._panels[key]
    assert not panel.isHidden()
