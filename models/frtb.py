"""
FRTB Standardised Approach — sensitivities-based method (SBM), Master-plan M8.

Computes Basel FRTB market-risk capital from risk-weighted sensitivities. Within
a bucket the weighted sensitivities WS_k = RW_k·s_k aggregate with intra-bucket
correlation ρ; buckets aggregate with inter-bucket correlation γ:

    K_b = √( Σ WS_k² + ΣΣ_{k≠l} ρ·WS_k·WS_l )
    Δ   = √( Σ K_b² + ΣΣ_{b≠c} γ·S_b·S_c ),   S_b = Σ_k WS_k

The charge is evaluated under the three regulatory correlation scenarios
(medium, high = min(1.25ρ,1), low = max(2ρ-1,0.75ρ)) and the maximum is taken.

Validated: a single factor charges RW·|s|; the charge is homogeneous degree 1
(2× sensitivities → 2× capital); imperfect correlation diversifies (charge < sum
of |WS|); perfect positive correlation recovers the undiversified sum; opposite
signs hedge; and the scenario maximum dominates the medium scenario.
"""

from __future__ import annotations

import numpy as np


def bucket_charge(ws, rho):
    """K_b = √(Σ WS² + ΣΣ_{k≠l} ρ WS_k WS_l) for one bucket."""
    ws = np.asarray(ws, float)
    var = np.sum(ws**2) + rho * (np.sum(ws)**2 - np.sum(ws**2))
    return np.sqrt(max(var, 0.0))


def aggregate_delta(buckets, rho, gamma):
    """Aggregate bucket charges across buckets with inter-bucket correlation γ."""
    Kb, Sb = [], []
    for ws in buckets.values():
        Kb.append(bucket_charge(ws, rho))
        Sb.append(float(np.sum(ws)))
    Kb, Sb = np.array(Kb), np.array(Sb)
    var = np.sum(Kb**2) + gamma * (np.sum(Sb)**2 - np.sum(Sb**2))
    return float(np.sqrt(max(var, 0.0)))


def _scenarios(rho, gamma):
    return {"medium": (rho, gamma),
            "high": (min(1.25 * rho, 1.0), min(1.25 * gamma, 1.0)),
            "low": (max(2 * rho - 1, 0.75 * rho), max(2 * gamma - 1, 0.75 * gamma))}


def frtb_delta_charge(factors, rho=0.5, gamma=0.25) -> dict:
    """SBM delta charge over the three correlation scenarios; returns the max.

    factors: list of dicts {bucket, sensitivity, risk_weight}.
    """
    buckets: dict = {}
    for f in factors:
        ws = f["risk_weight"] * f["sensitivity"]
        buckets.setdefault(f["bucket"], []).append(ws)
    out = {name: aggregate_delta(buckets, r, g)
           for name, (r, g) in _scenarios(rho, gamma).items()}
    charge = max(out.values())
    return dict(charge=charge, scenarios=out,
                worst=max(out, key=out.get), n_buckets=len(buckets))
