"""MR-4: Market Risk consumers must never publish partial reprice metrics."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from api import marketrisk
from domain.portfolio import Position
from services.portfolio_service import PortfolioService
from services.risk_service import RiskService


def _shifts(n: int = 1) -> dict:
    zeros = np.zeros(n)
    return {
        "dates": [f"2026-07-{i + 1:02d}" for i in range(n)],
        "eq": zeros.copy(),
        "dr": zeros.copy(),
        "dvol": zeros.copy(),
        "fx": zeros.copy(),
        "dr_tenors": {5.0: zeros.copy()},
        "eq_names": {},
        "vol_names": {},
        "fx_pairs": {},
        "factors": ["synthetic"],
        "factor_warnings": [],
    }


class _ResultPortfolio:
    positions = []

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def full_reprice_pnl(self, **_kwargs):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class _NonFiniteGreekPricing:
    """Returns a finite price but an invalid Greek payload."""

    audit = None

    @staticmethod
    def price_vanilla_option(*_args, **_kwargs):
        return {
            "value": 10.0,
            "errors": [],
            "warnings": [],
            "raw": {
                "delta": np.nan, "gamma": 0.01, "vega": 2.0,
                "theta": -0.1, "rho": 0.5,
            },
            "model_id": "bad-greeks",
            "model_status": "test",
            "market_data_snapshot_id": "test",
        }


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        ({"pnl": 123.0, "errors": ["bad position"]}, "bad position"),
        ({"pnl": 123.0, "errors": [], "valid": False}, "marked invalid"),
        ({"pnl": np.nan, "errors": []}, "non-finite"),
        ({"pnl": 1.0, "base_value": np.inf, "errors": []}, "base value"),
        ({}, "empty or invalid"),
        (RuntimeError("engine exploded"), "engine exploded"),
    ],
)
def test_historical_reprice_rejects_partial_invalid_and_empty_results(
        result, reason):
    portfolio = _ResultPortfolio(result)

    with pytest.raises(ValueError) as exc_info:
        marketrisk._reprice_series(portfolio, _shifts())

    message = str(exc_info.value)
    assert "historical full reprice scenario 0" in message
    assert "2026-07-01" in message
    assert reason in message


def test_successful_hyppl_keeps_compatible_empty_error_list():
    portfolio = _ResultPortfolio({
        "pnl": 7.5, "base_value": 100.0, "shocked_value": 107.5,
        "errors": [], "valid": True,
    })

    result = marketrisk._hyppl_from_scenarios(portfolio, _shifts(2))

    assert result["pnl"].tolist() == pytest.approx([7.5, 7.5])
    assert result["reprice_errors"] == []


def test_custom_hyppl_enforces_and_reports_paired_crn_profile():
    class CustomPortfolio:
        positions = [SimpleNamespace(instrument="custom_product")]

        def __init__(self):
            self.calls = 0

        def full_reprice_pnl(self, **kwargs):
            self.calls += 1
            assert kwargs["custom_repricing_profile"] == "custom_hist_crn_v1"
            return {
                "pnl": float(self.calls),
                "base_value": 100.0,
                "shocked_value": 100.0 + self.calls,
                "errors": [],
                "valid": True,
                "warnings": ["profile warning"],
                "custom_repricing_profile": "custom_hist_crn_v1",
                "base_value_source": (
                    "custom_profile_computed" if self.calls == 1
                    else "custom_profile_cache"
                ),
            }

    result = marketrisk._hyppl_from_scenarios(
        CustomPortfolio(), _shifts(2),
        custom_repricing_profile="custom_hist_crn_v1",
    )

    assert result["pnl"].tolist() == pytest.approx([1.0, 2.0])
    assert result["reprice_errors"] == []
    assert result["reprice_warnings"] == ["profile warning"]
    assert len(result["scenario_matrix_hash"]) == 64
    changed = _shifts(2)
    changed["eq"][1] = 0.01
    assert marketrisk._scenario_matrix_hash(changed) != result[
        "scenario_matrix_hash"]
    evidence = result["repricing_evidence"]
    assert evidence["profile"] == "custom_hist_crn_v1"
    assert evidence["inner_paths"] == 1_000
    assert evidence["common_random_numbers"] is True
    assert evidence["paired_profile_base"] is True
    assert evidence["base_value_sources"] == [
        "custom_profile_cache", "custom_profile_computed",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        {"custom_repricing_profile": None},
        {"base_value_source": "scenario_reprice"},
    ],
)
def test_custom_hyppl_rejects_missing_profile_or_paired_base_evidence(mutation):
    class BrokenCustomPortfolio:
        positions = [SimpleNamespace(instrument="custom_product")]

        @staticmethod
        def full_reprice_pnl(**_kwargs):
            result = {
                "pnl": 1.0,
                "base_value": 100.0,
                "shocked_value": 101.0,
                "errors": [],
                "valid": True,
                "custom_repricing_profile": "custom_hist_crn_v1",
                "base_value_source": "custom_profile_computed",
            }
            result.update(mutation)
            return result

    with pytest.raises(ValueError, match="profile evidence|paired base"):
        marketrisk._reprice_series(
            BrokenCustomPortfolio(), _shifts(),
            custom_repricing_profile="custom_hist_crn_v1",
        )


def test_failed_hyppl_is_not_cached(monkeypatch):
    shifts = _shifts()
    portfolio = _ResultPortfolio({"pnl": 999.0, "errors": ["broken leg"]})
    ctx = SimpleNamespace(
        portfolio=portfolio,
        snapshot=SimpleNamespace(snapshot_id="strict-snapshot"),
    )
    monkeypatch.setattr(marketrisk, "factor_shifts", lambda *args, **kwargs: shifts)
    marketrisk.invalidate_cache()

    with pytest.raises(ValueError, match="broken leg"):
        marketrisk.hyppl(ctx, window=60)

    assert marketrisk._CACHE == {}


def test_overview_rejects_legacy_partial_hyppl_before_metrics(monkeypatch):
    monkeypatch.setattr(marketrisk, "hyppl", lambda *args, **kwargs: {
        "dates": ["2026-07-01"],
        "pnl": np.array([1_000_000.0]),
        "reprice_errors": ["position P7 failed"],
        "horizon_method": "none",
        "factors": ["synthetic"],
    })

    with pytest.raises(ValueError, match="position P7 failed"):
        marketrisk.overview(SimpleNamespace())


@pytest.mark.parametrize("pnl", [np.array([]), np.array([0.0, np.nan])])
def test_backtest_rejects_empty_or_nonfinite_hyppl(monkeypatch, pnl):
    monkeypatch.setattr(marketrisk, "hyppl", lambda *args, **kwargs: {
        "dates": [f"d{i}" for i in range(len(pnl))],
        "pnl": pnl,
        "reprice_errors": [],
    })

    with pytest.raises(ValueError, match="HypPL"):
        marketrisk.backtest(SimpleNamespace())


def _matrix_shifts(n: int = 64) -> dict:
    rng = np.random.default_rng(20260713)
    return {
        "dates": [f"d{i}" for i in range(n)],
        "eq": rng.normal(0.0, 0.01, n),
        "dr": rng.normal(0.0, 0.001, n),
        "dvol": rng.normal(0.0, 0.002, n),
        "fx": rng.normal(0.0, 0.01, n),
        "dr_tenors": {
            tenor: rng.normal(0.0, 0.001, n)
            for tenor in marketrisk._KBD_TENORS
        },
        "eq_names": {},
        "vol_names": {},
        "fx_pairs": {},
        "factors": ["synthetic"],
        "factor_warnings": [],
    }


def test_matrix_mc_rejects_partial_reprice_before_var(monkeypatch):
    portfolio = _ResultPortfolio({
        "pnl": 1_000_000.0, "errors": ["basket pricer failed"],
    })
    monkeypatch.setattr(
        marketrisk, "factor_shifts", lambda *args, **kwargs: _matrix_shifts())

    with pytest.raises(ValueError) as exc_info:
        marketrisk.mc_var_matrix(
            SimpleNamespace(portfolio=portfolio), n_sims=2, seed=7)

    message = str(exc_info.value)
    assert "Matrix-MC full reprice simulation 0" in message
    assert "basket pricer failed" in message
    assert portfolio.calls == 1


def test_pnl_explain_rejects_partial_reprice_with_date_context(monkeypatch):
    portfolio = _ResultPortfolio({"pnl": 42.0, "errors": ["bad option"]})
    monkeypatch.setattr(
        marketrisk, "factor_shifts", lambda *args, **kwargs: _shifts())

    with pytest.raises(ValueError) as exc_info:
        marketrisk.pnl_explain(SimpleNamespace(portfolio=portfolio))

    message = str(exc_info.value)
    assert "P&L Explain full reprice scenario 0" in message
    assert "2026-07-01" in message
    assert "bad option" in message


def test_portfolio_explain_pnl_rejects_valuation_error():
    service = PortfolioService()
    service.add(Position(
        id="broken-position", instrument="not_a_product",
        description="unsupported", quantity=1.0, params={},
    ))

    with pytest.raises(ValueError) as exc_info:
        service.explain_pnl(dS_relative=0.01)

    message = str(exc_info.value)
    assert "broken-position" in message
    assert "unsupported portfolio instrument" in message


def test_portfolio_explain_pnl_rejects_nonfinite_greek():
    service = PortfolioService(pricing=_NonFiniteGreekPricing())
    service.add(Position(
        id="bad-greek", instrument="option", description="bad Greek",
        quantity=1.0,
        params={
            "S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05,
            "sigma": 0.20, "q": 0.0, "opt": "call",
        },
    ))

    with pytest.raises(ValueError) as exc_info:
        service.explain_pnl(dS_relative=0.01)

    message = str(exc_info.value).lower()
    assert "non-finite" in message


def test_strict_full_reprice_rejects_nonfinite_position_values():
    service = PortfolioService()
    service.add(Position(
        id="nan-position", instrument="equity", description="invalid spot",
        quantity=1.0, params={"S": np.nan},
    ))

    with pytest.raises(ValueError) as exc_info:
        service.full_reprice_pnl()

    message = str(exc_info.value).lower()
    assert "nan-position" in message
    assert "non-finite" in message


@pytest.mark.parametrize(
    "scenario",
    [
        {"dS": np.nan},
        {"dr": np.inf},
        {"dvol": -np.inf},
        {"dfx": np.nan},
        {"dr_curve": [(5.0, np.inf)]},
        {"dr_curves": {"UNUSED": [(5.0, np.nan)]}},
        {"dS_by_name": {"UNUSED": np.inf}},
        {"dvol_by_name": {"UNUSED": np.nan}},
        {"dfx_by_pair": {"UNUSED/RUB": -np.inf}},
        {"dvol_by_position": {"unused-position": np.nan}},
    ],
)
def test_strict_full_reprice_rejects_nonfinite_unused_and_extra_shocks(scenario):
    service = PortfolioService()
    service.add(Position(
        id="bond-only", instrument="bond", description="unrelated factor",
        quantity=1.0,
        params={"face": 1_000.0, "coupon": 0.08, "T": 5.0,
                "freq": 2, "r": 0.10},
    ))

    with pytest.raises(ValueError, match="non-finite"):
        service.full_reprice_pnl(**scenario)


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        ({"pnl": 50.0, "errors": ["position failed"]}, "position failed"),
        ({"pnl": np.nan, "errors": []}, "non-finite"),
        ({}, "empty or invalid"),
        (RuntimeError("pricing crash"), "pricing crash"),
    ],
)
def test_risk_service_full_reprice_var_returns_error_not_partial_metric(
        result, reason):
    portfolio = _ResultPortfolio(result)
    zeros = np.zeros(30)

    response = RiskService().full_reprice_var(
        portfolio, zeros, zeros, zeros, zeros)

    assert response["value"] is None
    assert response["raw"] is None
    assert response["errors"]
    message = "; ".join(response["errors"])
    assert "full_reprice_var scenario 0" in message
    assert reason in message
    assert portfolio.calls == 1


def test_risk_service_success_keeps_empty_reprice_errors():
    portfolio = _ResultPortfolio({"pnl": 2.0, "errors": [], "valid": True})
    zeros = np.zeros(30)

    response = RiskService().full_reprice_var(
        portfolio, zeros, zeros, zeros, zeros)

    assert response["errors"] == []
    assert response["raw"]["reprice_errors"] == []
    assert portfolio.calls == 30
