"""Canonical component risk for the Pricing_new multi-asset autocall."""

from __future__ import annotations

from datetime import date

import pytest

from api import marketrisk
from domain.market_data import MarketDataSnapshot
from domain.portfolio import Position
from services.portfolio_service import PortfolioService


def _snapshot(snapshot_id: str = "snapshot-autocall") -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id=snapshot_id,
        valuation_date=date(2026, 7, 18),
        source="MOEX",
        quality="PRODUCTION",
    )


def _params(*, assets=None, kinds=None, sigmas=None, snapshot_id="snapshot-autocall"):
    return {
        "component_secids": ["AAA", "BOND1"],
        "component_kinds": kinds or ["equity", "bond"],
        "assets": assets or [80.0, 90.0],
        "reference_spots": [100.0, 100.0],
        "sigmas": sigmas or [0.0, 0.0],
        "incomes": [0.0, 0.0],
        "weights": [0.5, 0.5],
        "correlation": [[1.0, 0.0], [0.0, 1.0]],
        "resolved_snapshot_id": snapshot_id,
        "r": 0.0,
        "T": 1.0,
        "observation_dates": [1.0],
        "autocall_barrier": 5.0,
        "autocall_aggregation": "best_of",
        "coupon_barrier": 0.0,
        "coupon_aggregation": "worst_of",
        "coupon_rate": 0.0,
        "guaranteed_coupon": 0.0,
        "memory_coupon": True,
        "protection_barrier": 0.95,
        "protection_aggregation": "worst_of",
        "protection_monitoring": "maturity",
        "notional": 1_000.0,
        "n_sims": 1_000,
        "steps": 1,
        "seed": 31,
    }


def _service(params=None, *, snapshot_id="snapshot-autocall") -> PortfolioService:
    service = PortfolioService(snapshot=_snapshot(snapshot_id))
    service.add(Position(
        id="autocall",
        instrument="multi_asset_autocall",
        description="seasoned two-asset note",
        quantity=1.0,
        params=params or _params(snapshot_id=snapshot_id),
    ))
    return service


def test_full_reprice_routes_each_spot_without_resetting_reference_levels():
    service = _service()

    first = service.full_reprice_pnl(
        dS_by_name={"AAA": 0.10, "BOND1": 0.0}
    )
    second = service.full_reprice_pnl(
        dS_by_name={"AAA": 0.0, "BOND1": 0.10}
    )

    # Base worst-of = 80%. Moving AAA to 88% changes redemption to 88%;
    # moving only BOND1 leaves AAA as the worst component at 80%.
    assert first["base_value"] == pytest.approx(800.0)
    assert first["pnl"] == pytest.approx(80.0)
    assert second["pnl"] == pytest.approx(0.0)


def test_global_equity_vol_proxy_does_not_shock_bond_model_volatility():
    params = _params(sigmas=[0.0, 0.20])
    service = _service(params)

    result = service.full_reprice_pnl(dvol=0.10)
    equity_only = service.full_reprice_pnl(
        dvol=0.0, dvol_by_name={"AAA": 0.10}
    )

    # The global equity-vol proxy is identical to an explicit equity-only move:
    # the bond component does not inherit it.
    assert result["pnl"] == pytest.approx(equity_only["pnl"], abs=1e-12)
    assert any(
        "equity-IV/RVI proxy is forbidden" in warning
        for warning in result["warnings"]
    )


def test_portfolio_value_exposes_named_component_greeks():
    service = _service(_params(assets=[80.0, 80.0]))

    valuation = service.value()
    position = valuation.positions[0]
    exposures = {row.factor_id: row.sensitivity for row in position.exposures}

    assert valuation.errors == []
    assert position.price == pytest.approx(800.0)
    assert position.delta == pytest.approx(10.0)
    assert "equity.aaa.spot" in exposures
    assert "equity.bond1.spot" in exposures
    assert position.metadata["pricing_diagnostics"]["greeks_method"] == (
        "central_fd_common_random_numbers_with_parallel_cross_gamma"
    )


def test_repricing_fails_closed_when_resolved_snapshot_is_not_bound():
    service = _service(
        _params(snapshot_id="snapshot-old"),
        snapshot_id="snapshot-current",
    )

    with pytest.raises(ValueError, match="not bound snapshot"):
        service.full_reprice_pnl()


def test_market_risk_discovers_spot_for_all_components_but_no_bond_iv():
    service = _service()

    assert marketrisk._book_secids(service) == ["AAA", "BOND1"]
    assert marketrisk._book_vol_names(service) == ["AAA"]
    assert marketrisk._book_component_kinds(service) == {
        "AAA": "equity",
        "BOND1": "bond",
    }


def test_missing_component_kind_fails_before_factor_history_resolution():
    params = _params()
    params["component_kinds"] = ["equity"]
    service = _service(params)

    with pytest.raises(ValueError, match="component_kinds has 1 entries"):
        marketrisk._book_vol_names(service)
