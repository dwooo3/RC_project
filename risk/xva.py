"""
XVA engine — netting sets, CSA collateral and the valuation-adjustment suite
(CVA / DVA / FVA / MVA / KVA), Master-plan M4.

Builds on risk/exposure.py: instead of summarising one trade to EPE/PFE, it
simulates the *path-wise MtM cube* (n_sims × n_grid) for a portfolio of IRS that
share a single Hull-White short-rate path — so trades net correctly. On top of
the netted cube it applies a CSA (variation margin with threshold / MTA / margin
period of risk) and integrates every adjustment against the counterparty/own
default distributions of Phase-1 hazard curves.

Identities (tested): offsetting trades net to ~0 exposure (netting benefit);
zero threshold + zero MPoR collateralises exposure to ~0; every adjustment is 0
when its spread/factor is 0 and scales linearly with it; collateral reduces both
CVA and FVA.
"""

from __future__ import annotations

import numpy as np

from curves.yield_curve import YieldCurve


# ── path-wise Hull-White MtM cube for an IRS portfolio ───────

def _hw_affine(hw, t, s, t_var):
    """HW P(t,s)=A·e^{-B r}: return (A, B) vectorisable in r."""
    k, sg = hw.kappa, hw.sigma
    B = (1 - np.exp(-k * (s - t))) / k
    P0s = hw.curve.discount(s)
    P0t = hw.curve.discount(t) if t > 1e-8 else 1.0
    f0t = hw._inst_forward(t)
    A = (P0s / P0t) * np.exp(B * f0t - sg**2 * B**2 * t_var / (4 * k))
    return A, B


def _swap_value(hw, r, t, notional, fixed_rate, pay_times, dt_pay, sign):
    remaining = pay_times[pay_times > t + 1e-12]
    if remaining.size == 0:
        return np.zeros_like(r)
    t_var = 1 - np.exp(-2 * hw.kappa * t)
    ann = np.zeros_like(r)
    for s in remaining:
        A, B = _hw_affine(hw, t, s, t_var)
        ann += dt_pay * A * np.exp(-B * r)
    A_end, B_end = _hw_affine(hw, t, remaining[-1], t_var)
    float_pv = 1.0 - A_end * np.exp(-B_end * r)
    return sign * notional * (float_pv - fixed_rate * ann)


def simulate_irs_portfolio(trades: list[dict], curve: YieldCurve, kappa=0.1,
                           sigma_r=0.012, n_sims=4000, n_grid=24, seed=42) -> dict:
    """Simulate a shared HW path and revalue each IRS at every grid date.
    Returns the netted MtM cube (n_sims × n_grid+1) and per-trade cubes.

    Each trade: dict(notional, fixed_rate, T, freq, pay_fixed)."""
    from models.short_rate import HullWhite

    hw = HullWhite(kappa, sigma_r, curve)
    rng = np.random.default_rng(seed)
    T = max(tr["T"] for tr in trades)
    grid = np.linspace(0.0, T, n_grid + 1)
    steps_per = 8
    fine_steps = n_grid * steps_per
    dt = T / fine_steps

    specs = []
    for tr in trades:
        dt_pay = 1.0 / tr["freq"]
        pay_times = np.array([i * dt_pay for i in range(1, int(round(tr["T"] * tr["freq"])) + 1)])
        specs.append((tr, dt_pay, pay_times, 1.0 if tr.get("pay_fixed", True) else -1.0))

    per_trade = [np.zeros((n_sims, n_grid + 1)) for _ in trades]
    r = np.full(n_sims, hw._r0)

    def revalue(g_idx, t):
        for k, (tr, dt_pay, pay_times, sign) in enumerate(specs):
            if t <= tr["T"] + 1e-9:
                per_trade[k][:, g_idx] = _swap_value(hw, r, t, tr["notional"],
                                                     tr["fixed_rate"], pay_times,
                                                     dt_pay, sign)

    revalue(0, 0.0)
    g = 0
    for i in range(fine_steps):
        t_i = i * dt
        f = hw.curve.forward_rate(t_i, t_i + dt)
        dfdt = (hw.curve.rate(t_i + dt) - hw.curve.rate(max(t_i - dt, 0.001))) / (2 * dt)
        theta_t = dfdt + kappa * f + sigma_r**2 * (1 - np.exp(-2 * kappa * t_i)) / (2 * kappa)
        r = r + (theta_t - kappa * r) * dt + sigma_r * np.sqrt(dt) * rng.standard_normal(n_sims)
        t_next = (i + 1) * dt
        if g + 1 <= n_grid and np.isclose(t_next, grid[g + 1], atol=dt / 2):
            g += 1
            revalue(g, grid[g])
            if g >= n_grid:
                break
    netted = sum(per_trade)
    return dict(times=grid, mtm=netted, per_trade=per_trade, n_sims=n_sims,
                n_trades=len(trades))


# ── CSA collateral (variation margin) ────────────────────────

def collateralize(times, mtm, threshold=0.0, mta=0.0, mpor=2.0 / 52,
                  two_way=True) -> np.ndarray:
    """Apply variation margin under a (two-way) CSA. Collateral held reflects the
    MtM as of t-MPoR (the margin-period-of-risk gap): the counterparty posts
    max(MtM_lag - threshold, 0); under a two-way CSA we symmetrically post
    max(-MtM_lag - threshold, 0). Returns the collateralised MtM = MtM - C, so a
    zero threshold + zero MPoR drives exposure to ~0 on both sides."""
    times = np.asarray(times, float)
    n_grid = len(times) - 1
    coll = np.zeros_like(mtm)
    for g in range(n_grid + 1):
        t_lag = times[g] - mpor
        if t_lag <= times[0]:
            lagged = mtm[:, 0]
        else:                                          # interpolate in time (per path)
            hi = int(np.searchsorted(times, t_lag, side="left"))
            hi = min(max(hi, 1), n_grid)
            lo = hi - 1
            w = (t_lag - times[lo]) / (times[hi] - times[lo])
            lagged = (1 - w) * mtm[:, lo] + w * mtm[:, hi]
        recv = np.maximum(lagged - threshold, 0.0)     # counterparty posts to us
        post = np.maximum(-lagged - threshold, 0.0) if two_way else 0.0
        if mta > 0:                                     # call only above the MTA
            recv = np.where(lagged - threshold > mta, recv, 0.0)
            if two_way:
                post = np.where(-lagged - threshold > mta, post, 0.0)
        coll[:, g] = mtm[:, g] - (recv - post)
    return coll


def exposure_profiles(times, mtm) -> dict:
    """EPE/ENE/EE and PFE 95/99 from a (collateralised or raw) MtM cube."""
    pos = np.maximum(mtm, 0.0)
    neg = np.minimum(mtm, 0.0)
    return dict(times=np.asarray(times, float),
                epe=pos.mean(axis=0), ene=neg.mean(axis=0), ee=mtm.mean(axis=0),
                pfe95=np.quantile(pos, 0.95, axis=0),
                pfe99=np.quantile(pos, 0.99, axis=0))


# ── initial margin (dynamic, model-based) ────────────────────

def initial_margin_profile(times, mtm, mpor=2.0 / 52, q=0.99) -> np.ndarray:
    """Dynamic IM(t) = q-quantile across paths of the netting-set value change
    over the margin period of risk [t, t+MPoR] (a model proxy for SIMM/ISDA)."""
    times = np.asarray(times, float)
    n_grid = len(times) - 1
    im = np.zeros(n_grid + 1)
    for g in range(n_grid + 1):
        t_fwd = times[g] + mpor
        if t_fwd >= times[-1]:
            fwd = mtm[:, -1]
        else:
            hi = int(np.searchsorted(times, t_fwd, side="left"))
            hi = min(max(hi, 1), n_grid)
            lo = hi - 1
            w = (t_fwd - times[lo]) / (times[hi] - times[lo])
            fwd = (1 - w) * mtm[:, lo] + w * mtm[:, hi]
        im[g] = np.quantile(np.abs(fwd - mtm[:, g]), q)
    return im


# ── survival helper ──────────────────────────────────────────

def _survival(curve, t):
    return 1.0 if curve is None else curve.survival(t)


# ── valuation adjustments ────────────────────────────────────

def funding_value_adjustment(times, epe, ene, disc_curve, funding_spread,
                             cpty_hazard=None, own_hazard=None) -> dict:
    """FVA = FCA - FBA: funding cost on (uncollateralised) positive exposure and
    funding benefit on negative exposure, while both parties survive."""
    times = np.asarray(times, float)
    fca = fba = 0.0
    for i in range(1, len(times)):
        t0, t1 = times[i - 1], times[i]
        tm, dtau = 0.5 * (t0 + t1), t1 - t0
        surv = _survival(cpty_hazard, tm) * _survival(own_hazard, tm)
        df = disc_curve.discount(tm) * funding_spread * surv * dtau
        fca += 0.5 * (epe[i - 1] + epe[i]) * df
        fba += -0.5 * (ene[i - 1] + ene[i]) * df
    return dict(fca=fca, fba=fba, fva=fca - fba)


def margin_value_adjustment(times, im, disc_curve, funding_spread,
                            cpty_hazard=None, own_hazard=None) -> float:
    """MVA = funding cost of posting initial margin over the trade life."""
    times = np.asarray(times, float)
    mva = 0.0
    for i in range(1, len(times)):
        t0, t1 = times[i - 1], times[i]
        tm, dtau = 0.5 * (t0 + t1), t1 - t0
        surv = _survival(cpty_hazard, tm) * _survival(own_hazard, tm)
        mva += funding_spread * 0.5 * (im[i - 1] + im[i]) * disc_curve.discount(tm) * surv * dtau
    return mva


def capital_value_adjustment(times, epe, disc_curve, cost_of_capital,
                             risk_weight=1.0, alpha=1.4,
                             cpty_hazard=None, own_hazard=None) -> dict:
    """KVA = cost of holding CCR capital over the life. Capital K(t) = RW·8%·
    EAD(t), EAD(t) = α·EffectiveEPE(t) (running max of EPE, Basel-style)."""
    times = np.asarray(times, float)
    eff_epe = np.maximum.accumulate(np.asarray(epe, float))    # effective EPE
    ead = alpha * eff_epe
    capital = risk_weight * 0.08 * ead
    kva = 0.0
    for i in range(1, len(times)):
        t0, t1 = times[i - 1], times[i]
        tm, dtau = 0.5 * (t0 + t1), t1 - t0
        surv = _survival(cpty_hazard, tm) * _survival(own_hazard, tm)
        kva += cost_of_capital * 0.5 * (capital[i - 1] + capital[i]) * disc_curve.discount(tm) * surv * dtau
    return dict(kva=kva, peak_capital=float(capital.max()), peak_ead=float(ead.max()))


def xva_suite(sim, disc_curve, cpty_hazard, own_hazard=None, *,
              funding_spread=0.0, cost_of_capital=0.0, risk_weight=1.0,
              csa=None, im_mpor=2.0 / 52, recovery=None, own_recovery=None) -> dict:
    """Full XVA on a simulated netting-set cube. csa=dict(threshold,mta,mpor)
    collateralises CVA/FVA exposure; IM (for MVA) is always dynamic."""
    from risk.exposure import cva_from_profile

    times, mtm = sim["times"], sim["mtm"]
    raw = exposure_profiles(times, mtm)
    if csa is not None:
        coll_mtm = collateralize(times, mtm, csa.get("threshold", 0.0),
                                 csa.get("mta", 0.0), csa.get("mpor", 2.0 / 52))
        prof = exposure_profiles(times, coll_mtm)
    else:
        prof = raw

    credit = cva_from_profile(times, prof["epe"], cpty_hazard, disc_curve,
                              recovery=recovery, ene=prof["ene"],
                              own_hazard_curve=own_hazard, own_recovery=own_recovery)
    fva = funding_value_adjustment(times, prof["epe"], prof["ene"], disc_curve,
                                   funding_spread, cpty_hazard, own_hazard)
    im = initial_margin_profile(times, mtm, im_mpor)
    mva = margin_value_adjustment(times, im, disc_curve, funding_spread,
                                  cpty_hazard, own_hazard)
    kva = capital_value_adjustment(times, prof["epe"], disc_curve, cost_of_capital,
                                   risk_weight, cpty_hazard=cpty_hazard,
                                   own_hazard=own_hazard)
    total = (credit["cva"] - credit["dva"] + fva["fva"] + mva + kva["kva"])
    return dict(cva=credit["cva"], dva=credit["dva"], bcva=credit["bcva"],
                fca=fva["fca"], fba=fva["fba"], fva=fva["fva"], mva=mva,
                kva=kva["kva"], peak_capital=kva["peak_capital"],
                peak_epe=float(prof["epe"].max()), peak_im=float(im.max()),
                total_xva=total, collateralised=csa is not None)
