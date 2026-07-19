"""Historical factor routing for canonical Custom Product positions."""

from types import SimpleNamespace

import pytest

from api import marketrisk


def _book(*positions):
    return SimpleNamespace(positions=list(positions))


def _custom(position_id: str, secids: list[str], kinds: list[str]):
    return SimpleNamespace(
        id=position_id,
        instrument="custom_product",
        params={
            "component_secids": secids,
            "component_kinds": kinds,
        },
    )


def test_custom_product_routes_all_spots_but_only_equity_index_vol_factors():
    portfolio = _book(_custom(
        "custom-1",
        ["SBER", "SU26238RMFS4", "CNYRUBF", "GOLD"],
        ["equity", "bond", "future", "commodity"],
    ))

    assert marketrisk._book_secids(portfolio) == [
        "CNYRUBF", "GOLD", "SBER", "SU26238RMFS4",
    ]
    assert marketrisk._book_vol_names(portfolio) == ["SBER"]
    assert marketrisk._book_component_kinds(portfolio) == {
        "CNYRUBF": "future",
        "GOLD": "commodity",
        "SBER": "equity",
        "SU26238RMFS4": "bond",
    }


def test_custom_product_factor_kinds_fail_closed_on_unsupported_or_conflict():
    with pytest.raises(ValueError, match="unsupported component kinds"):
        marketrisk._book_component_kinds(_book(
            _custom("bad", ["UNKNOWN"], ["crypto"]),
        ))

    with pytest.raises(ValueError, match="conflicting kinds"):
        marketrisk._book_component_kinds(_book(
            _custom("first", ["SBER"], ["equity"]),
            _custom("second", ["SBER"], ["commodity"]),
        ))
