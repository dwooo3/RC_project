"""
Model visibility + parameter editing in the pricing UI: every product exposes a
model, the detail screen shows a model selector + governance summary + a
"Model & parameters…" popup, and selecting an engine changes the price.
"""
import pytest
from PySide6.QtWidgets import QApplication, QComboBox

from app.panels.pricing_catalogue import PRODUCTS
from app.panels.pricing_detail import PricingDetailScreen
from app.panels.model_params_dialog import ModelParamsDialog, model_metadata
from services.pricing_service import PricingService


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def by_id():
    return {p.id: p for p in PRODUCTS}


# ── coverage: every product has a visible model ──────────

def test_every_product_exposes_a_model():
    for p in PRODUCTS:
        assert p.engines(), f"{p.id} has no model to display"
        assert p.primary_model() in p.engines()


def test_multi_model_products_have_selectors(by_id):
    for pid in ("vanilla", "american", "swaption", "convertible", "cap_floor", "cds", "barrier"):
        assert len(by_id[pid].engines()) > 1, f"{pid} should offer multiple models"


# ── detail screen wiring ─────────────────────────────────

@pytest.mark.parametrize("pid", ["vanilla", "bond", "american", "convertible", "irs", "cds"])
def test_detail_screen_shows_model(app, by_id, pid):
    scr = PricingDetailScreen(by_id[pid], PricingService())
    assert scr._engine_combo is not None
    assert scr._model_summary is not None and scr._model_summary.text()
    btn = scr.findChild(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton,
                        "model_params_button")
    assert btn is not None
    assert scr._values().get("__engine") == scr._engine_combo.currentText()


# ── pop-up dialog ────────────────────────────────────────

def test_dialog_multi_model_has_combo_and_params(app, by_id):
    dlg = ModelParamsDialog(by_id["vanilla"].engines(), "heston_cf", {}, None)
    assert dlg._combo is not None and dlg.selected_engine() == "heston_cf"
    rv = dlg.result_values()
    assert rv["__engine"] == "heston_cf"
    assert {"v0", "kappa", "theta", "xi", "rho"} <= set(rv)


def test_dialog_single_model_no_combo(app, by_id):
    dlg = ModelParamsDialog(by_id["bond"].engines(), "fixed_bond", {}, None)
    assert dlg._combo is None
    assert dlg.result_values() == {"__engine": "fixed_bond"}     # analytic, no params


def test_dialog_afv_params(app, by_id):
    dlg = ModelParamsDialog(by_id["convertible"].engines(), "afv_convertible", {}, None)
    assert {"lam0", "alpha", "recovery"} <= set(dlg.result_values())


def test_model_metadata_governance():
    m = model_metadata("cgmy")
    assert m["status"] == "Approximation" and m["family"] == "levy"
    assert model_metadata("heston_cf")["asset_class"] == "equity"


# ── engine selection drives pricing ──────────────────────

def _price(by_id, pid, **eng):
    p = by_id[pid]
    v = {f.key: f.default for f in p.fields}
    v.update(eng)
    return p.price(PricingService(), v)


def test_engine_selection_changes_price(by_id):
    a_pde = _price(by_id, "american", __engine="pde_cn")["value"]
    a_baw = _price(by_id, "american", __engine="baw")["value"]
    assert a_pde > 0 and a_baw > 0 and abs(a_pde - a_baw) > 1e-4
    tf = _price(by_id, "convertible", __engine="convertible_bond")["value"]
    afv = _price(by_id, "convertible", __engine="afv_convertible")["value"]
    assert tf > 0 and afv > 0 and abs(tf - afv) > 1.0
    blk = _price(by_id, "cap_floor", __engine="capfloor")["value"]
    lmm = _price(by_id, "cap_floor", __engine="lmm")["value"]
    assert blk > 0 and lmm > 0 and blk != lmm


def test_american_model_id_reflects_engine(by_id):
    for eng in ("pde_cn", "baw", "bjerksund_stensland"):
        assert _price(by_id, "american", __engine=eng)["model_id"] == eng
