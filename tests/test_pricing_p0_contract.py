"""P0 contracts for exact-run identity and live numerical controls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.pricing_workstation import (
    _american,
    _barrier,
    find_product,
    normalize_ws_result,
    price_ws,
    validate_ws,
)
from services.pricing_service import PricingService


def _defaults(product_id: str, engine_id: str) -> dict:
    product = find_product(product_id)
    engine = next(item for item in product.engines if item.id == engine_id)
    return {spec.key: spec.default for spec in product.params_for(engine, [], [])}


@pytest.fixture
def svc():
    return PricingService(
        allow_analytics_lab=True,
        allow_non_production_models=True,
    )


def test_workstation_hash_is_full_stable_and_matches_audit(svc):
    params = _defaults("asian_option", "asian")
    params["n_sims"] = 1_000

    first = price_ws(svc, None, "asian_option", "asian", params)
    first_hash = first["provenance"]["inputs_hash"]
    assert first_hash == svc.audit.records[-1].inputs_hash

    reordered = {key: params[key] for key in reversed(list(params))}
    again = price_ws(svc, None, "asian_option", "asian", reordered)
    assert again["provenance"]["inputs_hash"] == first_hash

    changed = price_ws(
        svc, None, "asian_option", "asian", {**params, "n_sims": 2_000}
    )
    assert changed["provenance"]["inputs_hash"] != first_hash
    assert changed["provenance"]["inputs_hash"] == svc.audit.records[-1].inputs_hash


def test_workstation_hash_includes_environment_and_snapshot(svc):
    params = _defaults("european_option", "black_scholes")
    env_a = SimpleNamespace(
        env_id="FO", default_params={}, curve_map={}, pricer_overrides={}
    )
    env_b = SimpleNamespace(
        env_id="RISK", default_params={}, curve_map={}, pricer_overrides={}
    )
    base = price_ws(svc, None, "european_option", "black_scholes", params,
                    env=env_a)
    other_env = price_ws(svc, None, "european_option", "black_scholes", params,
                         env=env_b)
    assert base["provenance"]["inputs_hash"] != other_env["provenance"]["inputs_hash"]
    snapshot_a = SimpleNamespace(
        snapshot_id="snap-a", curves={}, vol_surfaces={}, is_demo=False,
        metadata={}, source="test", quality="validated")
    snapshot_b = SimpleNamespace(
        snapshot_id="snap-b", curves={}, vol_surfaces={}, is_demo=False,
        metadata={}, source="test", quality="validated")
    on_a = price_ws(svc, snapshot_a, "european_option", "black_scholes", params,
                    env=env_a)
    on_b = price_ws(svc, snapshot_b, "european_option", "black_scholes", params,
                    env=env_a)
    assert on_a["provenance"]["inputs_hash"] != on_b["provenance"]["inputs_hash"]


def test_nested_engine_context_preserves_exact_request_hash(svc):
    params = _defaults("european_option", "carr_madan")
    env_fo = SimpleNamespace(
        env_id="FO", default_params={}, curve_map={}, pricer_overrides={}
    )
    env_risk = SimpleNamespace(
        env_id="RISK", default_params={}, curve_map={}, pricer_overrides={}
    )
    fo = price_ws(svc, None, "european_option", "carr_madan", params,
                  env=env_fo)
    risk = price_ws(svc, None, "european_option", "carr_madan", params,
                    env=env_risk)

    assert fo["provenance"]["inputs_hash"] != risk["provenance"]["inputs_hash"]
    assert fo["provenance"]["inputs_hash"] == svc.audit.records[-2].inputs_hash
    assert risk["provenance"]["inputs_hash"] == svc.audit.records[-1].inputs_hash


def test_non_scalar_curve_is_audited_even_though_not_bookable(svc):
    params = _defaults("commodity_curve", "schwartz_smith")
    first = price_ws(svc, None, "commodity_curve", "schwartz_smith", params)
    changed = price_ws(
        svc, None, "commodity_curve", "schwartz_smith",
        {**params, "spot": float(params["spot"]) * 1.1},
    )
    assert first["value"] is None and first["series"]
    assert first["provenance"]["calculation_id"].startswith("calc_")
    assert first["provenance"]["inputs_hash"] != changed["provenance"]["inputs_hash"]


def test_omitted_schema_default_has_same_resolved_hash(svc):
    params = _defaults("european_option", "black_scholes")
    explicit = price_ws(svc, None, "european_option", "black_scholes", params)
    omitted = price_ws(
        svc, None, "european_option", "black_scholes",
        {key: value for key, value in params.items() if key != "q"},
    )
    assert omitted["provenance"]["inputs_hash"] == explicit["provenance"]["inputs_hash"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_validation_rejects_non_finite_numeric_terms(bad):
    params = _defaults("european_option", "black_scholes")
    result = validate_ws(
        "european_option", "black_scholes", {**params, "S": bad},
        allow_analytics_lab=True, allow_non_production=True,
    )
    assert result["valid"] is False
    assert any(item["code"] == "TERMS_NON_FINITE" and item["param"] == "S"
               for item in result["issues"])


def test_american_adapter_forwards_each_numerical_schema():
    calls = []

    class Spy:
        def price_american_option(self, *args, **kwargs):
            calls.append(kwargs)
            return {"value": 1.0}

    base = {"S": 100, "K": 100, "T": 1, "r": .05, "sigma": .2,
            "q": 0, "opt": "put"}
    _american(Spy(), {**base, "engine": "pde_cn", "Ns": 123, "Nt": 234}, None)
    _american(Spy(), {**base, "engine": "binomial_crr", "N": 321}, None)
    _american(Spy(), {**base, "engine": "mc_lsm", "n_sims": 4321,
                      "steps": 37, "seed": 9}, None)

    assert calls[0]["ns"] == 123 and calls[0]["nt"] == 234
    assert calls[1]["N"] == 321
    assert calls[2]["n_sims"] == 4321
    assert calls[2]["steps"] == 37 and calls[2]["seed"] == 9


def test_barrier_pde_forwards_rebate():
    captured = {}

    class Spy:
        def price_barrier_option_pde(self, *args, **kwargs):
            captured.update(kwargs)
            return {"value": 1.0}

    _barrier(Spy(), {
        "engine": "pde_cn", "S": 100, "K": 100, "H": 90, "T": 1,
        "r": .05, "sigma": .2, "q": 0, "opt": "call",
        "barrier_type": "down-out", "rebate": 7.5, "Ns": 100, "Nt": 120,
    }, None)
    assert captured["rebate"] == 7.5


def test_normalizer_separates_numerical_error_from_advanced_greeks():
    result = normalize_ws_result({
        "value": 1.0,
        "model_id": "black_scholes",
        "model_status": "Validated",
        "raw": {"stderr": 0.01, "delta_spot": 0.55, "speed": -0.002},
        "warnings": [], "errors": [], "model_limitations": [],
    })
    assert {item["key"] for item in result["greeks"]} == {"delta_spot", "speed"}
    assert {item["key"] for item in result["measures"]} == {"stderr"}
