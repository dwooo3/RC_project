"""Canonical scenario repricing and CRN Greeks for the custom AST engine."""

from __future__ import annotations

import copy

import pytest

from api.custom_products import (
    CustomProductIntegrityError,
    CustomProductRepricingError,
    CustomProductStore,
    component_greeks_definition,
    custom_mc_resource_budget,
    definition_hash,
    inception_valuation_state,
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
        "enabled": True, "method": "same_seed_regeneration", "seed": 19,
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
    assert first["greeks_evidence"]["rng_contract"]["version"] == 1
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
    assert evidence["repricings"] == 9
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
