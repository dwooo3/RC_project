"""
Stress testing and scenario analysis:
  - Historical scenarios (2008, COVID, etc.)
  - Hypothetical factor shocks
  - Reverse stress testing
  - Sensitivity analysis (Greeks ladder, rate ladder)
  - PnL attribution (delta/gamma/vega explain)
"""

import numpy as np
from models.black_scholes import bsm
from models.black_scholes import Greeks


# ─────────────────────────────────────────────────────────
# Historical stress scenarios
# ─────────────────────────────────────────────────────────

HISTORICAL_SCENARIOS = {
    "Black Monday (1987-10-19)":    {"spot":-0.2245, "vol":+0.60, "rate":+0.002},
    "Gulf War (1990-08)":           {"spot":-0.1500, "vol":+0.30, "rate":-0.003},
    "LTCM / Russia (1998-08)":      {"spot":-0.2000, "vol":+0.50, "rate":-0.010},
    "Dot-com peak (2000-03)":       {"spot":-0.4900, "vol":+0.35, "rate":-0.025},
    "9/11 (2001-09-11)":            {"spot":-0.0700, "vol":+0.30, "rate":-0.005},
    "Lehman (2008-09-15)":          {"spot":-0.3500, "vol":+0.80, "rate":-0.020},
    "EUR Sovereign (2010-2012)":    {"spot":-0.2200, "vol":+0.40, "rate":+0.030},
    "Taper Tantrum (2013-05)":      {"spot":-0.0600, "vol":+0.25, "rate":+0.010},
    "China Deval (2015-08)":        {"spot":-0.1100, "vol":+0.35, "rate":-0.005},
    "COVID crash (2020-03)":        {"spot":-0.3500, "vol":+0.80, "rate":-0.015},
    "Meme squeeze (2021-01)":       {"spot":+0.5000, "vol":+0.60, "rate": 0.000},
    "Rate hike shock (2022)":       {"spot":-0.1800, "vol":+0.30, "rate":+0.040},
    "Bull run (generic)":           {"spot":+0.3000, "vol":-0.25, "rate":+0.005},
    "Flash crash (generic)":        {"spot":-0.1000, "vol":+0.70, "rate": 0.000},
}


def stress_option(S: float, K: float, T: float, r: float, sigma: float,
                  q: float = 0.0, opt: str = "call",
                  scenarios: dict = None, position: float = 1.0) -> list:
    """
    Apply stress scenarios to an option position.
    position: number of contracts (positive = long, negative = short).
    Returns list of scenario results.
    """
    scenarios = scenarios or HISTORICAL_SCENARIOS
    base = bsm(S, K, T, r, sigma, q, opt)
    results = []
    for name, shocks in scenarios.items():
        S_str = S * (1 + shocks.get("spot", 0))
        sig_s = max(sigma * (1 + shocks.get("vol",  0)), 0.01)
        r_str = max(r + shocks.get("rate", 0), -0.05)
        T_str = max(T - shocks.get("time", 0), 1/365)
        stressed = bsm(S_str, K, T_str, r_str, sig_s, q, opt)
        pnl = (stressed.price - base.price) * position
        results.append(dict(
            scenario=name,
            spot_shock=f"{shocks.get('spot',0):+.1%}",
            vol_shock= f"{shocks.get('vol', 0):+.1%}",
            rate_shock=f"{shocks.get('rate',0):+.3f}",
            base_price=round(base.price, 4),
            stressed_price=round(stressed.price, 4),
            pnl=round(pnl, 4),
            pnl_pct=f"{pnl/(base.price*abs(position)):+.1%}" if base.price else "N/A",
        ))
    return results


def stress_bond(duration: float, convexity: float, price: float,
                dv01: float, rate_shocks: list = None) -> list:
    """Stress test a bond position with interest rate shocks."""
    rate_shocks = rate_shocks or [-0.02, -0.01, -0.005, 0, 0.005, 0.01, 0.02, 0.03]
    results = []
    for dr in rate_shocks:
        dp_pct = -duration*dr + 0.5*convexity*dr**2
        dp_abs = price * dp_pct
        results.append(dict(rate_shock=f"{dr:+.2%}", dp_pct=f"{dp_pct:+.2%}",
                            dp_abs=round(dp_abs,4), new_price=round(price+dp_abs,4)))
    return results


# ─────────────────────────────────────────────────────────
# Sensitivity / Greeks ladder
# ─────────────────────────────────────────────────────────

def greeks_ladder(S: float, K: float, T: float, r: float, sigma: float,
                  q: float = 0.0, opt: str = "call",
                  spot_range: float = 0.30, steps: int = 21) -> list:
    """Greeks across a range of spot prices."""
    spots = np.linspace(S*(1-spot_range), S*(1+spot_range), steps)
    results = []
    for s in spots:
        g = bsm(s, K, T, r, sigma, q, opt)
        results.append(dict(spot=round(s,4), price=round(g.price,4),
                            delta=round(g.delta,4), gamma=round(g.gamma,6),
                            vega=round(g.vega,4), theta=round(g.theta,4)))
    return results


def vol_ladder(S: float, K: float, T: float, r: float, sigma: float,
               q: float = 0.0, opt: str = "call",
               vol_range: float = 0.20, steps: int = 11) -> list:
    """Price and Greeks across vol range."""
    vols = np.linspace(max(sigma-vol_range,0.01), sigma+vol_range, steps)
    results = []
    for v in vols:
        g = bsm(S, K, T, r, v, q, opt)
        results.append(dict(vol=f"{v:.1%}", price=round(g.price,4),
                            delta=round(g.delta,4), vega=round(g.vega,4)))
    return results


def rate_ladder(S: float, K: float, T: float, r: float, sigma: float,
                q: float = 0.0, opt: str = "call") -> list:
    """Price across rate range."""
    rates = np.arange(-0.02, 0.12, 0.01)
    results = []
    for ri in rates:
        g = bsm(S, K, T, ri, sigma, q, opt)
        results.append(dict(rate=f"{ri:.2%}", price=round(g.price,4), rho=round(g.rho,4)))
    return results


def time_decay_ladder(S: float, K: float, T: float, r: float, sigma: float,
                      q: float = 0.0, opt: str = "call") -> list:
    """Time value decay from T to 0."""
    days = list(range(int(T*365), -1, -max(1, int(T*365)//20)))
    results = []
    for d in days:
        t = max(d/365, 0)
        g = bsm(S, K, t, r, sigma, q, opt)
        results.append(dict(days_to_expiry=d, price=round(g.price,4),
                            theta=round(g.theta,4), delta=round(g.delta,4)))
    return results


# ─────────────────────────────────────────────────────────
# PnL Attribution (Greeks-based explain)
# ─────────────────────────────────────────────────────────

def pnl_explain(g: Greeks, dS: float, dSigma: float, dt: float, dr: float) -> dict:
    """
    Decompose PnL into delta/gamma/vega/theta/rho components.
    dS: spot move, dSigma: vol move (absolute), dt: time elapsed (days), dr: rate move.
    """
    delta_pnl = g.delta * dS
    gamma_pnl = 0.5 * g.gamma * dS**2
    vega_pnl  = g.vega * dSigma * 100
    theta_pnl = g.theta * dt
    rho_pnl   = g.rho * dr * 100
    vanna_pnl = g.vanna * dS * dSigma
    volga_pnl = 0.5 * g.volga * dSigma**2

    total = delta_pnl + gamma_pnl + vega_pnl + theta_pnl + rho_pnl
    total_2nd = total + vanna_pnl + volga_pnl

    return dict(
        delta=round(delta_pnl, 6),
        gamma=round(gamma_pnl, 6),
        vega=round(vega_pnl, 6),
        theta=round(theta_pnl, 6),
        rho=round(rho_pnl, 6),
        vanna=round(vanna_pnl, 6),
        volga=round(volga_pnl, 6),
        total_1st_order=round(delta_pnl + theta_pnl, 6),
        total_2nd_order=round(total, 6),
        total_with_cross=round(total_2nd, 6),
    )


# ─────────────────────────────────────────────────────────
# Reverse stress testing
# ─────────────────────────────────────────────────────────

def reverse_stress(S: float, K: float, T: float, r: float, sigma: float,
                   q: float = 0.0, opt: str = "call",
                   target_loss: float = None, target_loss_pct: float = None) -> dict:
    """
    Find the smallest joint spot/vol shock that causes the target loss.
    Uses optimization to find minimum-distance stress point.
    """
    from scipy.optimize import minimize
    base_price = bsm(S, K, T, r, sigma, q, opt).price

    if target_loss is None and target_loss_pct is not None:
        target_loss = base_price * target_loss_pct
    elif target_loss is None:
        target_loss = base_price * 0.5

    def objective(x):
        ds, dv = x
        return ds**2 + dv**2  # minimize shock magnitude

    def constraint(x):
        ds, dv = x
        S_s = S*(1+ds); sig_s = max(sigma*(1+dv), 0.001)
        p   = bsm(S_s, K, T, r, sig_s, q, opt).price
        return (base_price - p) - target_loss

    res = minimize(objective, [-0.1, 0.2],
                   constraints=[{"type":"eq","fun":constraint}],
                   bounds=[(-0.99,5),(-0.99,5)])
    ds, dv = res.x
    S_s = S*(1+ds); sig_s = max(sigma*(1+dv), 0.001)
    p   = bsm(S_s, K, T, r, sig_s, q, opt).price

    return dict(spot_shock=ds, vol_shock=dv,
                stressed_spot=S_s, stressed_vol=sig_s,
                base_price=base_price, stressed_price=p,
                actual_loss=base_price-p, target_loss=target_loss)
