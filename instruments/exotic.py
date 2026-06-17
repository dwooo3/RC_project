"""
Exotic single-asset options:
  - Chooser (simple & complex)
  - Compound (option on option)
  - Forward-start option
  - Shout option
  - Power option (symmetric & asymmetric)
  - Cliquet / Ratchet
  - Reset (strike-reset) option
  - Range accrual
  - Corridor variance option
"""

import numpy as np
from scipy.stats import norm, multivariate_normal
from models.black_scholes import bsm
from models.monte_carlo import gbm_paths


# ─────────────────────────────────────────────────────────
# Chooser option (Rubinstein 1991)
# ─────────────────────────────────────────────────────────

def simple_chooser(S: float, K: float, T_choose: float, T: float,
                   r: float, sigma: float, q: float = 0.0) -> dict:
    """
    Simple chooser: at T_choose, holder picks call or put, both expiring at T.
    Exact formula: chooser = call(S,K,T) + put(S, K*exp(-(r-q)*(T-T_choose)), T_choose).
    """
    from models.black_scholes import bsm
    call_T  = bsm(S, K, T, r, sigma, q, "call").price
    K_adj   = K * np.exp(-(r - q)*(T - T_choose))
    put_Tc  = bsm(S, K_adj, T_choose, r, sigma, q, "put").price
    price   = call_T + put_Tc
    return dict(price=price, T_choose=T_choose, T_expiry=T)


def complex_chooser(S: float, Kc: float, Kp: float,
                    T_choose: float, Tc: float, Tp: float,
                    r: float, sigma: float, q: float = 0.0) -> dict:
    """
    Complex chooser with different strikes and maturities for call/put.
    Rubinstein (1991) bivariate normal formula.
    """
    b  = r - q
    sv_c = sigma*np.sqrt(Tc); sv_p = sigma*np.sqrt(Tp)
    sv_t = sigma*np.sqrt(T_choose)
    (np.log(S/S) + (b + sigma**2/2)*T_choose) / sv_t  # approximate

    # Solve critical S* numerically
    from scipy.optimize import brentq
    def eq(Ss):
        return (bsm(Ss, Kc, Tc-T_choose, r, sigma, q, "call").price
               -bsm(Ss, Kp, Tp-T_choose, r, sigma, q, "put").price)
    try:
        Ss = brentq(eq, S*0.01, S*10)
    except ValueError:
        Ss = S

    rho_c = np.sqrt(T_choose/Tc); rho_p = np.sqrt(T_choose/Tp)
    I1 = (np.log(S/Ss) + (b + sigma**2/2)*T_choose) / sv_t
    I2 = (np.log(S/Kc) + (b + sigma**2/2)*Tc)       / sv_c
    I3 = (np.log(S/Kp) + (b + sigma**2/2)*Tp)       / sv_p

    def M(a, b, rho):
        return multivariate_normal.cdf([a, b], mean=[0,0], cov=[[1,rho],[rho,1]])

    price = (S*np.exp(-q*Tc)*(M(I1, I2-sigma**2*T_choose/sv_t, rho_c))
            -Kc*np.exp(-r*Tc)*M(I1-sv_t, I2-sv_c, rho_c)
            -S*np.exp(-q*Tp)*M(-I1, -(I3-sigma**2*T_choose/sv_t), -rho_p)
            +Kp*np.exp(-r*Tp)*M(-I1+sv_t, -(I3-sv_p), -rho_p))
    return dict(price=price, Kc=Kc, Kp=Kp, T_choose=T_choose)


# ─────────────────────────────────────────────────────────
# Compound option (Geske 1979)
# ─────────────────────────────────────────────────────────

def compound_option(S: float, K_outer: float, K_inner: float,
                    T1: float, T2: float, r: float, sigma: float,
                    q: float = 0.0,
                    outer: str = "call", inner: str = "call") -> dict:
    """
    Compound option (option on option).
    outer/inner: "call" or "put"
    T1 < T2: T1 = outer expiry, T2 = inner expiry.
    """
    from scipy.optimize import brentq
    b  = r - q
    sv1 = sigma*np.sqrt(T1); sv2 = sigma*np.sqrt(T2)
    rho = np.sqrt(T1/T2)

    # Critical stock price S* at T1
    def eq(Ss):
        p = bsm(Ss, K_inner, T2-T1, r, sigma, q, inner).price
        return p - K_outer
    try:
        Ss = brentq(eq, S*0.001, S*10, maxiter=200)
    except ValueError:
        Ss = S


    d1 = (np.log(S/Ss)     + (b + sigma**2/2)*T1) / sv1
    d2 = (np.log(S/K_inner) + (b + sigma**2/2)*T2) / sv2

    def M(a, b_, rho_): return multivariate_normal.cdf([a, b_], cov=[[1,rho_],[rho_,1]])

    if outer == "call" and inner == "call":
        price = (S*np.exp(-q*T2)*M(d1, d2-sv2, rho)
                -K_inner*np.exp(-r*T2)*M(d1-sv1, d2-sv2, rho)
                -K_outer*np.exp(-r*T1)*norm.cdf(d1-sv1))
    elif outer == "put" and inner == "call":
        price = (-S*np.exp(-q*T2)*M(-d1, d2-sv2, -rho)
                +K_inner*np.exp(-r*T2)*M(-d1+sv1, d2-sv2, -rho)
                +K_outer*np.exp(-r*T1)*norm.cdf(-d1+sv1))
    elif outer == "call" and inner == "put":
        price = (-S*np.exp(-q*T2)*M(-d1, -(d2-sv2), rho)
                +K_inner*np.exp(-r*T2)*M(-d1+sv1, -(d2-sv2), rho)
                +K_outer*np.exp(-r*T1)*norm.cdf(d1-sv1))
    else:  # put on put
        price = (S*np.exp(-q*T2)*M(d1, -(d2-sv2), -rho)
                -K_inner*np.exp(-r*T2)*M(d1-sv1, -(d2-sv2), -rho)
                -K_outer*np.exp(-r*T1)*norm.cdf(-d1+sv1))

    return dict(price=max(price, 0), outer=outer, inner=inner, Ss=Ss)


# ─────────────────────────────────────────────────────────
# Forward-start option
# ─────────────────────────────────────────────────────────

def forward_start(S: float, alpha: float, T_start: float, T: float,
                  r: float, sigma: float, q: float = 0.0,
                  opt: str = "call") -> dict:
    """
    Forward-start option: at T_start, strike is set to K = alpha*S(T_start).
    alpha: moneyness at start (1.0 = ATM).
    """
    b  = r - q
    tau = T - T_start
    disc_s = np.exp(-q * T_start)
    d1 = (np.log(1/alpha) + (b + sigma**2/2)*tau) / (sigma*np.sqrt(tau))
    d2 = d1 - sigma*np.sqrt(tau)
    sign = 1 if opt == "call" else -1

    price = S * disc_s * (sign*(np.exp(-q*tau)*norm.cdf(sign*d1)
                               -alpha*np.exp(-r*tau)*norm.cdf(sign*d2)))
    delta = disc_s * (sign*(np.exp(-q*tau)*norm.cdf(sign*d1)
                            -alpha*np.exp(-r*tau)*norm.cdf(sign*d2)))
    return dict(price=price, delta=delta, alpha=alpha, T_start=T_start)


# ─────────────────────────────────────────────────────────
# Shout option
# ─────────────────────────────────────────────────────────

def shout_option_mc(S: float, K: float, T: float, r: float, sigma: float,
                    q: float = 0.0, opt: str = "call",
                    n_sims: int = 50_000, steps: int = 252, seed: int = 42) -> dict:
    """
    Shout option: holder can 'shout' once, locking in intrinsic value.
    Simplified: optimal shout when intrinsic exceeds continuation value (LSM approach).
    """
    paths = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)
    dt    = T / steps
    np.exp(-r*dt)

    # payoff if we shout at step i: guaranteed max(S_i-K,0) + call on residual
    # simplified: shout when in-the-money, compare to BSM continuation
    if opt == "call":
        iv_fn = lambda x: np.maximum(x - K, 0)
    else:
        iv_fn = lambda x: np.maximum(K - x, 0)

    shout_pv = np.zeros(n_sims)
    shouted  = np.zeros(n_sims, dtype=bool)

    for i in range(1, steps+1):
        tau_i = (steps - i) * dt
        S_i   = paths[:, i]
        iv    = iv_fn(S_i)
        # continuation: BSM on remaining life
        if tau_i > 0:
            from models.black_scholes import bsm as _bsm
            cont_arr = np.array([_bsm(s, K, tau_i, r, sigma, q, opt).price for s in S_i])
        else:
            cont_arr = np.zeros(n_sims)

        should_shout = (~shouted) & (iv > cont_arr) & (iv > 0)
        np.maximum(iv_fn(paths[:, -1]), iv)  # guarantee the shout floor
        shout_pv = np.where(should_shout & ~shouted,
                            np.exp(-r*(i*dt))*iv + np.exp(-r*T)*np.maximum(iv_fn(paths[:,-1]) - iv, 0),
                            shout_pv)
        shouted  = shouted | should_shout

    # for those who never shouted
    shout_pv = np.where(~shouted, np.exp(-r*T)*iv_fn(paths[:,-1]), shout_pv)
    price    = shout_pv.mean()
    stderr   = shout_pv.std() / np.sqrt(n_sims)
    return dict(price=price, stderr=stderr, n_sims=n_sims)


# ─────────────────────────────────────────────────────────
# Power options
# ─────────────────────────────────────────────────────────

def power_option(S: float, K: float, T: float, r: float, sigma: float,
                 q: float = 0.0, power: float = 2.0, opt: str = "call") -> dict:
    """
    Symmetric power option: payoff = max(S_T^n - K, 0).
    Uses adjusted BSM with S → S^n equivalent.
    """
    b  = r - q
    sigma_n = power * sigma
    b_n     = power*(b + (power-1)*sigma**2/2)
    S_n     = S**power
    disc    = np.exp(-r*T)
    sv      = sigma_n * np.sqrt(T)

    d1 = (np.log(S_n/K) + (b_n + sigma_n**2/2)*T) / sv
    d2 = d1 - sv
    sign = 1 if opt == "call" else -1

    price = sign*(S_n*np.exp((b_n - r)*T)*norm.cdf(sign*d1) - K*disc*norm.cdf(sign*d2))
    return dict(price=max(price, 0), power=power, S_power=S_n)


def asym_power_option(S: float, K: float, T: float, r: float, sigma: float,
                      q: float = 0.0, power: float = 2.0, opt: str = "call") -> dict:
    """
    Asymmetric power option: payoff = S_T^n * max(S_T - K, 0).
    """
    from models.monte_carlo import mc_price
    if opt == "call":
        pf = lambda paths: paths[:, -1]**power * np.maximum(paths[:, -1] - K, 0)
    else:
        pf = lambda paths: paths[:, -1]**power * np.maximum(K - paths[:, -1], 0)
    return mc_price(pf, S, r, q, sigma, T)


# ─────────────────────────────────────────────────────────
# Cliquet / Ratchet option
# ─────────────────────────────────────────────────────────

def cliquet(S: float, T: float, r: float, sigma: float, q: float = 0.0,
            reset_dates: list = None, cap: float = None, floor: float = 0.0,
            global_cap: float = None, n_sims: int = 100_000, seed: int = 42) -> dict:
    """
    Cliquet (ratchet) option: sum of forward-start ATM options over sub-periods.
    Each sub-period: payoff = max(R_i - floor, 0), capped at cap.
    R_i = S(t_i)/S(t_{i-1}) - 1 (period return).
    """
    if reset_dates is None:
        n = 4
        reset_dates = [T*i/n for i in range(1, n+1)]

    all_dates = [0.0] + sorted(reset_dates)
    steps     = 252
    dt        = T / steps
    paths     = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)

    total_payoff = np.zeros(n_sims)
    for i in range(1, len(all_dates)):
        t0 = all_dates[i-1]; t1 = all_dates[i]
        idx0 = int(round(t0/dt)); idx1 = int(round(t1/dt))
        S0_i = paths[:, idx0]; S1_i = paths[:, idx1]
        R_i  = S1_i / S0_i - 1.0
        pf_i = np.maximum(R_i - floor, 0.0)
        if cap is not None:
            pf_i = np.minimum(pf_i, cap)
        total_payoff += pf_i

    if global_cap is not None:
        total_payoff = np.minimum(total_payoff, global_cap)

    pv     = np.exp(-r*T) * total_payoff
    price  = pv.mean()
    stderr = pv.std() / np.sqrt(n_sims)
    return dict(price=price, stderr=stderr, n_periods=len(reset_dates), n_sims=n_sims)


# ─────────────────────────────────────────────────────────
# Reset (strike-reset) option
# ─────────────────────────────────────────────────────────

def reset_option(S: float, K: float, T: float, r: float, sigma: float,
                 q: float = 0.0, T_reset: float = None, opt: str = "call",
                 n_sims: int = 100_000, seed: int = 42) -> dict:
    """
    Reset option: at T_reset, if OTM, strike resets to current spot.
    """
    if T_reset is None:
        T_reset = T / 2
    steps   = 252
    dt      = T / steps
    paths   = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)
    idx_r   = int(round(T_reset / dt))
    S_reset = paths[:, idx_r]
    S_T     = paths[:, -1]

    if opt == "call":
        K_eff   = np.where(S_reset < K, S_reset, K)  # reset if OTM (S_reset < K for call)
        payoff  = np.maximum(S_T - K_eff, 0)
    else:
        K_eff   = np.where(S_reset > K, S_reset, K)
        payoff  = np.maximum(K_eff - S_T, 0)

    pv     = np.exp(-r*T) * payoff
    price  = pv.mean()
    stderr = pv.std() / np.sqrt(n_sims)
    return dict(price=price, stderr=stderr, T_reset=T_reset, n_sims=n_sims)


# ─────────────────────────────────────────────────────────
# Range accrual note (equity-linked)
# ─────────────────────────────────────────────────────────

def range_accrual(S: float, L: float, U: float, T: float, r: float, sigma: float,
                  q: float = 0.0, coupon: float = 0.05,
                  n_sims: int = 100_000, steps: int = 252, seed: int = 42) -> dict:
    """
    Range accrual: pays coupon * (fraction of days S is in [L, U]).
    """
    paths    = gbm_paths(S, r, q, sigma, T, steps, n_sims, seed=seed)
    in_range = ((paths >= L) & (paths <= U)).mean(axis=1)  # fraction of time in range
    pv       = np.exp(-r*T) * coupon * in_range
    price    = pv.mean()
    stderr   = pv.std() / np.sqrt(n_sims)
    return dict(price=price, stderr=stderr, coupon=coupon, L=L, U=U, n_sims=n_sims)
