"""Canonical scenario repricing and CRN Greeks for the custom AST engine."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from api.custom_products import (
    CustomProductIntegrityError,
    CustomProductRepricingError,
    CustomProductStore,
    component_greeks_definition,
    canonical_dated_fixing_ledger,
    canonical_instance_contract_schedule,
    custom_mc_resource_budget,
    definition_hash,
    historical_roll_forward_state,
    inception_valuation_seed,
    inception_valuation_state,
    reconstruct_historical_valuation_state,
    roll_forward_dated_valuation_state,
    seasoned_valuation_state,
    roll_forward_valuation_state,
    scenario_price_definition,
)


def _weighted_definition() -> dict:
    return {
        "name": "Two-asset linear basket",
        "description": "Test-only generic AST",
        "author": "test",
        "assets": ["Asset A", "Asset B"],
        "slots": {},
        "state": {},
        "schedule": {"observations": 1, "maturity": 1.0},
        "observation_program": [],
        "maturity_program": [{
            "action": "pay",
            "amount": {"node": "weighted", "weights": [0.25, 0.75]},
        }],
    }


def _market() -> dict:
    return {
        "r": 0.0,
        "sigmas": [0.20, 0.25],
        "qs": [0.0, 0.0],
        "corr": [[1.0, 0.3], [0.3, 1.0]],
    }


def _state(defn: dict) -> dict:
    return inception_valuation_state(
        defn,
        {"Asset A": 100.0, "Asset B": 200.0},
        {"Asset A": 100.0, "Asset B": 200.0},
    )


def _published_store(tmp_path) -> tuple[CustomProductStore, dict]:
    store = CustomProductStore(str(tmp_path / "custom.json"))
    created = store.create(definition=_weighted_definition(), author="maker")
    store.compile(created["id"])
    store.submit(created["id"], "maker")
    store.approve(created["id"], "checker")
    published = store.publish(created["id"])
    return store, published


def _dated_accrual_definition() -> dict:
    defn = _weighted_definition()
    # Numeric maturity is intentionally unrelated to the short dated instance:
    # contract_schedule must become authoritative when it is supplied.
    defn["schedule"] = {"observations": 2, "maturity": 1.0}
    defn["state"] = {"accrued": 0.0}
    defn["observation_program"] = [{
        "action": "accumulate",
        "name": "accrued",
        "value": {"node": "accrual"},
    }]
    defn["maturity_program"] = [{
        "action": "pay",
        "amount": {"node": "state", "name": "accrued"},
    }]
    return defn


def _moex_instance_schedule(defn: dict) -> dict:
    return canonical_instance_contract_schedule(defn, {
        "effective_date": "2025-02-03",
        "contractual_observation_dates": ["2025-02-08", "2025-02-15"],
        "observation_dates": ["2025-02-10", "2025-02-17"],
        "contractual_maturity_date": "2025-02-15",
        "maturity_date": "2025-02-17",
        "business_day_convention": "FOLLOWING",
        "fixing_convention": "MOEX_OFFICIAL_CLOSE",
        "calendar": {
            "calendar_id": "MOEX_SECURITIES",
            "source": "MOEX ISS / iss.only=boards / test evidence",
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


def _dated_fixing_rows() -> list[dict]:
    levels = [
        ("2025-02-03", 100.0, 200.0),
        ("2025-02-04", 90.0, 202.0),
        ("2025-02-05", 95.0, 204.0),
        ("2025-02-06", 105.0, 198.0),
        ("2025-02-07", 108.0, 196.0),
        ("2025-02-10", 110.0, 194.0),
        ("2025-02-11", 109.0, 193.0),
        ("2025-02-12", 107.0, 195.0),
        ("2025-02-13", 106.0, 197.0),
        ("2025-02-14", 105.0, 199.0),
        ("2025-02-17", 104.0, 201.0),
    ]
    return [{
        "date": day,
        "spots": {"Asset A": first, "Asset B": second},
    } for day, first, second in levels]


def _dated_ledger(defn: dict, schedule: dict) -> dict:
    return canonical_dated_fixing_ledger(defn, schedule, {
        "source": "MarketDataDB exact MOEX official closes",
        "source_version": "market_data_db_snapshot_2025-02-17T23:59:59+03:00",
        "payload_hash": "b" * 64,
        "fixings": _dated_fixing_rows(),
    })


def test_canonical_scenario_uses_fixed_reference_and_is_replayable():
    defn = _weighted_definition()
    state = _state(defn)
    scenario = {
        "schema_version": 1,
        "spot_multipliers": {"Asset A": 1.10, "Asset B": 1.0},
        "sigma_shifts": {"Asset A": 0.0, "Asset B": 0.0},
    }

    result = scenario_price_definition(
        defn, {}, _market(), state, scenario,
        n_sims=2_000, steps=16, seed=19,
    )
    replay = scenario_price_definition(
        defn, {}, _market(), state, result["scenario"],
        n_sims=2_000, steps=16, seed=19,
    )

    assert result["value"] == pytest.approx(replay["value"], abs=0.0)
    assert result["scenario"]["absolute_current_spots"] == {
        "Asset A": pytest.approx(110.0), "Asset B": pytest.approx(200.0),
    }
    assert result["valuation_state"]["reference_spots"] == {
        "Asset A": 100.0, "Asset B": 200.0,
    }
    evidence = result["repricing_evidence"]
    assert evidence["contract"] == "custom_ast_scenario_repricing"
    assert evidence["contract_version"] == 1
    assert evidence["current_performances"] == {
        "Asset A": pytest.approx(1.1), "Asset B": pytest.approx(1.0),
    }
    assert evidence["time_roll_years"] == 0.0
    assert evidence["common_random_numbers"] == {
        "enabled": True,
        "method": "same_seed_single_stream_chunk_invariant",
        "seed": 19,
    }


@pytest.mark.parametrize(
    "scenario",
    [
        {"spot_multipliers": {"Asset A": 1.1}},
        {"spot_multipliers": {
            "Asset A": 1.1, "Asset B": 1.0, "UNKNOWN": 1.0,
        }},
        {"absolute_current_spots": {
            "Asset A": float("nan"), "Asset B": 200.0,
        }},
        {"sigma_shifts": {"Asset A": 0.01}},
    ],
)
def test_scenario_asset_vectors_fail_closed(scenario):
    defn = _weighted_definition()
    with pytest.raises(CustomProductRepricingError):
        scenario_price_definition(
            defn, {}, _market(), _state(defn), scenario,
            n_sims=1_000, steps=16, seed=3,
        )


def test_inconsistent_dual_spot_representation_fails_closed():
    defn = _weighted_definition()
    with pytest.raises(
        CustomProductRepricingError, match="противоречат",
    ) as exc_info:
        scenario_price_definition(
            defn, {}, _market(), _state(defn), {
                "spot_multipliers": {"Asset A": 1.1, "Asset B": 1.0},
                "absolute_current_spots": {
                    "Asset A": 105.0, "Asset B": 200.0,
                },
            }, n_sims=1_000, steps=16,
        )
    assert exc_info.value.code == "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state.update(mode="seasoned"),
        lambda state: state.update(observation_index=1),
        lambda state: state["current_spots"].update({"Asset A": 99.0}),
        lambda state: state["running_min"].update({"Asset A": 0.8}),
    ],
)
def test_unsupported_seasoned_state_has_stable_code(mutate):
    defn = _weighted_definition()
    state = _state(defn)
    mutate(state)

    with pytest.raises(CustomProductRepricingError) as exc_info:
        scenario_price_definition(
            defn, {}, _market(), state, {},
            n_sims=1_000, steps=16, seed=3,
        )
    assert exc_info.value.code == "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED"
    assert exc_info.value.as_dict()["reason"]


def test_inception_state_builder_rejects_non_reference_performance():
    defn = _weighted_definition()
    with pytest.raises(CustomProductRepricingError) as exc_info:
        inception_valuation_state(
            defn,
            {"Asset A": 101.0, "Asset B": 200.0},
            {"Asset A": 100.0, "Asset B": 200.0},
        )
    assert exc_info.value.code == "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED"


def test_component_greeks_are_deterministic_keyed_and_audited():
    defn = _weighted_definition()
    kwargs = dict(
        defn=defn, slots={}, market=_market(), valuation_state=_state(defn),
        scenario=None, n_sims=4_000, steps=16, seed=71,
        spot_bump_relative=0.005, volatility_bump=0.01,
    )

    first = component_greeks_definition(**kwargs)
    second = component_greeks_definition(**kwargs)

    assert first["component_greeks"] == second["component_greeks"]
    assert first["repricing_evidence"]["rng_contract"]["bit_generator"] == (
        "PCG64")
    assert first["greeks_evidence"]["rng_contract"]["version"] == 2
    assert first["greeks_evidence"]["rng_contract"]["streaming_algorithm"] \
        == "chunk_invariant_sequential_normals_v2"
    by_asset = first["component_greeks"]
    assert list(by_asset) == ["Asset A", "Asset B"]
    assert by_asset["Asset A"]["delta"] == pytest.approx(0.25 / 100.0,
                                                          rel=0.01)
    assert by_asset["Asset B"]["delta"] == pytest.approx(0.75 / 200.0,
                                                          rel=0.01)
    assert by_asset["Asset A"]["gamma"] == pytest.approx(0.0, abs=1e-11)
    assert by_asset["Asset B"]["gamma"] == pytest.approx(0.0, abs=1e-11)
    assert all(row["method"]["vega"] == "central"
               for row in first["component_greeks"].values())
    evidence = first["greeks_evidence"]
    assert evidence["method"] == "finite_difference_common_random_numbers"
    assert evidence["asset_key"] == "logical_definition_asset_name"
    assert evidence["repricings"] == 13
    assert evidence["aggregate_repricings"] == 2
    assert evidence["total_repricings"] == 15
    matrix = np.asarray(first["cross_gamma_matrix"])
    assert matrix.shape == (2, 2)
    assert np.allclose(matrix, matrix.T)
    assert first["cross_gamma_pairs"][0]["cross_gamma"] == pytest.approx(
        0.0, abs=1e-11)
    assert evidence["units"]["vega"] == (
        "dPV per +1 volatility point (0.01 absolute sigma)"
    )
    assert evidence["common_random_numbers"]["seed"] == 71


def test_store_reprice_is_version_hash_pinned_and_adds_identity(tmp_path):
    store, published = _published_store(tmp_path)
    state = _state(published["definition"])

    result = store.component_greeks(
        published["id"], {}, _market(), valuation_state=state,
        n_sims=1_000, steps=16, seed=5, version=published["version"],
        expected_definition_hash=published["definition_hash"],
    )

    assert result["product_id"] == published["id"]
    assert result["version"] == published["version"]
    assert result["definition_hash"] == published["definition_hash"]
    assert result["repricing_evidence"]["definition_version"] \
        == published["version"]
    assert result["watermark"] is None

    with pytest.raises(ValueError, match="definition hash mismatch"):
        store.reprice(
            published["id"], {}, _market(), valuation_state=state,
            n_sims=1_000, steps=16, version=published["version"],
            expected_definition_hash="0" * 64,
        )


def test_store_reprice_rejects_tampered_definition_and_result(tmp_path,
                                                               monkeypatch):
    store, published = _published_store(tmp_path)
    state = _state(published["definition"])
    store._data[published["id"]]["versions"][0]["definition"][
        "description"
    ] = "tampered"
    with pytest.raises(CustomProductIntegrityError,
                       match="definition hash integrity mismatch"):
        store.reprice(
            published["id"], {}, _market(), valuation_state=state,
            n_sims=1_000, steps=16, version=1,
        )

    clean_store, clean = _published_store(tmp_path / "clean")
    clean_state = _state(clean["definition"])

    def wrong_hash(*args, **kwargs):
        return {
            "definition_hash": "0" * 64,
            "repricing_evidence": {},
        }

    monkeypatch.setattr("api.custom_products.scenario_price_definition",
                        wrong_hash)
    with pytest.raises(CustomProductIntegrityError,
                       match="repricing result definition hash mismatch"):
        clean_store.reprice(
            clean["id"], {}, _market(), valuation_state=clean_state,
            n_sims=1_000, steps=16, version=1,
        )


def test_state_hash_changes_when_economics_contract_changes():
    defn = _weighted_definition()
    original = _state(defn)
    changed = copy.deepcopy(original)
    changed["schema_version"] = 2
    assert definition_hash(defn)
    with pytest.raises(CustomProductRepricingError) as exc_info:
        scenario_price_definition(
            defn, {}, _market(), changed, {}, n_sims=1_000, steps=16,
        )
    assert exc_info.value.code == "CUSTOM_PRODUCT_REPRICING_SCHEMA_UNSUPPORTED"


def test_custom_mc_resource_preflight_blocks_oom_grid_and_greek_work():
    with pytest.raises(CustomProductRepricingError) as unit_error:
        custom_mc_resource_budget(5, 200_000, 1_024)
    assert unit_error.value.code == "CUSTOM_PRODUCT_RESOURCE_LIMIT"

    # The unit cube fits, but 21 CRN repricings for five components do not.
    with pytest.raises(CustomProductRepricingError) as greek_error:
        custom_mc_resource_budget(
            5, 19_000, 252, include_greeks=True,
        )
    assert greek_error.value.code == "CUSTOM_PRODUCT_RESOURCE_LIMIT"


def test_custom_mc_resource_budget_is_returned_as_pricing_evidence():
    defn = _weighted_definition()
    result = scenario_price_definition(
        defn, {}, _market(), _state(defn), {},
        n_sims=1_000, steps=16, seed=23,
    )

    budget = result["resource_budget"]
    assert budget["policy"] == "custom_mc_resource_v1"
    assert budget["path_points"] == 2 * 1_000 * 17
    assert result["repricing_evidence"]["resource_budget"] == budget


def test_seasoned_state_prices_only_remaining_observations():
    defn = _weighted_definition()
    defn["schedule"] = {"observations": 2, "maturity": 1.0}
    defn["state"] = {"seen": 0.0}
    defn["observation_program"] = [{
        "action": "accumulate", "name": "seen",
        "value": {"node": "const", "value": 1.0},
    }]
    defn["maturity_program"] = [{
        "action": "pay", "amount": {"node": "state", "name": "seen"},
    }]
    state = seasoned_valuation_state(
        defn, {"Asset A": 110.0, "Asset B": 200.0},
        {"Asset A": 100.0, "Asset B": 200.0}, 1,
        state_values={"seen": 1.0}, running_min={"Asset A": 1.0, "Asset B": 1.0},
        running_max={"Asset A": 1.1, "Asset B": 1.0},
    )
    result = scenario_price_definition(
        defn, {}, _market(), state, {}, n_sims=1_000, steps=16, seed=9,
    )
    assert result["value"] == pytest.approx(2.0)
    assert result["repricing_evidence"]["state_mode"] == "seasoned"
    assert result["repricing_evidence"]["seasoned_state_supported"] is True
    assert result["repricing_evidence"]["time_roll_years"] == pytest.approx(0.5)


def test_roll_forward_applies_observation_program_once_and_is_replayable():
    defn = _weighted_definition()
    defn["schedule"] = {"observations": 2, "maturity": 1.0}
    defn["state"] = {"seen": 0.0}
    defn["observation_program"] = [{
        "action": "accumulate", "name": "seen",
        "value": {"node": "const", "value": 1.0},
    }]
    defn["maturity_program"] = [{
        "action": "pay", "amount": {"node": "state", "name": "seen"},
    }]
    inception = inception_valuation_state(
        defn, {"Asset A": 100.0, "Asset B": 200.0},
    )
    seasoned = roll_forward_valuation_state(
        defn, inception,
        [{"observation_index": 1,
          "spots": {"Asset A": 110.0, "Asset B": 190.0}}],
    )
    assert seasoned["mode"] == "seasoned"
    assert seasoned["observation_index"] == 1
    assert seasoned["state_values"] == {"seen": 1.0}
    assert seasoned["running_min"] == {"Asset A": pytest.approx(1.0),
                                        "Asset B": pytest.approx(0.95)}
    replay = scenario_price_definition(
        defn, {}, _market(), seasoned, {}, n_sims=1_000, steps=16, seed=9,
    )
    assert replay["value"] == pytest.approx(2.0)


def test_chunked_mc_bounds_peak_memory_and_is_replayable():
    defn = _weighted_definition()
    state = _state(defn)
    kwargs = dict(
        defn=defn, slots={}, market=_market(), valuation_state=state,
        scenario={}, n_sims=3_000, steps=32, seed=31, chunk_size=512,
    )
    first = scenario_price_definition(**kwargs)
    second = scenario_price_definition(**kwargs)
    assert first["value"] == second["value"]
    budget = first["resource_budget"]
    assert budget["chunked"] is True
    assert budget["chunk_size"] == 512
    assert budget["path_points"] < budget["total_path_points"]
    assert budget["estimated_peak_bytes"] < 512 * 32 * 2 * 64


def test_historical_roll_advances_time_and_preserves_intrawindow_extrema():
    defn = _weighted_definition()
    defn["schedule"] = {"observations": 4, "maturity": 1.0}
    state = _state(defn)
    down_up = historical_roll_forward_state(
        defn, state,
        [
            {"Asset A": np.log(0.8), "Asset B": 0.0},
            {"Asset A": np.log(1.25), "Asset B": 0.0},
        ],
    )
    flat = historical_roll_forward_state(
        defn, state,
        [{"Asset A": 0.0, "Asset B": 0.0}] * 2,
    )

    rolled = down_up["valuation_state"]
    assert rolled["observation_index"] == 0
    assert rolled["elapsed_time"] == pytest.approx(2 / 252)
    assert rolled["current_spots"]["Asset A"] == pytest.approx(100.0)
    assert rolled["running_min"]["Asset A"] == pytest.approx(0.8)
    assert down_up["evidence"]["path_hash"] != flat["evidence"]["path_hash"]
    assert down_up["evidence"]["transition_hash"] != flat["evidence"][
        "transition_hash"]


def test_historical_roll_books_autocall_cashflow_and_carries_to_horizon():
    defn = _weighted_definition()
    defn["schedule"] = {"observations": 4, "maturity": 1.0}
    defn["observation_program"] = [{
        "action": "terminate",
        "when": {"node": "ge", "args": [
            {"node": "worst_of"}, {"node": "const", "value": 1.0},
        ]},
        "payout": {"node": "const", "value": 1.0},
    }]
    result = historical_roll_forward_state(
        defn, _state(defn),
        [{"Asset A": 0.0, "Asset B": 0.0}] * 126,
        reinvestment_rate=0.10,
    )

    assert result["terminal"] is True
    assert result["valuation_state"] is None
    assert result["cashflows"] == [{"time": 0.25, "amount": 1.0}]
    assert result["horizon_cashflow"] == pytest.approx(
        np.exp(0.10 * (126 / 252 - 0.25)))
    assert result["evidence"]["terminated_early"] is True


def test_historical_roll_handles_maturity_and_nondefault_schedule_slots():
    defn = _weighted_definition()
    defn["slots"] = {
        "term": {"type": "number", "default": 1.0, "min": 0.05, "max": 3.0},
        "obs": {"type": "number", "default": 2.0, "min": 1.0, "max": 12.0},
    }
    defn["schedule"] = {
        "observations": {"slot": "obs"},
        "maturity": {"slot": "term"},
    }
    slots = {"term": 0.1, "obs": 1.0}
    result = historical_roll_forward_state(
        defn, _state(defn),
        [{"Asset A": 0.0, "Asset B": 0.0}] * 26,
        slots=slots,
    )
    assert result["terminal"] is True
    assert result["cashflows"][0]["time"] == pytest.approx(0.1)
    assert result["horizon_cashflow"] == pytest.approx(1.0)


def test_chunked_mc_is_chunk_size_invariant_with_odd_path_tail():
    defn = _weighted_definition()
    defn["assets"] = ["Asset A"]
    defn["maturity_program"] = [{
        "action": "pay", "amount": {"node": "perf"},
    }]
    state = inception_valuation_state(
        defn, {"Asset A": 100.0}, {"Asset A": 100.0})
    common = dict(
        defn=defn, slots={},
        market={"r": 0.0, "sigma": 0.2, "q": 0.0},
        valuation_state=state,
        scenario={}, n_sims=1_001, steps=16, seed=123,
    )
    whole = scenario_price_definition(**common)
    chunked = scenario_price_definition(**common, chunk_size=512)
    assert chunked["value"] == whole["value"]
    assert chunked["stderr"] == whole["stderr"]
    assert chunked["n_sims"] == 1_001


def test_pairwise_cross_gamma_matrix_prices_bilinear_payoff():
    defn = _weighted_definition()
    defn["maturity_program"] = [{
        "action": "pay",
        "amount": {"node": "mul", "args": [
            {"node": "asset", "index": 0},
            {"node": "asset", "index": 1},
        ]},
    }]
    result = component_greeks_definition(
        defn, {}, _market(), _state(defn), n_sims=1_000, steps=16, seed=5,
    )
    matrix = np.asarray(result["cross_gamma_matrix"])
    assert matrix[0, 1] == pytest.approx(
        result["value"] / (100.0 * 200.0), rel=1e-8)
    assert matrix[1, 0] == pytest.approx(matrix[0, 1])
    assert result["pairwise_cross_gamma_contribution"] == pytest.approx(
        2.0 * result["value"], rel=1e-8)
    assert result["parallel_gamma"] == pytest.approx(
        2.0 * result["value"], rel=1e-8)


def test_malformed_seasoned_alive_and_extrema_fail_closed():
    defn = _weighted_definition()
    defn["schedule"] = {"observations": 2, "maturity": 1.0}
    state = seasoned_valuation_state(
        defn, {"Asset A": 100.0, "Asset B": 200.0},
        {"Asset A": 100.0, "Asset B": 200.0}, 0,
        elapsed_time=0.1,
    )
    bad_alive = copy.deepcopy(state); bad_alive["alive"] = "yes"
    with pytest.raises(CustomProductRepricingError):
        scenario_price_definition(
            defn, {}, _market(), bad_alive, {}, n_sims=1_000, steps=16)
    bad_extrema = copy.deepcopy(state)
    bad_extrema["running_min"]["Asset A"] = 1.1
    with pytest.raises(CustomProductRepricingError):
        scenario_price_definition(
            defn, {}, _market(), bad_extrema, {}, n_sims=1_000, steps=16)


@pytest.mark.parametrize("chunk_size", [float("nan"), float("inf"), "bad"])
def test_chunk_size_validation_keeps_stable_resource_error(chunk_size):
    with pytest.raises(CustomProductRepricingError) as caught:
        custom_mc_resource_budget(1, 1_000, 16, chunk_size=chunk_size)
    assert caught.value.code == "CUSTOM_PRODUCT_RESOURCE_LIMIT"


def test_fractional_observation_slot_fails_closed_in_every_pricing_route():
    defn = _weighted_definition()
    defn["slots"] = {
        "obs": {"type": "number", "default": 2.0, "min": 1.0, "max": 12.0},
    }
    defn["schedule"]["observations"] = {"slot": "obs"}

    with pytest.raises(CustomProductRepricingError) as caught:
        scenario_price_definition(
            defn, {"obs": 1.5}, _market(), _state(defn), {},
            n_sims=1_000, steps=16,
        )
    assert caught.value.code == "CUSTOM_PRODUCT_REPRICING_INVALID_STATE"
    assert "integer" in caught.value.reason


@pytest.mark.parametrize("override", [0.0, 13.0])
def test_schedule_slot_override_bounds_fail_closed(override):
    defn = _weighted_definition()
    defn["slots"] = {
        "obs": {"type": "number", "default": 2.0, "min": 1.0, "max": 12.0},
    }
    defn["schedule"]["observations"] = {"slot": "obs"}

    with pytest.raises(CustomProductRepricingError) as caught:
        scenario_price_definition(
            defn, {"obs": override}, _market(), _state(defn), {},
            n_sims=1_000, steps=16,
        )
    assert caught.value.code == "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO"


def test_dated_schedule_preserves_contractual_and_resolved_moex_dates():
    schedule = _moex_instance_schedule(_dated_accrual_definition())

    assert schedule["contractual_observation_dates"] == [
        "2025-02-08", "2025-02-15",
    ]
    assert schedule["observation_dates"] == ["2025-02-10", "2025-02-17"]
    assert schedule["business_day_convention"] == "FOLLOWING"
    assert schedule["calendar"]["calendar_id"] == "MOEX_SECURITIES"
    assert schedule["calendar"]["source_hash"] == "a" * 64
    # Canonical contracts are idempotent and verify their embedded hashes.
    assert canonical_instance_contract_schedule(
        _dated_accrual_definition(), schedule,
    ) == schedule


def test_actual_state_reconstruction_replays_every_session_and_event():
    defn = _dated_accrual_definition()
    schedule = _moex_instance_schedule(defn)
    seed = inception_valuation_seed(
        defn, schedule, {"Asset A": 100.0, "Asset B": 200.0},
    )
    result = reconstruct_historical_valuation_state(
        defn, schedule, seed, _dated_ledger(defn, schedule), "2025-02-12",
    )

    state = result["valuation_state"]
    assert state["mode"] == "seasoned"
    assert state["state_as_of"] == "2025-02-12"
    assert state["observation_index"] == 1
    assert state["elapsed_time"] == pytest.approx(9 / 365)
    assert state["state_values"]["accrued"] == pytest.approx(7 / 365)
    assert state["current_spots"] == {"Asset A": 107.0, "Asset B": 195.0}
    assert state["running_min"]["Asset A"] == pytest.approx(0.9)
    assert state["running_min"]["Asset B"] == pytest.approx(0.965)
    assert state["instance_schedule_hash"] == schedule["schedule_hash"]
    assert state["inception_seed_hash"] == seed["seed_hash"]
    assert result["evidence"]["processed_event_count"] == 1
    assert result["evidence"]["required_session_count"] == 8


def test_dated_roll_reaches_maturity_and_returns_realized_cashflow_ledger():
    defn = _dated_accrual_definition()
    schedule = _moex_instance_schedule(defn)
    ledger = _dated_ledger(defn, schedule)
    seed = inception_valuation_seed(
        defn, schedule, {"Asset A": 100.0, "Asset B": 200.0},
    )
    start = reconstruct_historical_valuation_state(
        defn, schedule, seed, ledger, "2025-02-12",
    )["valuation_state"]
    result = roll_forward_dated_valuation_state(
        defn, schedule, start, ledger, "2025-02-17",
    )

    assert result["terminal"] is True
    assert result["terminal_reason"] == "maturity"
    assert result["valuation_state"] is None
    assert result["cashflows"] == [{
        "date": "2025-02-17",
        "time": pytest.approx(14 / 365),
        "amount": pytest.approx(14 / 365),
        "phase": "maturity",
        "action_index": 0,
        "observation_index": 1,
    }]
    assert result["evidence"]["contract"] == "custom_ast_dated_path_roll_v1"


def test_scenario_mc_uses_resolved_event_times_instead_of_numeric_template_t():
    defn = _dated_accrual_definition()
    schedule = _moex_instance_schedule(defn)
    seed = inception_valuation_seed(
        defn, schedule, {"Asset A": 100.0, "Asset B": 200.0},
    )
    dated = scenario_price_definition(
        defn, {}, _market(), seed["valuation_state"], {},
        n_sims=1_000, steps=16, seed=17,
        contract_schedule=schedule,
    )
    numeric = scenario_price_definition(
        defn, {}, _market(), inception_valuation_state(
            defn, {"Asset A": 100.0, "Asset B": 200.0}), {},
        n_sims=1_000, steps=16, seed=17,
    )

    assert dated["value"] == pytest.approx(14 / 365)
    assert numeric["value"] == pytest.approx(1.0)
    assert dated["repricing_evidence"]["observation_times"] == pytest.approx(
        [7 / 365, 14 / 365],
    )
    assert dated["repricing_evidence"]["timing_contract"] == (
        "resolved_dated_schedule_act_365f_v1"
    )


def test_actual_reconstruction_fails_closed_on_session_gap_and_hash_tamper():
    defn = _dated_accrual_definition()
    schedule = _moex_instance_schedule(defn)
    seed = inception_valuation_seed(
        defn, schedule, {"Asset A": 100.0, "Asset B": 200.0},
    )
    missing = [row for row in _dated_fixing_rows()
               if row["date"] != "2025-02-06"]
    with pytest.raises(CustomProductRepricingError) as gap:
        reconstruct_historical_valuation_state(
            defn, schedule, seed, {
                "source": "MarketDataDB exact MOEX official closes",
                "source_version": (
                    "market_data_db_snapshot_2025-02-17T23:59:59+03:00"
                ),
                "payload_hash": "b" * 64,
                "fixings": missing,
            }, "2025-02-12",
        )
    assert gap.value.code == "CUSTOM_PRODUCT_HISTORICAL_STATE_GAP"

    tampered_ledger = copy.deepcopy(_dated_ledger(defn, schedule))
    tampered_ledger["fixings"][1]["spots"]["Asset A"] = 91.0
    with pytest.raises(CustomProductRepricingError) as ledger_integrity:
        canonical_dated_fixing_ledger(defn, schedule, tampered_ledger)
    assert ledger_integrity.value.code == "CUSTOM_PRODUCT_FIXING_LEDGER_INTEGRITY"

    tampered_schedule = copy.deepcopy(schedule)
    tampered_schedule["fixing_convention"] = "MOEX_CLOSING_AUCTION"
    with pytest.raises(CustomProductRepricingError) as schedule_integrity:
        canonical_instance_contract_schedule(defn, tampered_schedule)
    assert schedule_integrity.value.code == (
        "CUSTOM_PRODUCT_INSTANCE_SCHEDULE_INTEGRITY"
    )

    tampered_seed = copy.deepcopy(seed)
    tampered_seed["reference_fixing"]["spots"]["Asset A"] = 99.0
    with pytest.raises(CustomProductRepricingError) as seed_integrity:
        reconstruct_historical_valuation_state(
            defn, schedule, tampered_seed, _dated_ledger(defn, schedule),
            "2025-02-12",
        )
    assert seed_integrity.value.code == "CUSTOM_PRODUCT_INCEPTION_SEED_INTEGRITY"

    unordered = copy.deepcopy(_dated_fixing_rows())
    unordered[1], unordered[2] = unordered[2], unordered[1]
    with pytest.raises(CustomProductRepricingError) as date_order:
        canonical_dated_fixing_ledger(defn, schedule, {
            "source": "MarketDataDB exact MOEX official closes",
            "source_version": "snapshot-v1",
            "payload_hash": "b" * 64,
            "fixings": unordered,
        })
    assert date_order.value.code == "CUSTOM_PRODUCT_FIXING_LEDGER_INVALID"


def test_dated_current_state_historical_roll_requires_exact_session_dates():
    defn = _dated_accrual_definition()
    schedule = _moex_instance_schedule(defn)
    seed = inception_valuation_seed(
        defn, schedule, {"Asset A": 100.0, "Asset B": 200.0},
    )
    ledger = _dated_ledger(defn, schedule)
    start = reconstruct_historical_valuation_state(
        defn, schedule, seed, ledger, "2025-02-12",
    )["valuation_state"]
    flat = [{"Asset A": 0.0, "Asset B": 0.0}] * 3
    result = historical_roll_forward_state(
        defn, start, flat,
        contract_schedule=schedule,
        path_dates=["2025-02-13", "2025-02-14", "2025-02-17"],
    )
    assert result["terminal"] is True
    assert result["horizon_cashflow"] == pytest.approx(14 / 365)

    with pytest.raises(CustomProductRepricingError) as gap:
        historical_roll_forward_state(
            defn, start, flat,
            contract_schedule=schedule,
            path_dates=["2025-02-13", "2025-02-17", "2025-02-18"],
        )
    assert gap.value.code == "CUSTOM_PRODUCT_HISTORICAL_STATE_GAP"


def test_store_reprice_threads_dated_schedule_into_the_mc_evaluator(tmp_path):
    defn = _dated_accrual_definition()
    store = CustomProductStore(str(tmp_path / "dated-custom.json"))
    created = store.create(definition=defn, author="maker")
    store.compile(created["id"])
    store.submit(created["id"], "maker")
    store.approve(created["id"], "checker")
    published = store.publish(created["id"])
    schedule = _moex_instance_schedule(defn)
    seed = inception_valuation_seed(
        defn, schedule, {"Asset A": 100.0, "Asset B": 200.0},
    )

    result = store.reprice(
        published["id"], {}, _market(),
        valuation_state=seed["valuation_state"], scenario={},
        contract_schedule=schedule,
        n_sims=1_000, steps=16, seed=3,
        expected_definition_hash=published["definition_hash"],
    )

    assert result["value"] == pytest.approx(14 / 365)
    assert result["repricing_evidence"]["instance_schedule_hash"] == (
        schedule["schedule_hash"]
    )
