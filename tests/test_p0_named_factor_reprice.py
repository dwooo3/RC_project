"""MR-4: executable named curves/surfaces and snapshot-bound repricing."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from api.context import AppContext
from curves.yield_curve import YieldCurve
from domain.portfolio import Position
from infra.db.app_db import AppDB
from risk.vol_surface import VolSurface
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService


def _market():
    market = MarketDataService()
    discount = YieldCurve.flat(0.10, label="DISC")
    projection = YieldCurve.flat(0.06, label="PROJ")
    snapshot = market.create_snapshot(
        snapshot_id="named-2026-07-13",
        valuation_date=date(2026, 7, 13),
        curves={"DISC": discount, "PROJ": projection},
        vol_surfaces={"EQ_SURFACE": {"type": "flat", "vol": 0.40}},
    )
    return market, snapshot, discount, projection


def test_named_dual_curves_drive_irs_instead_of_captured_flat_r():
    market, snapshot, discount, projection = _market()
    service = PortfolioService(market_data=market, snapshot=snapshot)
    position = Position(
        id="irs", instrument="irs", description="dual curve", quantity=1.0,
        params={
            "notional": 1_000_000.0, "fixed_rate": 0.08, "T": 5.0,
            "freq": 4, "r": 0.99, "pay_fixed": True,
            "curve_id": "DISC", "proj_curve_id": "PROJ",
        },
    )
    service.add(position)

    valuation = service.value()
    expected = service.pricing.price_irs(
        1_000_000.0, 0.08, 5.0, 4, curve=discount,
        proj_curve=projection, snapshot=snapshot,
        curve_id="DISC", proj_curve_id="PROJ",
    )

    assert valuation.errors == []
    assert position.price == pytest.approx(expected["value"])
    assert position.market_data_snapshot_id == snapshot.snapshot_id
    assert service.portfolio.market_data_snapshot_id == snapshot.snapshot_id
    # The intentionally absurd legacy scalar r must not enter named-curve NPV.
    flat_r_value = service.pricing.price_irs(
        1_000_000.0, 0.08, 5.0, 4,
        curve=market.flat_curve(0.99), pay_fixed=True,
    )["value"]
    assert position.price != pytest.approx(flat_r_value)


def test_named_dual_curve_irs_dv01_is_signed_joint_one_bp_fd():
    market, snapshot, discount, projection = _market()
    service = PortfolioService(market_data=market, snapshot=snapshot)
    quantity = -2.0
    position = Position(
        id="irs-dv01", instrument="irs", description="dual curve DV01",
        quantity=quantity,
        params={
            "notional": 1_000_000.0, "fixed_rate": 0.08, "T": 5.0,
            "freq": 4, "r": 0.99, "pay_fixed": True,
            "curve_id": "DISC", "proj_curve_id": "PROJ",
        },
    )
    service.add(position)

    valuation = service.value()

    def value(disc, proj):
        return service.pricing.price_irs(
            1_000_000.0, 0.08, 5.0, 4, curve=disc,
            proj_curve=proj, pay_fixed=True, snapshot=snapshot,
            curve_id="DISC", proj_curve_id="PROJ",
        )["value"]

    expected = quantity * (
        value(discount.parallel_shift(-1.0), projection.parallel_shift(-1.0))
        - value(discount.parallel_shift(1.0), projection.parallel_shift(1.0))
    ) / 2.0

    assert valuation.errors == []
    assert position.dv01 == pytest.approx(expected)


def test_named_cap_vega_preserves_projection_curve():
    market, snapshot, discount, projection = _market()
    service = PortfolioService(market_data=market, snapshot=snapshot)
    quantity = -2.0
    position = Position(
        id="cap-vega", instrument="cap", description="dual curve cap",
        quantity=quantity,
        params={
            "notional": 1_000_000.0, "K": 0.05, "T": 3.0,
            "freq": 4, "r": 0.99, "vol": 0.25, "opt": "cap",
            "curve_id": "DISC", "proj_curve_id": "PROJ",
        },
    )
    service.add(position)

    valuation = service.value()

    def value(vol):
        return service.pricing.price_cap_floor(
            1_000_000.0, 0.05, 3.0, 4, vol, "cap",
            curve=discount, proj_curve=projection, snapshot=snapshot,
            curve_id="DISC", proj_curve_id="PROJ",
        )["value"]

    expected = quantity * (value(0.26) - value(0.24)) / 0.02 * 0.01

    assert valuation.errors == []
    assert position.vega == pytest.approx(expected)


def test_historical_curve_scenario_shifts_every_native_node():
    market, snapshot, discount, _projection = _market()
    service = PortfolioService(market_data=market, snapshot=snapshot)
    shifts = [(0.25, 0.0010), (2.0, 0.0020), (10.0, 0.0030)]

    shifted = service._shift_curve_object(discount, 0.0, shifts)
    expected_moves = np.interp(
        discount.tenors,
        np.array([tenor for tenor, _ in shifts]),
        np.array([move for _, move in shifts]),
    )

    assert shifted.zero_rates == pytest.approx(
        discount.zero_rates + expected_moves)
    assert shifted.rate(0.25) - discount.rate(0.25) == pytest.approx(0.0010)
    assert shifted.rate(10.0) - discount.rate(10.0) == pytest.approx(0.0030)


def test_named_surface_resolves_current_node_then_applies_vol_scenario():
    market, snapshot, _discount, _projection = _market()
    service = PortfolioService(market_data=market, snapshot=snapshot)
    position = Position(
        id="option", instrument="option", description="surface option",
        quantity=1.0,
        params={
            "S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05,
            "sigma": 0.10, "q": 0.0, "opt": "call",
            "secid": "SBER", "vol_surface_id": "EQ_SURFACE",
        },
    )
    service.add(position)

    valuation = service.value()
    expected_base = service.pricing.price_vanilla_option(
        100.0, 100.0, 1.0, 0.05, 0.40, 0.0, "call",
        snapshot=snapshot,
    )["value"]
    expected_up = service.pricing.price_vanilla_option(
        100.0, 100.0, 1.0, 0.05, 0.41, 0.0, "call",
        snapshot=snapshot,
    )["value"]
    scenario = service.full_reprice_pnl(
        dvol=0.0, dvol_by_name={"SBER": 0.01})

    assert valuation.errors == []
    assert position.price == pytest.approx(expected_base)
    assert scenario["pnl"] == pytest.approx(expected_up - expected_base)
    assert scenario["valid"] is True


@pytest.mark.parametrize(
    ("strike", "tenor", "violated_axis"),
    [(120.0, 1.0, "strike"), (100.0, 3.0, "tenor")],
)
def test_named_surface_rejects_nodes_outside_calibrated_support(
        strike, tenor, violated_axis):
    market = MarketDataService()
    surface = VolSurface(
        np.array([90.0, 100.0, 110.0]),
        np.array([0.5, 1.0, 2.0]),
        np.full((3, 3), 0.30),
        S0=100.0,
        label="bounded",
    )
    snapshot = market.create_snapshot(
        snapshot_id="bounded-surface-2026-07-13",
        valuation_date=date(2026, 7, 13),
        vol_surfaces={"BOUNDED": surface},
    )
    service = PortfolioService(market_data=market, snapshot=snapshot)
    service.add(Position(
        id=f"outside-{violated_axis}", instrument="option",
        description="outside surface support", quantity=1.0,
        params={
            "S": 100.0, "K": strike, "T": tenor, "r": 0.05,
            "sigma": 0.20, "q": 0.0, "opt": "call",
            "secid": "SBER", "vol_surface_id": "BOUNDED",
        },
    ))

    with pytest.raises(ValueError) as exc_info:
        service.full_reprice_pnl()

    message = str(exc_info.value).lower()
    assert "bounded" in message
    assert violated_axis in message
    assert "support" in message


def test_named_projection_curve_rejects_instrument_beyond_max_tenor():
    market = MarketDataService()
    discount = YieldCurve.flat(0.10, label="DISC")
    short_projection = YieldCurve(
        np.array([0.25, 0.50, 1.0]),
        np.array([0.06, 0.06, 0.06]),
        label="PROJ_SHORT",
    )
    snapshot = market.create_snapshot(
        snapshot_id="short-projection-2026-07-13",
        valuation_date=date(2026, 7, 13),
        curves={"DISC": discount, "PROJ_SHORT": short_projection},
    )
    service = PortfolioService(market_data=market, snapshot=snapshot)
    service.add(Position(
        id="irs-too-long", instrument="irs",
        description="projection support breach", quantity=1.0,
        params={
            "notional": 1_000_000.0, "fixed_rate": 0.08, "T": 5.0,
            "freq": 4, "r": 0.10, "pay_fixed": True,
            "curve_id": "DISC", "proj_curve_id": "PROJ_SHORT",
        },
    ))

    with pytest.raises(ValueError) as exc_info:
        service.full_reprice_pnl()

    message = str(exc_info.value).lower()
    assert "proj_short" in message
    assert "tenor" in message
    assert "5" in message


def test_named_dependency_without_bound_snapshot_fails_closed():
    service = PortfolioService()
    service.add(Position(
        id="named", instrument="irs", description="missing snapshot",
        quantity=1.0,
        params={
            "notional": 1_000_000.0, "fixed_rate": 0.08, "T": 5.0,
            "freq": 4, "r": 0.10, "curve_id": "DISC",
        },
    ))

    with pytest.raises(ValueError, match="requires a bound market-data snapshot"):
        service.full_reprice_pnl(dr=0.001)


def test_unsupported_position_cannot_be_silent_zero_risk():
    service = PortfolioService()
    service.add(Position(
        id="unknown", instrument="not_a_product", description="bad",
        quantity=1.0, params={},
    ))

    with pytest.raises(ValueError, match="unsupported portfolio instrument"):
        service.full_reprice_pnl()


def test_app_context_binds_book_and_filtered_book_to_active_snapshot():
    market, snapshot, _discount, _projection = _market()
    context = AppContext()
    context._market = market
    context._snapshot = snapshot
    context._app_db = AppDB(":memory:")

    book = context.portfolio
    filtered = context.filtered_portfolio(book="Trading")

    assert book.market_data is market
    assert book.snapshot is snapshot
    assert book.portfolio.market_data_snapshot_id == snapshot.snapshot_id
    assert filtered.market_data is market
    assert filtered.snapshot is snapshot
    assert all(position.market_data_snapshot_id == snapshot.snapshot_id
               for position in filtered.positions)
