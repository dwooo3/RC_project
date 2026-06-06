"""Pricing workspace UI — every product prices and can be added to the portfolio."""
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


def test_pricing_workspace_constructs(app):
    from app.panels.pricing_workspace import PricingWorkspace
    w = PricingWorkspace()
    assert w is not None


def test_every_catalogue_product_prices(app):
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen
    from services.pricing_service import PricingService
    svc = PricingService()
    failed = []
    for product in PRODUCTS:
        screen = PricingDetailScreen(product, svc)
        screen.calculate()
        res = screen._last_result
        if not res or res.get("value") is None or res.get("errors"):
            failed.append(product.id)
    assert not failed, f"products failed to price: {failed}"


def test_add_to_portfolio_creates_priced_position_with_greeks(app):
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen
    from app.panels.session import shared_portfolio
    from services.pricing_service import PricingService

    svc = PricingService()
    barrier = next(p for p in PRODUCTS if p.id == "barrier")
    screen = PricingDetailScreen(barrier, svc)
    screen.calculate()
    before = len(shared_portfolio().positions)
    screen.add_to_portfolio()
    pf = shared_portfolio()
    pf.value()
    assert len(pf.positions) == before + 1
    pos = pf.positions[-1]
    assert pos.instrument == "barrier"
    assert pos.model_id == "barrier"            # governance provenance carried over
    assert pos.delta != 0 and pos.vega != 0     # sensitivities computed


def test_detail_screen_shows_cashflow_schedule(app):
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen
    from services.pricing_service import PricingService
    svc = PricingService()
    bond = next(p for p in PRODUCTS if p.id == "bond")
    scr = PricingDetailScreen(bond, svc)
    scr.calculate()
    assert not scr._cf_table.isHidden()       # schedule shown for a coupon bond
    assert scr._cf_table.rowCount() > 0


def test_day_count_selectable_on_bond(app):
    from app.panels.pricing_catalogue import PRODUCTS
    bond = next(p for p in PRODUCTS if p.id == "bond")
    keys = {f.key for f in bond.fields}
    assert "day_count" in keys


def test_custom_bond_manual_schedule_prices(app):
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen
    from services.pricing_service import PricingService
    cb = next(p for p in PRODUCTS if p.id == "custom_bond")
    scr = PricingDetailScreen(cb, PricingService())
    scr.calculate()
    assert scr._last_result["value"] > 0


def test_curve_selectors_present_by_role(app):
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen
    from services.pricing_service import PricingService
    svc = PricingService()
    fra = PricingDetailScreen(next(p for p in PRODUCTS if p.id == "fra"), svc)
    assert fra._disc_combo is not None and fra._proj_combo is not None   # dual-curve
    bond = PricingDetailScreen(next(p for p in PRODUCTS if p.id == "bond"), svc)
    assert bond._disc_combo is not None and bond._proj_combo is None     # discount only
    vanilla = PricingDetailScreen(next(p for p in PRODUCTS if p.id == "vanilla"), svc)
    assert vanilla._disc_combo is None                                   # no curve


def test_selecting_projection_curve_changes_fra(app):
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen
    from services.pricing_service import PricingService
    scr = PricingDetailScreen(next(p for p in PRODUCTS if p.id == "fra"), PricingService())
    scr.calculate()
    base = scr._last_result["value"]
    # pick a non-flat snapshot curve for projection
    names = [scr._proj_combo.itemText(i) for i in range(scr._proj_combo.count())]
    pick = next(n for n in names if n not in ("flat(r)",))
    scr._proj_combo.setCurrentText(pick)
    scr.calculate()
    assert scr._last_result["value"] != base       # projection curve drives the forward
