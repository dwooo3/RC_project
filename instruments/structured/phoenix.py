"""
Structured notes (Hull Ch. 12.1 + market practice):
  - Phoenix / Autocall
  - Reverse Convertible
  - Principal Protected Note (PPN)
  - Participation Certificate
  - Capital-at-Risk Note
  - Worst-of Barrier Reverse Convertible (WBRC)
  - First-to-Default (FTD) basket
  - Credit-Linked Note (CLN)
  - Phoenix with memory coupon
"""

import numpy as np
from models.monte_carlo import multi_asset_paths, gbm_paths


# ─────────────────────────────────────────────────────────
# Phoenix / Autocall
# ─────────────────────────────────────────────────────────

def phoenix(
    S0: float, r: float, q: float, sigma: float, T: float,
    obs_dates: list,          # list of observation times (years)
    autocall_barrier: float,  # e.g. 1.0 = 100% of S0
    coupon_barrier: float,    # e.g. 0.70 = 70% of S0
    ki_barrier: float,        # knock-in barrier e.g. 0.65 = 65%
    coupon_rate: float,       # e.g. 0.10 = 10% p.a.
    memory_coupon: bool = True,
    n_sims: int = 100_000, steps: int = 252, seed: int = 42,
) -> dict:
    """
    Phoenix (Autocall with memory coupon).

    At each observation date t_i:
      - If S(t_i) >= autocall_barrier*S0: autocall, pay 100% + accrued coupon
      - Else if S(t_i) >= coupon_barrier*S0: pay coupon (memory recovers missed)
      - Else: no coupon (memory accumulates if memory_coupon=True)
      - At maturity T:
        - If S(T) >= ki_barrier*S0: pay 100%
        - Else: pay S(T)/S0 * 100% (capital loss)

    Returns fair value of note (as % of face = 1.0).
    """
    paths = gbm_paths(S0, r, q, sigma, T, steps, n_sims, seed=seed)
    dt    = T / steps
    disc  = np.exp(-r * T)

    # observation step indices
    obs_steps = [min(int(round(t/dt)), steps) for t in obs_dates]
    obs_dates[0] if obs_dates else T  # first coupon period

    payoffs = np.zeros(n_sims)
    alive   = np.ones(n_sims, dtype=bool)
    memory_coupons = np.zeros(n_sims)

    for i, (step, t_obs) in enumerate(zip(obs_steps, obs_dates)):
        S_obs  = paths[:, step]
        cpn    = coupon_rate * (obs_dates[i] - (obs_dates[i-1] if i>0 else 0))

        # Memory coupon accumulation
        at_coupon_bar = alive & (S_obs >= coupon_barrier*S0)
        no_coupon     = alive & (S_obs < coupon_barrier*S0)

        if memory_coupon:
            memory_coupons[at_coupon_bar] += cpn  # catch up
            memory_coupons[no_coupon]     += cpn  # accumulate missed
        else:
            memory_coupons[at_coupon_bar] += cpn

        # Autocall check
        autocall = alive & (S_obs >= autocall_barrier*S0)
        if autocall.any():
            disc_t  = np.exp(-r * t_obs)
            # pay 100% + accrued memory coupon
            payoffs[autocall] = disc_t * (1.0 + memory_coupons[autocall])
            alive[autocall]   = False
            memory_coupons[autocall] = 0

    # At maturity — surviving paths
    S_T = paths[:, -1]
    # Capital: if above KI barrier at maturity → 100%, else S_T/S0
    capital = np.where(S_T >= ki_barrier*S0, 1.0, S_T/S0)
    # Coupon at maturity for surviving
    final_cpn = memory_coupons[alive] if memory_coupon else np.zeros(alive.sum())
    payoffs[alive] = disc * (capital[alive] + final_cpn)

    price  = payoffs.mean()
    stderr = payoffs.std() / np.sqrt(n_sims)

    autocall_prob = (~alive).mean()  # fraction that autocalled
    return dict(
        price=price, stderr=stderr,
        autocall_prob=autocall_prob,
        fair_spread_bps=(1-price)*10000,  # excess coupon needed for fair value
        n_sims=n_sims,
    )


# ─────────────────────────────────────────────────────────
# Reverse Convertible
# ─────────────────────────────────────────────────────────

def reverse_convertible(
    S0: float, r: float, q: float, sigma: float, T: float,
    ki_barrier: float,   # knock-in barrier (e.g. 0.70)
    coupon_rate: float,  # annual coupon e.g. 0.12
    n_sims: int = 100_000, seed: int = 42,
) -> dict:
    """
    Reverse convertible: investor receives coupon, risks downside.
    At maturity:
      - If barrier never touched: 100% + coupon
      - If barrier touched AND S_T < S0: pay S_T/S0 (physical delivery of stock)
      - If barrier touched AND S_T >= S0: pay 100% + coupon
    """
    paths = gbm_paths(S0, r, q, sigma, T, 252, n_sims, seed=seed)
    S_T   = paths[:, -1]
    S_min = paths.min(axis=1)
    disc  = np.exp(-r*T)
    cpn   = coupon_rate * T

    ki_hit  = S_min <= ki_barrier * S0
    payoff  = np.where(
        ki_hit & (S_T < S0),
        S_T/S0,        # downside participation
        1.0            # full principal
    ) + cpn

    pv    = disc * payoff
    return dict(
        price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims),
        ki_prob=ki_hit.mean(),
        capital_loss_prob=(ki_hit & (S_T < S0)).mean(),
        breakeven=ki_barrier,
    )


# ─────────────────────────────────────────────────────────
# Principal Protected Note (PPN)
# ─────────────────────────────────────────────────────────

def ppn(
    face: float, r: float, sigma: float, T: float,
    participation: float = 1.0,
    cap: float = None,      # maximum return cap
    floor_: float = 0.0,    # minimum return (usually 0)
    S0: float = 100.0, q: float = 0.0,
    n_sims: int = 100_000, seed: int = 42,
) -> dict:
    """
    Principal Protected Note:
      - Bond floor: PV of guaranteed principal = face * discount(T)
      - Option: call option on underlying (participation * call payoff)
      - Payoff = face + participation * max(S_T/S0 - 1, floor_), capped at cap

    Hull Ch. 12.1: PPN = ZCB + call option.
    """
    from models.black_scholes import bsm as _bsm
    disc     = np.exp(-r*T)
    zcb_cost = face * disc   # cost of bond floor

    # Remaining budget for options
    option_budget = face - zcb_cost

    # Call option cost (BSM)
    call_price = _bsm(S0, S0, T, r, sigma, q, "call").price
    # Number of calls we can buy per unit face
    n_calls = option_budget / call_price if call_price > 1e-8 else 0
    # effective participation = n_calls (normalized)
    part_actual = n_calls * participation

    # MC payoff
    paths  = gbm_paths(S0, r, q, sigma, T, 252, n_sims, seed=seed)
    S_T    = paths[:, -1]
    ret    = np.maximum(S_T/S0 - 1, floor_)
    if cap is not None:
        ret = np.minimum(ret, cap)
    payoff = face + face * part_actual * ret
    pv     = disc * payoff

    return dict(
        price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims),
        zcb_cost=zcb_cost,
        option_budget=option_budget,
        effective_participation=part_actual,
        call_price=call_price,
    )


# ─────────────────────────────────────────────────────────
# Worst-of Basket Reverse Convertible (WBRC)
# ─────────────────────────────────────────────────────────

def worst_of_barrier_rc(
    S0_list: list, r: float, q_list: list,
    sigma_list: list, corr_matrix: np.ndarray,
    T: float, ki_barrier: float, coupon_rate: float,
    n_sims: int = 50_000, seed: int = 42,
) -> dict:
    """
    Worst-of Barrier Reverse Convertible on a basket of assets.
    Barrier is monitored on the WORST performer continuously.
    At maturity: if barrier touched AND worst_S_T < S0 → pay worst S_T/S0
    """
    len(S0_list)
    S0  = np.array(S0_list, dtype=float)
    sig = np.array(sigma_list, dtype=float)
    q   = np.array(q_list, dtype=float)
    disc = np.exp(-r*T)
    cpn  = coupon_rate * T

    paths = multi_asset_paths(S0, r, q, sig, corr_matrix, T, 252, n_sims, seed)
    # paths: (n_sims, n_assets, steps+1)

    # worst performer path (relative to S0)
    rel_paths = paths / S0[np.newaxis, :, np.newaxis]  # normalised
    worst_path = rel_paths.min(axis=1)  # (n_sims, steps+1) worst-of at each step

    ki_hit   = worst_path.min(axis=1) <= ki_barrier  # touched during life
    worst_T  = worst_path[:, -1]                     # worst performer at maturity

    capital = np.where(ki_hit & (worst_T < 1.0), worst_T, 1.0)
    payoff  = capital + cpn
    pv      = disc * payoff

    return dict(
        price=pv.mean(), stderr=pv.std()/np.sqrt(n_sims),
        ki_prob=ki_hit.mean(),
        loss_prob=(ki_hit & (worst_T < 1.0)).mean(),
        avg_worst_T=worst_T.mean(),
    )
