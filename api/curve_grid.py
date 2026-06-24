"""Standard tenor grid for curve display.

Every curve in the Market Data view is resampled onto one canonical pillar set
(1D → 10Y) so curves are directly comparable. This is a *display* transform: the
stored curve points (used by pricing) keep their native nodes; we only
interpolate for presentation.

Interpolation: **monotone cubic Hermite (PCHIP)** on zero rates. Natural cubic
splines are C²-smooth but not shape-preserving — they overshoot and can produce
oscillating/negative *forward* rates, which is exactly what you don't want on a
yield curve (and worse here, where an overnight anchor sits far from the first
node). Pure linear avoids overshoot but kinks the forwards. PCHIP is
monotonicity/shape-preserving with no overshoot — a standard, defensible choice
alongside log-linear-on-DF and Hagan–West monotone-convex.

The overnight anchor (CBR key rate for OFZ; RUONIA fixing for RUONIA curves) is
injected as a real 1D node so the short end is interpolated consistently. Pillars
beyond the longest native node are dropped by default (we don't fabricate a long
end). Zero rates are continuous-compounded (engine convention); DF = exp(-z·t).
"""

from __future__ import annotations

import math

# Canonical pillars: (label, tenor in years, ACT/365).
STANDARD_PILLARS: list[tuple[str, float]] = [
    ("1D", 1.0 / 365), ("1W", 7.0 / 365), ("2W", 14.0 / 365),
    ("1M", 30.0 / 365), ("2M", 60.0 / 365), ("3M", 91.0 / 365),
    ("6M", 182.0 / 365), ("9M", 273.0 / 365),
    ("1Y", 1.0), ("2Y", 2.0), ("3Y", 3.0), ("4Y", 4.0), ("5Y", 5.0),
    ("6Y", 6.0), ("7Y", 7.0), ("8Y", 8.0), ("9Y", 9.0), ("10Y", 10.0),
]
_ON_T = 1.0 / 365


def _lin(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for x0, x1, y0, y1 in zip(xs, xs[1:], ys, ys[1:]):
        if x0 <= x <= x1:
            w = (x - x0) / (x1 - x0)
            return y0 + w * (y1 - y0)
    return ys[-1]


def _make_interp(tenors: list[float], zeros: list[float]):
    """Monotone cubic Hermite (PCHIP) interpolant; linear fallback."""
    try:
        from scipy.interpolate import PchipInterpolator
        fn = PchipInterpolator(tenors, zeros, extrapolate=False)
        return lambda T: float(fn(T))
    except Exception:
        return lambda T: _lin(T, tenors, zeros)


def standardize_curve(points, *, overnight_rate: float | None = None,
                      extend_long: bool = False) -> list[dict]:
    """Resample native ``[(tenor, zero, df)]`` onto the standard pillar grid.

    ``overnight_rate`` (continuous) is injected as a 1D node to anchor the short
    end (e.g. the CBR key rate for OFZ) so PCHIP interpolates it consistently.
    """
    pts = sorted((float(t), float(z)) for t, z, _ in points if z is not None)
    # inject the overnight anchor as a real 1D node when the curve starts later
    if overnight_rate is not None and (not pts or pts[0][0] > _ON_T + 1e-9):
        pts = [(_ON_T, float(overnight_rate))] + pts
    # dedup tenors (PCHIP needs strictly increasing x)
    dedup: list[tuple[float, float]] = []
    for t, z in pts:
        if not dedup or t > dedup[-1][0] + 1e-12:
            dedup.append((t, z))
    if len(dedup) < 2:
        return []
    tenors = [t for t, _ in dedup]
    zeros = [z for _, z in dedup]
    tmin, tmax = tenors[0], tenors[-1]
    interp = _make_interp(tenors, zeros)

    out: list[dict] = []
    for label, T in STANDARD_PILLARS:
        if T < tmin - 1e-9:
            z = zeros[0]                           # flat below the shortest node
        elif T > tmax + 1e-9:
            if not extend_long:
                continue                           # don't fabricate the long end
            z = zeros[-1]
        else:
            z = interp(T)
        out.append({"label": label, "tenor": T, "zero": z, "discount": math.exp(-z * T)})
    return out
