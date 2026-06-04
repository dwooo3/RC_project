"""Scenario engine foundation tests."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from curves.yield_curve import YieldCurve
from domain import Scenario, ScenarioResult, ScenarioShock, ScenarioShockType, ScenarioType
from domain.market_data import MarketDataSource
from domain.portfolio import Position
from services.portfolio_service import PortfolioService
from services.pricing_service import PricingService
from services.risk_service import RiskService


def test_scenario_domain_supports_required_types():
    scenarios = [
        Scenario("hist-2008", "2008 Rates Shock", ScenarioType.HISTORICAL),
        Scenario("hypo-1", "Hypothetical USD/RUB Shock", ScenarioType.HYPOTHETICAL),
        Scenario("reg-1", "Regulatory Parallel Up", ScenarioType.REGULATORY),
        Scenario("custom-1", "Desk Custom", ScenarioType.CUSTOM),
    ]

    assert [scenario.type_value for scenario in scenarios] == [
        "Historical",
        "Hypothetical",
        "Regulatory",
        "Custom",
    ]


def test_portfolio_run_scenario_separates_equity_and_fx_shocks():
    service = PortfolioService("Scenario")
    service.add(Position("eq1", "equity", "Equity", 10, {"S": 100.0}))
    service.add(
        Position(
            "fx1",
            "fx_forward",
            "FX forward",
            5,
            {"S": 90.0, "r_d": 0.10, "r_f": 0.04, "T": 0.5, "ccy_pair": "USD/RUB"},
        )
    )
    scenario = Scenario(
        scenario_id="custom-equity",
        name="Equity shock only",
        scenario_type=ScenarioType.CUSTOM,
        shocks=[
            ScenarioShock(
                shock_type=ScenarioShockType.EQUITY_SHOCK,
                value=2.0,
                unit="absolute",
                bucket="Equity",
            )
        ],
    )

    result = service.run_scenario(scenario)

    assert isinstance(result, ScenarioResult)
    assert result.pnl == pytest.approx(20.0)
    assert result.bucket_pnl["Equity"] == pytest.approx(20.0)
    assert result.bucket_pnl["FX"] == pytest.approx(0.0)
    assert result.stressed_value == pytest.approx(result.base_value + 20.0)


def test_portfolio_run_scenario_supports_fx_and_volatility_shocks():
    service = PortfolioService("Scenario")
    service.add(
        Position(
            "fx1",
            "fx_forward",
            "FX forward",
            5,
            {"S": 90.0, "r_d": 0.10, "r_f": 0.04, "T": 0.5, "ccy_pair": "USD/RUB"},
        )
    )
    service.add(
        Position(
            "call1",
            "call",
            "ATM call",
            2,
            {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "sigma": 0.20, "opt": "call"},
        )
    )
    scenario = Scenario(
        "hypo-fx-vol",
        "FX and Vol Shock",
        ScenarioType.HYPOTHETICAL,
        shocks=[
            ScenarioShock(ScenarioShockType.FX_SHOCK, 3.0, "absolute", bucket="FX"),
            ScenarioShock(ScenarioShockType.VOLATILITY_SHOCK, 0.01, "absolute", bucket="Volatility"),
        ],
    )

    result = service.run_scenario(scenario)

    assert result.bucket_pnl["FX"] == pytest.approx(15.0)
    assert result.bucket_pnl["Volatility"] > 0
    assert result.factor_pnl["fx.usd/rub"] == pytest.approx(15.0)
    assert result.pnl > 15.0


def test_portfolio_run_scenario_supports_parallel_curve_shift_and_steepener_warning():
    service = PortfolioService("Rates")
    service.add(
        Position(
            "bond1",
            "bond",
            "Fixed bond",
            100.0,
            {"face": 100.0, "coupon": 0.05, "T": 2.0, "freq": 2, "r": 0.05},
        )
    )
    parallel = Scenario(
        "reg-rates-up",
        "Regulatory 100bp up",
        ScenarioType.REGULATORY,
        shocks=[ScenarioShock(ScenarioShockType.PARALLEL_CURVE_SHIFT, 100.0, "bp", bucket="Rates")],
    )
    steepener = Scenario(
        "hist-steepener",
        "Historical steepener",
        ScenarioType.HISTORICAL,
        shocks=[ScenarioShock(ScenarioShockType.STEEPENER, 50.0, "bp", bucket="Rates")],
    )

    parallel_result = service.run_scenario(parallel)
    steepener_result = service.run_scenario(steepener)

    assert parallel_result.bucket_pnl["Rates"] < 0
    assert steepener_result.bucket_pnl["Rates"] < 0
    assert any("Steepener scenario is approximated" in warning for warning in steepener_result.warnings)


def test_pricing_service_curve_shocks_parallel_steepener_flattener():
    curve = YieldCurve.flat(0.05, source=MarketDataSource.MANUAL)
    pricing = PricingService()

    shifted = pricing.shock_curve(curve, ScenarioShock(ScenarioShockType.PARALLEL_CURVE_SHIFT, 100.0, "bp"))
    steepened = pricing.shock_curve(curve, ScenarioShock(ScenarioShockType.STEEPENER, 100.0, "bp"))
    flattened = pricing.shock_curve(curve, ScenarioShock(ScenarioShockType.FLATTENER, 100.0, "bp"))

    assert shifted.rate(5.0) == pytest.approx(curve.rate(5.0) + 0.01)
    assert steepened.rate(30.0) > curve.rate(30.0)
    assert steepened.rate(0.25) < curve.rate(0.25)
    assert flattened.rate(30.0) < curve.rate(30.0)


def test_risk_service_runs_portfolio_scenario():
    service = PortfolioService("Risk Scenario")
    service.add(Position("eq1", "equity", "Equity", 10, {"S": 100.0}))
    scenario = {
        "scenario_id": "custom-risk",
        "name": "RiskService Custom",
        "scenario_type": ScenarioType.CUSTOM,
        "shocks": [
            {
                "shock_type": ScenarioShockType.EQUITY_SHOCK,
                "value": -1.5,
                "unit": "absolute",
                "bucket": "Equity",
            }
        ],
    }

    result = RiskService().run_portfolio_scenario(service, scenario)

    assert result["errors"] == []
    assert result["value"] == pytest.approx(-15.0)
    assert result["raw"]["scenario_id"] == "custom-risk"
    assert result["scenario_result"].pnl == pytest.approx(-15.0)
