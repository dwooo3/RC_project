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
import io
import math

R = 0.0                                   # margined futures options: no discounting
# Fine call-delta grid for the surface plot (5%-step, 0.05 … 0.95).
_DELTA_BUCKETS = [round(0.05 * i, 2) for i in range(1, 20)]

# In-process surface cache keyed by (underlying, vol-snapshot). The surface is
# expensive (per-option IV + SABR fit + delta inversion) but static until the
# next ingest, so the first open computes and the rest are instant.
_CACHE: dict = {}
_PNG_CACHE: dict = {}                      # (underlying, snapshot) → rendered PNG bytes


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
                    weights: list[float], beta: float = 1.0) -> dict:
    """Liquidity-weighted SABR fit with a tenor-scaled vol-of-vol cap.

    Weights ∝ √OI so liquid strikes anchor the fit and thin wings can't drag it.
    ν (vol-of-vol) is bounded by ~1.5/√T: short-dated smiles may be very convex,
    but a 1y smile with ν=20 only blows the wings up — this keeps far expiries sane.
    """
    from models.heston import sabr_vol
    from scipy.optimize import least_squares

    finite = [v for v in ivs if math.isfinite(v)]
    atm = sorted(finite)[len(finite) // 2] if finite else 0.2
    nu_max = min(20.0, max(0.8, 1.2 / math.sqrt(max(T, 1e-3))))
    w = [math.sqrt(max(x, 0.0) + 1.0) for x in weights]
    fallback = {"alpha": float(atm), "beta": beta, "rho": 0.0, "nu": 0.3}

    def resid(p):
        a, rho, nu = p
        out = []
        for K, iv, wi in zip(strikes, ivs, w):
            try:
                m = sabr_vol(F, K, T, a, beta, rho, nu)
            except Exception:
                m = None
            out.append((m - iv) * wi if (m is not None and math.isfinite(m)) else 1e3)
        return out

    try:
        sol = least_squares(resid, [max(atm, 0.05), -0.1, min(0.6, nu_max)],
                            bounds=([1e-4, -0.999, 1e-4], [5.0, 0.999, nu_max]), max_nfev=400)
        if all(math.isfinite(x) for x in sol.x):
            return {"alpha": float(sol.x[0]), "beta": beta, "rho": float(sol.x[1]), "nu": float(sol.x[2])}
        return fallback
    except Exception:
        return fallback


def _strike_for_delta(F: float, T: float, sabr: dict, target: float) -> float:
    """Invert call-delta(K) == target via bisection on K (delta ↓ as K ↑)."""
    from models.heston import sabr_vol
    a, b = 0.3 * F, 3.0 * F
    for _ in range(24):
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
    cache_key = (underlying, db.latest_vol_snapshot() or "")
    if cache_key in _CACHE:
        return _CACHE[cache_key]
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
            # NaN slips through plain comparisons (NaN<=x is False), so test finiteness.
            if iv is None or not math.isfinite(iv) or iv <= 1e-3 or iv > 5:
                continue
            d = _call_delta(F, K, T, iv)
            if not math.isfinite(d) or d < 0.02 or d > 0.98:   # drop noisy deep wings
                continue
            pts.append({"strike": K, "opt_type": typ, "quote": price, "iv": iv,
                        "delta": d, "oi": o.get("oi") or 0.0})
        pts.sort(key=lambda x: x["strike"])
        if len(pts) < 3:
            continue

        sabr = _calibrate_sabr(F, T, [p["strike"] for p in pts], [p["iv"] for p in pts],
                               [p["oi"] for p in pts])
        sq = n = 0
        for p in pts:
            siv = sabr_vol(F, p["strike"], T, sabr["alpha"], sabr["beta"], sabr["rho"], sabr["nu"])
            opt = "call" if p["opt_type"] == "C" else "put"
            p["sabr_iv"] = siv
            p["fair_value"] = float(black76(F, p["strike"], T, R, siv, opt).price)
            if math.isfinite(siv):
                sq += (siv - p["iv"]) ** 2
                n += 1
        rmse = math.sqrt(sq / n) if n else None

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
            "sabr": sabr, "rmse": rmse, "n_points": len(pts),
            "points": pts, "sabr_curve": curve,
        })

    # calibrated surface: SABR IV at standard call-deltas, per expiry
    grid = []
    for e in expiries:
        F, T, s = e["forward"], e["t"], e["sabr"]
        cells = []
        for d in _DELTA_BUCKETS:
            K = _strike_for_delta(F, T, s, d)
            cells.append({"delta": d, "iv": sabr_vol(F, K, T, s["alpha"], s["beta"], s["rho"], s["nu"])})
        grid.append({"expiry": e["expiry"], "t": T, "cells": cells})

    rmses = [e["rmse"] for e in expiries if e.get("rmse") is not None]
    diagnostics = {
        "fit_model": "SABR (β=1, OI-weighted)",
        "n_expiries": len(expiries),
        "n_points": sum(e["n_points"] for e in expiries),
        "rmse": (sum(rmses) / len(rmses)) if rmses else None,   # mean across expiries
    }
    result = {"underlying": underlying, "expiries": expiries, "deltas": _DELTA_BUCKETS,
              "surface": grid, "diagnostics": diagnostics}
    if len(_CACHE) > 40:
        _CACHE.clear()
    _CACHE[cache_key] = result
    return result


# FX underlyings whose FORTS options give an OTC-style ATM/25Δ-RR/25Δ-BF quote
# (Si=USD/RUB, CNY=CNY/RUB, Eu=EUR/RUB, ED=EUR/USD). Other underlyings have no
# OTC feed, so their OTC section stays empty.
_FX_OTC = {"Si", "CNY", "Eu", "ED"}


def otc_surface(ctx, underlying: str) -> dict:
    """OTC FX vol quoted the desk way — ATM / 25Δ risk-reversal / 25Δ butterfly per
    tenor — derived from the FORTS FX option smiles (that's how OTC FX vol is
    quoted). Non-FX underlyings return is_fx=False (no OTC feed)."""
    if underlying not in _FX_OTC:
        return {"underlying": underlying, "is_fx": False, "tenors": []}
    svc = ctx.market
    db = ctx.market_db
    snap = ctx.snapshot
    if db is None:
        return {"underlying": underlying, "is_fx": True, "tenors": []}
    from infra.moex_iss.options_surface import rr_bf_25delta

    expiries = sorted({o["expiry"] for o in db.get_option_chain(underlying) if o.get("expiry")})
    tenors = []
    for exp in expiries:
        sm = svc.get_option_smile(underlying, exp, snap)
        if not sm or not sm.get("forward"):
            continue
        try:
            rb = rr_bf_25delta(sm, sm["T"], sm["forward"])
        except Exception:
            continue
        if rb.get("atm_vol") is None:
            continue
        tenors.append({
            "expiry": exp, "t": sm["T"], "forward": sm["forward"],
            "atm": rb.get("atm_vol"), "rr25": rb.get("rr_25"), "bf25": rb.get("bf_25"),
            "sig25c": rb.get("sig_25c"), "sig25p": rb.get("sig_25p"),
        })
    tenors.sort(key=lambda x: x["t"])
    return {"underlying": underlying, "is_fx": True, "tenors": tenors}


def surface_png(ctx, underlying: str) -> bytes | None:
    """Render the calibrated SABR surface as a static 3-axis chart (matplotlib
    mplot3d): X = call delta, Y = time to expiry, Z = implied vol %. Returns PNG
    bytes (transparent, dark-theme tick/labels) for display in the app, or None
    when there isn't enough of a grid to draw.
    """
    db = ctx.market_db
    snap = (db.latest_vol_snapshot() or "") if db is not None else ""
    cache_key = (underlying, snap)
    if cache_key in _PNG_CACHE:
        return _PNG_CACHE[cache_key]

    data = surface(ctx, underlying)
    rows = [r for r in data["surface"] if r.get("t")]
    deltas = data["deltas"]
    if len(rows) < 2 or len(deltas) < 2:
        return None
    rows.sort(key=lambda r: r["t"])

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.ticker import FuncFormatter

    fg = "#9aa0aa"                                       # tick / label colour
    X = np.array(deltas, dtype=float)                    # call delta 0..1
    Y = np.array([r["t"] for r in rows], dtype=float)    # years to expiry
    Z = np.array([[((c.get("iv") or np.nan) * 100.0) for c in r["cells"]] for r in rows])
    # fill the odd NaN cell by row-neighbour so plot_surface stays watertight
    for i in range(Z.shape[0]):
        row = Z[i]
        if np.isnan(row).any() and not np.isnan(row).all():
            idx = np.arange(len(row))
            good = ~np.isnan(row)
            row[~good] = np.interp(idx[~good], idx[good], row[good])
    # Per-expiry SABR slices are fitted independently → adjacent expiries can
    # disagree at the wings, leaving single-cell spikes. A light Gaussian smooth
    # (display only — table/smile stay raw) tames them into a clean surface.
    try:
        from scipy.ndimage import gaussian_filter
        if Z.shape[0] >= 3:
            Z = gaussian_filter(Z, sigma=(0.7, 0.8), mode="nearest")
    except Exception:
        pass
    Xg, Yg = np.meshgrid(X, Y)

    fig = plt.figure(figsize=(8.8, 5.6), dpi=130)
    fig.patch.set_alpha(0.0)
    ax = fig.add_subplot(111, projection="3d")
    ax.patch.set_alpha(0.0)
    ax.plot_surface(Xg, Yg, Z, cmap="turbo", edgecolor="black", linewidth=0.25,
                    antialiased=True, rstride=1, cstride=1, alpha=0.96)

    ax.set_xlabel("Δ call", color=fg, labelpad=10, fontsize=10)
    ax.set_ylabel("Срок, лет", color=fg, labelpad=12, fontsize=10)
    ax.set_zlabel("IV, %", color=fg, labelpad=8, fontsize=10)
    ax.set_title(f"{underlying} · поверхность волатильности (SABR)", color="#d6d9df",
                 fontsize=12, pad=12)
    ax.zaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.view_init(elev=26, azim=-56)

    # dark theme: transparent panes, faint light grid, light ticks
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.set_pane_color((1, 1, 1, 0.0))
        axis.pane.set_edgecolor((1, 1, 1, 0.10))
        axis._axinfo["grid"]["color"] = (1, 1, 1, 0.12)
        axis._axinfo["grid"]["linewidth"] = 0.6
    ax.tick_params(colors=fg, labelsize=8)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    png = buf.getvalue()

    if len(_PNG_CACHE) > 40:
        _PNG_CACHE.clear()
    _PNG_CACHE[cache_key] = png
    return png
