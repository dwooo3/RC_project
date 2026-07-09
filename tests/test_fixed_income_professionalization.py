"""Professional fixed-income convention tests."""

import os
import sys
from datetime import date

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from curves.yield_curve import YieldCurve, year_fraction
from domain.market_data import MarketDataSnapshot, MarketDataSource
from domain.results import BondPricingRequest
from instruments.fixed_income import (
    adjust_business_day,
    fixed_bond,
    generate_coupon_schedule,
    settlement_from_valuation,
)
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService


def test_day_count_conventions_for_known_date_pair():
    start = date(2024, 1, 1)
    end = date(2024, 7, 1)

    assert year_fraction(start, end, "act365") == pytest.approx(182 / 365)
    assert year_fraction(start, end, "act360") == pytest.approx(182 / 360)
    assert year_fraction(start, end, "30360") == pytest.approx(0.5)
    assert year_fraction(2.5) == pytest.approx(2.5)


def test_coupon_schedule_generation_regular_semiannual():
    periods = generate_coupon_schedule(
        issue_date=date(2024, 1, 1),
        maturity_date=date(2025, 1, 1),
        frequency=2,
        day_count="30360",
    )

    assert len(periods) == 2
    assert periods[0].start_date == date(2024, 1, 1)
    assert periods[0].end_date == date(2024, 7, 1)
    assert periods[0].accrual_factor == pytest.approx(0.5)
    assert periods[1].end_date == date(2025, 1, 1)


def test_business_day_adjustment_and_settlement_days():
    assert adjust_business_day(date(2024, 8, 31), "following") == date(2024, 9, 2)
    assert adjust_business_day(date(2024, 8, 31), "preceding") == date(2024, 8, 30)
    assert adjust_business_day(date(2024, 8, 31), "modified-following") == date(2024, 8, 30)
    assert settlement_from_valuation(date(2024, 8, 30), settlement_days=2) == date(2024, 9, 3)


def test_fixed_bond_clean_dirty_accrued_flat_curve_known_example():
    curve = YieldCurve.flat(0.05, source=MarketDataSource.MANUAL)

    result = fixed_bond(
        face=100.0,
        coupon=0.06,
        T=2.0,
        freq=2,
        curve=curve,
        settlement_date=date(2024, 4, 1),
        issue_date=date(2024, 1, 1),
        maturity_date=date(2026, 1, 1),
        day_count="act365",
    )

    expected_times = [
        year_fraction(date(2024, 4, 1), date(2024, 7, 1), "act365"),
        year_fraction(date(2024, 4, 1), date(2025, 1, 1), "act365"),
        year_fraction(date(2024, 4, 1), date(2025, 7, 1), "act365"),
        year_fraction(date(2024, 4, 1), date(2026, 1, 1), "act365"),
    ]
    expected_cashflows = [3.0, 3.0, 3.0, 103.0]
    expected_dirty = sum(cf * np.exp(-0.05 * t) for cf, t in zip(expected_cashflows, expected_times))
    expected_accrued = 3.0 * year_fraction(date(2024, 1, 1), date(2024, 4, 1), "act365") / year_fraction(
        date(2024, 1, 1), date(2024, 7, 1), "act365"
    )

    assert result["dirty_price"] == pytest.approx(expected_dirty)
    assert result["accrued_interest"] == pytest.approx(expected_accrued)
    assert result["clean_price"] == pytest.approx(expected_dirty - expected_accrued)
    assert result["previous_coupon_date"] == date(2024, 1, 1)
    assert result["next_coupon_date"] == date(2024, 7, 1)
    assert result["dv01"] > 0
    assert result["mod_duration"] > 0
    assert result["convexity"] > 0


def test_pricing_service_date_aware_bond_result_contains_governance_and_market_metadata():
    market_data = MarketDataService()
    valuation_date = date(2024, 4, 1)
    snapshot = MarketDataSnapshot(
        snapshot_id="manual-fi-2024-04-01",
        valuation_date=valuation_date,
        source=MarketDataSource.MANUAL,
        quality=MarketDataSource.MANUAL.value,
        curves={
            "manual_flat": market_data.flat_curve(
                0.05,
                label="Manual FI flat curve",
                source=MarketDataSource.MANUAL,
                valuation_date=valuation_date,
            )
        },
    )
    request = BondPricingRequest(
        face=100.0,
        coupon=0.06,
        maturity=2.0,
        frequency=2,
        curve_id="manual_flat",
        currency="RUB",
        settlement_date=date(2024, 4, 1),
        issue_date=date(2024, 1, 1),
        maturity_date=date(2026, 1, 1),
        day_count="act365",
    )

    result = PricingService(market_data=market_data).price_bond(request, snapshot=snapshot)

    assert result["errors"] == []
    assert result["model_id"] == "fixed_bond"
    assert result["model_status"] == "Validated"  # fixed_bond: batch-1 2026-07
    assert result["market_data_source"] == "MANUAL"
    assert result["dirty_price"] == pytest.approx(result["clean_price"] + result["accrued_interest"])
    assert result["bond_result"].settlement_date == date(2024, 4, 1)
    warnings = " ".join(result["warnings"])
    assert "Limitations remain" in warnings
