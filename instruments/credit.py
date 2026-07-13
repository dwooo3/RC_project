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
                                 r_curve=None, freq: int = 4) -> dict:
    """
    Piecewise-constant hazard curve bootstrapped from CDS par spreads
    (2026-06 Phase 1: real sequential bootstrap via curves.hazard — the old
    body returned the s/(1-R) credit-triangle approximation per tenor).
    Falls back to the credit triangle only when no discount curve is given.
    """
    from curves.hazard import bootstrap_hazard_curve, hazard_curve_from_corp_spreads
    if r_curve is not None:
        hc = bootstrap_hazard_curve(tenors, spreads, r_curve, recovery, freq)
    else:
        hc = hazard_curve_from_corp_spreads(tenors, spreads, recovery)
    return dict(tenors=list(tenors), hazards=list(hc.hazards),
                survival=[hc.survival(t) for t in tenors], curve=hc)


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


def cds_curve(notional: float, spread: float, T: float, freq: int,
              hazard_curve, disc_curve, recovery: float | None = None,
              buy_protection: bool = True) -> dict:
    """
    CDS priced off a bootstrapped HazardCurve and a YieldCurve (Phase 1).
    Premium leg includes half-period accrual-on-default; protection leg
    integrates (1-R)·P(t)·dQ(t). Same leg model as the bootstrap, so a CDS
    quoted at its bootstrap spread reprices to zero NPV exactly.
    """
    from curves.hazard import cds_legs
    legs = cds_legs(spread, T, freq, hazard_curve, disc_curve, recovery)
    premium_pv = notional * legs["premium_pv"]
    protection_pv = notional * legs["protection_pv"]
    npv = (protection_pv - premium_pv) if buy_protection else (premium_pv - protection_pv)
    dv01 = notional * legs["risky_annuity"] / 10000
    return dict(npv=npv, fair_spread=legs["fair_spread"],
                premium_pv=premium_pv, protection_pv=protection_pv,
                risky_annuity=legs["risky_annuity"], dv01=dv01,
                risky_duration=legs["risky_annuity"],
                survival_at_maturity=hazard_curve.survival(T))


def risky_bond(face: float, coupon: float, T: float, freq: int,
               disc_curve, hazard_curve, recovery: float | None = None) -> dict:
    """
    Credit-risky fixed-coupon bond (Phase 1): coupons and principal weighted by
    survival, plus recovery on face paid at default. Links the bond stack to the
    credit stack — previously bonds were discounted with no default risk and
    spreads existed only as output metrics.
    """
    recovery = hazard_curve.recovery if recovery is None else recovery
    dt = 1.0 / freq
    n = int(round(T * freq))
    cpn = face * coupon / freq

    pv_coupons = sum(cpn * disc_curve.discount(i * dt) * hazard_curve.survival(i * dt)
                     for i in range(1, n + 1))
    pv_principal = face * disc_curve.discount(T) * hazard_curve.survival(T)

    m = max(1, int(round(T * 52)))
    grid = np.linspace(0.0, T, m + 1)
    pv_recovery = sum(recovery * face
                      * disc_curve.discount(0.5 * (t0 + t1))
                      * (hazard_curve.survival(t0) - hazard_curve.survival(t1))
                      for t0, t1 in zip(grid[:-1], grid[1:]))

    price = pv_coupons + pv_principal + pv_recovery

    # risk-free reference and credit spread (flat z-spread over the curve)
    riskless = (sum(cpn * disc_curve.discount(i * dt) for i in range(1, n + 1))
                + face * disc_curve.discount(T))

    def _pv_at_zspread(z: float) -> float:
        return (sum(cpn * disc_curve.discount(i * dt) * np.exp(-z * i * dt)
                    for i in range(1, n + 1))
                + face * disc_curve.discount(T) * np.exp(-z * T))

    try:
        credit_zspread = brentq(lambda z: _pv_at_zspread(z) - price, -0.05, 5.0)
    except ValueError:
        credit_zspread = float("nan")

    # CS01: reprice with all hazards bumped +1bp
    from curves.hazard import HazardCurve as _HC
    bumped = _HC(hazard_curve.tenors, hazard_curve.hazards + 1e-4,
                 recovery=hazard_curve.recovery, label="bumped")
    bumped_price = (sum(cpn * disc_curve.discount(i * dt) * bumped.survival(i * dt)
                        for i in range(1, n + 1))
                    + face * disc_curve.discount(T) * bumped.survival(T)
                    + sum(recovery * face * disc_curve.discount(0.5 * (t0 + t1))
                          * (bumped.survival(t0) - bumped.survival(t1))
                          for t0, t1 in zip(grid[:-1], grid[1:])))

    return dict(price=price, clean_price=price, dirty_price=price, accrued_interest=0.0,
                pv_coupons=pv_coupons, pv_principal=pv_principal, pv_recovery=pv_recovery,
                riskless_price=riskless, credit_spread=credit_zspread,
                cs01=bumped_price - price,
                survival_at_maturity=hazard_curve.survival(T),
                expected_loss=riskless - price)


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
# ISDA CDS Standard Model (fixed coupon + upfront)
# ─────────────────────────────────────────────────────────

def isda_cds_legs(hazard: float, coupon: float, T: float, freq: int, r: float,
                  recovery: float = 0.4) -> dict:
    """ISDA-style flat-hazard CDS legs with accrual-on-default.

    RPV01 = Σ Δt·df·Q + ½Σ Δt·df·ΔQ (premium accrued to the default date);
    protection PV = (1-R)·∫ df dPD. Returns RPV01, protection PV and par spread.
    """
    dt = 1.0 / freq
    times = [i * dt for i in range(1, int(round(T * freq)) + 1)]
    rpv01 = 0.0
    _prev_t, prev_Q = 0.0, 1.0
    for t in times:
        Q = survival_prob(t, hazard)
        df = np.exp(-r * t)
        rpv01 += dt * df * Q + 0.5 * dt * df * (prev_Q - Q)   # coupon + accrual
        _prev_t, prev_Q = t, Q
    # protection leg on a fine grid
    dti = min(dt, 0.02)
    grid = np.arange(dti, T + dti / 2, dti)
    Qg = np.exp(-hazard * grid)
    Qg_prev = np.exp(-hazard * (grid - dti))
    prot = (1 - recovery) * np.sum(np.exp(-r * (grid - dti / 2)) * (Qg_prev - Qg))
    par = prot / rpv01 if rpv01 > 0 else float("nan")
    return dict(rpv01=rpv01, protection_pv=prot, par_spread=par,
                coupon_pv=coupon * rpv01)


def cds_upfront(notional: float, coupon: float, quoted_spread: float, T: float,
                freq: int, r: float, recovery: float = 0.4) -> dict:
    """ISDA standard model: convert a quoted (par) spread to the clean upfront on
    a fixed-coupon contract. Upfront = (par_spread - coupon)·RPV01·notional, with
    the flat hazard calibrated so the model par spread matches the quote."""
    h = isda_flat_hazard(quoted_spread, T, freq, r, recovery)
    legs = isda_cds_legs(h, coupon, T, freq, r, recovery)
    upfront = (legs["par_spread"] - coupon) * legs["rpv01"] * notional
    return dict(upfront=upfront, points_upfront=upfront / notional,
                par_spread=legs["par_spread"], rpv01=legs["rpv01"],
                hazard=h, protection_pv=legs["protection_pv"] * notional)


def isda_flat_hazard(quoted_spread: float, T: float, freq: int, r: float,
                     recovery: float = 0.4) -> float:
    """Flat hazard whose ISDA par spread equals the quoted spread."""
    def eq(h):
        return isda_cds_legs(h, 0.0, T, freq, r, recovery)["par_spread"] - quoted_spread
    try:
        return brentq(eq, 1e-7, 5.0)
    except ValueError:
        return quoted_spread / (1 - recovery)


def cds_spread_from_upfront(notional: float, coupon: float, points_upfront: float,
                            T: float, freq: int, r: float, recovery: float = 0.4) -> float:
    """Inverse: recover the quoted par spread from the clean points-upfront."""
    def eq(s):
        return cds_upfront(notional, coupon, s, T, freq, r, recovery)["points_upfront"] - points_upfront
    return brentq(eq, 1e-7, 5.0)


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


# ─────────────────────────────────────────────────────────
# Asset swap (par-par) — Этап 5
# ─────────────────────────────────────────────────────────

def asset_swap_parpar(face: float, coupon: float, T: float, freq: int,
                      market_price: float, r: float) -> dict:
    """Par-par asset swap spread.

    Инвестор покупает бонд по грязной цене P, входит в своп: платит купоны
    бонда, получает плавающую + спред s на номинал par=face. Пакет стоит par.
    Спред s (десятичная ставка) = (V* − P) / (face · A), где V* — цена бонда
    по risk-free (своп) кривой, A — per-unit аннуитет плавающей ноги.
    Recovery не входит: это risk-free-vs-market спред, не hazard-модель.
    """
    dt = 1.0 / freq
    times = [i * dt for i in range(1, int(round(T * freq)) + 1)]
    annuity = sum(dt * np.exp(-r * t) for t in times)      # per-unit (на 1 par)

    # цена бонда по risk-free кривой (плоская r) — «справедливая» без кредита
    riskfree_value = sum(face * coupon * dt * np.exp(-r * t) for t in times)
    riskfree_value += face * np.exp(-r * T)

    # s — десятичная ставка на номинал par=face: делим на face·A
    asw_spread = ((riskfree_value - market_price) / (face * annuity)
                  if annuity > 0 else float("nan"))
    return dict(
        asset_swap_spread=asw_spread,                      # десятичная, scale-invariant
        asset_swap_spread_bp=asw_spread * 10000,
        riskfree_value=riskfree_value, market_price=market_price,
        annuity=annuity, npv=riskfree_value - market_price,
        value=asw_spread * 10000,
    )


# ─────────────────────────────────────────────────────────
# CDS Index (homogeneous pool) — Этап 5
# ─────────────────────────────────────────────────────────

def cds_index(notional: float, index_spread: float, coupon: float, T: float,
              freq: int, r: float, recovery: float = 0.4,
              n_names: int = 125, buy_protection: bool = True) -> dict:
    """CDS index на гомогенном пуле (iTraxx/CDX-стиль).

    Плоский hazard из котируемого индекс-спреда (ISDA-стиль), затем клин-
    апфронт на фиксированном купоне (100/500bp) = (par − coupon)·RPV01.
    Возвращает fair spread, RPV01, upfront, protection/premium PV.
    """
    h = isda_flat_hazard(index_spread, T, freq, r, recovery)
    legs = isda_cds_legs(h, coupon, T, freq, r, recovery)
    upfront = (legs["par_spread"] - coupon) * legs["rpv01"] * notional
    sign = 1.0 if buy_protection else -1.0
    return dict(
        fair_spread=legs["par_spread"], hazard=h, rpv01=legs["rpv01"],
        upfront=sign * upfront, points_upfront=sign * upfront / notional,
        protection_pv=legs["protection_pv"] * notional,
        premium_pv=coupon * legs["rpv01"] * notional,
        n_names=n_names, index_dv01=notional * legs["rpv01"] / 10000,
        npv=sign * upfront, value=sign * upfront,
    )


# ─────────────────────────────────────────────────────────
# CDS Index Option — Этап 5
# ─────────────────────────────────────────────────────────

def cds_index_option(notional: float, strike_spread: float, current_spread: float,
                     sigma: float, T_opt: float, T_index: float, freq: int,
                     r: float, recovery: float = 0.4,
                     option: str = "payer") -> dict:
    """Опцион на CDS-индекс (payer/receiver) — Black на форвардном спреде с
    ФОРВАРДНЫМ risky-annuity нумерером (как swaption).

    payer (право купить защиту по strike) = A_fwd·[F·N(d1) − K·N(d2)];
    receiver (право продать защиту) = A_fwd·[K·N(−d2) − F·N(−d1)], где
    A_fwd = RPV01(0,T_index) − RPV01(0,T_opt) — annuity периода T_opt→T_index
    (докупонные периоды до экспирации в underlying опциона не входят).
    Упрощения (→ Approximation): форвардный спред F≈current_spread (без
    convexity/carry), front-end protection (FEP) не добавляется, плоский
    hazard/дисконт.
    """
    from scipy.stats import norm as _norm

    numeric_inputs = (notional, strike_spread, current_spread, sigma, T_opt,
                      T_index, freq, r, recovery)
    if not all(np.isfinite(value) for value in numeric_inputs):
        raise ValueError("CDS index option inputs must be finite")
    if notional <= 0:
        raise ValueError("notional must be positive")
    if strike_spread <= 0 or current_spread <= 0:
        raise ValueError("strike_spread and current_spread must be positive")
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    if T_opt <= 0 or T_index <= T_opt:
        raise ValueError("require 0 < T_opt < T_index")
    if int(freq) != freq or freq <= 0:
        raise ValueError("freq must be a positive integer")
    if not 0 <= recovery < 1:
        raise ValueError("recovery must be in [0, 1)")
    if option not in {"payer", "receiver"}:
        raise ValueError("option must be 'payer' or 'receiver'")

    h = isda_flat_hazard(current_spread, T_index, freq, r, recovery)
    rpv01_index = isda_cds_legs(h, 0.0, T_index, freq, r, recovery)["rpv01"]
    rpv01_opt = (isda_cds_legs(h, 0.0, T_opt, freq, r, recovery)["rpv01"]
                 if T_opt > 0 else 0.0)
    annuity_fwd = max(rpv01_index - rpv01_opt, 0.0)      # forward risky annuity
    F, K = current_spread, strike_spread
    sv = sigma * np.sqrt(T_opt)
    d1 = (np.log(F / K) + 0.5 * sv * sv) / sv
    d2 = d1 - sv
    if option == "payer":
        unit = F * _norm.cdf(d1) - K * _norm.cdf(d2)
    else:
        unit = K * _norm.cdf(-d2) - F * _norm.cdf(-d1)
    price = notional * annuity_fwd * unit
    return dict(
        price=price, value=price, npv=price,
        rpv01=annuity_fwd, rpv01_index=rpv01_index, forward_spread=F, hazard=h,
        option=option, notional=notional,
    )
