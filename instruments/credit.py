"""
Credit instruments:
  - CDS (Credit Default Swap) — pricing and spread
  - Survival probability (flat hazard rate)
  - CDO tranche pricing (large homogeneous pool)
  - Credit spread option
  - Default digital (binary CDS)
  - CDS swaption
  - CVA / DVA (simple unilateral)
"""

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm


# ─────────────────────────────────────────────────────────
# Hazard rate / survival probability
# ─────────────────────────────────────────────────────────

def survival_prob(T: float, hazard: float) -> float:
    """Survival probability under constant hazard rate λ: Q(τ>T) = exp(-λT)."""
    return np.exp(-hazard * T)


def hazard_from_spread(spread: float, recovery: float = 0.4) -> float:
    """Approximate hazard rate: λ ≈ spread / (1 - R)."""
    return spread / (1 - recovery)


def survival_curve_from_spreads(tenors: list, spreads: list,
                                 recovery: float = 0.4,
                                 r_curve=None) -> dict:
    """
    Piecewise constant hazard rate curve bootstrapped from CDS spreads.
    Returns dict with tenors and hazard rates.
    """
    hazards = []
    prev_T  = 0.0
    prev_SP = 1.0

    for T, s in zip(tenors, spreads):
        h = s / (1 - recovery)  # first approximation per segment
        hazards.append(h)

    return dict(tenors=tenors, hazards=hazards,
                survival=[np.exp(-h*t) for h, t in zip(hazards, tenors)])


# ─────────────────────────────────────────────────────────
# CDS Pricing
# ─────────────────────────────────────────────────────────

def cds(notional: float, spread: float, T: float, freq: int,
        hazard: float, r: float, recovery: float = 0.4,
        buy_protection: bool = True) -> dict:
    """
    CDS pricing.
    spread:    contracted CDS spread (annual, e.g. 0.01 = 100bps)
    hazard:    risk-neutral hazard rate (constant)
    Returns: NPV, fair spread, DV01 (risky annuity), risky duration.
    """
    dt     = 1.0 / freq
    times  = [i*dt for i in range(1, int(round(T*freq))+1)]

    # premium leg PV (accruing spread per period, weighted by survival)
    risky_annuity = sum(dt * np.exp(-r*t) * survival_prob(t, hazard) for t in times)
    premium_pv    = spread * notional * risky_annuity

    # protection leg PV = integral of (1-R)*lambda*exp(-r*t)*Q(tau>t)
    dt_int = 0.01
    t_int  = np.arange(dt_int, T + dt_int, dt_int)
    prot_pv = notional * (1-recovery) * hazard * np.sum(
                np.exp(-r*t_int) * np.exp(-hazard*t_int)) * dt_int

    npv = (prot_pv - premium_pv) if buy_protection else (premium_pv - prot_pv)

    # fair CDS spread
    fair_spread = prot_pv / (notional * risky_annuity) if risky_annuity > 0 else np.nan

    dv01 = notional * risky_annuity / 10000  # per bp move in spread
    risky_dur = risky_annuity

    return dict(npv=npv, fair_spread=fair_spread, premium_pv=premium_pv,
                protection_pv=prot_pv, risky_annuity=risky_annuity,
                dv01=dv01, risky_duration=risky_dur)


def cds_implied_hazard(market_spread: float, T: float, freq: int,
                        r: float, recovery: float = 0.4) -> float:
    """Extract implied hazard rate from market CDS spread."""
    def eq(h):
        res = cds(1, market_spread, T, freq, h, r, recovery)
        return res["npv"]
    try:
        return brentq(eq, 1e-6, 5.0)
    except ValueError:
        return market_spread / (1 - recovery)


# ─────────────────────────────────────────────────────────
# Default digital (binary CDS)
# ─────────────────────────────────────────────────────────

def default_digital(notional: float, T: float, hazard: float,
                    r: float, pay_on: str = "default") -> dict:
    """
    Binary CDS: pays notional on default (pay_on='default') or survival.
    """
    dt_int = 0.01
    t_arr  = np.arange(dt_int, T+dt_int, dt_int)
    default_pv = notional * hazard * np.sum(np.exp(-r*t_arr) * np.exp(-hazard*t_arr)) * dt_int
    survival_pv = notional * np.exp(-(r + hazard)*T)

    if pay_on == "default":
        return dict(price=default_pv, pd=1 - np.exp(-hazard*T))
    else:
        return dict(price=survival_pv, ps=np.exp(-hazard*T))


# ─────────────────────────────────────────────────────────
# CDO tranche pricing (LHP — Large Homogeneous Pool)
# ─────────────────────────────────────────────────────────

def cdo_lhp(notional: float, K1: float, K2: float,
            T: float, n: int, p: float, rho: float,
            r: float, recovery: float = 0.4) -> dict:
    """
    CDO tranche [K1, K2] via Vasicek Large Homogeneous Pool (Gaussian copula).
    n: number of names, p: unconditional default probability, rho: correlation.
    """
    from scipy.stats import norm as N

    def cond_loss_prob(x, p_, rho_):
        q = N.ppf(p_)
        return N.cdf((q - np.sqrt(rho_)*x) / np.sqrt(1-rho_))

    def expected_tranche_loss(K_lo, K_hi, M=100):
        """Integrate E[L_tranche] numerically over systematic factor x."""
        x_pts = np.linspace(-5, 5, M)
        dx    = x_pts[1] - x_pts[0]
        e_loss = 0.0
        lgd = 1 - recovery
        for x in x_pts:
            p_x    = cond_loss_prob(x, p, rho)
            # expected pool loss given x (normal approximation)
            mu_L   = n * p_x * lgd
            sig_L  = np.sqrt(n * p_x * (1-p_x)) * lgd
            # E[max(L-K1,0)] - E[max(L-K2,0)]
            def e_call(K):
                d = (mu_L - K) / (sig_L + 1e-10)
                return (mu_L - K)*N.cdf(d) + sig_L*N.pdf(d)
            e_loss += (e_call(K_lo*n) - e_call(K_hi*n)) * N.pdf(x) * dx
        return e_loss / ((K_hi - K_lo)*n)

    etl = expected_tranche_loss(K1, K2)
    price = notional * (K2-K1) * (1 - np.exp(-r*T) * (1 - etl))

    return dict(price=price, expected_tranche_loss=etl,
                attachment=K1, detachment=K2)


# ─────────────────────────────────────────────────────────
# Credit spread option
# ─────────────────────────────────────────────────────────

def credit_spread_option(S0: float, K: float, T: float, r: float,
                          sigma: float, opt: str = "call") -> dict:
    """
    European option on credit spread (log-normal spread model, Black-76 style).
    S0: current spread, K: strike spread.
    """
    from models.black_scholes import black76
    g = black76(S0, K, T, r, sigma, opt)
    return dict(price=g.price, delta=g.delta, vega=g.vega)


# ─────────────────────────────────────────────────────────
# CVA / DVA (unilateral, simplified)
# ─────────────────────────────────────────────────────────

def cva(exposure_profile: list, hazard_cpty: float,
        recovery_cpty: float, r: float) -> dict:
    """
    Unilateral CVA = (1-R) * integral EPE(t) * λ * exp(-(r+λ)t) dt
    exposure_profile: list of (t, EPE_t) tuples.
    """
    lgd = 1 - recovery_cpty
    total = 0.0
    for i in range(len(exposure_profile)-1):
        t0, epe0 = exposure_profile[i]
        t1, epe1 = exposure_profile[i+1]
        dt   = t1 - t0
        t_m  = 0.5*(t0+t1); epe_m = 0.5*(epe0+epe1)
        total += epe_m * hazard_cpty * np.exp(-(r+hazard_cpty)*t_m) * dt
    cva_val = lgd * total
    return dict(cva=cva_val, lgd=lgd)


def dva(exposure_profile: list, hazard_own: float,
        recovery_own: float, r: float) -> dict:
    """DVA — own credit value adjustment (symmetric to CVA on own default)."""
    return cva(exposure_profile, hazard_own, recovery_own, r)
