"""Multi-instrument pricing-book and Greek-profile API contract."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from api.pricing_workstation import ladder_ws, price_book_ws, price_ws
from services.pricing_service import PricingService


BS_PARAMS = {
    "S": 100.0,
    "K": 100.0,
    "T": 1.0,
    "r": 0.05,
    "q": 0.0,
    "sigma": 0.2,
    "opt": "call",
}


@pytest.fixture(scope="module")
def svc():
    return PricingService(
        allow_analytics_lab=True,
        allow_non_production_models=True,
    )


def _leg(leg_id: str, *, strike: float = 100.0,
         quantity: float = 1.0) -> dict:
    return {
        "id": leg_id,
        "label": f"Call {strike:g}",
        "product": "european_option",
        "engine": "black_scholes",
        "params": {**BS_PARAMS, "K": strike},
        "quantity": quantity,
    }


def _greeks_by_key(items: list[dict]) -> dict[str, float]:
    return {item["key"]: item["value"] for item in items}


def test_two_european_calls_aggregate_value_and_greeks(svc):
    legs = [_leg("atm", quantity=2.0),
            _leg("otm", strike=110.0, quantity=3.0)]
    result = price_book_ws(svc, None, legs)

    atm = price_ws(svc, None, "european_option", "black_scholes",
                   dict(BS_PARAMS))
    otm = price_ws(svc, None, "european_option", "black_scholes",
                   {**BS_PARAMS, "K": 110.0})
    assert result["count"] == result["success_count"] == 2
    assert result["aggregation"]["status"] == "provisional"
    assert result["aggregation"]["compatible"] is True
    assert result["aggregation"]["greeks_compatible"] is True
    assert result["errors"] == []
    assert [leg["id"] for leg in result["legs"]] == ["atm", "otm"]
    assert result["total_value"] == pytest.approx(
        2.0 * atm["value"] + 3.0 * otm["value"])

    expected_delta = (
        2.0 * _greeks_by_key(atm["greeks"])["delta"]
        + 3.0 * _greeks_by_key(otm["greeks"])["delta"]
    )
    assert _greeks_by_key(result["greeks"])["delta"] == pytest.approx(
        expected_delta)
    assert result["legs"][0]["position_value"] == pytest.approx(
        2.0 * atm["value"])
    assert _greeks_by_key(result["legs"][0]["greeks"])["delta"] == \
        pytest.approx(2.0 * _greeks_by_key(atm["greeks"])["delta"])
    assert result["legs"][0]["result"]["product"] == "european_option"


def test_long_short_positions_net_with_signed_quantity(svc):
    result = price_book_ws(
        svc, None,
        [_leg("long", quantity=3.0), _leg("short", quantity=-2.0)],
    )
    unit = price_ws(svc, None, "european_option", "black_scholes",
                    dict(BS_PARAMS))
    unit_greeks = _greeks_by_key(unit["greeks"])

    assert result["success_count"] == 2
    assert result["total_value"] == pytest.approx(unit["value"])
    assert result["legs"][1]["quantity"] == -2.0
    assert result["legs"][1]["position_value"] == pytest.approx(
        -2.0 * unit["value"])
    for key, value in _greeks_by_key(result["greeks"]).items():
        assert value == pytest.approx(unit_greeks[key])


def test_bad_leg_isolated_and_successful_leg_still_contributes(svc):
    result = price_book_ws(
        svc, None,
        [_leg("good"), {
            **_leg("bad"),
            "engine": "engine-that-does-not-exist",
        }],
    )

    assert result["count"] == 2
    assert result["success_count"] == 1
    assert result["legs"][0]["error"] is None
    assert result["legs"][0]["result"] is not None
    assert result["legs"][1]["result"] is None
    assert "unknown engine" in result["legs"][1]["error"]
    assert result["errors"] == [
        f"bad: {result['legs'][1]['error']}",
    ]
    assert result["total_value"] == pytest.approx(
        result["legs"][0]["position_value"])


def test_mixed_product_headlines_are_not_silently_aggregated(svc):
    mixed = price_book_ws(svc, None, [
        _leg("option"),
        {
            "id": "forward",
            "label": "Equity forward",
            "product": "equity_forward",
            "engine": "equity_forward",
            "quantity": 1.0,
            "params": {
                "S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05,
                "q": 0.0, "notional": 1.0, "position": "long",
            },
        },
    ])

    assert mixed["success_count"] == 2
    assert all(leg["position_value"] is not None for leg in mixed["legs"])
    assert mixed["aggregation"]["status"] == "blocked"
    assert mixed["aggregation"]["compatible"] is False
    assert mixed["total_value"] is None
    assert mixed["greeks"] == []


def test_explicit_same_currency_monetary_products_net_pv_only(svc):
    option = {**_leg("option"), "currency": "RUB"}
    forward = {
        "id": "forward",
        "label": "Equity forward",
        "product": "equity_forward",
        "engine": "equity_forward",
        "currency": "RUB",
        "quantity": 1.0,
        "params": {
            "S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05,
            "q": 0.0, "notional": 1.0, "position": "long",
        },
    }

    result = price_book_ws(svc, None, [option, forward])

    assert result["success_count"] == 2
    assert result["aggregation"]["status"] == "typed"
    assert result["aggregation"]["compatible"] is True
    assert result["aggregation"]["greeks_compatible"] is False
    assert result["aggregation"]["basis"] == "currency:RUB|measure:pv"
    assert result["total_value"] == pytest.approx(sum(
        leg["position_value"] for leg in result["legs"]
    ))
    assert result["greeks"] == []
    assert {leg["currency"] for leg in result["legs"]} == {"RUB"}


def test_different_underlyings_do_not_silently_net_greeks(svc):
    sber = {**_leg("sber"), "risk_factor_id": "SBER"}
    gazp = {**_leg("gazp", strike=110.0), "risk_factor_id": "GAZP"}
    result = price_book_ws(svc, None, [sber, gazp])

    assert result["success_count"] == 2
    assert result["aggregation"]["compatible"] is True
    assert result["aggregation"]["greeks_compatible"] is False
    assert result["total_value"] is not None
    assert result["greeks"] == []
    assert all(leg["greeks"] for leg in result["legs"])


def test_book_bounds_and_quantity_validation_are_fail_closed(svc):
    with pytest.raises(ValueError, match="at most 100"):
        price_book_ws(svc, None, [_leg(str(i)) for i in range(101)])

    partial = price_book_ws(
        svc, None,
        [_leg("good"), _leg("nan", quantity=math.nan)],
    )
    assert partial["success_count"] == 1
    assert partial["legs"][1]["error"] == "quantity must be finite"

    overflow = price_book_ws(svc, None, [_leg("huge", quantity=1e308)])
    assert overflow["success_count"] == 0
    assert overflow["total_value"] is None
    assert overflow["greeks"] == []
    assert "not finite" in overflow["legs"][0]["error"]

    from api.server import WsBookLegRequest, WsBookPriceRequest

    # The HTTP schema rejects non-finite JSON quantities and oversized books
    # before a request can enter the pricing runtime.
    with pytest.raises(ValidationError):
        WsBookLegRequest(**_leg("nan", quantity=math.nan))
    with pytest.raises(ValidationError):
        WsBookLegRequest(**{
            **_leg("nan-param"),
            "params": {**BS_PARAMS, "sigma": math.nan},
        })
    valid = WsBookLegRequest(**_leg("short", quantity=-2.0))
    assert valid.quantity == -2.0
    with pytest.raises(ValidationError):
        WsBookPriceRequest(legs=[valid] * 101)


def test_book_has_exact_top_level_audit_hash_and_unique_leg_ids(svc):
    before = len(svc.audit.records)
    base = price_book_ws(svc, None, [_leg("atm", quantity=2.0),
                                     _leg("otm", strike=110.0)])
    reordered_params = {key: BS_PARAMS[key] for key in reversed(BS_PARAMS)}
    equivalent = price_book_ws(svc, None, [
        {**_leg("atm", quantity=2.0), "params": reordered_params},
        _leg("otm", strike=110.0),
    ])
    changed_quantity = price_book_ws(
        svc, None, [_leg("atm", quantity=3.0),
                    _leg("otm", strike=110.0)])
    changed_order = price_book_ws(
        svc, None, [_leg("otm", strike=110.0),
                    _leg("atm", quantity=2.0)])

    assert base["calculation_id"].startswith("calc_")
    assert base["calculation_timestamp"]
    assert len(base["inputs_hash"]) == len(base["context_hash"]) == 64
    assert base["inputs_hash"] == equivalent["inputs_hash"]
    assert base["inputs_hash"] != changed_quantity["inputs_hash"]
    assert base["inputs_hash"] != changed_order["inputs_hash"]
    book_records = [record for record in svc.audit.records[before:]
                    if record.calculation_type == "pricing_book"]
    assert len(book_records) == 4
    assert book_records[0].inputs_hash == base["inputs_hash"]

    with pytest.raises(ValueError, match="leg ids must be unique: duplicate"):
        price_book_ws(svc, None, [_leg("duplicate"), _leg("duplicate")])


def test_failed_non_scalar_leg_params_still_change_book_hash(svc):
    def curve_leg(spot):
        return {
            "id": "curve", "label": "Commodity curve",
            "product": "commodity_curve", "engine": "schwartz_smith",
            "quantity": 1.0,
            "params": {
                "spot": spot, "tenors": "0.25,0.5,1", "r": 0.05,
                "kappa": 1.0, "rho": 0.3,
                "sigma_s": 0.3, "sigma_y": 0.2, "mu_y": 0.0,
                "y0": 0.0,
            },
        }

    first = price_book_ws(svc, None, [curve_leg(100.0)])
    changed = price_book_ws(svc, None, [curve_leg(200.0)])
    assert first["success_count"] == changed["success_count"] == 0
    assert first["inputs_hash"] != changed["inputs_hash"]


def test_server_book_route_resolves_one_runtime(monkeypatch, svc):
    from api import server

    calls = []

    def runtime(env_id):
        calls.append(env_id)
        return None, None, svc, [], []

    monkeypatch.setattr(server, "_workstation_runtime", runtime)
    request = server.WsBookPriceRequest(
        env_id=None,
        legs=[server.WsBookLegRequest(**_leg("one")),
              server.WsBookLegRequest(**_leg("two", strike=110.0))],
    )
    result = server.ws_book_price(request)

    assert calls == [None]
    assert result["count"] == result["success_count"] == 2
    assert result["environment"] is None


def test_ladder_rows_expose_numeric_greek_profiles(svc):
    result = ladder_ws(
        svc, None, "european_option", "black_scholes", dict(BS_PARAMS),
        "S", 80.0, 120.0, steps=5,
    )

    assert len(result["rows"]) == 5
    for row in result["rows"]:
        assert {"delta", "gamma", "vega"} <= set(row["greeks"])
        assert all(math.isfinite(value) for value in row["greeks"].values())
    deltas = [row["greeks"]["delta"] for row in result["rows"]]
    assert deltas == sorted(deltas)
