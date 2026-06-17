"""
Cross-currency swaps (Phase 2).

Constant-notional XCCY swap on S = domestic per foreign (e.g. RUB per USD):
domestic leg (float + basis spread, or fixed) vs foreign leg (float or fixed),
with initial and final exchange of notionals. Each leg is built from simple
projected forwards on its own projection curve and discounted on its own
discount curve; the foreign leg PV converts to domestic at spot.

Conventions: receive the domestic leg, pay the foreign leg (sign flips via
`receive_domestic=False`). The basis spread lives on the domestic leg —
the RUB-USD market quotes the basis on the RUB side.
"""


from curves.yield_curve import YieldCurve


def _float_leg_pv(notional: float, spread: float, T: float, freq: int,
                  disc: YieldCurve, proj: YieldCurve,
                  exchange_notional: bool) -> dict:
    """PV of a float leg: simple projected forwards + spread, optional redemption."""
    dt = 1.0 / freq
    n = int(round(T * freq))
    pv, annuity = 0.0, 0.0
    for i in range(1, n + 1):
        t0, t1 = (i - 1) * dt, i * dt
        fwd = (proj.discount(t0) / proj.discount(t1) - 1.0) / dt
        df = disc.discount(t1)
        pv += (fwd + spread) * dt * df
        annuity += dt * df
    if exchange_notional:
        pv += disc.discount(T)        # final notional; initial exchange handled by caller
    return dict(pv=notional * pv, annuity=annuity)


def _fixed_leg_pv(notional: float, rate: float, T: float, freq: int,
                  disc: YieldCurve, exchange_notional: bool) -> dict:
    dt = 1.0 / freq
    n = int(round(T * freq))
    annuity = sum(dt * disc.discount(i * dt) for i in range(1, n + 1))
    pv = rate * annuity
    if exchange_notional:
        pv += disc.discount(T)
    return dict(pv=notional * pv, annuity=annuity)


def xccy_swap(notional_dom: float, S: float, T: float, freq: int,
              disc_dom: YieldCurve, disc_fgn: YieldCurve,
              proj_dom: YieldCurve | None = None,
              proj_fgn: YieldCurve | None = None,
              basis_spread: float = 0.0,
              leg_dom: str = "float", leg_fgn: str = "float",
              fixed_rate_dom: float = 0.0, fixed_rate_fgn: float = 0.0,
              exchange_notionals: bool = True,
              receive_domestic: bool = True) -> dict:
    """
    Constant-notional cross-currency swap.
    notional_dom: domestic-leg notional; foreign notional = notional_dom / S.
    NPV reported in domestic currency. Fair basis spread is the domestic-leg
    spread that zeroes the NPV (float domestic leg only).
    """
    proj_dom = proj_dom or disc_dom
    proj_fgn = proj_fgn or disc_fgn
    notional_fgn = notional_dom / S

    if leg_dom == "float":
        dom = _float_leg_pv(notional_dom, basis_spread, T, freq, disc_dom, proj_dom,
                            exchange_notionals)
    else:
        dom = _fixed_leg_pv(notional_dom, fixed_rate_dom, T, freq, disc_dom,
                            exchange_notionals)
    if leg_fgn == "float":
        fgn = _float_leg_pv(notional_fgn, 0.0, T, freq, disc_fgn, proj_fgn,
                            exchange_notionals)
    else:
        fgn = _fixed_leg_pv(notional_fgn, fixed_rate_fgn, T, freq, disc_fgn,
                            exchange_notionals)

    # Initial exchange at t=0: receive-domestic pays out N_dom, receives N_fgn·S
    # — at spot start these net to zero in domestic terms, kept explicit for clarity.
    initial = (notional_fgn * S - notional_dom) if exchange_notionals else 0.0

    npv = dom["pv"] - fgn["pv"] * S + initial
    if not receive_domestic:
        npv = -npv

    fair_basis = float("nan")
    if leg_dom == "float":
        # spread* solves dom_pv(spread*) = S·fgn_pv - initial
        annuity_dom = dom["annuity"] * notional_dom
        fair_basis = basis_spread - (dom["pv"] - fgn["pv"] * S + initial) / annuity_dom

    # FX delta of the foreign leg in domestic terms (notional_fgn fixed)
    fx_delta = -fgn["pv"] if receive_domestic else fgn["pv"]
    dv01_dom = notional_dom * dom["annuity"] / 10000
    dv01_fgn = notional_fgn * fgn["annuity"] / 10000

    return dict(npv=npv, fair_basis_spread=fair_basis,
                leg_domestic_pv=dom["pv"], leg_foreign_pv_fgn=fgn["pv"],
                leg_foreign_pv_dom=fgn["pv"] * S, initial_exchange=initial,
                fx_delta=fx_delta, dv01_domestic=dv01_dom, dv01_foreign=dv01_fgn,
                notional_foreign=notional_fgn, basis_spread=basis_spread)
