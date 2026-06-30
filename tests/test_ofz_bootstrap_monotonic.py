"""OFZ zero bootstrap must produce a discount-factor-monotonic curve even on
noisy/inverted quotes (the recurring ofz_zero_bootstrap ingest failure)."""
import math

from infra.moex_iss.validation import validate_curve_points
from infra.ofz_bootstrap import bootstrap_zero


def _zcb(T, z):
    """A zero-coupon bond priced at continuous zero z."""
    return {"mat": T, "dirty": 100.0 * math.exp(-z * T), "cfs": [(T, 100.0)]}


def test_clean_upward_curve_passes():
    bonds = [_zcb(1.0, 0.10), _zcb(2.0, 0.11), _zcb(3.0, 0.12)]
    pts = bootstrap_zero(bonds)
    assert validate_curve_points(pts) == []
    assert len(pts) == 3


def test_df_violating_node_is_dropped():
    # T=2.35 @ z=0.110 makes DF tick *up* vs T=2.0 @ z=0.13 (negative forward),
    # a small-enough z-jump (0.02) to slip past max_step — must still be rejected.
    bonds = [_zcb(1.0, 0.14), _zcb(2.0, 0.13), _zcb(2.35, 0.110), _zcb(3.0, 0.13)]
    pts = bootstrap_zero(bonds)
    assert validate_curve_points(pts) == []                  # curve is admissible
    dfs = [df for _, _, df in pts]
    assert all(dfs[i] <= dfs[i - 1] + 1e-12 for i in range(1, len(dfs)))
    assert 2.35 not in [round(T, 2) for T, _, _ in pts]      # the bad node was dropped


def test_output_always_monotonic_postcondition():
    # a jittery inverted-then-rising RUB-like front
    zs = [(1.0, 0.145), (1.5, 0.132), (2.0, 0.121), (2.4, 0.108),
          (3.0, 0.124), (4.0, 0.131), (5.0, 0.138)]
    pts = bootstrap_zero([_zcb(T, z) for T, z in zs])
    assert validate_curve_points(pts) == []
