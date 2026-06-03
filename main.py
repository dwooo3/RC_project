"""
Market Risk & Pricing Engine — CLI
Usage: python main.py <command> [options]

Commands:
  Vanilla options:
    option          European/American/Bermudan option (all models)
  Exotic options:
    barrier         Single/double barrier option
    asian           Asian (arithmetic/geometric) option
    digital         Digital: cash-or-nothing, asset-or-nothing, one-touch, no-touch
    lookback        Fixed/floating strike lookback
    chooser         Chooser option
    compound        Compound option (option on option)
    forward_start   Forward-start option
    cliquet         Cliquet / ratchet option
    variance_swap   Variance swap fair strike and P&L
  Multi-asset:
    basket          Basket option
    spread          Spread option (Kirk/MC)
    rainbow         Best-of / worst-of option
    exchange        Exchange option (Margrabe)
    quanto          Quanto option
  Fixed income:
    bond            Fixed-rate bond (price, YTM, duration, convexity, DV01)
    irs             Interest rate swap
    cap_floor       Cap / Floor / Collar
    swaption        European swaption
    cds             Credit default swap
  FX:
    fx_forward      FX forward / swap points
    fx_option       FX option (Garman-Kohlhagen)
    fx_barrier      FX barrier option
  Risk:
    var             VaR (Historical / Parametric / MC / EVT) with backtesting
    stress          Stress test option with 14 historical scenarios
    greeks_ladder   Greeks across spot range
    pnl_explain     PnL attribution (delta/gamma/vega/theta decomposition)
    implied_vol     Implied volatility from market price
    heston          Heston model pricing
    sabr            SABR model pricing
"""

import argparse
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))


# ─────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────

def hdr(title: str, width: int = 65):
    print(f"\n{'─'*width}")
    print(f"  {title}")
    print(f"{'─'*width}")


def row(label: str, value, width: int = 32):
    print(f"  {label:<{width}} {value}")


def table(headers: list, rows: list, col_widths: list = None):
    if not rows:
        return
    if col_widths is None:
        col_widths = [max(len(str(r[i])) for r in rows + [headers]) + 2
                      for i in range(len(headers))]
    fmt = "  " + "".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("  " + "─" * sum(col_widths))
    for r in rows:
        print(fmt.format(*[str(x) for x in r]))


# ─────────────────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────────────────

def cmd_option(args):
    from instruments.vanilla import european, american, bermudan
    kw = dict(S=args.spot, K=args.strike, T=args.expiry,
              r=args.rate, sigma=args.vol, q=args.div, opt=args.type)

    hdr(f"{args.exercise.upper()} {args.type.upper()}  "
        f"S={args.spot}  K={args.strike}  T={args.expiry}y  σ={args.vol:.0%}  model={args.model}")

    if args.exercise == "european":
        res = european(**kw, model=args.model)
    elif args.exercise == "american":
        res = american(**kw, model=args.model)
    else:
        dates = [args.expiry*i/4 for i in range(1,5)]
        res   = bermudan(**kw, exercise_dates=dates, model=args.model)

    for k, v in res.items():
        if isinstance(v, float):
            row(f"{k}:", f"{v:.6f}")
        elif v is not None and not isinstance(v, (dict, list)):
            row(f"{k}:", v)
    print()


def cmd_barrier(args):
    from instruments.barrier import single_barrier, double_barrier_ko, barrier_mc
    hdr(f"BARRIER {args.type.upper()}  {args.barrier_type}  S={args.spot}  K={args.strike}  H={args.barrier}")

    if args.double:
        res = double_barrier_ko(args.spot, args.strike, args.lower, args.upper,
                                args.expiry, args.rate, args.vol, args.div, args.type)
        row("Price:", f"{res['price']:.6f}")
        row("Lower barrier:", res["lower"])
        row("Upper barrier:", res["upper"])
    else:
        if args.mc:
            res = barrier_mc(args.spot, args.strike, args.barrier, args.expiry,
                             args.rate, args.vol, args.div, args.type, args.barrier_type)
            row("Price (MC):", f"{res['price']:.6f}")
            row("Std error:",  f"{res['stderr']:.6f}")
        else:
            res = single_barrier(args.spot, args.strike, args.barrier, args.expiry,
                                 args.rate, args.vol, args.div, args.type, args.barrier_type, args.rebate)
            row("Price:", f"{res['price']:.6f}")
            row("Vanilla:", f"{res['vanilla']:.6f}")
            row("Barrier:", res["barrier"])
            row("Type:", res["barrier_type"])
    print()


def cmd_asian(args):
    from instruments.asian import arithmetic_asian, geometric_asian_continuous, geometric_asian_discrete
    hdr(f"ASIAN {args.type.upper()}  {args.averaging}  S={args.spot}  K={args.strike}  n={args.fixings}")

    if args.geometric:
        if args.continuous:
            res = geometric_asian_continuous(args.spot, args.strike, args.expiry,
                                            args.rate, args.vol, args.div, args.type)
        else:
            res = geometric_asian_discrete(args.spot, args.strike, args.expiry,
                                          args.rate, args.vol, args.div, args.fixings, args.type)
    else:
        res = arithmetic_asian(args.spot, args.strike, args.expiry, args.rate,
                               args.vol, args.div, args.fixings, args.type,
                               n_sims=args.sims, averaging=args.averaging)

    for k, v in res.items():
        if isinstance(v, float):
            row(f"{k}:", f"{v:.6f}")
        elif not isinstance(v, (dict, list)):
            row(f"{k}:", v)
    print()


def cmd_digital(args):
    from instruments.digital import (cash_or_nothing, asset_or_nothing,
                                     one_touch, no_touch, double_no_touch, supershare)
    hdr(f"DIGITAL {args.digital_type.upper()}  S={args.spot}  K={args.strike}")

    if args.digital_type == "cash_or_nothing":
        res = cash_or_nothing(args.spot, args.strike, args.expiry, args.rate, args.vol,
                              args.div, args.type, args.cash)
    elif args.digital_type == "asset_or_nothing":
        res = asset_or_nothing(args.spot, args.strike, args.expiry, args.rate, args.vol,
                               args.div, args.type)
    elif args.digital_type == "one_touch":
        res = one_touch(args.spot, args.barrier, args.expiry, args.rate, args.vol,
                        args.div, args.direction, args.payment, args.cash)
    elif args.digital_type == "no_touch":
        res = no_touch(args.spot, args.barrier, args.expiry, args.rate, args.vol,
                       args.div, args.direction, args.cash)
    elif args.digital_type == "double_no_touch":
        res = double_no_touch(args.spot, args.lower, args.upper, args.expiry,
                              args.rate, args.vol, args.div, args.cash)
    elif args.digital_type == "supershare":
        res = supershare(args.spot, args.lower, args.upper, args.expiry,
                         args.rate, args.vol, args.div)
    else:
        print(f"Unknown digital type: {args.digital_type}"); return

    for k, v in res.items():
        if isinstance(v, float):
            row(f"{k}:", f"{v:.6f}")
        else:
            row(f"{k}:", v)
    print()


def cmd_lookback(args):
    from instruments.lookback import floating_lookback, fixed_lookback, lookback_mc
    hdr(f"LOOKBACK  {args.lb_style}  {args.type.upper()}  S={args.spot}")

    if args.mc:
        res = lookback_mc(args.spot, args.strike, args.expiry, args.rate, args.vol,
                          args.div, args.type, args.lb_style)
        row("Price (MC):", f"{res['price']:.6f}")
        row("Std error:",  f"{res['stderr']:.6f}")
    elif args.lb_style == "floating":
        res = floating_lookback(args.spot, args.expiry, args.rate, args.vol, args.div, args.type)
        for k, v in res.items():
            row(f"{k}:", f"{v:.6f}" if isinstance(v, float) else v)
    else:
        res = fixed_lookback(args.spot, args.strike, args.expiry, args.rate, args.vol, args.div, args.type)
        for k, v in res.items():
            row(f"{k}:", f"{v:.6f}" if isinstance(v, float) else v)
    print()


def cmd_variance_swap(args):
    from instruments.variance_swaps import (variance_swap_pnl, vol_swap_mc,
                                             corridor_variance_swap)
    hdr(f"VARIANCE SWAP  S={args.spot}  σ={args.vol:.0%}  T={args.expiry}y")
    fair = args.vol**2
    row("Fair variance strike:", f"{fair:.6f}  ({args.vol:.2%} vol equivalent)")

    vs_pnl = variance_swap_pnl(fair*1.05, fair, args.notional)
    row("P&L (if realized var = fair+5%):", f"{vs_pnl['pnl']:.2f}")

    vol_res = vol_swap_mc(args.spot, args.rate, args.div, args.vol, args.expiry, n_sims=50_000)
    row("Vol swap strike (MC):", f"{vol_res['vol_strike']:.4f}  ({vol_res['vol_strike']:.2%})")
    row("Std realized vol:", f"{vol_res['std_realized_vol']:.4f}")

    if args.lower and args.upper:
        corr = corridor_variance_swap(args.spot, args.rate, args.div, args.vol, args.expiry,
                                      args.lower, args.upper)
        row(f"Corridor [{args.lower},{args.upper}] var strike:", f"{corr['corridor_var_strike']:.6f}")
        row("% time in corridor:", f"{corr['pct_time_in']:.1%}")
    print()


def cmd_bond(args):
    from instruments.fixed_income import fixed_bond
    from services.market_data_service import MarketDataService
    curve = MarketDataService().flat_curve(args.rate)
    hdr(f"BOND  Face={args.face}  Coupon={args.coupon:.2%}  T={args.expiry}y  Freq={args.freq}/yr")
    res = fixed_bond(args.face, args.coupon, args.expiry, args.freq, curve)
    row("Price:",         f"{res['price']:.4f}")
    row("YTM:",           f"{res['ytm']:.4f}  ({res['ytm']:.2%})")
    row("Z-spread:",      f"{res['zspread']:.4f}" if not np.isnan(res.get('zspread',np.nan)) else "N/A")
    row("Mac. Duration:", f"{res['mac_duration']:.4f} years")
    row("Mod. Duration:", f"{res['mod_duration']:.4f} years")
    row("Convexity:",     f"{res['convexity']:.4f}")
    row("DV01:",          f"{res['dv01']:.4f}  (per 1bp rate move)")

    # rate sensitivity table
    print("\n  Rate sensitivity:")
    from risk.stress import stress_bond
    rows = stress_bond(res["mod_duration"], res["convexity"], res["price"], res["dv01"])
    table(["Rate shock", "ΔPrice%", "ΔPrice abs", "New price"],
          [[r["rate_shock"], r["dp_pct"], r["dp_abs"], r["new_price"]] for r in rows])
    print()


def cmd_irs(args):
    from instruments.fixed_income import irs
    from services.market_data_service import MarketDataService
    curve = MarketDataService().flat_curve(args.rate)
    hdr(f"IRS  Notional={args.notional:,.0f}  Fixed={args.fixed_rate:.2%}  T={args.expiry}y  Freq={args.freq}/yr")
    res = irs(args.notional, args.fixed_rate, args.expiry, args.freq, curve, args.pay_fixed)
    row("NPV:",        f"{res['npv']:,.2f}")
    row("Fair rate:",  f"{res['fair_rate']:.4f}  ({res['fair_rate']:.2%})")
    row("Fixed leg PV:", f"{res['fixed_pv']:,.2f}")
    row("Float leg PV:", f"{res['float_pv']:,.2f}")
    row("DV01:",       f"{res['dv01']:,.2f}")
    print()


def cmd_cap_floor(args):
    from instruments.fixed_income import cap_floor, collar
    from services.market_data_service import MarketDataService
    curve = MarketDataService().flat_curve(args.rate)
    hdr(f"CAP/FLOOR  Notional={args.notional:,.0f}  K={args.strike:.2%}  T={args.expiry}y  σ={args.vol:.0%}")
    cap   = cap_floor(args.notional, args.strike, args.expiry, args.freq, curve, args.vol, "cap")
    floor = cap_floor(args.notional, args.strike, args.expiry, args.freq, curve, args.vol, "floor")
    row("Cap price:",   f"{cap['price']:,.2f}")
    row("Floor price:", f"{floor['price']:,.2f}")
    col  = collar(args.notional, args.strike*1.02, args.strike*0.98, args.expiry,
                  args.freq, curve, args.vol)
    row("Collar (±2% strikes):", f"{col['price']:,.2f}  (net cost)")
    print()


def cmd_swaption(args):
    from instruments.fixed_income import swaption
    from services.market_data_service import MarketDataService
    curve = MarketDataService().flat_curve(args.rate)
    hdr(f"SWAPTION  N={args.notional:,.0f}  K={args.strike:.2%}  T_opt={args.t_option}y  T_swap={args.t_swap}y")
    for opt in ["payer", "receiver"]:
        res = swaption(args.notional, args.strike, args.t_option, args.t_swap,
                       args.freq, curve, args.vol, opt)
        row(f"{opt.capitalize()} swaption:", f"{res['price']:,.2f}")
    row("Forward swap rate:", f"{res['fwd_swap_rate']:.4f}  ({res['fwd_swap_rate']:.2%})")
    print()


def cmd_cds(args):
    from instruments.credit import cds, cds_implied_hazard
    hazard = cds_implied_hazard(args.spread, args.expiry, args.freq, args.rate, args.recovery)
    hdr(f"CDS  N={args.notional:,.0f}  Spread={args.spread:.0%}  T={args.expiry}y  R={args.recovery:.0%}")
    res = cds(args.notional, args.spread, args.expiry, args.freq,
              hazard, args.rate, args.recovery, True)
    row("NPV:",          f"{res['npv']:,.2f}")
    row("Fair spread:",  f"{res['fair_spread']:.4f}  ({res['fair_spread']*10000:.1f}bps)")
    row("Hazard rate:",  f"{hazard:.4f}  ({hazard:.2%})")
    row("Default prob:", f"{1-np.exp(-hazard*args.expiry):.2%}")
    row("Risky DV01:",   f"{res['dv01']:,.2f}")
    print()


def cmd_fx_forward(args):
    from instruments.fx import fx_forward, fx_swap
    hdr(f"FX FORWARD  S={args.spot}  r_d={args.r_d:.2%}  r_f={args.r_f:.2%}  T={args.expiry}y")
    res = fx_forward(args.spot, args.r_d, args.r_f, args.expiry, args.notional)
    row("Spot:",           f"{res['spot']:.4f}")
    row("Forward:",        f"{res['forward']:.4f}")
    row("Swap points:",    f"{res['swap_points']:.4f}")

    sw = fx_swap(args.spot, args.r_d, args.r_f, args.expiry/2, args.expiry)
    row("FX swap (near):", f"{sw['near_forward']:.4f}")
    row("FX swap (far):",  f"{sw['far_forward']:.4f}")
    row("Net swap pts:",   f"{sw['net_swap_points']:.4f}")
    print()


def cmd_fx_option(args):
    from instruments.fx import fx_option, straddle, risk_reversal
    hdr(f"FX OPTION  S={args.spot}  K={args.strike}  T={args.expiry}y  σ={args.vol:.0%}  N={args.notional:,.0f}")
    res = fx_option(args.spot, args.strike, args.expiry, args.r_d, args.r_f,
                    args.vol, args.notional, args.type)
    row("Price:",              f"{res['price']:.6f}")
    row("Premium (domestic):", f"{res['premium_domestic']:,.2f}")
    row("Premium (foreign):",  f"{res['premium_foreign']:,.2f}")
    row("Delta (spot):",       f"{res['delta_spot']:.4f}")
    row("Delta (fwd):",        f"{res['delta_fwd']:.4f}")
    row("Delta (prem-adj):",   f"{res['delta_premium_adj']:.4f}")
    row("Gamma:",              f"{res['gamma']:.6f}")
    row("Vega (per 1%):",      f"{res['vega']:.4f}")
    row("Theta (per day):",    f"{res['theta']:.4f}")
    row("Vanna:",              f"{res['vanna']:.6f}")
    row("Volga:",              f"{res['volga']:.6f}")

    std = straddle(args.spot, args.spot, args.expiry, args.r_d, args.r_f,
                   args.vol, args.notional)
    print(f"\n  ATM Straddle: {std['price']:.6f}")
    print()


def cmd_var(args):
    from risk.var import (historical_var, parametric_var, montecarlo_var,
                          evt_var, portfolio_var, kupiec_test)
    np.random.seed(42)
    if args.returns:
        returns = np.loadtxt(args.returns)
        print(f"  Loaded {len(returns)} daily returns from {args.returns}")
    else:
        returns = np.random.normal(0.0005, 0.015, 1000)
        print("  [demo] Synthetic returns: N=1000, μ=0.05%/day, σ=1.5%/day")

    hdr(f"VAR  Position={args.value:,.0f}  Confidence={args.confidence:.0%}  Horizon={args.horizon}d")
    kw = dict(position_value=args.value, confidence=args.confidence, horizon=args.horizon)

    methods = {
        "Historical":             historical_var(returns, **kw),
        "Parametric (Normal)":    parametric_var(returns, **kw, distribution="normal"),
        "Parametric (Student-t)": parametric_var(returns, **kw, distribution="t"),
        "Monte Carlo":            montecarlo_var(returns, **kw, n_sims=200_000),
        "EVT (POT)":              evt_var(returns, args.value, args.confidence),
    }
    table(["Method", "VaR", "CVaR"],
          [[name, f"{r['VaR']:>12,.2f}", f"{r['CVaR']:>12,.2f}"]
           for name, r in methods.items() if "error" not in r],
          [25, 15, 15])

    # Kupiec backtest
    n_exc = int((1-args.confidence)*len(returns))
    kt    = kupiec_test(len(returns), n_exc, args.confidence)
    print(f"\n  Kupiec test (synthetic):  LR={kt['lr_stat']:.3f}  p={kt['p_value']:.3f}  "
          f"Reject={kt['reject']}")
    print()


def cmd_stress(args):
    from risk.stress import stress_option
    hdr(f"STRESS TEST  {args.type.upper()}  S={args.spot}  K={args.strike}  T={args.expiry}y  σ={args.vol:.0%}")
    results = stress_option(args.spot, args.strike, args.expiry, args.rate, args.vol,
                            args.div, args.type)
    table(["Scenario", "Spot", "Vol", "Base", "Stressed", "P&L", "P&L%"],
          [[r["scenario"][:28], r["spot_shock"], r["vol_shock"],
            r["base_price"], r["stressed_price"], r["pnl"], r["pnl_pct"]]
           for r in results],
          [30, 7, 7, 8, 10, 10, 8])
    print()


def cmd_greeks_ladder(args):
    from risk.stress import greeks_ladder
    hdr(f"GREEKS LADDER  {args.type.upper()}  K={args.strike}  T={args.expiry}y  σ={args.vol:.0%}")
    res = greeks_ladder(args.spot, args.strike, args.expiry, args.rate, args.vol,
                        args.div, args.type)
    table(["Spot", "Price", "Delta", "Gamma", "Vega", "Theta"],
          [[r["spot"], r["price"], r["delta"], r["gamma"], r["vega"], r["theta"]]
           for r in res],
          [10, 10, 8, 10, 8, 10])
    print()


def cmd_pnl_explain(args):
    from risk.stress import pnl_explain
    from models.black_scholes import bsm
    hdr(f"P&L ATTRIBUTION  {args.type.upper()}  S={args.spot}→{args.spot+args.ds}")
    g = bsm(args.spot, args.strike, args.expiry, args.rate, args.vol, args.div, args.type)
    res = pnl_explain(g, args.ds, args.dvol, args.dt, args.dr)
    row("Delta P&L:",  f"{res['delta']:+.6f}")
    row("Gamma P&L:",  f"{res['gamma']:+.6f}")
    row("Vega P&L:",   f"{res['vega']:+.6f}")
    row("Theta P&L:",  f"{res['theta']:+.6f}")
    row("Rho P&L:",    f"{res['rho']:+.6f}")
    row("Vanna P&L:",  f"{res['vanna']:+.6f}")
    row("Volga P&L:",  f"{res['volga']:+.6f}")
    row("─"*30, "─"*10)
    row("Total (2nd order):", f"{res['total_2nd_order']:+.6f}")
    row("Total (incl. cross):", f"{res['total_with_cross']:+.6f}")
    print()


def cmd_implied_vol(args):
    from models.implied_vol import implied_vol_bsm, implied_vol_black76, implied_vol_gk
    hdr(f"IMPLIED VOL  Market price={args.market_price}  S={args.spot}  K={args.strike}  T={args.expiry}y")
    iv_bsm = implied_vol_bsm(args.market_price, args.spot, args.strike, args.expiry,
                              args.rate, args.div, args.type)
    row("BSM implied vol:", f"{iv_bsm:.6f}  ({iv_bsm:.2%})" if not np.isnan(iv_bsm) else "N/A")

    iv_b76 = implied_vol_black76(args.market_price, args.spot, args.strike, args.expiry,
                                  args.rate, args.type)
    row("Black-76 implied vol:", f"{iv_b76:.6f}  ({iv_b76:.2%})" if not np.isnan(iv_b76) else "N/A")
    print()


def cmd_heston(args):
    from models.heston import heston_price
    hdr(f"HESTON  S={args.spot}  K={args.strike}  T={args.expiry}y  v0={args.v0}")
    res = heston_price(args.spot, args.strike, args.expiry, args.rate, args.div,
                       args.v0, args.kappa, args.theta, args.xi, args.rho_heston, args.type)
    row("Price:",        f"{res['price']:.6f}")
    row("Implied vol:",  f"{res['implied_vol']:.4f}  ({res['implied_vol']:.2%})" if res.get("implied_vol") else "N/A")
    row("Delta:",        f"{res['delta']:.4f}")
    print()


def cmd_sabr(args):
    from models.heston import sabr_price
    hdr(f"SABR  F={args.spot}  K={args.strike}  T={args.expiry}y  α={args.alpha}  β={args.beta}")
    res = sabr_price(args.spot, args.strike, args.expiry, args.rate,
                     args.alpha, args.beta, args.rho_sabr, args.nu, args.type)
    row("Price:",        f"{res['price']:.6f}")
    row("Implied vol:",  f"{res['implied_vol']:.4f}  ({res['implied_vol']:.2%})")
    row("Delta:",        f"{res['delta']:.4f}")
    print()


# ─────────────────────────────────────────────────────────
# Argument parser
# ─────────────────────────────────────────────────────────

def add_base(p):
    p.add_argument("--spot",   type=float, default=100.0,  help="Spot price")
    p.add_argument("--strike", type=float, default=100.0,  help="Strike price")
    p.add_argument("--expiry", type=float, default=0.25,   help="Time to expiry (years)")
    p.add_argument("--rate",   type=float, default=0.05,   help="Risk-free rate")
    p.add_argument("--vol",    type=float, default=0.20,   help="Volatility")
    p.add_argument("--div",    type=float, default=0.00,   help="Dividend yield")
    p.add_argument("--type",   choices=["call","put"], default="call")
    return p


def build_parser():
    P = argparse.ArgumentParser(prog="python main.py",
                                 description="Market Risk & Pricing Engine",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = P.add_subparsers(dest="cmd", required=True)

    # option
    p = add_base(sub.add_parser("option"))
    p.add_argument("--model",    default="bsm", choices=["bsm","black76","gk","bachelier","binomial","binomial_lr","trinomial","mc","lsm"])
    p.add_argument("--exercise", default="european", choices=["european","american","bermudan"])

    # barrier
    p = add_base(sub.add_parser("barrier"))
    p.add_argument("--barrier",      type=float, default=90.0)
    p.add_argument("--barrier_type", default="down-out",
                   choices=["down-out","down-in","up-out","up-in"])
    p.add_argument("--rebate",  type=float, default=0.0)
    p.add_argument("--double",  action="store_true")
    p.add_argument("--lower",   type=float, default=80.0)
    p.add_argument("--upper",   type=float, default=120.0)
    p.add_argument("--mc",      action="store_true")

    # asian
    p = add_base(sub.add_parser("asian"))
    p.add_argument("--fixings",    type=int,  default=12)
    p.add_argument("--geometric",  action="store_true")
    p.add_argument("--continuous", action="store_true")
    p.add_argument("--averaging",  default="fixed", choices=["fixed","floating"])
    p.add_argument("--sims",       type=int, default=100_000)

    # digital
    p = add_base(sub.add_parser("digital"))
    p.add_argument("--digital_type", default="cash_or_nothing",
                   choices=["cash_or_nothing","asset_or_nothing","one_touch",
                            "no_touch","double_no_touch","supershare"])
    p.add_argument("--cash",      type=float, default=1.0)
    p.add_argument("--barrier",   type=float, default=110.0)
    p.add_argument("--direction", default="up", choices=["up","down"])
    p.add_argument("--payment",   default="expiry", choices=["expiry","touch"])
    p.add_argument("--lower",     type=float, default=90.0)
    p.add_argument("--upper",     type=float, default=110.0)

    # lookback
    p = add_base(sub.add_parser("lookback"))
    p.add_argument("--lb_style", default="floating", choices=["floating","fixed"])
    p.add_argument("--mc", action="store_true")

    # variance_swap
    p = sub.add_parser("variance_swap")
    p.add_argument("--spot",     type=float, default=100.0)
    p.add_argument("--vol",      type=float, default=0.20)
    p.add_argument("--expiry",   type=float, default=1.0)
    p.add_argument("--rate",     type=float, default=0.05)
    p.add_argument("--div",      type=float, default=0.00)
    p.add_argument("--notional", type=float, default=1_000_000)
    p.add_argument("--lower",    type=float, default=None)
    p.add_argument("--upper",    type=float, default=None)

    # bond
    p = sub.add_parser("bond")
    p.add_argument("--face",   type=float, default=100.0)
    p.add_argument("--coupon", type=float, default=0.05)
    p.add_argument("--expiry", type=float, default=5.0)
    p.add_argument("--rate",   type=float, default=0.04)
    p.add_argument("--freq",   type=int,   default=2)

    # irs
    p = sub.add_parser("irs")
    p.add_argument("--notional",   type=float, default=10_000_000)
    p.add_argument("--fixed_rate", type=float, default=0.04)
    p.add_argument("--expiry",     type=float, default=5.0)
    p.add_argument("--rate",       type=float, default=0.035)
    p.add_argument("--freq",       type=int,   default=4)
    p.add_argument("--pay_fixed",  action="store_true", default=True)

    # cap_floor
    p = sub.add_parser("cap_floor")
    p.add_argument("--notional", type=float, default=10_000_000)
    p.add_argument("--strike",   type=float, default=0.05)
    p.add_argument("--expiry",   type=float, default=5.0)
    p.add_argument("--rate",     type=float, default=0.04)
    p.add_argument("--vol",      type=float, default=0.20)
    p.add_argument("--freq",     type=int,   default=4)

    # swaption
    p = sub.add_parser("swaption")
    p.add_argument("--notional",  type=float, default=10_000_000)
    p.add_argument("--strike",    type=float, default=0.04)
    p.add_argument("--t_option",  type=float, default=1.0)
    p.add_argument("--t_swap",    type=float, default=5.0)
    p.add_argument("--rate",      type=float, default=0.035)
    p.add_argument("--vol",       type=float, default=0.20)
    p.add_argument("--freq",      type=int,   default=4)

    # cds
    p = sub.add_parser("cds")
    p.add_argument("--notional",  type=float, default=10_000_000)
    p.add_argument("--spread",    type=float, default=0.01)
    p.add_argument("--expiry",    type=float, default=5.0)
    p.add_argument("--rate",      type=float, default=0.02)
    p.add_argument("--recovery",  type=float, default=0.40)
    p.add_argument("--freq",      type=int,   default=4)

    # fx_forward
    p = sub.add_parser("fx_forward")
    p.add_argument("--spot",     type=float, default=1.0800)
    p.add_argument("--r_d",      type=float, default=0.04)
    p.add_argument("--r_f",      type=float, default=0.02)
    p.add_argument("--expiry",   type=float, default=0.25)
    p.add_argument("--notional", type=float, default=1_000_000)

    # fx_option
    p = sub.add_parser("fx_option")
    p.add_argument("--spot",     type=float, default=1.0800)
    p.add_argument("--strike",   type=float, default=1.0900)
    p.add_argument("--expiry",   type=float, default=0.25)
    p.add_argument("--r_d",      type=float, default=0.04)
    p.add_argument("--r_f",      type=float, default=0.02)
    p.add_argument("--vol",      type=float, default=0.08)
    p.add_argument("--notional", type=float, default=1_000_000)
    p.add_argument("--type",     choices=["call","put"], default="call")

    # fx_barrier
    p = sub.add_parser("fx_barrier")
    p.add_argument("--spot",         type=float, default=1.0800)
    p.add_argument("--strike",       type=float, default=1.0900)
    p.add_argument("--barrier",      type=float, default=1.0500)
    p.add_argument("--expiry",       type=float, default=0.25)
    p.add_argument("--r_d",          type=float, default=0.04)
    p.add_argument("--r_f",          type=float, default=0.02)
    p.add_argument("--vol",          type=float, default=0.08)
    p.add_argument("--notional",     type=float, default=1_000_000)
    p.add_argument("--type",         choices=["call","put"], default="call")
    p.add_argument("--barrier_type", default="down-out",
                   choices=["down-out","down-in","up-out","up-in"])

    # var
    p = sub.add_parser("var")
    p.add_argument("--value",      type=float, default=1_000_000)
    p.add_argument("--confidence", type=float, default=0.95)
    p.add_argument("--horizon",    type=int,   default=1)
    p.add_argument("--returns",    type=str,   default=None)

    # stress
    p = add_base(sub.add_parser("stress"))

    # greeks_ladder
    p = add_base(sub.add_parser("greeks_ladder"))

    # pnl_explain
    p = add_base(sub.add_parser("pnl_explain"))
    p.add_argument("--ds",   type=float, default=2.0,   help="Spot move")
    p.add_argument("--dvol", type=float, default=0.01,  help="Vol move (absolute)")
    p.add_argument("--dt",   type=float, default=1.0,   help="Time elapsed (days)")
    p.add_argument("--dr",   type=float, default=0.001, help="Rate move (absolute)")

    # implied_vol
    p = add_base(sub.add_parser("implied_vol"))
    p.add_argument("--market_price", type=float, default=5.0)

    # heston
    p = add_base(sub.add_parser("heston"))
    p.add_argument("--v0",        type=float, default=0.04)
    p.add_argument("--kappa",     type=float, default=2.0)
    p.add_argument("--theta",     type=float, default=0.04)
    p.add_argument("--xi",        type=float, default=0.3)
    p.add_argument("--rho_heston",type=float, default=-0.7)

    # sabr
    p = add_base(sub.add_parser("sabr"))
    p.add_argument("--alpha",    type=float, default=0.15)
    p.add_argument("--beta",     type=float, default=0.5)
    p.add_argument("--nu",       type=float, default=0.4)
    p.add_argument("--rho_sabr", type=float, default=-0.3)

    return P


def cmd_fx_barrier(args):
    from instruments.fx import fx_barrier
    hdr(f"FX BARRIER  {args.type.upper()}  {args.barrier_type}  S={args.spot}  K={args.strike}  H={args.barrier}")
    res = fx_barrier(args.spot, args.strike, args.barrier, args.expiry,
                     args.r_d, args.r_f, args.vol, args.type, args.barrier_type,
                     notional=args.notional)
    row("Price:", f"{res['price']:.6f}")
    row("Premium (domestic):", f"{res['premium_domestic']:,.2f}")
    print()


COMMANDS = {
    "option":        cmd_option,
    "barrier":       cmd_barrier,
    "asian":         cmd_asian,
    "digital":       cmd_digital,
    "lookback":      cmd_lookback,
    "variance_swap": cmd_variance_swap,
    "bond":          cmd_bond,
    "irs":           cmd_irs,
    "cap_floor":     cmd_cap_floor,
    "swaption":      cmd_swaption,
    "cds":           cmd_cds,
    "fx_forward":    cmd_fx_forward,
    "fx_option":     cmd_fx_option,
    "fx_barrier":    cmd_fx_barrier,
    "var":           cmd_var,
    "stress":        cmd_stress,
    "greeks_ladder": cmd_greeks_ladder,
    "pnl_explain":   cmd_pnl_explain,
    "implied_vol":   cmd_implied_vol,
    "heston":        cmd_heston,
    "sabr":          cmd_sabr,
}


def main():
    parser = build_parser()
    args   = parser.parse_args()
    COMMANDS[args.cmd](args)


if __name__ == "__main__":
    main()
