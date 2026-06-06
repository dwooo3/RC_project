"""Phase 4 — Pricing result states: idle, input-validation error (with field
highlight), recovery, and the demo/stale market-data banner.
Visibility is checked with ``not isHidden()`` (offscreen ``isVisible`` is False).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QLineEdit


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _bond():
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen
    from services.pricing_service import PricingService
    bond = next(p for p in PRODUCTS if p.id == "bond")
    return PricingDetailScreen(bond, PricingService())


def _first_numeric_field(scr):
    for f in scr.product.fields:
        if isinstance(scr._inputs[f.key], QLineEdit) and not isinstance(f.default, str):
            return f.key
    raise AssertionError("no numeric field")


def test_idle_state_before_calculate(app):
    scr = _bond()
    assert scr._price_label.text() == "—"
    assert not scr._add_btn.isEnabled()
    assert scr._cf_table.isHidden()
    assert "Calculate" in scr._prov_sub.text()


def test_invalid_input_highlights_field_and_blocks(app):
    scr = _bond()
    key = _first_numeric_field(scr)
    scr._inputs[key].setText("abc")
    scr.calculate()
    assert not scr._error_label.isHidden()
    assert scr._inputs[key].property("invalid") == "true"
    assert not scr._add_btn.isEnabled()
    assert scr._last_result is None


def test_recovers_after_fixing_input(app):
    scr = _bond()
    key = _first_numeric_field(scr)
    good = scr._inputs[key].text()
    scr._inputs[key].setText("abc")
    scr.calculate()
    scr._inputs[key].setText(good)
    scr.calculate()
    assert scr._error_label.isHidden()
    assert scr._inputs[key].property("invalid") == "false"
    assert scr._add_btn.isEnabled()
    assert scr._last_result is not None


def test_stale_banner_matches_source(app):
    scr = _bond()
    scr.calculate()
    res = scr._last_result
    src = str(res.get("market_data_source") or "").upper()
    snap = (res.get("market_data_snapshot_id") or "").lower()
    expected = src in {"DEMO", "MANUAL"} or "demo" in snap
    assert (not scr._stale_label.isHidden()) == expected


def test_mark_invalid_helper_toggles_property(app):
    from ui.components import mark_invalid
    w = QLineEdit("x")
    mark_invalid(w, True)
    assert w.property("invalid") == "true"
    mark_invalid(w, False)
    assert w.property("invalid") == "false"
