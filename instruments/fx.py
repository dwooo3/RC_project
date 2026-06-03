"""
FX instruments:
  - FX Forward / FX Swap (points)
  - FX Option (Garman-Kohlhagen) with full Greeks
  - FX Barrier option
  - FX Digital option
  - FX Asian option
  - FX Knock-in/Knock-out with window barrier
  - Risk reversal / Strangle / Butterfly (vol surface conventions)
  - FX Variance swap
"""

import numpy as np
from models.black_scholes import garman_kohlhagen, Greeks
from instruments.barrier import single_barrier, barrier_mc
from instruments.digital import cash_or_nothing
from instruments.asian import arithmetic_asian


# ─────────────────────────────────────────────────────────
# FX Forward
# ─────────────────────────────────────────────────────────

def fx_forward(S: float, r_d: float, r_f: float, T: float,
               notional: float = 1_000_000,
               forward_agreed: float = None) -> dict:
    """
    FX Forward pricing.
    S: spot, r_d: domestic rate, r_f: foreign rate.
    forward_agreed: if given, NPV of the forward contract.
    """
    F = S * np.exp((r_d - r_f) * T)
    swap_points = F - S  # in pips (last decimal place)

    npv = None
    if forward_agreed is not None:
        npv = notional * np.exp(-r_d * T) * (F - forward_agreed)

    return dict(forward=F, swap_points=swap_points, spot=S,
                notional=notional, npv=npv, T=T)


def fx_swap(S: float, r_d: float, r_f: float,
            T_near: float, T_far: float, notional: float = 1_000_000) -> dict:
    """
    FX Swap: near leg + far leg at different maturities.
    """
    near = fx_forward(S, r_d, r_f, T_near, notional)
    far  = fx_forward(S, r_d, r_f, T_far,  notional)
    net_swap_points = far["forward"] - near["forward"]
    return dict(near_forward=near["forward"], far_forward=far["forward"],
                net_swap_points=net_swap_points, T_near=T_near, T_far=T_far)


# ─────────────────────────────────────────────────────────
# FX Option (Garman-Kohlhagen)
# ─────────────────────────────────────────────────────────

def fx_option(S: float, K: float, T: float, r_d: float, r_f: float,
              sigma: float, notional: float = 1_000_000,
              opt: str = "call",
              quote: str = "domestic_pips") -> dict:
    """
    FX option pricing.
    quote: domestic_pips | pct_foreign | pct_domestic | premium_adjusted_delta
    """
    g = garman_kohlhagen(S, K, T, r_d, r_f, sigma, opt)

    # Standard delta conventions
    delta_spot   = g.delta  # dPrice/dS
    delta_fwd    = g.delta * np.exp(r_f * T)  # forward delta
    delta_prem   = g.delta - g.price / S       # premium-included delta

    # Premium in different conventions
    prem_dom  = g.price * notional           # domestic currency
    prem_for  = g.price / S * notional       # foreign currency
    prem_pct_dom = g.price / S              # % of notional in domestic
    prem_pct_for = g.price / (K * np.exp(-r_d*T))  # % of notional in foreign

    return dict(
        price=g.price, premium_domestic=prem_dom, premium_foreign=prem_for,
        delta_spot=delta_spot, delta_fwd=delta_fwd, delta_premium_adj=delta_prem,
        gamma=g.gamma, vega=g.vega, theta=g.theta, rho_d=g.rho,
        vanna=g.vanna, volga=g.volga,
        prem_pct_domestic=prem_pct_dom, prem_pct_foreign=prem_pct_for,
        notional=notional, opt=opt
    )


# ─────────────────────────────────────────────────────────
# FX Volatility surface conventions
# ─────────────────────────────────────────────────────────

def fx_vol_from_rr_str(atm: float, rr: float, strangle: float,
                        delta: float = 0.25) -> dict:
    """
    Reconstruct call/put vols from ATM, risk-reversal and strangle quotes.
    RR = sigma_call(Δ) - sigma_put(Δ)
    STR = 0.5*(sigma_call(Δ) + sigma_put(Δ)) - ATM
    Returns vols for 25Δ call, 25Δ put, ATM.
    """
    sigma_call = atm + strangle + 0.5*rr
    sigma_put  = atm + strangle - 0.5*rr
    return dict(atm=atm, call_25d=sigma_call, put_25d=sigma_put,
                rr=rr, strangle=strangle, delta=delta)


def delta_to_strike(S: float, T: float, r_d: float, r_f: float,
                     sigma: float, delta: float, opt: str = "call") -> float:
    """Convert delta to strike (Garman-Kohlhagen inverse)."""
    from scipy.stats import norm
    from scipy.optimize import brentq
    disc_f = np.exp(-r_f * T)
    sign   = 1 if opt == "call" else -1

    def eq(K):
        d1 = (np.log(S/K) + (r_d-r_f+0.5*sigma**2)*T) / (sigma*np.sqrt(T))
        return sign * disc_f * norm.cdf(sign*d1) - delta

    return brentq(eq, S*0.01, S*5)


# ─────────────────────────────────────────────────────────
# FX Barrier options
# ─────────────────────────────────────────────────────────

def fx_barrier(S: float, K: float, H: float, T: float,
               r_d: float, r_f: float, sigma: float,
               opt: str = "call", barrier_type: str = "down-out",
               rebate: float = 0.0, notional: float = 1_000_000,
               method: str = "closed_form") -> dict:
    """FX barrier option."""
    if method == "closed_form":
        res = single_barrier(S, K, H, T, r_d, sigma, r_f, opt, barrier_type, rebate)
    else:
        res = barrier_mc(S, K, H, T, r_d, sigma, r_f, opt, barrier_type, rebate)
    res["premium_domestic"] = res["price"] * notional
    return res


# ─────────────────────────────────────────────────────────
# Risk reversal / Strangle / Straddle / Strangle combo
# ─────────────────────────────────────────────────────────

def risk_reversal(S: float, K_call: float, K_put: float, T: float,
                  r_d: float, r_f: float,
                  sigma_call: float, sigma_put: float,
                  notional: float = 1_000_000) -> dict:
    """Long call + short put (or reverse)."""
    call = fx_option(S, K_call, T, r_d, r_f, sigma_call, notional, "call")
    put  = fx_option(S, K_put,  T, r_d, r_f, sigma_put,  notional, "put")
    return dict(price=call["price"] - put["price"],
                delta=call["delta_spot"] - put["delta_spot"],
                vega=call["vega"] - put["vega"],
                call=call, put=put)


def strangle(S: float, K_call: float, K_put: float, T: float,
             r_d: float, r_f: float,
             sigma_call: float, sigma_put: float,
             notional: float = 1_000_000) -> dict:
    """Long call + long put (OTM strangle)."""
    call = fx_option(S, K_call, T, r_d, r_f, sigma_call, notional, "call")
    put  = fx_option(S, K_put,  T, r_d, r_f, sigma_put,  notional, "put")
    return dict(price=call["price"] + put["price"],
                delta=call["delta_spot"] + put["delta_spot"],
                vega=call["vega"] + put["vega"],
                call=call, put=put)


def straddle(S: float, K: float, T: float, r_d: float, r_f: float,
             sigma: float, notional: float = 1_000_000) -> dict:
    """ATM straddle: call + put at same strike."""
    return strangle(S, K, K, T, r_d, r_f, sigma, sigma, notional)
