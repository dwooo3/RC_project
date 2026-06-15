"""
Mortgage pass-through (MBS) with a prepayment model, Master-plan M8.

Projects the monthly cashflows of an amortising mortgage pool that prepays at a
PSA-scaled CPR: the borrower pays scheduled principal + interest on the gross
WAC, prepays a fraction (SMM) of the surviving balance each month, and the
investor receives scheduled + prepaid principal plus interest on the net
pass-through coupon. Discounting the projected cashflows (flat rate or a curve +
OAS) gives the price, and the principal timing gives the weighted-average life.

Validated: all principal is returned (Σ principal = original balance); zero
prepayment leaves the scheduled amortisation and prices to par when discounted
at the net coupon; faster prepayment shortens WAL; price falls as the discount
rate rises; OAS↔price round-trips.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq


def psa_cpr(month, psa=100.0):
    """PSA prepayment ramp: CPR rises 0.2%/mo to 6% at month 30, then flat."""
    base = 0.06 * min(month, 30) / 30.0
    return base * psa / 100.0


def mbs_cashflows(balance, wac, net_coupon, wam_months, psa=100.0):
    """Monthly cashflows of the pool. Returns dict of arrays (1..wam)."""
    c = wac / 12.0
    n = int(wam_months)
    pmt = balance * c * (1 + c) ** n / ((1 + c) ** n - 1) if c > 0 else balance / n
    B = balance
    months, interest, sched, prepay, total = [], [], [], [], []
    for m in range(1, n + 1):
        ig = c * B
        sp = min(pmt - ig, B)
        smm = 1 - (1 - psa_cpr(m, psa)) ** (1 / 12.0)
        pp = smm * (B - sp)
        inv_int = (net_coupon / 12.0) * B
        months.append(m); interest.append(inv_int)
        sched.append(sp); prepay.append(pp)
        total.append(inv_int + sp + pp)
        B -= sp + pp
        if B <= 1e-6:
            break
    return dict(month=np.array(months), interest=np.array(interest),
                sched_principal=np.array(sched), prepay=np.array(prepay),
                principal=np.array(sched) + np.array(prepay), total=np.array(total))


def mbs_price(balance, wac, net_coupon, wam_months, psa=100.0,
              disc_rate=None, curve=None, oas=0.0) -> dict:
    """Price + WAL of the pass-through. Discount at a flat rate or a curve+OAS."""
    cf = mbs_cashflows(balance, wac, net_coupon, wam_months, psa)
    t = cf["month"] / 12.0
    if curve is not None:
        df = np.array([curve.discount(ti) * np.exp(-oas * ti) for ti in t])
    else:
        r = disc_rate if disc_rate is not None else net_coupon
        df = (1 + r / 12.0) ** (-cf["month"]) * np.exp(-oas * t)  # monthly comp.
    price = float(np.sum(cf["total"] * df))
    principal = cf["principal"]
    wal = float(np.sum(t * principal) / np.sum(principal))
    return dict(price=price, price_pct=100.0 * price / balance, wal=wal,
                total_principal=float(principal.sum()), psa=psa)


def mbs_oas(market_price, balance, wac, net_coupon, wam_months, psa=100.0,
            curve=None, disc_rate=None) -> float:
    """Solve the OAS (flat spread) that reprices the pool to the market price."""
    def f(oas):
        return mbs_price(balance, wac, net_coupon, wam_months, psa,
                         disc_rate, curve, oas)["price"] - market_price
    return brentq(f, -0.5, 0.5, xtol=1e-10)
