"""OIS zero-curve bootstrap.

Turns a term structure of OIS par rates into continuous-compounded zero rates
and discount factors — the convention the engine stores curves in
(``YieldCurve`` reads ``zero_rate`` as continuous, DF = exp(-z·t)).

Two regimes:
  - Money-market short end (tenor ≤ 1y): a single bullet payment, so
        DF(t) = 1 / (1 + r·t).
  - OIS swaps (tenor > 1y): annual fixed coupons. We bootstrap on an integer-year
    grid (par rates linearly interpolated to each year), closed-form per year
        DF(n) = (1 − r_n·Σ_{k<n} DF(k)) / (1 + r_n),
    then sample the requested tenors (log-linear DF interpolation off the grid).

All rates are decimals (0.14 == 14%). Returns ``[(tenor, zero_cont, df)]``.
This is deliberately a transparent bootstrap on indicative term rates, not a
dual-curve/turn-aware engine — adequate for a RUONIA/RUSFAR OIS proxy.
"""

from __future__ import annotations

import math

_ONE_Y = 1.0 + 1e-9


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Linear interpolation with flat extrapolation."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for x0, x1, y0, y1 in zip(xs, xs[1:], ys, ys[1:]):
        if x0 <= x <= x1:
            w = (x - x0) / (x1 - x0)
            return y0 + w * (y1 - y0)
    return ys[-1]


def bootstrap_ois(tenors, par_rates) -> list[tuple[float, float, float]]:
    """Bootstrap OIS par rates → ``[(tenor_years, zero_continuous, df)]``."""
    nodes = sorted((float(t), float(r)) for t, r in zip(tenors, par_rates))
    if not nodes:
        return []
    ts = [t for t, _ in nodes]
    rs = [r for _, r in nodes]

    # Integer-year DF grid for the annual-coupon (>1y) bootstrap.
    df_year: dict[int, float] = {}
    max_y = int(math.ceil(ts[-1]))
    annuity = 0.0
    for y in range(1, max_y + 1):
        r_y = _interp(float(y), ts, rs)
        df = 1.0 / (1.0 + r_y) if y == 1 else (1.0 - r_y * annuity) / (1.0 + r_y)
        annuity += df
        df_year[y] = df

    out: list[tuple[float, float, float]] = []
    for t, r in nodes:
        if t <= _ONE_Y:
            df = 1.0 / (1.0 + r * t)                      # money-market bullet
        else:
            y0, y1 = int(math.floor(t)), int(math.ceil(t))
            d0 = df_year.get(y0, 1.0)
            d1 = df_year.get(y1, d0)
            if y1 == y0:
                df = d0
            else:                                         # log-linear in DF
                w = (t - y0) / (y1 - y0)
                df = math.exp((1 - w) * math.log(d0) + w * math.log(d1))
        z = -math.log(df) / t
        out.append((t, z, df))
    return out
