"""Monte Carlo — shape, antithetic, LSM no-recursion."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest
from models.monte_carlo import gbm_paths, mc_price, lsm
from models.black_scholes import bsm


def test_gbm_paths_shape_even():
    paths = gbm_paths(100, 0.05, 0.0, 0.20, 1.0, 252, 1000, antithetic=True, seed=0)
    assert paths.shape == (1000, 253)


def test_gbm_paths_shape_odd():
    """Odd n_sims with antithetic — should produce even number of paths."""
    paths = gbm_paths(100, 0.05, 0.0, 0.20, 1.0, 252, 999, antithetic=True, seed=0)
    # actual sims = 2*(999//2) = 998
    assert paths.shape[0] % 2 == 0
    assert paths.shape[1] == 253


def test_gbm_paths_no_antithetic():
    paths = gbm_paths(100, 0.05, 0.0, 0.20, 1.0, 50, 500, antithetic=False, seed=1)
    assert paths.shape == (500, 51)


def test_gbm_initial_price():
    paths = gbm_paths(100, 0.05, 0.0, 0.20, 1.0, 10, 200, seed=2)
    assert np.allclose(paths[:, 0], 100.0)


def test_mc_european_call_vs_bsm():
    """MC call price within 2σ of BSM for large n_sims."""
    ref = bsm(100, 100, 1.0, 0.05, 0.20).price

    def payoff(paths):
        return np.maximum(paths[:, -1] - 100, 0)

    res = mc_price(payoff, 100, 0.05, 0.0, 0.20, 1.0,
                   steps=252, n_sims=100_000, seed=42)
    assert abs(res["price"] - ref) < 0.3, (
        f"MC={res['price']:.4f} BSM={ref:.4f}")


def test_lsm_no_recursion_american_put():
    """LSM must not raise RecursionError."""
    res = lsm(100, 110, 1.0, 0.05, 0.20, n_sims=10_000, steps=50, opt="put", seed=42)
    assert "price" in res
    assert res["price"] > 0


def test_lsm_american_put_ge_european_put():
    """American put >= European put (early exercise value)."""
    eur_ref = bsm(100, 110, 1.0, 0.05, 0.20, opt="put").price
    ame = lsm(100, 110, 1.0, 0.05, 0.20, n_sims=20_000, steps=100,
              opt="put", seed=0)
    assert ame["price"] >= eur_ref - 0.5, (
        f"LSM american={ame['price']:.4f} < european BSM={eur_ref:.4f}")
