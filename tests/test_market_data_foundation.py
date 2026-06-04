"""Market data foundation and curve ownership tests."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pytest

from curves.yield_curve import YieldCurve
from domain.market_data import MarketDataSource, MarketDataStore
from instruments import fixed_income
from services.market_data_service import MarketDataService


def test_market_data_sources_are_explicit():
    assert {s.value for s in MarketDataSource} == {
        "DEMO",
        "MANUAL",
        "CSV",
        "MOEX",
        "BLOOMBERG",
        "REUTERS",
    }


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
    assert snapshot.version == 1
    assert snapshot.created_at.tzinfo is not None
    assert set(snapshot.curves) >= {"flat_rub", "ofz_demo", "ruonia_demo"}
    assert set(snapshot.fx_rates) >= {"USD/RUB", "EUR/RUB"}
    assert "equity_flat_demo" in snapshot.vol_surfaces
    assert "corp_1t_demo" in snapshot.credit_curves
    assert "corp_1t" in snapshot.credit_spreads
    assert all(curve.validate().valid for curve in snapshot.curves.values())
    assert all(curve.source == "DEMO" for curve in snapshot.curves.values())


def test_fixed_income_uses_canonical_yield_curve_owner():
    assert fixed_income.YieldCurve is YieldCurve


def test_market_data_store_versions_duplicate_snapshot_ids():
    store = MarketDataStore()
    service = MarketDataService(store=store)
    curve = service.flat_curve(0.05, valuation_date=date(2026, 6, 3))

    first = service.manual_snapshot(
        "manual-close",
        valuation_date=date(2026, 6, 3),
        curves={"rub": curve},
    )
    second = service.manual_snapshot(
        "manual-close",
        valuation_date=date(2026, 6, 3),
        curves={"rub": curve},
    )

    assert first.version == 1
    assert second.version == 2
    assert store.get("manual-close", 1) == first
    assert store.get("manual-close") == second
    assert [snapshot.version for snapshot in store.list_versions("manual-close")] == [1, 2]


def test_manual_snapshot_owns_curve_fx_vol_and_credit_data():
    service = MarketDataService()
    curve = service.flat_curve(0.05, valuation_date=date(2026, 6, 3))
    snapshot = service.manual_snapshot(
        "manual-all",
        valuation_date=date(2026, 6, 3),
        curves={"rub": curve},
        fx_rates={"USD/RUB": 91.25},
        vol_surfaces={"eq_flat": {"type": "flat", "vol": 0.21}},
        credit_curves={"corp": {"base_curve_id": "rub", "spread": 0.012}},
        credit_spreads={"issuer_a": 0.015},
    )

    assert snapshot.source == MarketDataSource.MANUAL
    assert service.get_curve("rub", snapshot) is curve
    assert service.get_fx_rate("USD/RUB", snapshot) == 91.25
    assert service.get_vol_surface("eq_flat", snapshot)["vol"] == 0.21
    assert service.get_credit_curve("corp", snapshot)["spread"] == 0.012
    assert service.get_credit_spread("issuer_a", snapshot) == 0.015


def test_csv_snapshot_records_source_details_without_file_loading():
    service = MarketDataService()
    snapshot = service.csv_snapshot(
        "csv-close",
        valuation_date=date(2026, 6, 3),
        fx_rates={"USD/RUB": 90.5},
        source_file="market_data.csv",
    )

    assert snapshot.source == MarketDataSource.CSV
    assert snapshot.source_details == {"provider": "CSV", "file": "market_data.csv"}
    assert service.get_snapshot("csv-close") == snapshot


def test_external_provider_interfaces_are_prepared_not_implemented():
    service = MarketDataService()

    for source in (MarketDataSource.MOEX, MarketDataSource.BLOOMBERG, MarketDataSource.REUTERS):
        with pytest.raises(NotImplementedError, match="prepared but not implemented"):
            service.load_provider_snapshot(source, valuation_date=date(2026, 6, 3))
