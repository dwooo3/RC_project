"""Directed regressions for incremental-VaR factor-universe consistency."""

from __future__ import annotations

import math
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from api import marketrisk
from api.pricing_workstation import portfolio_repricing_engine
from domain.portfolio import Position
from services.portfolio_service import PortfolioService


class _HistoryDB:
    def __init__(self, series):
        self.series = series

    def get_time_series(self, factor_id):
        return [
            {"dt": dt, "value": value}
            for dt, value in self.series.get(factor_id, [])
        ]


def _levels(growth: float) -> list[tuple[str, float]]:
    start = date(2026, 1, 1)
    return [
        ((start + timedelta(days=i)).isoformat(), 100.0 * growth**i)
        for i in range(61)
    ]


def _base_portfolio() -> PortfolioService:
    ps = PortfolioService()
    ps.add(Position(id="base", instrument="equity", quantity=1.0,
                    description="Base", params={"S": 100.0, "secid": "BASE"}))
    return ps


def test_factor_universe_comes_from_explicit_union_portfolio():
    flat = _levels(1.0)
    db = _HistoryDB({
        "IMOEX:price": flat,
        "KBD:5Y": [(dt, 0.10) for dt, _ in flat],
        "RVI:price": [(dt, 20.0) for dt, _ in flat],
        "USDRUB:fix": [(dt, 90.0) for dt, _ in flat],
        "NEW:price": _levels(1.01),
        "EURRUB:fix": _levels(1.02),
    })
    persisted = _base_portfolio()
    union = _base_portfolio()
    union.add(Position(id="new_eq", instrument="option", quantity=1.0,
                       description="New equity", params={"S": 100.0,
                       "K": 100.0, "T": 1.0, "r": 0.0, "sigma": 0.2,
                       "q": 0.0, "opt": "call", "secid": "NEW"}))
    union.add(Position(id="new_fx", instrument="fx_forward", quantity=1.0,
                       description="New FX", ccy_pair="EUR/RUB",
                       params={"S": 100.0, "K": 100.0, "T": 1.0,
                               "r_d": 0.0, "r_f": 0.0,
                               "ccy_pair": "EUR/RUB"}))
    ctx = SimpleNamespace(market_db=db, portfolio=persisted)

    shifts = marketrisk.factor_shifts(
        ctx, window=60, portfolio=union)

    assert np.allclose(shifts["eq"], 0.0)
    assert np.allclose(shifts["fx"], 0.0)
    assert shifts["eq_names"]["NEW"] == pytest.approx(math.log(1.01))
    assert shifts["fx_pairs"]["EUR/RUB"] == pytest.approx(math.log(1.02))
    assert "NEW" not in marketrisk.factor_shifts(
        ctx, window=60)["eq_names"]


@pytest.mark.parametrize(
    ("product", "params", "identity", "expected_engine"),
    [
        ("european_option",
         {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.0,
          "sigma": 0.2, "q": 0.0, "opt": "call", "secid": "NEW"},
         ("secid", "NEW"), "black_scholes"),
        ("fx_forward",
         {"S": 100.0, "forward_agreed": 100.0, "T": 1.0,
          "r_d": 0.0, "r_f": 0.0, "ccy_pair": "EUR/RUB"},
         ("ccy_pair", "EUR/RUB"), "fx_forward"),
    ],
)
def test_incremental_uses_one_union_scenario_set(
        monkeypatch, product, params, identity, expected_engine):
    base = _base_portfolio()
    ctx = SimpleNamespace(
        portfolio=base, snapshot=SimpleNamespace(snapshot_id="snapshot"))
    factor_sources = []
    repriced = []

    shared = {
        "dates": ["d1", "d2", "d3"],
        "eq": np.array([-0.01, 0.0, 0.01]),
        "dr": np.zeros(3),
        "dvol": np.zeros(3),
        "fx": np.array([-0.02, 0.0, 0.02]),
        "dr_tenors": {},
        "eq_names": {"NEW": np.array([-0.03, 0.0, 0.03])},
        "fx_pairs": {"EUR/RUB": np.array([-0.04, 0.0, 0.04])},
        "factors": ["shared union factors"],
        "has_fx": True,
    }

    def fake_factor_shifts(_ctx, _window, frm=None, till=None, portfolio=None):
        del frm, till
        positions = {position.id: position for position in portfolio.positions}
        factor_sources.append(set(positions))
        assert positions["whatif_trade"].params[identity[0]] == identity[1]
        return shared

    def fake_reprice(ps, shifts):
        ids = {position.id for position in ps.positions}
        repriced.append((ids, id(shifts), tuple(shifts["dates"])))
        scale = 1.0 if ids == {"base"} else 2.0 if ids == {"whatif_trade"} else 3.0
        return np.array([-scale, 0.0, scale]), set()

    monkeypatch.setattr(marketrisk, "factor_shifts", fake_factor_shifts)
    monkeypatch.setattr(marketrisk, "_reprice_series", fake_reprice)
    monkeypatch.setattr(marketrisk, "_CACHE", {
        ("snapshot", 60, None, None, 1): {
            "dates": ["cached"], "pnl": np.array([999.0]),
        },
    })

    result = marketrisk.incremental(
        ctx, product, None, params, confidence=0.99, window=60)

    assert result["engine"] == expected_engine
    assert factor_sources == [{"base", "whatif_trade"}]
    assert [ids for ids, _, _ in repriced] == [
        {"base"}, {"base", "whatif_trade"}, {"whatif_trade"}]
    assert len({scenario_id for _, scenario_id, _ in repriced}) == 1
    assert {dates for _, _, dates in repriced} == {("d1", "d2", "d3")}
    assert result["n_scenarios"] == 3
    assert result["var_with_trade"] == pytest.approx(
        result["var_base"] + result["incremental_var"])


def test_incremental_engine_is_validated_before_scenario_generation(monkeypatch):
    ctx = SimpleNamespace(portfolio=_base_portfolio())
    params = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.0,
              "sigma": 0.2, "q": 0.0, "opt": "call"}
    monkeypatch.setattr(
        marketrisk, "factor_shifts",
        lambda *args, **kwargs: pytest.fail("scenarios must not be generated"))

    assert portfolio_repricing_engine(
        "european_option", None) == "black_scholes"
    assert portfolio_repricing_engine(
        "european_option", "black_scholes") == "black_scholes"
    with pytest.raises(ValueError, match="cannot be reproduced"):
        marketrisk.incremental(
            ctx, "european_option", "heston_cf", params, window=60)
    with pytest.raises(ValueError, match="unknown engine"):
        marketrisk.incremental(
            ctx, "european_option", "typo_engine", params, window=60)


@pytest.mark.parametrize(
    ("params", "quantity"),
    [({"S": float("nan")}, 1.0), ({"S": float("inf")}, 1.0),
     ({"S": 100.0}, float("nan"))],
)
def test_incremental_rejects_non_finite_trade_inputs(
        monkeypatch, params, quantity):
    ctx = SimpleNamespace(portfolio=_base_portfolio())
    complete = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.0,
                "sigma": 0.2, "q": 0.0, "opt": "call"} | params
    monkeypatch.setattr(
        marketrisk, "factor_shifts",
        lambda *args, **kwargs: pytest.fail("scenarios must not be generated"))

    with pytest.raises(ValueError, match="finite"):
        marketrisk.incremental(
            ctx, "european_option", "black_scholes", complete,
            quantity=quantity, window=60)


def test_incremental_rejects_non_finite_repricing(monkeypatch):
    base = _base_portfolio()
    ctx = SimpleNamespace(portfolio=base)
    shared = {
        "dates": ["d1"], "eq": np.zeros(1), "dr": np.zeros(1),
        "dvol": np.zeros(1), "fx": np.zeros(1), "dr_tenors": {},
        "eq_names": {}, "fx_pairs": {}, "factors": ["test"], "has_fx": True,
    }
    monkeypatch.setattr(marketrisk, "factor_shifts", lambda *args, **kwargs: shared)
    monkeypatch.setattr(
        marketrisk, "_reprice_series",
        lambda *_args, **_kwargs: (np.array([float("nan")]), set()))

    with pytest.raises(ValueError, match="non-finite"):
        marketrisk.incremental(
            ctx, "european_option", "black_scholes",
            {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.0,
             "sigma": 0.2, "q": 0.0, "opt": "call"}, window=60)


def test_portfolio_add_uses_the_same_engine_gate(monkeypatch):
    from api import server

    class _Portfolio:
        positions = []

        @staticmethod
        def price_all():
            return None

    class _Context:
        portfolio = _Portfolio()

        def __init__(self):
            self.calls = []

        def add_position(self, instrument, params, description, quantity):
            self.calls.append((instrument, params, description, quantity))
            return SimpleNamespace(
                id="captured", instrument=instrument, description=description,
                quantity=quantity, market_value=0.0)

    fake_ctx = _Context()
    monkeypatch.setattr(server, "CONTEXT", fake_ctx)
    params = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.0,
              "sigma": 0.2, "q": 0.0, "opt": "call", "secid": "NEW"}

    with pytest.raises(server.HTTPException) as exc_info:
        server.portfolio_add(server.WsCaptureRequest(
            product="european_option", engine="heston_cf", params=params))
    assert exc_info.value.status_code == 400
    assert "cannot be reproduced" in exc_info.value.detail
    assert fake_ctx.calls == []

    result = server.portfolio_add(server.WsCaptureRequest(
        product="european_option", engine=None, params=params))
    assert result["engine"] == "black_scholes"
    assert fake_ctx.calls[0][1]["secid"] == "NEW"
