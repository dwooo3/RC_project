"""Phase FI-1 — shared fixed-income analytics + unified result contract."""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")

from curves.yield_curve import YieldCurve
from instruments.fixed_income import _price_cashflows
from instruments.fixed_income_analytics import (
    bond_yield, yield_to_workout, yield_to_worst,
    effective_duration_convexity, key_rate_durations,
    g_spread, i_spread,
)
from domain.fixed_income import FixedIncomeResult

CFS = [(1, 5), (2, 5), (3, 5), (4, 5), (5, 105)]   # 5y annual 5% bond, face 100


def _flat_curve(r=0.05):
    return YieldCurve([1, 2, 3, 5, 7, 10], [r] * 6, interp="linear")


# ── yield solvers ─────────────────────────────────────────
def test_bond_yield_recovers_known_yield():
    price = sum(c / (1.05) ** t for t, c in CFS)
    assert bond_yield(CFS, price, freq=1) == pytest.approx(0.05, abs=1e-6)


def test_par_bond_yields_coupon():
    price = 100.0  # par
    assert bond_yield(CFS, price, freq=1) == pytest.approx(0.05, abs=1e-6)


def test_yield_to_worst_callable_premium_bond():
    # premium bond (priced to 3%): yield to an earlier call at par is below YTM
    price = sum(c / (1.03) ** t for t, c in CFS)        # > 100
    res = yield_to_worst(CFS, price, freq=1, call_schedule=[(3, 105)])  # call at par+coupon
    assert res["ytm"] == pytest.approx(0.03, abs=1e-4)
    assert res["ytc"] is not None and res["ytc"] < res["ytm"]
    assert res["ytw"] == pytest.approx(res["ytc"])


# ── curve-bump risk ───────────────────────────────────────
def test_effective_duration_positive_and_sane():
    curve = _flat_curve(0.05)
    base = _price_cashflows(CFS, curve)
    reprice = lambda sh: _price_cashflows(CFS, curve.parallel_shift(sh * 1e4))
    eff_dur, eff_cvx = effective_duration_convexity(reprice, base)
    assert 3.5 < eff_dur < 5.0     # ~4.4y for a 5y 5% bond
    assert eff_cvx > 0


def test_key_rate_durations_sum_to_effective():
    curve = _flat_curve(0.05)
    base = _price_cashflows(CFS, curve)
    reprice = lambda sh: _price_cashflows(CFS, curve.parallel_shift(sh * 1e4))
    eff_dur, _ = effective_duration_convexity(reprice, base)
    krd = key_rate_durations(CFS, curve, base, _price_cashflows)
    assert sum(krd.values()) == pytest.approx(eff_dur, rel=0.02)
    assert krd[5.0] > krd[1.0]     # most sensitivity at the cashflow-heavy long node


# ── spread analytics ──────────────────────────────────────
def test_g_and_i_spread_signs():
    govt = _flat_curve(0.04)
    swap = _flat_curve(0.045)
    assert g_spread(0.06, govt, 5) > 0          # bond yields above govt
    assert i_spread(0.06, swap, 5) < g_spread(0.06, govt, 5)  # swap > govt => smaller spread


# ── contract ──────────────────────────────────────────────
def test_fixed_income_result_aliases_and_dict():
    r = FixedIncomeResult(npv=99.5, dv01=0.045, yield_=0.06)
    assert r.pv01 == 0.045 and r.bpv == 0.045   # aliases populated
    d = r.as_dict()
    assert d["yield"] == 0.06 and "yield_" not in d
