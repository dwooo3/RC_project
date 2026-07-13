"""MR-7: short/empty backtest samples must fail in a controlled way."""

from types import SimpleNamespace

import numpy as np

import pytest

from api import marketrisk
from risk.var import kupiec_test


def test_kupiec_empty_sample_is_explicitly_not_applicable():
    result = kupiec_test(0, 0, 0.99)

    assert result["applicable"] is False
    assert result["reject"] is False
    assert result["lr_stat"] is None
    assert result["p_value"] is None
    assert "at least one" in result["reason"]


@pytest.mark.parametrize(
    ("n_obs", "n_exceptions"),
    [(-1, 0), (10, -1), (10, 11), (10.9, 1), (10, 1.9), (True, 0)],
)
def test_kupiec_rejects_inconsistent_counts(n_obs, n_exceptions):
    with pytest.raises(ValueError):
        kupiec_test(n_obs, n_exceptions, 0.99)


def test_kupiec_large_sample_stays_finite_without_underflow():
    result = kupiec_test(100_000, 1_000, 0.99)

    assert np.isfinite(result["lr_stat"])
    assert np.isfinite(result["p_value"])
    assert result["reject"] is False


def _hyppl(n: int) -> dict:
    return {
        "dates": [f"d{i:03d}" for i in range(n)],
        "pnl": np.zeros(n),
    }


def test_backtest_rejects_insufficient_history_before_kupiec(monkeypatch):
    monkeypatch.setattr(marketrisk, "hyppl", lambda *_args, **_kwargs: _hyppl(79))

    with pytest.raises(ValueError, match="need at least 80"):
        marketrisk.backtest(SimpleNamespace(), lookback=250)


@pytest.mark.parametrize("lookback", [0, 59, 60.5, True])
def test_backtest_rejects_invalid_lookback(monkeypatch, lookback):
    monkeypatch.setattr(marketrisk, "hyppl", lambda *_args, **_kwargs: _hyppl(100))

    with pytest.raises(ValueError, match="lookback"):
        marketrisk.backtest(SimpleNamespace(), lookback=lookback)


def test_backtest_preserves_minimum_out_of_sample(monkeypatch):
    monkeypatch.setattr(marketrisk, "hyppl", lambda *_args, **_kwargs: _hyppl(80))

    result = marketrisk.backtest(SimpleNamespace(), lookback=250)

    assert result["lookback"] == 60
    assert result["n_obs"] == 20
    assert result["kupiec"]["applicable"] is True
