"""Standard tenor-grid resampling for curve display."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from api.curve_grid import STANDARD_PILLARS, standardize_curve

# A GCURVE-like native curve: 3M..10Y.
OFZ_NATIVE = [(0.25, 0.138, None), (0.5, 0.136, None), (1.0, 0.134, None),
              (2.0, 0.137, None), (5.0, 0.149, None), (10.0, 0.157, None)]


def test_full_grid_with_overnight_anchor():
    std = standardize_curve(OFZ_NATIVE, overnight_rate=0.1425)
    assert len(std) == len(STANDARD_PILLARS)            # full 1D..10Y
    assert std[0]["tenor"] == pytest.approx(1 / 365)
    assert std[0]["zero"] == pytest.approx(0.1425)      # 1D == key-rate anchor


def test_dfs_monotonic_non_increasing():
    std = standardize_curve(OFZ_NATIVE, overnight_rate=0.1425)
    dfs = [p["discount"] for p in std]
    assert all(b <= a + 1e-12 for a, b in zip(dfs, dfs[1:]))


def test_short_end_blends_to_first_node():
    # below the first native node (3M), pillars interpolate between the O/N
    # anchor (14.25% @1D) and the first node (13.8% @3M) — strictly decreasing.
    std = {round(p["tenor"] * 365): p["zero"] for p in standardize_curve(OFZ_NATIVE, overnight_rate=0.1425)}
    assert std[1] > std[7] > std[30] > std[91]          # 1D > 1W > 1M > 3M


def test_short_curve_clamps_long_end():
    # native to 3M only → no fabricated long end (no extrapolation past 3M).
    short = standardize_curve([(1 / 365, 0.142, None), (7 / 365, 0.142, None),
                               (91 / 365, 0.140, None)])
    assert max(p["tenor"] for p in short) <= 91 / 365 + 1e-9
    assert len(short) == 6                               # 1D,1W,2W,1M,2M,3M


def test_too_few_points_returns_empty():
    assert standardize_curve([(1.0, 0.14, None)]) == []
