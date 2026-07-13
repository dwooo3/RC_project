"""MR-6/MR-8 regressions: granular Matrix-MC, EVT and IV readiness."""

from __future__ import annotations

import math
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from api import marketrisk
from api.serialization import jsonable
from domain.portfolio import Position
from services.portfolio_service import PortfolioService


class _HistoryDB:
    def __init__(self, series):
        self.series = series

    def get_time_series(self, factor_id, *args):
        del args
        return [{"dt": dt, "value": value}
                for dt, value in self.series.get(factor_id, [])]


def _dates(n: int, start: date = date(2022, 1, 1)) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def _base_history(n: int, start: date = date(2022, 1, 1)) -> dict:
    dates = _dates(n, start)
    history = {
        "IMOEX:price": list(zip(dates, 100.0 * np.exp(np.arange(n) * 0.001))),
        "KBD:5Y": list(zip(dates, 0.10 + np.arange(n) * 0.00001)),
        "RVI:price": list(zip(dates, 20.0 + np.arange(n) * 0.01)),
        "USDRUB:fix": list(zip(dates, 90.0 + np.arange(n) * 0.01)),
    }
    for tenor in marketrisk._KBD_TENORS:
        history[f"KBD:{tenor:g}Y"] = list(history["KBD:5Y"])
    return history


def _ctx(history, portfolio=None):
    return SimpleNamespace(
        market_db=_HistoryDB(history),
        portfolio=portfolio or PortfolioService(),
    )


def test_iv_readiness_counts_shocks_not_raw_levels():
    history = _base_history(61)
    dates = _dates(61)
    history["IV:MIX"] = list(zip(dates[:60], 0.20 + np.arange(60) * 0.001))

    fallback = marketrisk.factor_shifts(_ctx(history), window=60)
    assert fallback["factor_diagnostics"]["volatility"]["selected_source"] == "RVI:price"
    assert len(fallback["dates"]) == 60

    history["IV:MIX"] = list(zip(dates, 0.20 + np.arange(61) * 0.001))
    own = marketrisk.factor_shifts(_ctx(history), window=60)
    assert own["factor_diagnostics"]["volatility"]["selected_source"] == "IV:MIX"
    assert own["dvol"] == pytest.approx(np.full(60, 0.001))


def test_iv30_is_preferred_without_splicing_legacy_history(monkeypatch):
    history = _base_history(61)
    dates = _dates(61)
    # Both methodologies cover the calendar but have deliberately different
    # moves. The canonical constant-maturity series must win as a whole.
    history["IV30:MIX"] = list(zip(
        dates, 0.25 + np.arange(61) * 0.002))
    history["IV:MIX"] = list(zip(
        dates, 0.15 + np.arange(61) * 0.010))
    monkeypatch.setattr(
        marketrisk,
        "_iv30_consumer_readiness",
        lambda *args, **kwargs: {"ready": True, "blockers": []},
    )

    shifts = marketrisk.factor_shifts(_ctx(history), window=60)

    diag = shifts["factor_diagnostics"]["volatility"]
    assert diag["selected_source"] == "IV30:MIX"
    assert shifts["dvol"] == pytest.approx(np.full(60, 0.002))
    assert "30d ATM-forward" in shifts["factors"][2]


def test_orphan_iv30_levels_without_operational_lineage_use_rvi_proxy():
    history = _base_history(61)
    dates = _dates(61)
    history["IV30:MIX"] = list(zip(
        dates, 0.25 + np.arange(61) * 0.002))

    shifts = marketrisk.factor_shifts(_ctx(history), window=60)

    diag = shifts["factor_diagnostics"]["volatility"]
    assert diag["selected_source"] == "RVI:price"
    iv30 = next(row for row in diag["candidates"]
                if row["source"] == "IV30:MIX")
    assert iv30["coverage_ready"] is True
    assert iv30["operational_readiness"]["ready"] is False


def test_iv_cannot_shorten_window_and_stress_uses_period_coverage():
    history = _base_history(501)
    dates = _dates(501)
    history["IV:MIX"] = list(zip(dates[-61:], 0.20 + np.arange(61) * 0.001))

    long_window = marketrisk.factor_shifts(_ctx(history), window=500)
    short_window = marketrisk.factor_shifts(_ctx(history), window=60)
    assert len(long_window["dates"]) == 500
    assert long_window["factor_diagnostics"]["volatility"]["selected_source"] == "RVI:price"
    assert short_window["factor_diagnostics"]["volatility"]["selected_source"] == "IV:MIX"

    # Raw IV points outside the requested stress period must not be selected.
    history["IV:MIX"] = list(zip(
        _dates(70, date(2026, 1, 1)), 0.20 + np.arange(70) * 0.001))
    stress = marketrisk.factor_shifts(
        _ctx(history), frm=dates[0], till=dates[100])
    assert stress["factor_diagnostics"]["volatility"]["selected_source"] == "RVI:price"
    assert len(stress["dates"]) == 100


def test_iv_readiness_supplies_fifty_horizon_windows():
    history = _base_history(70)
    dates = _dates(70)
    history["IV:MIX"] = list(zip(dates[:69], 0.20 + np.arange(69) * 0.001))

    fallback = marketrisk.factor_shifts(
        _ctx(history), window=60, horizon=20)
    assert fallback["factor_diagnostics"]["volatility"]["selected_source"] == "RVI:price"
    assert fallback["factor_diagnostics"]["volatility"]["required_daily_shocks"] == 69

    history["IV:MIX"] = list(zip(dates, 0.20 + np.arange(70) * 0.001))
    own = marketrisk.factor_shifts(_ctx(history), window=60, horizon=20)
    assert own["factor_diagnostics"]["volatility"]["selected_source"] == "IV:MIX"


def test_per_underlying_iv_is_aligned_and_explicit():
    history = _base_history(61)
    dates = _dates(61)
    history["IV:SBRF"] = list(zip(dates, 0.30 + np.arange(61) * 0.002))
    book = PortfolioService()
    book.add(Position(
        id="sber", instrument="option", quantity=1.0, description="SBER call",
        params={"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.0,
                "sigma": 0.3, "q": 0.0, "opt": "call", "secid": "SBER"}))

    shifts = marketrisk.factor_shifts(_ctx(history, book), window=60)

    assert shifts["vol_names"]["SBER"] == pytest.approx(np.full(60, 0.002))
    diag = shifts["factor_diagnostics"]["volatility"]["per_underlying"]["SBER"]
    assert diag["selected_source"] == "IV:SBRF"
    assert diag["fallback"] is False


class _RecordingPortfolio:
    def __init__(self):
        self.calls = []

    def full_reprice_pnl(self, **kwargs):
        self.calls.append(kwargs)
        pnl = kwargs["dS"] + kwargs["dvol"] + kwargs["dfx"] + kwargs["dr"]
        pnl += sum((kwargs.get("dS_by_name") or {}).values())
        pnl += sum((kwargs.get("dvol_by_name") or {}).values())
        pnl += sum((kwargs.get("dfx_by_pair") or {}).values())
        return {"pnl": pnl, "errors": []}


def test_matrix_mc_routes_granular_factors_without_duplicate_usd(monkeypatch):
    n = 80
    x = np.linspace(-0.02, 0.02, n)
    shifts = {
        "dates": [f"d{i}" for i in range(n)],
        "eq": x, "dr": x * 0.01, "dvol": np.sin(np.arange(n)) * 0.001,
        "fx": np.cos(np.arange(n)) * 0.002,
        "dr_tenors": {t: x * (0.005 + i * 0.001)
                      for i, t in enumerate(marketrisk._KBD_TENORS)},
        "eq_names": {"SBER": np.roll(x, 1)},
        "vol_names": {"SBER": np.sin(np.arange(n) + 0.5) * 0.001},
        "fx_pairs": {
            "USD/RUB": np.cos(np.arange(n)) * 0.002,
            "EUR/RUB": np.cos(np.arange(n) + 0.7) * 0.002,
        },
        "factors": ["synthetic"], "factor_warnings": [],
    }
    portfolio = _RecordingPortfolio()
    monkeypatch.setattr(marketrisk, "factor_shifts", lambda *args, **kwargs: shifts)

    result = marketrisk.mc_var_matrix(
        SimpleNamespace(portfolio=portfolio), n_sims=12, seed=7)

    assert result["factors"].count("fx:USD/RUB") == 1
    assert "equity:SBER" in result["factors"]
    assert "vol:SBER" in result["factors"]
    assert "fx:EUR/RUB" in result["factors"]
    assert result["factor_routes"]["fx"]["USD/RUB"] == "fx:USD/RUB"
    assert len(portfolio.calls) == 12
    assert all("SBER" in call["dS_by_name"] for call in portfolio.calls)
    assert all("SBER" in call["dvol_by_name"] for call in portfolio.calls)
    assert all(set(call["dfx_by_pair"]) == {"USD/RUB", "EUR/RUB"}
               for call in portfolio.calls)


def test_overview_propagates_evt_diagnostics_and_uses_cvar(monkeypatch):
    pnl = np.linspace(-2.0, 2.0, 100)
    hp = {
        "pnl": pnl, "dates": [f"d{i}" for i in range(len(pnl))],
        "horizon_method": "none", "factors": ["synthetic"],
        "reprice_errors": [], "factor_warnings": ["RVI proxy visible"],
        "factor_diagnostics": {"volatility": {"selected_source": "RVI:price"}},
    }
    monkeypatch.setattr(marketrisk, "hyppl", lambda *args, **kwargs: hp)

    import risk.var as var_module
    monkeypatch.setattr(var_module, "evt_var", lambda *args, **kwargs: {
        "VaR": 10.0, "CVaR": 15.0, "threshold": 1.2, "xi": 0.4,
        "beta": 0.5, "n_exceedances": 25,
        "xi_by_threshold": {0.13: 0.5, 0.07: 0.3, 0.10: 0.4},
        "xi_spread": 0.2, "warnings": ["thin tail"],
    })
    ctx = SimpleNamespace(portfolio=PortfolioService())

    result = marketrisk.overview(ctx, confidence=0.95, window=100)
    evt = next(method for method in result["methods"] if method["method"] == "evt")

    assert evt["es"] == 15.0
    assert evt["confidence"] == 0.99
    assert evt["n_exceedances"] == 25
    assert [point["threshold_pct"] for point in evt["xi_grid"]] == [0.07, 0.10, 0.13]
    assert "EVT: thin tail" in result["data_quality"]
    assert "RVI proxy visible" in result["data_quality"]
    assert jsonable(result)["evt_diagnostics"]["xi"] == 0.4


def test_overview_represents_infinite_evt_es_as_null(monkeypatch):
    pnl = np.linspace(-2.0, 2.0, 100)
    monkeypatch.setattr(marketrisk, "hyppl", lambda *args, **kwargs: {
        "pnl": pnl, "dates": [f"d{i}" for i in range(100)],
        "horizon_method": "none", "factors": [], "reprice_errors": [],
    })
    import risk.var as var_module
    monkeypatch.setattr(var_module, "evt_var", lambda *args, **kwargs: {
        "VaR": 10.0, "CVaR": math.inf, "threshold": 1.2, "xi": 1.1,
        "beta": 0.5, "n_exceedances": 25, "xi_by_threshold": {0.1: 1.1},
        "xi_spread": 0.0, "warnings": ["ES undefined"],
    })

    result = marketrisk.overview(
        SimpleNamespace(portfolio=PortfolioService()), window=100)
    evt = next(method for method in result["methods"] if method["method"] == "evt")
    assert evt["es"] is None
    assert jsonable(result)["methods"][-1]["es"] is None
