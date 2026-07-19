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
from dataclasses import replace
import math

import numpy as np

from instruments.structured.basket_note import Constituent, nearest_correlation


_AGGREGATIONS = frozenset({"worst_of", "best_of", "average"})
_MONITORING = frozenset({"maturity", "continuous"})
_MAX_ASSETS = 5
# The engine retains float64[n_sims, n_assets, steps + 1] relative paths; its
# correlated-normal cube has approximately the same size while paths are built.
# Fail explicitly rather than letting a user-configured run exhaust the desktop
# process.  The tighter Greeks limit below accounts for retaining both cubes.
_MAX_PATH_POINTS = 25_000_000
# Component Greeks retain both the common correlated shocks and one reusable
# relative-path cube.  Bound their combined float64 footprint to roughly the
# same 200 MB target as a normal pricing call before payoff temporaries.
_MAX_GREEK_PATH_POINTS = 12_500_000


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


def _resolved_correlation(
    correlation: np.ndarray | Sequence[Sequence[float]] | None,
    n_assets: int,
) -> tuple[np.ndarray, float, float, float]:
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
    return (
        used_corr,
        input_min_eigenvalue,
        corr_adjustment_norm,
        used_min_eigenvalue,
    )


def _correlated_normals(
    used_corr: np.ndarray,
    n_sims: int,
    steps: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    independent = rng.standard_normal((n_sims, steps, len(used_corr)))
    return independent @ np.linalg.cholesky(used_corr).T


def _relative_paths_from_normals(
    spots: np.ndarray,
    references: np.ndarray,
    r: float,
    incomes: np.ndarray,
    vols: np.ndarray,
    T: float,
    normals: np.ndarray,
) -> np.ndarray:
    """Build S(t)/reference paths from one reusable correlated shock cube."""
    n_sims, steps, n_assets = normals.shape
    if len(spots) != n_assets:
        raise ValueError("correlated shock cube has the wrong asset dimension")
    dt = T / steps
    increments = (
        (r - incomes - 0.5 * vols ** 2)[np.newaxis, np.newaxis, :] * dt
        + vols[np.newaxis, np.newaxis, :] * math.sqrt(dt) * normals
    )
    np.cumsum(increments, axis=1, out=increments)
    increments += np.log(spots / references)[np.newaxis, np.newaxis, :]
    np.exp(increments, out=increments)
    relative = np.empty((n_sims, n_assets, steps + 1), dtype=float)
    relative[:, :, 0] = spots / references
    relative[:, :, 1:] = increments.transpose(0, 2, 1)
    return relative


def _relative_component_from_normals(
    spot: float,
    reference: float,
    r: float,
    income: float,
    vol: float,
    T: float,
    normals: np.ndarray,
) -> np.ndarray:
    """Rebuild one component only, retaining common shocks for a vol bump."""
    n_sims, steps = normals.shape
    dt = T / steps
    increments = (
        (r - income - 0.5 * vol ** 2) * dt
        + vol * math.sqrt(dt) * normals
    )
    np.cumsum(increments, axis=1, out=increments)
    increments += math.log(spot / reference)
    np.exp(increments, out=increments)
    out = np.empty((n_sims, steps + 1), dtype=float)
    out[:, 0] = spot / reference
    out[:, 1:] = increments
    return out


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
    reference_spots: Sequence[float] | None = None,
    _relative_paths_override: np.ndarray | None = None,
) -> dict:
    """Price a 1--5 asset autocall and return audit-friendly diagnostics.

    Barrier and coupon rates are ratios/rates (``0.65`` = 65%).  The returned
    headline ``price`` is in the same currency units as ``notional``.

    ``reference_spots`` are the immutable trade fixing levels used by every
    relative barrier.  They default to the current constituent spots for an
    inception valuation.  Supplying them separately is mandatory for a later
    scenario revaluation: a market shock must move the current spots without
    resetting the contractual barriers.
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
    if reference_spots is None:
        references = spots.copy()
    else:
        try:
            reference_values = list(reference_spots)
        except TypeError as exc:
            raise ValueError("reference_spots must be a sequence") from exc
        if len(reference_values) != len(items):
            raise ValueError(
                "reference_spots must have one value per underlying"
            )
        references = np.asarray([
            _finite(f"reference_spot[{name}]", value)
            for name, value in zip(names, reference_values)
        ], dtype=float)
    vols = np.asarray([_finite(f"vol[{name}]", item.vol)
                       for name, item in zip(names, items)], dtype=float)
    incomes = np.asarray([_finite(f"income[{name}]", item.income)
                          for name, item in zip(names, items)], dtype=float)
    weights = np.asarray([_finite(f"weight[{name}]", item.weight)
                          for name, item in zip(names, items)], dtype=float)
    if np.any(spots <= 0.0):
        raise ValueError("all underlying spots must be positive")
    if np.any(references <= 0.0):
        raise ValueError("all reference spots must be positive")
    if np.any((vols < 0.0) | (vols > 5.0)):
        raise ValueError("all underlying volatilities must be in [0, 5]")
    if np.any(weights < 0.0) or weights.sum() <= 0.0:
        raise ValueError("underlying weights must be non-negative with positive sum")
    weights = weights / weights.sum()

    n_assets = len(items)
    (
        used_corr,
        input_min_eigenvalue,
        corr_adjustment_norm,
        used_min_eigenvalue,
    ) = _resolved_correlation(correlation, n_assets)

    if _relative_paths_override is None:
        normals = _correlated_normals(used_corr, n_sims, steps, seed)
        relative = _relative_paths_from_normals(
            spots, references, r, incomes, vols, T, normals
        )
    else:
        relative = np.asarray(_relative_paths_override, dtype=float)
        expected_shape = (n_sims, n_assets, steps + 1)
        if relative.shape != expected_shape:
            raise ValueError(
                "internal relative path cube must have shape "
                f"{expected_shape}"
            )
        expected_initial = spots / references
        if not np.allclose(
                relative[:, :, 0], expected_initial[np.newaxis, :],
                rtol=1e-12, atol=1e-14):
            raise ValueError(
                "internal relative path cube has inconsistent initial levels"
            )
    if not np.all(np.isfinite(relative)):
        raise ValueError("Monte-Carlo engine produced non-finite paths")
    if relative.shape[0] != n_sims:
        raise ValueError("Monte-Carlo engine produced the wrong path count")

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
        "reference_spots": {
            name: float(value) for name, value in zip(names, references)
        },
        "underlying_vols": {name: float(value) for name, value in zip(names, vols)},
        "underlying_incomes": {name: float(value) for name, value in zip(names, incomes)},
        "underlying_weights": {name: float(value) for name, value in zip(names, weights)},
        "correlation_by_pair": correlation_by_pair,
        "autocall_cumulative": autocall_profile,
        "pv_distribution": _histogram(pv_paths),
    }


def multi_asset_autocall_component_greeks(
    constituents: Sequence[Constituent],
    r: float,
    T: float,
    correlation: np.ndarray | Sequence[Sequence[float]] | None = None,
    *,
    reference_spots: Sequence[float] | None = None,
    spot_bump_relative: float = 0.01,
    vol_bump: float = 0.01,
    **contract,
) -> dict:
    """CRN finite-difference component Greeks for an autocall.

    Every bumped valuation reuses the exact same seed from ``contract``.  The
    resulting common random numbers materially reduce nested-Monte-Carlo noise
    compared with independent bump runs.  Delta and Gamma are per one price
    unit of the named component; Vega is per one volatility percentage point.

    This function deliberately requires explicit immutable reference levels.
    Resetting a relative barrier to each bumped current spot would manufacture
    zero spot risk and is therefore rejected at this risk boundary.
    """
    items = list(constituents)
    if reference_spots is None:
        raise ValueError(
            "component Greeks require explicit immutable reference_spots"
        )
    references = list(reference_spots)
    if len(references) != len(items):
        raise ValueError("reference_spots must have one value per underlying")
    spot_bump_relative = _finite("spot_bump_relative", spot_bump_relative)
    if not 0.0 < spot_bump_relative <= 0.50:
        raise ValueError("spot_bump_relative must be in (0, 0.5]")
    vol_bump = _finite("vol_bump", vol_bump)
    if not 0.0 < vol_bump <= 0.50:
        raise ValueError("vol_bump must be in (0, 0.5]")

    # Pin a deterministic seed even when a caller omitted it.  The base and
    # every bump must consume the same random stream for CRN semantics.
    terms = dict(contract)
    if "_relative_paths_override" in terms:
        raise ValueError("internal relative path override is not a contract term")
    terms["seed"] = _positive_int("seed", terms.get("seed", 42), 0)
    if terms["seed"] > np.iinfo(np.uint32).max:
        raise ValueError("seed must be <= 4294967295")
    terms["n_sims"] = _positive_int(
        "n_sims", terms.get("n_sims", 20_000), 1_000
    )
    terms["steps"] = _positive_int("steps", terms.get("steps", 100), 1)
    r = _finite("r", r)
    T = _finite("T", T)
    if T <= 0.0:
        raise ValueError("T must be positive")

    names = [str(item.name).strip() for item in items]
    if not 1 <= len(items) <= _MAX_ASSETS:
        raise ValueError("multi-asset autocall requires 1 to 5 underlyings")
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("underlying names must be non-empty and unique")
    spots = np.asarray([
        _finite(f"spot[{name}]", item.spot)
        for name, item in zip(names, items)
    ], dtype=float)
    references_array = np.asarray([
        _finite(f"reference_spot[{name}]", value)
        for name, value in zip(names, references)
    ], dtype=float)
    vols = np.asarray([
        _finite(f"vol[{name}]", item.vol)
        for name, item in zip(names, items)
    ], dtype=float)
    incomes = np.asarray([
        _finite(f"income[{name}]", item.income)
        for name, item in zip(names, items)
    ], dtype=float)
    if np.any(spots <= 0.0) or np.any(references_array <= 0.0):
        raise ValueError("spots and reference_spots must be positive")
    if np.any((vols < 0.0) | (vols > 5.0)):
        raise ValueError("all underlying volatilities must be in [0, 5]")

    grid_points = (
        terms["n_sims"] * len(items) * (terms["steps"] + 1)
    )
    if grid_points > _MAX_GREEK_PATH_POINTS:
        raise ValueError(
            "component Greek grid is too large; require n_sims * n_assets * "
            "(steps + 1) <= 12500000"
        )
    schedule = _observation_schedule(terms.get("observation_dates"), T)
    dt = T / terms["steps"]
    observation_steps = [
        min(terms["steps"], max(1, int(round(value / dt))))
        for value in schedule
    ]
    if len(set(observation_steps)) != len(observation_steps):
        raise ValueError("steps is too small to distinguish all observation dates")
    used_corr, _input_eigen, _adjustment, _used_eigen = (
        _resolved_correlation(correlation, len(items))
    )
    normals = _correlated_normals(
        used_corr, terms["n_sims"], terms["steps"], terms["seed"]
    )
    reusable_relative = _relative_paths_from_normals(
        spots, references_array, r, incomes, vols, T, normals
    )

    def price(current: list[Constituent], relative_paths: np.ndarray) -> float:
        result = multi_asset_autocall(
            current,
            r,
            T,
            correlation,
            reference_spots=references,
            _relative_paths_override=relative_paths,
            **terms,
        )
        value = float(result["price"])
        if not math.isfinite(value):
            raise ValueError("component bump returned a non-finite price")
        return value

    base_result = multi_asset_autocall(
        items,
        r,
        T,
        correlation,
        reference_spots=references,
        _relative_paths_override=reusable_relative,
        **terms,
    )
    base = float(base_result["price"])
    component_rows: dict[str, dict[str, float | str]] = {}
    for index, item in enumerate(items):
        spot = _finite(f"spot[{item.name}]", item.spot)
        ds = max(abs(spot) * spot_bump_relative, 1e-4)
        if spot - ds <= 0.0:  # defensive if the relative bound is relaxed later
            ds = max(spot * 0.5, 1e-8)
        spot_up = list(items)
        spot_down = list(items)
        spot_up[index] = replace(item, spot=spot + ds)
        spot_down[index] = replace(item, spot=spot - ds)
        base_component = reusable_relative[:, index, :].copy()
        try:
            reusable_relative[:, index, :] = base_component * (
                (spot + ds) / spot
            )
            up = price(spot_up, reusable_relative)
            reusable_relative[:, index, :] = base_component * (
                (spot - ds) / spot
            )
            down = price(spot_down, reusable_relative)
        finally:
            reusable_relative[:, index, :] = base_component
        delta = (up - down) / (2.0 * ds)
        gamma = (up - 2.0 * base + down) / (ds * ds)

        sigma = _finite(f"vol[{item.name}]", item.vol)
        upper_sigma = sigma + vol_bump
        lower_sigma = max(sigma - vol_bump, 0.0)
        if upper_sigma > 5.0:
            upper_sigma = 5.0
        span = upper_sigma - lower_sigma
        if span <= 0.0:
            raise ValueError(
                f"volatility bump for '{item.name}' has no valid finite span"
            )
        vol_up = list(items)
        vol_down = list(items)
        vol_up[index] = replace(item, vol=upper_sigma)
        vol_down[index] = replace(item, vol=lower_sigma)
        try:
            reusable_relative[:, index, :] = _relative_component_from_normals(
                spot,
                references_array[index],
                r,
                incomes[index],
                upper_sigma,
                T,
                normals[:, :, index],
            )
            price_up_vol = price(vol_up, reusable_relative)
            reusable_relative[:, index, :] = _relative_component_from_normals(
                spot,
                references_array[index],
                r,
                incomes[index],
                lower_sigma,
                T,
                normals[:, :, index],
            )
            price_down_vol = price(vol_down, reusable_relative)
        finally:
            reusable_relative[:, index, :] = base_component
        vega = (price_up_vol - price_down_vol) / span * 0.01

        values = (delta, gamma, vega)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(
                f"component Greeks for '{item.name}' are non-finite"
            )
        component_rows[str(item.name)] = {
            "kind": str(item.kind),
            "delta": float(delta),
            "gamma": float(gamma),
            "diagonal_gamma": float(gamma),
            "vega": float(vega),
            "spot_bump": float(ds),
            "vol_bump": float(span),
            "gamma_convention": "d2PV/dS_i2",
        }

    # A sum of diagonal d2PV/dS_i2 values is not the Gamma of a parallel
    # basket move: it omits cross-partials and even mixes sensitivities whose
    # underlyings have different price units.  Revalue an explicit common
    # relative shock S_i(x)=S_i*(1+x) on the same random paths.  The resulting
    # d2PV/dx2 contains both weighted diagonal and 2-way cross-Gamma terms.
    parallel_up_items = [
        replace(item, spot=float(item.spot) * (1.0 + spot_bump_relative))
        for item in items
    ]
    parallel_down_items = [
        replace(item, spot=float(item.spot) * (1.0 - spot_bump_relative))
        for item in items
    ]
    try:
        reusable_relative *= 1.0 + spot_bump_relative
        parallel_up = price(parallel_up_items, reusable_relative)
    finally:
        reusable_relative /= 1.0 + spot_bump_relative
    try:
        reusable_relative *= 1.0 - spot_bump_relative
        parallel_down = price(parallel_down_items, reusable_relative)
    finally:
        reusable_relative /= 1.0 - spot_bump_relative
    parallel_delta = (
        (parallel_up - parallel_down) / (2.0 * spot_bump_relative)
    )
    parallel_gamma = (
        (parallel_up - 2.0 * base + parallel_down)
        / (spot_bump_relative * spot_bump_relative)
    )
    parallel_diagonal_gamma = float(sum(
        float(component_rows[str(item.name)]["diagonal_gamma"])
        * float(item.spot) ** 2
        for item in items
    ))
    parallel_cross_gamma = parallel_gamma - parallel_diagonal_gamma
    if not all(math.isfinite(value) for value in (
            parallel_delta, parallel_gamma, parallel_diagonal_gamma,
            parallel_cross_gamma)):
        raise ValueError("parallel component Greeks are non-finite")

    base_result["component_greeks"] = component_rows
    base_result["delta"] = float(sum(
        float(row["delta"]) for row in component_rows.values()
    ))
    base_result["component_diagonal_gamma_sum"] = float(sum(
        float(row["diagonal_gamma"]) for row in component_rows.values()
    ))
    base_result["parallel_delta"] = float(parallel_delta)
    base_result["parallel_gamma"] = float(parallel_gamma)
    base_result["parallel_diagonal_gamma"] = parallel_diagonal_gamma
    base_result["parallel_cross_gamma"] = float(parallel_cross_gamma)
    base_result["parallel_spot_bump_relative"] = float(spot_bump_relative)
    # Backward-compatible headline now has the economically correct aggregate
    # meaning. Component rows retain their explicit diagonal Gamma.
    base_result["gamma"] = float(parallel_gamma)
    base_result["gamma_convention"] = (
        "d2PV/dx2 for parallel relative spot shock S_i(x)=S_i*(1+x)"
    )
    base_result["vega"] = float(sum(
        float(row["vega"]) for row in component_rows.values()
    ))
    base_result["greeks_method"] = (
        "central_fd_common_random_numbers_with_parallel_cross_gamma"
    )
    return base_result


__all__ = [
    "multi_asset_autocall",
    "multi_asset_autocall_component_greeks",
]
