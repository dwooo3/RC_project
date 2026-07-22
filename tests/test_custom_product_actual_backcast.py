"""Actual-trade historical state wiring for custom AST portfolio repricing."""

from __future__ import annotations

import copy
from datetime import date
import hashlib
import json

import pytest

from api import custom_products, pricing_new_risk
from api.pricing_workstation import price_book_ws, to_position
from domain.market_data import MarketDataSnapshot, MarketDataSource
from domain.portfolio import Position
from services.portfolio_service import PortfolioService
from services.pricing_service import PricingService


def _snapshot() -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id="SNAP-ACTUAL-BACKCAST",
        valuation_date=date(2026, 7, 22),
        source=MarketDataSource.MANUAL,
        quality="MANUAL",
    )


def _definition() -> dict:
    return {
        "name": "Dated accrual note",
        "description": "Two observed accrual periods",
        "author": "test",
        "assets": ["S"],
        "slots": {},
        "state": {"accrued": 0.0},
        # Dated instance overrides this template maturity while retaining count.
        "schedule": {"observations": 2, "maturity": 1.0},
        "observation_program": [{
            "action": "accumulate",
            "name": "accrued",
            "value": {"node": "accrual"},
        }],
        "maturity_program": [{
            "action": "pay",
            "amount": {"node": "state", "name": "accrued"},
        }],
    }


def _publish(store: custom_products.CustomProductStore) -> dict:
    created = store.create(definition=_definition(), author="maker")
    store.compile(created["id"])
    store.submit(created["id"], "maker")
    store.approve(created["id"], "checker")
    return store.publish(created["id"])


def _attachment(detail: dict) -> str:
    return json.dumps({
        "schema_version": 1,
        "product_id": detail["id"],
        "product_name": detail["definition"]["name"],
        "definition_version": detail["version"],
        "definition_state": detail["state"],
        "definition_hash": detail["definition_hash"],
        "engine_id": "custom_mc_gbm",
        "slots": {},
        "market": {
            "rate": {
                "value": 0.10,
                "source": "manual_override",
                "overridden": False,
                "override_reason": "controlled backcast test",
            },
            "assets": [{
                "index": 0,
                "asset_name": "S",
                "secid": "SBER",
                "category": "equities",
                "currency": "RUB",
                "spot": 100.0,
                "volatility": 0.20,
                "carry_yield": 0.0,
                "source": "market_snapshot",
                "snapshot_id": "SNAP-ACTUAL-BACKCAST",
                "spot_overridden": False,
                "volatility_overridden": False,
                "carry_overridden": False,
            }],
            "correlation": [[1.0]],
        },
        "numerical": {"paths": 1_000, "steps": 16, "seed": 17},
        "payoff_basis": "normalized_notional",
        "state_mode": "inception",
        "state_source": "explicit_assumption",
        "limitations": [],
    }, sort_keys=True, separators=(",", ":"))


def _schedule(definition: dict) -> dict:
    return custom_products.canonical_instance_contract_schedule(definition, {
        "effective_date": "2025-02-03",
        "contractual_observation_dates": ["2025-02-08", "2025-02-15"],
        "observation_dates": ["2025-02-10", "2025-02-17"],
        "contractual_maturity_date": "2025-02-15",
        "maturity_date": "2025-02-17",
        "business_day_convention": "FOLLOWING",
        "fixing_convention": "MOEX_OFFICIAL_CLOSE",
        "calendar": {
            "calendar_id": "MOEX_SECURITIES",
            "source": "MOEX ISS official calendar payload",
            "version": "2025-02-17T23:59:59+03:00",
            "payload_hash": "a" * 64,
            "resolved_sessions": [
                "2025-02-03", "2025-02-04", "2025-02-05",
                "2025-02-06", "2025-02-07", "2025-02-10",
                "2025-02-11", "2025-02-12", "2025-02-13",
                "2025-02-14", "2025-02-17",
            ],
        },
    })


def _fixing_rows() -> list[dict]:
    levels = [
        ("2025-02-03", 100.0), ("2025-02-04", 90.0),
        ("2025-02-05", 95.0), ("2025-02-06", 105.0),
        ("2025-02-07", 108.0), ("2025-02-10", 110.0),
        ("2025-02-11", 109.0), ("2025-02-12", 107.0),
        ("2025-02-13", 106.0), ("2025-02-14", 105.0),
        ("2025-02-17", 104.0),
    ]
    return [{"date": day, "spots": {"S": level}}
            for day, level in levels]


def _sha(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _attach_lifecycle(params: dict, definition: dict) -> None:
    schedule = _schedule(definition)
    seed = custom_products.inception_valuation_seed(
        definition, schedule, {"S": 100.0},
    )
    bindings = {
        "schema_version": 1,
        "contract": "moex_exact_fixing_bindings_v1",
        "schedule_hash": schedule["schedule_hash"],
        "calendar_id": schedule["calendar"]["calendar_id"],
        "calendar_version": schedule["calendar"]["version"],
        "calendar_payload_hash": schedule["calendar"]["payload_hash"],
        "asset_names": ["S"],
        "bindings": [{
            "asset_name": "S",
            "secid": "SBER",
            "factor_id": "SBER:price",
            "price_basis": "LEGAL_CLOSE",
            "board": "TQBR",
            "session": "",
            "source": "MOEX",
            "missing_fixing_policy": "error",
        }],
    }
    bindings["bindings_hash"] = _sha(bindings)
    ledger = custom_products.canonical_dated_fixing_ledger(
        definition, schedule, {
            "source": "MarketDataDB exact MOEX official closes",
            "source_version": "snapshot-2025-02-17T23:59:59+03:00",
            "payload_hash": "b" * 64,
            "fixings": _fixing_rows(),
        },
    )
    backcast = {
        "schema": "custom-product-actual-backcast-v1",
        "contract_schedule": schedule,
        "inception_seed": seed,
        "fixing_ledger": ledger,
    }
    backcast["contract_hash"] = _sha(backcast)

    resolved = copy.deepcopy(params["resolved_contract"])
    resolved.update({
        "contract_schedule": schedule,
        "fixing_bindings": bindings,
        "inception_seed": seed,
        "valuation_state": seed["valuation_state"],
    })
    resolved.pop("repricing_contract_hash", None)
    resolved["repricing_contract_hash"] = _sha(resolved)
    params.update({
        "contract_schedule": schedule,
        "fixing_bindings": bindings,
        "inception_seed": seed,
        "valuation_state": seed["valuation_state"],
        "state_mode": "inception",
        "state_source": "explicit_assumption",
        "historical_backcast_contract": backcast,
        "repricing_contract_hash": resolved["repricing_contract_hash"],
        "resolved_contract": resolved,
    })


@pytest.fixture
def actual_service(monkeypatch, tmp_path) -> PortfolioService:
    store = custom_products.CustomProductStore(str(tmp_path / "custom.json"))
    monkeypatch.setattr(custom_products, "_STORE", store)
    detail = _publish(store)
    request_leg = {
        "id": "actual-custom",
        "label": "Actual custom",
        "product": "custom_product",
        "engine": "custom_mc",
        "currency": "RUB",
        "quantity": 1_000.0,
        "params": {"attachment_json": _attachment(detail)},
    }
    book = price_book_ws(PricingService(), _snapshot(), [request_leg])
    assert book["errors"] == []
    leg = pricing_new_risk.legs_with_resolved_pricing_inputs(
        [request_leg], book,
    )[0]
    instrument, params, description = to_position(
        "custom_product", leg["params"], "custom_mc",
    )
    _attach_lifecycle(params, detail["definition"])
    service = PortfolioService(snapshot=_snapshot())
    service.add(Position(
        id="actual-custom", instrument=instrument, quantity=1_000.0,
        currency="RUB", description=description, params=params,
    ))
    return service


def _scenario(start: str, end: str, dates: list[str]) -> dict:
    return {
        "schema": "historical-custom-spot-path-v1",
        "day_count_basis": 252,
        "start_date": start,
        "end_date": end,
        "dates": dates,
        "fallback_log_returns": [0.0] * len(dates),
        "log_returns_by_factor": {"SBER": [0.0] * len(dates)},
    }


def _actual_reprice(service: PortfolioService, *, start: str, end: str,
                    dates: list[str]) -> dict:
    return service.full_reprice_pnl(
        dS=0.0,
        dS_by_name={"SBER": 0.0},
        spot_shock_convention="log",
        custom_repricing_profile="custom_hist_crn_v1",
        historical_state_mode="actual_trade_backcast",
        horizon=len(dates),
        custom_path_scenario=_scenario(start, end, dates),
    )


def test_actual_backcast_uses_scenario_specific_start_and_bypasses_base_cache(
        actual_service):
    first = _actual_reprice(
        actual_service, start="2025-02-11", end="2025-02-12",
        dates=["2025-02-12"],
    )
    second = _actual_reprice(
        actual_service, start="2025-02-12", end="2025-02-13",
        dates=["2025-02-13"],
    )

    assert first["valid"] is second["valid"] is True
    assert first["base_value"] != pytest.approx(second["base_value"])
    assert first["base_value_source"] == second["base_value_source"] == (
        "actual_trade_backcast_reconstructed"
    )
    assert actual_service._scenario_base_cache == {}
    first_hash = first["actual_trade_backcast_evidence"][0][
        "reconstruction"]["output_state_hash"]
    second_hash = second["actual_trade_backcast_evidence"][0][
        "reconstruction"]["output_state_hash"]
    assert first_hash != second_hash


def test_actual_backcast_cashflow_is_normalized_then_scaled_once_by_quantity(
        actual_service):
    result = _actual_reprice(
        actual_service, start="2025-02-12", end="2025-02-17",
        dates=["2025-02-13", "2025-02-14", "2025-02-17"],
    )

    evidence = result["actual_trade_backcast_evidence"][0]
    normalized = 14.0 / 365.0
    assert result["pnl_convention"] == (
        "horizon_cashflows_plus_end_pv_minus_backcast_start_pv"
    )
    assert evidence["cashflow_unit"] == "normalized_notional"
    assert evidence["normalized_horizon_cashflow"] == pytest.approx(normalized)
    assert result["shocked_value"] == pytest.approx(normalized * 1_000.0)
    assert result["pnl"] == pytest.approx(
        evidence["end_state_value"] * 1_000.0
        + normalized * 1_000.0 - result["base_value"]
    )
    assert evidence["dated_roll"]["terminal_reason"] == "maturity"


def test_actual_backcast_requires_daily_rate_policy_for_intermediate_cashflow(
        actual_service, monkeypatch):
    original_roll = custom_products.roll_forward_dated_valuation_state

    def roll_with_intermediate_cashflow(*args, **kwargs):
        result = copy.deepcopy(original_roll(*args, **kwargs))
        result["cashflows"].insert(0, {
            "date": "2025-02-14",
            "time": 11.0 / 365.0,
            "amount": 0.01,
            "phase": "observation",
            "action_index": 0,
            "observation_index": 1,
        })
        return result

    monkeypatch.setattr(
        custom_products, "roll_forward_dated_valuation_state",
        roll_with_intermediate_cashflow,
    )
    with pytest.raises(
            ValueError,
            match="daily rate path policy is required for intermediate "
                  "cashflow carry"):
        _actual_reprice(
            actual_service, start="2025-02-12", end="2025-02-17",
            dates=["2025-02-13", "2025-02-14", "2025-02-17"],
        )


def test_actual_backcast_reconstructs_stateful_event_and_daily_extrema(
        actual_service):
    params = copy.deepcopy(actual_service.positions[0].params)
    params.update({
        "custom_repricing_profile": "custom_hist_crn_v1",
        "historical_state_mode": "actual_trade_backcast",
        "historical_backcast_phase": "start",
        "historical_scenario_start_date": "2025-02-12",
        "historical_scenario_end_date": "2025-02-13",
        "historical_scenario_dates": ["2025-02-13"],
    })

    request = actual_service._custom_product_repricing_inputs(params)

    assert request["valuation_state"]["observation_index"] == 1
    assert request["valuation_state"]["state_values"]["accrued"] == pytest.approx(
        7.0 / 365.0)
    assert request["valuation_state"]["running_min"]["S"] == pytest.approx(0.9)
    assert request["state_reconstruction_evidence"]["processed_event_count"] == 1


def test_actual_backcast_rejects_trade_terminated_before_scenario_start(
        actual_service, monkeypatch):
    original_reconstruct = custom_products.reconstruct_historical_valuation_state

    def terminated_reconstruction(*args, **kwargs):
        result = copy.deepcopy(original_reconstruct(*args, **kwargs))
        result["terminal"] = True
        return result

    monkeypatch.setattr(
        custom_products, "reconstruct_historical_valuation_state",
        terminated_reconstruction,
    )
    with pytest.raises(
            ValueError,
            match="terminated before historical scenario start"):
        _actual_reprice(
            actual_service, start="2025-02-12", end="2025-02-13",
            dates=["2025-02-13"],
        )


def test_actual_backcast_fails_closed_on_contract_gap_and_scenario_date_tamper(
        actual_service):
    tampered = actual_service.positions[0].params["historical_backcast_contract"]
    tampered["fixing_ledger"]["fixings"][1]["spots"]["S"] = 91.0
    with pytest.raises(ValueError, match="backcast contract hash mismatch"):
        _actual_reprice(
            actual_service, start="2025-02-12", end="2025-02-13",
            dates=["2025-02-13"],
        )

    # Restore a valid hash after removing a required intermediate session: the
    # core must then fail on exact coverage rather than on envelope integrity.
    backcast = actual_service.positions[0].params["historical_backcast_contract"]
    backcast["fixing_ledger"] = copy.deepcopy(backcast["fixing_ledger"])
    backcast["fixing_ledger"]["fixings"] = [
        row for row in backcast["fixing_ledger"]["fixings"]
        if row["date"] != "2025-02-06"
    ]
    ledger = backcast["fixing_ledger"]
    ledger.pop("source_hash", None)
    ledger.pop("ledger_hash", None)
    definition = custom_products.get_store().get_version(
        actual_service.positions[0].params["custom_product_id"], 1,
    )["definition"]
    backcast["fixing_ledger"] = custom_products.canonical_dated_fixing_ledger(
        definition, backcast["contract_schedule"], ledger,
    )
    backcast.pop("contract_hash", None)
    backcast["contract_hash"] = _sha(backcast)
    with pytest.raises(ValueError, match="missing exact session fixings"):
        _actual_reprice(
            actual_service, start="2025-02-12", end="2025-02-13",
            dates=["2025-02-13"],
        )

    with pytest.raises(ValueError, match="scenario dates"):
        _actual_reprice(
            actual_service, start="2025-02-12", end="2025-02-17",
            dates=["2025-02-13", "2025-02-17"],
        )


def test_current_state_mode_remains_cached_profile_path(actual_service):
    result = actual_service.full_reprice_pnl(
        dS_by_name={"SBER": 0.0},
        spot_shock_convention="log",
        custom_repricing_profile="custom_hist_crn_v1",
    )

    assert result["valid"] is True
    assert result["historical_state_mode"] == "current_state_hyppl"
    assert result["base_value_source"] == "custom_profile_computed"
    assert result["pnl_convention"] == "shocked_market_value_minus_base_market_value"
    assert actual_service._scenario_base_cache


def test_actual_backcast_rejects_mixed_portfolio(actual_service):
    actual_service.add(Position(
        id="equity", instrument="equity", quantity=1.0,
        description="non-custom", params={"S": 100.0},
    ))
    with pytest.raises(ValueError, match="custom_product positions only"):
        _actual_reprice(
            actual_service, start="2025-02-12", end="2025-02-13",
            dates=["2025-02-13"],
        )
