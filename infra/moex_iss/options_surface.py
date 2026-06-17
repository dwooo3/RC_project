"""
Consumption layer for the FORTS option vol surfaces, gap follow-up.

The EOD job already implies Black-76 vols across the full FORTS option chain and
stores them in ``vol_points`` / the snapshot's ``{UND}_FORTS`` surfaces
(strike × expiry grids). This module turns those stored grids into the inputs the
calibrators want:

* a single-expiry smile (strikes, ivs) with an ATM-forward estimate, for SABR /
  Heston / local-vol calibration,
* 25Δ risk-reversal / butterfly from the smile, for the Vanna-Volga FX model.

Pure functions over the surface dicts — no network — so they are unit-testable
on synthetic surfaces and reusable by the market-data service.
"""

from __future__ import annotations

from datetime import date

import numpy as np
from scipy.stats import norm


def year_fraction(expiry, valuation_date) -> float:
    """ACT/365 between the valuation date and an ISO expiry string/date."""
    exp = expiry if isinstance(expiry, date) else date.fromisoformat(str(expiry)[:10])
    val = valuation_date if isinstance(valuation_date, date) else date.fromisoformat(str(valuation_date)[:10])
    return max((exp - val).days / 365.0, 1e-6)


def smile_at_expiry(surface: dict, expiry: str | None = None) -> dict:
    """Extract one expiry's smile from a ``{UND}_FORTS`` surface dict.
    expiry=None → the nearest (first) expiry with ≥3 strikes."""
    pts = surface.get("points", [])
    by_exp: dict[str, list[tuple]] = {}
    for p in pts:
        by_exp.setdefault(p["expiry"], []).append((p["strike"], p["iv"]))
    if not by_exp:
        return {}
    if expiry is None:
        cand = [e for e in sorted(by_exp) if len(by_exp[e]) >= 3]
        expiry = cand[0] if cand else sorted(by_exp)[0]
    grid = sorted(by_exp.get(expiry, []))
    strikes = [k for k, _ in grid]
    ivs = [v for _, v in grid]
    return {"expiry": expiry, "strikes": strikes, "ivs": ivs,
            "underlying": surface.get("underlying")}


def clean_smile(strikes, ivs, iv_lo=0.05, iv_hi=1.5, band=0.30, min_pts=5):
    """Drop illiquid/garbage points from a self-implied FORTS smile: keep sane
    IVs (iv_lo..iv_hi) and strikes within ±`band` log-moneyness of the ATM
    forward (the min-IV strike). Two-pass (sanity → forward → moneyness window).
    Returns (strikes, ivs, forward) or the originals if too few survive."""
    s = np.asarray(strikes, float)
    v = np.asarray(ivs, float)
    sane = (v >= iv_lo) & (v <= iv_hi) & np.isfinite(v)
    if sane.sum() < min_pts:
        return list(s), list(v), float(s[np.argmin(v)] if len(s) else 0.0)
    s, v = s[sane], v[sane]
    F0 = s[int(np.argmin(v))]
    near = np.abs(np.log(s / F0)) <= band
    if near.sum() < min_pts:
        near = np.ones_like(s, bool)
    s, v = s[near], v[near]
    order = np.argsort(s)
    s, v = s[order], v[order]
    F = s[int(np.argmin(v))]
    return list(s), list(v), float(F)


def estimate_forward(strikes, ivs) -> float:
    """ATM-forward proxy = the smile vertex (parabola fit around the min-IV
    strike). For a convex smile the minimum sits at the forward."""
    strikes = np.asarray(strikes, float)
    ivs = np.asarray(ivs, float)
    if len(strikes) < 3:
        return float(strikes[len(strikes) // 2])
    i = int(np.argmin(ivs))
    i = min(max(i, 1), len(strikes) - 2)
    x = strikes[i - 1:i + 2]
    y = ivs[i - 1:i + 2]
    a, b, _ = np.polyfit(x, y, 2)
    vertex = -b / (2 * a) if abs(a) > 1e-15 else strikes[i]
    return float(np.clip(vertex, strikes[0], strikes[-1]))


def _iv(strikes, ivs, K):
    return float(np.interp(K, strikes, ivs))


def rr_bf_25delta(smile: dict, T: float, F: float | None = None) -> dict:
    """25Δ ATM / risk-reversal / butterfly from a smile (Black forward deltas).
    A flat smile gives RR≈0, BF≈0; a downward skew gives RR<0."""
    strikes = np.asarray(smile["strikes"], float)
    ivs = np.asarray(smile["ivs"], float)
    F = estimate_forward(strikes, ivs) if F is None else F
    sig_atm = _iv(strikes, ivs, F)

    def call_delta(K):
        s = _iv(strikes, ivs, K)
        d1 = (np.log(F / K) + 0.5 * s**2 * T) / (s * np.sqrt(T))
        return norm.cdf(d1)

    # dense strike grid for delta inversion
    grid = np.linspace(strikes[0], strikes[-1], 400)
    cd = np.array([call_delta(K) for K in grid])
    # 25Δ call: call_delta = 0.25 (K>F); 25Δ put: call_delta = 0.75 (K<F)
    k_25c = float(np.interp(0.25, cd[::-1], grid[::-1]))   # cd decreasing in K
    k_25p = float(np.interp(0.75, cd[::-1], grid[::-1]))
    s_25c = _iv(strikes, ivs, k_25c)
    s_25p = _iv(strikes, ivs, k_25p)
    return {"forward": F, "atm_vol": sig_atm,
            "rr_25": s_25c - s_25p, "bf_25": 0.5 * (s_25c + s_25p) - sig_atm,
            "k_25c": k_25c, "k_25p": k_25p, "sig_25c": s_25c, "sig_25p": s_25p}
