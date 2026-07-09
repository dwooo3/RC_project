"""Underlying market-facts for the pricing workstation.

Given a (category, secid) from the instrument-entity store, build a compact
"facts" dict the client can pour into a pricer's parameter form: spot, realized
/ implied vol, dividend yield, time-to-expiry, currency, and a curve-implied
risk-free rate. Each workstation product declares its own fill map
{param_key -> fact_key}, so the same facts feed very different forms.
"""

from __future__ import annotations

import datetime as _dt

from api import market_entity


def _years_to(date_str: str | None) -> float | None:
    if not date_str:
        return None
    try:
        d = _dt.date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return None
    days = (d - _dt.date.today()).days
    return round(days / 365.0, 4) if days > 0 else None


# FORTS month codes (futures): F=Jan G=Feb H=Mar J=Apr K=May M=Jun
# N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec
_FORTS_MONTH = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
                "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}


def _expiry_from_ticker(secid: str) -> float | None:
    """Fallback expiry from a FORTS futures code (SiU6 -> Sep 2026): month
    letter + single year digit; expiry approximated as the 15th (FORTS
    futures expire mid-month). Deterministic when last_trade_date is absent."""
    if len(secid) < 3:
        return None
    month = _FORTS_MONTH.get(secid[-2].upper())
    if month is None or not secid[-1].isdigit():
        return None
    today = _dt.date.today()
    year = (today.year // 10) * 10 + int(secid[-1])
    # FORTS lists ~2 years ahead; a mid-month date in the past means the
    # contract has expired — do NOT wrap a decade forward.
    return _years_to(_dt.date(year, month, 15).isoformat())


def _atm_iv(ctx, asset_code: str | None, spot: float | None) -> float | None:
    """ATM implied vol (decimal) from the snapshot's calibrated FORTS surface."""
    if not asset_code:
        return None
    try:
        surfaces = ctx.snapshot.vol_surfaces
    except Exception:
        return None
    for sid in (f"{asset_code}_FORTS", asset_code):
        if sid not in (surfaces or {}):
            continue
        try:
            surface = ctx.market.get_vol_surface(sid, ctx.snapshot)
            if hasattr(surface, "get_vol") and spot:
                return round(float(surface.get_vol(spot, 0.25)), 4)
            if isinstance(surface, dict) and surface.get("median_vol") is not None:
                return round(float(surface["median_vol"]), 4)
        except Exception:
            continue
    return None


def _r_zero(ctx, tenor: float = 1.0) -> float | None:
    """Curve-implied risk-free anchor: GCURVE zero at `tenor` (continuous)."""
    for cid in ("GCURVE_RUB", "ZCB_OFZ_RUB", "KEYRATE_RUB"):
        try:
            curve = ctx.market.get_curve(cid, ctx.snapshot)
            return round(float(curve.rate(tenor)), 6)
        except Exception:
            continue
    return None


def facts(ctx, category: str, secid: str) -> dict:
    """Market facts for one instrument, shaped for form autofill."""
    inst = market_entity.instrument(ctx, category, secid)

    spot = inst.get("last")
    day = inst.get("day") or {}
    if spot is None:
        spot = day.get("close")
    stats = inst.get("stats") or {}
    rv30 = stats.get("rv_30d_pct")

    div_yield = inst.get("div_yield_pct")
    asset_code = inst.get("asset_code")
    expiry_t = None
    if category in ("futures", "options"):
        try:
            ref = ctx.market_db.get_instrument_ref(secid) or {}
            expiry_t = _years_to(ref.get("last_trade_date"))
        except Exception:
            expiry_t = None
        if expiry_t is None:
            for f in inst.get("fields", []):
                if str(f.get("name", "")).upper() in ("LSTTRADE", "LASTTRADEDATE"):
                    expiry_t = _years_to(f.get("value"))
                    break
        if expiry_t is None and category == "futures":
            expiry_t = _expiry_from_ticker(secid)

    iv = _atm_iv(ctx, asset_code or (secid if category == "options" else None),
                 float(spot) if spot else None)
    vol = iv if iv else (round(rv30 / 100.0, 4) if rv30 else None)

    out = {
        "secid": secid,
        "category": category,
        "label": inst.get("issuer_ru") or inst.get("name_ru") or secid,
        "currency": inst.get("currency"),
        "facts": {
            "spot": float(spot) if spot is not None else None,
            "vol": vol,
            "atm_iv": iv,
            "rv30": round(rv30 / 100.0, 4) if rv30 else None,
            "div_yield": round(div_yield / 100.0, 4) if div_yield else 0.0,
            "expiry_T": expiry_t,
            "r_zero": _r_zero(ctx),
            "ytm": round(inst["ytm"] / 100.0, 6) if inst.get("ytm") else None,
        },
    }
    return out
