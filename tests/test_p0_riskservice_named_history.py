"""MR-4B: RiskService routes exact named histories into every scenario."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from services.risk_service import RiskService


class _RecordingPortfolio:
    def __init__(self, positions):
        self.positions = positions
        self.calls: list[dict] = []

    def full_reprice_pnl(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "pnl": kwargs.get("dS", 0.0),
            "errors": [],
            "valid": True,
        }


def _position(position_id: str = "dual-risk", **params):
    return SimpleNamespace(id=position_id, params=params)


@pytest.mark.parametrize(
    ("position", "curve_histories", "surface_histories", "message"),
    [
        (
            _position(curve_id="DISC", proj_curve_id="PROJ"),
            {"DISC": {1.0: np.zeros(30)}},
            None,
            "named curve histories are required: PROJ",
        ),
        (
            _position(vol_surface_id="SBER_FORTS"),
            None,
            {},
            "named surface histories are required for positions: dual-risk",
        ),
    ],
)
def test_named_dependencies_fail_closed_without_their_exact_history(
        position, curve_histories, surface_histories, message):
    portfolio = _RecordingPortfolio([position])
    generic = np.zeros(30)

    result = RiskService().full_reprice_var(
        portfolio,
        generic,
        generic,
        vol_changes=generic,
        curve_changes_by_id=curve_histories,
        surface_changes_by_position=surface_histories,
    )

    assert result["value"] is None
    assert result["raw"] is None
    assert message in "; ".join(result["errors"])
    assert portfolio.calls == []


def test_exact_curve_and_surface_maps_are_delivered_per_scenario():
    portfolio = _RecordingPortfolio([
        _position(
            curve_id="DISC",
            proj_curve_id="PROJ",
            vol_surface_id="SBER_FORTS",
        ),
    ])
    n = 30
    equity = np.linspace(-0.03, 0.03, n)
    generic_rate = np.full(n, 0.77)
    generic_vol = np.full(n, 0.66)
    discount_1y = np.linspace(0.001, 0.003, n)
    discount_5y = np.linspace(0.004, 0.006, n)
    projection_1y = np.linspace(-0.002, -0.004, n)
    surface = np.linspace(0.01, 0.02, n)

    result = RiskService().full_reprice_var(
        portfolio,
        equity,
        generic_rate,
        vol_changes=generic_vol,
        curve_changes_by_id={
            "DISC": {1.0: discount_1y, 5.0: discount_5y},
            "PROJ": {1.0: projection_1y},
        },
        surface_changes_by_position={"dual-risk": surface},
    )

    assert result["errors"] == []
    assert len(portfolio.calls) == n
    for index, call in enumerate(portfolio.calls):
        assert call["dr"] == pytest.approx(0.77)
        assert call["dvol"] == pytest.approx(0.66)
        assert call["dr_curves"] == {
            "DISC": [
                (1.0, pytest.approx(discount_1y[index])),
                (5.0, pytest.approx(discount_5y[index])),
            ],
            "PROJ": [(1.0, pytest.approx(projection_1y[index]))],
        }
        assert call["dvol_by_position"] == {
            "dual-risk": pytest.approx(surface[index]),
        }


@pytest.mark.parametrize("short_dependency", ["curve", "surface"])
def test_named_history_must_cover_the_complete_joint_window(short_dependency):
    portfolio = _RecordingPortfolio([
        _position(curve_id="DISC", vol_surface_id="SBER_FORTS"),
    ])
    generic = np.zeros(30)
    curve = np.zeros(29 if short_dependency == "curve" else 30)
    surface = np.zeros(29 if short_dependency == "surface" else 30)

    result = RiskService().full_reprice_var(
        portfolio,
        generic,
        generic,
        vol_changes=generic,
        curve_changes_by_id={"DISC": {5.0: curve}},
        surface_changes_by_position={"dual-risk": surface},
    )

    assert result["value"] is None
    assert result["raw"] is None
    assert "incomplete" in "; ".join(result["errors"])
    assert portfolio.calls == []


@pytest.mark.parametrize(
    ("equity", "rates", "volatility", "fx", "message"),
    [
        (np.zeros(31), np.zeros(30), np.zeros(32), np.zeros(33),
         "exactly equal lengths"),
        (np.zeros((30, 1)), np.zeros(30), np.zeros(30), np.zeros(30),
         "one-dimensional"),
        (np.r_[np.zeros(29), np.nan], np.zeros(30), np.zeros(30), np.zeros(30),
         "non-finite"),
    ],
)
def test_joint_factor_histories_require_exact_finite_one_dimensional_alignment(
        equity, rates, volatility, fx, message):
    portfolio = _RecordingPortfolio([])

    result = RiskService().full_reprice_var(
        portfolio, equity, rates, volatility, fx)

    assert result["value"] is None
    assert message in "; ".join(result["errors"])
    assert portfolio.calls == []


def test_scalar_or_non_mapping_history_inputs_fail_as_structured_risk_error():
    portfolio = _RecordingPortfolio([])

    scalar = RiskService().full_reprice_var(
        portfolio, 0.01, np.zeros(30), np.zeros(30), np.zeros(30))
    bad_named_map = RiskService().full_reprice_var(
        portfolio, np.zeros(30), np.zeros(30), np.zeros(30), np.zeros(30),
        curve_changes_by_id=[("DISC", {1.0: np.zeros(30)})],
    )

    assert scalar["value"] is None
    assert "one-dimensional" in "; ".join(scalar["errors"])
    assert bad_named_map["value"] is None
    assert "must be a mapping" in "; ".join(bad_named_map["errors"])
    assert portfolio.calls == []


@pytest.mark.parametrize(
    ("curve_values", "surface_values", "message"),
    [
        (np.zeros(31), np.zeros(30), "expected exactly 30 scenarios"),
        (np.zeros((30, 1)), np.zeros(30), "one-dimensional"),
        (np.zeros(30), np.r_[np.zeros(29), np.inf], "non-finite"),
    ],
)
def test_named_histories_require_exact_finite_one_dimensional_alignment(
        curve_values, surface_values, message):
    portfolio = _RecordingPortfolio([
        _position(curve_id="DISC", vol_surface_id="SBER_FORTS"),
    ])
    generic = np.zeros(30)

    result = RiskService().full_reprice_var(
        portfolio,
        generic,
        generic,
        vol_changes=generic,
        curve_changes_by_id={"DISC": {5.0: curve_values}},
        surface_changes_by_position={"dual-risk": surface_values},
    )

    assert result["value"] is None
    assert message in "; ".join(result["errors"])
    assert portfolio.calls == []
