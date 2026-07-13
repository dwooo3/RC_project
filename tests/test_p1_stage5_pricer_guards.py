"""PR-1 regressions for the Stage-5 approximation pricers."""

import math

import pytest

from instruments.credit import cds_index_option
from instruments.equity_linear import equity_swap


def test_equity_swap_delta_matches_spot_independent_npv():
    base = equity_swap(
        100.0, 1_000_000.0, 5.0, 0.12, 0.03, spread=0.005, freq=4)
    bumped = equity_swap(
        110.0, 1_000_000.0, 5.0, 0.12, 0.03, spread=0.005, freq=4)

    assert bumped["npv"] == pytest.approx(base["npv"])
    assert base["delta"] == 0.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"strike_spread": 0.0},
        {"current_spread": 0.0},
        {"sigma": 0.0},
        {"T_opt": 0.0},
        {"T_index": 0.5},
        {"freq": 0},
        {"recovery": 1.0},
        {"option": "invalid"},
        {"current_spread": math.nan},
        {"sigma": math.inf},
    ],
)
def test_cds_index_option_rejects_invalid_black_inputs(overrides):
    inputs = {
        "notional": 10_000_000.0,
        "strike_spread": 0.011,
        "current_spread": 0.011,
        "sigma": 0.5,
        "T_opt": 0.5,
        "T_index": 5.0,
        "freq": 4,
        "r": 0.08,
        "recovery": 0.4,
        "option": "payer",
    }
    inputs.update(overrides)

    with pytest.raises(ValueError):
        cds_index_option(**inputs)


def test_cds_index_option_valid_case_is_finite():
    result = cds_index_option(
        10_000_000.0, 0.011, 0.011, 0.5, 0.5, 5.0, 4, 0.08)

    assert result["price"] > 0
