"""FRN engine identities (registry gate: frn Prototype -> Approximation)."""

from __future__ import annotations

import pytest

from curves.yield_curve import YieldCurve
from instruments.fixed_income import frn


def test_single_curve_collapses_to_par_reset():
    """proj == disc: the floating leg telescopes to par, so the price equals
    the par-reset identity face + PV(spread coupons) exactly."""
    curve = YieldCurve.flat(0.12)
    res = frn(1000.0, 0.015, 5.0, 2, curve)
    dt, periods = 0.5, 10
    spread_pv = sum(1000.0 * 0.015 * dt * curve.discount(i * dt)
                    for i in range(1, periods + 1))
    assert res["price"] == pytest.approx(1000.0 + spread_pv, rel=1e-12)
    assert res["float_pv"] + res["redemption_pv"] == pytest.approx(1000.0, rel=1e-12)


def test_dual_curve_basis_moves_coupons():
    """A projection curve above the discount curve raises the projected
    coupons -> the note prices above the single-curve answer (and vice versa)."""
    disc = YieldCurve.flat(0.12)
    proj_hi = YieldCurve.flat(0.14)
    proj_lo = YieldCurve.flat(0.10)
    base = frn(1000.0, 0.0, 5.0, 2, disc)["price"]
    hi = frn(1000.0, 0.0, 5.0, 2, disc, proj_hi)["price"]
    lo = frn(1000.0, 0.0, 5.0, 2, disc, proj_lo)["price"]
    assert hi > base > lo
    assert base == pytest.approx(1000.0, rel=1e-12)


def test_spread_dv01_is_annuity():
    """1bp of extra spread must be worth face * annuity / 10000."""
    curve = YieldCurve.flat(0.10)
    res = frn(1000.0, 0.02, 3.0, 4, curve)
    bumped = frn(1000.0, 0.02 + 1e-4, 3.0, 4, curve)
    assert bumped["price"] - res["price"] == pytest.approx(res["spread_dv01"], rel=1e-9)


def test_registry_promoted():
    from models.registry import MODEL_REGISTRY, ModelStatus
    assert MODEL_REGISTRY["frn"]["status"] == ModelStatus.APPROXIMATION
    assert MODEL_REGISTRY["frn"]["tests"]
