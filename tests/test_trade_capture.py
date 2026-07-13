"""Trade capture gate: every capturable workstation product must map to a
Position the PortfolioService can actually revalue, and the book must
round-trip through AppDB persistence."""

from __future__ import annotations

import math

import pytest

from api.pricing_workstation import PRODUCTS, TO_POSITION, find_product, to_position
from domain.portfolio import Position
from infra.db.app_db import AppDB
from services.portfolio_service import PortfolioService
from services.pricing_service import PricingService


def _default_values(product) -> dict:
    engine = product.engines[0]
    return {s.key: s.default for s in product.params_for(engine, [], [])}


@pytest.mark.parametrize("product_id", sorted(TO_POSITION))
def test_captured_position_reprices(product_id):
    product = find_product(product_id)
    assert product is not None, f"{product_id} in TO_POSITION but not in PRODUCTS"
    inst, params, desc = to_position(product_id, _default_values(product))
    assert desc

    ps = PortfolioService()
    ps.add(Position(id=f"t_{product_id}", instrument=inst, quantity=1.0,
                    description=desc, params=params))
    ps.price_all()
    pos = ps.positions[0]
    assert not pos.errors, f"{product_id} -> {inst}: {pos.errors}"
    assert pos.market_value == pos.market_value, f"{product_id}: NaN market value"


def test_non_capturable_products_return_none():
    non_capturable = [p.id for p in PRODUCTS if p.id not in TO_POSITION]
    assert non_capturable, "expected some products without a portfolio route"
    for pid in non_capturable:
        assert to_position(pid, {}) is None


def test_fx_forward_default_strike_is_fair_forward():
    product = find_product("fx_forward")
    values = _default_values(product)          # forward_agreed defaults to 0
    _, params, _ = to_position("fx_forward", values)
    fair = params["S"] * math.exp((params["r_d"] - params["r_f"]) * params["T"])
    assert params["K"] == pytest.approx(fair)


def test_fx_forward_capture_preserves_notional_price_and_factor_identity():
    values = _default_values(find_product("fx_forward"))
    values.update({"forward_agreed": 95.0, "notional": 1_000_000.0,
                   "secid": "EuU6"})
    inst, params, desc = to_position("fx_forward", values, "fx_forward")
    expected = PricingService().price_fx_forward(
        values["S"], values["r_d"], values["r_f"], values["T"],
        values["notional"], values["forward_agreed"])["value"]

    ps = PortfolioService()
    ps.add(Position(id="ws_fx", instrument=inst, quantity=1.0,
                    description=desc, params=params))
    ps.price_all()

    assert params["notional"] == values["notional"]
    assert params["secid"] == "EuU6"
    assert params["ccy_pair"] == "EUR/RUB"
    assert ps.positions[0].market_value == pytest.approx(expected)


def test_fx_forward_legacy_quantity_notional_is_not_multiplied_twice():
    params = {"S": 90.0, "K": 91.0, "r_d": 0.10, "r_f": 0.045,
              "T": 0.25, "ccy_pair": "USD/RUB"}
    expected = PricingService().price_fx_forward(
        params["S"], params["r_d"], params["r_f"], params["T"],
        1_000_000, params["K"])["value"]
    ps = PortfolioService()
    ps.add(Position(id="legacy_fx", instrument="fx_forward",
                    quantity=1_000_000, description="legacy", params=params))

    ps.price_all()

    assert ps.positions[0].market_value == pytest.approx(expected)


@pytest.mark.parametrize(
    ("secid", "pair"),
    [("EURRUB_TOM", "EUR/RUB"), ("CNYRUB_TOM", "CNY/RUB"),
     ("EUR_RUB__TOM", "EUR/RUB")],
)
def test_fx_forward_capture_maps_spot_fx_identity(secid, pair):
    values = _default_values(find_product("fx_forward"))
    values["secid"] = secid

    _, params, _ = to_position("fx_forward", values)

    assert params["secid"] == secid
    assert params["ccy_pair"] == pair


def test_cds_capture_preserves_flat_hazard_price():
    values = _default_values(find_product("cds"))
    values.update({"spread": 0.01, "hazard": 0.02})
    inst, params, desc = to_position("cds", values, "cds")
    expected = PricingService().price_cds(
        values["notional"], values["spread"], values["T"],
        int(values["freq"]), values["hazard"], values["r"],
        values["recovery"])["value"]

    ps = PortfolioService()
    ps.add(Position(id="ws_cds", instrument=inst, quantity=1.0,
                    description=desc, params=params))
    ps.price_all()

    assert params["hazard"] == values["hazard"]
    assert ps.positions[0].market_value == pytest.approx(expected)
    assert ps.positions[0].model_status == "Validated"


def test_book_roundtrips_through_appdb():
    db = AppDB(":memory:")
    ps = PortfolioService()
    ps.portfolio.portfolio_id = "test_book"
    inst, params, desc = to_position("irs", _default_values(find_product("irs")))
    ps.add(Position(id="ws_irs_001", instrument=inst, quantity=2.0,
                    description=desc, params=params))
    ps.save_to_db(db)

    loaded = PortfolioService.load_from_db(db, "test_book")
    assert [p.id for p in loaded.positions] == ["ws_irs_001"]
    pos = loaded.positions[0]
    assert pos.quantity == 2.0
    assert pos.params["notional"] == params["notional"]
    loaded.price_all()
    assert not loaded.positions[0].errors


def test_portfolio_mutation_invalidates_hyppl_cache():
    from api import marketrisk
    marketrisk._CACHE[("snap", 500)] = {"pnl": [1.0]}
    marketrisk.invalidate_cache()
    assert marketrisk._CACHE == {}
