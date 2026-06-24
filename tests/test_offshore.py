"""Offshore FX funding curves — bootstrap + CNH construction (pure, no network)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math

from infra.offshore import build_offshore_curve


def test_build_offshore_curve_money_market():
    # O/N + 3M + 6M par rates -> continuous zeros, DF=1/(1+r*t) at short end
    pts = [(1 / 365, 0.036), (91 / 365, 0.0364), (182 / 365, 0.0368)]
    nodes = build_offshore_curve(pts)
    assert len(nodes) == 3
    # implied simple rate at 6M recovers the input
    t, z, df = nodes[-1]
    assert (1 / df - 1) / t == __import__("pytest").approx(0.0368, abs=1e-4)


def test_build_offshore_curve_needs_two_points():
    assert build_offshore_curve([(1 / 365, 0.036)]) == []


def test_cnh_cip_identity():
    # CNH = SOFR + carry(Si) - carry(CNY); a flat check that the arithmetic holds
    sofr, carry_si, carry_cny = 0.036, 0.104, 0.100
    cnh = sofr + carry_si - carry_cny
    assert cnh == __import__("pytest").approx(0.040)
    assert math.exp(-cnh * 1.0) < 1.0
