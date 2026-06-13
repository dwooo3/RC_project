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


# ── Snapshot selector (Stage V.1) ────────────────────────

def available_snapshots(db, source: str | None = None) -> list[dict]:
    """
    Stored snapshots for a date dropdown, newest first.
    Returns [{snapshot_id, valuation_date, source, quality}].
    """
    if db is None:
        return []
    rows = db._query(  # noqa: SLF001
        "SELECT snapshot_id, valuation_date, source, quality "
        "FROM market_data_snapshots ORDER BY valuation_date DESC")
    if source:
        rows = [r for r in rows if r["source"] == source]
    return rows


# ── Chart-ready helpers (Stage V.2) ──────────────────────

def curve_overlay_chart(snapshot, curve_ids: list[str] | None = None,
                        tenors=(0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20)) -> list:
    """[(label, xs, ys%) ...] for ChartWidget.plot_curves — curve overlay."""
    ids = curve_ids or list(snapshot.curves.keys())
    series = []
    for cid in ids:
        if cid not in snapshot.curves:
            continue
        c = snapshot.curves[cid]
        tmax = float(max(c.tenors)) if len(getattr(c, "tenors", [])) else max(tenors)
        xs = [T for T in tenors if T <= tmax + 1e-9]
        series.append((cid, xs, [c.rate(T) * 100 for T in xs]))
    return series


def commodity_curve_chart(db, snapshot_id: str) -> list:
    """[(asset, expiry_years, settle) ...] for plot_curves — commodity strips."""
    from datetime import date as _d
    vdate = _snap_date(snapshot_id) or _d.today()
    rows = db.get_commodity_quotes(snapshot_id)
    by_asset: dict[str, list] = {}
    for r in rows:
        try:
            T = (_d.fromisoformat(str(r["expiry"])[:10]) - vdate).days / 365.0
        except (TypeError, ValueError):
            continue
        if r.get("settle"):
            by_asset.setdefault(r["asset"], []).append((T, float(r["settle"])))
    series = []
    for asset, pts in by_asset.items():
        pts.sort()
        series.append((asset, [t for t, _ in pts], [s for _, s in pts]))
    return series


# ── Data Browser: a spreadsheet-style catalogue of every dataset ─────────

def dataset_catalog(db, snapshot) -> list[dict]:
    """
    List the datasets available for the current snapshot with row counts, for a
    dropdown (Excel-sheet style). Only non-empty datasets are listed.
    """
    sid = snapshot.snapshot_id
    out = []

    def add(key, label, count):
        if count:
            out.append({"key": key, "label": label, "count": count})

    add("curves", "Yield Curves", len(snapshot.curves))
    add("fx", "FX Rates", len(snapshot.fx_rates))
    add("bonds", "Bonds (quotes)", len(db.get_bond_quotes(sid)) if db else 0)
    add("equities", "Equities (spot)", len(db.get_equity_quotes(sid)) if db else 0)
    add("vol", "Vol Surfaces", len(vol_underlyings(db, sid)) if db else len(snapshot.vol_surfaces))
    add("commodity", "Commodity Futures",
        len(db.get_commodity_quotes(sid)) if db else 0)
    add("dividends", "Dividends", _dividends_count(db) if db else 0)
    add("history", "Factor History",
        _history_factor_count(db) if db else 0)
    add("hazard", "Hazard Curves",
        sum(1 for v in snapshot.credit_curves.values() if hasattr(v, "hazards")))
    return out


def dataset_table(db, snapshot, key: str, limit: int = 200) -> dict:
    """
    Render-ready {title, columns, rows} for one dataset key — the body the Data
    Browser shows when a sheet is picked from the dropdown.
    """
    sid = snapshot.snapshot_id
    if key == "curves":
        t = curve_table(snapshot, list(snapshot.curves.keys()))
        cols = ["Tenor (y)"] + t["columns"]
        rows = [[r[0]] + [("" if v is None else f"{v:.3f}%") for v in r[1:]]
                for r in t["rows"]]
        return {"title": "Yield Curves (zero rates)", "columns": cols, "rows": rows}

    if key == "fx":
        return {"title": "FX Rates", "columns": ["Pair", "Rate"],
                "rows": [[p, f"{r:.4f}"] for p, r in sorted(snapshot.fx_rates.items())]}

    if key == "bonds":
        rows = sorted(db.get_bond_quotes(sid), key=lambda q: q.get("volume") or 0,
                      reverse=True)[:limit]
        return {"title": f"Bond Quotes (top {len(rows)} by volume)",
                "columns": ["SECID", "Board", "Clean", "YTM %", "Volume"],
                "rows": [[q["secid"], q.get("board", ""),
                          _fmt(q.get("clean_price")),
                          _pct(q.get("ytm")), _fmt(q.get("volume"), 0)]
                         for q in rows]}

    if key == "equities":
        rows = sorted(db.get_equity_quotes(sid), key=lambda q: q.get("volume") or 0,
                      reverse=True)[:limit]
        out = []
        for q in rows:
            last, prev = q.get("last"), q.get("prevprice")
            chg = (last / prev - 1) * 100 if last and prev else None
            out.append([q["secid"], _fmt(last), _fmt(prev),
                        (f"{chg:+.2f}%" if chg is not None else ""),
                        _fmt(q.get("volume"), 0)])
        return {"title": f"Equity Spot (top {len(out)} by volume)",
                "columns": ["SECID", "Last", "Prev", "Chg", "Volume"], "rows": out}

    if key == "vol":
        rows = []
        for und in vol_underlyings(db, sid):
            sm = vol_smile_slices(db, sid, und)
            n = sum(s["n_points"] for s in sm["slices"])
            exps = len(sm["slices"])
            atm = sm["slices"][0]["atm_vol"] if sm["slices"] else None
            rows.append([und, exps, n, (f"{atm:.2f}%" if atm else "")])
        rows.sort(key=lambda r: r[2], reverse=True)
        return {"title": "Vol Surfaces (self-implied)",
                "columns": ["Underlying", "Expiries", "Points", "Front ATM"],
                "rows": rows}

    if key == "commodity":
        rows = [[q["asset"], str(q.get("expiry", ""))[:10], _fmt(q.get("settle")),
                 _fmt(q.get("open_interest"), 0)]
                for q in db.get_commodity_quotes(sid)]
        return {"title": "Commodity Futures (settlement strip)",
                "columns": ["Asset", "Expiry", "Settle", "Open Interest"], "rows": rows}

    if key == "dividends":
        rows = []
        for secid in _dividend_secids(db)[:limit]:
            divs = db.get_dividends(secid)
            if divs:
                last = divs[-1]
                rows.append([secid, last["registry_date"], _fmt(last.get("value")),
                             last.get("currency", ""), len(divs)])
        rows.sort(key=lambda r: r[1], reverse=True)
        return {"title": "Dividends (latest per name)",
                "columns": ["SECID", "Registry date", "Value", "Ccy", "History"],
                "rows": rows}

    if key == "history":
        rows = db._query(  # noqa: SLF001
            "SELECT factor_id, kind, COUNT(*) n, MIN(dt) lo, MAX(dt) hi "
            "FROM time_series GROUP BY factor_id, kind ORDER BY n DESC LIMIT ?",
            (limit,)) if db else []
        return {"title": "Factor History (time series)",
                "columns": ["Factor", "Kind", "Points", "From", "To"],
                "rows": [[r["factor_id"], r["kind"], r["n"], r["lo"], r["hi"]]
                         for r in rows]}

    if key == "hazard":
        rows = []
        for cid, c in snapshot.credit_curves.items():
            if hasattr(c, "hazards"):
                rows.append([cid, f"{c.hazard(5.0) * 100:.2f}%",
                             f"{c.survival(5.0):.3f}", f"{c.recovery:.0%}"])
        return {"title": "Hazard Curves", "columns":
                ["Curve", "λ(5y)", "Q(5y)", "Recovery"], "rows": rows}

    return {"title": key, "columns": [], "rows": []}


def _fmt(v, digits: int = 2) -> str:
    if v in (None, ""):
        return ""
    return f"{float(v):,.{digits}f}"


def _pct(v) -> str:
    return "" if v in (None, "") else f"{float(v) * 100:.2f}"


def _dividends_count(db) -> int:
    try:
        return db._query("SELECT COUNT(DISTINCT secid) c FROM dividends")[0]["c"]
    except Exception:
        return 0


def _dividend_secids(db) -> list[str]:
    try:
        return [r["secid"] for r in db._query(
            "SELECT DISTINCT secid FROM dividends ORDER BY secid")]
    except Exception:
        return []


def _history_factor_count(db) -> int:
    try:
        return db._query("SELECT COUNT(DISTINCT factor_id) c FROM time_series")[0]["c"]
    except Exception:
        return 0


def _snap_date(snapshot_id: str) -> date | None:
    try:
        return date.fromisoformat(snapshot_id.split("-", 1)[1])
    except (IndexError, ValueError):
        return None
