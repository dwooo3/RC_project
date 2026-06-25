"""Volatility-surface API (Market section).

Built from the live FORTS option chain (option_quotes). For each OTM option we
imply Black-76 vol from the settlement quote (FORTS options are margined →
r = 0), compute the call-delta, then **calibrate SABR (Hagan 2002)** per expiry
to smooth the smile. The table shows delta · quote · fair value (Black-76 at the
calibrated vol) · IV; the surface is the calibrated SABR IV on a delta grid.

Engine models reused: models.black_scholes.black76, models.implied_vol.
implied_vol_black76, models.heston.sabr_vol.
"""

from __future__ import annotations

import datetime as _dt

R = 0.0                                   # margined futures options: no discounting
# Fine call-delta grid for the surface plot (5%-step, 0.05 … 0.95).
_DELTA_BUCKETS = [round(0.05 * i, 2) for i in range(1, 20)]


def list_underlyings(ctx) -> dict:
    db = ctx.market_db
    rows = db.vol_surface_underlyings() if db is not None else []
    return {
        "as_of": (db.latest_vol_snapshot() or "").replace("moex-", "") if db is not None else "",
        "underlyings": [{"code": r["underlying"], "expiries": r["expiries"], "points": r["points"]}
                        for r in rows],
        "count": len(rows),
    }


def _years(expiry: str, today: _dt.date) -> float:
    try:
        return max((_dt.date.fromisoformat(expiry) - today).days, 1) / 365.0
    except ValueError:
        return 0.0


def _call_delta(F: float, K: float, T: float, sigma: float) -> float:
    from models.black_scholes import black76
    return float(black76(F, K, T, R, sigma, "call").delta)


def _calibrate_sabr(F: float, T: float, strikes: list[float], ivs: list[float],
                    beta: float = 1.0) -> dict:
    from models.heston import sabr_vol
    from scipy.optimize import least_squares

    atm = sorted(ivs)[len(ivs) // 2]

    def resid(p):
        a, rho, nu = p
        return [sabr_vol(F, K, T, a, beta, rho, nu) - iv for K, iv in zip(strikes, ivs)]

    try:
        sol = least_squares(resid, [max(atm, 0.05), -0.1, 0.6],
                            bounds=([1e-4, -0.999, 1e-4], [5.0, 0.999, 20.0]), max_nfev=300)
        return {"alpha": float(sol.x[0]), "beta": beta, "rho": float(sol.x[1]), "nu": float(sol.x[2])}
    except Exception:
        return {"alpha": float(atm), "beta": beta, "rho": 0.0, "nu": 1e-4}


def _strike_for_delta(F: float, T: float, sabr: dict, target: float) -> float:
    """Invert call-delta(K) == target via bisection on K (delta ↓ as K ↑)."""
    from models.heston import sabr_vol
    a, b = 0.3 * F, 3.0 * F
    for _ in range(38):
        mid = 0.5 * (a + b)
        iv = sabr_vol(F, mid, T, sabr["alpha"], sabr["beta"], sabr["rho"], sabr["nu"])
        if _call_delta(F, mid, T, iv) > target:
            a = mid
        else:
            b = mid
    return 0.5 * (a + b)


def surface(ctx, underlying: str) -> dict:
    from models.black_scholes import black76
    from models.heston import sabr_vol
    from models.implied_vol import implied_vol_black76

    db = ctx.market_db
    if db is None:
        return {"underlying": underlying, "expiries": [], "deltas": _DELTA_BUCKETS, "surface": []}
    today = _dt.date.today()
    chain = db.get_option_chain(underlying)
    fut = {r["secid"]: r.get("last") for r in db.list_instrument_refs("futures")}

    by_exp: dict[str, list] = {}
    for o in chain:
        by_exp.setdefault(o["expiry"], []).append(o)

    expiries = []
    for exp in sorted(by_exp):
        opts = by_exp[exp]
        T = _years(exp, today)
        F = fut.get(opts[0].get("underlying")) or opts[0].get("central_strike")
        if not F or T <= 0:
            continue
        pts = []
        for o in opts:
            K, typ = o.get("strike"), o.get("opt_type")
            if not K or not ((typ == "C" and K >= F) or (typ == "P" and K < F)):
                continue                                  # OTM wing only
            price = (o.get("last") or 0) or o.get("settle")
            if not price or price <= 0:
                continue
            opt = "call" if typ == "C" else "put"
            try:
                iv = implied_vol_black76(price, F, K, T, R, opt)
            except Exception:
                iv = None
            if not iv or iv <= 1e-3 or iv > 5:
                continue
            d = _call_delta(F, K, T, iv)
            if d < 0.02 or d > 0.98:                      # drop noisy deep wings
                continue
            pts.append({"strike": K, "opt_type": typ, "quote": price, "iv": iv, "delta": d})
        pts.sort(key=lambda x: x["strike"])
        if len(pts) < 3:
            continue

        sabr = _calibrate_sabr(F, T, [p["strike"] for p in pts], [p["iv"] for p in pts])
        for p in pts:
            siv = sabr_vol(F, p["strike"], T, sabr["alpha"], sabr["beta"], sabr["rho"], sabr["nu"])
            opt = "call" if p["opt_type"] == "C" else "put"
            p["sabr_iv"] = siv
            p["fair_value"] = float(black76(F, p["strike"], T, R, siv, opt).price)

        # smooth SABR curve in delta space for the chart
        curve = []
        for i in range(25):
            K = F * (0.70 + i * (0.60 / 24))
            siv = sabr_vol(F, K, T, sabr["alpha"], sabr["beta"], sabr["rho"], sabr["nu"])
            curve.append({"delta": _call_delta(F, K, T, siv), "iv": siv})
        curve.sort(key=lambda x: x["delta"])

        expiries.append({
            "expiry": exp, "t": T, "forward": F,
            "atm_iv": sabr_vol(F, F, T, sabr["alpha"], sabr["beta"], sabr["rho"], sabr["nu"]),
            "sabr": sabr, "points": pts, "sabr_curve": curve,
        })

    # calibrated surface: SABR IV at standard call-deltas, per expiry
    grid = []
    for e in expiries:
        F, T, s = e["forward"], e["t"], e["sabr"]
        cells = []
        for d in _DELTA_BUCKETS:
            K = _strike_for_delta(F, T, s, d)
            cells.append({"delta": d, "iv": sabr_vol(F, K, T, s["alpha"], s["beta"], s["rho"], s["nu"])})
        grid.append({"expiry": e["expiry"], "cells": cells})

    return {"underlying": underlying, "expiries": expiries,
            "deltas": _DELTA_BUCKETS, "surface": grid}
