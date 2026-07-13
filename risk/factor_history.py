"""Canonical identities for governed historical risk-factor nodes.

The level series are deliberately namespaced by the market-data dependency
they belong to.  A scenario for ``GCURVE_RUB`` must therefore never be reused
for ``RUONIA_RUB`` (or for an unrelated USD/EUR curve) merely because both are
rates.  Values stored under these IDs are *levels*; Market Risk takes aligned
close-to-close differences when it builds a scenario.
"""

from __future__ import annotations

import math


# Stable risk grid used for every named yield curve.  EOD/backfill publishers
# write only nodes that are inside the source curve's native tenor support.
# Scenario generation then requires the complete applicable grid for each
# curve dependency held by the book.
CURVE_HISTORY_TENORS = (
    1.0 / 12.0,
    0.25,
    0.5,
    1.0,
    2.0,
    3.0,
    5.0,
    7.0,
    10.0,
    15.0,
    20.0,
    30.0,
)


def _number_token(value: float) -> str:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("factor node coordinate must be finite and positive")
    return format(number, ".12g")


def curve_node_factor_id(curve_id: str, tenor: float) -> str:
    """Return the durable level-series ID for one named curve/risk tenor."""
    identity = str(curve_id).strip()
    if not identity:
        raise ValueError("curve_id is required for historical factor identity")
    return f"CURVE:{identity}:{_number_token(tenor)}Y"


def supported_curve_history_tenors(
    curve,
    required_tenor: float | None = None,
) -> tuple[float, ...]:
    """Canonical nodes spanning the curve's complete native support.

    ``YieldCurve`` may use a global cubic interpolator, so even native nodes
    beyond the last held cashflow can affect rates inside the held interval
    after a node shock.  Until scenario curves use a demonstrably local shift
    representation, historical maps must therefore cover the complete native
    support rather than stop at the first right-hand bracket.
    """
    raw = getattr(curve, "tenors", None)
    if raw is None or not len(raw):
        raise ValueError("named curve does not expose native tenor support")
    values = sorted(float(value) for value in raw)
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("named curve contains invalid native tenors")
    if len(values) != len(set(values)):
        raise ValueError("named curve contains duplicate native tenors")
    lo, hi = min(values), max(values)
    supported = tuple(
        tenor for tenor in CURVE_HISTORY_TENORS
        if lo - 1e-12 <= tenor <= hi + 1e-12
    )
    if required_tenor is None:
        return tuple(sorted(set((*values, *supported))))
    required = float(required_tenor)
    if not math.isfinite(required) or required <= 0:
        raise ValueError("required curve tenor must be finite and positive")
    if required < lo - 1e-12:
        raise ValueError(
            f"curve support starts at {lo:.6g}Y, above required {required:.6g}Y")
    if required > hi + 1e-12:
        raise ValueError(
            f"curve support ends at {hi:.6g}Y, below required {required:.6g}Y")
    return tuple(sorted(set((*values, *supported))))
