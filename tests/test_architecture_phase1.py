"""Phase 1 architecture contracts remain backward compatible."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pytest

from curves.yield_curve import YieldCurve as CanonicalYieldCurve
from domain import MarketDataSnapshot, PricingResult, RiskFactorExposure
from instruments.fixed_income import YieldCurve as FixedIncomeYieldCurve
from instruments.fixed_income import fixed_bond
from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService


def test_market_data_snapshot_marks_demo_data():
    snapshot = MarketDataSnapshot(
        snapshot_id="demo-1",
        valuation_date=date(2026, 6, 3),
        source="Demo / Manual",
        quality="demo",
    )

    assert snapshot.is_demo


def test_market_data_service_returns_canonical_curve():
    snapshot = MarketDataService().demo_snapshot(date(2026, 6, 3))

    assert snapshot.is_demo
    assert isinstance(snapshot.curves["flat_rub"], CanonicalYieldCurve)


def test_governance_service_normalizes_registry_entry():
    model = GovernanceService().get_model("fixed_bond")

    assert model.model_id == "fixed_bond"
    assert model.domain == "Pricing"
    assert model.production_allowed is True
    assert model.limitations


def test_governance_service_blocks_placeholder_by_default():
    model = GovernanceService().get_model("not_registered")

    assert model.production_allowed is False
    assert model.status == "Placeholder"


def test_pricing_result_carries_model_and_exposures():
    exposure = RiskFactorExposure(
        factor_name="OFZ 5Y",
        factor_type="rate",
        currency="RUB",
        bump_size=0.0001,
        sensitivity=12.3,
        unit="DV01",
    )
    result = PricingResult(
        price=100.0,
        currency="RUB",
        market_value=1_000_000.0,
        model_id="fixed_bond",
        sensitivities=[exposure],
        market_data_snapshot_id="demo-2026-06-03",
    )

    assert result.sensitivities[0].unit == "DV01"
    assert result.market_data_snapshot_id


def test_fixed_income_yield_curve_is_canonical_adapter():
    curve = FixedIncomeYieldCurve.flat(0.10)

    assert isinstance(curve, CanonicalYieldCurve)
    assert curve.discount(1.0) == pytest.approx(CanonicalYieldCurve.flat(0.10).discount(1.0))


def test_fixed_bond_keeps_legacy_api_with_curve_adapter():
    curve = FixedIncomeYieldCurve.flat(0.05)
    result = fixed_bond(face=100.0, coupon=0.05, T=2.0, freq=2, curve=curve)

    assert result["price"] > 0
    assert "cash_flows" in result
