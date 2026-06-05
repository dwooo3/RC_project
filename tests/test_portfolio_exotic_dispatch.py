"""Layer 1 — PortfolioService prices/risks exotic instruments (save-to-portfolio)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")

from domain.portfolio import Position
from services.portfolio_service import PortfolioService


def _pos(instrument, params, qty=1.0):
    return Position(id=f"p-{instrument}", instrument=instrument,
                    description=instrument, quantity=qty, params=params)


def _priced(portfolio, pos):
    portfolio.add(pos)
    portfolio.value()          # triggers pricing/risk
    return pos


def test_barrier_position_priced_with_greeks():
    pf = PortfolioService("T")
    pos = _priced(pf, _pos("barrier", {"S": 100, "K": 100, "H": 90, "T": 1.0,
                                       "r": 0.05, "sigma": 0.20, "opt": "call",
                                       "barrier_type": "down-out"}))
    assert pos.price > 0 and pos.market_value > 0
    assert pos.delta != 0 and pos.vega != 0
    units = {e.unit for e in pos.exposures}
    assert {"Delta", "Vega"} <= units


def test_digital_position_uses_analytic_greeks():
    pf = PortfolioService("T")
    pos = _priced(pf, _pos("digital", {"S": 100, "K": 100, "T": 0.5, "r": 0.04,
                                       "sigma": 0.20, "style": "cash", "cash": 1.0}))
    assert pos.price > 0
    assert any(e.factor_id == "equity.spot" for e in pos.exposures)


@pytest.mark.parametrize("inst,params", [
    ("asian", {"S": 100, "K": 100, "T": 1.0, "r": 0.05, "sigma": 0.20,
               "averaging": "geometric"}),
    ("lookback", {"S": 100, "T": 1.0, "r": 0.05, "sigma": 0.20,
                  "strike_type": "floating", "opt": "call"}),
    ("spread", {"S1": 100, "S2": 100, "K": 5, "T": 1.0, "r": 0.05,
                "sigma1": 0.20, "sigma2": 0.25, "rho": 0.4}),
])
def test_exotic_positions_priced_and_exposed(inst, params):
    pf = PortfolioService("T")
    pos = _priced(pf, _pos(inst, params))
    assert pos.price > 0
    assert pos.delta != 0
    assert any(e.bucket == "Equity" for e in pos.exposures)


def test_autocall_position_priced_mc():
    pf = PortfolioService("T")
    pos = _priced(pf, _pos("autocall", {
        "S0": 100, "r": 0.05, "q": 0.0, "sigma": 0.20, "T": 3.0,
        "obs_dates": [1, 2, 3], "autocall_barrier": 1.0, "coupon_barrier": 0.70,
        "ki_barrier": 0.65, "coupon_rate": 0.10, "n_sims": 4000, "steps": 50}))
    assert pos.price is not None
    assert pos.model_id == "structured_autocall"


def test_portfolio_aggregates_exotic_exposures():
    pf = PortfolioService("T")
    pf.add(_pos("barrier", {"S": 100, "K": 100, "H": 90, "T": 1.0, "r": 0.05,
                            "sigma": 0.20, "opt": "call", "barrier_type": "down-out"}))
    pf.add(_pos("digital", {"S": 100, "K": 100, "T": 0.5, "r": 0.04, "sigma": 0.20}))
    pf.value()
    exposures = pf.risk_factor_exposures()
    factor_ids = {e.factor_id for e in exposures}
    assert "equity.spot" in factor_ids
    assert "vol.implied" in factor_ids


# ── Rates derivatives dispatch ───────────────────────────

def test_frn_position_dv01():
    pf = PortfolioService("T")
    pos = _priced(pf, _pos("frn", {"face": 1000, "spread": 0.01, "T": 5, "freq": 2, "r": 0.10}))
    assert pos.price > 0
    assert any(e.unit == "DV01" for e in pos.exposures)


def test_cap_floor_position_dv01_and_vega():
    pf = PortfolioService("T")
    pos = _priced(pf, _pos("cap_floor", {"notional": 1_000_000, "K": 0.10, "T": 3,
                                         "freq": 2, "vol": 0.20, "r": 0.10, "opt": "cap"}))
    assert pos.price >= 0
    units = {e.unit for e in pos.exposures}
    assert "DV01" in units and "Vega" in units


def test_swaption_position_dv01_and_vega():
    pf = PortfolioService("T")
    pos = _priced(pf, _pos("swaption", {"notional": 1_000_000, "K": 0.10, "T_option": 1,
                                        "T_swap": 5, "freq": 2, "sigma": 0.20, "r": 0.10,
                                        "opt": "payer"}))
    assert pos.price >= 0
    assert pos.model_id == "swaption"
    units = {e.unit for e in pos.exposures}
    assert "DV01" in units and "Vega" in units


def test_fra_position_dv01():
    pf = PortfolioService("T")
    pos = _priced(pf, _pos("fra", {"notional": 1_000_000, "K": 0.10, "T1": 1, "T2": 1.5, "r": 0.10}))
    assert any(e.unit == "DV01" for e in pos.exposures)


def test_bond_position_has_key_rate_exposures():
    pf = PortfolioService("T")
    pos = _priced(pf, _pos("bond", {"face": 1000, "coupon": 0.07, "T": 10, "freq": 2, "r": 0.10}))
    kr = [e for e in pos.exposures if e.unit == "Key Rate DV01"]
    assert len(kr) >= 3
    headline = next(e for e in pos.exposures if e.unit == "DV01")
    assert sum(e.sensitivity for e in kr) == pytest.approx(headline.sensitivity, rel=0.1)
