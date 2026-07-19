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
from services.portfolio_service import PortfolioService
from services.pricing_service import PricingService


def _snapshot() -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id="SNAP-CUSTOM",
        valuation_date=date(2026, 7, 18),
        source=MarketDataSource.MANUAL,
        quality="MANUAL",
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
    assert position.gamma == pytest.approx(0.4)
    assert position.metadata["custom_product_evidence"]["gamma_aggregation"] \
        == "sum_diagonal_component_gammas_cross_gamma_excluded"
    assert any("cross-gamma" in warning for warning in position.warnings)


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
            )
            for shock in shocks
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


def test_custom_product_blocks_multi_day_risk_before_history(
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
        lambda *_args, **_kwargs: pytest.fail(
            "history must not run without custom time-roll semantics"),
    )

    with pytest.raises(pricing_new_risk.PricingNewRiskError) as caught:
        pricing_new_risk.calculate_transient_book_risk(
            ctx, [leg], window=250, horizon=10)

    assert caught.value.code == "custom_horizon_time_roll_unsupported"
    assert caught.value.details["custom_legs"] == ["custom"]
    assert caught.value.details["requested_horizon"] == 10


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
