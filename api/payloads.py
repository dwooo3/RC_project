"""Per-screen payload builders.

Each function assembles one screen's data from the existing services/view layer
and returns a plain dict; the server applies `jsonable` before sending. Heavier
or optional pieces are guarded so one failure degrades that section, not the
whole screen.
"""

from __future__ import annotations

from api.instruments import CURVE_LABELS
from services import analytics_views as av
from services import market_views as mv

_SPOT_SHOCKS = [-0.10, -0.05, 0.0, 0.05, 0.10]
_VOL_SHOCKS = [-0.05, -0.02, 0.0, 0.02, 0.05]
_CURVE_TENORS = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0]


def _safe(fn, default):
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": str(exc), **({} if not isinstance(default, dict) else default)} \
            if isinstance(default, dict) else default


def snapshot_meta(ctx) -> dict:
    snap = ctx.snapshot
    source = snap.source
    return {
        "snapshot_id": snap.snapshot_id,
        "valuation_date": str(getattr(snap, "valuation_date", "") or ""),
        "source": source.value if hasattr(source, "value") else str(source),
        "quality": getattr(snap, "quality", ""),
        "is_live": ctx.is_live(),
        "is_demo": getattr(snap, "is_demo", True),
    }


def market(ctx) -> dict:
    overview = _safe(lambda: mv.market_overview(ctx.market_db, ctx.snapshot), {})
    curve = _safe(lambda: _ofz_curve(ctx), [])
    return {"snapshot": snapshot_meta(ctx), "overview": overview, "curve": curve}


def _ofz_curve(ctx) -> list:
    """Sample the live OFZ zero curve for a chartable term structure."""
    tenors = [0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20]
    curve = ctx.market.ofz_curve()
    points = []
    for t in tenors:
        rate = None
        for attr in ("zero_rate", "rate", "spot_rate"):
            fn = getattr(curve, attr, None)
            if callable(fn):
                try:
                    rate = float(fn(t))
                    break
                except Exception:
                    continue
        if rate is not None:
            points.append({"tenor": t, "rate": rate})
    return points


def _curve_series(d) -> list:
    return [{"t": float(t), "rate": float(r)} for t, r in sorted(d.items())]


def curves(ctx) -> dict:
    """Sampled zero / par / forward term structures for every snapshot curve."""
    out = []
    for cid in ctx.snapshot.curves:
        try:
            c = ctx.market.get_curve(cid, ctx.snapshot)
            out.append({
                "id": cid,
                "label": CURVE_LABELS.get(cid, cid),
                "zero": _curve_series(c.zero_curve(_CURVE_TENORS)),
                "par": _curve_series(c.par_curve(_CURVE_TENORS)),
                "forward": _curve_series(c.forward_curve(_CURVE_TENORS)),
            })
        except Exception:
            continue
    return {"curves": out}


def portfolio(ctx) -> dict:
    ps = ctx.portfolio
    val = ps.value()
    return {
        "snapshot": snapshot_meta(ctx),
        "valuation": {
            "portfolio_id": val.portfolio_id,
            "base_currency": val.base_currency,
            "total_market_value": val.total_market_value,
            "snapshot_id": val.market_data_snapshot_id,
            "warnings": list(val.warnings or []),
            "n_positions": len(val.positions),
        },
        "positions": _safe(ps.positions_table, []),
        "aggregate": _safe(ps.aggregate, {}),
    }


def risk(ctx) -> dict:
    ps = ctx.portfolio
    return {
        "var_99": ctx.parametric_var(0.99, 1),
        "var_95": ctx.parametric_var(0.95, 1),
        "var_99_10d": ctx.parametric_var(0.99, 10),
        "decomposition": _safe(lambda: av.risk_decomposition(ps), {}),
        "what_if_grid": _safe(lambda: av.what_if_grid(ps, _SPOT_SHOCKS, _VOL_SHOCKS), {}),
    }


def governance(ctx) -> dict:
    gs = ctx.governance
    return {
        "counts": _safe(gs.status_counts, {}),
        "models": _safe(gs.list_models, []),
        "validation": _safe(gs.validation_status, []),
        "limitations": _safe(gs.limitations_report, []),
        "audit": _safe(lambda: gs.audit_trail()[:40], []),
    }


def analytics(ctx) -> dict:
    ps = ctx.portfolio
    return {
        "decomposition": _safe(lambda: av.risk_decomposition(ps), {}),
        "scenarios": _safe(lambda: av.scenario_library(ps), {}),
        "what_if_grid": _safe(lambda: av.what_if_grid(ps, _SPOT_SHOCKS, _VOL_SHOCKS), {}),
    }


def dashboard(ctx) -> dict:
    ps = ctx.portfolio
    val = ps.value()
    overview = _safe(lambda: mv.market_overview(ctx.market_db, ctx.snapshot), {})
    var = ctx.parametric_var(0.99, 1)
    counts = _safe(ctx.governance.status_counts, {})
    return {
        "snapshot": snapshot_meta(ctx),
        "portfolio": {
            "total_market_value": val.total_market_value,
            "base_currency": val.base_currency,
            "n_positions": len(val.positions),
        },
        "risk": {
            "var": var["var"],
            "expected_shortfall": var["expected_shortfall"],
            "confidence": var["confidence"],
            "horizon_days": var["horizon_days"],
        },
        "governance": {"counts": counts, "total": sum(counts.values()) if counts else 0},
        "market": {
            "key_rate": overview.get("key_rate"),
            "kbd": overview.get("kbd", {}),
            "fx": overview.get("fx", {}),
            "key_vols": overview.get("key_vols", {}),
            "top_movers": overview.get("top_movers", [])[:5],
            "most_active": overview.get("most_active", [])[:5],
        },
    }
