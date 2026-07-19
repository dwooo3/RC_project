"""Contract, diagnostics and workstation tests for the multi-asset autocall."""

from __future__ import annotations

import math

import numpy as np
import pytest

from api.pricing_workstation import build_ws_catalogue, price_book_ws, price_ws
import instruments.structured.multi_asset_autocall as autocall_module
from instruments.structured.basket_note import Constituent
from instruments.structured.multi_asset_autocall import multi_asset_autocall
from instruments.structured.multi_asset_autocall import (
    multi_asset_autocall_component_greeks,
)
from services.pricing_service import PricingService


def _basket(*, vol_a: float = 0.40, vol_b: float = 0.35):
    return [
        Constituent("A", "equity", 100.0, 0.55, vol_a, 0.0),
        Constituent("B", "index", 200.0, 0.45, vol_b, 0.0),
    ]


_CORRELATION = np.array([[1.0, 0.25], [0.25, 1.0]])


def test_zero_vol_guaranteed_coupon_and_protected_principal_are_exact():
    result = multi_asset_autocall(
        _basket(vol_a=0.0, vol_b=0.0),
        r=0.0,
        T=3.0,
        correlation=_CORRELATION,
        observation_dates=[1.0, 2.0, 3.0],
        autocall_barrier=2.0,
        coupon_rate=0.0,
        guaranteed_coupon=0.05,
        notional=1_000.0,
        n_sims=1_000,
        steps=3,
    )

    assert result["price"] == pytest.approx(1_150.0, abs=1e-12)
    assert result["price_ratio"] == pytest.approx(1.15, abs=1e-12)
    assert result["stderr"] == pytest.approx(0.0, abs=1e-12)
    assert result["autocall_probability"] == 0.0
    assert result["survival_probability"] == 1.0
    assert result["capital_loss_probability"] == 0.0
    assert result["expected_coupon_ratio"] == pytest.approx(0.15, abs=1e-12)


def test_first_observation_autocall_matches_discounted_closed_form():
    rate = 0.04
    constituents = [
        Constituent("A", "equity", 100.0, 0.5, 0.0, rate),
        Constituent("B", "index", 200.0, 0.5, 0.0, rate),
    ]
    result = multi_asset_autocall(
        constituents,
        r=rate,
        T=2.0,
        correlation=_CORRELATION,
        observation_dates=[1.0, 2.0],
        autocall_barrier=1.0,
        coupon_rate=0.0,
        guaranteed_coupon=0.05,
        notional=1_000.0,
        n_sims=1_000,
        steps=2,
    )

    expected = 1_050.0 * math.exp(-rate)
    assert result["price"] == pytest.approx(expected, rel=1e-12)
    assert result["autocall_probability"] == 1.0
    assert result["expected_life"] == pytest.approx(1.0)
    assert result["expected_principal_ratio"] == pytest.approx(1.0)


def test_trigger_aggregations_are_independent_and_pathwise_ordered():
    common = dict(
        constituents=_basket(),
        r=0.0,
        T=2.0,
        correlation=_CORRELATION,
        observation_dates=[0.5, 1.0, 1.5, 2.0],
        autocall_barrier=1.10,
        protection_barrier=0.0,
        coupon_rate=0.0,
        guaranteed_coupon=0.0,
        n_sims=4_000,
        steps=40,
        seed=17,
    )
    autocall = {
        mode: multi_asset_autocall(
            autocall_aggregation=mode,
            protection_aggregation="worst_of",
            **common,
        )
        for mode in ("best_of", "average", "worst_of")
    }
    assert (
        autocall["best_of"]["autocall_probability"]
        >= autocall["average"]["autocall_probability"]
        >= autocall["worst_of"]["autocall_probability"]
    )

    protection_common = {
        **common,
        "observation_dates": [2.0],
        "autocall_barrier": 5.0,
        "protection_barrier": 0.80,
    }
    protection = {
        mode: multi_asset_autocall(
            autocall_aggregation="best_of",
            protection_aggregation=mode,
            **protection_common,
        )
        for mode in ("worst_of", "average", "best_of")
    }
    assert (
        protection["worst_of"]["capital_loss_probability"]
        >= protection["average"]["capital_loss_probability"]
        >= protection["best_of"]["capital_loss_probability"]
    )


def test_memory_coupon_is_reproducible_and_pays_catchups():
    common = dict(
        constituents=_basket(vol_a=0.45, vol_b=0.40),
        r=0.0,
        T=2.0,
        correlation=_CORRELATION,
        observation_dates=[0.5, 1.0, 1.5, 2.0],
        autocall_barrier=5.0,
        coupon_barrier=0.90,
        coupon_rate=0.10,
        guaranteed_coupon=0.0,
        n_sims=5_000,
        steps=40,
        seed=7,
    )
    with_memory = multi_asset_autocall(memory_coupon=True, **common)
    replay = multi_asset_autocall(memory_coupon=True, **common)
    without_memory = multi_asset_autocall(memory_coupon=False, **common)

    assert replay == with_memory
    assert with_memory["price"] > without_memory["price"]
    assert with_memory["memory_coupon_paid_probability"] > 0.0
    assert 0.0 < with_memory["coupon_hit_probability"] < 1.0
    assert with_memory["ci95_low"] <= with_memory["price"] <= with_memory["ci95_high"]
    assert len(with_memory["autocall_cumulative"]) == 4
    assert with_memory["pv_distribution"]


def test_continuous_protection_monitoring_contains_maturity_breaches():
    common = dict(
        constituents=_basket(vol_a=0.50, vol_b=0.45),
        r=0.0,
        T=2.0,
        correlation=_CORRELATION,
        observation_dates=[2.0],
        autocall_barrier=5.0,
        protection_barrier=0.85,
        coupon_rate=0.0,
        guaranteed_coupon=0.0,
        n_sims=5_000,
        steps=40,
        seed=23,
    )
    maturity = multi_asset_autocall(
        protection_monitoring="maturity", **common
    )
    continuous = multi_asset_autocall(
        protection_monitoring="continuous", **common
    )

    assert (
        continuous["protection_breach_probability"]
        >= maturity["protection_breach_probability"]
    )
    assert (
        continuous["capital_loss_probability"]
        >= maturity["capital_loss_probability"]
    )


def test_reference_spots_are_immutable_contract_fixings_for_repricing():
    constituent = [Constituent("A", "equity", 80.0, 1.0, 0.0, 0.0)]
    common = dict(
        r=0.0,
        T=1.0,
        observation_dates=[1.0],
        autocall_barrier=5.0,
        protection_barrier=0.90,
        coupon_rate=0.0,
        guaranteed_coupon=0.0,
        notional=1_000.0,
        n_sims=1_000,
        steps=1,
        seed=5,
    )

    inception_reset = multi_asset_autocall(constituent, **common)
    seasoned = multi_asset_autocall(
        constituent, reference_spots=[100.0], **common
    )

    assert inception_reset["price"] == pytest.approx(1_000.0)
    assert seasoned["price"] == pytest.approx(800.0)
    assert seasoned["reference_spots"] == {"A": 100.0}


def test_component_greeks_use_crn_and_return_named_map():
    result = multi_asset_autocall_component_greeks(
        [Constituent("A", "equity", 80.0, 1.0, 0.0, 0.0)],
        r=0.0,
        T=1.0,
        reference_spots=[100.0],
        observation_dates=[1.0],
        autocall_barrier=5.0,
        protection_barrier=0.90,
        coupon_rate=0.0,
        guaranteed_coupon=0.0,
        notional=1_000.0,
        n_sims=1_000,
        steps=1,
        seed=9,
    )
    replay = multi_asset_autocall_component_greeks(
        [Constituent("A", "equity", 80.0, 1.0, 0.0, 0.0)],
        r=0.0,
        T=1.0,
        reference_spots=[100.0],
        observation_dates=[1.0],
        autocall_barrier=5.0,
        protection_barrier=0.90,
        coupon_rate=0.0,
        guaranteed_coupon=0.0,
        notional=1_000.0,
        n_sims=1_000,
        steps=1,
        seed=9,
    )

    assert replay == result
    assert set(result["component_greeks"]) == {"A"}
    assert result["component_greeks"]["A"]["delta"] == pytest.approx(10.0)
    assert result["component_greeks"]["A"]["gamma"] == pytest.approx(
        0.0, abs=1e-10
    )
    assert result["greeks_method"] == (
        "central_fd_common_random_numbers_with_parallel_cross_gamma"
    )


def test_component_greeks_reject_barrier_reset_without_reference_spots():
    with pytest.raises(ValueError, match="immutable reference_spots"):
        multi_asset_autocall_component_greeks(
            _basket(), r=0.0, T=1.0, n_sims=1_000, steps=1
        )


def test_component_greeks_generate_one_common_shock_cube(monkeypatch):
    calls = 0
    original = autocall_module._correlated_normals

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(autocall_module, "_correlated_normals", counted)
    multi_asset_autocall_component_greeks(
        _basket(),
        r=0.0,
        T=1.0,
        reference_spots=[100.0, 200.0],
        observation_dates=[0.5, 1.0],
        n_sims=1_000,
        steps=4,
        seed=27,
    )

    assert calls == 1


def test_reusable_path_component_delta_matches_public_bump_and_revalue():
    items = [
        Constituent("A", "equity", 95.0, 0.5, 0.30, 0.01),
        Constituent("B", "equity", 110.0, 0.5, 0.25, 0.02),
    ]
    common = dict(
        reference_spots=[100.0, 100.0],
        observation_dates=[0.5, 1.0],
        n_sims=2_000,
        steps=10,
        seed=7,
    )
    greeks = multi_asset_autocall_component_greeks(
        items, r=0.05, T=1.0, **common
    )
    ds = items[0].spot * 0.01
    up = [Constituent("A", "equity", 95.0 + ds, 0.5, 0.30, 0.01), items[1]]
    down = [Constituent("A", "equity", 95.0 - ds, 0.5, 0.30, 0.01), items[1]]
    direct_delta = (
        multi_asset_autocall(up, r=0.05, T=1.0, **common)["price"]
        - multi_asset_autocall(down, r=0.05, T=1.0, **common)["price"]
    ) / (2.0 * ds)

    assert greeks["component_greeks"]["A"]["delta"] == pytest.approx(
        direct_delta, rel=1e-12, abs=1e-12
    )


def test_parallel_gamma_includes_cross_gamma_and_keeps_diagonal_explicit():
    items = [
        Constituent("A", "equity", 95.0, 0.5, 0.30, 0.01),
        Constituent("B", "equity", 110.0, 0.5, 0.25, 0.02),
    ]
    common = dict(
        reference_spots=[100.0, 100.0],
        observation_dates=[0.5, 1.0],
        autocall_barrier=1.10,
        protection_barrier=0.80,
        coupon_barrier=0.80,
        coupon_rate=0.05,
        n_sims=5_000,
        steps=20,
        seed=7,
    )
    result = multi_asset_autocall_component_greeks(
        items, r=0.05, T=1.0, **common
    )
    h = result["parallel_spot_bump_relative"]
    up = [
        Constituent(item.name, item.kind, item.spot * (1.0 + h),
                    item.weight, item.vol, item.income)
        for item in items
    ]
    down = [
        Constituent(item.name, item.kind, item.spot * (1.0 - h),
                    item.weight, item.vol, item.income)
        for item in items
    ]
    direct_gamma = (
        multi_asset_autocall(up, r=0.05, T=1.0, **common)["price"]
        - 2.0 * result["price"]
        + multi_asset_autocall(down, r=0.05, T=1.0, **common)["price"]
    ) / (h * h)
    weighted_diagonal = sum(
        result["component_greeks"][item.name]["diagonal_gamma"]
        * item.spot ** 2
        for item in items
    )

    assert result["gamma"] == pytest.approx(direct_gamma, abs=1e-9)
    assert result["parallel_gamma"] == pytest.approx(direct_gamma, abs=1e-9)
    assert result["parallel_diagonal_gamma"] == pytest.approx(
        weighted_diagonal, abs=1e-9
    )
    assert result["parallel_cross_gamma"] == pytest.approx(
        direct_gamma - weighted_diagonal, abs=1e-9
    )
    assert abs(result["parallel_cross_gamma"]) > 1.0
    for row in result["component_greeks"].values():
        assert row["gamma"] == row["diagonal_gamma"]
        assert row["gamma_convention"] == "d2PV/dS_i2"
    assert result["gamma_convention"].startswith("d2PV/dx2")


@pytest.mark.parametrize(
    ("constituents", "kwargs", "message"),
    [
        (
            [Constituent(str(i), "equity", 100.0) for i in range(6)],
            {},
            "1 to 5 underlyings",
        ),
        (
            _basket(),
            {"correlation": [[1.0, 1.1], [1.1, 1.0]]},
            r"correlation entries must be in \[-1, 1\]",
        ),
        (
            _basket(),
            {"observation_dates": [0.01, 0.02], "steps": 10},
            "too small to distinguish",
        ),
        (_basket(), {"memory_coupon": "yes"}, "must be boolean"),
        (
            [Constituent(str(i), "equity", 100.0) for i in range(5)],
            {"n_sims": 100_000, "steps": 100},
            "Monte-Carlo grid is too large",
        ),
    ],
)
def test_invalid_contracts_fail_before_simulation(constituents, kwargs, message):
    numerical = {"n_sims": 1_000, **kwargs}
    with pytest.raises(ValueError, match=message):
        multi_asset_autocall(
            constituents,
            r=0.0,
            T=1.0,
            **numerical,
        )


def test_service_resolves_mixed_real_market_inputs_and_governs_result():
    service = PricingService()
    result = service.price_multi_asset_autocall(
        [
            {"secid": "SBER", "kind": "equity", "weight": 0.4},
            {"secid": "IMOEX", "kind": "index", "weight": 0.3},
            {"secid": "SU26238RMFS4", "kind": "bond", "weight": 0.3},
        ],
        r=0.16,
        T=1.0,
        observation_dates=[0.5, 1.0],
        n_sims=1_000,
        steps=10,
        seed=11,
    )

    assert result["errors"] == []
    assert math.isfinite(result["value"])
    assert result["model_id"] == "structured_autocall"
    assert result["calculation_id"].startswith("calc_")
    assert result["raw"]["resolved_inputs"]["resolved_snapshot_id"]
    assert result["raw"]["market_data_evidence"]["resolved_inputs_hash"]
    assert set(result["raw"]["underlying_spots"]) == {
        "SBER", "IMOEX", "SU26238RMFS4"
    }
    assert len(result["raw"]["correlation_by_pair"]) == 3
    assert any("Bond underlyings" in warning for warning in result["warnings"])
    assert any("market-data fallback" in warning for warning in result["warnings"])


def test_service_preserves_seasoned_contract_fixings_in_replay_and_risk_state():
    service = PricingService()
    result = service.price_multi_asset_autocall(
        [
            {"secid": "SBER", "kind": "equity", "weight": 0.5},
            {"secid": "IMOEX", "kind": "index", "weight": 0.5},
        ],
        r=0.10,
        T=1.0,
        reference_spots=[300.0, 3_000.0],
        reference_fixing_dates=["2025-07-18", "2025-07-18"],
        observation_dates=[1.0],
        n_sims=1_000,
        steps=10,
        seed=13,
    )

    assert result["errors"] == []
    resolved = result["raw"]["resolved_inputs"]
    assert resolved["reference_spots"] == [300.0, 3_000.0]
    assert resolved["reference_spot_source"] == "contract_fixing"
    assert resolved["reference_fixing_dates"] == [
        "2025-07-18", "2025-07-18",
    ]
    assert result["raw"]["market_data_evidence"]["contract_reference"] == {
        "source": "contract_fixing",
        "reference_spots": [300.0, 3_000.0],
        "reference_fixing_dates": ["2025-07-18", "2025-07-18"],
    }
    assert not any(
        "inception-only fixing assumption" in warning
        for warning in result["warnings"]
    )


def test_service_rejects_partial_contract_reference_grid():
    result = PricingService().price_multi_asset_autocall(
        [
            {"secid": "SBER", "kind": "equity", "weight": 0.5},
            {"secid": "IMOEX", "kind": "index", "weight": 0.5},
        ],
        r=0.10,
        T=1.0,
        reference_spots=[300.0],
        observation_dates=[1.0],
        n_sims=1_000,
        steps=10,
    )
    assert result["value"] is None
    assert any("one contractual fixing" in error for error in result["errors"])


def test_workstation_catalogue_binding_and_generic_pricing_vertical():
    catalogue = build_ws_catalogue()
    product = next(
        item for item in catalogue["products"]
        if item["id"] == "multi_asset_autocall"
    )
    engine = product["engines"][0]
    parameter_keys = {item["key"] for item in engine["params"]}

    assert product["underlying"]["categories"] == [
        "equities", "indices", "bonds"
    ]
    assert engine["id"] == "multi_asset_autocall"
    assert engine["eligibility"]["model_definition_id"] == "correlated_gbm"
    assert engine["eligibility"]["effective_production_allowed"] is True
    assert {
        "basket", "observation_dates", "autocall_aggregation",
        "coupon_aggregation", "protection_aggregation", "n_sims", "steps",
        "seed", "reference_spots", "reference_fixing_dates",
    } <= parameter_keys

    result = price_ws(
        PricingService(),
        None,
        "multi_asset_autocall",
        "multi_asset_autocall",
        {
            "basket": "SBER:0.5:equity, SU26238RMFS4:0.5:bond",
            "r": 0.10,
            "T": 1.0,
            "observation_dates": "0.5,1",
            "n_sims": 1_000,
            "steps": 10,
            "seed": 19,
        },
    )

    assert result["errors"] == []
    assert math.isfinite(result["value"])
    assert result["provenance"]["inputs_hash"]
    assert result["resolved_inputs"]["resolved_snapshot_id"]
    assert result["market_data_evidence"]["resolved_inputs_hash"]
    assert any("market-data fallback" in warning for warning in result["warnings"])
    component_keys = {
        item["key"] for item in result["greeks"] if "." in item["key"]
    }
    assert {
        "delta.SBER", "gamma.SBER", "vega.SBER",
        "delta.SU26238RMFS4", "gamma.SU26238RMFS4",
        "vega.SU26238RMFS4",
    } <= component_keys
    assert {item["key"] for item in result["series"]} == {
        "autocall_cumulative", "pv_distribution"
    }
    measure_labels = {item["key"]: item["label"] for item in result["measures"]}
    assert measure_labels["capital_loss_probability"] == "P(capital loss)"
    assert measure_labels["protection_breach_probability"] == "P(protection breach)"


def test_currency_typed_book_nets_autocall_and_option_pv_but_not_greeks():
    result = price_book_ws(PricingService(), None, [
        {
            "id": "note", "label": "Five-asset note",
            "product": "multi_asset_autocall",
            "engine": "multi_asset_autocall",
            "currency": "RUB", "quantity": 1.0,
            "params": {
                "basket": "SBER:0.5:equity, SU26238RMFS4:0.5:bond",
                "r": 0.10, "T": 1.0, "observation_dates": "0.5,1",
                "n_sims": 1_000, "steps": 10, "seed": 19,
            },
        },
        {
            "id": "hedge", "label": "Option hedge",
            "product": "european_option", "engine": "black_scholes",
            "risk_factor_id": "SBER", "currency": "RUB", "quantity": -1.0,
            "params": {
                "S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05,
                "q": 0.0, "sigma": 0.2, "opt": "call",
            },
        },
    ])

    assert result["success_count"] == 2
    assert result["aggregation"]["status"] == "typed"
    assert result["aggregation"]["basis"] == "currency:RUB|measure:pv"
    assert result["total_value"] == pytest.approx(sum(
        leg["position_value"] for leg in result["legs"]
    ))
    assert result["greeks"] == []
