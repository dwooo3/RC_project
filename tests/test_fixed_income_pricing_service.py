"""Fixed-income PricingService boundary tests."""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.market_data import MarketDataSnapshot, MarketDataSource
from domain.results import BondPricingRequest, BondPricingResult
from instruments.fixed_income import fixed_bond
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService


def _manual_flat_snapshot(rate: float = 0.05) -> MarketDataSnapshot:
    market_data = MarketDataService()
    valuation_date = date(2026, 6, 4)
    return MarketDataSnapshot(
        snapshot_id="manual-flat-2026-06-04",
        valuation_date=valuation_date,
        source=MarketDataSource.MANUAL,
        quality=MarketDataSource.MANUAL.value,
        curves={
            "manual_flat": market_data.flat_curve(
                rate,
                label="Manual flat test curve",
                source=MarketDataSource.MANUAL,
                valuation_date=valuation_date,
            )
        },
        metadata={"warning": "Manual flat curve for service boundary test."},
    )


def test_price_bond_flat_curve_baseline_matches_legacy_engine():
    market_data = MarketDataService()
    snapshot = _manual_flat_snapshot()
    direct = fixed_bond(100.0, 0.06, 3.0, 2, snapshot.curves["manual_flat"])

    result = PricingService(market_data=market_data).price_bond(
        100.0,
        0.06,
        3.0,
        2,
        snapshot=snapshot,
        curve_id="manual_flat",
    )

    assert result["errors"] == []
    assert result["value"] == pytest.approx(direct["price"])
    assert result["dirty_price"] == pytest.approx(direct["price"])
    assert result["clean_price"] == pytest.approx(direct["price"])
    assert result["accrued_interest"] == 0.0


def test_price_bond_accepts_request_and_returns_model_metadata():
    snapshot = _manual_flat_snapshot()
    request = BondPricingRequest(
        face=100.0,
        coupon=0.06,
        maturity=3.0,
        frequency=2,
        curve_id="manual_flat",
        currency="RUB",
    )

    result = PricingService().price_bond(request, snapshot=snapshot)

    assert result["model_id"] == "fixed_bond"
    assert result["model_status"] == "Approximation"
    assert result["request"] == request
    assert isinstance(result["bond_result"], BondPricingResult)
    assert result["bond_result"].model_id == "fixed_bond"


def test_price_bond_surfaces_fixed_income_audit_warnings():
    snapshot = _manual_flat_snapshot()

    result = PricingService().price_bond(
        100.0,
        0.06,
        3.0,
        2,
        snapshot=snapshot,
        curve_id="manual_flat",
    )

    warnings = " ".join(result["warnings"])
    assert "regular coupon schedules" in warnings
    assert "ACT/365F" in warnings
    assert "Limitations remain" in warnings
    assert "Duration, convexity, and DV01" in warnings


def test_price_bond_result_contains_market_data_source_metadata():
    snapshot = _manual_flat_snapshot()

    result = PricingService().price_bond(
        100.0,
        0.06,
        3.0,
        2,
        snapshot=snapshot,
        curve_id="manual_flat",
    )

    assert result["market_data_snapshot_id"] == "manual-flat-2026-06-04"
    assert result["market_data_source"] == "MANUAL"
    assert result["market_data_quality"] == "MANUAL"
    assert any("MANUAL" in warning for warning in result["warnings"])
