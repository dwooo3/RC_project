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


def frtb_vega_charge(factors, rho=0.5, gamma=0.25) -> dict:
    """SBM vega charge — structurally identical aggregation to delta, fed with
    vega sensitivities × vega risk weights. factors: {bucket, sensitivity, risk_weight}."""
    return frtb_delta_charge(factors, rho, gamma)


# ── curvature ────────────────────────────────────────────────

def curvature_cvr(pv0, pv_up, pv_down, delta, rw_curv):
    """CVR_k = -min(ΔPV_up - RW·δ, ΔPV_down + RW·δ) from up/down shock revals."""
    up = (pv_up - pv0) - rw_curv * delta
    down = (pv_down - pv0) + rw_curv * delta
    return -min(up, down)


def _bucket_curvature(cvr, rho):
    cvr = np.asarray(cvr, float)
    pos = np.maximum(cvr, 0.0)
    psi = ~((cvr[:, None] < 0) & (cvr[None, :] < 0))    # 1 unless both negative
    M = rho * psi.astype(float)
    np.fill_diagonal(M, 0.0)
    var = np.sum(pos**2) + np.sum(M * np.outer(cvr, cvr))
    return np.sqrt(max(var, 0.0))


def _aggregate_curvature(buckets, rho, gamma):
    Kb = np.array([_bucket_curvature(c, rho) for c in buckets.values()])
    Sb = np.array([float(np.sum(c)) for c in buckets.values()])
    psi = ~((Sb[:, None] < 0) & (Sb[None, :] < 0))
    M = gamma * psi.astype(float)
    np.fill_diagonal(M, 0.0)
    var = np.sum(Kb**2) + np.sum(M * np.outer(Sb, Sb))
    return float(np.sqrt(max(var, 0.0)))


def frtb_curvature_charge(factors, rho=0.5, gamma=0.25) -> dict:
    """SBM curvature charge over the three scenarios. factors: {bucket, cvr}."""
    buckets: dict = {}
    for f in factors:
        buckets.setdefault(f["bucket"], []).append(f["cvr"])
    out = {name: _aggregate_curvature(buckets, r, g)
           for name, (r, g) in _scenarios(rho, gamma).items()}
    charge = max(out.values())
    return dict(charge=charge, scenarios=out, worst=max(out, key=out.get))


# ── default risk charge (DRC) ────────────────────────────────

def frtb_drc_charge(factors) -> dict:
    """Default Risk Charge (non-securitisation): per bucket net long/short JTD
    with the gross-JTD hedge-benefit ratio. factors: {bucket, jtd, risk_weight}
    (jtd signed: long > 0, short < 0)."""
    buckets: dict = {}
    for f in factors:
        buckets.setdefault(f["bucket"], []).append(f["risk_weight"] * f["jtd"])
    per_bucket, total = {}, 0.0
    for b, rwjtd in buckets.items():
        arr = np.asarray(rwjtd, float)
        long = float(np.sum(np.maximum(arr, 0.0)))
        short = float(np.sum(np.maximum(-arr, 0.0)))
        wts = long / (long + short) if (long + short) > 0 else 0.0
        drc_b = max(long - wts * short, 0.0)
        per_bucket[b] = drc_b
        total += drc_b
    return dict(charge=total, per_bucket=per_bucket, hedge_benefit_ratio=wts if buckets else 0.0)


# ── total SBM + DRC ──────────────────────────────────────────

def frtb_capital(delta_factors=None, vega_factors=None, curvature_factors=None,
                 drc_factors=None, rho=0.5, gamma=0.25) -> dict:
    """Total FRTB-SA: SBM (delta + vega + curvature, each scenario-maxed) + DRC."""
    d = frtb_delta_charge(delta_factors, rho, gamma)["charge"] if delta_factors else 0.0
    v = frtb_vega_charge(vega_factors, rho, gamma)["charge"] if vega_factors else 0.0
    c = frtb_curvature_charge(curvature_factors, rho, gamma)["charge"] if curvature_factors else 0.0
    drc = frtb_drc_charge(drc_factors)["charge"] if drc_factors else 0.0
    sbm = d + v + c
    return dict(delta=d, vega=v, curvature=c, sbm=sbm, drc=drc, total=sbm + drc)


# ── FRTB Internal Models Approach (expected shortfall), gap batch 4 ──

def frtb_ima_es(pnl_scenarios, alpha=0.975, liquidity_scale=1.0):
    """FRTB-IMA expected-shortfall charge: ES at the α level of the loss
    distribution (mean loss beyond the α-VaR), scaled for liquidity horizons.
    pnl_scenarios: array of portfolio P&L (gains +, losses -)."""
    losses = -np.asarray(pnl_scenarios, float)
    var = np.quantile(losses, alpha)
    tail = losses[losses >= var]
    es = float(tail.mean()) if tail.size else float(var)
    return dict(es=es * liquidity_scale, var=float(var) * liquidity_scale,
                alpha=alpha)
