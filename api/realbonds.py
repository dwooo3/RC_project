"""Real-bond repricing feed.

Lists tradeable bonds from the market-data DB (MOEX ISS feed) and reprices a
selected one against a chosen discount curve: theoretical vs market price, the
Z-spread that matches the market quote, G-spread, and a parallel-shift scenario.
Cashflows are reconstructed from the real coupon/amortization schedule.
"""

from __future__ import annotations

import datetime as _dt

from scipy.optimize import brentq

from api.instruments import CURVE_LABELS
from instruments.fixed_income_analytics import bond_yield


def _to_date(value):
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _snapshot_meta(ctx) -> dict:
    snap = ctx.snapshot
    return {"snapshot_id": snap.snapshot_id,
            "valuation_date": str(getattr(snap, "valuation_date", "") or ""),
            "is_live": ctx.is_live()}


def list_real_bonds(ctx, board=None, search=None, limit=300) -> dict:
    db = ctx.market_db
    if db is None:
        return {"snapshot": _snapshot_meta(ctx), "bonds": [], "boards": [], "count": 0}
    all_rows = db.get_real_bonds(ctx.snapshot.snapshot_id, board=None, limit=None)
    boards = sorted({r["board"] for r in all_rows if r.get("board")})
    rows = [r for r in all_rows if r.get("board") == board] if board else all_rows
    needle = (search or "").lower().strip()
    bonds = []
    for r in rows:
        if needle:
            hay = " ".join(str(r.get(k, "") or "") for k in ("secid", "isin", "issuer")).lower()
            if needle not in hay:
                continue
        bonds.append({
            "secid": r["secid"], "isin": r.get("isin"), "issuer": r.get("issuer"),
            "board": r.get("board"), "coupon_percent": r.get("coupon_percent"),
            "mat_date": r.get("mat_date"), "clean_price": r.get("clean_price"),
            "ytm": r.get("ytm"), "volume": r.get("volume"),
            "list_level": r.get("list_level"), "currency": r.get("currency"),
        })
        if len(bonds) >= limit:
            break
    return {"snapshot": _snapshot_meta(ctx), "bonds": bonds, "boards": boards, "count": len(bonds)}


def _solve_zspread(f, lo=-900, hi=5000, step=100):
    """Scan for a sign change of f over a sane bps range, then bracket-solve.
    Avoids the overflow/non-finite values of a single wide brentq bracket."""
    prev_s, prev_f = lo, f(lo)
    for s in range(lo + step, hi + 1, step):
        cur_f = f(s)
        if prev_f == 0:
            return float(prev_s)
        if (prev_f < 0) != (cur_f < 0):
            try:
                return float(brentq(f, prev_s, s, xtol=1e-3))
            except (ValueError, RuntimeError):
                return None
        prev_s, prev_f = s, cur_f
    return None


def _project_floating(ref, valuation, forecast_curve, float_spread_bps) -> list[tuple[float, float]]:
    """Project a floater's future coupons from a forecast curve's forward rates."""
    nxt = _to_date(ref.get("next_coupon"))
    mat = _to_date(ref.get("mat_date"))
    period = int(ref.get("coupon_period") or 182)
    if not (nxt and mat and mat > valuation and period > 0):
        return []
    spread = float(float_spread_bps) / 10000.0
    coupons: list[tuple[float, float]] = []
    d_prev, d = valuation, nxt
    guard = 0
    while d <= mat and guard < 400:
        guard += 1
        t0 = max((d_prev - valuation).days / 365.0, 1e-4)
        t1 = (d - valuation).days / 365.0
        if t1 > t0:
            fwd = forecast_curve.forward_rate(t0, t1)
            tau = (d - d_prev).days / 365.0
            coupons.append((t1, (fwd + spread) * tau * 100.0))
        d_prev, d = d, d + _dt.timedelta(days=period)
    return coupons


def _build_cashflows(ref, schedule, valuation, *, forecast_curve=None, float_spread_bps=0.0):
    """Future cashflows per 100 face from the real coupon/amortization schedule.

    Returns (cashflows, is_floater). When the bond has no known future fixed
    coupons but a forecast curve is supplied, future coupons are projected from
    that curve's forward rates (+ spread) — i.e. a floating-rate note priced off
    RUONIA/OFZ forwards.
    """
    face = float(ref.get("facevalue") or 100.0)
    raw: list[tuple[float, float]] = []
    for c in schedule.get("coupons", []):
        d = _to_date(c.get("coupon_date"))
        if d is None or c.get("value") is None:
            continue
        t = (d - valuation).days / 365.0
        if t > 1e-6:
            raw.append((t, float(c["value"]) / face * 100.0))

    is_floater = False
    if not raw and forecast_curve is not None:
        projected = _project_floating(ref, valuation, forecast_curve, float_spread_bps)
        if projected:
            raw.extend(projected)
            is_floater = True

    amorts = schedule.get("amortizations") or []
    if amorts:
        for a in amorts:
            d = _to_date(a.get("amort_date"))
            if d is None or a.get("value") is None:
                continue
            t = (d - valuation).days / 365.0
            if t > 1e-6:
                raw.append((t, float(a["value"]) / face * 100.0))
    else:
        mat = _to_date(ref.get("mat_date"))
        if mat:
            t = (mat - valuation).days / 365.0
            if t > 1e-6:
                raw.append((t, 100.0))

    merged: dict[float, float] = {}
    for t, amount in raw:
        key = round(t, 6)
        merged[key] = merged.get(key, 0.0) + amount
    return sorted(merged.items()), is_floater


def reprice(ctx, secid: str, curve_id: str = "GCURVE_RUB", shift_bps: float = 0.0,
            forecast_curve_id: str = "RUONIA_RUB", float_spread_bps: float = 0.0) -> dict:
    db = ctx.market_db
    if db is None:
        raise ValueError("market-data DB unavailable")
    ref = db.get_bond_ref(secid)
    quote = db.get_bond_quote(ctx.snapshot.snapshot_id, secid)
    if not ref or not quote:
        raise ValueError(f"unknown bond {secid}")
    if quote.get("clean_price") is None:
        raise ValueError(f"no market price for {secid}")

    valuation = _to_date(ctx.snapshot.valuation_date) or _dt.date.today()
    schedule = db.get_bond_schedule(secid)
    forecast = None
    if forecast_curve_id:
        try:
            forecast = ctx.market.get_curve(forecast_curve_id, ctx.snapshot)
        except Exception:
            forecast = None
    cashflows, is_floater = _build_cashflows(
        ref, schedule, valuation, forecast_curve=forecast, float_spread_bps=float_spread_bps)
    if not cashflows:
        raise ValueError(f"no future cashflows for {secid} (floating/expired?)")

    base = ctx.market.get_curve(curve_id, ctx.snapshot)
    priced = base.parallel_shift(float(shift_bps)) if shift_bps else base

    def pv(curve) -> float:
        return sum(amount * curve.discount(t) for t, amount in cashflows)

    face = float(ref.get("facevalue") or 100.0)
    market_clean = float(quote["clean_price"])
    market_accrued = float(quote.get("accruedint") or 0.0) / face * 100.0
    market_dirty = market_clean + market_accrued

    theo_dirty = pv(priced)
    theo_clean = theo_dirty - market_accrued

    # Z-spread: parallel spread (bps) on the base curve that reprices to the market.
    z_spread = _solve_zspread(lambda s: pv(base.parallel_shift(s)) - market_dirty)

    # Yield-space comparison, apples-to-apples: both the curve-implied YTM and the
    # market-implied YTM are solved from the SAME cashflows with the SAME yield
    # convention, so their difference is a clean richness/cheapness measure of the
    # bond versus the chosen curve (for a sovereign on its own curve this is basis
    # to the fitted curve; on a different curve it reads as a credit spread).
    freq = max(1, round(365.0 / float(ref.get("coupon_period") or 182)))

    def _effective(nominal):
        # bond_yield returns a freq-compounded nominal yield; MOEX quotes the
        # effective annual yield, so convert for an apples-to-apples comparison.
        return (1.0 + nominal / freq) ** freq - 1.0

    curve_ytm = implied_ytm = ytm_spread = None
    try:
        curve_ytm = _effective(bond_yield(cashflows, pv(base), freq))
        implied_ytm = _effective(bond_yield(cashflows, market_dirty, freq))
        ytm_spread = (implied_ytm - curve_ytm) * 10000.0
    except Exception:
        pass

    return {
        "secid": secid, "isin": ref.get("isin"), "issuer": ref.get("issuer"),
        "board": quote.get("board"), "facevalue": face,
        "coupon_percent": ref.get("coupon_percent"), "mat_date": ref.get("mat_date"),
        "curve_id": curve_id, "curve_label": CURVE_LABELS.get(curve_id, curve_id),
        "shift_bps": shift_bps,
        "market_clean": market_clean, "market_dirty": market_dirty,
        "market_accrued": market_accrued, "market_ytm": quote.get("ytm"),
        "implied_ytm": implied_ytm, "curve_ytm": curve_ytm,
        "theoretical_clean": theo_clean, "theoretical_dirty": theo_dirty,
        "price_diff": theo_clean - market_clean,
        "z_spread_bps": z_spread, "ytm_spread_bps": ytm_spread,
        "is_floater": is_floater,
        "forecast_curve_id": (forecast_curve_id if is_floater else None),
        "float_spread_bps": (float_spread_bps if is_floater else None),
        "cashflows": [{"t": t, "amount": a} for t, a in cashflows],
        "n_cashflows": len(cashflows),
        "valuation_date": str(valuation),
    }
