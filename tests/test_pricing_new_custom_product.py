"""Pricing_new integration contract for the version-pinned AST builder."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from api import custom_products, pricing_new_risk
from api.pricing_new_runs import PricingNewRunService
from api.pricing_workstation import (
    build_ws_catalogue,
    price_book_ws,
    price_ws,
    to_position,
)
from domain.market_data import MarketDataSnapshot, MarketDataSource
from domain.portfolio import Position
from infra.db.market_data_db import MarketDataDB
from infra.moex_calendar import calendar_payload_hash
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService
from services.pricing_service import PricingService


def _snapshot() -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id="SNAP-CUSTOM",
        valuation_date=date(2026, 7, 18),
        source=MarketDataSource.MANUAL,
        quality="MANUAL",
    )


def _snapshot_on(value: date) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id="SNAP-CUSTOM",
        valuation_date=value,
        source=MarketDataSource.MANUAL,
        quality="MANUAL",
    )


def _stock_calendar(db: MarketDataDB, start: date, end: date) -> dict:
    days = []
    cursor = start
    while cursor <= end:
        days.append({
            "tradedate": cursor.isoformat(),
            "is_traded": int(cursor.weekday() < 5),
            "trade_session_date": None,
            "reason": None if cursor.weekday() < 5 else "H",
            "updatetime": "2026-07-20 23:00:00",
        })
        cursor = date.fromordinal(cursor.toordinal() + 1)
    digest = calendar_payload_hash(
        calendar_id="MOEX_STOCK", market="stock",
        from_date=start, till_date=end, days=days,
    )
    return db.save_trading_calendar_version(
        calendar_id="MOEX_STOCK", market="stock",
        from_date=start, till_date=end, days=days,
        source="MOEX", source_url="https://apim.moex.com/iss/calendars/stock",
        payload_hash=digest, fetched_at="2026-07-20T23:01:00+00:00",
    )


def _attachment(detail: dict, *, definition_hash: str | None = None) -> str:
    slots = {
        key: float(spec["default"])
        for key, spec in detail["definition"]["slots"].items()
    }
    payload = {
        "schema_version": 1,
        "product_id": detail["id"],
        "product_name": detail["definition"]["name"],
        "definition_version": detail["version"],
        "definition_state": detail["state"],
        "definition_hash": definition_hash or detail["definition_hash"],
        "engine_id": "custom_mc_gbm",
        "slots": slots,
        "market": {
            "rate": {
                "value": 0.10,
                "source": "manual_override",
                "overridden": False,
                "override_reason": "controlled test input",
            },
            "assets": [{
                "index": 0,
                "asset_name": "S",
                "secid": "SBER",
                "category": "equities",
                "currency": "RUB",
                "spot": 300.0,
                "volatility": 0.25,
                "carry_yield": 0.0,
                "source": "market_snapshot",
                "snapshot_id": "SNAP-CUSTOM",
                "spot_overridden": False,
                "volatility_overridden": False,
                "carry_overridden": False,
            }],
            "correlation": [[1.0]],
        },
        "numerical": {"paths": 1_000, "steps": 32, "seed": 17},
        "payoff_basis": "normalized_notional",
        "state_mode": "inception",
        "state_source": "explicit_assumption",
        "limitations": ["test evidence"],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _risk_leg(detail: dict, *, quantity: float = 1_000.0) -> dict:
    return {
        "id": "custom",
        "label": "Custom Phoenix",
        "product": "custom_product",
        "engine": "custom_mc",
        "currency": "RUB",
        "quantity": quantity,
        "params": {"attachment_json": _attachment(detail)},
    }


def _priced_risk_leg(detail: dict) -> tuple[dict, dict]:
    request_leg = _risk_leg(detail)
    book_result = price_book_ws(
        PricingService(), _snapshot(), [request_leg])
    assert book_result["errors"] == []
    enriched = pricing_new_risk.legs_with_resolved_pricing_inputs(
        [request_leg], book_result)
    return enriched[0], book_result


@pytest.fixture
def custom_store(monkeypatch, tmp_path):
    store = custom_products.CustomProductStore(str(tmp_path / "custom.json"))
    monkeypatch.setattr(custom_products, "_STORE", store)
    return store


def test_catalogue_publishes_embedded_custom_product_engine():
    product = next(item for item in build_ws_catalogue()["products"]
                   if item["id"] == "custom_product")

    assert product["engines"][0]["id"] == "custom_mc"
    assert product["engines"][0]["eligibility"]["model_definition_id"] \
        == "correlated_gbm"
    assert {item["key"] for item in product["engines"][0]["params"]} == {
        "attachment_json"
    }


def test_version_pinned_attachment_prices_after_latest_head_changes(custom_store):
    detail = custom_store.get("phoenix_autocall")
    svc = PricingService()
    params = {"attachment_json": _attachment(detail)}

    first = price_ws(svc, _snapshot(), "custom_product", "custom_mc", params)
    custom_store.new_version(detail["id"], author="test-user")
    replay = price_ws(svc, _snapshot(), "custom_product", "custom_mc", params)

    assert first["errors"] == replay["errors"] == []
    assert replay["value"] == pytest.approx(first["value"])
    assert replay["resolved_inputs"]["definition_version"] == 1
    assert replay["resolved_inputs"]["definition_hash"] == detail["definition_hash"]
    assert replay["provenance"]["inputs_hash"] == first["provenance"]["inputs_hash"]
    assert "test evidence" in replay["warnings"]


def test_definition_hash_mismatch_fails_closed(custom_store):
    detail = custom_store.get("phoenix_autocall")
    with pytest.raises(ValueError, match="definition hash mismatch"):
        price_ws(
            PricingService(), _snapshot(), "custom_product", "custom_mc",
            {"attachment_json": _attachment(detail, definition_hash="0" * 64)},
        )


def test_custom_attachment_resolves_contractual_dates_on_pinned_moex_calendar(
    custom_store,
):
    detail = custom_store.get("phoenix_autocall")
    payload = json.loads(_attachment(detail))
    payload["slots"]["n_obs"] = 2.0
    payload["slots"]["T"] = 0.5
    payload["contract_schedule"] = {
        "schema_version": 1,
        "effective_date": "2026-07-20",
        "contractual_maturity_date": "2026-08-02",
        "contractual_observation_dates": ["2026-07-26", "2026-08-02"],
        "business_day_convention": "MODIFIED_FOLLOWING",
        "calendar_id": "MOEX_STOCK",
        "calendar_version": 1,
        "day_count_convention": "ACT/365F",
        "valuation_cutoff": "POST_CLOSE_POST_EVENTS",
        "fixing_bindings": [{
            "asset_name": "S",
            "secid": "SBER",
            "price_basis": "CLOSE",
            "board": "TQBR",
            "session": "",
            "source": "MOEX",
            "missing_fixing_policy": "error",
        }],
    }
    db = MarketDataDB(":memory:")
    db.init_schema()
    _stock_calendar(db, date(2026, 7, 20), date(2026, 8, 3))
    market = MarketDataService(market_db=db)
    service = PricingService(market_data=market)

    result = price_ws(
        service,
        _snapshot_on(date(2026, 7, 20)),
        "custom_product",
        "custom_mc",
        {"attachment_json": json.dumps(payload)},
    )

    assert result["errors"] == []
    resolved = result["resolved_inputs"]
    schedule = resolved["contract_schedule"]
    assert schedule["contractual_observation_dates"] == [
        "2026-07-26", "2026-08-02"]
    assert schedule["observation_dates"] == ["2026-07-27", "2026-08-03"]
    assert schedule["maturity_date"] == "2026-08-03"
    assert schedule["calendar"]["calendar_id"] == "MOEX_STOCK"
    assert schedule["calendar"]["version"] == "1"
    assert len(schedule["calendar"]["payload_hash"]) == 64
    assert resolved["fixing_bindings"]["bindings"][0] == {
        "asset_name": "S",
        "secid": "SBER",
        "factor_id": "SBER:price",
        "price_basis": "CLOSE",
        "board": "TQBR",
        "session": "",
        "source": "MOEX",
        "missing_fixing_policy": "error",
    }
    assert resolved["inception_seed"]["effective_date"] == "2026-07-20"
    assert resolved["valuation_state"]["instance_schedule_hash"] == \
        schedule["schedule_hash"]


def test_multi_asset_attachment_binds_historical_correlation_calibration(
    custom_store, monkeypatch,
):
    definition = {
        "name": "Two asset historical correlation",
        "description": "integration test",
        "author": "maker",
        "assets": ["A", "B"],
        "slots": {}, "state": {},
        "schedule": {"observations": 1, "maturity": 1.0},
        "observation_program": [],
        "maturity_program": [{
            "action": "pay", "amount": {"node": "worst_of"},
        }],
    }
    created = custom_store.create(definition=definition, author="maker")
    custom_store.compile(created["id"])
    custom_store.submit(created["id"], "maker")
    custom_store.approve(created["id"], "checker")
    detail = custom_store.publish(created["id"])
    payload = {
        "schema_version": 1, "product_id": detail["id"],
        "product_name": definition["name"], "definition_version": 1,
        "definition_state": "published",
        "definition_hash": detail["definition_hash"],
        "engine_id": "custom_mc_multi_gbm", "slots": {},
        "market": {
            "rate": {"value": 0.1, "source": "manual_override",
                     "override_reason": "test"},
            "assets": [
                {"index": index, "asset_name": name, "secid": secid,
                 "category": "equities", "currency": "RUB", "spot": spot,
                 "volatility": 0.2, "carry_yield": 0.0,
                 "source": "market_snapshot", "snapshot_id": "SNAP-CUSTOM"}
                for index, (name, secid, spot) in enumerate(
                    [("A", "AAA", 100.0), ("B", "BBB", 200.0)])
            ],
            "correlation": [[1.0, 0.25], [0.25, 1.0]],
            "correlation_calibration": {
                "mode": "historical", "method": "ewma", "lookback": 120,
                "decay": 0.96, "min_samples": 40,
                "fallback_policy": "error",
            },
        },
        "numerical": {"paths": 1_000, "steps": 16, "seed": 7},
        "payoff_basis": "normalized_notional",
        "state_mode": "inception", "state_source": "explicit_assumption",
        "limitations": [],
    }
    observed = {}

    def calibrated(factor_ids, **kwargs):
        observed["factor_ids"] = factor_ids
        observed.update(kwargs)
        return {
            "factor_ids": factor_ids, "as_of": "2026-07-18",
            "lookback": 120, "method": "ewma", "decay": 0.96,
            "min_samples": 40, "fallback_policy": "error",
            "raw_matrix": [[1.0, 0.6], [0.6, 1.0]],
            "matrix": [[1.0, 0.6], [0.6, 1.0]],
            "matrix_hash": "e" * 64, "adjustment_frobenius": 0.0,
            "raw_min_eigenvalue": 0.4, "adjusted_min_eigenvalue": 0.4,
            "adjustment_material": False, "pairs": [], "series": [],
            "fallback": False,
        }

    service = PricingService()
    monkeypatch.setattr(service.market_data, "historical_correlation", calibrated)
    result = price_ws(
        service, _snapshot(), "custom_product", "custom_mc",
        {"attachment_json": json.dumps(payload)},
    )

    assert result["errors"] == []
    assert observed["factor_ids"] == ["AAA:price", "BBB:price"]
    resolved = result["resolved_inputs"]
    assert resolved["correlation"] == [[1.0, 0.6], [0.6, 1.0]]
    assert resolved["correlation_evidence"][
        "historical_estimation_bound"] is True
    assert resolved["correlation_evidence"]["matrix_hash"] == "e" * 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(product_name="Not the definition"),
         "name does not match"),
        (lambda payload: payload["market"]["assets"][0].update(
            asset_name="UNKNOWN"), "asset names do not match"),
        (lambda payload: payload["slots"].update(unknown_slot=1.0),
         "slot grid does not match"),
    ],
)
def test_attachment_contract_is_checked_against_exact_definition(
    custom_store, mutate, message,
):
    detail = custom_store.get("phoenix_autocall")
    payload = json.loads(_attachment(detail))
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        price_ws(
            PricingService(), _snapshot(), "custom_product", "custom_mc",
            {"attachment_json": json.dumps(payload)},
        )


def _seasoned_attachment(detail: dict, *, market_spot: float = 310.0,
                         state_spot: float = 310.0) -> dict:
    payload = json.loads(_attachment(detail))
    payload["state_mode"] = "seasoned"
    payload["state_source"] = "seasoned_observation"
    payload["market"]["assets"][0]["spot"] = market_spot
    payload["valuation_state"] = {
        "schema_version": 1,
        "state_contract": "custom_ast_seasoned_state_v1",
        "mode": "seasoned",
        "asset_names": ["S"],
        "current_spots": {"S": state_spot},
        "reference_spots": {"S": 300.0},
        "observation_index": 1,
        "state_values": {"memory": 0.0},
        "running_min": {"S": 0.90},
        "running_max": {"S": 1.05},
        "elapsed_time": 0.30,
        "alive": True,
        "state_as_of": "2026-07-18",
        "state_source_hash": "a" * 64,
    }
    return payload


def test_seasoned_attachment_prices_on_one_bound_market_state(custom_store):
    detail = custom_store.get("phoenix_autocall")
    result = price_ws(
        PricingService(), _snapshot(), "custom_product", "custom_mc",
        {"attachment_json": json.dumps(_seasoned_attachment(detail))},
    )

    assert result["errors"] == []
    state = result["resolved_inputs"]["valuation_state"]
    assert state["mode"] == "seasoned"
    assert state["current_spots"] == {"S": 310.0}
    assert state["state_source_hash"] == "a" * 64


def test_seasoned_attachment_rejects_state_market_spot_split(custom_store):
    detail = custom_store.get("phoenix_autocall")
    payload = _seasoned_attachment(
        detail, market_spot=310.0, state_spot=309.0)

    with pytest.raises(ValueError, match="must equal the bound market asset spot"):
        price_ws(
            PricingService(), _snapshot(), "custom_product", "custom_mc",
            {"attachment_json": json.dumps(payload)},
        )


def test_lifecycle_progress_after_attachment_does_not_change_pinned_economics(
    custom_store,
):
    detail = custom_store.get("phoenix_autocall")
    payload = json.loads(_attachment(detail))
    payload["definition_state"] = "tested"

    result = price_ws(
        PricingService(), _snapshot(), "custom_product", "custom_mc",
        {"attachment_json": json.dumps(payload)},
    )

    assert result["errors"] == []
    assert result["resolved_inputs"]["definition_state_at_attachment"] == "tested"
    assert result["resolved_inputs"]["definition_state_at_pricing"] == "published"


def test_legacy_unit_state_attachment_prices_but_risk_fails_closed(custom_store):
    detail = custom_store.get("phoenix_autocall")
    payload = json.loads(_attachment(detail))
    for key in ("payoff_basis", "state_mode", "state_source"):
        payload.pop(key)
    request_leg = _risk_leg(detail)
    request_leg["params"]["attachment_json"] = json.dumps(payload)

    book_result = price_book_ws(PricingService(), _snapshot(), [request_leg])
    assert book_result["errors"] == []
    warnings = book_result["legs"][0]["result"]["warnings"]
    assert any("payoff_basis" in item for item in warnings)
    assert any("explicit inception" in item for item in warnings)

    enriched = pricing_new_risk.legs_with_resolved_pricing_inputs(
        [request_leg], book_result)
    capability = pricing_new_risk.evaluate_book_capabilities(
        enriched, bound_snapshot_id="SNAP-CUSTOM")
    assert capability["supported"] is False
    assert capability["unsupported"][0]["code"] == (
        "custom_payoff_unit_contract_required")


def test_exact_version_read_is_integrity_checked_and_defensive(custom_store):
    first = custom_store.get_version("phoenix_autocall", 1)
    first["definition"]["name"] = "client mutation"
    second = custom_store.get_version("phoenix_autocall", 1)

    assert second["definition"]["name"] == "Phoenix Autocall"


def test_store_load_rejects_definition_tampered_on_disk(custom_store):
    path = Path(custom_store.path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["phoenix_autocall"]["versions"][0]["definition"][
        "description"
    ] = "tampered after approval"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        custom_products.CustomProductIntegrityError,
        match="definition hash integrity mismatch",
    ):
        custom_products.CustomProductStore(str(path))


def test_store_get_rejects_definition_tampered_in_memory(custom_store):
    custom_store._data["phoenix_autocall"]["versions"][0]["definition"][
        "description"
    ] = "tampered in memory"

    with pytest.raises(
        custom_products.CustomProductIntegrityError,
        match="definition hash integrity mismatch",
    ):
        custom_store.get("phoenix_autocall")


def test_version_pinned_price_rejects_tampered_definition(custom_store):
    detail = custom_store.get("phoenix_autocall")
    custom_store._data["phoenix_autocall"]["versions"][0]["definition"][
        "description"
    ] = "tampered version"

    with pytest.raises(
        custom_products.CustomProductIntegrityError,
        match="definition hash integrity mismatch",
    ):
        custom_store.price(
            "phoenix_autocall", {}, {"r": 0.05, "sigma": 0.20},
            n_sims=1_000, steps=16, version=1,
            expected_definition_hash=detail["definition_hash"],
        )


def test_price_rejects_result_with_different_definition_hash(
    custom_store, monkeypatch,
):
    monkeypatch.setattr(
        custom_products,
        "price_definition",
        lambda *_args, **_kwargs: {"definition_hash": "0" * 64},
    )

    with pytest.raises(
        custom_products.CustomProductIntegrityError,
        match="pricing result definition hash mismatch",
    ):
        custom_store.price(
            "phoenix_autocall", {}, {"r": 0.05, "sigma": 0.20},
            n_sims=1_000, steps=16, version=1,
        )


def test_custom_product_can_share_named_book_pv_and_publishes_repricing_evidence(
    custom_store,
):
    detail = custom_store.get("phoenix_autocall")
    result = price_book_ws(PricingService(), _snapshot(), [{
        "id": "custom",
        "label": "Custom Phoenix",
        "product": "custom_product",
        "engine": "custom_mc",
        "currency": "RUB",
        "quantity": 1_000.0,
        "params": {"attachment_json": _attachment(detail)},
    }, {
        "id": "hedge",
        "label": "SBER call",
        "product": "european_option",
        "engine": "black_scholes",
        "risk_factor_id": "SBER",
        "currency": "RUB",
        "quantity": -1.0,
        "params": {
            "S": 300.0, "K": 300.0, "T": 1.0, "r": 0.10,
            "q": 0.0, "sigma": 0.25, "opt": "call",
        },
    }])

    assert result["success_count"] == 2
    assert result["aggregation"]["status"] == "typed"
    assert result["total_value"] == pytest.approx(sum(
        leg["position_value"] for leg in result["legs"]
    ))
    assert result["legs"][0]["result"]["resolved_inputs"]["custom_product_id"] \
        == detail["id"]


def test_successful_custom_price_materializes_canonical_risk_position_and_named_greeks(
    custom_store,
):
    detail = custom_store.get("phoenix_autocall")
    leg, book_result = _priced_risk_leg(detail)

    resolved = book_result["legs"][0]["result"]["resolved_inputs"]
    named_greeks = book_result["legs"][0]["result"]["greeks"]
    assert {row["key"] for row in named_greeks} >= {
        "delta.SBER", "gamma.SBER", "vega.SBER",
    }
    assert all(
        row.get("kind") == "equity"
        for row in named_greeks if row["key"].endswith(".SBER")
    )
    assert resolved["schema"] == "custom-product-portfolio-repricing-v1"
    assert resolved["definition_version"] == detail["version"]
    assert resolved["definition_hash"] == detail["definition_hash"]
    assert resolved["resolved_snapshot_id"] == "SNAP-CUSTOM"
    assert resolved["component_secids"] == ["SBER"]
    assert resolved["asset_names"] == ["S"]
    assert resolved["payoff_basis"] == "normalized_notional"
    assert resolved["quantity_unit"] == "currency_notional"
    assert resolved["state_mode"] == "inception"
    assert resolved["state_source"] == "explicit_assumption"
    assert len(resolved["correlation_evidence"]["matrix_hash"]) == 64
    assert resolved["valuation_state"]["mode"] == "inception"
    assert resolved["repricing_contract_hash"]

    capability = pricing_new_risk.evaluate_book_capabilities(
        [leg], bound_snapshot_id="SNAP-CUSTOM")
    assert capability["supported"] is True
    assert capability["supported_legs"][0]["instrument"] == "custom_product"

    instrument, params, description = to_position(
        "custom_product", leg["params"], "custom_mc")
    portfolio = PortfolioService(snapshot=_snapshot())
    portfolio.add(Position(
        id="custom", instrument=instrument, quantity=1_000.0,
        currency="RUB", description=description, params=params,
    ))
    valuation = portfolio.value()

    assert valuation.errors == []
    assert valuation.total_market_value == pytest.approx(
        book_result["total_value"])
    exposures = {
        item.factor_id: item for item in portfolio.positions[0].exposures
    }
    assert set(exposures) == {
        "equity.sber.spot",
        "equity.sber.spot_gamma",
        "vol.sber.model",
    }
    assert exposures["vol.sber.model"].unit == "Vega"
    assert exposures["vol.sber.model"].bump_size == pytest.approx(0.01)
    evidence = portfolio.positions[0].metadata["custom_product_evidence"]
    assert evidence["definition_hash"] == detail["definition_hash"]
    assert evidence["resolved_snapshot_id"] == "SNAP-CUSTOM"
    assert evidence["payoff_basis"] == "normalized_notional"
    assert evidence["state_source"] == "explicit_assumption"


def test_custom_full_reprice_routes_spot_and_vol_by_exact_secid(custom_store):
    detail = custom_store.get("phoenix_autocall")
    leg, _book_result = _priced_risk_leg(detail)
    instrument, params, description = to_position(
        "custom_product", leg["params"], "custom_mc")
    portfolio = PortfolioService(snapshot=_snapshot())
    portfolio.add(Position(
        id="custom", instrument=instrument, quantity=1_000.0,
        currency="RUB", description=description, params=params,
    ))

    unrelated = portfolio.full_reprice_pnl(
        dS=0.0, dvol=0.0, dr=0.0,
        dS_by_name={"GAZP": 0.10},
        dvol_by_name={"GAZP": 0.01},
    )
    named_spot = portfolio.full_reprice_pnl(
        dS=0.0, dvol=0.0, dr=0.0,
        dS_by_name={"SBER": 0.10},
    )
    named_vol = portfolio.full_reprice_pnl(
        dS=0.0, dvol=0.0, dr=0.0,
        dvol_by_name={"SBER": 0.01},
    )
    rate = portfolio.full_reprice_pnl(
        dS=0.0, dvol=0.0, dr=0.01,
    )

    assert unrelated["pnl"] == pytest.approx(0.0, abs=1e-12)
    assert named_spot["pnl"] != pytest.approx(0.0, abs=1e-8)
    assert named_vol["pnl"] != pytest.approx(0.0, abs=1e-8)
    assert rate["pnl"] != pytest.approx(0.0, abs=1e-8)
    assert named_spot["errors"] == named_vol["errors"] == rate["errors"] == []


def test_custom_component_exposure_taxonomy_and_gamma_semantics(
    custom_store, monkeypatch,
):
    service = PortfolioService(snapshot=_snapshot())
    request = {
        "product_id": "synthetic",
        "definition_version": 1,
        "definition_hash": "a" * 64,
        "attachment_hash": "b" * 64,
        "repricing_contract_hash": "c" * 64,
        "resolved_snapshot_id": "SNAP-CUSTOM",
        "asset_names": ["EQ", "BOND", "FUT", "CMD"],
        "component_secids": ["SBER", "RU000A", "SiU6", "GOLD"],
        "component_kinds": ["equity", "bond", "future", "commodity"],
        "assets": [300.0, 90.0, 100.0, 2_500.0],
        "reference_spots": [300.0, 90.0, 100.0, 2_500.0],
        "sigmas": [0.2, 0.1, 0.15, 0.25],
        "incomes": [0.0, 0.0, 0.0, 0.0],
        "correlation": np.eye(4).tolist(),
        "correlation_evidence": {
            "matrix_hash": "d" * 64,
            "method": "user_supplied_static_correlation",
        },
        "slots": {},
        "market": {},
        "numerical": {"paths": 1_000, "steps": 16, "seed": 7},
        "repricing_profile": None,
        "payoff_basis": "normalized_notional",
        "quantity_unit": "currency_notional",
        "state_mode": "inception",
        "state_source": "explicit_assumption",
        "valuation_state": {"mode": "inception"},
        "scenario": None,
        "attachment": {"limitations": []},
    }
    monkeypatch.setattr(
        service, "_custom_product_repricing_inputs", lambda _params: request)
    monkeypatch.setattr(custom_store, "reprice", lambda *_args, **_kwargs: {
        "value": 1.0,
        "state": "published",
        "engine": "custom_mc_multi_gbm",
        "repricing_evidence": {"rng_contract": {"version": 1}},
        "greeks_evidence": {},
        "component_greeks": {
            name: {"delta": 1.0, "gamma": 0.1, "vega": 0.01}
            for name in request["asset_names"]
        },
        "parallel_gamma": 0.8,
        "parallel_cross_gamma": 0.4,
        "parallel_diagonal_gamma": 0.4,
        "cross_gamma_matrix": (np.eye(4) * 0.1).tolist(),
        "cross_gamma_pairs": [],
        "gamma_convention": "d2PV/dx2 for parallel relative spot shock",
    })
    position = Position(
        id="typed", instrument="custom_product", quantity=1.0,
        currency="RUB", description="typed custom", params={},
    )
    service.add(position)

    valuation = service.value()

    assert valuation.errors == []
    exposures = {item.factor_id: item for item in position.exposures}
    assert exposures["equity.sber.spot"].bucket == "Equity"
    assert exposures["credit.ru000a.price"].bucket == "Credit"
    assert exposures["future.siu6.spot"].bucket == "Equity"
    assert exposures["commodity.gold.spot"].bucket == "Commodity"
    assert position.gamma == pytest.approx(0.8)
    assert position.metadata["custom_product_evidence"]["gamma_aggregation"] \
        == "parallel_relative_spot_shock"
    assert position.metadata["custom_product_evidence"][
        "parallel_cross_gamma"] == pytest.approx(0.4)
    assert not any("cross-gamma" in warning for warning in position.warnings)


def test_custom_historical_profile_uses_paired_1000_path_base_cache(
    custom_store, monkeypatch,
):
    detail = custom_store.get("phoenix_autocall")
    leg, _book_result = _priced_risk_leg(detail)
    instrument, params, description = to_position(
        "custom_product", leg["params"], "custom_mc")
    portfolio = PortfolioService(snapshot=_snapshot())
    portfolio.add(Position(
        id="custom", instrument=instrument, quantity=1_000.0,
        currency="RUB", description=description, params=params,
    ))
    original_reprice = custom_store.reprice
    observed_paths = []

    def tracked_reprice(*args, **kwargs):
        observed_paths.append(kwargs["n_sims"])
        return original_reprice(*args, **kwargs)

    monkeypatch.setattr(custom_store, "reprice", tracked_reprice)
    first = portfolio.full_reprice_pnl(
        dS=0.0, dS_by_name={"SBER": 0.05},
        custom_repricing_profile="custom_hist_crn_v1",
        base_value_override=123_456.0,
    )
    assert observed_paths == [1_000, 1_000]
    assert first["base_value_source"] == "custom_profile_computed"
    assert first["base_value"] != pytest.approx(123_456.0)
    assert any("override ignored" in item for item in first["warnings"])

    observed_paths.clear()
    second = portfolio.full_reprice_pnl(
        dS=0.0, dS_by_name={"SBER": -0.05},
        custom_repricing_profile="custom_hist_crn_v1",
    )
    assert observed_paths == [1_000]
    assert second["base_value_source"] == "custom_profile_cache"
    assert second["base_value"] == pytest.approx(first["base_value"])

    assert portfolio._scenario_base_cache
    portfolio.add(Position(
        id="cash-like", instrument="equity", quantity=1.0,
        description="cache invalidator", params={"S": 1.0},
    ))
    assert portfolio._scenario_base_cache == {}
    portfolio.clear()
    assert portfolio.positions == []
    assert portfolio._scenario_base_cache == {}


def test_custom_product_runs_through_transient_historical_risk_pipeline(
    custom_store, monkeypatch,
):
    detail = custom_store.get("phoenix_autocall")
    leg, _book_result = _priced_risk_leg(detail)
    base = PortfolioService(snapshot=_snapshot())
    ctx = SimpleNamespace(
        portfolio=base, snapshot=_snapshot(), audit=base.audit,
    )
    observed = {}
    original_value = PortfolioService.value

    def tracked_value(portfolio, *, calculate_risk=True):
        observed.setdefault("valuation_risk_flags", []).append(calculate_risk)
        return original_value(portfolio, calculate_risk=calculate_risk)

    monkeypatch.setattr(PortfolioService, "value", tracked_value)

    def fake_hyppl(
        _ctx, window, frm=None, till=None, portfolio=None, horizon=1, *,
        custom_repricing_profile=None, deadline_seconds=None,
    ):
        assert window == 250
        assert horizon == 1
        assert custom_repricing_profile == "custom_hist_crn_v1"
        assert deadline_seconds == 60.0
        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].instrument == "custom_product"
        observed["secids"] = portfolio.positions[0].params["component_secids"]
        shocks = [np.log(0.90), np.log(0.97), np.log(1.04), np.log(1.10)]
        repriced = [
            portfolio.full_reprice_pnl(
                dS=0.0,
                dS_by_name={"SBER": float(shock)},
                spot_shock_convention="log",
                custom_repricing_profile=custom_repricing_profile,
                horizon=1,
                custom_path_scenario={
                    "schema": "historical-custom-spot-path-v1",
                    "day_count_basis": 252,
                    "dates": [f"2026-01-{index + 1:02d}"],
                    "fallback_log_returns": [float(shock)],
                    "log_returns_by_factor": {"SBER": [float(shock)]},
                },
            )
            for index, shock in enumerate(shocks)
        ]
        pnl = [item["pnl"] for item in repriced]
        return {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            "pnl": np.asarray(pnl),
            "factors": ["EQ:SBER"],
            "factor_warnings": [],
            "factor_diagnostics": {},
            "reprice_errors": [],
            "reprice_warnings": ["paired custom risk profile"],
            "repricing_evidence": {
                "profile": custom_repricing_profile,
                "inner_paths": 1_000,
                "common_random_numbers": True,
                "paired_profile_base": True,
                "base_value": repriced[0]["base_value"],
                "base_value_sources": sorted({
                    item["base_value_source"] for item in repriced
                }),
                "scenario_count": len(repriced),
                "path_roll_applied": True,
                "path_days": 1,
                "path_day_count_basis": 252,
                "path_roll_contract": "historical-custom-spot-path-v1",
                "pnl_convention": (
                    "horizon_cashflows_plus_end_pv_minus_current_base_pv"),
                "path_roll_hashes": [
                    item["custom_path_roll_evidence"][0]["path_hash"]
                    for item in repriced
                ],
                "path_roll_evidence": [
                    {
                        "path_hash": item["custom_path_roll_evidence"][0]["path_hash"],
                        "transition_hash": item["custom_path_roll_evidence"][0]["transition_hash"],
                        "cashflow_ledger_hash": item["custom_path_roll_evidence"][0]["cashflow_ledger_hash"],
                        "output_state_hash": item["custom_path_roll_evidence"][0]["output_state_hash"],
                        "terminal": item["custom_path_roll_evidence"][0]["terminal"],
                    }
                    for item in repriced
                ],
            },
            "scenario_matrix_hash": "c" * 64,
            "horizon_method": "none",
        }

    monkeypatch.setattr(pricing_new_risk.marketrisk, "hyppl", fake_hyppl)
    result = pricing_new_risk.calculate_transient_book_risk(
        ctx, [leg], confidence=0.75, window=250,
        model="historical_full_reprice",
    )

    assert observed["secids"] == ["SBER"]
    assert observed["valuation_risk_flags"] == [False]
    assert result["positions"] == 1
    assert result["n_scenarios"] == 4
    assert result["capability"]["supported"] is True
    assert result["provenance"]["snapshot_id"] == "SNAP-CUSTOM"
    assert result["factors"] == ["EQ:SBER"]
    custom_evidence = result["provenance"]["custom_repricing"]
    assert custom_evidence["profile"] == "custom_hist_crn_v1"
    assert custom_evidence["inner_paths"] == 1_000
    assert custom_evidence["requested_work_path_points"] == 8_250_000
    assert custom_evidence["actual_work_path_points"] == 132_000
    assert custom_evidence["execution"]["paired_profile_base"] is True
    assert result["provenance"]["scenario_matrix_hash"] == "c" * 64
    assert "paired custom risk profile" in result["data_quality"]


def test_custom_product_accepts_multi_day_risk_with_path_roll_evidence(
    custom_store, monkeypatch,
):
    detail = custom_store.get("phoenix_autocall")
    leg, _book_result = _priced_risk_leg(detail)
    base = PortfolioService(snapshot=_snapshot())
    ctx = SimpleNamespace(
        portfolio=base, snapshot=_snapshot(), audit=base.audit,
    )
    observed = {}

    def fake_hyppl(_ctx, window, frm=None, till=None, portfolio=None,
                   horizon=1, **_kwargs):
        observed["horizon"] = horizon
        return {
            "dates": ["2026-01-10", "2026-01-20"],
            "pnl": np.asarray([-2.0, 3.0]),
            "factors": ["EQ:SBER"],
            "factor_warnings": [], "factor_diagnostics": {},
            "reprice_errors": [], "reprice_warnings": [],
            "repricing_evidence": {
                "profile": "custom_hist_crn_v1", "inner_paths": 1_000,
                "common_random_numbers": True, "paired_profile_base": True,
                "base_value": 100.0, "scenario_count": 2,
                "path_roll_applied": True, "path_days": 10,
                "path_day_count_basis": 252,
                "path_roll_contract": "historical-custom-spot-path-v1",
                "pnl_convention": (
                    "horizon_cashflows_plus_end_pv_minus_current_base_pv"),
                "path_roll_hashes": ["a" * 64, "b" * 64],
                "path_roll_evidence": [
                    {
                        "path_hash": "a" * 64,
                        "transition_hash": "d" * 64,
                        "cashflow_ledger_hash": "e" * 64,
                        "output_state_hash": "f" * 64,
                        "terminal": False,
                    },
                    {
                        "path_hash": "b" * 64,
                        "transition_hash": "1" * 64,
                        "cashflow_ledger_hash": "2" * 64,
                        "output_state_hash": "3" * 64,
                        "terminal": False,
                    },
                ],
            },
            "scenario_matrix_hash": "c" * 64,
            "horizon_method": "factor_aggregation_full_reprice",
        }

    monkeypatch.setattr(pricing_new_risk.marketrisk, "hyppl", fake_hyppl)
    result = pricing_new_risk.calculate_transient_book_risk(
        ctx, [leg], window=250, horizon=10)

    assert observed["horizon"] == 10
    assert result["horizon"] == 10
    assert result["n_scenarios"] == 2


def test_portfolio_full_reprice_applies_sequential_ten_day_custom_path(
    custom_store,
):
    detail = custom_store.get("phoenix_autocall")
    leg, _book_result = _priced_risk_leg(detail)
    instrument, params, description = to_position(
        "custom_product", leg["params"], engine_id="custom_mc")
    service = PortfolioService(snapshot=_snapshot())
    service.add(Position(
        id="custom-path", instrument=instrument, quantity=1.0,
        currency="RUB", description=description, params=params,
    ))
    daily = float(np.log(1.10) / 10.0)
    result = service.full_reprice_pnl(
        dS=0.0,
        dS_by_name={"SBER": float(np.log(1.10))},
        spot_shock_convention="log",
        custom_repricing_profile="custom_hist_crn_v1",
        horizon=10,
        custom_path_scenario={
            "schema": "historical-custom-spot-path-v1",
            "day_count_basis": 252,
            "dates": [f"2026-01-{day:02d}" for day in range(1, 11)],
            "fallback_log_returns": [daily] * 10,
            "log_returns_by_factor": {"SBER": [daily] * 10},
        },
    )

    assert result["valid"] is True
    assert result["horizon"] == 10
    evidence = result["custom_path_roll_evidence"][0]
    assert evidence["requested_days"] == 10
    assert evidence["end_elapsed_time"] == pytest.approx(10 / 252)
    assert evidence["path_hash"]
    assert evidence["transition_hash"]


def test_portfolio_custom_path_endpoint_mismatch_fails_closed(custom_store):
    detail = custom_store.get("phoenix_autocall")
    leg, _book_result = _priced_risk_leg(detail)
    instrument, params, description = to_position(
        "custom_product", leg["params"], engine_id="custom_mc")
    service = PortfolioService(snapshot=_snapshot())
    service.add(Position(
        id="custom-path-mismatch", instrument=instrument, quantity=1.0,
        currency="RUB", description=description, params=params,
    ))

    with pytest.raises(ValueError, match="differs from endpoint shock"):
        service.full_reprice_pnl(
            dS_by_name={"SBER": float(np.log(1.10))},
            spot_shock_convention="log",
            custom_repricing_profile="custom_hist_crn_v1",
            horizon=2,
            custom_path_scenario={
                "schema": "historical-custom-spot-path-v1",
                "day_count_basis": 252,
                "dates": ["2026-01-01", "2026-01-02"],
                "fallback_log_returns": [0.0, 0.0],
                "log_returns_by_factor": {"SBER": [0.0, 0.0]},
            },
        )


def test_custom_product_blocks_more_than_500_scenarios_before_valuation(
    custom_store, monkeypatch,
):
    detail = custom_store.get("phoenix_autocall")
    leg, _book_result = _priced_risk_leg(detail)
    base = PortfolioService(snapshot=_snapshot())
    ctx = SimpleNamespace(
        portfolio=base, snapshot=_snapshot(), audit=base.audit,
    )
    monkeypatch.setattr(
        PortfolioService,
        "value",
        lambda *_args, **_kwargs: pytest.fail(
            "valuation must not run after a failed resource preflight"),
    )
    monkeypatch.setattr(
        pricing_new_risk.marketrisk,
        "hyppl",
        lambda *_args, **_kwargs: pytest.fail(
            "history must not run after a failed resource preflight"),
    )

    with pytest.raises(pricing_new_risk.PricingNewRiskError) as caught:
        pricing_new_risk.calculate_transient_book_risk(
            ctx, [leg], window=501, horizon=1)

    assert caught.value.code == "custom_risk_resource_limit"
    assert caught.value.details["requested_scenarios"] == 501
    assert caught.value.details["scenario_limit"] == 500


def test_custom_historical_work_budget_boundary_is_fail_closed():
    exact = SimpleNamespace(
        leg_id="exact",
        instrument="custom_product",
        params={
            "asset_names": ["A", "B", "C", "D"],
            "numerical": {"paths": 1_000, "steps": 749, "seed": 17},
            "definition_hash": "a" * 64,
            "repricing_contract_hash": "b" * 64,
        },
    )
    policy = pricing_new_risk._custom_risk_compute_policy(
        [exact], requested_scenarios=500)
    assert policy["requested_work_path_points"] == 1_500_000_000

    over = SimpleNamespace(
        leg_id="over",
        instrument="custom_product",
        params={
            **exact.params,
            "numerical": {"paths": 1_000, "steps": 750, "seed": 17},
        },
    )
    with pytest.raises(pricing_new_risk.PricingNewRiskError) as caught:
        pricing_new_risk._custom_risk_compute_policy(
            [over], requested_scenarios=500)
    assert caught.value.code == "custom_risk_resource_limit"
    assert caught.value.details["requested_work_path_points"] == 1_502_000_000


def test_custom_historical_deadline_never_publishes_partial_result(
    custom_store, monkeypatch,
):
    detail = custom_store.get("phoenix_autocall")
    leg, _book_result = _priced_risk_leg(detail)
    base = PortfolioService(snapshot=_snapshot())
    ctx = SimpleNamespace(
        portfolio=base, snapshot=_snapshot(), audit=base.audit,
    )
    monkeypatch.setattr(
        pricing_new_risk.marketrisk,
        "hyppl",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TimeoutError("synthetic deadline")),
    )

    with pytest.raises(pricing_new_risk.PricingNewRiskError) as caught:
        pricing_new_risk.calculate_transient_book_risk(
            ctx, [leg], window=250, horizon=1)

    assert caught.value.code == "custom_risk_deadline_exceeded"
    assert caught.value.details["partial_result_published"] is False


def test_custom_risk_fails_closed_without_exact_snapshot_or_inception_state(
    custom_store,
):
    detail = custom_store.get("phoenix_autocall")
    raw = _risk_leg(detail)
    missing = pricing_new_risk.evaluate_book_capabilities([raw])
    assert missing["unsupported"][0]["code"] == (
        "custom_pricing_evidence_required"
    )

    leg, _book_result = _priced_risk_leg(detail)
    mismatch = pricing_new_risk.evaluate_book_capabilities(
        [leg], bound_snapshot_id="SNAP-OTHER")
    assert mismatch["unsupported"][0]["code"] == "snapshot_binding_mismatch"

    seasoned = json.loads(json.dumps(leg))
    seasoned["params"]["custom_repricing"]["valuation_state"]["mode"] = (
        "seasoned"
    )
    unsupported = pricing_new_risk.evaluate_book_capabilities([seasoned])
    assert unsupported["unsupported"][0]["code"] == (
        "custom_seasoned_state_unsupported"
    )


def test_custom_portfolio_repricing_rejects_tampered_contract_hash(custom_store):
    detail = custom_store.get("phoenix_autocall")
    leg, _book_result = _priced_risk_leg(detail)
    instrument, params, description = to_position(
        "custom_product", leg["params"], "custom_mc")
    params["resolved_contract"]["slots"]["coupon_rate"] = 0.99
    assert leg["params"]["custom_repricing"]["slots"]["coupon_rate"] != 0.99
    portfolio = PortfolioService(snapshot=_snapshot())
    portfolio.add(Position(
        id="tampered", instrument=instrument, quantity=1.0,
        currency="RUB", description=description, params=params,
    ))

    valuation = portfolio.value()

    assert valuation.errors
    assert "repricing contract hash mismatch" in valuation.errors[0]


def test_pricing_new_keeps_typed_attachment_and_materializes_flat_adapter_only_for_execution(
    custom_store,
):
    from api import server

    detail = custom_store.get("phoenix_autocall")
    attachment = json.loads(_attachment(detail))
    request = server.PricingNewLegRequest(
        id="custom", label="Custom Phoenix", product="custom_product",
        engine="custom_mc", currency="RUB", quantity=1_000.0,
        params={}, custom_product=attachment,
    )
    persisted = request.model_dump(mode="json", exclude_none=True)
    execution = server._pricing_new_execution_legs([persisted])[0]

    assert persisted["custom_product"] == attachment
    assert persisted["params"] == {}
    assert "custom_product" not in execution
    assert json.loads(execution["params"]["attachment_json"]) == attachment

    with pytest.raises(ValueError, match="only valid"):
        server._pricing_new_execution_legs([{
            **persisted, "product": "european_option",
        }])


def test_named_pricing_new_route_prices_and_replays_nested_custom_attachment(
    custom_store, monkeypatch, tmp_path,
):
    from api import server

    detail = custom_store.get("phoenix_autocall")
    attachment = json.loads(_attachment(detail))
    run_store = PricingNewRunService(tmp_path / "pricing-new-runs.json")
    service = PricingService()

    monkeypatch.setattr(server, "_pricing_new_runs", run_store)
    monkeypatch.setattr(
        server,
        "_workstation_runtime",
        lambda _env_id: (None, _snapshot(), service, [], []),
    )
    request = server.PricingNewPriceRequest(
        name="Custom payoff replay",
        env_id="FO",
        legs=[server.PricingNewLegRequest(
            id="custom",
            label="Custom Phoenix",
            product="custom_product",
            engine="custom_mc",
            currency="RUB",
            quantity=1_000.0,
            params={},
            custom_product=attachment,
        )],
    )

    created = server.pricing_new_price(request)
    restored = server.pricing_new_run(created["run_id"])

    assert created["request"]["legs"][0]["params"] == {}
    assert created["request"]["legs"][0]["custom_product"] == attachment
    assert created["result"]["success_count"] == 1
    assert created["result"]["legs"][0]["result"]["resolved_inputs"][
        "definition_hash"
    ] == detail["definition_hash"]
    assert restored == created
