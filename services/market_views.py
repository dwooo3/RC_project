"""
Market-data view models (Stage III visualization).

Pure functions that turn snapshots / DB rows into render-ready structures
(tables, series, smile slices with SVI fits, factor correlations). No Qt — so
every view is unit-tested headless, and the Qt panels stay thin wrappers.
Lives in services/ so it may import curves/risk freely while the UI panels keep
to the service boundary.
"""

from __future__ import annotations

from datetime import date

import numpy as np

DEFAULT_TENORS = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0)


# ── Yield curves ─────────────────────────────────────────

def curve_table(snapshot, curve_ids: list[str],
                tenors=DEFAULT_TENORS) -> dict:
    """
    Tenor × curve grid of zero rates (%) for the curves present in the snapshot.
    Returns {tenors, columns: [curve_id...], rows: [[tenor, r1%, r2%, ...]]}.
    """
    present = [c for c in curve_ids if c in snapshot.curves]
    rows = []
    for T in tenors:
        row = [T]
        for cid in present:
            try:
                row.append(round(snapshot.curves[cid].rate(T) * 100, 3))
            except Exception:
                row.append(None)
        rows.append(row)
    return {"tenors": list(tenors), "columns": present, "rows": rows}


def curve_history_series(db, factor_id: str) -> dict:
    """Time series of a curve tenor (e.g. 'KBD:5Y') as {dates, values%}."""
    rows = db.get_time_series(factor_id, "rate")
    return {
        "factor_id": factor_id,
        "dates": [r["dt"] for r in rows],
        "values": [r["value"] * 100 for r in rows],   # decimal -> percent
    }


def breakeven_term_structure(snapshot, nominal_id="GCURVE_RUB",
                             real_id="REALCURVE_OFZIN",
                             tenors=(1, 2, 3, 5, 7, 10)) -> dict:
    """Market breakeven inflation (%) = nominal − real, where both curves exist."""
    if nominal_id not in snapshot.curves or real_id not in snapshot.curves:
        return {"available": False, "tenors": [], "breakeven": [],
                "nominal": [], "real": []}
    from curves.inflation import breakeven_rate
    nom, real = snapshot.curves[nominal_id], snapshot.curves[real_id]
    real_max = float(np.max(real.tenors))
    ts = [T for T in tenors if T <= real_max]
    return {
        "available": True,
        "tenors": ts,
        "breakeven": [round(breakeven_rate(nom, real, T) * 100, 3) for T in ts],
        "nominal": [round(nom.rate(T) * 100, 3) for T in ts],
        "real": [round(real.rate(T) * 100, 3) for T in ts],
    }


# ── Vol surface (smile slices + SVI) ─────────────────────

def vol_smile_slices(db, snapshot_id: str, underlying: str,
                     valuation_date: date | None = None,
                     min_points: int = 5) -> dict:
    """
    Per-expiry implied-vol smiles for an underlying, each with an SVI fit when
    enough strikes are present. Forward F per expiry is taken as the strike of
    the lowest-IV point (the smile minimum ~ ATM-forward).
    Returns {underlying, slices: [{expiry, strikes, vols%, svi:{k%, fit_vols%,
    rmse} | None}]}.
    """
    from risk.vol_surface import fit_svi_slice

    valuation_date = valuation_date or _snap_date(snapshot_id)
    pts = [p for p in db.get_vol_points(snapshot_id) if p["underlying"] == underlying]
    by_expiry: dict[str, list] = {}
    for p in pts:
        by_expiry.setdefault(str(p["expiry"])[:10], []).append(p)

    slices = []
    for expiry in sorted(by_expiry):
        rows = sorted(by_expiry[expiry], key=lambda r: r["strike"])
        strikes = np.array([r["strike"] for r in rows], dtype=float)
        vols = np.array([r["iv"] for r in rows], dtype=float)
        F = float(strikes[int(np.argmin(vols))])           # smile-min ~ forward
        svi = None
        if len(strikes) >= min_points and valuation_date is not None:
            T = max((date.fromisoformat(expiry) - valuation_date).days / 365.0, 1e-4)
            try:
                fit = fit_svi_slice(strikes, vols, T, F)
                svi = {
                    "log_moneyness": [round(float(np.log(k / F)), 4) for k in strikes],
                    "fit_vols": [round(float(v) * 100, 3) for v in fit["fit_vols"]],
                    "rmse": round(float(fit["rmse"]) * 100, 4),
                }
            except Exception:
                svi = None
        slices.append({
            "expiry": expiry,
            "forward": F,
            "strikes": [float(k) for k in strikes],
            "vols": [round(float(v) * 100, 3) for v in vols],
            "atm_vol": round(float(vols.min()) * 100, 3),
            "svi": svi,
            "n_points": len(strikes),
        })
    return {"underlying": underlying, "slices": slices}


def atm_term_structure(smile: dict) -> dict:
    """ATM vol per expiry from vol_smile_slices output."""
    return {
        "expiries": [s["expiry"] for s in smile["slices"]],
        "atm_vols": [s["atm_vol"] for s in smile["slices"]],
    }


def vol_underlyings(db, snapshot_id: str) -> list[str]:
    return sorted({p["underlying"] for p in db.get_vol_points(snapshot_id)})


# ── Factor series + correlations (VaR inputs) ────────────

def factor_series(mds, factors: list[str], kind: str = "price",
                  method: str = "log") -> dict:
    """
    Aligned returns for a set of factors plus their correlation matrix —
    the inputs a factor VaR / diversification view needs.
    Returns {factors, n_obs, ann_vol%, correlation, last_values}.
    """
    series = {}
    for f in factors:
        try:
            r = mds.get_returns(f, kind=kind, method=method)
            if r.size:
                series[f] = r
        except Exception:
            continue
    if not series:
        return {"factors": [], "n_obs": 0, "ann_vol": {}, "correlation": [],
                "aligned_factors": []}
    n = min(len(r) for r in series.values())
    names = sorted(series)
    mat = np.array([series[f][-n:] for f in names])        # align on the tail
    ann_vol = {f: round(float(series[f].std() * np.sqrt(252) * 100), 2) for f in names}
    corr = np.corrcoef(mat) if len(names) > 1 and n > 1 else np.array([[1.0]])
    return {
        "factors": names,
        "aligned_factors": names,
        "n_obs": int(n),
        "ann_vol": ann_vol,
        "correlation": np.round(corr, 3).tolist(),
    }


# ── Data health (ingest history + calendar gaps) ─────────

def ingest_history(db, limit: int = 30) -> list[dict]:
    """Recent ingest_log rows for the data-health panel."""
    return db.recent_ingest_log(limit)


def snapshot_calendar(db, lookback_days: int = 30,
                      today: date | None = None) -> dict:
    """
    Which business days in the lookback window have a stored MOEX snapshot —
    surfaces gaps the daily job should backfill.
    """
    today = today or date.today()
    from datetime import timedelta
    have = set()
    for d in range(lookback_days + 1):
        day = today - timedelta(days=d)
        if day.weekday() >= 5:
            continue
        sid = f"moex-{day.isoformat()}"
        if db.get_snapshot_meta(sid):
            have.add(day.isoformat())
    business = []
    for d in range(lookback_days + 1):
        day = today - timedelta(days=d)
        if day.weekday() < 5:
            business.append(day.isoformat())
    missing = [d for d in business if d not in have]
    return {"business_days": len(business), "present": len(have),
            "missing": sorted(missing), "coverage_pct": round(
                100 * len(have) / max(len(business), 1), 1)}


def _snap_date(snapshot_id: str) -> date | None:
    try:
        return date.fromisoformat(snapshot_id.split("-", 1)[1])
    except (IndexError, ValueError):
        return None
