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
    normalize_ws_result,
    price_ws,
)
from services.pricing_service import PricingService


@pytest.fixture(scope="module")
def svc():
    return PricingService(allow_analytics_lab=True)


def _default_params(product, engine) -> dict:
    params = {}
    for spec in product.params_for(engine, [], []):
        params[spec.key] = spec.default
    # keep the test matrix fast: shrink MC/lattice workloads
    fast = {"n_sims": 3000, "n_paths": 3000, "n": 2048, "steps": 30,
            "N": 120, "NS": 60, "Nv": 30, "Nt": 40, "N1": 40, "N2": 40,
            "n_z": 100, "n_strikes": 10}
    for key, val in fast.items():
        if key in params:
            params[key] = val
    return params


ALL_CASES = [(p.id, e.id) for p in PRODUCTS for e in p.engines]


@pytest.mark.parametrize("product_id,engine_id", ALL_CASES)
def test_every_engine_prices_with_defaults(svc, product_id, engine_id):
    product = find_product(product_id)
    engine = next(e for e in product.engines if e.id == engine_id)
    params = _default_params(product, engine)
    params["curve_id"] = FLAT_CURVE          # no live snapshot in tests

    result = price_ws(svc, None, product_id, engine_id, params)

    assert result["errors"] == [], (
        f"{product_id}/{engine_id} errored: {result['errors']}")
    assert result["value"] is not None or result["series"], (
        f"{product_id}/{engine_id} returned neither value nor series")
    if result["value"] is not None:
        assert result["value"] == result["value"], (   # NaN guard
            f"{product_id}/{engine_id} returned NaN")


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


def test_unknown_product_raises(svc):
    with pytest.raises(ValueError):
        price_ws(svc, None, "no_such_product", None, {})


def test_normalizer_extracts_greeks_and_series():
    governed = {
        "value": 5.0, "model_id": "black_scholes", "model_status": "Approximation",
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
