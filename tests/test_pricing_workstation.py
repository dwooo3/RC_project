"""Gate for the universal pricing workstation: every product x engine must
price cleanly with its default parameters (demo snapshot, flat curves).

MC-heavy engines get their path counts trimmed so the whole matrix runs in
seconds; correctness of the engines themselves is covered by the model tests —
this file guards the catalogue wiring (adapters, param specs, normalization).
"""

from __future__ import annotations

import pytest

from api.pricing_workstation import (
    FLAT_CURVE,
    PRODUCTS,
    build_ws_catalogue,
    find_product,
    ladder_ws,
    normalize_ws_result,
    price_ws,
    scenarios_ws,
)
from services.pricing_service import PricingService


@pytest.fixture(scope="module")
def svc():
    return PricingService(
        allow_analytics_lab=True,
        allow_non_production_models=True,
    )


def _default_params(product, engine) -> dict:
    specs = product.params_for(engine, [], [])
    params = {}
    for spec in specs:
        params[spec.key] = spec.default
    # keep the test matrix fast: shrink MC/lattice workloads
    fast = {"n_sims": 3000, "n_paths": 3000, "n": 2048, "steps": 30,
            "N": 120, "NS": 60, "Nv": 30, "Nt": 40, "N1": 40, "N2": 40,
            "n_z": 100, "n_strikes": 10}
    by_key = {spec.key: spec for spec in specs}
    for key, value in fast.items():
        if key in params:
            spec = by_key[key]
            if spec.minimum is not None:
                value = max(value, spec.minimum)
            if spec.maximum is not None:
                value = min(value, spec.maximum)
            params[key] = int(value) if spec.dtype == "int" else value
    return params


ALL_CASES = [(p.id, e.id) for p in PRODUCTS for e in p.engines]


@pytest.mark.parametrize("product_id,engine_id", ALL_CASES)
def test_every_engine_prices_with_defaults(svc, product_id, engine_id):
    product = find_product(product_id)
    engine = next(e for e in product.engines if e.id == engine_id)
    params = _default_params(product, engine)
    if product.needs_curve:
        params["curve_id"] = FLAT_CURVE      # no live snapshot in tests

    # Custom Product is intentionally builder-only: there is no safe generic
    # default for a version/hash-pinned payout definition and its market-data
    # evidence.  The dedicated Pricing_new integration tests exercise the full
    # nested attachment path; this matrix verifies the fail-closed boundary.
    if product_id == "custom_product":
        with pytest.raises(ValueError, match="attachment_json is required"):
            price_ws(svc, None, product_id, engine_id, params)
        return

    result = price_ws(svc, None, product_id, engine_id, params)

    assert result["errors"] == [], (
        f"{product_id}/{engine_id} errored: {result['errors']}")
    assert result["value"] is not None or result["series"], (
        f"{product_id}/{engine_id} returned neither value nor series")
    if result["value"] is not None:
        assert result["value"] == result["value"], (   # NaN guard
            f"{product_id}/{engine_id} returned NaN")
    assert result["model_id"] == engine.model_id
    assert "engine" not in result["resolved_params"]
    assert "attachment_json" not in result["resolved_params"]


def test_catalogue_serializes():
    cat = build_ws_catalogue(["GCURVE_RUB"], ["RTS_FORTS"])
    assert cat["products"], "empty catalogue"
    ids = [p["id"] for p in cat["products"]]
    assert len(ids) == len(set(ids)), "duplicate product ids"
    for p in cat["products"]:
        assert p["engines"], f"{p['id']} has no engines"
        for e in p["engines"]:
            assert e["params"], f"{p['id']}/{e['id']} has no params"
            keys = [s["key"] for s in e["params"]]
            assert len(keys) == len(set(keys)), (
                f"{p['id']}/{e['id']} duplicate param keys: "
                f"{[k for k in keys if keys.count(k) > 1]}")
            assert e["governance"]["status"], f"{p['id']}/{e['id']} no governance"


def test_qw0_engine_identities_and_merton_cos_are_exposed():
    product = find_product("european_option")
    by_id = {engine.id: engine for engine in product.engines}
    assert by_id["merton_cos"].model_id == "merton_cos"
    assert by_id["heston_adi"].model_id == "heston_adi"

    two_asset = find_product("two_asset_option")
    legacy = next(engine for engine in two_asset.engines if engine.id == "adi")
    assert legacy.model_id == "two_asset_adi"


def test_qw0_analytics_lab_gates_merton_cos_and_heston_adi():
    blocked = PricingService()
    merton = blocked.price_levy_option(
        "merton_cos", 100, 100, 1, 0.05, 0.2)
    heston = blocked.price_heston_adi(
        100, 100, 1, 0.03, 0.0, 0.04, 1.5, 0.04, 0.3, -0.6,
        NS=40, Nv=20, Nt=20)
    assert merton["value"] is None and merton["model_id"] == "merton_cos"
    assert heston["value"] is None and heston["model_id"] == "heston_adi"
    assert all(any("allow_analytics_lab=True" in error for error in result["errors"])
               for result in (merton, heston))


def test_unknown_product_raises(svc):
    with pytest.raises(ValueError):
        price_ws(svc, None, "no_such_product", None, {})


def test_price_path_enforces_parameter_schema(svc):
    product = find_product("european_option")
    params = _default_params(product, product.engines[0])

    with pytest.raises(ValueError, match="SCHEMA_UNKNOWN_FIELD"):
        price_ws(svc, None, "european_option", "black_scholes",
                 {**params, "sigmma": 0.2})
    with pytest.raises(ValueError, match="TERMS_OUT_OF_RANGE"):
        price_ws(svc, None, "european_option", "black_scholes",
                 {**params, "sigma": -0.2})


def test_validator_checks_environment_effective_params():
    from api.pricing_workstation import validate_ws
    from domain.pricing_environment import PricingEnvironment

    env = PricingEnvironment(
        "BAD", "bad defaults", default_params={"sigma": -0.2})
    result = validate_ws(
        "european_option", "black_scholes",
        {"S": 100, "K": 100, "T": 1, "r": 0.05, "q": 0.0, "opt": "call"},
        env=env)
    assert result["valid"] is False
    assert any(issue["param"] == "sigma" and issue["code"] == "TERMS_OUT_OF_RANGE"
               for issue in result["issues"])


def test_ladder_full_revaluation(svc):
    product = find_product("european_option")
    params = _default_params(product, product.engines[0])
    out = ladder_ws(svc, None, "european_option", "black_scholes", params,
                    "S", 70.0, 130.0, steps=7)
    assert len(out["rows"]) == 7
    values = [r["value"] for r in out["rows"]]
    assert all(v is not None for v in values)
    assert values == sorted(values), "call value must rise with spot"
    mid = out["rows"][3]                       # S=100 == base params
    assert abs(mid["pnl"]) < 1e-9


def test_scenarios_full_revaluation(svc):
    product = find_product("european_option")
    params = _default_params(product, product.engines[0])
    out = scenarios_ws(svc, None, "european_option", "black_scholes", params)
    assert len(out["rows"]) >= 10
    by_name = {r["scenario"]: r for r in out["rows"]}
    lehman = next(v for k, v in by_name.items() if "Lehman" in k)
    assert lehman["error"] is None
    assert lehman["pnl"] is not None and lehman["pnl"] < 0, (
        "long ATM call must lose in a -35% spot crash")
    squeeze = next(v for k, v in by_name.items() if "Meme" in k)
    assert squeeze["pnl"] > 0


def test_scenarios_rate_product_uses_curve_shift(svc):
    product = find_product("irs")
    params = _default_params(product, product.engines[0])
    params["curve_id"] = FLAT_CURVE
    out = scenarios_ws(svc, None, "irs", "irs", params)
    hike = next(r for r in out["rows"] if "Rate hike" in r["scenario"])
    assert hike["error"] is None
    assert hike["pnl"] is not None and hike["pnl"] != 0, (
        "IRS must react to a +400bp rate scenario via the curve shift")


def test_scenario_rate_shock_not_double_counted(svc):
    """Flat-curve mode: the rate shock must hit the curve exactly once —
    via the shifted r field, NOT r + shift_bps together (regression)."""
    product = find_product("irs")
    params = _default_params(product, product.engines[0])
    params["curve_id"] = FLAT_CURVE
    out = scenarios_ws(svc, None, "irs", "irs", params)
    hike = next(r for r in out["rows"] if "Rate hike" in r["scenario"])

    manual = dict(params)
    manual["r"] = float(manual["r"]) + 0.040           # the 2022 scenario shock
    expected = price_ws(svc, None, "irs", "irs", manual)["value"]
    assert hike["value"] == pytest.approx(expected, rel=1e-9), (
        "scenario value must equal a single manual r+400bp repricing")


def test_normalizer_extracts_greeks_and_series():
    governed = {
        "value": 5.0, "model_id": "black_scholes", "model_status": "Approximation",
        "calculation_timestamp": "2026-07-15T00:00:00+00:00",
        "raw": {"price": 5.0, "delta": 0.6, "gamma": 0.02,
                "cashflows": [(0.5, 35.0), (1.0, 1035.0)],
                "curve": [{"T": 1.0, "F": 101.0}]},
        "warnings": [], "errors": [], "model_limitations": [],
    }
    out = normalize_ws_result(governed)
    assert out["value"] == 5.0
    assert {g["key"] for g in out["greeks"]} == {"delta", "gamma"}
    assert len(out["series"]) == 2
    assert out["series"][0]["points"][0] == {"x": 0.5, "y": 35.0}
    assert out["provenance"]["valuation_time"] == "2026-07-15T00:00:00+00:00"
