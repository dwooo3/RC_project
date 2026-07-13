"""
FORTS option vol-surface assembly (Phase D).

Pure functions to normalise raw ISS option rows (engine=futures, market=options)
into vol_points and to group stored points into snapshot vol_surfaces structures.
Implied vols are stored as decimals (ISS quotes them in percent).

⚠️ Column names (ASSETCODE/STRIKE/expiry/volatility) must be confirmed on first
live run; extraction is tolerant of common variants.
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import date as _date
from datetime import datetime as _datetime

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


_TRADE_DATE_COLS = ("TRADEDATE", "tradedate", "TRADE_DATE", "trade_date")
_PREV_DATE_COLS = ("PREVDATE", "prevdate", "PREVTRADEDATE", "prev_trade_date")

PRIMARY_IV_METHOD = "black76_settlement"
PRIMARY_OPTION_PRICE_SOURCES = frozenset({"MOEX_FORTS_OPTION_SETTLEMENT"})
PRIMARY_FORWARD_SOURCES = frozenset({
    "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
    "MOEX_FORTS_FUTURES_SETTLEMENT",
})
PRIMARY_OPTION_PRICE_BASES = frozenset({"settlement", "previous_settlement"})
PRIMARY_FORWARD_BASES = frozenset({
    "underlying_settlement", "settlement", "previous_settlement",
})


def _strict_iso_day(value) -> str | None:
    """Return an ISO day only when the complete input is a valid ISO value."""
    if isinstance(value, _datetime):
        return value.date().isoformat()
    if isinstance(value, _date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = (
            _date.fromisoformat(raw)
            if len(raw) == 10
            else _datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        )
    except ValueError:
        return None
    return parsed.isoformat()


def _row_date(*rows: dict, previous: bool = False) -> str | None:
    """First explicit ISO trading date in the supplied ISS rows.

    ``SYSTIME`` is intentionally not accepted: it is a response/update clock
    and may advance on a weekend while the settlement itself remains Friday's.
    """
    columns = _PREV_DATE_COLS if previous else _TRADE_DATE_COLS
    for row in rows:
        for column in columns:
            value = row.get(column)
            if not value:
                continue
            parsed = _strict_iso_day(value)
            if parsed is not None:
                return parsed
    return None


def _settlement_value(primary: dict, secondary: dict) -> tuple[float | None, str | None, str]:
    """Settlement, its explicit observation date, and current/previous basis."""
    candidates = [
        (row, "SETTLEPRICE", False, "settlement")
        for row in (primary, secondary)
    ] + [
        (row, "PREVSETTLEPRICE", True, "previous_settlement")
        for row in (secondary, primary)
    ]
    first_undated = None
    for row, column, previous, basis in candidates:
        value = _to_float(row.get(column))
        if value is None or value <= 0:
            continue
        candidate = (value, _row_date(row, previous=previous), basis)
        if candidate[1] is not None:
            return candidate
        first_undated = first_undated or candidate
    return first_undated or (None, None, "missing")


def primary_iv_provenance_error(point: dict, expected_date=None) -> str | None:
    """Return the first fail-closed lineage error for a publishable IV point."""
    if point.get("method") != PRIMARY_IV_METHOD:
        return "method_not_allowed"
    if point.get("observation_status") != "verified":
        return "observation_date_not_verified"
    observation_date = _strict_iso_day(point.get("observation_date"))
    option_date = _strict_iso_day(point.get("option_price_date"))
    forward_date = _strict_iso_day(point.get("forward_date"))
    if not observation_date or not option_date or not forward_date:
        return "observation_date_not_verified"
    if len({observation_date, option_date, forward_date}) != 1:
        return "observation_date_mismatch"
    if expected_date is not None:
        expected = _strict_iso_day(expected_date)
        if expected is None or observation_date != expected:
            return "observation_date_mismatch"
    expiry = _strict_iso_day(point.get("expiry"))
    if expiry is None or expiry <= observation_date:
        return "invalid_expiry"
    try:
        raw_tenor_days = float(point.get("tenor_days"))
    except (TypeError, ValueError, OverflowError):
        return "invalid_tenor_days"
    if (not math.isfinite(raw_tenor_days) or raw_tenor_days <= 0
            or not raw_tenor_days.is_integer()):
        return "invalid_tenor_days"
    tenor_days = int(raw_tenor_days)
    actual_tenor_days = (
        _date.fromisoformat(expiry) - _date.fromisoformat(observation_date)
    ).days
    if tenor_days != actual_tenor_days:
        return "invalid_tenor_days"
    if point.get("option_price_source") not in PRIMARY_OPTION_PRICE_SOURCES:
        return "option_price_source_not_allowed"
    if point.get("forward_source") not in PRIMARY_FORWARD_SOURCES:
        return "forward_source_not_allowed"
    if point.get("option_price_basis") not in PRIMARY_OPTION_PRICE_BASES:
        return "option_price_basis_not_allowed"
    if point.get("forward_basis") not in PRIMARY_FORWARD_BASES:
        return "forward_basis_not_allowed"
    try:
        forward = float(point["forward"])
    except (KeyError, TypeError, ValueError):
        return "invalid_forward"
    if not math.isfinite(forward) or forward <= 0:
        return "invalid_forward"
    return None


def vol_point_payload_error(point: dict) -> str | None:
    """Validate the identity and IV payload shared by raw and lineage rows."""
    underlying = str(point.get("underlying") or "").strip()
    if not underlying or underlying == "UNKNOWN":
        return "invalid_underlying"
    if _strict_iso_day(point.get("expiry")) is None:
        return "invalid_expiry"
    try:
        strike = float(point.get("strike"))
    except (TypeError, ValueError, OverflowError):
        return "invalid_strike"
    if not math.isfinite(strike) or strike <= 0:
        return "invalid_strike"
    try:
        iv = float(point.get("iv"))
    except (TypeError, ValueError, OverflowError):
        return "invalid_iv"
    if not math.isfinite(iv) or not 0.01 < iv < 3.0:
        return "invalid_iv"
    return None


def _vol_point_key(point: dict) -> tuple[str, str, float]:
    underlying = str(point.get("underlying") or "").strip()
    expiry = _strict_iso_day(point.get("expiry"))
    try:
        strike = float(point.get("strike"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid_strike") from exc
    if (not underlying or underlying == "UNKNOWN" or expiry is None
            or not math.isfinite(strike) or strike <= 0):
        raise ValueError("invalid_vol_point_key")
    return underlying, expiry, strike


def vol_lineage_diagnostics(raw_points: list[dict], observations: list[dict]) -> dict:
    """Compare a consumable raw surface with its audited point-for-point lineage."""
    def collect(rows: list[dict]) -> tuple[dict[tuple[str, str, float], dict], list[str]]:
        by_key: dict[tuple[str, str, float], dict] = {}
        invalid: list[str] = []
        for index, row in enumerate(rows):
            error = vol_point_payload_error(row)
            try:
                key = _vol_point_key(row)
            except ValueError:
                invalid.append(f"{index}:{error or 'invalid_vol_point_key'}")
                continue
            if key in by_key:
                invalid.append(f"{index}:duplicate_vol_point_key")
            if error:
                invalid.append(f"{index}:{error}")
            by_key[key] = row
        return by_key, invalid

    raw_by_key, invalid_raw = collect(raw_points)
    observation_by_key, invalid_observations = collect(observations)
    raw_keys = set(raw_by_key)
    observation_keys = set(observation_by_key)
    missing_observation_keys = raw_keys - observation_keys
    extra_observation_keys = observation_keys - raw_keys
    iv_value_mismatch_keys: list[str] = []
    for key in sorted(raw_keys & observation_keys):
        try:
            raw_iv = float(raw_by_key[key].get("iv"))
            observation_iv = float(observation_by_key[key].get("iv"))
        except (TypeError, ValueError, OverflowError):
            continue
        if (math.isfinite(raw_iv) and math.isfinite(observation_iv)
                and raw_iv != observation_iv):
            underlying, expiry, strike = key
            iv_value_mismatch_keys.append(
                f"{underlying}|{expiry}|{strike:g}"
            )
    key_coverage_complete = (
        raw_keys == observation_keys
        and len(raw_by_key) == len(raw_points)
        and len(observation_by_key) == len(observations)
    )
    payload_match_complete = (
        key_coverage_complete
        and not invalid_raw
        and not invalid_observations
        and not iv_value_mismatch_keys
    )
    return {
        "raw_keys": raw_keys,
        "observation_keys": observation_keys,
        "missing_observation_keys": missing_observation_keys,
        "extra_observation_keys": extra_observation_keys,
        "invalid_raw_payloads": invalid_raw,
        "invalid_observation_payloads": invalid_observations,
        "iv_value_mismatch_keys": iv_value_mismatch_keys,
        "key_coverage_complete": key_coverage_complete,
        "payload_match_complete": payload_match_complete,
    }


def futures_settle_details(futures_secs: list[dict],
                           futures_md: list[dict]) -> dict[str, dict]:
    """SHORTNAME -> governed settlement details used as option forwards."""
    md_by_id = {r.get("SECID"): r for r in futures_md}
    out: dict[str, dict] = {}
    for sec in futures_secs:
        name = sec.get("SHORTNAME")
        if not name:
            continue
        md = md_by_id.get(sec.get("SECID"), {})
        settle, observation_date, basis = _settlement_value(md, sec)
        if settle is not None:
            out[str(name)] = {
                "forward": settle,
                "forward_date": observation_date,
                "forward_source": "MOEX_FORTS_FUTURES_SETTLEMENT",
                "forward_basis": basis,
            }
    return out


def futures_settle_map(futures_secs: list[dict], futures_md: list[dict]) -> dict[str, float]:
    """Backward-compatible SHORTNAME -> settlement-price view."""
    return {name: row["forward"]
            for name, row in futures_settle_details(futures_secs, futures_md).items()}


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
    from models.implied_vol import implied_vol_black76

    fut_settle = futures_settle_details(futures_secs, futures_md)
    md_by_id = {r.get("SECID"): r for r in option_md}
    if isinstance(valuation_date, str):
        valuation_date = _date.fromisoformat(valuation_date[:10])

    best: dict[tuple, dict] = {}
    for sec in option_secs:
        parsed = parse_option_shortname(sec.get("SHORTNAME"))
        if not parsed:
            continue
        md = md_by_id.get(sec.get("SECID"), {})
        price, option_date, price_basis = _settlement_value(md, sec)
        direct_forward = None
        direct_forward_date = None
        undated_direct_forward = None
        for row in (md, sec):
            candidate = _to_float(row.get("UNDERLYINGSETTLEPRICE"))
            if candidate is None or candidate <= 0:
                continue
            candidate_date = _row_date(row)
            if candidate_date is not None:
                direct_forward = candidate
                direct_forward_date = candidate_date
                break
            undated_direct_forward = undated_direct_forward or candidate
        forward_details = fut_settle.get(parsed["underlying"], {})
        fallback_forward = _to_float(forward_details.get("forward"))
        fallback_date = forward_details.get("forward_date")
        if direct_forward is not None:
            F = direct_forward
            forward_date = direct_forward_date
            forward_source = "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT"
            forward_basis = "underlying_settlement"
        elif fallback_forward is not None and fallback_forward > 0 and fallback_date:
            F = fallback_forward
            forward_date = fallback_date
            forward_source = (forward_details.get("forward_source")
                              or "MOEX_FORTS_FUTURES_SETTLEMENT")
            forward_basis = forward_details.get("forward_basis") or "missing"
        elif undated_direct_forward is not None:
            F = undated_direct_forward
            forward_date = None
            forward_source = "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT"
            forward_basis = "underlying_settlement"
        else:
            F = fallback_forward
            forward_date = fallback_date
            forward_source = (forward_details.get("forward_source")
                              or "MOEX_FORTS_FUTURES_SETTLEMENT")
            forward_basis = forward_details.get("forward_basis") or "missing"
        if not F:
            continue
        if option_date is None:
            observation_status = "missing_option_date"
            observation_date = None
        elif forward_date is None:
            observation_status = "missing_forward_date"
            observation_date = option_date
        elif option_date != forward_date:
            observation_status = f"date_mismatch:{option_date}!={forward_date}"
            observation_date = option_date
        else:
            observation_status = "verified"
            observation_date = option_date
        oi = _to_float(md.get("OPENPOSITION")) or _to_float(sec.get("PREVOPENPOSITION")) or 0.0
        expiry_raw = sec.get("LASTTRADEDATE") or parsed["expiry"]
        try:
            expiry = _date.fromisoformat(str(expiry_raw)[:10])
        except ValueError:
            continue
        tenor_base = (_date.fromisoformat(observation_date)
                      if observation_status == "verified" else valuation_date)
        tenor_days = (expiry - tenor_base).days
        T = tenor_days / 365.0
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
               "iv": float(iv), "forward": F, "T": T, "tenor_days": tenor_days,
               "oi": oi, "otm": is_otm, "observation_date": observation_date,
               "observation_status": observation_status,
               "source": forward_source, "method": PRIMARY_IV_METHOD,
               "option_price_date": option_date, "forward_date": forward_date,
               "option_price_source": "MOEX_FORTS_OPTION_SETTLEMENT",
               "forward_source": forward_source,
               "option_price_basis": price_basis, "forward_basis": forward_basis}
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
        observation_date = _row_date(row)
        forward = _to_float(row.get("UNDERLYINGSETTLEPRICE"))
        if observation_date is None:
            observation_status = "missing_option_date"
        elif forward is None or forward <= 0:
            observation_status = "missing_forward_date"
        else:
            observation_status = "verified"
        out.append({
            "underlying": str(underlying or "UNKNOWN"),
            "expiry": str(expiry),
            "strike": strike,
            "iv": iv,
            "forward": forward,
            "oi": _to_float(row.get("OPENPOSITION") or row.get("PREVOPENPOSITION")),
            "observation_date": observation_date,
            "observation_status": observation_status,
            "source": "MOEX_FORTS_PUBLISHED_IV",
            "option_price_date": observation_date,
            "forward_date": observation_date if forward and forward > 0 else None,
            "option_price_source": "MOEX_FORTS_PUBLISHED_IV",
            "forward_source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
            "option_price_basis": "published_iv",
            "forward_basis": "underlying_settlement",
            "method": "published_iv",
        })
    return out


def iv30_representative(points: list[dict], observation_date,
                        *, target_days: int = 30,
                        nearest_tolerance_days: int = 7,
                        max_atm_log_moneyness: float = 0.10) -> dict:
    """Build one governed constant-maturity ATM-forward IV observation.

    First interpolate the smile to ``log(K/F)=0`` for each expiry.  Then
    interpolate *total variance* between the expiries bracketing 30 calendar
    days.  With no bracket, a nearest expiry is permitted only inside ±7 days
    and is explicitly WARN-quality; farther extrapolation is rejected.
    """
    if isinstance(observation_date, str):
        try:
            observation_date = _date.fromisoformat(observation_date[:10])
        except ValueError:
            return {"accepted": False, "reason": "invalid_observation_date"}
    if not isinstance(observation_date, _date):
        return {"accepted": False, "reason": "missing_observation_date"}

    by_expiry: dict[str, list[dict]] = {}
    for point in points:
        try:
            expiry = _date.fromisoformat(str(point.get("expiry") or "")[:10])
            strike = float(point["strike"])
            iv = float(point["iv"])
            forward = float(point["forward"])
        except (KeyError, TypeError, ValueError):
            continue
        if (expiry <= observation_date or strike <= 0 or forward <= 0
                or not math.isfinite(iv) or not 0.01 < iv < 3.0):
            continue
        enriched = {**point, "expiry": expiry.isoformat(), "strike": strike,
                    "iv": iv, "forward": forward,
                    "log_moneyness": math.log(strike / forward)}
        by_expiry.setdefault(expiry.isoformat(), []).append(enriched)

    expiry_atm: list[dict] = []
    for expiry_iso, rows in sorted(by_expiry.items()):
        rows.sort(key=lambda row: row["log_moneyness"])
        left = [row for row in rows if row["log_moneyness"] <= 0]
        right = [row for row in rows if row["log_moneyness"] >= 0]
        selected: list[dict]
        atm_method: str
        if (left and right
                and abs(left[-1]["log_moneyness"]) <= max_atm_log_moneyness
                and abs(right[0]["log_moneyness"]) <= max_atm_log_moneyness):
            lo, hi = left[-1], right[0]
            selected = [lo] if lo is hi else [lo, hi]
            span = hi["log_moneyness"] - lo["log_moneyness"]
            if abs(span) < 1e-15:
                atm_iv = lo["iv"]
                atm_method = "exact_forward"
            else:
                weight = -lo["log_moneyness"] / span
                atm_iv = lo["iv"] + weight * (hi["iv"] - lo["iv"])
                atm_method = "log_moneyness_interpolation"
        else:
            nearest = min(rows, key=lambda row: abs(row["log_moneyness"]))
            if abs(nearest["log_moneyness"]) > max_atm_log_moneyness:
                continue
            selected = [nearest]
            atm_iv = nearest["iv"]
            atm_method = "nearest_forward_strike"
        expiry_date = _date.fromisoformat(expiry_iso)
        tenor_days = (expiry_date - observation_date).days
        expiry_atm.append({
            "expiry": expiry_iso,
            "tenor_days": tenor_days,
            "T": tenor_days / 365.0,
            "iv": float(atm_iv),
            "atm_method": atm_method,
            "strikes": [row["strike"] for row in selected],
            "forwards": [row["forward"] for row in selected],
            "open_interest": [row.get("open_interest", row.get("oi"))
                              for row in selected],
        })

    if not expiry_atm:
        return {"accepted": False, "reason": "no_atm_forward_expiry"}

    exact = next((row for row in expiry_atm if row["tenor_days"] == target_days), None)
    warnings: list[str] = []
    if exact is not None:
        value = exact["iv"]
        method = "atm_forward_exact_30d"
        selected_expiries = [exact]
        quality = "OK"
    else:
        lower = [row for row in expiry_atm if row["tenor_days"] < target_days]
        upper = [row for row in expiry_atm if row["tenor_days"] > target_days]
        if lower and upper:
            lo = max(lower, key=lambda row: row["tenor_days"])
            hi = min(upper, key=lambda row: row["tenor_days"])
            w_lo = lo["iv"] ** 2 * lo["T"]
            w_hi = hi["iv"] ** 2 * hi["T"]
            if w_hi + 1e-12 < w_lo:
                return {
                    "accepted": False,
                    "reason": "calendar_total_variance_inversion",
                    "selected_expiries": [lo, hi],
                }
            target_t = target_days / 365.0
            weight = (target_t - lo["T"]) / (hi["T"] - lo["T"])
            target_variance = w_lo + weight * (w_hi - w_lo)
            value = math.sqrt(max(target_variance, 0.0) / target_t)
            method = "atm_forward_total_variance_30d"
            selected_expiries = [lo, hi]
            quality = "OK"
        else:
            nearest = min(expiry_atm, key=lambda row: abs(row["tenor_days"] - target_days))
            distance = abs(nearest["tenor_days"] - target_days)
            if distance > nearest_tolerance_days:
                return {
                    "accepted": False,
                    "reason": "no_30d_bracket_or_bounded_nearest",
                    "nearest_expiry": nearest,
                    "distance_days": distance,
                }
            value = nearest["iv"]
            method = "atm_forward_nearest_tenor"
            selected_expiries = [nearest]
            quality = "WARN"
            warnings.append(
                f"30D maturity not bracketed; {nearest['tenor_days']}D expiry used "
                f"within ±{nearest_tolerance_days}D bound")

    # An exact or bounded-nearest target still needs the same local calendar
    # sanity as an interpolated target.  Check the selected expiry/expiries and
    # their immediate neighbours; a farther unrelated wing cannot veto IV30.
    ordered = sorted(expiry_atm, key=lambda row: row["tenor_days"])
    selected_tenors = {row["tenor_days"] for row in selected_expiries}
    selected_indices = [index for index, row in enumerate(ordered)
                        if row["tenor_days"] in selected_tenors]
    if selected_indices:
        start = max(min(selected_indices) - 1, 0)
        stop = min(max(selected_indices) + 2, len(ordered))
        local = ordered[start:stop]
        for earlier, later in zip(local, local[1:]):
            earlier_variance = earlier["iv"] ** 2 * earlier["T"]
            later_variance = later["iv"] ** 2 * later["T"]
            if later_variance + 1e-12 < earlier_variance:
                return {
                    "accepted": False,
                    "reason": "calendar_total_variance_inversion",
                    "selected_expiries": selected_expiries,
                    "inversion_pair": [earlier, later],
                }

    if not math.isfinite(value) or not 0.01 < value < 3.0:
        return {"accepted": False, "reason": "invalid_representative_iv"}
    return {
        "accepted": True,
        "value": float(value),
        "quality": quality,
        "method": method,
        "target_days": target_days,
        "observation_date": observation_date.isoformat(),
        "selected_expiries": selected_expiries,
        "warnings": warnings,
    }


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


def governed_snapshot_surface_error(
    raw_points: list[dict],
    observations: list[dict],
    surface_id: str,
    cached_surface,
    observation_date,
) -> str | None:
    """Bind a cached FORTS grid to the governed rows behind its snapshot ID.

    Snapshot tables are mutable in the current store.  Checking the DB's raw
    and provenance rows against each other is therefore insufficient: a
    previously materialised ``MarketDataSnapshot`` could still carry another
    grid under the same ID.  This gate requires point-for-point equality with
    a freshly rebuilt grid as well as valid primary provenance.
    """
    identity = str(surface_id or "")
    if not identity.endswith("_FORTS"):
        return "surface_identity_not_forts"
    underlying = identity.removesuffix("_FORTS")
    if not underlying:
        return "surface_underlying_missing"
    lineage = vol_lineage_diagnostics(raw_points, observations)
    if not lineage["payload_match_complete"]:
        return "raw_provenance_payload_mismatch"
    rebuilt = build_vol_surfaces(raw_points).get(identity)
    if rebuilt is None:
        return "surface_rows_missing"
    if cached_surface != rebuilt:
        return "cached_surface_snapshot_mismatch"
    relevant = [
        point for point in observations
        if str(point.get("underlying") or "") == underlying
    ]
    if not relevant:
        return "surface_provenance_missing"
    errors = sorted(set(
        error for point in relevant
        if (error := primary_iv_provenance_error(point, observation_date))
    ))
    if errors:
        return "invalid_surface_provenance:" + ",".join(errors)
    return None
