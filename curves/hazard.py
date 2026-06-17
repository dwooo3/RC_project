"""
Hazard / survival curve construction (Phase 1).

Piecewise-constant hazard rates bootstrapped from CDS par spreads so that each
quoted CDS reprices to zero NPV. The same premium/protection-leg model is used
by the bootstrap and by the pricer (instruments.credit.cds_curve), so the
round-trip is exact by construction.
"""

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq


@dataclass(frozen=True)
class HazardValidation:
    valid: bool
    errors: list[str]


class HazardCurve:
    """
    Piecewise-constant hazard curve: hazards[i] applies on (tenors[i-1], tenors[i]],
    flat extrapolation beyond the last tenor.
    """

    def __init__(self, tenors, hazards, label: str = "hazard",
                 recovery: float = 0.4, metadata: dict | None = None):
        self.tenors = np.array(tenors, dtype=float)
        self.hazards = np.array(hazards, dtype=float)
        self.label = label
        self.recovery = float(recovery)
        self.metadata = metadata or {}
        v = self.validate()
        if not v.valid:
            raise ValueError(f"Invalid hazard curve {label}: {'; '.join(v.errors)}")

    def validate(self) -> HazardValidation:
        errors = []
        if self.tenors.shape != self.hazards.shape:
            errors.append("tenors and hazards must have the same length")
            return HazardValidation(False, errors)
        if self.tenors.size == 0:
            errors.append("curve must contain at least one tenor")
        if self.tenors.size and (not np.all(np.isfinite(self.tenors)) or np.any(self.tenors <= 0)):
            errors.append("tenors must be positive and finite")
        if self.tenors.size and np.any(np.diff(self.tenors) <= 0):
            errors.append("tenors must be strictly increasing")
        if self.hazards.size and (not np.all(np.isfinite(self.hazards)) or np.any(self.hazards < 0)):
            errors.append("hazards must be non-negative and finite")
        if not 0.0 <= self.recovery < 1.0:
            errors.append("recovery must be in [0, 1)")
        return HazardValidation(not errors, errors)

    def hazard(self, t: float) -> float:
        """Instantaneous hazard λ(t) (piecewise constant, flat extrapolation)."""
        if t <= 0:
            return float(self.hazards[0])
        idx = int(np.searchsorted(self.tenors, t, side="left"))
        return float(self.hazards[min(idx, len(self.hazards) - 1)])

    def cumulative(self, t: float) -> float:
        """Cumulative hazard Λ(t) = ∫₀ᵗ λ(s) ds."""
        if t <= 0:
            return 0.0
        total, prev = 0.0, 0.0
        for T_i, h_i in zip(self.tenors, self.hazards):
            if t <= T_i:
                return total + h_i * (t - prev)
            total += h_i * (T_i - prev)
            prev = T_i
        return total + float(self.hazards[-1]) * (t - prev)

    def survival(self, t: float) -> float:
        """Survival probability Q(τ > t) = exp(-Λ(t))."""
        return float(np.exp(-self.cumulative(t)))

    def default_prob(self, t1: float, t2: float | None = None) -> float:
        """P(τ ≤ t1), or P(t1 < τ ≤ t2) when t2 is given."""
        if t2 is None:
            return 1.0 - self.survival(t1)
        return max(self.survival(t1) - self.survival(t2), 0.0)

    @classmethod
    def flat(cls, hazard: float, label: str = "flat hazard",
             recovery: float = 0.4) -> "HazardCurve":
        return cls([1.0, 5.0, 10.0, 30.0], [hazard] * 4, label=label, recovery=recovery)


# ─────────────────────────────────────────────────────────
# CDS legs on a hazard curve (shared by pricer and bootstrap)
# ─────────────────────────────────────────────────────────

def cds_legs(spread: float, T: float, freq: int, hazard_curve: HazardCurve,
             disc_curve, recovery: float | None = None,
             protection_steps_per_year: int = 52) -> dict:
    """
    Premium and protection leg PVs per unit notional.
    Premium leg includes the standard half-period accrual-on-default term.
    Protection leg integrates (1-R)·P(t)·dQ(t) on a weekly grid.
    """
    recovery = hazard_curve.recovery if recovery is None else recovery
    dt = 1.0 / freq
    n = int(round(T * freq))
    times = [i * dt for i in range(1, n + 1)]

    risky_annuity = 0.0
    prev_t = 0.0
    for t in times:
        q_prev, q_t = hazard_curve.survival(prev_t), hazard_curve.survival(t)
        df = disc_curve.discount(t)
        risky_annuity += dt * df * q_t                      # coupon paid if alive
        risky_annuity += 0.5 * dt * df * (q_prev - q_t)     # accrued on default
        prev_t = t
    premium_pv = spread * risky_annuity

    m = max(1, int(round(T * protection_steps_per_year)))
    grid = np.linspace(0.0, T, m + 1)
    protection_pv = 0.0
    for t0, t1 in zip(grid[:-1], grid[1:]):
        dq = hazard_curve.survival(t0) - hazard_curve.survival(t1)
        protection_pv += (1 - recovery) * disc_curve.discount(0.5 * (t0 + t1)) * dq

    fair_spread = protection_pv / risky_annuity if risky_annuity > 0 else float("nan")
    return dict(premium_pv=premium_pv, protection_pv=protection_pv,
                risky_annuity=risky_annuity, fair_spread=fair_spread)


# ─────────────────────────────────────────────────────────
# Bootstrap from CDS par spreads
# ─────────────────────────────────────────────────────────

def bootstrap_hazard_curve(tenors: list, spreads: list, disc_curve,
                           recovery: float = 0.4, freq: int = 4,
                           label: str = "bootstrapped hazard",
                           metadata: dict | None = None,
                           on_infeasible: str = "raise") -> HazardCurve:
    """
    Sequentially solve the piecewise-constant hazard per tenor bucket so each
    quoted CDS (par spread) has zero NPV under cds_legs. Exact round-trip with
    instruments.credit.cds_curve by construction.

    A long-end quote can be infeasible: when earlier buckets already imply low
    survival, no bucket hazard can lift the protection leg to the quoted spread
    (the quote is arbitrageable against the shorter CDS). on_infeasible:
      "raise" — ValueError naming the offending tenor (default);
      "clamp" — use the hazard that brings NPV closest to zero and record the
                tenor under metadata["infeasible_tenors"].
    """
    if len(tenors) != len(spreads):
        raise ValueError("tenors and spreads must have the same length")
    if on_infeasible not in {"raise", "clamp"}:
        raise ValueError("on_infeasible must be 'raise' or 'clamp'")

    hazards: list[float] = []
    infeasible: list[float] = []
    H_LO, H_HI = 1e-10, 10.0
    for i, (T_i, s_i) in enumerate(zip(tenors, spreads)):
        def npv(h: float) -> float:
            trial = HazardCurve(list(tenors[:i + 1]), hazards + [h],
                                recovery=recovery, label="trial")
            legs = cds_legs(s_i, T_i, freq, trial, disc_curve, recovery)
            return legs["protection_pv"] - legs["premium_pv"]

        try:
            h_i = brentq(npv, H_LO, H_HI)
        except ValueError as exc:
            if on_infeasible == "raise":
                raise ValueError(
                    f"Hazard bootstrap infeasible at tenor {T_i} (spread {s_i}): "
                    f"no bucket hazard reprices the quote given the shorter quotes. "
                    f"{exc}"
                ) from exc
            from scipy.optimize import minimize_scalar
            res = minimize_scalar(lambda h: abs(npv(h)), bounds=(H_LO, H_HI),
                                  method="bounded")
            h_i = float(res.x)
            infeasible.append(T_i)
        hazards.append(h_i)

    meta = {**(metadata or {}),
            "bootstrap": {"spreads": list(spreads), "freq": freq}}
    if infeasible:
        meta["infeasible_tenors"] = infeasible
        meta["warning"] = (
            f"Quotes at tenors {infeasible} are inconsistent with shorter quotes; "
            "bucket hazards clamped to the closest repriceable value."
        )
    return HazardCurve(list(tenors), hazards, label=label, recovery=recovery,
                       metadata=meta)


def hazard_curve_from_corp_spreads(tenors: list, z_spreads: list,
                                   recovery: float = 0.4,
                                   label: str = "hazard from corp spreads",
                                   metadata: dict | None = None) -> HazardCurve:
    """
    Approximate hazard curve from corporate z-spreads via the credit triangle
    λ ≈ s/(1-R) per bucket — for issuers without a CDS quote. Marked as an
    approximation in metadata; prefer bootstrap_hazard_curve for CDS quotes.
    """
    hazards = [max(s, 0.0) / (1 - recovery) for s in z_spreads]
    return HazardCurve(list(tenors), hazards, label=label, recovery=recovery,
                       metadata={**(metadata or {}), "method": "credit_triangle"})
