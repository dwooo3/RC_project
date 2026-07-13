"""
Market-data validation per MOEX_MARKET_DATA_INTEGRATION_PROMPT.md §5.

Pure functions: ingestion and snapshot assembly call these to derive a data
quality verdict (OK / STALE / PARTIAL / REJECTED) plus human-readable warnings.
REJECTED data must not feed production valuations.
"""

from __future__ import annotations

import math
from datetime import date


QUALITY_OK = "OK"
QUALITY_STALE = "STALE"
QUALITY_PARTIAL = "PARTIAL"
QUALITY_REJECTED = "REJECTED"


def validate_curve_points(points: list[tuple[float, float, float | None]],
                          *, min_points: int = 3) -> list[str]:
    """Return a list of errors (empty == valid) for (tenor, zero_rate, df) points."""
    errors: list[str] = []
    if len(points) < min_points:
        errors.append(f"curve has {len(points)} points (< {min_points} required)")
        return errors
    tenors = [p[0] for p in points]
    zeros = [p[1] for p in points]
    if any(not math.isfinite(t) or not math.isfinite(z) for t, z in zip(tenors, zeros)):
        errors.append("curve contains NaN/inf")
    if any(t <= 0 for t in tenors):
        errors.append("tenors must be positive")
    if any(b <= a for a, b in zip(tenors, tenors[1:])):
        errors.append("tenors must be strictly increasing")
    # discount factors: compute from continuous zero if not supplied
    dfs = []
    for t, z, df in points:
        dfs.append(df if df is not None else math.exp(-z * t))
    if any((d is None) or (not math.isfinite(d)) or d <= 0 for d in dfs):
        errors.append("discount factors must be positive and finite")
    elif any(b - a > 1e-9 for a, b in zip(dfs, dfs[1:])):
        errors.append("discount factors must be monotonic non-increasing")
    return errors


def validate_fx(fx: dict[str, float], *, cross_tol: float = 0.02) -> list[str]:
    """Validate FX rates: positivity + USD/EUR/RUB cross-consistency when present."""
    errors: list[str] = []
    for pair, rate in fx.items():
        if not math.isfinite(rate) or rate <= 0:
            errors.append(f"{pair} rate must be positive and finite")
    usd, eur, eurusd = fx.get("USD/RUB"), fx.get("EUR/RUB"), fx.get("EUR/USD")
    if usd and eur and eurusd:
        implied = eur / usd
        if abs(implied - eurusd) / eurusd > cross_tol:
            errors.append(
                f"FX cross inconsistent: EUR/RUB÷USD/RUB={implied:.4f} vs EUR/USD={eurusd:.4f}"
            )
    return errors


def assess_quality(
    *,
    valuation_date: date,
    as_of: date | None,
    curve_errors: list[str],
    fx_errors: list[str],
    expected_components: set[str],
    present_components: set[str],
    max_stale_days: int = 3,
) -> tuple[str, list[str]]:
    """
    Combine freshness, completeness and structural checks into a quality verdict.

    Hard structural failures (curve/FX errors) → REJECTED.
    Stale trade date → STALE. Missing expected components → PARTIAL.
    """
    warnings: list[str] = []

    if curve_errors or fx_errors:
        warnings.extend(curve_errors)
        warnings.extend(fx_errors)
        return QUALITY_REJECTED, warnings

    missing = expected_components - present_components
    quality = QUALITY_OK

    if as_of is not None:
        if as_of > valuation_date:
            warnings.append(
                f"market data trade date {as_of} is after valuation {valuation_date}"
            )
            return QUALITY_REJECTED, warnings
        stale_days = (valuation_date - as_of).days
        if stale_days > max_stale_days:
            warnings.append(
                f"market data trade date {as_of} is {stale_days}d from valuation {valuation_date}"
            )
            quality = QUALITY_STALE

    if missing:
        warnings.append(f"missing market data components: {sorted(missing)}")
        if quality == QUALITY_OK:
            quality = QUALITY_PARTIAL

    return quality, warnings


def is_production_quality(quality: str) -> bool:
    return quality == QUALITY_OK
