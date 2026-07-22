"""Market Risk workstation (Calypso ERS-style) for the bridge.

Two-step process, faithful to the doc: (1) shifts generation — joint daily
factor changes from REAL stored history (IMOEX equity returns, КБД 5Y absolute
rate changes, RVI vol-point changes); (2) risk metric computation — the demo
book is FULL-REPRICED through its actual pricers on every historical scenario
(PortfolioService.full_reprice_pnl), giving a Hypothetical P&L distribution
from which VaR / ES / EVT metrics and the backtest are computed.

The FX factor runs on 5y of CBR daily fixings (USDRUB:fix, backfilled
2026-07-09); fixings are forward-filled onto trading dates, so gaps produce a
carried level rather than a fake zero move. The vol factor switches from the
RVI proxy only when approved own ATM-IV history covers every endpoint of the
requested rolling/stress calendar and supplies enough actual shocks/windows.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time

import numpy as np

from risk.factor_history import curve_node_factor_id, supported_curve_history_tenors

# HypPL series cache: (snapshot_id, window, stress period, horizon) -> series.
_CACHE: dict = {}


CUSTOM_HISTORICAL_REPRICING_PROFILE = "custom_hist_crn_v1"
CUSTOM_HISTORICAL_INNER_PATHS = 1_000


def _portfolio_positions(portfolio) -> list:
    """Return a defensive view of the positions accepted by risk adapters."""
    positions = getattr(portfolio, "positions", None)
    if positions is None:
        positions = getattr(getattr(portfolio, "portfolio", None), "positions", None)
    return list(positions or [])


def _portfolio_has_custom_product(portfolio) -> bool:
    return any(
        getattr(position, "instrument", None) == "custom_product"
        for position in _portfolio_positions(portfolio)
    )


def _scenario_matrix_hash(shifts: dict) -> str:
    """Hash the exact aligned factor matrix consumed by full repricing."""
    matrix_keys = (
        "dates", "eq", "dr", "dvol", "fx", "dr_tenors", "dr_curves",
        "eq_names", "vol_names", "dvol_positions", "fx_pairs",
        "spot_return_paths",
        "actual_trade_backcast",
    )

    def canonical(value):
        if isinstance(value, dict):
            return {
                str(key): canonical(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, np.ndarray):
            return canonical(value.tolist())
        if isinstance(value, (list, tuple)):
            return [canonical(item) for item in value]
        if isinstance(value, np.generic):
            return value.item()
        return value

    payload = {
        "schema": "historical-factor-scenario-matrix-v1",
        **{
            key: canonical(shifts.get(key, {} if key not in {
                "dates", "eq", "dr", "dvol", "fx"} else []))
            for key in matrix_keys
        },
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def invalidate_cache() -> None:
    """Drop cached HypPL series — called on any portfolio mutation."""
    _CACHE.clear()


def _series(db, factor_id: str) -> list[tuple[str, float]]:
    rows = db.get_time_series(factor_id) or []
    return [(r["dt"], float(r["value"])) for r in rows if r.get("value") is not None]


def _iv30_consumer_readiness(
    db,
    factor_id: str,
    dates: list[str],
    *,
    as_of: str,
    max_staleness_days: int,
) -> dict:
    """Require the operational lineage gate before consuming canonical IV30."""
    underlying = str(factor_id).removeprefix("IV30:").strip()
    if not underlying or not dates:
        return {
            "ready": False,
            "blockers": ["invalid_iv30_consumer_request"],
        }
    try:
        from infra.jobs.iv30_operational import iv30_readiness_report
        report = iv30_readiness_report(
            db,
            dates[0],
            dates[-1],
            min_shocks=max(len(dates) - 1, 0),
            required_underlyings=[underlying],
            expected_dates=dates,
            as_of=as_of,
            max_staleness_days=max_staleness_days,
            require_validation_reports=True,
        )
        factor = (report.get("factors") or {}).get(factor_id) or {}
        return {
            "ready": bool(report.get("ready") and factor.get("ready")),
            "blockers": list(report.get("blockers") or []),
            "factor": factor,
            "staleness_days": report.get("staleness_days"),
        }
    except Exception as exc:
        return {
            "ready": False,
            "blockers": ["operational_readiness_unavailable"],
            "error": str(exc),
        }


# Named stress windows for Stress VaR (Calypso §2.3): a fixed historical
# period whose shifts are applied to the CURRENT portfolio.
STRESS_WINDOWS = {
    "2022": ("2022-01-01", "2022-12-30"),          # мобилизация/санкции
    "2024h2": ("2024-09-01", "2025-03-31"),        # цикл КС 21%
}


_KBD_TENORS = (0.25, 1.0, 2.0, 5.0, 10.0)


def _component_secids(params: dict) -> list[str]:
    raw = (params or {}).get("component_secids")
    if raw in (None, "", []):
        raw = (params or {}).get("asset_ids")
    if raw in (None, "", []):
        return []
    values = raw if isinstance(raw, (list, tuple)) else str(raw).replace(";", ",").split(",")
    out = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("secid") or value.get("id") or ""
        token = str(value).strip().split(":", 1)[0].strip()
        if token:
            out.append(token)
    return out


def _component_kinds(params: dict) -> list[str]:
    raw = (params or {}).get("component_kinds")
    if raw in (None, "", []):
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError("component_kinds must be an aligned array")
    return [str(value).strip().lower() for value in raw]


def _book_secids(portfolio) -> list[str]:
    """Typed equity spot identities held in the book."""
    out = []
    for pos in portfolio.positions:
        params = pos.params or {}
        components = _component_secids(params)
        if components and pos.instrument in (
                "spread", "basket", "multi_asset_autocall", "custom_product"):
            out.extend(components)
            continue
        secid = params.get("secid")
        has_spot = any(key in params for key in ("S", "S0", "S1", "S2", "spot"))
        if secid and (has_spot or pos.instrument in ("equity", "future")):
            out.append(str(secid))
    return sorted(set(out))


def _book_component_kinds(portfolio) -> dict[str, str]:
    """Declared kinds for multi-asset components, rejecting ambiguity."""
    out: dict[str, str] = {}
    for pos in portfolio.positions:
        if pos.instrument not in ("multi_asset_autocall", "custom_product"):
            continue
        params = pos.params or {}
        components = _component_secids(params)
        kinds = _component_kinds(params)
        if len(kinds) != len(components):
            raise ValueError(
                f"{pos.id}: component_kinds has {len(kinds)} entries; "
                f"expected {len(components)}")
        supported = (
            {"equity", "index", "bond"}
            if pos.instrument == "multi_asset_autocall"
            else {"equity", "index", "bond", "future", "commodity"}
        )
        invalid = sorted(set(kinds) - supported)
        if invalid:
            raise ValueError(
                f"{pos.id}: unsupported component kinds: "
                + ", ".join(invalid))
        for secid, kind in zip(components, kinds):
            previous = out.get(secid)
            if previous is not None and previous != kind:
                raise ValueError(
                    f"component '{secid}' has conflicting kinds "
                    f"'{previous}' and '{kind}'")
            out[secid] = kind
    return out


_EQUITY_VOL_INSTRUMENTS = {
    "call", "put", "option", "digital", "barrier", "asian", "lookback",
    "spread", "basket", "autocall", "multi_asset_autocall", "custom_product",
}


_NAMED_CURVE_INSTRUMENTS = {
    "bond", "irs", "swap", "frn", "fra", "cap", "floor",
    "cap_floor", "swaption",
}


def _position_curve_tenor(params: dict) -> float:
    if isinstance(params.get("T"), (int, float)):
        return float(params["T"])
    if isinstance(params.get("T2"), (int, float)):
        return float(params["T2"])
    if (isinstance(params.get("T_option"), (int, float))
            and isinstance(params.get("T_swap"), (int, float))):
        return float(params["T_option"]) + float(params["T_swap"])
    return 5.0


def _book_curve_requirements(portfolio) -> dict[str, float]:
    """Named discount/projection dependencies and longest held cashflow."""
    requirements: dict[str, float] = {}
    for position in portfolio.positions:
        if position.instrument not in _NAMED_CURVE_INSTRUMENTS:
            continue
        params = position.params or {}
        required_tenor = _position_curve_tenor(params)
        for key in ("curve_id", "proj_curve_id"):
            curve_id = params.get(key)
            if curve_id:
                identity = str(curve_id)
                requirements[identity] = max(
                    requirements.get(identity, 0.0), required_tenor)
    return requirements


def _book_surface_requirements(portfolio) -> dict[str, dict]:
    """Position-specific sticky-strike/constant-maturity dependencies."""
    requirements: dict[str, dict] = {}
    for position in portfolio.positions:
        params = position.params or {}
        surface_id = params.get("vol_surface_id")
        if not surface_id or position.instrument not in {"call", "put", "option"}:
            continue
        if position.id in requirements:
            raise ValueError(
                f"duplicate position id '{position.id}' prevents surface attribution")
        try:
            strike = float(params["K"])
            tenor = float(params["T"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"position '{position.id}' has invalid named-surface K/T") from exc
        if (not math.isfinite(strike) or strike <= 0
                or not math.isfinite(tenor) or tenor <= 0):
            raise ValueError(
                f"position '{position.id}' has invalid named-surface K/T")
        requirements[position.id] = {
            "surface_id": str(surface_id),
            "K": strike,
            "T": tenor,
        }
    return requirements


def _sticky_strike_surface_level(points: list[dict], observation_date: str,
                                  strike: float, tenor: float) -> float:
    """Interpolate one governed surface at constant absolute K and maturity.

    Smile interpolation is linear in strike inside each expiry.  Maturity
    interpolation is linear in total variance and requires a bracket.  Neither
    axis permits extrapolation; a missing bracket invalidates the scenario set.
    """
    from datetime import date as _date

    try:
        as_of = _date.fromisoformat(str(observation_date)[:10])
    except ValueError as exc:
        raise ValueError("surface observation date is invalid") from exc
    by_expiry: dict[str, list[tuple[float, float]]] = {}
    for point in points:
        try:
            expiry = _date.fromisoformat(str(point.get("expiry") or "")[:10])
            node_strike = float(point["strike"])
            iv = float(point["iv"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if (expiry <= as_of or node_strike <= 0 or not math.isfinite(iv)
                or not 0.001 < iv < 5.0):
            continue
        by_expiry.setdefault(expiry.isoformat(), []).append((node_strike, iv))

    slices = []
    for expiry_iso, raw_nodes in by_expiry.items():
        nodes = sorted(set(raw_nodes))
        strikes = np.asarray([node[0] for node in nodes], dtype=float)
        vols = np.asarray([node[1] for node in nodes], dtype=float)
        if (len(strikes) < 2 or strike < strikes[0] - 1e-12
                or strike > strikes[-1] + 1e-12):
            continue
        expiry = _date.fromisoformat(expiry_iso)
        node_tenor = (expiry - as_of).days / 365.0
        slices.append((node_tenor, float(np.interp(strike, strikes, vols))))
    slices.sort()
    if not slices:
        raise ValueError("surface has no strike-supported expiry slices")

    exact = next((value for node_tenor, value in slices
                  if abs(node_tenor - tenor) <= 1e-12), None)
    if exact is not None:
        return exact
    lower = [item for item in slices if item[0] < tenor]
    upper = [item for item in slices if item[0] > tenor]
    if not lower or not upper:
        raise ValueError("surface has no constant-maturity tenor bracket")
    lo_t, lo_vol = max(lower)
    hi_t, hi_vol = min(upper)
    lo_variance = lo_vol * lo_vol * lo_t
    hi_variance = hi_vol * hi_vol * hi_t
    if hi_variance + 1e-12 < lo_variance:
        raise ValueError("surface has a calendar total-variance inversion")
    weight = (tenor - lo_t) / (hi_t - lo_t)
    variance = lo_variance + weight * (hi_variance - lo_variance)
    value = math.sqrt(max(variance, 0.0) / tenor)
    if not math.isfinite(value) or not 0.001 < value < 5.0:
        raise ValueError("surface interpolation produced invalid volatility")
    return value


def _book_vol_names(portfolio) -> list[str]:
    """Equity implied-vol identities eligible for own ATM-IV history."""
    out = []
    for pos in portfolio.positions:
        if pos.instrument not in _EQUITY_VOL_INSTRUMENTS:
            continue
        params = pos.params or {}
        components = _component_secids(params)
        if components and pos.instrument in (
                "spread", "basket", "multi_asset_autocall", "custom_product"):
            if pos.instrument in ("multi_asset_autocall", "custom_product"):
                kinds = _component_kinds(params)
                if len(kinds) != len(components):
                    raise ValueError(
                        f"{pos.id}: component_kinds has {len(kinds)} entries; "
                        f"expected {len(components)}")
                # Only equity/index components may consume the governed
                # IV30/RVI equity-vol route. Bond, generic future and commodity
                # model volatilities are calibrated inputs and stay fixed
                # unless an explicit named policy shock is supplied.
                out.extend(
                    secid for secid, kind in zip(components, kinds)
                    if kind in {"equity", "index"}
                )
            else:
                out.extend(components)
        elif params.get("secid"):
            out.append(str(params["secid"]))
    return sorted(set(out))


def _book_fx_pairs(portfolio) -> list[str]:
    out = []
    for pos in portfolio.positions:
        if pos.instrument.startswith(("fx", "ndf", "xccy")):
            pair = (pos.params or {}).get("ccy_pair") or pos.ccy_pair
            if pair:
                out.append(str(pair))
    return sorted(set(out))


def _ffill_levels(series: dict, dates: list[str]) -> dict:
    """Forward-fill a sparse level series onto the trading-date grid."""
    last = None
    if dates:
        prior_dates = [date for date, value in series.items()
                       if date < dates[0] and value > 0]
        if prior_dates:
            last = series[max(prior_dates)]
    out = {}
    for d in dates:
        if series.get(d, 0) > 0:
            last = series[d]
        if last is not None:
            out[d] = last
    return out


def factor_shifts(ctx, window: int = 500, frm: str | None = None,
                  till: str | None = None, portfolio=None,
                  horizon: int = 1, *,
                  _inside_read_snapshot: bool = False) -> dict:
    """Step 1 — shifts generation: aligned joint daily factor changes.
    ``frm``/``till`` clip to a fixed period (stress window) — then ``window``
    is ignored. Granular equity/FX factors follow the portfolio that will
    actually be repriced, not necessarily the persisted context book."""
    db = ctx.market_db
    read_snapshot = getattr(db, "read_snapshot", None)
    if not _inside_read_snapshot and callable(read_snapshot):
        with read_snapshot():
            return factor_shifts(
                ctx,
                window=window,
                frm=frm,
                till=till,
                portfolio=portfolio,
                horizon=horizon,
                _inside_read_snapshot=True,
            )
    factor_portfolio = portfolio if portfolio is not None else ctx.portfolio
    eq = dict(_series(db, "IMOEX:price"))
    kbd = dict(_series(db, "KBD:5Y"))
    kbd_tenors = {t: dict(_series(db, f"KBD:{t:g}Y")) for t in _KBD_TENORS}
    usd = dict(_series(db, "USDRUB:fix"))

    try:
        horizon = int(horizon)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("horizon must be a positive integer") from exc
    if horizon < 1:
        raise ValueError("horizon must be a positive integer")

    from datetime import date as _date, datetime as _datetime

    def _calendar_token(value, label: str) -> str | None:
        if value is None:
            return None
        if isinstance(value, _datetime):
            return value.date().isoformat()
        if isinstance(value, _date):
            return value.isoformat()
        if not isinstance(value, str):
            raise ValueError(f"{label} must be an ISO calendar date")
        token = value.strip()
        try:
            parsed = (
                _date.fromisoformat(token)
                if len(token) == 10
                else _datetime.fromisoformat(
                    token.replace("Z", "+00:00")
                ).date()
            )
            return parsed.isoformat()
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO calendar date") from exc

    frm_token = _calendar_token(frm, "frm")
    till_token = _calendar_token(till, "till")
    if frm_token and till_token and frm_token > till_token:
        raise ValueError("frm must not be after till")

    active_snapshot = getattr(factor_portfolio, "snapshot", None)
    if active_snapshot is None:
        active_snapshot = getattr(ctx, "snapshot", None)
    snapshot_cutoff = _calendar_token(
        getattr(active_snapshot, "valuation_date", None),
        "active snapshot valuation_date",
    )
    if snapshot_cutoff and till_token and till_token > snapshot_cutoff:
        raise ValueError(
            f"requested till {till_token} is after active snapshot valuation "
            f"date {snapshot_cutoff}")

    def _valid(value, *, max_value: float | None = None) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and number > 0 and (
            max_value is None or number <= max_value)

    # Coverage-first IV readiness (MR-8). Source selection happens only after
    # the requested rolling/stress calendar is known. Every endpoint must be
    # present, so a gap can never turn a multi-day IV move into a daily shock.
    master_dates = sorted(
        d for d in set(eq) & set(kbd)
        if _valid(eq[d]) and math.isfinite(float(kbd[d]))
        and (snapshot_cutoff is None or d <= snapshot_cutoff))
    if frm_token or till_token:
        master_dates = [d for d in master_dates
                        if (not frm_token or d >= frm_token)
                        and (not till_token or d <= till_token)]
    available_shocks = len(master_dates) - 1
    min_daily_shocks = max(60, horizon + 50 - 1)
    if available_shocks < min_daily_shocks:
        raise ValueError(
            "not enough joint factor history: "
            f"need {min_daily_shocks} daily shocks, got {max(available_shocks, 0)}")

    if frm_token or till_token:
        output_dates = master_dates
        check_dates = master_dates
    else:
        requested = available_shocks if not window else min(int(window), available_shocks)
        output_dates = master_dates[-(requested + 1):]
        coverage_shocks = max(min_daily_shocks, requested)
        check_dates = master_dates[-(coverage_shocks + 1):]

    def _source_diagnostic(factor_id: str, series: dict,
                           dates: list[str], max_value: float) -> dict:
        valid_levels = sum(
            1 for date in dates
            if date in series and _valid(series[date], max_value=max_value))
        valid_shocks = sum(
            1 for prev, cur in zip(dates, dates[1:])
            if (prev in series and cur in series
                and _valid(series[prev], max_value=max_value)
                and _valid(series[cur], max_value=max_value)))
        return {
            "source": factor_id,
            "raw_levels": len(series),
            "required_levels": len(dates),
            "aligned_levels": valid_levels,
            "valid_shocks": valid_shocks,
            "required_shocks": len(dates) - 1,
            "coverage": valid_levels / len(dates) if dates else 0.0,
            "ready": valid_levels == len(dates),
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
        }

    iv_candidates = []
    selected_vol = None
    selected_vol_id = None
    # The scalar equity factor is IMOEX, so only its approved MIX/MXI option
    # histories may replace the scalar RVI proxy. RTS belongs to RTSI and is
    # considered only in the per-underlying map below.
    # Canonical 30-calendar-day ATM-forward history is a separate series from
    # the legacy nearest-expiry representative. Never splice both methods into
    # one level series: prefer a complete IV30 calendar, then fall back to a
    # complete legacy calendar, and finally to the approved RVI proxy.
    iv_gate_as_of = (
        check_dates[-1]
        if frm_token or till_token
        else snapshot_cutoff or check_dates[-1]
    )
    iv_gate_max_staleness = 0 if frm_token or till_token else 4
    for iv_id in ("IV30:MIX", "IV30:MXI", "IV:MIX", "IV:MXI"):
        series = dict(_series(db, iv_id))
        diag = _source_diagnostic(iv_id, series, check_dates, 5.0)
        if iv_id.startswith("IV30:"):
            diag["coverage_ready"] = diag["ready"]
            gate = _iv30_consumer_readiness(
                db,
                iv_id,
                check_dates,
                as_of=iv_gate_as_of,
                max_staleness_days=iv_gate_max_staleness,
            ) if diag["ready"] else {
                "ready": False,
                "blockers": ["level_coverage_incomplete"],
            }
            diag["operational_readiness"] = gate
            diag["ready"] = bool(diag["ready"] and gate["ready"])
        iv_candidates.append(diag)
        if selected_vol is None and diag["ready"]:
            selected_vol, selected_vol_id = series, iv_id

    rvi = dict(_series(db, "RVI:price"))
    rvi_diag = _source_diagnostic("RVI:price", rvi, check_dates, 500.0)
    factor_warnings: list[str] = []
    if selected_vol is None:
        if not rvi_diag["ready"]:
            raise ValueError(
                "volatility history is not ready for the requested calendar: "
                "neither own IV nor approved RVI proxy has complete coverage")
        selected_vol, selected_vol_id = rvi, "RVI:price"
        factor_warnings.append(
            "Volatility: RVI proxy used because own index IV does not cover "
            f"all {len(check_dates) - 1} required daily shocks")
    elif selected_vol_id.startswith("IV:"):
        factor_warnings.append(
            f"Volatility: {selected_vol_id} is legacy nearest-expiry history; "
            "canonical IV30 history does not yet cover the requested calendar")

    for position in factor_portfolio.positions:
        if (position.instrument in ("spread", "basket")
                and not _component_secids(position.params or {})):
            factor_warnings.append(
                f"{position.id}: multi-asset component identity missing; "
                "global equity/vol proxies used")
        elif position.instrument in ("multi_asset_autocall", "custom_product"):
            params = position.params or {}
            components = _component_secids(params)
            kinds = _component_kinds(params)
            product_label = (
                "multi-asset autocall"
                if position.instrument == "multi_asset_autocall"
                else "custom product"
            )
            if not components:
                raise ValueError(
                    f"{position.id}: {product_label} requires explicit "
                    "component_secids for historical factor routing")
            if len(kinds) != len(components):
                raise ValueError(
                    f"{position.id}: component_kinds has {len(kinds)} entries; "
                    f"expected {len(components)}")
            for secid, kind in zip(components, kinds):
                if kind == "bond":
                    factor_warnings.append(
                        f"Bond {secid}: spot-like own price history is used; "
                        "model volatility is held fixed because equity-IV/RVI "
                        "proxy is forbidden")
                elif (position.instrument == "custom_product"
                      and kind in {"future", "commodity"}):
                    factor_warnings.append(
                        f"{kind.title()} {secid}: own spot-like history is used; "
                        "model volatility is held fixed because no governed "
                        "named volatility history is bound")

    vol_scale = 1.0 / 100.0 if selected_vol_id == "RVI:price" else 1.0
    if selected_vol_id == "RVI:price":
        vol_label = "RVI (vol proxy, Δ points)"
    elif selected_vol_id.startswith("IV30:"):
        vol_label = f"{selected_vol_id} (30d ATM-forward vol, ΔIV)"
    else:
        vol_label = f"{selected_vol_id} (legacy nearest-expiry vol, ΔIV)"
    dates = output_dates
    has_fx = len(usd) >= 60

    # A7 (validation report): forward-fill fixings onto the trading-date grid —
    # a fixing gap carries the level, and the change lands on the first date it
    # reappears (close-to-close over holidays), instead of fabricating a chain
    # of zero moves that damped FX vol (was 284/500 non-zero days).
    fx_level = _ffill_levels(usd, dates)

    # M3: per-name equity series for book holdings (fallback: IMOEX move);
    # per-pair FX for book currencies beyond USD/RUB.
    name_levels = {}
    component_kinds = _book_component_kinds(factor_portfolio)
    for secid in _book_secids(factor_portfolio):
        s = dict(_series(db, f"{secid}:price"))
        if all(d in s and _valid(s[d]) for d in dates):
            name_levels[secid] = s
        elif component_kinds.get(secid) not in {None, "equity", "index"}:
            kind = component_kinds[secid]
            raise ValueError(
                f"{kind.title()} {secid}: own price history is incomplete for "
                "the requested calendar; IMOEX proxy is forbidden")
        else:
            factor_warnings.append(
                f"Underlying {secid}: own price history incomplete; "
                "IMOEX proxy used")
    pair_levels = {}
    for pair in _book_fx_pairs(factor_portfolio):
        s = dict(_series(db, f"{pair.replace('/', '')}:fix"))
        if len(s) >= 60:
            filled = _ffill_levels(s, dates)
            if all(date in filled for date in dates):
                pair_levels[pair] = filled
                continue
        factor_warnings.append(
            f"FX {pair}: own fixing history incomplete; USD/RUB proxy used")

    # Per-underlying vega factors use the same coverage contract as the global
    # vol source. Missing exact IV remains an explicit proxy, never a silent
    # switch or a shortened scenario set.
    try:
        from api.underlying import EQUITY_TO_FORTS
    except Exception:
        EQUITY_TO_FORTS = {}
    vol_levels: dict[str, dict] = {}
    vol_name_diagnostics: dict[str, dict] = {}
    for secid in _book_vol_names(factor_portfolio):
        codes = []
        mapped = EQUITY_TO_FORTS.get(secid)
        if mapped:
            codes.append(mapped)
        if secid == "IMOEX":
            codes.extend(["MIX", "MXI"])
        elif secid == "RTSI":
            codes.append("RTS")
        elif not codes:
            codes.append(secid)
        seen = set()
        candidates = []
        factor_ids = ([f"IV30:{code}" for code in codes]
                      + [f"IV:{code}" for code in codes])
        for factor_id in factor_ids:
            if factor_id in seen:
                continue
            seen.add(factor_id)
            series = dict(_series(db, factor_id))
            diag = _source_diagnostic(factor_id, series, check_dates, 5.0)
            if factor_id.startswith("IV30:"):
                diag["coverage_ready"] = diag["ready"]
                gate = _iv30_consumer_readiness(
                    db,
                    factor_id,
                    check_dates,
                    as_of=iv_gate_as_of,
                    max_staleness_days=iv_gate_max_staleness,
                ) if diag["ready"] else {
                    "ready": False,
                    "blockers": ["level_coverage_incomplete"],
                }
                diag["operational_readiness"] = gate
                diag["ready"] = bool(diag["ready"] and gate["ready"])
            candidates.append(diag)
            if diag["ready"]:
                vol_levels[secid] = series
                break
        selected = next((d for d in candidates if d["ready"]), None)
        vol_name_diagnostics[secid] = {
            "selected_source": selected["source"] if selected else selected_vol_id,
            "fallback": selected is None,
            "method": (
                "constant_maturity_30d_atm_forward"
                if selected and selected["source"].startswith("IV30:")
                else "legacy_nearest_expiry"
                if selected else "proxy"
            ),
            "candidates": candidates,
        }
        if selected and selected["source"].startswith("IV:"):
            factor_warnings.append(
                f"Volatility {secid}: legacy nearest-expiry IV used because "
                "canonical IV30 history is incomplete")
        if selected is None:
            factor_warnings.append(
                f"Volatility {secid}: own IV history incomplete; "
                f"{selected_vol_id} proxy used")

    # MR-4B: named discount/projection curves use their own governed level
    # histories.  A generic RUB KBD scenario is still retained for legacy
    # scalar-rate positions, but it may not stand in for a named dependency.
    curve_requirements = _book_curve_requirements(factor_portfolio)
    curve_level_series: dict[str, dict[float, dict[str, float]]] = {}
    curve_diagnostics: dict[str, dict] = {}
    if curve_requirements:
        market = getattr(factor_portfolio, "market_data", None)
        snapshot = getattr(factor_portfolio, "snapshot", None)
        if market is None:
            market = getattr(ctx, "market", None)
        if snapshot is None:
            snapshot = getattr(ctx, "snapshot", None)
        if market is None or snapshot is None:
            raise ValueError(
                "named curve history requires the active market-data snapshot")

        for curve_id, required_tenor in sorted(curve_requirements.items()):
            try:
                curve = market.get_curve(curve_id, snapshot)
            except Exception as exc:
                raise ValueError(
                    f"named curve '{curve_id}' is unavailable in the active snapshot") from exc
            nodes = supported_curve_history_tenors(
                curve, required_tenor=required_tenor)
            node_series: dict[float, dict[str, float]] = {
                tenor: {} for tenor in nodes
            }
            node_diagnostics = []
            history_reader = getattr(db, "get_curve_history", None)
            history_source = "snapshot_curve_points"
            methods: set[str] = set()
            if callable(history_reader):
                observations = history_reader(
                    curve_id, frm=check_dates[0], till=check_dates[-1])
                for observation in observations:
                    day = str(observation.get("dt") or "")[:10]
                    if day not in check_dates:
                        continue
                    method = str(observation.get("method") or "unknown").lower()
                    methods.add(
                        "zero_curve_points"
                        if method in {"nss", "points", "zcyc"} else method)
                    points = observation.get("points") or []
                    try:
                        tenors = np.asarray(
                            [float(point["tenor"]) for point in points], dtype=float)
                        rates = np.asarray(
                            [float(point["zero_rate"]) for point in points], dtype=float)
                    except (KeyError, TypeError, ValueError, OverflowError) as exc:
                        raise ValueError(
                            f"named curve '{curve_id}' has invalid history on {day}") from exc
                    if (len(tenors) == 0 or len(tenors) != len(np.unique(tenors))
                            or not np.all(np.isfinite(tenors))
                            or not np.all(np.isfinite(rates))
                            or np.any(tenors <= 0) or np.any(np.abs(rates) > 5.0)):
                        raise ValueError(
                            f"named curve '{curve_id}' has invalid history on {day}")
                    order = np.argsort(tenors)
                    tenors, rates = tenors[order], rates[order]
                    if (nodes[0] < tenors[0] - 1e-12
                            or nodes[-1] > tenors[-1] + 1e-12):
                        continue  # coverage diagnostic below will fail the date
                    interpolated = np.interp(np.asarray(nodes), tenors, rates)
                    for tenor, value in zip(nodes, interpolated):
                        node_series[tenor][day] = float(value)
                if len(methods) > 1:
                    raise ValueError(
                        f"named curve '{curve_id}' history changes methodology "
                        f"inside the requested calendar: {', '.join(sorted(methods))}")
            else:
                # Compatibility for small external/fake adapters.  Production
                # MarketDataDB reads snapshot-bound grids above.
                history_source = "canonical_curve_node_series"
                for tenor in nodes:
                    node_series[tenor] = dict(
                        _series(db, curve_node_factor_id(curve_id, tenor)))

            missing = []
            for tenor, series in node_series.items():
                factor_id = curve_node_factor_id(curve_id, tenor)
                valid_levels = sum(
                    1 for day in check_dates
                    if day in series and math.isfinite(float(series[day]))
                    and abs(float(series[day])) <= 5.0
                )
                ready = valid_levels == len(check_dates)
                node_diagnostics.append({
                    "source": factor_id,
                    "tenor": tenor,
                    "raw_levels": len(series),
                    "required_levels": len(check_dates),
                    "aligned_levels": valid_levels,
                    "ready": ready,
                    "history_source": history_source,
                })
                if not ready:
                    missing.append(factor_id)
            curve_diagnostics[curve_id] = {
                "required_tenor": required_tenor,
                "nodes": node_diagnostics,
                "ready": not missing,
                "history_source": history_source,
                "methodology": next(iter(methods), None),
            }
            if missing:
                preview = ", ".join(missing[:3])
                suffix = "..." if len(missing) > 3 else ""
                raise ValueError(
                    f"named curve '{curve_id}' history is incomplete for the "
                    f"requested calendar: {preview}{suffix}; generic KBD proxy is forbidden")
            curve_level_series[curve_id] = node_series

    # Named vol surfaces are position-specific dependencies: two options on
    # the same SECID but different surface IDs or K/T nodes must not share one
    # per-underlying proxy.  Historical v1 is explicitly sticky-strike and
    # constant-maturity over verified raw FORTS observations.
    surface_requirements = _book_surface_requirements(factor_portfolio)
    surface_level_series: dict[str, dict[str, float]] = {}
    surface_diagnostics: dict[str, dict] = {}
    if surface_requirements:
        if active_snapshot is None:
            raise ValueError(
                "named surface history requires the active market-data snapshot")
        if snapshot_cutoff is None:
            raise ValueError(
                "named surface history requires a valid active snapshot date")
        from infra.moex_iss.vol_surface import (
            governed_snapshot_surface_error,
            primary_iv_provenance_error,
            vol_lineage_diagnostics,
        )

        raw_reader = getattr(db, "get_vol_points", None)
        observation_reader = getattr(db, "get_vol_point_observations", None)
        snapshot_id = getattr(active_snapshot, "snapshot_id", None)
        if (not snapshot_id or not callable(raw_reader)
                or not callable(observation_reader)):
            raise ValueError(
                "named surface base requires governed raw/provenance storage")
        current_raw_points = raw_reader(snapshot_id)
        current_observations = observation_reader(snapshot_id)
        current_lineage = vol_lineage_diagnostics(
            current_raw_points, current_observations)
        if not current_lineage["payload_match_complete"]:
            raise ValueError(
                "active named surface raw/provenance payload is not governed")

        current_surfaces = getattr(active_snapshot, "vol_surfaces", {}) or {}
        for dependency in surface_requirements.values():
            surface_id = dependency["surface_id"]
            suffix = "_FORTS"
            expected_underlying = (
                surface_id[:-len(suffix)] if surface_id.endswith(suffix) else "")
            current_surface = current_surfaces.get(surface_id)
            governed_grid = (
                bool(expected_underlying)
                and isinstance(current_surface, dict)
                and current_surface.get("type") == "grid"
                and current_surface.get("source") == "MOEX_FORTS"
                and str(current_surface.get("underlying") or "")
                == expected_underlying
                and isinstance(current_surface.get("points"), (list, tuple))
                and bool(current_surface.get("points"))
            )
            if not governed_grid:
                raise ValueError(
                    f"named surface '{surface_id}' is not a governed FORTS "
                    "grid identity in the active snapshot")
            current_error = governed_snapshot_surface_error(
                current_raw_points,
                current_observations,
                surface_id,
                current_surface,
                snapshot_cutoff,
            )
            if current_error:
                raise ValueError(
                    f"named surface '{surface_id}' active provenance is invalid: "
                    + current_error)
        history_reader = getattr(db, "get_vol_surface_history", None)
        if not callable(history_reader):
            raise ValueError(
                "named surface history requires governed point-provenance storage")

        for position_id, dependency in sorted(surface_requirements.items()):
            surface_id = dependency["surface_id"]
            observations = history_reader(
                surface_id, frm=check_dates[0], till=check_dates[-1])
            by_date = {str(row.get("dt") or "")[:10]: row
                       for row in observations}
            levels: dict[str, float] = {}
            rejected: dict[str, str] = {}
            for day in check_dates:
                observation = by_date.get(day)
                if observation is None:
                    rejected[day] = "missing_observation"
                    continue
                points = observation.get("points") or []
                provenance_errors = sorted(set(
                    error for point in points
                    if (error := primary_iv_provenance_error(point, day))
                ))
                if provenance_errors:
                    rejected[day] = "provenance:" + ",".join(provenance_errors)
                    continue
                try:
                    levels[day] = _sticky_strike_surface_level(
                        points, day, dependency["K"], dependency["T"])
                except ValueError as exc:
                    rejected[day] = str(exc)
            ready = len(levels) == len(check_dates)
            surface_diagnostics[position_id] = {
                **dependency,
                "methodology": "sticky_strike_constant_maturity_total_variance",
                "required_levels": len(check_dates),
                "aligned_levels": len(levels),
                "ready": ready,
                "rejected": rejected,
            }
            if not ready:
                first_day = next(iter(rejected), check_dates[0])
                reason = rejected.get(first_day, "missing_observation")
                raise ValueError(
                    f"named surface '{surface_id}' history for position "
                    f"'{position_id}' is incomplete on {first_day}: {reason}; "
                    "IV30/RVI proxy is forbidden")
            surface_level_series[position_id] = levels

    out_dates, previous_dates, eq_ret, dr, dvol, fx_ret = [], [], [], [], [], []
    dr_tenors: dict[float, list] = {t: [] for t in _KBD_TENORS}
    dr_curves: dict[str, dict[float, list]] = {
        curve_id: {tenor: [] for tenor in nodes}
        for curve_id, nodes in curve_level_series.items()
    }
    eq_names: dict[str, list] = {s: [] for s in name_levels}
    vol_names: dict[str, list] = {s: [] for s in vol_levels}
    dvol_positions: dict[str, list] = {
        position_id: [] for position_id in surface_level_series
    }
    fx_pairs: dict[str, list] = {p: [] for p in pair_levels}
    for prev, cur in zip(dates, dates[1:]):
        if eq[prev] <= 0 or eq[cur] <= 0:
            continue
        previous_dates.append(prev)
        out_dates.append(cur)
        eq_move = math.log(eq[cur] / eq[prev])
        eq_ret.append(eq_move)
        dr.append(kbd[cur] - kbd[prev])                 # КБД already decimal
        for t in _KBD_TENORS:
            s = kbd_tenors[t]
            dr_tenors[t].append(s[cur] - s[prev]
                                if (prev in s and cur in s)
                                else kbd[cur] - kbd[prev])   # fallback 5Y
        for curve_id, nodes in curve_level_series.items():
            for tenor, series in nodes.items():
                dr_curves[curve_id][tenor].append(
                    series[cur] - series[prev])
        dvol.append((selected_vol[cur] - selected_vol[prev]) * vol_scale)
        if has_fx and fx_level.get(prev) and fx_level.get(cur):
            fx_ret.append(math.log(fx_level[cur] / fx_level[prev]))
        else:
            fx_ret.append(0.0)
        for secid, s in name_levels.items():
            eq_names[secid].append(math.log(s[cur] / s[prev])
                                   if (s.get(prev, 0) > 0 and s.get(cur, 0) > 0)
                                   else eq_move)          # fallback: индекс
        for secid, s in vol_levels.items():
            vol_names[secid].append(s[cur] - s[prev])
        for position_id, series in surface_level_series.items():
            dvol_positions[position_id].append(series[cur] - series[prev])
        for pair, s in pair_levels.items():
            fx_pairs[pair].append(math.log(s[cur] / s[prev])
                                  if (s.get(prev) and s.get(cur))
                                  else fx_ret[-1])
    factors = ["IMOEX (equity, log-return)"
               + (f" + per-name: {', '.join(eq_names)}" if eq_names else ""),
               f"КБД {len(_KBD_TENORS)} теноров (rates, bucketed by maturity)",
               vol_label
               + (f" + per-underlying: {', '.join(vol_names)}" if vol_names else ""),
               ("USD/RUB fix (fx, log-return)"
                + (f" + {', '.join(p for p in fx_pairs if p != 'USD/RUB')}"
                   if any(p != "USD/RUB" for p in fx_pairs) else ""))
               if has_fx else "FX (no history — zero)"]
    if dr_curves:
        factors[1] += " + named curves: " + ", ".join(sorted(dr_curves))
    if dvol_positions:
        factors[2] += " + named surface positions: " + ", ".join(
            sorted(dvol_positions))
    return {
        "dates": out_dates,
        # Exact scenario-start session for each daily return.  This is
        # intentionally carried separately from the end-date label: actual
        # lifecycle backcast must reconstruct state at the window start,
        # before applying the first observed return.
        "previous_dates": previous_dates,
        "eq": np.array(eq_ret), "dr": np.array(dr), "dvol": np.array(dvol),
        "fx": np.array(fx_ret),
        "dr_tenors": {t: np.array(v) for t, v in dr_tenors.items()},
        "dr_curves": {
            curve_id: {tenor: np.array(values) for tenor, values in nodes.items()}
            for curve_id, nodes in dr_curves.items()
        },
        "eq_names": {s: np.array(v) for s, v in eq_names.items()},
        "vol_names": {s: np.array(v) for s, v in vol_names.items()},
        "dvol_positions": {
            position_id: np.array(values)
            for position_id, values in dvol_positions.items()
        },
        "fx_pairs": {p: np.array(v) for p, v in fx_pairs.items()},
        "factors": factors,
        "has_fx": has_fx,
        "factor_warnings": sorted(set(factor_warnings)),
        "factor_diagnostics": {
            "volatility": {
                "selected_source": selected_vol_id,
                "fallback": selected_vol_id == "RVI:price",
                "method": (
                    "constant_maturity_30d_atm_forward"
                    if selected_vol_id.startswith("IV30:")
                    else "legacy_nearest_expiry"
                    if selected_vol_id.startswith("IV:") else "proxy"
                ),
                "required_daily_shocks": len(check_dates) - 1,
                "requested_window": int(window),
                "horizon": horizon,
                "period": {"from": frm, "till": till},
                "candidates": iv_candidates,
                "rvi": rvi_diag,
                "per_underlying": vol_name_diagnostics,
            },
            "curves": curve_diagnostics,
            "surfaces": surface_diagnostics,
        },
    }


def _validated_reprice_pnl(result, *, context: str) -> float:
    """Return a finite scenario P&L or fail closed with caller context.

    ``PortfolioService.full_reprice_pnl`` historically returned the P&L of
    the successfully-priced subset together with ``errors``.  A Market Risk
    consumer must never turn that partial result into VaR/ES.  Keep the
    producer's diagnostic payload compatible, but make every risk workflow
    reject errors, an explicit invalid flag, missing values and non-finite
    values before the observation enters a distribution.
    """
    if not isinstance(result, dict) or not result:
        raise ValueError(f"{context}: empty or invalid reprice result")

    raw_errors = result.get("errors") or []
    if isinstance(raw_errors, str):
        raw_errors = [raw_errors]
    errors = [str(error) for error in raw_errors if error not in (None, "")]
    if errors:
        raise ValueError(f"{context}: " + "; ".join(errors))
    if result.get("valid") is False:
        raise ValueError(f"{context}: reprice result is marked invalid")
    if "pnl" not in result:
        raise ValueError(f"{context}: reprice result has no P&L")

    def finite_scalar(value, label: str) -> float:
        try:
            array = np.asarray(value)
            if array.ndim != 0:
                raise TypeError
            number = float(array)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{context}: {label} is not a scalar") from exc
        if not math.isfinite(number):
            raise ValueError(f"{context}: {label} is non-finite")
        return number

    pnl = finite_scalar(result["pnl"], "P&L")
    for key, label in (("base_value", "base value"),
                       ("shocked_value", "shocked value")):
        if key in result:
            finite_scalar(result[key], label)
    return pnl


def _validated_hyppl(hp, *, context: str) -> np.ndarray:
    """Validate a complete HypPL contract before any statistic is computed."""
    if not isinstance(hp, dict) or not hp:
        raise ValueError(f"{context}: empty or invalid HypPL result")
    raw_errors = hp.get("reprice_errors") or []
    if isinstance(raw_errors, str):
        raw_errors = [raw_errors]
    errors = [str(error) for error in raw_errors if error not in (None, "")]
    if errors:
        raise ValueError(f"{context}: repricing failed: " + "; ".join(errors))
    if hp.get("valid") is False:
        raise ValueError(f"{context}: HypPL result is marked invalid")
    if "pnl" not in hp:
        raise ValueError(f"{context}: HypPL result has no P&L series")
    try:
        pnl = np.asarray(hp["pnl"], dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{context}: HypPL series is not numeric") from exc
    if pnl.ndim != 1 or pnl.size == 0:
        raise ValueError(f"{context}: HypPL must be a non-empty one-dimensional series")
    if not np.all(np.isfinite(pnl)):
        raise ValueError(f"{context}: HypPL contains non-finite values")
    dates = hp.get("dates")
    if not isinstance(dates, (list, tuple)) or len(dates) != len(pnl):
        raise ValueError(f"{context}: HypPL dates and values must have equal length")
    return pnl


def _contract_digest(payload) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _slice_actual_scenarios(shifts: dict, indices: list[int]) -> dict:
    """Slice every scenario-aligned factor/path array by one exact index set."""
    out = dict(shifts)

    def sliced(values):
        if isinstance(values, np.ndarray):
            return values[np.asarray(indices, dtype=int)]
        if isinstance(values, (list, tuple)):
            return [values[index] for index in indices]
        raise ValueError("actual backcast factor array is not scenario-aligned")

    for key in ("dates", "previous_dates", "eq", "dr", "dvol", "fx"):
        if key in shifts:
            out[key] = sliced(shifts[key])
    for key in ("dr_tenors", "eq_names", "vol_names",
                "dvol_positions", "fx_pairs"):
        out[key] = {
            name: sliced(values)
            for name, values in (shifts.get(key) or {}).items()
        }
    out["dr_curves"] = {
        curve_id: {
            tenor: sliced(values)
            for tenor, values in nodes.items()
        }
        for curve_id, nodes in (shifts.get("dr_curves") or {}).items()
    }
    paths = shifts.get("spot_return_paths") or {}
    out["spot_return_paths"] = {
        **paths,
        "dates": sliced(paths.get("dates") or []),
        "start_dates": sliced(paths.get("start_dates") or []),
        "fallback_log_returns": sliced(
            paths.get("fallback_log_returns") or []),
        "log_returns_by_factor": {
            name: sliced(values)
            for name, values in (paths.get("log_returns_by_factor") or {}).items()
        },
    }
    return out


def _actual_state_matches(reconstructed: dict, captured: dict) -> bool:
    """Compare lifecycle economics while ignoring independently sourced hashes."""
    if not isinstance(reconstructed, dict) or not isinstance(captured, dict):
        return False
    for key in ("mode", "asset_names", "observation_index", "alive", "state_as_of"):
        if reconstructed.get(key) != captured.get(key):
            return False
    for key in ("elapsed_time",):
        try:
            if not math.isclose(
                    float(reconstructed.get(key)), float(captured.get(key)),
                    rel_tol=0.0, abs_tol=1e-12):
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    for key in ("current_spots", "reference_spots", "running_min",
                "running_max", "state_values"):
        left = reconstructed.get(key)
        right = captured.get(key)
        if not isinstance(left, dict) or not isinstance(right, dict) \
                or set(left) != set(right):
            return False
        try:
            if any(not math.isclose(
                    float(left[name]), float(right[name]),
                    rel_tol=0.0, abs_tol=1e-12) for name in left):
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return True


def _clone_portfolio_for_backcast(ps):
    """Clone positions without copying DB connections/locks owned by services."""
    from services.portfolio_service import PortfolioService

    prepared = PortfolioService(
        market_data=ps.market_data,
        pricing=ps.pricing,
        audit=ps.audit,
        snapshot=ps.snapshot,
    )
    source_portfolio = getattr(ps, "portfolio", None)
    target_portfolio = prepared.portfolio
    for attr in ("portfolio_id", "name", "base_currency"):
        if source_portfolio is not None and hasattr(source_portfolio, attr):
            setattr(target_portfolio, attr, getattr(source_portfolio, attr))
    for position in _portfolio_positions(ps):
        prepared.add(copy.deepcopy(position))
    return prepared


def _prepare_actual_trade_backcast(ctx, ps, shifts: dict) -> tuple[object, dict]:
    """Bind exact MOEX sessions/fixings and reconcile the current trade state.

    This is intentionally performed after horizon aggregation: scenario start
    and end dates are then final, and a single immutable fixing ledger can be
    shared across all scenarios of one position.  Only pre-effective windows
    may be removed; any in-life calendar/fixing gap fails the whole request.
    """
    positions = _portfolio_positions(ps)
    if not positions or any(
            getattr(position, "instrument", None) != "custom_product"
            for position in positions):
        raise ValueError(
            "actual_trade_backcast supports all-custom_product books only")
    position_ids = [str(getattr(position, "id", "") or "") for position in positions]
    if any(not value for value in position_ids) or len(set(position_ids)) != len(position_ids):
        raise ValueError(
            "actual_trade_backcast requires unique non-empty position ids")

    paths = shifts.get("spot_return_paths") or {}
    dates = list(shifts.get("dates") or [])
    starts = list(paths.get("start_dates") or [])
    path_dates = list(paths.get("dates") or [])
    if (paths.get("schema") != "historical-spot-return-paths-v1"
            or len(starts) != len(dates) or len(path_dates) != len(dates)
            or not dates or any(not isinstance(value, str) or not value
                                for value in starts)):
        raise ValueError(
            "actual_trade_backcast requires aligned exact scenario start/end dates")

    db = getattr(ctx, "market_db", None)
    if db is None:
        db = getattr(getattr(ps, "market_data", None), "market_db", None)
    if db is None:
        raise ValueError(
            "actual_trade_backcast requires the governed market-data database")

    from api import custom_products
    from infra.moex_calendar import MoexCalendarResolver

    store = custom_products.get_store()
    specifications: list[dict] = []
    calendar_signature = None
    max_effective = ""
    common_cutoff = None
    for position in positions:
        params = getattr(position, "params", None) or {}
        schedule_raw = params.get("contract_schedule")
        bindings_raw = params.get("fixing_bindings")
        seed_raw = params.get("inception_seed")
        if not all(isinstance(value, dict) for value in (
                schedule_raw, bindings_raw, seed_raw)):
            raise ValueError(
                f"{position.id}: actual_trade_backcast requires schedule, "
                "fixing bindings and inception seed")
        product_id = str(params.get("custom_product_id") or "")
        version = params.get("definition_version")
        detail = store.get_version(product_id, version)
        if detail.get("definition_hash") != params.get("definition_hash"):
            raise ValueError(
                f"{position.id}: actual backcast definition hash mismatch")
        definition = detail["definition"]
        schedule = custom_products.canonical_instance_contract_schedule(
            definition, schedule_raw, slots=params.get("slots") or {})
        if schedule != schedule_raw:
            raise ValueError(
                f"{position.id}: contract schedule is not canonical")
        calendar = schedule["calendar"]
        try:
            calendar_version = int(calendar["version"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"{position.id}: calendar version is invalid") from exc
        resolver = MoexCalendarResolver.from_db(
            db, str(calendar["calendar_id"]), calendar_version)
        signature = (
            resolver.calendar_id, resolver.version, resolver.payload_hash)
        if calendar_signature is None:
            calendar_signature = signature
        elif signature != calendar_signature:
            raise ValueError(
                "actual_trade_backcast requires one pinned MOEX calendar version")
        if (calendar.get("source_hash") != resolver.payload_hash
                or calendar.get("payload_hash") != resolver.payload_hash):
            raise ValueError(
                f"{position.id}: calendar payload differs from the governed DB version")
        expected_sessions = [
            day.isoformat() for day in resolver.business_sessions(
                schedule["effective_date"], schedule["maturity_date"])
        ]
        if expected_sessions != calendar.get("resolved_sessions"):
            raise ValueError(
                f"{position.id}: resolved contract sessions differ from MOEX calendar")

        bindings_payload = dict(bindings_raw)
        supplied_bindings_hash = str(
            bindings_payload.pop("bindings_hash", "") or "")
        if (_contract_digest(bindings_payload) != supplied_bindings_hash
                or bindings_raw.get("contract")
                != "moex_exact_fixing_bindings_v1"
                or bindings_raw.get("schedule_hash") != schedule["schedule_hash"]
                or bindings_raw.get("calendar_id") != resolver.calendar_id
                or int(bindings_raw.get("calendar_version", -1)) != resolver.version
                or bindings_raw.get("calendar_payload_hash") != resolver.payload_hash):
            raise ValueError(
                f"{position.id}: exact fixing binding hash/calendar mismatch")
        asset_names = list(params.get("asset_names") or [])
        raw_rows = bindings_raw.get("bindings")
        if (not isinstance(raw_rows, list) or len(raw_rows) != len(asset_names)
                or bindings_raw.get("asset_names") != asset_names):
            raise ValueError(
                f"{position.id}: exact fixing bindings are not asset-aligned")
        binding_by_asset = {
            str(row.get("asset_name") or ""): row
            for row in raw_rows if isinstance(row, dict)
        }
        if set(binding_by_asset) != set(asset_names):
            raise ValueError(
                f"{position.id}: exact fixing binding asset set mismatch")
        for asset_name, secid in zip(
                asset_names, list(params.get("component_secids") or [])):
            binding = binding_by_asset[asset_name]
            if (binding.get("secid") != secid
                    or binding.get("factor_id") != f"{secid}:price"
                    or binding.get("source") != "MOEX"
                    or binding.get("missing_fixing_policy") != "error"):
                raise ValueError(
                    f"{position.id}: exact fixing identity mismatch for {asset_name}")

        captured_state = params.get("valuation_state")
        if not isinstance(captured_state, dict):
            raise ValueError(
                f"{position.id}: captured valuation state is missing")
        cutoff = str(captured_state.get("state_as_of") or "")
        if cutoff not in expected_sessions:
            raise ValueError(
                f"{position.id}: captured state_as_of is not a MOEX contract session")
        max_effective = max(max_effective, schedule["effective_date"])
        common_cutoff = cutoff if common_cutoff is None else min(common_cutoff, cutoff)
        specifications.append({
            "position_id": position.id,
            "definition": definition,
            "params": params,
            "schedule": schedule,
            "bindings": bindings_raw,
            "binding_by_asset": binding_by_asset,
            "seed": seed_raw,
            "captured_state": captured_state,
            "resolver": resolver,
        })

    retained = [index for index, start in enumerate(starts)
                if start >= max_effective]
    dropped_pre_effective = len(dates) - len(retained)
    if not retained:
        raise ValueError(
            "actual_trade_backcast has no scenarios on or after trade effective date")
    for index in retained:
        if dates[index] > str(common_cutoff):
            raise ValueError(
                "actual_trade_backcast scenario end is after captured trade state")
        for spec in specifications:
            sessions = spec["schedule"]["calendar"]["resolved_sessions"]
            start = starts[index]
            end = dates[index]
            if start not in sessions or end not in sessions:
                raise ValueError(
                    f"{spec['position_id']}: scenario endpoint is outside contract sessions")
            left = sessions.index(start)
            right = sessions.index(end)
            expected_path = sessions[left + 1:right + 1]
            if right <= left or list(path_dates[index]) != expected_path:
                raise ValueError(
                    f"{spec['position_id']}: historical scenario skips a MOEX session")
    if len(retained) < 60:
        raise ValueError(
            "actual_trade_backcast requires at least 60 post-effective scenarios; "
            f"got {len(retained)}")

    prepared = _clone_portfolio_for_backcast(ps)
    prepared_by_id = {
        str(position.id): position for position in _portfolio_positions(prepared)
    }
    position_evidence = []
    for spec in specifications:
        schedule = spec["schedule"]
        captured_state = spec["captured_state"]
        required_end = str(captured_state["state_as_of"])
        sessions = [
            value for value in schedule["calendar"]["resolved_sessions"]
            if schedule["effective_date"] <= value <= required_end
        ]
        exact_by_asset: dict[str, dict[str, dict]] = {}
        provenance_rows = []
        for asset_name in spec["params"]["asset_names"]:
            binding = spec["binding_by_asset"][asset_name]
            rows = db.get_contract_fixings_window(
                binding["factor_id"], schedule["effective_date"], required_end,
                price_basis=binding["price_basis"],
                source=binding["source"], board=binding["board"],
                session=binding["session"],
            )
            by_date = {}
            for row in rows:
                semantic = {
                    "factor_id": str(row.get("factor_id") or ""),
                    "observed_date": str(row.get("observed_date") or ""),
                    "value": float(row.get("value")),
                    "price_basis": str(row.get("price_basis") or "").upper(),
                    "board": str(row.get("board") or "").upper(),
                    "session": str(row.get("session") or "").upper(),
                    "source": str(row.get("source") or "").upper(),
                }
                if (not math.isfinite(semantic["value"])
                        or semantic["value"] <= 0.0
                        or any(semantic[key] != binding[key] for key in (
                            "factor_id", "price_basis", "board", "session", "source"))
                        or _contract_digest(semantic)
                        != str(row.get("payload_hash") or "")):
                    raise ValueError(
                        f"{spec['position_id']}: fixing semantic hash/identity "
                        f"failed for {asset_name} {semantic['observed_date']}")
                physical_date = semantic["observed_date"]
                session_date = spec["resolver"].session_date_for(physical_date)
                if session_date is None:
                    raise ValueError(
                        f"{spec['position_id']}: fixing exists on a closed MOEX "
                        f"calendar date {physical_date}")
                session_token = session_date.isoformat()
                # MOEX reason=W rows belong to a later named session.  They are
                # audit evidence but not a second contractual fixing; the row
                # observed on the named session date is the authoritative close.
                if physical_date == session_token and session_token in sessions:
                    if session_token in by_date:
                        raise ValueError(
                            f"{spec['position_id']}: duplicate exact fixing for "
                            f"{asset_name} {session_token}")
                    by_date[session_token] = row
                provenance_rows.append({
                    **semantic,
                    "official_session_date": session_token,
                    "collapsed_weekend_session": physical_date != session_token,
                    "payload_hash": str(row.get("payload_hash") or ""),
                    "fetched_at": str(row.get("fetched_at") or ""),
                })
            missing = [value for value in sessions if value not in by_date]
            if missing:
                raise ValueError(
                    f"{spec['position_id']}: exact fixing coverage failed for "
                    f"{asset_name}; missing={missing[:5]}")
            exact_by_asset[asset_name] = by_date

        fixings = [{
            "date": value,
            "spots": {
                asset_name: float(exact_by_asset[asset_name][value]["value"])
                for asset_name in spec["params"]["asset_names"]
            },
        } for value in sessions]
        manifest = {
            "contract": "market_data_db_exact_fixings_v1",
            "calendar_id": schedule["calendar"]["calendar_id"],
            "calendar_version": schedule["calendar"]["version"],
            "calendar_payload_hash": schedule["calendar"]["payload_hash"],
            "bindings_hash": spec["bindings"]["bindings_hash"],
            "rows": sorted(provenance_rows, key=lambda row: (
                row["observed_date"], row["factor_id"], row["price_basis"],
                row["board"], row["session"], row["source"])),
        }
        raw_ledger = {
            "source": "MarketDataDB exact MOEX contract_fixings",
            "source_version": (
                "contract_fixings_v1:"
                + spec["bindings"]["bindings_hash"]),
            "payload_hash": _contract_digest(manifest),
            "fixings": fixings,
        }
        ledger = custom_products.canonical_dated_fixing_ledger(
            spec["definition"], schedule, raw_ledger,
            slots=spec["params"].get("slots") or {},
        )
        reconciliation = custom_products.reconstruct_historical_valuation_state(
            spec["definition"], schedule, spec["seed"], ledger, required_end,
            slots=spec["params"].get("slots") or {},
        )
        if reconciliation.get("terminal") or not _actual_state_matches(
                reconciliation.get("valuation_state"), captured_state):
            raise ValueError(
                f"{spec['position_id']}: reconstructed current lifecycle state "
                "does not match the captured seasoned state")
        backcast_payload = {
            "schema": "custom-product-actual-backcast-v1",
            "contract_schedule": schedule,
            "inception_seed": spec["seed"],
            "fixing_ledger": ledger,
        }
        backcast = {
            **backcast_payload,
            "contract_hash": _contract_digest(backcast_payload),
        }
        prepared_by_id[str(spec["position_id"])].params[
            "historical_backcast_contract"] = backcast
        position_evidence.append({
            "position_id": str(spec["position_id"]),
            "schedule_hash": schedule["schedule_hash"],
            "bindings_hash": spec["bindings"]["bindings_hash"],
            "inception_seed_hash": spec["seed"].get("seed_hash"),
            "fixing_ledger_hash": ledger["ledger_hash"],
            "fixing_source_hash": ledger["source_hash"],
            "backcast_contract_hash": backcast["contract_hash"],
            "current_state_reconciliation_hash": _contract_digest(
                reconciliation["evidence"]),
        })

    prepared_shifts = _slice_actual_scenarios(shifts, retained)
    prepared_shifts["actual_trade_backcast"] = {
        "schema": "actual-trade-state-backcast-scenarios-v1",
        "calendar_id": calendar_signature[0],
        "calendar_version": calendar_signature[1],
        "calendar_payload_hash": calendar_signature[2],
        "dropped_pre_effective_scenarios": dropped_pre_effective,
        "scenario_count": len(retained),
        "positions": position_evidence,
        "non_spot_market_parameter_basis": (
            "current_snapshot_levels_plus_historical_rate_vol_changes"),
    }
    prepared_shifts["factors"] = list(shifts.get("factors") or [])
    return prepared, prepared_shifts


def _reprice_series(
    ps,
    shifts: dict,
    *,
    custom_repricing_profile: str | None = None,
    evidence: dict | None = None,
    deadline_seconds: float | None = None,
    horizon: int = 1,
    historical_state_mode: str = "current_state_hyppl",
) -> tuple[np.ndarray, set[str]]:
    dates = list(shifts.get("dates") or [])
    previous_dates = list(shifts.get("previous_dates") or [])
    if previous_dates and len(previous_dates) != len(dates):
        raise ValueError("previous_dates length does not match factor dates")
    if not dates:
        raise ValueError("historical full reprice: scenario set is empty")
    has_custom = _portfolio_has_custom_product(ps)
    if historical_state_mode not in {
            "current_state_hyppl", "actual_trade_backcast"}:
        raise ValueError(
            "historical full reprice: unsupported historical_state_mode")
    if historical_state_mode == "actual_trade_backcast" and not has_custom:
        raise ValueError(
            "historical full reprice: actual_trade_backcast requires a "
            "custom_product lifecycle contract")
    if historical_state_mode == "actual_trade_backcast" and any(
            getattr(position, "instrument", None) != "custom_product"
            for position in _portfolio_positions(ps)):
        raise ValueError(
            "historical full reprice: actual_trade_backcast supports "
            "all-custom_product books only")
    if historical_state_mode == "actual_trade_backcast" and not previous_dates:
        raise ValueError(
            "historical full reprice: actual_trade_backcast requires exact "
            "scenario start dates")
    if custom_repricing_profile is not None:
        if custom_repricing_profile != CUSTOM_HISTORICAL_REPRICING_PROFILE:
            raise ValueError(
                "historical full reprice: unsupported custom repricing profile "
                f"'{custom_repricing_profile}'")
        if not has_custom:
            raise ValueError(
                "historical full reprice: custom repricing profile was supplied "
                "for a book without custom_product positions")
    elif has_custom:
        # All direct Market Risk entry points inherit the same production-safe
        # inner profile.  Pricing_new passes it explicitly and verifies the
        # evidence, while legacy callers still cannot accidentally launch the
        # high-fidelity attachment grid once per historical observation.
        custom_repricing_profile = CUSTOM_HISTORICAL_REPRICING_PROFILE

    started = time.monotonic()
    if deadline_seconds is not None:
        try:
            deadline_seconds = float(deadline_seconds)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "historical full reprice: deadline_seconds must be positive") from exc
        if not math.isfinite(deadline_seconds) or deadline_seconds <= 0.0:
            raise ValueError(
                "historical full reprice: deadline_seconds must be positive")

    pnl = np.empty(len(dates))
    dr_tenors = shifts.get("dr_tenors") or {}
    dr_curves = shifts.get("dr_curves") or {}
    eq_names = shifts.get("eq_names") or {}
    vol_names = shifts.get("vol_names") or {}
    dvol_positions = shifts.get("dvol_positions") or {}
    fx_pairs = shifts.get("fx_pairs") or {}
    spot_return_paths = shifts.get("spot_return_paths") or {}
    if has_custom:
        if spot_return_paths.get("schema") != "historical-spot-return-paths-v1":
            raise ValueError(
                "historical full reprice: custom products require sequential "
                "spot-return paths")
        if spot_return_paths.get("day_count_basis") != 252:
            raise ValueError(
                "historical full reprice: custom sequential paths require "
                "business/252 time roll")
        path_dates = list(spot_return_paths.get("dates") or [])
        fallback_paths = list(spot_return_paths.get("fallback_log_returns") or [])
        named_paths = spot_return_paths.get("log_returns_by_factor") or {}
        path_start_dates = list(spot_return_paths.get("start_dates") or [])
        if (len(path_dates) != len(dates) or len(fallback_paths) != len(dates)
                or len(path_start_dates) != len(dates)
                or any(len(values) != len(dates)
                       for values in named_paths.values())):
            raise ValueError(
                "historical full reprice: sequential spot paths are not aligned "
                "with scenario endpoints")
    warnings: set[str] = set()
    base_value_sources: set[str] = set()
    profile_base_value: float | None = None
    ordinary_base_value: float | None = None
    path_roll_hashes: list[str] = []
    path_roll_evidence: list[dict] = []
    actual_backcast_evidence: list[dict] = []
    scenario_base_values: list[float] = []
    custom_position_count = sum(
        getattr(position, "instrument", None) == "custom_product"
        for position in _portfolio_positions(ps)
    )
    for i in range(len(pnl)):
        elapsed = time.monotonic() - started
        if deadline_seconds is not None and elapsed > deadline_seconds:
            raise TimeoutError(
                "historical full reprice deadline exceeded before scenario "
                f"{i} ({elapsed:.3f}s > {deadline_seconds:.3f}s)")
        scenario_context = (
            f"historical full reprice scenario {i} ({dates[i]})")
        try:
            kwargs = dict(
                dS=float(shifts["eq"][i]), dr=float(shifts["dr"][i]),
                dvol=float(shifts["dvol"][i]), dfx=float(shifts["fx"][i]),
                dr_curve=[(t, float(v[i])) for t, v in dr_tenors.items()] or None,
                dr_curves={
                    curve_id: [(tenor, float(values[i]))
                               for tenor, values in nodes.items()]
                    for curve_id, nodes in dr_curves.items()
                } if dr_curves else None,
                dS_by_name={s: float(v[i]) for s, v in eq_names.items()} or None,
                dvol_by_name={s: float(v[i]) for s, v in vol_names.items()} or None,
                dvol_by_position={position_id: float(values[i])
                                  for position_id, values in dvol_positions.items()} or None,
                dfx_by_pair={p: float(v[i]) for p, v in fx_pairs.items()} or None,
                spot_shock_convention="log",
            )
            if custom_repricing_profile is not None:
                kwargs["custom_repricing_profile"] = custom_repricing_profile
                kwargs["custom_path_scenario"] = {
                    "schema": "historical-custom-spot-path-v1",
                    "day_count_basis": int(
                        spot_return_paths.get("day_count_basis", 252)),
                    "dates": list(path_dates[i]),
                    "fallback_log_returns": list(fallback_paths[i]),
                    "log_returns_by_factor": {
                        factor_id: list(values[i])
                        for factor_id, values in named_paths.items()
                    },
                }
                if historical_state_mode == "actual_trade_backcast":
                    kwargs["custom_path_scenario"].update({
                        "start_date": previous_dates[i],
                        "end_date": dates[i],
                    })
            elif ordinary_base_value is not None:
                # For ordinary books the first scenario establishes the exact
                # static-book base PV.  Reuse it on later observations; every
                # shocked book is still fully repriced.
                kwargs["base_value_override"] = ordinary_base_value
            kwargs["horizon"] = int(horizon)
            kwargs["historical_state_mode"] = historical_state_mode
            res = ps.full_reprice_pnl(**kwargs)
        except Exception as exc:
            raise ValueError(f"{scenario_context}: {exc}") from exc
        pnl[i] = _validated_reprice_pnl(res, context=scenario_context)
        if not isinstance(res, dict):
            raise ValueError(f"{scenario_context}: invalid repricing evidence")
        raw_warnings = res.get("warnings") or []
        if isinstance(raw_warnings, str):
            raw_warnings = [raw_warnings]
        warnings.update(str(item) for item in raw_warnings if item not in (None, ""))

        if has_custom and historical_state_mode == "current_state_hyppl":
            if res.get("pnl_convention") != \
                    "horizon_cashflows_plus_end_pv_minus_current_base_pv":
                raise ValueError(
                    f"{scenario_context}: custom holding-period P&L "
                    "convention evidence is missing")
            rolls = res.get("custom_path_roll_evidence")
            if (not isinstance(rolls, list)
                    or len(rolls) != custom_position_count):
                raise ValueError(
                    f"{scenario_context}: custom path-roll evidence is incomplete")
            for roll in rolls:
                if (not isinstance(roll, dict)
                        or roll.get("contract")
                        != "custom_ast_historical_path_roll_v1"
                        or int(roll.get("requested_days", -1)) != int(horizon)
                        or roll.get("day_count_basis") != 252
                        or float(roll.get("end_elapsed_time", 0.0))
                        <= float(roll.get("start_elapsed_time", 0.0))):
                    raise ValueError(
                        f"{scenario_context}: custom path-roll evidence is invalid")
                hashes = {
                    key: str(roll.get(key) or "")
                    for key in (
                        "path_hash", "transition_hash",
                        "cashflow_ledger_hash",
                    )
                }
                output_state_hash = roll.get("output_state_hash")
                valid_output_state = (
                    (roll.get("terminal") is True and output_state_hash is None)
                    or (isinstance(output_state_hash, str)
                        and len(output_state_hash) == 64)
                )
                if (any(len(value) != 64 for value in hashes.values())
                        or not valid_output_state):
                    raise ValueError(
                        f"{scenario_context}: custom path-roll audit hash is invalid")
                path_roll_hashes.append(hashes["path_hash"])
                path_roll_evidence.append({
                    "scenario_index": i,
                    "scenario_date": dates[i],
                    "position_id": str(roll.get("position_id") or ""),
                    **hashes,
                    "output_state_hash": output_state_hash,
                    "terminal": bool(roll.get("terminal")),
                    "requested_days": int(roll["requested_days"]),
                    "consumed_days": int(roll.get("consumed_days", -1)),
                    "cashflow_count": int(roll.get("cashflow_count", -1)),
                    "horizon_cashflow": float(
                        roll.get("horizon_cashflow", 0.0)),
                })
        elif has_custom:
            if (res.get("historical_state_mode") != "actual_trade_backcast"
                    or res.get("pnl_convention")
                    != "horizon_cashflows_plus_end_pv_minus_backcast_start_pv"
                    or res.get("base_value_source")
                    != "actual_trade_backcast_reconstructed"):
                raise ValueError(
                    f"{scenario_context}: actual trade backcast P&L evidence is missing")
            records = res.get("actual_trade_backcast_evidence")
            if not isinstance(records, list) or len(records) != custom_position_count:
                raise ValueError(
                    f"{scenario_context}: actual trade backcast evidence is incomplete")
            for record in records:
                reconstruction = record.get("reconstruction") \
                    if isinstance(record, dict) else None
                dated_roll = record.get("dated_roll") \
                    if isinstance(record, dict) else None
                finite_fields = (
                    record.get("start_state_value"),
                    record.get("end_state_value"),
                    record.get("normalized_horizon_cashflow"),
                    record.get("quantity"),
                ) if isinstance(record, dict) else ()
                try:
                    finite_ok = len(finite_fields) == 4 and all(
                        math.isfinite(float(value)) for value in finite_fields)
                except (TypeError, ValueError, OverflowError):
                    finite_ok = False
                required_hashes = [
                    record.get("backcast_contract_hash"),
                    reconstruction.get("schedule_hash")
                    if isinstance(reconstruction, dict) else None,
                    reconstruction.get("fixing_ledger_hash")
                    if isinstance(reconstruction, dict) else None,
                    reconstruction.get("transition_hash")
                    if isinstance(reconstruction, dict) else None,
                    dated_roll.get("transition_hash")
                    if isinstance(dated_roll, dict) else None,
                    dated_roll.get("cashflow_ledger_hash")
                    if isinstance(dated_roll, dict) else None,
                ]
                if (not isinstance(record, dict) or not finite_ok
                        or record.get("cashflow_unit") != "normalized_notional"
                        or reconstruction.get("contract")
                        != "custom_ast_historical_state_reconstruction_v1"
                        or dated_roll.get("contract")
                        != "custom_ast_dated_path_roll_v1"
                        or reconstruction.get("end_as_of") != previous_dates[i]
                        or dated_roll.get("start_as_of") != previous_dates[i]
                        or dated_roll.get("end_as_of") != dates[i]
                        or any(not isinstance(value, str) or len(value) != 64
                               for value in required_hashes)):
                    raise ValueError(
                        f"{scenario_context}: actual trade state/roll evidence is invalid")
                actual_backcast_evidence.append({
                    "scenario_index": i,
                    "scenario_start_date": previous_dates[i],
                    "scenario_end_date": dates[i],
                    **record,
                })

        if (custom_repricing_profile is not None
                and historical_state_mode == "current_state_hyppl"):
            try:
                current_base = float(res["base_value"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"{scenario_context}: base value evidence is missing or invalid") from exc
            if not math.isfinite(current_base):
                raise ValueError(
                    f"{scenario_context}: base value evidence is non-finite")
            if res.get("custom_repricing_profile") != custom_repricing_profile:
                raise ValueError(
                    f"{scenario_context}: custom repricing profile evidence mismatch")
            source = str(res.get("base_value_source") or "").strip()
            if source not in {"custom_profile_computed", "custom_profile_cache"}:
                raise ValueError(
                    f"{scenario_context}: custom paired base evidence is missing")
            base_value_sources.add(source)
            if profile_base_value is None:
                profile_base_value = current_base
            elif not math.isclose(
                    current_base, profile_base_value, rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError(
                    f"{scenario_context}: custom paired base value changed across scenarios")
        elif custom_repricing_profile is not None:
            try:
                current_base = float(res["base_value"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"{scenario_context}: reconstructed start PV is invalid") from exc
            if not math.isfinite(current_base):
                raise ValueError(
                    f"{scenario_context}: reconstructed start PV is non-finite")
            scenario_base_values.append(current_base)
        elif "base_value" in res:
            try:
                current_base = float(res["base_value"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"{scenario_context}: base value evidence is invalid") from exc
            if not math.isfinite(current_base):
                raise ValueError(
                    f"{scenario_context}: base value evidence is non-finite")
            if ordinary_base_value is None:
                ordinary_base_value = current_base
            elif not math.isclose(
                    current_base, ordinary_base_value, rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError(
                    f"{scenario_context}: static-book base value changed across scenarios")

    elapsed = time.monotonic() - started
    if deadline_seconds is not None and elapsed > deadline_seconds:
        raise TimeoutError(
            "historical full reprice deadline exceeded after the final scenario "
            f"({elapsed:.3f}s > {deadline_seconds:.3f}s)")
    if evidence is not None:
        evidence.clear()
        evidence.update({
            "profile": custom_repricing_profile,
            "inner_paths": (
                CUSTOM_HISTORICAL_INNER_PATHS
                if custom_repricing_profile is not None else None
            ),
            "common_random_numbers": custom_repricing_profile is not None,
            "paired_profile_base": (
                custom_repricing_profile is not None
                and historical_state_mode == "current_state_hyppl"),
            "paired_scenario_start_end": (
                custom_repricing_profile is not None
                and historical_state_mode == "actual_trade_backcast"),
            "base_value": (
                profile_base_value
                if (custom_repricing_profile is not None
                    and historical_state_mode == "current_state_hyppl")
                else ordinary_base_value
            ),
            "scenario_base_values": scenario_base_values,
            "base_value_sources": sorted(base_value_sources),
            "base_value_repriced_once": (
                historical_state_mode == "current_state_hyppl"),
            "scenario_count": len(dates),
            "elapsed_seconds": elapsed,
            "deadline_seconds": deadline_seconds,
            "spot_shock_convention": "log",
            "path_roll_contract": (
                "custom_ast_dated_path_roll_v1"
                if historical_state_mode == "actual_trade_backcast" else
                "historical-custom-spot-path-v1" if has_custom else None),
            "path_day_count_basis": (
                spot_return_paths.get("day_count_basis") if has_custom else None),
            "path_days": int(horizon) if has_custom else None,
            "path_roll_applied": bool(has_custom),
            "path_roll_hashes": path_roll_hashes,
            "path_roll_evidence": path_roll_evidence,
            "actual_trade_backcast_evidence": actual_backcast_evidence,
            "actual_trade_backcast": (
                dict(shifts.get("actual_trade_backcast") or {})
                if historical_state_mode == "actual_trade_backcast" else None),
            "historical_state_mode": historical_state_mode,
            "pnl_convention": (
                "horizon_cashflows_plus_end_pv_minus_backcast_start_pv"
                if historical_state_mode == "actual_trade_backcast" else
                "horizon_cashflows_plus_end_pv_minus_current_base_pv"
                if has_custom else
                "shocked_market_value_minus_base_market_value"
            ),
            "loss_convention": "negative_pnl",
        })
    # Preserve the successful HypPL return arity. Invalid observations raise
    # above; this set carries non-fatal repricing warnings for the payload.
    return pnl, warnings


def aggregate_factor_shifts(shifts: dict, horizon: int,
                            min_windows: int = 50) -> tuple[dict, str]:
    """Aggregate daily factor moves before full repricing an h-day window.

    Equity/FX factors are log-returns, so addition gives the exact cumulative
    log-return. Rates and volatility are absolute changes and are additive too.
    The date attached to a window is its end date. If history cannot provide
    ``min_windows`` overlapping windows, return the daily shifts unchanged and
    let the caller use the explicitly-labelled sqrt-time fallback.
    """
    h = int(horizon)
    if h < 1 or h != horizon:
        raise ValueError("horizon must be a positive integer")

    dates = list(shifts.get("dates") or [])
    previous_dates = list(shifts.get("previous_dates") or [])
    if previous_dates and len(previous_dates) != len(dates):
        raise ValueError("previous_dates length does not match factor dates")

    def rolling_paths(values, width: int) -> list[list[float]]:
        arr = np.asarray(values, dtype=float)
        if len(arr) != len(dates):
            raise ValueError("factor series length does not match dates")
        return [arr[i:i + width].astype(float).tolist()
                for i in range(len(arr) - width + 1)]

    def attach_paths(payload: dict, width: int) -> dict:
        enriched = dict(payload)
        enriched["spot_return_paths"] = {
            "schema": "historical-spot-return-paths-v1",
            "day_count_basis": 252,
            "dates": [dates[i:i + width]
                      for i in range(len(dates) - width + 1)],
            "start_dates": [
                previous_dates[i] if previous_dates else None
                for i in range(len(dates) - width + 1)
            ],
            "fallback_log_returns": rolling_paths(shifts["eq"], width),
            "log_returns_by_factor": {
                name: rolling_paths(values, width)
                for name, values in (shifts.get("eq_names") or {}).items()
            },
        }
        return enriched

    if h == 1:
        return attach_paths(shifts, 1), "none"

    n_windows = len(dates) - h + 1
    if n_windows < int(min_windows):
        return shifts, "sqrt_time"

    def rolling_sum(values) -> np.ndarray:
        arr = np.asarray(values, dtype=float)
        if len(arr) != len(dates):
            raise ValueError("factor series length does not match dates")
        return np.convolve(arr, np.ones(h), mode="valid")

    aggregated = dict(shifts)
    aggregated["dates"] = dates[h - 1:]
    if previous_dates:
        aggregated["previous_dates"] = previous_dates[:n_windows]
    for key in ("eq", "dr", "dvol", "fx"):
        aggregated[key] = rolling_sum(shifts[key])
    for key in ("dr_tenors", "eq_names", "vol_names", "dvol_positions", "fx_pairs"):
        aggregated[key] = {
            name: rolling_sum(values)
            for name, values in (shifts.get(key) or {}).items()
        }
    aggregated["dr_curves"] = {
        curve_id: {
            tenor: rolling_sum(values)
            for tenor, values in nodes.items()
        }
        for curve_id, nodes in (shifts.get("dr_curves") or {}).items()
    }
    return attach_paths(aggregated, h), "factor_aggregation_full_reprice"


def _hyppl_from_scenarios(
    ps,
    shifts: dict,
    *,
    horizon_method: str = "none",
    horizon: int = 1,
    custom_repricing_profile: str | None = None,
    deadline_seconds: float | None = None,
    historical_state_mode: str = "current_state_hyppl",
) -> dict:
    """Reprice a portfolio on an already prepared, shared scenario set."""
    if horizon_method == "sqrt_time" and _portfolio_has_custom_product(ps):
        raise ValueError(
            "historical custom-product risk requires overlapping sequential "
            "factor paths; sqrt-time fallback is not valid for path-dependent "
            "state")
    repricing_evidence: dict = {}
    scenario_matrix_hash = _scenario_matrix_hash(shifts)
    if (custom_repricing_profile is None and deadline_seconds is None
            and not _portfolio_has_custom_product(ps)):
        # Preserve the historical two-positional-argument seam used by
        # incremental/what-if adapters and external test doubles.
        pnl, reprice_warnings = _reprice_series(ps, shifts)
    else:
        pnl, reprice_warnings = _reprice_series(
            ps,
            shifts,
            custom_repricing_profile=custom_repricing_profile,
            evidence=repricing_evidence,
            deadline_seconds=deadline_seconds,
            horizon=horizon,
            historical_state_mode=historical_state_mode,
        )
    if horizon_method == "sqrt_time":
        pnl = pnl * math.sqrt(int(horizon))
    out = {"dates": shifts["dates"], "pnl": pnl, "factors": shifts["factors"],
           "reprice_errors": [], "reprice_warnings": sorted(reprice_warnings),
           "repricing_evidence": repricing_evidence,
           "scenario_matrix_hash": scenario_matrix_hash,
           "horizon_method": horizon_method,
           "factor_warnings": list(shifts.get("factor_warnings") or []),
           "factor_diagnostics": dict(shifts.get("factor_diagnostics") or {})}
    _validated_hyppl(out, context="Historical HypPL")
    return out


def hyppl(
    ctx,
    window: int = 500,
    frm: str | None = None,
    till: str | None = None,
    portfolio=None,
    horizon: int = 1,
    *,
    custom_repricing_profile: str | None = None,
    deadline_seconds: float | None = None,
    historical_state_mode: str = "current_state_hyppl",
) -> dict:
    """Step 2 — Hypothetical P&L: full revaluation of the book on every
    historical joint scenario. For h>1 the factor changes are accumulated
    first and the book is repriced once per overlapping window. Cached for the
    MAIN book; ad-hoc books (what-if) are never cached."""
    key = (
        getattr(ctx.snapshot, "snapshot_id", "?"), int(window), frm, till,
        int(horizon), custom_repricing_profile, deadline_seconds,
        historical_state_mode,
    )
    if portfolio is None and key in _CACHE:
        return _CACHE[key]
    ps = portfolio if portfolio is not None else ctx.portfolio
    daily_shifts = factor_shifts(
        ctx, window, frm, till, portfolio=ps, horizon=horizon)
    shifts, horizon_method = aggregate_factor_shifts(daily_shifts, horizon)
    if historical_state_mode == "actual_trade_backcast":
        ps, shifts = _prepare_actual_trade_backcast(ctx, ps, shifts)
    out = _hyppl_from_scenarios(
        ps,
        shifts,
        horizon_method=horizon_method,
        horizon=horizon,
        custom_repricing_profile=custom_repricing_profile,
        deadline_seconds=deadline_seconds,
        historical_state_mode=historical_state_mode,
    )
    if portfolio is None:
        _CACHE[key] = out
    return out


def _histogram(pnl: np.ndarray, bins: int = 31) -> list[dict]:
    counts, edges = np.histogram(pnl, bins=bins)
    return [{"x": float((edges[i] + edges[i + 1]) / 2), "count": int(counts[i])}
            for i in range(len(counts))]


def _var_es(losses: np.ndarray, confidence: float) -> tuple[float, float]:
    losses = np.asarray(losses, dtype=float)
    if losses.ndim != 1 or losses.size == 0:
        raise ValueError("VaR/ES requires a non-empty one-dimensional loss series")
    if not np.all(np.isfinite(losses)):
        raise ValueError("VaR/ES loss series contains non-finite values")
    var = float(np.quantile(losses, confidence))
    tail = losses[losses >= var]
    return var, (float(tail.mean()) if tail.size else var)


def overview(ctx, confidence: float = 0.99, window: int = 500,
             horizon: int = 1, stress: str | None = None,
             book: str | None = None,
             evt_threshold: float = 0.10) -> dict:
    """VaR analysis report: HypPL distribution + metrics by method + drill-down.
    ``stress`` selects a named fixed historical period (Stress VaR);
    ``book`` (A4) считает VaR по срезу книги (без кэша);
    ``evt_threshold`` (A5) — доля хвоста для GPD-фита EVT (было скрытое 0.10)."""
    from risk.var import evt_var, montecarlo_var, parametric_var

    if stress and stress not in STRESS_WINDOWS:
        raise ValueError(f"unknown stress window: {stress}")
    frm, till = STRESS_WINDOWS.get(stress or "", (None, None))
    book_ps = ctx.filtered_portfolio(book=book) if book else None
    hp = hyppl(ctx, window, frm, till, portfolio=book_ps, horizon=horizon)
    pnl = _validated_hyppl(hp, context="Market Risk overview")
    horizon_method = hp["horizon_method"]
    selected_ps = book_ps if book_ps is not None else ctx.portfolio
    try:
        val = selected_ps.value()
    except Exception as exc:
        raise ValueError(f"Market Risk overview: portfolio valuation failed: {exc}") from exc
    valuation_errors = getattr(val, "errors", None) or []
    if isinstance(valuation_errors, str):
        valuation_errors = [valuation_errors]
    if valuation_errors:
        raise ValueError(
            "Market Risk overview: portfolio valuation failed: "
            + "; ".join(map(str, valuation_errors)))
    try:
        portfolio_value = float(val.total_market_value)
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "Market Risk overview: portfolio value is missing or invalid") from exc
    if not math.isfinite(portfolio_value):
        raise ValueError("Market Risk overview: portfolio value is non-finite")
    losses = -pnl
    var_h, es_h = _var_es(losses, confidence)

    methods = [{
        "method": "historical", "label": "Historical (full reprice)",
        "model_id": "var_full_reprice", "var": var_h, "es": es_h,
    }]
    try:
        p = parametric_var(pnl, 1.0, confidence, 1, "normal")
        methods.append({"method": "parametric", "label": "Parametric (normal)",
                        "model_id": "var_parametric",
                        "var": float(p["VaR"]), "es": float(p.get("ES", p["VaR"]))})
    except Exception:
        pass
    try:
        t = parametric_var(pnl, 1.0, confidence, 1, "t")
        methods.append({"method": "parametric_t", "label": "Parametric (Student-t)",
                        "model_id": "var_parametric",
                        "var": float(t["VaR"]), "es": float(t.get("ES", t["VaR"]))})
    except Exception:
        pass
    try:
        mc = montecarlo_var(pnl, 1.0, confidence, 1)
        methods.append({"method": "monte_carlo", "label": "Monte Carlo (fitted normal)",
                        "model_id": "var_mc",
                        "var": float(mc["VaR"]), "es": float(mc.get("ES", mc["VaR"]))})
    except Exception:
        pass
    evt_skip = None
    evt_diagnostics = None
    try:
        evt_confidence = max(confidence, 0.99)
        ev = evt_var(pnl, 1.0, evt_confidence,
                     threshold_pct=evt_threshold)
        if "error" in ev:
            n_exceedances = int(ev.get("n_exceedances", 0))
            evt_skip = (
                f"EVT пропущен: {ev['error']} — порог {evt_threshold:.0%}, "
                f"превышений {n_exceedances}")
            evt_diagnostics = {
                "status": "skipped",
                "confidence": evt_confidence,
                "threshold_pct": evt_threshold,
                "n_exceedances": n_exceedances,
                "xi_grid": [],
                "warnings": list(ev.get("warnings") or []),
                "error": ev["error"],
            }
        else:
            xi_grid = [
                {"threshold_pct": float(level), "xi": float(xi)}
                for level, xi in sorted(
                    (ev.get("xi_by_threshold") or {}).items(),
                    key=lambda item: float(item[0]))
            ]
            cvar = float(ev.get("CVaR", ev["VaR"]))
            evt_es = cvar if math.isfinite(cvar) else None
            evt_warnings = list(ev.get("warnings") or [])
            evt_diagnostics = {
                "status": "ok",
                "confidence": evt_confidence,
                "threshold_pct": evt_threshold,
                "threshold": float(ev["threshold"]),
                "xi": float(ev["xi"]),
                "beta": float(ev["beta"]),
                "n_exceedances": int(ev["n_exceedances"]),
                "xi_spread": float(ev["xi_spread"]),
                "xi_grid": xi_grid,
                "warnings": evt_warnings,
            }
            methods.append({
                "method": "evt", "label": "EVT (GPD tail)",
                "model_id": "evt_var", "threshold_pct": evt_threshold,
                "confidence": evt_confidence,
                "var": float(ev["VaR"]), "es": evt_es,
                "xi": float(ev["xi"]),
                "n_exceedances": int(ev["n_exceedances"]),
                "xi_spread": float(ev["xi_spread"]),
                "xi_grid": xi_grid, "warnings": evt_warnings,
            })
    except Exception as exc:
        evt_skip = f"EVT пропущен: {exc}"
        evt_diagnostics = {
            "status": "error", "confidence": max(confidence, 0.99),
            "threshold_pct": evt_threshold, "n_exceedances": 0,
            "xi_grid": [], "warnings": [], "error": str(exc),
        }

    order = np.argsort(pnl)
    worst = [{"date": hp["dates"][int(i)], "pnl": float(pnl[int(i)])} for i in order[:5]]
    best = [{"date": hp["dates"][int(i)], "pnl": float(pnl[int(i)])} for i in order[-5:][::-1]]

    quality = []
    quality.extend(hp.get("factor_warnings") or [])
    quality.extend(hp.get("reprice_warnings") or [])
    if any("no history" in f for f in hp["factors"]):
        quality.append("FX-фактор без истории — валютный риск в HypPL не учтён")
    if hp["reprice_errors"]:
        quality.append(f"{len(hp['reprice_errors'])} позиций не переоценились")
    if evt_skip:
        quality.append(evt_skip)
    elif evt_diagnostics:
        quality.extend(
            f"EVT: {warning}"
            for warning in evt_diagnostics.get("warnings", []))
    if horizon_method == "sqrt_time":
        quality.append("горизонт масштабирован sqrt(h) — истории мало для "
                       "перекрывающихся окон (параметрическое приближение)")

    return {
        "confidence": confidence, "window": window, "horizon": horizon,
        "horizon_method": horizon_method,
        "book": book or "",
        "stress": stress or "",
        "stress_period": f"{frm} … {till}" if frm else "",
        "n_scenarios": len(pnl),
        "portfolio_value": portfolio_value,
        "positions": len(selected_ps.positions),
        "var": var_h, "es": es_h,
        "methods": methods,
        "histogram": _histogram(pnl),
        "var_line": -var_h,
        "hyppl": [{"date": d, "pnl": float(p)} for d, p in zip(hp["dates"], pnl.tolist())],
        "worst": worst, "best": best,
        "factors": hp["factors"],
        "factor_diagnostics": hp.get("factor_diagnostics") or {},
        "evt_diagnostics": evt_diagnostics,
        "data_quality": quality,
        "pnl_mean": float(pnl.mean()), "pnl_std": float(pnl.std()),
    }


def mc_var_matrix(ctx, confidence: float = 0.99, window: int = 500,
                  n_sims: int = 1000, seed: int = 42) -> dict:
    """M4 (Calypso Matrix Transform): correlated Monte Carlo VaR.

    Ковариация фактор-вектора [equity, КБД×5 теноров, vol, fx] оценивается по
    истории, Cholesky превращает независимые нормали в согласованные joint-
    сценарии, книга ПОЛНОСТЬЮ переоценивается на каждом — в отличие от
    var_mc (fitted normal на готовом P&L), здесь корреляции факторов и
    нелинейность позиций входят в хвост честно.
    """
    try:
        normalized_n_sims = int(n_sims)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Matrix-MC n_sims must be a positive integer") from exc
    if (isinstance(n_sims, bool) or normalized_n_sims != n_sims
            or normalized_n_sims < 1):
        raise ValueError("Matrix-MC n_sims must be a positive integer")
    n_sims = normalized_n_sims

    shifts = factor_shifts(ctx, window)
    if not shifts.get("dates"):
        raise ValueError("Matrix-MC factor scenario set is empty")
    cols: list[np.ndarray] = []
    col_names: list[str] = []

    def add_column(label: str, values) -> int:
        arr = np.asarray(values, dtype=float)
        if len(arr) != len(shifts["dates"]):
            raise ValueError(f"factor '{label}' length does not match dates")
        cols.append(arr)
        col_names.append(label)
        return len(cols) - 1

    eq_idx = add_column("equity:IMOEX", shifts["eq"])
    rate_indices = {}
    for t in _KBD_TENORS:
        rate_indices[t] = add_column(
            f"rates:KBD:{t:g}y", shifts["dr_tenors"][t])
    vol_idx = add_column("vol:global", shifts["dvol"])
    fx_idx = add_column("fx:USD/RUB", shifts["fx"])

    def granular_index(label: str, values, base_idx: int) -> int:
        arr = np.asarray(values, dtype=float)
        base = cols[base_idx]
        # Identical routes are aliases, not duplicate covariance columns.
        # USD/RUB is the common live example; retaining it twice makes the
        # covariance singular without adding a risk dimension.
        if arr.shape == base.shape and np.array_equal(arr, base):
            return base_idx
        return add_column(label, arr)

    curve_rate_indices = {
        curve_id: {
            tenor: granular_index(
                f"rates:{curve_id}:{tenor:g}y", values,
                rate_indices.get(float(tenor), rate_indices[5.0]),
            )
            for tenor, values in sorted(nodes.items())
        }
        for curve_id, nodes in sorted((shifts.get("dr_curves") or {}).items())
    }

    eq_name_indices = {
        name: granular_index(f"equity:{name}", values, eq_idx)
        for name, values in sorted((shifts.get("eq_names") or {}).items())
    }
    vol_name_indices = {
        name: granular_index(f"vol:{name}", values, vol_idx)
        for name, values in sorted((shifts.get("vol_names") or {}).items())
    }
    vol_position_indices = {
        position_id: granular_index(
            f"vol:surface-position:{position_id}", values, vol_idx)
        for position_id, values in sorted(
            (shifts.get("dvol_positions") or {}).items())
    }
    fx_pair_indices = {}
    for pair, values in sorted((shifts.get("fx_pairs") or {}).items()):
        fx_pair_indices[pair] = (
            fx_idx if pair == "USD/RUB"
            else granular_index(f"fx:{pair}", values, fx_idx)
        )

    X = np.column_stack(cols)
    mu, cov = X.mean(axis=0), np.cov(X.T)

    # Cholesky c джиттером — историческая ковариация бывает полуопределённой
    jitter = 0.0
    for _ in range(6):
        try:
            L = np.linalg.cholesky(cov + jitter * np.eye(cov.shape[0]))
            break
        except np.linalg.LinAlgError:
            jitter = max(jitter * 10, 1e-12)
    else:
        raise ValueError("factor covariance is not positive definite")

    rng = np.random.default_rng(seed)
    sims = mu + rng.standard_normal((int(n_sims), len(cols))) @ L.T

    ps = ctx.portfolio
    pnl = np.empty(len(sims))
    for i, row in enumerate(sims):
        scenario_context = f"Matrix-MC full reprice simulation {i}"
        try:
            res = ps.full_reprice_pnl(
                dS=float(row[eq_idx]), dr=float(row[rate_indices[5.0]]),
                dvol=float(row[vol_idx]), dfx=float(row[fx_idx]),
                dr_curve=[(t, float(row[rate_indices[t]])) for t in _KBD_TENORS],
                dr_curves={
                    curve_id: [(tenor, float(row[index]))
                               for tenor, index in nodes.items()]
                    for curve_id, nodes in curve_rate_indices.items()
                } if curve_rate_indices else None,
                dS_by_name={name: float(row[index])
                            for name, index in eq_name_indices.items()} or None,
                dvol_by_name={name: float(row[index])
                              for name, index in vol_name_indices.items()} or None,
                dvol_by_position={position_id: float(row[index])
                                  for position_id, index in vol_position_indices.items()} or None,
                dfx_by_pair={pair: float(row[index])
                             for pair, index in fx_pair_indices.items()} or None,
                spot_shock_convention="log")
        except Exception as exc:
            raise ValueError(f"{scenario_context}: {exc}") from exc
        pnl[i] = _validated_reprice_pnl(res, context=scenario_context)
    var, es = _var_es(-pnl, confidence)

    corr_denominator = np.sqrt(np.outer(np.diag(cov), np.diag(cov)))
    corr = np.divide(cov, corr_denominator, out=np.zeros_like(cov),
                     where=corr_denominator > 0)
    return {
        "confidence": confidence, "window": window, "n_sims": int(n_sims),
        "var": var, "es": es,
        "pnl_mean": float(pnl.mean()), "pnl_std": float(pnl.std()),
        "histogram": _histogram(pnl),
        "factors": col_names,
        "factor_routes": {
            "equity": {name: col_names[index]
                       for name, index in eq_name_indices.items()},
            "vol": {name: col_names[index]
                    for name, index in vol_name_indices.items()},
            "surface_positions": {
                position_id: col_names[index]
                for position_id, index in vol_position_indices.items()
            },
            "fx": {pair: col_names[index]
                   for pair, index in fx_pair_indices.items()},
            "rates": {
                curve_id: {str(tenor): col_names[index]
                           for tenor, index in nodes.items()}
                for curve_id, nodes in curve_rate_indices.items()
            },
        },
        "corr_eq_rates5y": float(corr[eq_idx, rate_indices[5.0]]),
        "corr_eq_fx": float(corr[eq_idx, fx_idx]),
        "jitter": jitter,
        "reprice_errors": [],
        "factor_warnings": list(shifts.get("factor_warnings") or []),
        "method": "matrix_transform_full_reprice",
        "note": ("Гауссовы совместные факторы (Cholesky от исторической "
                 "ковариации) + полная переоценка; жирные хвосты факторов "
                 "не моделируются — сравнивайте с historical на том же окне."),
    }


def incremental(ctx, product: str, engine: str | None, params: dict,
                quantity: float = 1.0, confidence: float = 0.99,
                window: int = 500) -> dict:
    """Incremental VaR (Calypso §2.3): VaR(book + hypothetical trade) −
    VaR(book), full revaluation on the same historical scenarios. The trade is
    NOT persisted — pure what-if."""
    import copy

    from api.pricing_workstation import (
        portfolio_quantity,
        portfolio_repricing_engine,
        to_position,
    )
    from domain.portfolio import Position
    from services.portfolio_service import PortfolioService

    quantity = portfolio_quantity(quantity)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be strictly between 0 and 1") from exc
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")
    try:
        normalized_window = int(window)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("incremental window must be an integer >= 60") from exc
    if (isinstance(window, bool) or normalized_window != window
            or normalized_window < 60):
        raise ValueError("incremental window must be an integer >= 60")
    window = normalized_window

    mapped = to_position(product, params, engine_id=engine)
    if mapped is None:
        raise ValueError(f"'{product}' не поддерживается портфельной переоценкой")
    instrument, pos_params, desc = mapped
    resolved_engine = portfolio_repricing_engine(product, engine)

    trade = Position(id="whatif_trade", instrument=instrument, quantity=quantity,
                     description=desc, params=pos_params)

    base = ctx.portfolio
    shared_dependencies = {
        "market_data": base.market_data,
        "pricing": base.pricing,
        "audit": base.audit,
        "snapshot": getattr(base, "snapshot", None),
    }
    what_if = PortfolioService(**shared_dependencies)
    for pos in ctx.portfolio.positions:
        what_if.add(copy.deepcopy(pos))
    what_if.add(copy.deepcopy(trade))

    solo = PortfolioService(**shared_dependencies)
    solo.add(copy.deepcopy(trade))

    # MR-5: the union book defines the complete factor universe. Generate it
    # once, then reprice base/union/solo on the exact same dates and shifts;
    # the normal main-book HypPL cache is deliberately bypassed here.
    shared_shifts = factor_shifts(ctx, window, portfolio=what_if)
    base_hp = _hyppl_from_scenarios(base, shared_shifts)
    hp_new = _hyppl_from_scenarios(what_if, shared_shifts)
    hp_solo = _hyppl_from_scenarios(solo, shared_shifts)

    for label, series in (("base", base_hp), ("with-trade", hp_new),
                          ("standalone", hp_solo)):
        errors = series.get("reprice_errors") or []
        pnl_values = np.asarray(series.get("pnl"), dtype=float)
        if errors:
            raise ValueError(
                f"incremental {label} repricing failed: " + "; ".join(errors))
        if pnl_values.ndim != 1 or not len(pnl_values) \
                or not np.all(np.isfinite(pnl_values)):
            raise ValueError(f"incremental {label} HypPL is empty or non-finite")

    var_base, _ = _var_es(-base_hp["pnl"], confidence)
    var_new, _ = _var_es(-hp_new["pnl"], confidence)
    var_solo, _ = _var_es(-hp_solo["pnl"], confidence)

    incr = var_new - var_base
    return {
        "product": product, "engine": resolved_engine,
        "instrument": instrument, "quantity": quantity,
        "confidence": confidence, "window": window,
        "n_scenarios": len(shared_shifts["dates"]),
        "factors": list(shared_shifts["factors"]),
        "var_base": var_base, "var_with_trade": var_new,
        "incremental_var": incr,
        "standalone_var": var_solo,
        "diversification_benefit": var_solo - incr,
    }


def pnl_explain(ctx, theta_days: float = 1.0) -> dict:
    """P&L Explained (Calypso §2.4): the latest day's factor moves →
    full-reprice HYPOTHETICAL P&L (Basel: static book, market moves applied),
    attributed via greeks into market-data effects (delta/gamma/vega/rho) +
    time effect (theta); the unexplained remainder is the residual
    (higher-order and cross terms). Equity and FX historical log-returns are
    converted to position-level absolute spot moves for attribution. Если на
    дату as_of импортирован
    ФАКТИЧЕСКИЙ P&L (A3), выдаётся split APL vs HypPL: разрыв между ними —
    то, чего HypPL не содержит по построению (новые сделки, комиссии,
    внутридневная торговля, lifecycle-события)."""
    shifts = factor_shifts(ctx, window=30)
    if not shifts.get("dates"):
        raise ValueError("P&L Explain factor scenario set is empty")
    dS, dr = float(shifts["eq"][-1]), float(shifts["dr"][-1])
    dvol, dfx = float(shifts["dvol"][-1]), float(shifts["fx"][-1])
    dS_by_name = {name: float(values[-1])
                  for name, values in (shifts.get("eq_names") or {}).items()}
    dvol_by_name = {name: float(values[-1])
                    for name, values in (shifts.get("vol_names") or {}).items()}
    dvol_by_position = {
        position_id: float(values[-1])
        for position_id, values in (shifts.get("dvol_positions") or {}).items()
    }
    dfx_by_pair = {pair: float(values[-1])
                   for pair, values in (shifts.get("fx_pairs") or {}).items()}
    dr_curve = [(float(tenor), float(values[-1]))
                for tenor, values in (shifts.get("dr_tenors") or {}).items()]
    dr_curves = {
        curve_id: [(float(tenor), float(values[-1]))
                   for tenor, values in nodes.items()]
        for curve_id, nodes in (shifts.get("dr_curves") or {}).items()
    }
    as_of = shifts["dates"][-1]

    ps = ctx.portfolio
    scenario_context = f"P&L Explain full reprice scenario 0 ({as_of})"
    try:
        actual = ps.full_reprice_pnl(
            dS=dS, dr=dr, dvol=dvol, dfx=dfx,
            dr_curve=dr_curve or None,
            dr_curves=dr_curves or None,
            dS_by_name=dS_by_name or None,
            dvol_by_name=dvol_by_name or None,
            dvol_by_position=dvol_by_position or None,
            dfx_by_pair=dfx_by_pair or None,
            spot_shock_convention="log")
    except Exception as exc:
        raise ValueError(f"{scenario_context}: {exc}") from exc
    actual_pnl = _validated_reprice_pnl(actual, context=scenario_context)
    simple_dS = math.expm1(dS)
    simple_dfx = math.expm1(dfx)
    simple_dS_by_name = {name: math.expm1(value)
                         for name, value in dS_by_name.items()}
    simple_dfx_by_pair = {pair: math.expm1(value)
                          for pair, value in dfx_by_pair.items()}
    result = ps.explain_pnl(total_pnl=actual_pnl, dVol=dvol, dr=dr,
                            dS_relative=simple_dS,
                            dfx_relative=simple_dfx,
                            dS_relative_by_name=simple_dS_by_name or None,
                            dVol_by_name=dvol_by_name or None,
                            dfx_relative_by_pair=simple_dfx_by_pair or None,
                            theta_days=theta_days)
    explain_errors = getattr(result, "errors", None) or []
    if isinstance(explain_errors, str):
        explain_errors = [explain_errors]
    if explain_errors:
        raise ValueError(
            f"P&L Explain attribution failed ({as_of}): "
            + "; ".join(map(str, explain_errors)))

    # A3: фактический P&L (импортированный) vs гипотетический (модельный)
    apl_row = None
    try:
        apl_row = ctx.app_db.load_actual_pnl(as_of)
    except Exception:
        pass
    hyp = actual_pnl
    apl = {"available": apl_row is not None, "date": as_of}
    if apl_row is not None:
        apl.update({
            "actual_pnl": float(apl_row["pnl"]),
            "hypothetical_pnl": hyp,
            "gap": float(apl_row["pnl"]) - hyp,
            "source": apl_row.get("source", "manual"),
            "note": ("Разрыв APL−HypPL: новые сделки, внутридневная торговля, "
                     "lifecycle и theta (HypPL здесь без старения позиций — "
                     "время целиком в разрыве). Basel требует APL, очищенный "
                     "от комиссий: если импортирована серия с комиссиями, они "
                     "тоже осядут в разрыве."),
        })

    # lifecycle v1 (честно): позиции книги не «стареют» (T статично), поэтому
    # детектировать купоны/экспирации по календарю нельзя — только
    # предупреждаем о позициях у экспирации, чей lifecycle-эффект скоро
    # попадёт в разрыв APL/HypPL.
    lifecycle = []
    for p in ps.positions:
        t_rem = p.params.get("T", p.params.get("T_option"))
        if t_rem is not None and 0 < float(t_rem) <= 5 / 252:
            lifecycle.append({"position": p.description,
                              "T_years": float(t_rem),
                              "note": "экспирация ≤ 5 т.д. — lifecycle-эффект"})

    labels = {"delta_pnl": "Delta (equity)", "gamma_pnl": "Gamma",
              "vega_pnl": "Vega (vol)", "theta_pnl": "Theta (time)",
              "rate_pnl": "Rates", "rho_pnl": "Rates (rho)",
              "fx_pnl": "FX", "spread_pnl": "Credit spread"}
    comp = dict(result.components or {})
    numeric_outputs = list(comp.values()) + [result.residual]
    numeric_outputs.extend((result.factor_pnl or {}).values())
    numeric_outputs.extend((result.position_pnl or {}).values())
    try:
        finite_outputs = all(math.isfinite(float(value))
                             for value in numeric_outputs)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"P&L Explain attribution is non-numeric ({as_of})") from exc
    if not finite_outputs:
        raise ValueError(f"P&L Explain attribution is non-finite ({as_of})")
    effects = [{"key": k, "label": labels.get(k, k.replace("_pnl", "").capitalize()),
                "value": float(v)} for k, v in comp.items()]
    explain_warnings = list(result.warnings or [])
    if dr_curve and any(abs(move - dr) > 1e-12 for _tenor, move in dr_curve):
        explain_warnings.append(
            "HypPL uses the full KBD tenor shock; first-order rate attribution "
            "uses aggregate DV01, so curve-shape and cross effects remain in residual.")
    if dr_curves:
        explain_warnings.append(
            "HypPL routes historical node shocks to each named curve; first-order "
            "rate attribution remains aggregate DV01, so per-curve/node effects "
            "remain in residual until key-rate exposures are available.")
    if dvol_by_position:
        explain_warnings.append(
            "HypPL uses position-specific sticky-strike/constant-maturity surface "
            "moves; first-order vega attribution remains per-underlying, so smile, "
            "term and cross effects remain in residual.")
    return {
        "as_of": as_of,
        "moves": {"equity": simple_dS, "rates_bp": dr * 10000,
                  "vol_pts": dvol * 100, "fx": simple_dfx},
        "total_pnl": actual_pnl,
        "explained": float(sum(comp.values())),
        "residual": float(result.residual),
        "effects": effects,
        "by_factor": [{"factor": k, "pnl": float(v)}
                      for k, v in (result.factor_pnl or {}).items()],
        "by_position": [{"position": k, "pnl": float(v)}
                        for k, v in (result.position_pnl or {}).items()],
        "actual_vs_hypothetical": apl,
        "lifecycle": lifecycle,
        "note": ("Market-data effect по грикам, time effect = theta; equity/FX "
                 "log-returns переведены в абсолютные spot moves каждой позиции; "
                 "residual — нелинейность и кросс-эффекты."),
        "warnings": explain_warnings,
    }


_PCA_TENORS = (0.25, 1.0, 2.0, 5.0, 10.0)          # КБД series in the backfill


def pca_rates(ctx, confidence: float = 0.99, window: int = 500,
              n_components: int = 3) -> dict:
    """PCA of the КБД curve (level/slope/curvature) + PCA-VaR of the book's
    rate exposure mapped onto the tenor pillars — Calypso's bucketed rate risk
    against our single-factor (5Y parallel) HypPL treatment."""
    from risk.historical_var import pca_var

    db = ctx.market_db
    series = {t: dict(_series(db, f"KBD:{t:g}Y")) for t in _PCA_TENORS}
    dates = sorted(set.intersection(*(set(s) for s in series.values())))
    if len(dates) < 60:
        raise ValueError("not enough КБД tenor history for PCA")
    dates = dates[-(window + 1):]
    changes = np.array([[series[t][d1] - series[t][d0] for t in _PCA_TENORS]
                        for d0, d1 in zip(dates, dates[1:])]) * 10000  # bp units

    # DV01 vector: bond key-rate exposures land on their pillar, everything
    # else (IRS/swaption DV01) on the nearest pillar to its maturity.
    ps = ctx.portfolio
    ps.value()
    dv01 = np.zeros(len(_PCA_TENORS))
    for pos in ps.positions:
        exposures = getattr(pos, "exposures", []) or []
        krd, headline = [], []
        for exp in exposures:
            unit = str(getattr(exp, "unit", "")).lower()
            if "dv01" not in unit:
                continue
            factor = str(getattr(exp, "factor_name", ""))
            amount = float(getattr(exp, "sensitivity", 0.0) or 0.0)
            if factor.startswith("kr_"):
                try:
                    krd.append((float(factor[3:].rstrip("y")), amount))
                except ValueError:
                    continue
            elif "key rate" not in unit:
                headline.append(amount)
        if krd:                                     # bucketed beats the headline
            rows = krd
        else:
            t_pos = float(pos.params.get("T", 5.0)) if pos.params else 5.0
            rows = [(t_pos, a) for a in headline]
        for tenor, amount in rows:
            idx = int(np.argmin([abs(tenor - t) for t in _PCA_TENORS]))
            dv01[idx] += amount

    res = pca_var(changes, dv01, confidence, n_components)
    names = ["Level", "Slope", "Curvature"][:n_components]
    loadings = [
        {"component": names[i] if i < len(names) else f"PC{i+1}",
         "variance_share": float(res["eigenvalues"][i] / res["eigenvalues"].sum()
                                 * res["pct_variance_explained"]),
         "dv01": float(res["factor_dv01"][i]),
         "vol_annual_bp": float(res["factor_vol_annual"][i]),
         "weights": [{"tenor": t, "w": float(res["eigenvectors"][j, i])}
                     for j, t in enumerate(_PCA_TENORS)]}
        for i in range(n_components)
    ]
    # parallel-only comparison: total DV01 x quantile of the 5Y change
    par_losses = -changes[:, _PCA_TENORS.index(5.0)] * dv01.sum()
    var_parallel = float(np.quantile(np.abs(par_losses), confidence))
    return {
        "confidence": confidence, "window": len(changes),
        "tenors": list(_PCA_TENORS),
        "dv01_vector": [{"tenor": t, "dv01": float(v)}
                        for t, v in zip(_PCA_TENORS, dv01)],
        "pca_var": float(res["VaR"]),
        "parallel_var": var_parallel,
        "variance_explained": float(res["pct_variance_explained"]),
        "components": loadings,
        "note": ("PCA по дневным изменениям КБД (bp); Level/Slope/Curvature. "
                 "DV01 бондов — по key-rate корзинам, свопов — на ближайший "
                 "пиллар. HypPL пока использует один 5Y-фактор — PCA-VaR "
                 "показывает вклад формы кривой."),
    }


def backtest(ctx, confidence: float = 0.99, window: int = 500,
             lookback: int = 250) -> dict:
    """Backtesting analysis: rolling historical VaR vs next-day HypPL —
    exceptions, Kupiec POF, Christoffersen independence, Basel traffic light."""
    from risk.var import christoffersen_test, kupiec_test

    try:
        normalized_lookback = int(lookback)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("backtest lookback must be an integer") from exc
    if isinstance(lookback, bool) or normalized_lookback != lookback:
        raise ValueError("backtest lookback must be an integer")
    lookback = normalized_lookback
    min_lookback, min_out_of_sample = 60, 20
    if lookback < min_lookback:
        raise ValueError(
            f"backtest lookback must be at least {min_lookback} observations")

    hp = hyppl(ctx, window)
    pnl = _validated_hyppl(hp, context="Market Risk backtest")
    required = min_lookback + min_out_of_sample
    if len(pnl) < required:
        raise ValueError(
            "not enough HypPL history for backtest: "
            f"need at least {required} observations "
            f"({min_lookback} lookback + {min_out_of_sample} out-of-sample), "
            f"got {len(pnl)}")
    if lookback > len(pnl) - min_out_of_sample:
        lookback = max(min_lookback, len(pnl) // 2)

    # A3: если импортирован фактический P&L — Basel требует бэктест VaR
    # против ОБЕИХ серий (hypothetical и actual); actual подмешивается в
    # строки по датам, где он есть.
    apl_by_date = {}
    try:
        apl_by_date = {r["dt"]: float(r["pnl"])
                       for r in ctx.app_db.list_actual_pnl(limit=100_000)}
    except Exception:
        pass

    rows, exceptions, apl_exceptions = [], [], []
    for t in range(lookback, len(pnl)):
        var_t = float(np.quantile(-pnl[t - lookback:t], confidence))
        breach = bool(pnl[t] < -var_t)
        exceptions.append(breach)
        row = {"date": hp["dates"][t], "pnl": float(pnl[t]),
               "var": -var_t, "breach": breach}
        apl = apl_by_date.get(hp["dates"][t])
        if apl is not None:
            row["actual_pnl"] = apl
            row["actual_breach"] = bool(apl < -var_t)
            apl_exceptions.append(row["actual_breach"])
        rows.append(row)

    n_obs, n_exc = len(exceptions), int(sum(exceptions))
    if n_obs < min_out_of_sample:
        raise ValueError(
            f"backtest needs at least {min_out_of_sample} out-of-sample observations")
    expected = n_obs * (1 - confidence)
    kupiec = kupiec_test(n_obs, n_exc, confidence)
    christ = christoffersen_test(np.array(exceptions, dtype=int))  # self-guarding (D1)

    # M6-lite: у Kupiec-отклонения есть НАПРАВЛЕНИЕ — слишком мало пробоев
    # значит модель консервативна (капитал завышен), слишком много — агрессивна
    # (риск недооценён). Без знака reject читается как «модель занижает риск».
    if n_exc < expected:
        bias = "conservative"
    elif n_exc > expected:
        bias = "aggressive"
    else:
        bias = "in_line"

    # Basel traffic light, generalized: the 99%/250d thresholds (5/10 breaches)
    # are exactly 2x/4x the expected count — apply that ratio at any confidence.
    ratio = (n_exc / expected) if expected > 0 else 0.0
    zone = "green" if ratio < 2.0 else ("amber" if ratio < 4.0 else "red")

    return {
        "confidence": confidence, "lookback": lookback,
        "n_obs": n_obs, "n_exceptions": n_exc,
        "expected_exceptions": expected,
        "exception_rate": (n_exc / n_obs) if n_obs else 0.0,
        "kupiec": kupiec, "christoffersen": christ,
        "traffic_light": zone,
        "bias": bias,
        "actual_backtest": {
            "n_obs": len(apl_exceptions),
            "n_exceptions": int(sum(apl_exceptions)),
            "imported_dates": len(apl_by_date),
            "note": ("Тот же VaR против импортированной серии actual P&L (Basel: обе "
                     "серии). Внимание: VaR считается по ТЕКУЩЕЙ книге "
                     "(позиции статичны) — сравнение с историческим APL "
                     "корректно, пока состав книги на этих датах близок к "
                     "текущему."),
        } if apl_exceptions else {
            "n_obs": 0, "n_exceptions": 0,
            "imported_dates": len(apl_by_date),
            "note": ("actual P&L не импортирован" if not apl_by_date else
                     f"actual импортирован ({len(apl_by_date)} дат), но даты "
                     "не пересекаются с хвостом бэктеста"),
        },
        "rows": rows,
    }
