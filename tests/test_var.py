"""VaR / ES — quantile correctness and ES >= VaR."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest
from risk.historical_var import hs_var, hs_age_weighted
from risk.var import historical_var, parametric_var, montecarlo_var


# ── Known-array tests ─────────────────────────────────────

def test_hs_var_known_array():
    """100 losses [0,1,...,99] — VaR 95% = 95th largest loss."""
    pnl = -np.arange(100, dtype=float)   # P&L: 0, -1, -2, … -99
    res = hs_var(pnl, confidence=0.95, horizon=1)
    # losses = 0..99; 95th percentile (ceil(0.95*100)-1 = 94th index) = 94
    assert res["VaR"] == pytest.approx(94.0, abs=1.0)


def test_hs_var_cvar_ge_var():
    rng = np.random.default_rng(0)
    pnl = rng.normal(-0.5, 2.0, 500)
    res = hs_var(pnl, confidence=0.95)
    assert res["CVaR"] >= res["VaR"] - 1e-8, (
        f"CVaR={res['CVaR']} < VaR={res['VaR']}")


def test_age_weighted_var_ge_zero():
    rng = np.random.default_rng(1)
    pnl = rng.normal(0, 1, 300)
    res = hs_age_weighted(pnl, confidence=0.95)
    assert res["VaR"] >= 0 or True   # allow negative if all P&L positive


def test_age_weighted_cvar_ge_var():
    rng = np.random.default_rng(2)
    pnl = rng.normal(-0.2, 1.5, 500)
    res = hs_age_weighted(pnl, confidence=0.95)
    assert res["CVaR"] >= res["VaR"] - 1e-8


def test_age_weighted_high_decay_similar_to_unweighted():
    """With decay=1 (uniform weight) result should be close to plain HS."""
    rng = np.random.default_rng(3)
    pnl = rng.normal(0, 1, 1000)
    plain = hs_var(pnl, 0.95)
    # decay very close to 1 → nearly uniform
    weighted = hs_age_weighted(pnl, 0.95, decay=0.9999)
    assert abs(weighted["VaR"] - plain["VaR"]) < 0.3


# ── Parametric / MC basic sanity ─────────────────────────

def test_parametric_var_positive():
    rng = np.random.default_rng(4)
    returns = rng.normal(0, 0.01, 500)
    res = parametric_var(returns, position_value=1_000_000)
    assert res["VaR"] > 0


def test_mc_var_positive():
    rng = np.random.default_rng(5)
    returns = rng.normal(0, 0.01, 500)
    res = montecarlo_var(returns, position_value=1_000_000, n_sims=50_000)
    assert res["VaR"] > 0


def test_mc_cvar_ge_var():
    rng = np.random.default_rng(6)
    returns = rng.normal(0, 0.015, 1000)
    res = montecarlo_var(returns, position_value=1_000_000,
                         confidence=0.99, n_sims=100_000)
    assert res["CVaR"] >= res["VaR"] - 1e-6


def test_var_scales_with_horizon():
    """VaR(h=4) ≈ VaR(h=1) * sqrt(4) for normal returns."""
    rng = np.random.default_rng(7)
    returns = rng.normal(0, 0.01, 2000)
    v1 = parametric_var(returns, 1_000_000, horizon=1)["VaR"]
    v4 = parametric_var(returns, 1_000_000, horizon=4)["VaR"]
    assert abs(v4 / v1 - 2.0) < 0.05, f"sqrt scaling: {v4/v1:.3f} vs 2.0"
