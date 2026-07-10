"""Этап 1 плана по отчёту валидации (VALIDATION_REMARKS_PLAN_2026_07_10):
D1 christoffersen guard, D2 basket moment matching, A7 FX forward-fill,
M6-lite направление смещения backtest."""

from __future__ import annotations

import os
import warnings

import numpy as np
import pytest


# ── D1: christoffersen edge cases без NaN/warning ────────


def test_christoffersen_no_exceptions_is_not_applicable():
    from risk.var import christoffersen_test
    with warnings.catch_warnings():
        warnings.simplefilter("error")               # любой RuntimeWarning = fail
        res = christoffersen_test(np.zeros(250, dtype=int))
    assert res["applicable"] is False
    assert res["reject"] is False
    assert res["p_value"] is None


def test_christoffersen_short_series_is_not_applicable():
    from risk.var import christoffersen_test
    res = christoffersen_test(np.array([1]))
    assert res["applicable"] is False
    assert "short" in res["reason"]


def test_christoffersen_normal_case_still_works():
    from risk.var import christoffersen_test
    rng = np.random.default_rng(7)
    exceptions = (rng.uniform(size=500) < 0.01).astype(int)
    exceptions[10] = 1                                # гарантируем >=1 пробой
    res = christoffersen_test(exceptions)
    assert res["applicable"] is True
    assert res["p_value"] is not None
    assert np.isfinite(res["lr_stat"])


def test_clustered_exceptions_rejected():
    """Кластер подряд идущих пробоев должен отклоняться тестом независимости."""
    from risk.var import christoffersen_test
    exceptions = np.zeros(500, dtype=int)
    exceptions[100:112] = 1                           # 12 подряд — явная кластеризация
    res = christoffersen_test(exceptions)
    assert res["applicable"] is True
    assert res["reject"], "кластеризация пробоев обязана отклоняться"


# ── D2: basket moment matching == Levy == MC ─────────────


def test_basket_moment_matching_matches_mc_at_t2():
    """Пример из отчёта: до фикса moment matching давал 21.42 против MC 15.30."""
    from instruments.multi_asset import basket_option
    corr = np.array([[1.0, 0.3], [0.3, 1.0]])
    args = ([100, 100], [0.5, 0.5], 100.0, 2.0, 0.05, [0.2, 0.25], corr)
    mm = basket_option(*args, opt="call", method="moment_matching")
    mc = basket_option(*args, opt="call", method="mc", n_sims=200_000)
    assert mm["price"] == pytest.approx(15.2865, abs=2e-3), "Levy reference"
    assert abs(mm["price"] - mc["price"]) < 3 * mc["stderr"] + 0.05


def test_basket_moment_matching_single_asset_is_black76():
    """Одна бумага с весом 1 — корзина вырождается в Black-76 на её форвард."""
    from instruments.multi_asset import basket_option
    from models.black_scholes import black76
    import math
    S, K, T, r, sig = 100.0, 105.0, 1.5, 0.05, 0.25
    mm = basket_option([S], [1.0], K, T, r, [sig], np.array([[1.0]]),
                       opt="call", method="moment_matching")
    F = S * math.exp(r * T)
    assert mm["price"] == pytest.approx(black76(F, K, T, r, sig, "call").price,
                                        rel=1e-9)


# ── A7 / M6: живая БД ────────────────────────────────────

_DB = os.path.join(os.path.dirname(__file__), "..", "data", "market_data.sqlite")

pytestmark_live = pytest.mark.skipif(not os.path.exists(_DB),
                                     reason="live market store not present")


@pytestmark_live
def test_fx_factor_forward_filled():
    from api.context import CONTEXT
    from api.marketrisk import factor_shifts
    s = factor_shifts(CONTEXT, 500)
    nz = int((s["fx"] != 0).sum())
    assert nz > 350, f"после ffill ненулевых FX-дней должно быть заметно больше 284, есть {nz}"
    ann_vol = float(np.std(s["fx"]) * np.sqrt(252))
    assert 0.10 < ann_vol < 0.60, f"неправдоподобная FX-вола {ann_vol:.2%}"


@pytestmark_live
def test_backtest_reports_bias_direction():
    from api.context import CONTEXT
    from api.marketrisk import backtest
    bt = backtest(CONTEXT, confidence=0.99, window=300, lookback=150)
    assert bt["bias"] in ("conservative", "aggressive", "in_line")
    if bt["n_exceptions"] < bt["expected_exceptions"]:
        assert bt["bias"] == "conservative"
    assert "applicable" in bt["christoffersen"]
