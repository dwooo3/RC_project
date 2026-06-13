"""
FORTS option vol-surface assembly (Phase D).

Pure functions to normalise raw ISS option rows (engine=futures, market=options)
into vol_points and to group stored points into snapshot vol_surfaces structures.
Implied vols are stored as decimals (ISS quotes them in percent).

⚠️ Column names (ASSETCODE/STRIKE/expiry/volatility) must be confirmed on first
live run; extraction is tolerant of common variants.
"""

from __future__ import annotations

import re
import statistics

_STRIKE_COLS = ("STRIKE", "strike")
_IV_COLS = ("VOLATILITY", "IV", "THEORVOLATILITY", "SETTLEMENTVOLATILITY", "volatility")
_UNDERLYING_COLS = ("ASSETCODE", "UNDERLYINGASSET", "UNDERLYING", "assetcode")
_EXPIRY_COLS = ("LASTDELDATE", "EXPDATE", "LASTTRADEDATE", "expiration")


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(row: dict, cols) -> object | None:
    for c in cols:
        if c in row and row[c] not in (None, ""):
            return row[c]
    return None


def _iv_to_decimal(raw) -> float | None:
    v = _to_float(raw)
    if v is None or v <= 0:
        return None
    return v / 100.0 if v > 1.5 else v  # 25.0 -> 0.25; 0.25 stays 0.25


def _underlying_from_secid(secid: str | None) -> str | None:
    if not secid:
        return None
    m = re.match(r"[A-Za-z]+", str(secid))
    return m.group(0) if m else None


# ─────────────────────────────────────────────────────────
# Self-implied IV from EOD settlement prices (Stage I.5)
# ─────────────────────────────────────────────────────────
# EOD ISS marketdata carries NO volatility for FORTS options (the VOLATILITY
# field is intraday-only) — confirmed by live probe 2026-06-11. Settlement
# prices ARE published for every instrument, so implied vols are computed
# locally: FORTS options are futures-style margined, hence Black-76 with r=0
# against the underlying futures settlement price.

# SHORTNAME like "Si-6.26M180626CA100000": underlying "Si-6.26",
# expiry 18.06.26, C=call/P=put, A=margin style, strike 100000.
_SHORTNAME_RE = re.compile(
    r"^(?P<und>.+?)M(?P<dd>\d{2})(?P<mm>\d{2})(?P<yy>\d{2})"
    r"(?P<cp>[CP])[AE]?(?P<strike>[\d.]+)$"
)


def parse_option_shortname(shortname: str) -> dict | None:
    """Parse a FORTS option SHORTNAME into {underlying, expiry, cp, strike}."""
    m = _SHORTNAME_RE.match(str(shortname or "").strip())
    if not m:
        return None
    strike = _to_float(m.group("strike"))
    if strike is None or strike <= 0:
        return None
    yy = int(m.group("yy"))
    return {
        "underlying": m.group("und"),
        "expiry": f"20{yy:02d}-{m.group('mm')}-{m.group('dd')}",
        "cp": "call" if m.group("cp") == "C" else "put",
        "strike": strike,
    }


def futures_settle_map(futures_secs: list[dict], futures_md: list[dict]) -> dict[str, float]:
    """SHORTNAME -> settlement price for FORTS futures (md first, prev as fallback)."""
    md_by_id = {r.get("SECID"): r for r in futures_md}
    out: dict[str, float] = {}
    for sec in futures_secs:
        name = sec.get("SHORTNAME")
        if not name:
            continue
        md = md_by_id.get(sec.get("SECID"), {})
        settle = _to_float(md.get("SETTLEPRICE")) or _to_float(sec.get("PREVSETTLEPRICE"))
        if settle and settle > 0:
            out[str(name)] = settle
    return out


def imply_option_vols(option_secs: list[dict], option_md: list[dict],
                      futures_secs: list[dict], futures_md: list[dict],
                      valuation_date, *,
                      min_open_interest: float = 1.0,
                      moneyness: tuple = (0.5, 2.0),
                      iv_bounds: tuple = (0.03, 3.0),
                      min_days: int = 3) -> list[dict]:
    """
    Imply Black-76 vols from option settlement prices.

    Quality filters: positive settle, open interest, sane moneyness window,
    minimum time to expiry, iv inside bounds. For each (underlying, expiry,
    strike) the OTM contract wins (richer in information than the ITM twin).
    Returns rows {underlying(ASSETCODE), expiry, strike, iv, forward, T, oi}.
    """
    from datetime import date as _date

    from models.implied_vol import implied_vol_black76

    fut_settle = futures_settle_map(futures_secs, futures_md)
    md_by_id = {r.get("SECID"): r for r in option_md}
    if isinstance(valuation_date, str):
        valuation_date = _date.fromisoformat(valuation_date[:10])

    best: dict[tuple, dict] = {}
    for sec in option_secs:
        parsed = parse_option_shortname(sec.get("SHORTNAME"))
        if not parsed:
            continue
        F = fut_settle.get(parsed["underlying"])
        if not F:
            continue
        md = md_by_id.get(sec.get("SECID"), {})
        price = _to_float(md.get("SETTLEPRICE")) or _to_float(sec.get("PREVSETTLEPRICE"))
        oi = _to_float(md.get("OPENPOSITION")) or _to_float(sec.get("PREVOPENPOSITION")) or 0.0
        expiry_raw = sec.get("LASTTRADEDATE") or parsed["expiry"]
        try:
            expiry = _date.fromisoformat(str(expiry_raw)[:10])
        except ValueError:
            continue
        T = (expiry - valuation_date).days / 365.0
        K = parsed["strike"]
        if (price is None or price <= 0 or oi < min_open_interest
                or T < min_days / 365.0
                or not (moneyness[0] <= K / F <= moneyness[1])):
            continue
        try:
            iv = implied_vol_black76(price, F, K, T, 0.0, parsed["cp"])
        except Exception:
            continue
        if iv is None or not (iv_bounds[0] <= iv <= iv_bounds[1]) or iv != iv:
            continue
        is_otm = (K >= F) == (parsed["cp"] == "call")
        key = (sec.get("ASSETCODE") or parsed["underlying"], str(expiry), K)
        row = {"underlying": key[0], "expiry": key[1], "strike": K,
               "iv": float(iv), "forward": F, "T": T, "oi": oi, "otm": is_otm}
        prev = best.get(key)
        if prev is None or (is_otm and not prev["otm"]) or (is_otm == prev["otm"] and oi > prev["oi"]):
            best[key] = row
    return sorted(best.values(), key=lambda r: (r["underlying"], r["expiry"], r["strike"]))


def normalise_option_rows(rows: list[dict]) -> list[dict]:
    """Raw ISS option rows -> [{underlying, expiry, strike, iv}] (IV decimal)."""
    out: list[dict] = []
    for row in rows:
        strike = _to_float(_first(row, _STRIKE_COLS))
        iv = _iv_to_decimal(_first(row, _IV_COLS))
        if strike is None or iv is None:
            continue
        underlying = _first(row, _UNDERLYING_COLS) or _underlying_from_secid(
            row.get("SECID") or row.get("secid")
        )
        expiry = _first(row, _EXPIRY_COLS) or ""
        out.append({
            "underlying": str(underlying or "UNKNOWN"),
            "expiry": str(expiry),
            "strike": strike,
            "iv": iv,
        })
    return out


def build_vol_surfaces(points: list[dict]) -> dict[str, dict]:
    """
    Group vol points into ``{f'{underlying}_FORTS': surface}`` where surface is
    a renderer-neutral grid with a summary ATM-ish (median) vol.
    """
    by_underlying: dict[str, list[dict]] = {}
    for p in points:
        by_underlying.setdefault(p["underlying"], []).append(
            {"expiry": p["expiry"], "strike": p["strike"], "iv": p["iv"]}
        )
    surfaces: dict[str, dict] = {}
    for underlying, grid in by_underlying.items():
        ivs = [g["iv"] for g in grid]
        surfaces[f"{underlying}_FORTS"] = {
            "type": "grid",
            "source": "MOEX_FORTS",
            "underlying": underlying,
            "points": sorted(grid, key=lambda g: (g["expiry"], g["strike"])),
            "median_vol": statistics.median(ivs) if ivs else None,
            "n_points": len(grid),
        }
    return surfaces
