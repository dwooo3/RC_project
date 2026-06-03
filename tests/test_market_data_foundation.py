"""Market data foundation and curve ownership tests."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pytest

from curves.yield_curve import YieldCurve
from domain.market_data import MarketDataSource
from instruments import fixed_income
from services.market_data_service import MarketDataService


def test_market_data_sources_are_explicit():
    assert {s.value for s in MarketDataSource} == {"DEMO", "MANUAL", "MOEX", "CSV"}


def test_curve_rejects_nan_rates():
    with pytest.raises(ValueError, match="NaN or inf"):
        YieldCurve([1.0, 2.0], [0.05, float("nan")])


def test_curve_rejects_inf_tenors():
    with pytest.raises(ValueError, match="NaN or inf"):
        YieldCurve([1.0, float("inf")], [0.05, 0.06])


def test_curve_rejects_non_positive_discount_factors():
    with pytest.raises(ValueError, match="discount factors must be positive"):
        YieldCurve([1.0], [800.0])


def test_curve_rejects_non_monotonic_discount_factors():
    with pytest.raises(ValueError, match="monotonic"):
        YieldCurve([1.0, 2.0], [0.10, 0.01])


def test_market_data_service_tags_manual_flat_curve():
    curve = MarketDataService().flat_curve(0.05, valuation_date=date(2026, 6, 3))

    assert curve.source == "MANUAL"
    assert curve.valuation_date == date(2026, 6, 3)
    assert curve.validate().valid


def test_market_data_service_demo_snapshot_contains_valid_curves():
    snapshot = MarketDataService().demo_snapshot(date(2026, 6, 3))

    assert snapshot.source == MarketDataSource.DEMO
    assert set(snapshot.curves) >= {"flat_rub", "ofz_demo", "ruonia_demo"}
    assert all(curve.validate().valid for curve in snapshot.curves.values())
    assert all(curve.source == "DEMO" for curve in snapshot.curves.values())


def test_fixed_income_uses_canonical_yield_curve_owner():
    assert fixed_income.YieldCurve is YieldCurve
