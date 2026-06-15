"""Structured notes on baskets of real instruments — engine, resolver, service, UI."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings

import numpy as np
import pytest

warnings.filterwarnings("ignore")

from instruments.structured.basket_note import (
    Constituent, basket_note, nearest_correlation,
)
from services.pricing_service import PricingService


def _equity_basket():
    return [
        Constituent("A", "equity", spot=100.0, weight=0.5, vol=0.30, income=0.0),
        Constituent("B", "equity", spot=50.0, weight=0.5, vol=0.25, income=0.02),
    ]


# ── engine ────────────────────────────────────────────────────────────
def test_protection_floors_capital():
    """A 100%-protected note never redeems capital below par (ex-coupon)."""
    res = basket_note(_equity_basket(), r=0.10, T=2.0, principal_protection=1.0,
                      participation=1.0, n_sims=20_000)
    # capital-loss probability is on redemption (capital + upside); with full
    # protection redemption >= 1 always.
    assert res["capital_loss_prob"] == 0.0
    assert res["bond_floor"] == pytest.approx(1000 * np.exp(-0.10 * 2.0), rel=1e-9)


def test_no_protection_tracks_basket():
    """0% protection + 100% participation ≈ delta-one basket certificate (perf)."""
    res = basket_note(_equity_basket(), r=0.10, T=1.0, principal_protection=0.0,
                      participation=1.0, n_sims=40_000)
    # Expected redemption ratio ≈ expected basket performance.
    assert res["bond_floor"] == 0.0
    assert res["price_ratio"] == pytest.approx(res["expected_perf"] * np.exp(-0.10), rel=0.02)


def test_par_at_fair_participation():
    """Pricing the note at its fair participation values it at par."""
    base = basket_note(_equity_basket(), r=0.12, T=3.0, principal_protection=1.0,
                       guaranteed_coupon=0.0, participation=1.0, n_sims=40_000)
    fp = base["fair_participation"]
    assert fp is not None and fp > 0
    at_par = basket_note(_equity_basket(), r=0.12, T=3.0, principal_protection=1.0,
                         guaranteed_coupon=0.0, participation=fp, n_sims=40_000)
    assert at_par["price"] == pytest.approx(at_par["price"] / at_par["price_ratio"], rel=1e-6)
    assert at_par["price_ratio"] == pytest.approx(1.0, abs=1e-4)


def test_worst_of_cheaper_than_average():
    """Worst-of basket upside is weaker, so the note is worth less than average."""
    kw = dict(r=0.10, T=2.0, principal_protection=1.0, participation=1.0, n_sims=40_000)
    avg = basket_note(_equity_basket(), basket_type="average", **kw)
    wof = basket_note(_equity_basket(), basket_type="worst_of", **kw)
    assert wof["price"] < avg["price"]


def test_guaranteed_coupon_adds_pv():
    no_cpn = basket_note(_equity_basket(), r=0.10, T=3.0, principal_protection=1.0,
                         guaranteed_coupon=0.0, n_sims=10_000)
    with_cpn = basket_note(_equity_basket(), r=0.10, T=3.0, principal_protection=1.0,
                           guaranteed_coupon=0.06, coupon_freq=2, n_sims=10_000)
    assert with_cpn["guaranteed_coupon_pv"] > 0
    assert with_cpn["price"] > no_cpn["price"]


def test_nearest_correlation_is_pd():
    bad = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    fixed = nearest_correlation(bad)
    np.linalg.cholesky(fixed)  # must not raise
    assert np.allclose(np.diag(fixed), 1.0)


def test_empty_basket_raises():
    with pytest.raises(ValueError):
        basket_note([], r=0.1, T=1.0)


# ── service + resolver ────────────────────────────────────────────────
def test_service_governed_result():
    svc = PricingService()
    specs = [{"secid": "SBER", "kind": "equity", "weight": 0.6},
             {"secid": "GAZP", "kind": "equity", "weight": 0.4}]
    res = svc.price_basket_note(specs, r=0.16, T=3.0, principal_protection=1.0,
                                guaranteed_coupon=0.05, n_sims=8_000)
    assert res["value"] is not None and not res["errors"]
    assert res["model_id"] == "structured_basket_note"
    assert res["model_status"]  # governed status present
    assert res["raw"]["fair_participation"] is not None


def test_resolver_returns_constituents_and_pd_corr():
    svc = PricingService()
    specs = [{"secid": "SBER", "kind": "equity", "weight": 1.0},
             {"secid": "SU26238RMFS4", "kind": "bond", "weight": 1.0}]
    constituents, corr = svc.market_data.basket_market_inputs(specs, T=3.0)
    assert len(constituents) == 2
    assert all(c.spot > 0 and c.vol > 0 for c in constituents)
    np.linalg.cholesky(nearest_correlation(corr))  # estimable + PD-fixable


def test_basket_universe_kinds():
    svc = PricingService()
    for kind in ("equity", "bond", "index", "all"):
        uni = svc.market_data.basket_universe(kind)
        assert isinstance(uni, list) and uni
        assert all({"secid", "kind", "label"} <= set(u) for u in uni)


# ── catalogue + UI ────────────────────────────────────────────────────
def test_catalogue_product_prices_generically():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.panels.pricing_catalogue import PRODUCTS
    from app.panels.pricing_detail import PricingDetailScreen

    product = next(p for p in PRODUCTS if p.id == "basket_note")
    assert product.custom_screen is not None
    screen = PricingDetailScreen(product, PricingService())
    screen.calculate()
    assert screen._last_result["value"] is not None
    assert not screen._last_result["errors"]


def test_builder_panel_constructs_and_prices():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.panels.basket_builder_panel import BasketBuilderPanel

    panel = BasketBuilderPanel()
    assert panel._universe  # real or demo universe loaded
    panel._add_row("SBER", "equity", 0.5)
    panel._add_row("GAZP", "equity", 0.5)
    panel.calculate()
    assert panel.banner.text() == ""  # priced without error
    assert panel.grid._cards["Fair Value"]._val_lbl.text() not in ("—", "")
