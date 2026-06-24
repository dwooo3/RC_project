"""Zero-coupon curve bootstrapped from OFZ-PD bond prices.

An independent zero curve built directly from the dirty prices of liquid
fixed-coupon bullet OFZ — a cross-check on MOEX's published КБД (GCURVE), which
is an NSS *fit*. We select one liquid OFZ per maturity bucket (a clean spanning
set), then bootstrap sequentially: for each bond, discount its known coupons on
the curve solved so far and solve the zero rate at its maturity that reprices it,
with zero rates interpolated linearly on the trailing segment.

Stored as curve ``ZCB_OFZ_RUB`` (continuous zeros, DF = exp(-z·t)).
"""

from __future__ import annotations

import datetime as _dt
import math


def _to_date(value):
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def ofz_cashflows(ref: dict, schedule: dict, valuation: _dt.date):
    """Future cashflows per 100 face for a bullet fixed-coupon OFZ.

    Returns (cashflows, maturity_years) or (None, None) if the bond is a
    floater / true amortizer / already-matured (unsuitable for a clean
    bootstrap). A single amortization row is the bullet redemption, not an
    amortization schedule.
    """
    amorts = schedule.get("amortizations") or []
    if len(amorts) > 1:
        return None, None                              # true amortizer — skip
    face = float(ref.get("facevalue") or 1000.0)
    cfs: list[tuple[float, float]] = []
    for c in schedule.get("coupons", []):
        d = _to_date(c.get("coupon_date"))
        if d is None or c.get("value") is None:
            return None, None                          # missing/floating coupon
        t = (d - valuation).days / 365.0
        if t > 1e-6:
            cfs.append((t, float(c["value"]) / face * 100.0))
    mat = _to_date(ref.get("mat_date"))
    if mat is None:
        return None, None
    T = (mat - valuation).days / 365.0
    if T <= 1e-6 or not cfs:
        return None, None
    # redemption: the single amort row if present, else 100 at maturity
    if amorts and amorts[0].get("value") is not None:
        rd = _to_date(amorts[0].get("amort_date")) or mat
        cfs.append(((rd - valuation).days / 365.0, float(amorts[0]["value"]) / face * 100.0))
    else:
        cfs.append((T, 100.0))
    merged: dict[float, float] = {}
    for t, a in cfs:
        if t > 1e-6:
            merged[round(t, 6)] = merged.get(round(t, 6), 0.0) + a
    return sorted(merged.items()), T


def select_spanning(bonds: list[dict], *, min_gap: float = 0.35) -> list[dict]:
    """Greedily keep the most liquid bond per maturity bucket (≥ min_gap apart)."""
    by_mat = sorted(bonds, key=lambda b: b["mat"])
    out: list[dict] = []
    for b in by_mat:
        if out and b["mat"] - out[-1]["mat"] < min_gap:
            if (b.get("volume") or 0) > (out[-1].get("volume") or 0):
                out[-1] = b                            # keep the more liquid one
            continue
        out.append(b)
    return out


def bootstrap_zero(bonds: list[dict], *, max_step: float = 0.02) -> list[tuple[float, float, float]]:
    """Sequential bootstrap → ``[(maturity, zero_continuous, df)]``.

    ``bonds``: ``[{'mat': T, 'dirty': P, 'cfs': [(t, cf)]}]`` (per 100 face).
    ``max_step``: reject a node whose zero jumps more than this (decimal) from
    the previous one — a stale/illiquid quote otherwise poisons the curve.
    """
    from scipy.optimize import brentq

    nodes: list[tuple[float, float]] = []              # (T, zero) solved, sorted

    def z_of(t: float, trial_T: float, trial_z: float) -> float:
        pillars = nodes + [(trial_T, trial_z)]
        if t <= pillars[0][0]:
            return pillars[0][1]
        for (t0, z0), (t1, z1) in zip(pillars, pillars[1:]):
            if t0 <= t <= t1:
                return z0 + (z1 - z0) * (t - t0) / (t1 - t0)
        return pillars[-1][1]

    for b in bonds:
        T, P, cfs = b["mat"], b["dirty"], b["cfs"]
        if nodes and T <= nodes[-1][0] + 1e-6:
            continue                                   # keep maturities increasing

        def price(z, _cfs=cfs, _T=T):
            return sum(cf * math.exp(-z_of(t, _T, z) * t) for t, cf in _cfs)

        try:
            z = brentq(lambda z: price(z) - P, -0.05, 0.60, xtol=1e-7)
        except (ValueError, RuntimeError):
            continue
        if nodes and abs(z - nodes[-1][1]) > max_step:
            continue                                   # outlier — skip noisy bond
        nodes.append((T, z))

    return [(T, z, math.exp(-z * T)) for T, z in nodes]
