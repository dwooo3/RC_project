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
