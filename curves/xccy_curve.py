"""
Cross-currency (XCCY) basis curve bootstrap, Master-plan M3c.

A book collateralised in the *domestic* currency must discount its *foreign*
cashflows on a basis-adjusted curve P_x, not the foreign OIS curve P_f — the gap
is the cross-currency basis. We bootstrap P_x from par constant-notional XCCY
basis swaps: foreign-OIS-float + basis b versus domestic-OIS-float, principals
exchanged at start and maturity.

Each currency's own float leg, discounted on its own OIS curve, is worth par, so
the par condition isolates the foreign discount curve P_x. Each quoted tenor's
zero rate is solved (1-D) so that swap's par NPV is zero, with intermediate
coupon dates interpolated from the nodes already bootstrapped — the standard
sequential bootstrap, so the quoted swaps reprice exactly.

Identities (tested): zero basis ⇒ P_x ≡ P_f; the input swaps reprice to par
under an independent cashflow NPV; a positive foreign-leg basis lowers P_x; and
covered-interest-parity FX forwards F(T) = S0·P_x(T)/P_dom(T) come out monotone.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

from curves.yield_curve import YieldCurve


def _grid(maturity: float, freq: int):
    n = int(round(maturity * freq))
    dt = 1.0 / freq
    return np.array([i * dt for i in range(n + 1)])        # T_0=0 .. T_n


class _ZeroCurve:
    """Lightweight discount shim (linear zero-rate interp, flat extrapolation)
    used inside the bootstrap solver to avoid full-curve validation per probe."""
    def __init__(self, t, z):
        self.t, self.z = np.asarray(t, float), np.asarray(z, float)

    def discount(self, T):
        return float(np.exp(-np.interp(T, self.t, self.z) * T))


def bootstrap_xccy_curve(dom_curve, for_curve, fx_spot: float,
                         tenors: list[float], basis_bps: list[float],
                         freq: int = 4, label: str = "xccy") -> YieldCurve:
    """Bootstrap the foreign basis-adjusted discount curve P_x.

    dom_curve / for_curve are the two OIS curves; basis_bps is the XCCY basis
    (added to the foreign float leg) per `tenors`, in basis points (one flat
    spread per swap). Each tenor's zero rate is solved so that par swap prices
    to zero; intermediate coupon dates interpolate the nodes bootstrapped so far.
    """
    order = np.argsort(tenors)
    tenors = [float(tenors[i]) for i in order]
    basis_bps = [float(basis_bps[i]) for i in order]
    # short anchor: XCCY basis ≈ 0 at the very front, so P_x ≈ P_f there. Keeps
    # ≥2 nodes for linear interpolation of intermediate coupon dates.
    anchor_t = min(tenors) / (freq * 4)
    nodes_t, nodes_z = [anchor_t], [for_curve.rate(anchor_t)]
    for T, b in zip(tenors, basis_bps):
        z0 = for_curve.rate(T)                             # foreign zero as guess

        def npv(z):
            xc = _ZeroCurve(nodes_t + [T], nodes_z + [z])
            return xccy_basis_swap_npv(dom_curve, for_curve, xc, fx_spot, T, b, freq)

        z = brentq(npv, z0 - 0.2, z0 + 0.2, xtol=1e-14, rtol=1e-15)
        nodes_t.append(T)
        nodes_z.append(z)
    return YieldCurve(nodes_t, nodes_z, label=label, source=for_curve.source,
                      interp="linear")


def xccy_basis_swap_npv(dom_curve, for_curve, xccy_curve, fx_spot: float,
                        maturity: float, basis_bps: float, freq: int = 4,
                        dom_notional: float = 1.0) -> float:
    """Independent NPV (domestic ccy) of a constant-notional XCCY basis swap:
    receive domestic OIS float, pay foreign OIS float + basis. Used to verify
    the bootstrap (par swaps must price to ~0)."""
    b = basis_bps / 1e4
    grid = _grid(maturity, freq)
    for_notional = dom_notional / fx_spot

    dom_pv = 0.0                                           # receive dom float
    for i in range(1, len(grid)):
        ti, tprev = grid[i], grid[i - 1]
        fwd = dom_curve.discount(tprev) / dom_curve.discount(ti) - 1.0
        dom_pv += fwd * dom_curve.discount(ti) * dom_notional
    dom_pv += -dom_notional + dom_notional * dom_curve.discount(maturity)

    for_pv = 0.0                                           # pay for float+basis
    for i in range(1, len(grid)):
        ti, tprev = grid[i], grid[i - 1]
        fwd = for_curve.discount(tprev) / for_curve.discount(ti) - 1.0
        tau = ti - tprev
        for_pv += (fwd + b * tau) * xccy_curve.discount(ti) * for_notional
    for_pv += -for_notional + for_notional * xccy_curve.discount(maturity)

    return dom_pv - fx_spot * for_pv


def implied_fx_forwards(dom_curve, xccy_curve, fx_spot: float,
                        tenors: list[float]) -> dict:
    """Covered-interest-parity FX forwards (domestic per foreign) from the
    bootstrapped curves: value-in-domestic of 1 foreign at T is S0·P_x(T), which
    must equal P_dom(T)·F(T), hence F(T) = S0·P_x(T)/P_dom(T)."""
    return {T: fx_spot * xccy_curve.discount(T) / dom_curve.discount(T)
            for T in tenors}
