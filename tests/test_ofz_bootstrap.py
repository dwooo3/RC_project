"""OFZ zero-curve bootstrap from bond prices."""
import datetime as dt
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from infra.ofz_bootstrap import bootstrap_zero, ofz_cashflows, select_spanning


def _price(cfs, z):
    return sum(cf * math.exp(-z * t) for t, cf in cfs)


def test_bootstrap_recovers_flat_curve():
    # bonds priced off a known flat 13% continuous curve must bootstrap back to it
    z0 = 0.13
    bonds = []
    for years in (1, 2, 3, 5, 7, 10):
        cfs = [(float(k), 8.0) for k in range(1, years)] + [(float(years), 108.0)]
        bonds.append({"mat": float(years), "dirty": _price(cfs, z0), "cfs": cfs, "volume": 1})
    nodes = bootstrap_zero(bonds)
    assert len(nodes) == 6
    for _, z, _df in nodes:
        assert abs(z - z0) < 1e-3


def test_bootstrap_recovers_sloped_curve():
    def z_of(t):
        return 0.10 + 0.005 * t                       # upward slope
    bonds = []
    for years in (1, 2, 3, 5, 7, 10):
        cfs = [(float(k), 7.0) for k in range(1, years)] + [(float(years), 107.0)]
        dirty = sum(cf * math.exp(-z_of(t) * t) for t, cf in cfs)
        bonds.append({"mat": float(years), "dirty": dirty, "cfs": cfs, "volume": 1})
    nodes = bootstrap_zero(bonds)
    for T, z, _df in nodes:
        assert abs(z - z_of(T)) < 2e-3


def test_outlier_node_rejected():
    bonds = [
        {"mat": 1.0, "dirty": _price([(1.0, 110.0)], 0.13), "cfs": [(1.0, 110.0)], "volume": 1},
        {"mat": 2.0, "dirty": _price([(2.0, 110.0)], 0.40), "cfs": [(2.0, 110.0)], "volume": 1},  # 40% — wild
        {"mat": 3.0, "dirty": _price([(3.0, 110.0)], 0.132), "cfs": [(3.0, 110.0)], "volume": 1},
    ]
    nodes = bootstrap_zero(bonds, max_step=0.05)
    mats = [round(T, 1) for T, _, _ in nodes]
    assert 2.0 not in mats and 1.0 in mats and 3.0 in mats


def test_select_spanning_keeps_more_liquid_in_bucket():
    bonds = [{"mat": 1.0, "volume": 5}, {"mat": 1.1, "volume": 9}, {"mat": 3.0, "volume": 1}]
    sp = select_spanning(bonds, min_gap=0.35)
    assert len(sp) == 2 and sp[0]["volume"] == 9


def test_ofz_cashflows_rejects_true_amortizer():
    ref = {"facevalue": 1000, "mat_date": "2030-01-01"}
    sched = {"coupons": [{"coupon_date": "2027-01-01", "value": 40}],
             "amortizations": [{"amort_date": "2028-01-01", "value": 500},
                               {"amort_date": "2030-01-01", "value": 500}]}
    cfs, _ = ofz_cashflows(ref, sched, dt.date(2026, 1, 1))
    assert cfs is None


def test_ofz_cashflows_bullet_ok():
    ref = {"facevalue": 1000, "mat_date": "2030-01-01"}
    sched = {"coupons": [{"coupon_date": "2027-01-01", "value": 40},
                         {"coupon_date": "2030-01-01", "value": 40}],
             "amortizations": [{"amort_date": "2030-01-01", "value": 1000}]}
    cfs, T = ofz_cashflows(ref, sched, dt.date(2026, 1, 1))
    assert cfs is not None and abs(T - 4.0) < 0.1
    # last coupon (40/1000 face = 4.0 per 100) + redemption (100) = 104.0
    assert cfs[-1][1] == pytest.approx(104.0)
