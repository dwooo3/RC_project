"""Phase 2 — Pricing Valuation card (v6): metrics grid, cashflow + curve tables,
market-value footer; category selector hosted in the toolbar; inputs-only params.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _bond_screen():
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen
    from services.pricing_service import PricingService
    bond = next(p for p in PRODUCTS if p.id == "bond")
    return PricingDetailScreen(bond, PricingService())


def test_valuation_has_metrics_grid_and_curve_table(app):
    scr = _bond_screen()
    assert scr._metrics is not None
    assert scr._curve_table is not None
    assert scr._mv_value is not None


def test_metrics_populate_on_calculate(app):
    scr = _bond_screen()
    scr.calculate()
    # the 2-column metric grid has widgets after a successful valuation
    assert scr._metrics._grid.count() > 0


def test_market_value_tracks_qty(app):
    scr = _bond_screen()
    scr.calculate()
    assert scr._mv_value.text() not in ("—", "")
    one = scr._mv_value.text()
    scr._qty.setText("10")
    assert scr._mv_value.text() != one          # MV = price × qty updates live


def test_discount_curve_table_shows_for_named_curve(app):
    scr = _bond_screen()
    assert scr._disc_combo is not None
    name = next(scr._disc_combo.itemText(i) for i in range(scr._disc_combo.count())
               if scr._disc_combo.itemText(i) != "flat(r)")
    scr._disc_combo.setCurrentText(name)
    scr.calculate()
    assert not scr._curve_table.isHidden()
    assert scr._curve_table.rowCount() > 0


def test_cashflow_table_gets_pv_columns(app):
    scr = _bond_screen()
    name = next(scr._disc_combo.itemText(i) for i in range(scr._disc_combo.count())
               if scr._disc_combo.itemText(i) != "flat(r)")
    scr._disc_combo.setCurrentText(name)
    scr.calculate()
    assert scr._cf_table.columnCount() == 4      # Time, Cashflow, DF, PV
    # DF column is populated (not the em-dash placeholder) when a curve is chosen
    assert scr._cf_table.item(0, 2).text() != "—"


def test_category_selector_hosted_in_toolbar(app):
    from app.panels.pricing_workspace import PricingWorkspace
    ws = PricingWorkspace()
    controls = ws.header_controls()
    from ui.components import SegmentedControl
    assert isinstance(controls, SegmentedControl)


def test_workspace_calculate_drives_active_screen(app):
    from app.panels.pricing_workspace import PricingWorkspace
    ws = PricingWorkspace()
    ws._calculate()
    active = ws._stack.currentWidget()
    assert active._last_result is not None
