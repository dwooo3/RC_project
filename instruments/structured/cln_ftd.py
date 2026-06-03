"""
Credit-Linked Notes (CLN) and First-to-Default (FTD) baskets.
"""

import numpy as np
from scipy.stats import norm


# ─────────────────────────────────────────────────────────
# Credit-Linked Note (CLN)
# ─────────────────────────────────────────────────────────

def cln(
    face: float,
    coupon_rate: float,       # total coupon = risk-free + spread
    T: float,
    freq: int,
    r: float,                 # risk-free discount rate
    hazard: float,            # issuer hazard rate
    recovery: float = 0.40,
    reference_hazard: float = None,  # reference entity hazard (if different)
    reference_recovery: float = 0.40,
) -> dict:
    """
    Credit-Linked Note: bond with embedded credit risk of reference entity.
    If reference entity defaults:
      - Note redeems at face * recovery_reference
    Investor receives enhanced coupon = risk-free + credit spread.

    Pricing: CLN = Bond * Q(no default) + Recovery * P(default)
    """
    if reference_hazard is None:
        reference_hazard = hazard

    dt      = 1.0 / freq
    periods = int(round(T * freq))
    times   = [i*dt for i in range(1, periods+1)]

    def surv(t, h): return np.exp(-h * t)
    def disc_risk(t): return np.exp(-(r + reference_hazard) * t)  # risky discount

    # Premium leg: coupon payments when no default
    pv_coupons = sum(face * coupon_rate/freq * disc_risk(t) for t in times)

    # Principal leg: receive face at T if no default
    pv_principal = face * disc_risk(T)

    # Recovery leg: receive recovery if reference defaults
    dt_int = 0.01
    t_arr  = np.arange(dt_int, T+dt_int, dt_int)
    pv_recovery = (face * reference_recovery * reference_hazard
                   * np.sum(np.exp(-(r + reference_hazard)*t_arr)) * dt_int)

    cln_price = pv_coupons + pv_principal + pv_recovery

    # Fair spread (s such that CLN = face)
    from scipy.optimize import brentq
    def eq(s):
        coup_adj = sum(face*(coupon_rate+s)/freq * disc_risk(t) for t in times)
        return coup_adj + pv_principal + pv_recovery - face

    try:
        fair_spread = brentq(eq, -0.5, 5.0)
    except ValueError:
        fair_spread = np.nan

    default_prob = 1 - surv(T, reference_hazard)

    return dict(
        price=cln_price,
        fair_spread=fair_spread,
        fair_spread_bps=fair_spread*10000 if fair_spread==fair_spread else None,
        default_prob=default_prob,
        pv_coupons=pv_coupons,
        pv_principal=pv_principal,
        pv_recovery=pv_recovery,
        reference_hazard=reference_hazard,
        recovery=reference_recovery,
    )


# ─────────────────────────────────────────────────────────
# First-to-Default (FTD) basket
# ─────────────────────────────────────────────────────────

def ftd_basket(
    face: float,
    coupon_rate: float,      # FTD note coupon
    T: float,
    freq: int,
    r: float,                # risk-free rate
    hazards: list,           # list of hazard rates for n names
    recovery: float = 0.40,
    correlation: float = 0.30,  # pairwise Gaussian copula correlation
    n_sims: int = 100_000, seed: int = 42,
) -> dict:
    """
    First-to-Default (FTD) basket note.
    Pays until first default in basket; upon default pays face*recovery.
    Uses Gaussian copula simulation for correlated defaults.

    Parameters
    ----------
    hazards: list of hazard rates for each name in basket
    correlation: pairwise Gaussian copula correlation (flat)
    """
    rng  = np.random.default_rng(seed)
    n    = len(hazards)
    dt_  = 1.0 / freq
    periods = int(round(T*freq))
    times   = [i*dt_ for i in range(1, periods+1)]

    # Default times via Gaussian copula
    corr_matrix = np.full((n,n), correlation)
    np.fill_diagonal(corr_matrix, 1.0)
    L = np.linalg.cholesky(corr_matrix)

    Z = rng.standard_normal((n_sims, n)) @ L.T  # correlated normals
    U = norm.cdf(Z)  # uniform via probability integral transform

    # Map to default times: tau_i = -log(1-U_i)/lambda_i
    default_times = np.array([
        -np.log(np.maximum(1 - U[:,i], 1e-15)) / hazards[i]
        for i in range(n)
    ]).T  # (n_sims, n_names)

    ftd_times = default_times.min(axis=1)  # first default time

    # Value of FTD note
    pv_coupon = np.zeros(n_sims)
    pv_recov  = np.zeros(n_sims)

    for j, t in enumerate(times):
        survived = ftd_times > t
        pv_coupon += survived * face * coupon_rate/freq * np.exp(-r*t)

    # Recovery at first default (if before T)
    defaulted = ftd_times <= T
    pv_recov[defaulted] = (face * recovery * np.exp(-r * ftd_times[defaulted]))

    # Principal back if survived to T
    survived_T = ftd_times > T
    pv_principal = survived_T * face * np.exp(-r*T)

    total_pv = pv_coupon + pv_recov + pv_principal
    price    = total_pv.mean()
    stderr   = total_pv.std() / np.sqrt(n_sims)

    default_prob_before_T = defaulted.mean()

    # Fair spread
    def eq_spread(s):
        cpn_adj = np.zeros(n_sims)
        for t in times:
            survived = ftd_times > t
            cpn_adj += survived * face * (coupon_rate+s)/freq * np.exp(-r*t)
        return (cpn_adj + pv_recov + pv_principal).mean() - face

    from scipy.optimize import brentq
    try:
        fair_spread = brentq(eq_spread, -0.5, 5.0)
    except ValueError:
        fair_spread = np.nan

    return dict(
        price=price, stderr=stderr,
        fair_spread=fair_spread,
        fair_spread_bps=fair_spread*10000 if fair_spread==fair_spread else None,
        default_prob=default_prob_before_T,
        avg_ftd_time=ftd_times[defaulted].mean() if defaulted.any() else None,
        n_names=n, correlation=correlation, n_sims=n_sims,
    )


# ─────────────────────────────────────────────────────────
# Nth-to-Default basket (generalisation)
# ─────────────────────────────────────────────────────────

def nth_to_default(
    n_th: int,
    face: float, coupon_rate: float, T: float, freq: int, r: float,
    hazards: list, recovery: float = 0.40, correlation: float = 0.30,
    n_sims: int = 100_000, seed: int = 42,
) -> dict:
    """Nth-to-Default basket (FTD is n_th=1)."""
    rng = np.random.default_rng(seed)
    n   = len(hazards)
    corr_mat = np.full((n,n), correlation); np.fill_diagonal(corr_mat,1.0)
    L = np.linalg.cholesky(corr_mat)
    Z = rng.standard_normal((n_sims, n)) @ L.T
    U = norm.cdf(Z)
    default_times = np.array([
        -np.log(np.maximum(1-U[:,i],1e-15))/hazards[i] for i in range(n)
    ]).T
    sorted_times = np.sort(default_times, axis=1)
    nth_times = sorted_times[:, n_th-1]  # nth-to-default time

    dt_  = 1.0/freq; periods = int(round(T*freq))
    times_sched = [i*dt_ for i in range(1,periods+1)]
    pv = np.zeros(n_sims)
    for t in times_sched:
        pv += (nth_times > t)*face*coupon_rate/freq*np.exp(-r*t)
    defaulted = nth_times <= T
    pv[defaulted] += face*recovery*np.exp(-r*nth_times[defaulted])
    pv[~defaulted] += face*np.exp(-r*T)

    return dict(
        price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims),
        default_prob=defaulted.mean(), n_th=n_th, n_names=n,
    )
