"""Phase 3 gate: model comparison on a frozen context, convergence ladder,
solve-for and the Simulation Lab (spec §13.2, §14, §15).

The exit criterion of the phase is that an identical frozen context is
VISIBLY confirmed for comparisons — every row must carry the same
context_hash and the reference row must diff to exactly zero.
"""

from __future__ import annotations

import math

import pytest

from api.pricing_workstation import (
    compare_ws,
    convergence_ws,
    price_ws,
    simlab_ws,
    solve_ws,
)
from services.pricing_service import PricingService

BS_PARAMS = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "q": 0.0,
             "sigma": 0.2, "opt": "call"}


@pytest.fixture(scope="module")
def svc():
    return PricingService(allow_analytics_lab=True,
                          allow_non_production_models=True)


# ── model comparison (spec §15) ──────────────────────────

def test_compare_all_rows_share_one_frozen_context(svc):
    result = compare_ws(svc, None, "european_option", "black_scholes",
                        dict(BS_PARAMS))
    rows = result["rows"]
    assert len(rows) >= 10, "european option must expose its engine matrix"
    hashes = {row["context_hash"] for row in rows}
    assert hashes == {result["context_hash"]}, \
        "every engine row must reference the SAME frozen context"
    priced = [r for r in rows if r["value"] is not None]
    assert len(priced) >= 5
    snapshots = {r["snapshot_id"] for r in priced}
    assert len(snapshots) == 1, "engines priced on different snapshots"


def test_compare_reference_diffs_to_zero_and_others_are_close(svc):
    result = compare_ws(svc, None, "european_option", "black_scholes",
                        dict(BS_PARAMS))
    by_engine = {r["engine"]: r for r in result["rows"]}
    ref = by_engine["black_scholes"]
    assert ref["diff"] == 0.0 and ref["diff_pct"] == 0.0
    assert result["reference_value"] == ref["value"]
    # lattice engines must agree with closed form on a vanilla call
    crr = by_engine.get("binomial_crr")
    assert crr and crr["value"] is not None
    assert abs(crr["diff_pct"]) < 0.01
    # every row reports governance and runtime
    for row in result["rows"]:
        assert row["status"], f"{row['engine']} lost governance status"
        assert row["runtime_ms"] is not None


def test_compare_hook_streams_one_row_per_engine(svc):
    seen = []
    result = compare_ws(svc, None, "european_option", None, dict(BS_PARAMS),
                        hook=lambda done, total, row: seen.append((done, total)))
    assert len(seen) == len(result["rows"])
    assert seen[-1][0] == seen[-1][1] == len(result["rows"])


def test_compare_restricted_service_reports_error_rows_not_crash():
    restricted = PricingService()          # research engines are forbidden
    result = compare_ws(restricted, None, "european_option", "black_scholes",
                        dict(BS_PARAMS))
    failed = [r for r in result["rows"] if r["error"]]
    priced = [r for r in result["rows"] if r["value"] is not None]
    assert priced, "production engines must still price"
    assert failed, "research-only engines must surface a reason, not vanish"
    for row in failed:
        assert row["value"] is None and row["error"]


def test_compare_is_deterministic(svc):
    a = compare_ws(svc, None, "european_option", "black_scholes",
                   dict(BS_PARAMS))
    b = compare_ws(svc, None, "european_option", "black_scholes",
                   dict(BS_PARAMS))
    assert a["context_hash"] == b["context_hash"]


def test_compare_unknown_reference_engine_fails_closed(svc):
    with pytest.raises(ValueError, match="unknown engine"):
        compare_ws(svc, None, "european_option", "no_such_engine",
                   dict(BS_PARAMS))


# ── convergence ladder (spec §14) ────────────────────────

def test_convergence_lattice_converges_to_reference(svc):
    result = convergence_ws(svc, None, "european_option", "binomial_crr",
                            dict(BS_PARAMS), levels=[50, 100, 400, 1600])
    assert result["effort_key"] in ("N", "steps", "n")
    efforts = [row["effort"] for row in result["rows"]]
    assert efforts == sorted(efforts)
    last = result["rows"][-1]
    assert last["error_vs_ref"] == 0.0, "highest effort IS the reference"
    first = result["rows"][0]
    assert first["value"] is not None
    assert abs(first["error_vs_ref"]) > abs(last["error_vs_ref"])
    for row in result["rows"]:
        assert row["runtime_ms"] is not None


def test_convergence_closed_form_engine_fails_loudly(svc):
    with pytest.raises(ValueError, match="convergence неприменим"):
        convergence_ws(svc, None, "european_option", "black_scholes",
                       dict(BS_PARAMS))


def test_convergence_hook_and_level_clipping(svc):
    seen = []
    result = convergence_ws(
        svc, None, "european_option", "binomial_crr", dict(BS_PARAMS),
        levels=[1, 100, 10_000_000],
        hook=lambda done, total, row: seen.append(done))
    assert seen == list(range(1, len(result["rows"]) + 1))
    assert all(row["effort"] >= 2 for row in result["rows"])


# ── solve-for (spec §13.2) ───────────────────────────────

def test_solve_recovers_known_volatility(svc):
    target = price_ws(svc, None, "european_option", "black_scholes",
                      {**BS_PARAMS, "sigma": 0.25})["value"]
    result = solve_ws(svc, None, "european_option", "black_scholes",
                      dict(BS_PARAMS), "sigma", target, 0.05, 0.60)
    assert abs(result["root"] - 0.25) < 1e-6
    assert abs(result["residual"]) < 1e-6
    assert result["iterations"] > 0 and result["evaluations"] > 2


def test_solve_break_even_strike_is_monotone_decreasing_case(svc):
    # PV(call) falls as K rises — bisection must handle the decreasing branch
    result = solve_ws(svc, None, "european_option", "black_scholes",
                      dict(BS_PARAMS), "K", 5.0, 60.0, 200.0)
    check = price_ws(svc, None, "european_option", "black_scholes",
                     {**BS_PARAMS, "K": result["root"]})["value"]
    assert abs(check - 5.0) < 1e-6


def test_solve_without_sign_change_fails_loudly(svc):
    with pytest.raises(ValueError, match="нет смены знака"):
        solve_ws(svc, None, "european_option", "black_scholes",
                 dict(BS_PARAMS), "sigma", 1e9, 0.05, 0.60)


def test_solve_rejects_non_numeric_key(svc):
    with pytest.raises(ValueError, match="solve-for неприменим"):
        solve_ws(svc, None, "european_option", "black_scholes",
                 dict(BS_PARAMS), "opt", 5.0, 0.0, 1.0)


# ── simulation lab (spec §14) ────────────────────────────

def test_simlab_is_deterministic_and_labelled():
    a = simlab_ws("european_option", dict(BS_PARAMS), seed=7)
    b = simlab_ws("european_option", dict(BS_PARAMS), seed=7)
    assert a["nature"] == "illustrative_path_preview"
    assert a["payoff"]["mc_price"] == b["payoff"]["mc_price"]
    c = simlab_ws("european_option", dict(BS_PARAMS), seed=8)
    assert c["payoff"]["mc_price"] != a["payoff"]["mc_price"]


def test_simlab_fan_percentiles_are_ordered():
    result = simlab_ws("european_option", dict(BS_PARAMS), n_paths=3000)
    terminal_by_p = {band["p"]: band["values"][-1] for band in result["fan"]}
    values = [terminal_by_p[p] for p in (5, 25, 50, 75, 95)]
    assert values == sorted(values)
    assert result["times"][0] == 0.0
    assert abs(result["times"][-1] - BS_PARAMS["T"]) < 1e-12


def test_simlab_matches_lognormal_moments_and_bs_price(svc):
    result = simlab_ws("european_option", dict(BS_PARAMS),
                       n_paths=20000, n_steps=100, seed=1)
    s0, r, q, t = 100.0, 0.05, 0.0, 1.0
    expected_mean = s0 * math.exp((r - q) * t)
    tol = 3 * result["terminal"]["std"] / math.sqrt(result["n_paths"])
    assert abs(result["terminal"]["mean"] - expected_mean) < tol
    bs = price_ws(svc, None, "european_option", "black_scholes",
                  dict(BS_PARAMS))["value"]
    payoff = result["payoff"]
    assert abs(payoff["mc_price"] - bs) < 3 * payoff["mc_stderr"] + 1e-9
    assert 0.0 < payoff["prob_itm"] < 1.0


def test_simlab_undefined_for_products_without_spot():
    with pytest.raises(ValueError, match="нет спот-входа"):
        simlab_ws("interest_rate_swap", {})
