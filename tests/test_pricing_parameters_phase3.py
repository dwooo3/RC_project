"""Phase 3 — Parameters card: 2-column grid (label above field), full-width cells
for curves/schedules, and scroll-only-when-overflowing.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QScrollArea


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _screen(product_id):
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen
    from services.pricing_service import PricingService
    product = next(p for p in PRODUCTS if p.id == product_id)
    return PricingDetailScreen(product, PricingService())


def test_parameters_use_grid_and_scroll(app):
    scr = _screen("bond")
    assert isinstance(scr._param_scroll, QScrollArea)
    # all product input fields are present in the grid
    from app.panels.pricing_catalogue import PRODUCTS
    bond = next(p for p in PRODUCTS if p.id == "bond")
    assert {f.key for f in bond.fields} <= set(scr._inputs.keys())


def test_short_fields_lay_out_two_per_row(app):
    scr = _screen("bond")
    grid = scr._param_grid
    # first two short fields occupy row 0, columns 0 and 1
    first = scr._inputs[next(iter(scr._inputs))].parentWidget()
    r0, c0, rs0, cs0 = grid.getItemPosition(grid.indexOf(first))
    assert (r0, c0, cs0) == (0, 0, 1)


def test_curve_selector_is_full_width(app):
    scr = _screen("bond")           # discount-only curve product
    assert scr._disc_combo is not None
    cell = scr._disc_combo.parentWidget()
    _r, _c, _rs, cs = scr._param_grid.getItemPosition(scr._param_grid.indexOf(cell))
    assert cs == 2                  # spans both columns


def test_wide_schedule_field_spans_two_columns(app):
    scr = _screen("custom_bond")    # has the wide manual-cashflows field
    assert "cashflows" in scr._inputs
    cell = scr._inputs["cashflows"].parentWidget()
    _r, _c, _rs, cs = scr._param_grid.getItemPosition(scr._param_grid.indexOf(cell))
    assert cs == 2


def test_scroll_is_only_as_needed(app):
    from PySide6.QtCore import Qt
    scr = _screen("bond")
    assert scr._param_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert scr._param_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
