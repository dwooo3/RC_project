"""Acceptance §27.3 / §26: «every declared effective parameter has influence».

Curated matrix of numerical knobs whose change MUST move the value. The
full-catalogue scan (2026-07-16) found the wiring bugs fixed here
(european/barrier pde_cn Ns/Nt, convertible N — plus earlier lattice N and
MC params); engines whose params legitimately do not move the price at the
tested point (COS grids past machine convergence, g2pp n_sims under the
analytic method, homogeneous-pool n_names) are documented in the
implementation report, not asserted here.
"""

from __future__ import annotations

import pytest

from api.pricing_workstation import FLAT_CURVE, find_product, price_ws
from services.pricing_service import PricingService

BS = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "q": 0.0,
      "sigma": 0.2, "opt": "call"}


@pytest.fixture(scope="module")
def svc():
    return PricingService(allow_analytics_lab=True,
                          allow_non_production_models=True)


def _price(svc, product, engine, params):
    result = price_ws(svc, None, product, engine, params)
    assert not result.get("errors"), result.get("errors")
    return result["value"]


CASES = [
    # product, engine, extra params, knob, low, high
    ("european_option", "binomial_crr", BS, "N", 50, 2000),
    ("european_option", "binomial_lr", BS, "N", 51, 501),
    ("european_option", "trinomial", BS, "N", 40, 400),
    ("european_option", "pde_cn", BS, "Ns", 60, 400),
    ("european_option", "pde_cn", BS, "Nt", 60, 400),
    ("european_option", "mc_gbm", BS, "n_sims", 2000, 8000),
    ("european_option", "mc_gbm", BS, "seed", 1, 2),
    ("barrier_option",
     {"S": 100.0, "K": 100.0, "H": 90.0, "T": 1.0, "r": 0.05,
      "sigma": 0.2, "q": 0.0, "opt": "call", "barrier_type": "down-out",
      "rebate": 0.0},
     None, "Ns", 60, 400),
    ("convertible",
     {"S": 100.0, "sigma": 0.3, "q": 0.0, "face": 1000.0, "coupon": 0.05,
      "freq": 2, "T": 5.0, "conv_ratio": 10.0, "credit_spread": 0.02,
      "curve_id": FLAT_CURVE, "r": 0.1},
     None, "N", 60, 800),
]


def _normalize(case):
    if case[2] is None:
        product, params, _, knob, lo, hi = case
        engine = None
    else:
        product, engine, params, knob, lo, hi = case
    return product, engine, dict(params), knob, lo, hi


@pytest.mark.parametrize("case", CASES,
                         ids=[f"{c[0]}:{c[3] if c[2] is None else c[3]}"
                              for c in CASES])
def test_numerical_knob_moves_the_value(svc, case):
    product, engine, params, knob, lo, hi = _normalize(case)
    if engine is None:
        engine_obj = find_product(product).engines
        engine = next((e.id for e in engine_obj if e.id == "pde_cn"),
                      engine_obj[0].id)
        if product == "convertible":
            engine = "convertible_bond"
    low = _price(svc, product, engine, {**params, knob: lo})
    high = _price(svc, product, engine, {**params, knob: hi})
    assert low != high, (
        f"{product}/{engine}: '{knob}' не влияет на цену "
        f"({lo}→{hi} дали {low} == {high}) — параметр мёртв")
