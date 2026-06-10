"""
Counterparty exposure simulation + CVA/PFE (Phase 4).

Simulates the market state forward (Hull-White short rate for IRS, GBM for FX
forwards), revalues the trade analytically at each grid date per path, and
builds EPE/ENE/PFE profiles. CVA integrates EPE against the default
distribution of a Phase-1 HazardCurve — replacing the old profile-input-only
CVA with a simulated-exposure pipeline.
"""

import numpy as np

from curves.yield_curve import YieldCurve


def irs_exposure_profile(notional: float, fixed_rate: float, T: float, freq: int,
                         curve: YieldCurve, kappa: float = 0.1,
                         sigma_r: float = 0.012, pay_fixed: bool = True,
                         n_sims: int = 4000, n_grid: int = 24,
                         seed: int = 42) -> dict:
    """
    IRS exposure under Hull-White: simulate r_t, revalue the remaining swap at
    each grid date with analytic HW bond reconstitution P(t, s; r_t).
    Returns time grid, EPE/ENE (mean positive/negative exposure) and PFE 95/99.
    """
    from models.short_rate import HullWhite

    hw = HullWhite(kappa, sigma_r, curve)
    rng = np.random.default_rng(seed)
    dt_pay = 1.0 / freq
    pay_times = np.array([i * dt_pay for i in range(1, int(round(T * freq)) + 1)])

    grid = np.linspace(0.0, T, n_grid + 1)
    steps_per = 8
    sign = 1.0 if pay_fixed else -1.0

    # exact OU transition between grid dates for x = r - f(0,t) drift-adjusted:
    # simulate r via the HW SDE on a fine grid, then sample at grid dates.
    fine_steps = n_grid * steps_per
    dt = T / fine_steps
    r = np.full(n_sims, hw._r0)
    epe = np.zeros(n_grid + 1)
    ene = np.zeros(n_grid + 1)
    pfe95 = np.zeros(n_grid + 1)
    pfe99 = np.zeros(n_grid + 1)
    ee = np.zeros(n_grid + 1)

    def swap_value(r_arr: np.ndarray, t: float) -> np.ndarray:
        remaining = pay_times[pay_times > t + 1e-12]
        if remaining.size == 0:
            return np.zeros_like(r_arr)
        # vectorized over paths: P(t,s) = A(t,s) e^{-B r}; A,B from HW affine form
        ann = np.zeros_like(r_arr)
        for s in remaining:
            k_, sg = hw.kappa, hw.sigma
            B = (1 - np.exp(-k_ * (s - t))) / k_
            P0T = hw.curve.discount(s)
            P0t = hw.curve.discount(t) if t > 1e-8 else 1.0
            f0t = hw._inst_forward(t)
            A = (P0T / P0t) * np.exp(B * f0t - sg**2 * B**2 * (1 - np.exp(-2 * k_ * t)) / (4 * k_))
            ann += dt_pay * A * np.exp(-B * r_arr)
        s_end = remaining[-1]
        k_, sg = hw.kappa, hw.sigma
        B_end = (1 - np.exp(-k_ * (s_end - t))) / k_
        P0T = hw.curve.discount(s_end)
        P0t = hw.curve.discount(t) if t > 1e-8 else 1.0
        f0t = hw._inst_forward(t)
        A_end = (P0T / P0t) * np.exp(B_end * f0t - sg**2 * B_end**2 * (1 - np.exp(-2 * k_ * t)) / (4 * k_))
        P_end = A_end * np.exp(-B_end * r_arr)
        float_pv = 1.0 - P_end
        return sign * notional * (float_pv - fixed_rate * ann)

    v0 = swap_value(r, 0.0)
    epe[0] = max(v0.mean(), 0.0) if np.isscalar(v0) else np.maximum(v0, 0).mean()
    g = 0
    for i in range(fine_steps):
        t_i = i * dt
        f = hw.curve.forward_rate(t_i, t_i + dt)
        dfdt = (hw.curve.rate(t_i + dt) - hw.curve.rate(max(t_i - dt, 0.001))) / (2 * dt)
        theta_t = dfdt + kappa * f + sigma_r**2 * (1 - np.exp(-2 * kappa * t_i)) / (2 * kappa)
        r = r + (theta_t - kappa * r) * dt + sigma_r * np.sqrt(dt) * rng.standard_normal(n_sims)
        t_next = (i + 1) * dt
        if np.isclose(t_next, grid[g + 1], atol=dt / 2):
            g += 1
            v = swap_value(r, grid[g])
            pos = np.maximum(v, 0.0)
            epe[g] = pos.mean()
            ene[g] = np.minimum(v, 0.0).mean()
            ee[g] = v.mean()
            pfe95[g] = np.quantile(pos, 0.95)
            pfe99[g] = np.quantile(pos, 0.99)
            if g >= n_grid:
                break
    return dict(times=grid, epe=epe, ene=ene, ee=ee, pfe95=pfe95, pfe99=pfe99,
                n_sims=n_sims, instrument="irs", pay_fixed=pay_fixed)


def fx_forward_exposure_profile(S: float, K: float, T: float, r_d: float,
                                r_f: float, sigma_fx: float,
                                notional_fgn: float = 1_000_000,
                                position: str = "long",
                                n_sims: int = 10_000, n_grid: int = 24,
                                seed: int = 42) -> dict:
    """
    FX forward exposure under GBM spot: V_t = df_d(T-t)·N·(F_t - K), with
    F_t = S_t·e^{(r_d - r_f)(T-t)}.
    """
    rng = np.random.default_rng(seed)
    grid = np.linspace(0.0, T, n_grid + 1)
    sign = 1.0 if position == "long" else -1.0
    epe = np.zeros(n_grid + 1); ene = np.zeros(n_grid + 1)
    pfe95 = np.zeros(n_grid + 1); pfe99 = np.zeros(n_grid + 1)
    S_t = np.full(n_sims, S)
    for g in range(1, n_grid + 1):
        dt = grid[g] - grid[g - 1]
        Z = rng.standard_normal(n_sims)
        S_t = S_t * np.exp((r_d - r_f - 0.5 * sigma_fx**2) * dt
                           + sigma_fx * np.sqrt(dt) * Z)
        tau = T - grid[g]
        F_t = S_t * np.exp((r_d - r_f) * tau)
        v = sign * notional_fgn * (F_t - K) * np.exp(-r_d * tau)
        pos = np.maximum(v, 0.0)
        epe[g] = pos.mean(); ene[g] = np.minimum(v, 0.0).mean()
        pfe95[g] = np.quantile(pos, 0.95); pfe99[g] = np.quantile(pos, 0.99)
    return dict(times=grid, epe=epe, ene=ene, pfe95=pfe95, pfe99=pfe99,
                n_sims=n_sims, instrument="fx_forward", position=position)


def cva_from_profile(times, epe, hazard_curve, disc_curve: YieldCurve,
                     recovery: float | None = None,
                     ene=None, own_hazard_curve=None,
                     own_recovery: float | None = None) -> dict:
    """
    CVA = (1-R) Σ EPE(t_mid)·df(t_mid)·[Q(t_{i-1}) - Q(t_i)] on the exposure
    grid, with survival from a Phase-1 HazardCurve. DVA symmetrically on ENE
    with the own-credit curve when supplied.
    """
    recovery = hazard_curve.recovery if recovery is None else recovery
    times = np.asarray(times, dtype=float)
    epe = np.asarray(epe, dtype=float)
    cva = 0.0
    for i in range(1, len(times)):
        t0, t1 = times[i - 1], times[i]
        t_mid = 0.5 * (t0 + t1)
        epe_mid = 0.5 * (epe[i - 1] + epe[i])
        dq = hazard_curve.survival(t0) - hazard_curve.survival(t1)
        cva += (1 - recovery) * epe_mid * disc_curve.discount(t_mid) * dq

    dva = 0.0
    if ene is not None and own_hazard_curve is not None:
        own_recovery = (own_hazard_curve.recovery if own_recovery is None
                        else own_recovery)
        ene = np.asarray(ene, dtype=float)
        for i in range(1, len(times)):
            t0, t1 = times[i - 1], times[i]
            t_mid = 0.5 * (t0 + t1)
            ene_mid = 0.5 * (ene[i - 1] + ene[i])
            dq = own_hazard_curve.survival(t0) - own_hazard_curve.survival(t1)
            dva += (1 - own_recovery) * (-ene_mid) * disc_curve.discount(t_mid) * dq

    return dict(cva=cva, dva=dva, bcva=cva - dva, recovery=recovery,
                pd_horizon=1.0 - hazard_curve.survival(float(times[-1])))
