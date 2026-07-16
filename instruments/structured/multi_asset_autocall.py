"""Multi-asset autocall / Phoenix payoff on real market underlyings.

The pricing service resolves the ``Constituent`` objects and their empirical
correlation matrix from the market-data store.  This module owns only the
contract and the correlated-GBM Monte-Carlo valuation.

Contract convention
-------------------
At every observation date, while the note is alive:

* the guaranteed coupon accrues for the elapsed period and is paid;
* the conditional coupon is paid when its basket trigger is met (an autocall
  also pays the current/accrued conditional coupon);
* the note redeems at par when the autocall trigger is met.

At maturity, a surviving note returns par unless the configured protection
barrier has been breached.  After a breach, redemption participates one-for-one
in the protection basket below par.  ``maturity`` monitoring observes the
barrier only at maturity; ``continuous`` observes every simulated path step.

Each trigger can aggregate the same 1--5 underlyings independently as
``worst_of``, ``best_of`` or weighted ``average``.  This supports, for example,
an autocall on the best of five assets and downside protection on the worst.

Limitations are deliberate and exposed by the service/catalogue: constant
volatility and correlation, deterministic carry/rates, and bond underlyings as
price-index GBMs rather than full cash-flow/default models.
"""

from __future__ import annotations

from collections.abc import Sequence
import math

import numpy as np

from instruments.structured.basket_note import Constituent, nearest_correlation
from models.monte_carlo import multi_asset_paths


_AGGREGATIONS = frozenset({"worst_of", "best_of", "average"})
_MONITORING = frozenset({"maturity", "continuous"})
_MAX_ASSETS = 5
# The path generator materialises float64[n_sims, n_assets, steps + 1].  Keep
# one call below roughly 200 MB before temporary arrays; fail explicitly rather
# than letting a user-configured run exhaust the desktop process.
_MAX_PATH_POINTS = 25_000_000


def _finite(name: str, value: float) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(resolved):
        raise ValueError(f"{name} must be a finite number")
    return resolved


def _bounded(name: str, value: float, lo: float, hi: float) -> float:
    resolved = _finite(name, value)
    if not lo <= resolved <= hi:
        raise ValueError(f"{name} must be in [{lo:g}, {hi:g}]")
    return resolved


def _positive_int(name: str, value: int, minimum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer >= {minimum}")
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer >= {minimum}") from exc
    if resolved != value or resolved < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return resolved


def _observation_schedule(observation_dates: Sequence[float] | None,
                          maturity: float) -> list[float]:
    values = [] if observation_dates is None else [
        _finite("observation date", value) for value in observation_dates
    ]
    if not values:
        values = [maturity]
    if any(value <= 0.0 or value > maturity + 1e-12 for value in values):
        raise ValueError("observation dates must be in (0, T]")
    if any(right <= left for left, right in zip(values, values[1:])):
        raise ValueError("observation dates must be strictly increasing")
    # Maturity is always a contractual observation.  Appending it is explicit
    # in the resolved diagnostics and avoids an unobserved final coupon period.
    if values[-1] < maturity - 1e-12:
        values.append(maturity)
    else:
        values[-1] = maturity
    return values


def _aggregate(relative_levels: np.ndarray, weights: np.ndarray,
               mode: str) -> np.ndarray:
    """Aggregate n_sims x n_assets [x time] relative levels."""
    if mode == "worst_of":
        return relative_levels.min(axis=1)
    if mode == "best_of":
        return relative_levels.max(axis=1)
    # Contracted basket weights apply only to the average trigger.
    return np.tensordot(relative_levels, weights, axes=([1], [0]))


def _histogram(values: np.ndarray, bins: int = 30) -> list[list[float]]:
    lo = float(values.min())
    hi = float(values.max())
    if math.isclose(lo, hi, rel_tol=0.0, abs_tol=1e-12):
        return [[lo, float(values.size)]]
    counts, edges = np.histogram(values, bins=min(bins, max(5, values.size // 50)))
    centres = 0.5 * (edges[:-1] + edges[1:])
    return [[float(x), float(count)] for x, count in zip(centres, counts)]


def multi_asset_autocall(
    constituents: Sequence[Constituent],
    r: float,
    T: float,
    correlation: np.ndarray | Sequence[Sequence[float]] | None = None,
    *,
    observation_dates: Sequence[float] | None = None,
    autocall_barrier: float = 1.20,
    autocall_aggregation: str = "best_of",
    protection_barrier: float = 0.65,
    protection_aggregation: str = "worst_of",
    protection_monitoring: str = "maturity",
    coupon_barrier: float = 0.65,
    coupon_aggregation: str = "worst_of",
    coupon_rate: float = 0.0,
    guaranteed_coupon: float = 0.05,
    memory_coupon: bool = True,
    notional: float = 1_000.0,
    n_sims: int = 20_000,
    steps: int = 100,
    seed: int = 42,
) -> dict:
    """Price a 1--5 asset autocall and return audit-friendly diagnostics.

    Barrier and coupon rates are ratios/rates (``0.65`` = 65%).  The returned
    headline ``price`` is in the same currency units as ``notional``.
    """
    items = list(constituents)
    if not 1 <= len(items) <= _MAX_ASSETS:
        raise ValueError("multi-asset autocall requires 1 to 5 underlyings")
    names = [str(item.name).strip() for item in items]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("underlying names must be non-empty and unique")

    r = _finite("r", r)
    T = _finite("T", T)
    if T <= 0.0:
        raise ValueError("T must be positive")
    notional = _finite("notional", notional)
    if notional <= 0.0:
        raise ValueError("notional must be positive")
    autocall_barrier = _bounded("autocall_barrier", autocall_barrier, 0.01, 5.0)
    protection_barrier = _bounded("protection_barrier", protection_barrier, 0.0, 2.0)
    coupon_barrier = _bounded("coupon_barrier", coupon_barrier, 0.0, 5.0)
    coupon_rate = _bounded("coupon_rate", coupon_rate, 0.0, 5.0)
    guaranteed_coupon = _bounded("guaranteed_coupon", guaranteed_coupon, 0.0, 5.0)

    for name, aggregation in (
        ("autocall_aggregation", autocall_aggregation),
        ("protection_aggregation", protection_aggregation),
        ("coupon_aggregation", coupon_aggregation),
    ):
        if aggregation not in _AGGREGATIONS:
            allowed = ", ".join(sorted(_AGGREGATIONS))
            raise ValueError(f"{name} must be one of: {allowed}")
    if protection_monitoring not in _MONITORING:
        raise ValueError("protection_monitoring must be 'maturity' or 'continuous'")
    if not isinstance(memory_coupon, (bool, np.bool_)):
        raise ValueError("memory_coupon must be boolean")

    n_sims = _positive_int("n_sims", n_sims, 1_000)
    steps = _positive_int("steps", steps, 1)
    seed = _positive_int("seed", seed, 0)
    if seed > np.iinfo(np.uint32).max:
        raise ValueError("seed must be <= 4294967295")
    if n_sims * len(items) * (steps + 1) > _MAX_PATH_POINTS:
        raise ValueError(
            "Monte-Carlo grid is too large; require "
            "n_sims * n_assets * (steps + 1) <= 25000000"
        )

    schedule = _observation_schedule(observation_dates, T)
    dt = T / steps
    observation_steps = [min(steps, max(1, int(round(t / dt)))) for t in schedule]
    if len(set(observation_steps)) != len(observation_steps):
        raise ValueError(
            "steps is too small to distinguish all observation dates"
        )

    spots = np.asarray([_finite(f"spot[{name}]", item.spot)
                        for name, item in zip(names, items)], dtype=float)
    vols = np.asarray([_finite(f"vol[{name}]", item.vol)
                       for name, item in zip(names, items)], dtype=float)
    incomes = np.asarray([_finite(f"income[{name}]", item.income)
                          for name, item in zip(names, items)], dtype=float)
    weights = np.asarray([_finite(f"weight[{name}]", item.weight)
                          for name, item in zip(names, items)], dtype=float)
    if np.any(spots <= 0.0):
        raise ValueError("all underlying spots must be positive")
    if np.any((vols < 0.0) | (vols > 5.0)):
        raise ValueError("all underlying volatilities must be in [0, 5]")
    if np.any(weights < 0.0) or weights.sum() <= 0.0:
        raise ValueError("underlying weights must be non-negative with positive sum")
    weights = weights / weights.sum()

    n_assets = len(items)
    if correlation is None:
        input_corr = np.full((n_assets, n_assets), 0.5, dtype=float)
        np.fill_diagonal(input_corr, 1.0)
    else:
        input_corr = np.asarray(correlation, dtype=float)
    if input_corr.shape != (n_assets, n_assets):
        raise ValueError(
            f"correlation matrix must have shape ({n_assets}, {n_assets})"
        )
    if not np.all(np.isfinite(input_corr)):
        raise ValueError("correlation matrix must contain only finite values")
    if np.any(np.abs(input_corr) > 1.0 + 1e-12):
        raise ValueError("correlation entries must be in [-1, 1]")
    symmetric_corr = 0.5 * (input_corr + input_corr.T)
    input_min_eigenvalue = float(np.linalg.eigvalsh(symmetric_corr).min())
    used_corr = nearest_correlation(symmetric_corr)
    corr_adjustment_norm = float(np.linalg.norm(used_corr - input_corr, ord="fro"))
    used_min_eigenvalue = float(np.linalg.eigvalsh(used_corr).min())

    paths = multi_asset_paths(
        spots, r, incomes, vols, used_corr, T, steps, n_sims, seed
    )
    if paths.shape[0] != n_sims or not np.all(np.isfinite(paths)):
        raise ValueError("Monte-Carlo engine produced non-finite paths")
    relative = paths / spots[np.newaxis, :, np.newaxis]

    pv_paths = np.zeros(n_sims, dtype=float)
    total_cashflows = np.zeros(n_sims, dtype=float)
    coupon_cashflows = np.zeros(n_sims, dtype=float)
    principal_ratios = np.zeros(n_sims, dtype=float)
    alive = np.ones(n_sims, dtype=bool)
    accrued_memory = np.zeros(n_sims, dtype=float)
    autocall_time = np.full(n_sims, T, dtype=float)
    conditional_coupon_received = np.zeros(n_sims, dtype=bool)
    memory_catchup_received = np.zeros(n_sims, dtype=bool)
    autocall_profile: list[dict[str, float]] = []
    previous_date = 0.0
    cumulative_autocall = 0

    for step, observation_date in zip(observation_steps, schedule):
        alive_at_start = alive.copy()
        if not alive_at_start.any():
            autocall_profile.append({
                "t": float(observation_date),
                "value": float(cumulative_autocall / n_sims),
            })
            previous_date = observation_date
            continue

        levels = relative[:, :, step]
        autocall_metric = _aggregate(levels, weights, autocall_aggregation)
        coupon_metric = _aggregate(levels, weights, coupon_aggregation)
        autocall = alive_at_start & (autocall_metric >= autocall_barrier)

        period = observation_date - previous_date
        current_conditional = coupon_rate * period
        if memory_coupon:
            accrued_memory[alive_at_start] += current_conditional
            conditional_due = accrued_memory
        else:
            conditional_due = np.full(n_sims, current_conditional, dtype=float)

        # Market convention: an autocall redeems with the due conditional
        # coupon even if independently configured trigger aggregations differ.
        coupon_trigger = alive_at_start & (
            (coupon_metric >= coupon_barrier) | autocall
        )
        conditional_paid = np.where(coupon_trigger, conditional_due, 0.0)
        guaranteed_paid = np.where(
            alive_at_start, guaranteed_coupon * period, 0.0
        )
        paid_ratio = conditional_paid + guaranteed_paid
        discount = math.exp(-r * observation_date)
        coupon_amount = notional * paid_ratio
        pv_paths += discount * coupon_amount
        total_cashflows += coupon_amount
        coupon_cashflows += coupon_amount
        conditional_coupon_received |= coupon_trigger & (conditional_paid > 0.0)
        if memory_coupon and current_conditional > 0.0:
            memory_catchup_received |= coupon_trigger & (
                conditional_paid > current_conditional + 1e-14
            )
            accrued_memory[coupon_trigger] = 0.0

        if autocall.any():
            redemption = notional * autocall.astype(float)
            pv_paths += discount * redemption
            total_cashflows += redemption
            principal_ratios[autocall] = 1.0
            autocall_time[autocall] = observation_date
            alive[autocall] = False
            accrued_memory[autocall] = 0.0
            cumulative_autocall += int(autocall.sum())

        autocall_profile.append({
            "t": float(observation_date),
            "value": float(cumulative_autocall / n_sims),
        })
        previous_date = observation_date

    terminal_levels = relative[:, :, -1]
    terminal_protection_metric = _aggregate(
        terminal_levels, weights, protection_aggregation
    )
    if protection_monitoring == "continuous":
        protection_path = _aggregate(relative, weights, protection_aggregation)
        protection_breached = protection_path.min(axis=1) < protection_barrier
    else:
        protection_breached = terminal_protection_metric < protection_barrier

    at_risk = alive & protection_breached & (terminal_protection_metric < 1.0)
    maturity_capital = np.where(
        at_risk,
        np.clip(terminal_protection_metric, 0.0, 1.0),
        1.0,
    )
    maturity_redemption = np.where(alive, notional * maturity_capital, 0.0)
    pv_paths += math.exp(-r * T) * maturity_redemption
    total_cashflows += maturity_redemption
    principal_ratios[alive] = maturity_capital[alive]

    if not np.all(np.isfinite(pv_paths)):
        raise ValueError("payoff engine produced non-finite present values")
    price = float(pv_paths.mean())
    path_std = float(pv_paths.std(ddof=1)) if n_sims > 1 else 0.0
    stderr = path_std / math.sqrt(n_sims)
    ci_half_width = 1.96 * stderr
    percentiles = np.percentile(pv_paths, [1, 5, 50, 95, 99])

    correlation_by_pair = {
        f"{names[i]}|{names[j]}": float(used_corr[i, j])
        for i in range(n_assets) for j in range(i + 1, n_assets)
    }
    return {
        "price": price,
        "price_ratio": price / notional,
        "stderr": stderr,
        "ci95_low": price - ci_half_width,
        "ci95_high": price + ci_half_width,
        "autocall_probability": float((~alive).mean()),
        "survival_probability": float(alive.mean()),
        "protection_breach_probability": float((alive & protection_breached).mean()),
        "capital_loss_probability": float((principal_ratios < 1.0 - 1e-14).mean()),
        "coupon_hit_probability": float(conditional_coupon_received.mean()),
        "memory_coupon_paid_probability": float(memory_catchup_received.mean()),
        "expected_life": float(autocall_time.mean()),
        "expected_principal_ratio": float(principal_ratios.mean()),
        "expected_coupon_ratio": float(coupon_cashflows.mean() / notional),
        "expected_total_cashflow_ratio": float(total_cashflows.mean() / notional),
        "expected_terminal_protection_metric": float(terminal_protection_metric.mean()),
        "pv_std": path_std,
        "pv_p01": float(percentiles[0]),
        "pv_p05": float(percentiles[1]),
        "pv_p50": float(percentiles[2]),
        "pv_p95": float(percentiles[3]),
        "pv_p99": float(percentiles[4]),
        "input_corr_min_eigenvalue": input_min_eigenvalue,
        "used_corr_min_eigenvalue": used_min_eigenvalue,
        "corr_adjustment_norm": corr_adjustment_norm,
        "n_assets": n_assets,
        "n_sims": n_sims,
        "steps": steps,
        "seed": seed,
        "observation_dates": schedule,
        "autocall_aggregation": autocall_aggregation,
        "coupon_aggregation": coupon_aggregation,
        "protection_aggregation": protection_aggregation,
        "protection_monitoring": protection_monitoring,
        "underlying_spots": {name: float(value) for name, value in zip(names, spots)},
        "underlying_vols": {name: float(value) for name, value in zip(names, vols)},
        "underlying_incomes": {name: float(value) for name, value in zip(names, incomes)},
        "underlying_weights": {name: float(value) for name, value in zip(names, weights)},
        "correlation_by_pair": correlation_by_pair,
        "autocall_cumulative": autocall_profile,
        "pv_distribution": _histogram(pv_paths),
    }


__all__ = ["multi_asset_autocall"]
