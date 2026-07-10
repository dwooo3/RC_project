"""Batch-5 validation benchmarks: DCF-обвязка (money market / futures /
кастомные облигации) через точные тождества + Prototype-пул против
референсов (LSM==CRR, Heston-Euler==CF, rainbow MC==Stulz, callable
no-call==straight, phoenix-вырождения)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from curves.yield_curve import YieldCurve
from models.black_scholes import bsm

FLAT = YieldCurve.flat(0.10)


# ── DCF-обвязка: точные тождества ────────────────────────


def test_custom_bond_equals_fixed_bond():
    """custom_bond на кэшфлоу обычного бонда == fixed-rate bond движок."""
    from instruments.fixed_income import custom_bond, fixed_bond
    face, coupon, T, freq = 1000.0, 0.08, 5.0, 2
    cfs = [((i + 1) / freq, face * coupon / freq) for i in range(int(T * freq))]
    cfs[-1] = (T, cfs[-1][1] + face)
    custom = custom_bond(cfs, FLAT, freq)
    fixed = fixed_bond(face, coupon, T, freq, FLAT)
    assert custom["price"] == pytest.approx(fixed["dirty_price"], rel=1e-9)


def test_step_bond_flat_steps_is_fixed_bond():
    """Ступенчатый бонд с одинаковыми ступенями == обычный фикс."""
    from instruments.fixed_income import fixed_bond, step_bond
    face, T, freq, c = 1000.0, 6.0, 2, 0.07
    stepped = step_bond(face, [(0.0, c), (3.0, c)], T, freq, FLAT)
    fixed = fixed_bond(face, c, T, freq, FLAT)
    assert stepped["price"] == pytest.approx(fixed["dirty_price"], rel=1e-9)


def test_amortizing_conserves_principal():
    """Кэшфлоу линейной амортизации: Σ(cf − проценты) == номинал точно, а цена
    == независимое дисконтирование кэшфлоу на той же кривой."""
    from instruments.fixed_income import amortizing_bond
    face, coupon, T, freq = 1000.0, 0.08, 4.0, 2
    res = amortizing_bond(face, coupon, T, freq, FLAT, amort_type="linear")
    cfs = res["cash_flows"]
    # проценты за период i: coupon/freq * остаток; восстановим principal-часть
    n, dt = int(T * freq), 1.0 / freq
    outstanding, principal_total = face, 0.0
    for _, amt in cfs:
        interest = outstanding * coupon * dt
        principal_total += amt - interest
        outstanding -= face / n
    assert principal_total == pytest.approx(face, rel=1e-9)
    ref = sum(a * FLAT.discount(t) for t, a in cfs)
    assert res["price"] == pytest.approx(ref, rel=1e-9)


def test_perpetual_is_coupon_over_yield():
    """Консоль: PV == C/y точно на флэт-кривой (годовой купон)."""
    from instruments.fixed_income import perpetual_bond
    face, coupon = 1000.0, 0.09
    curve = YieldCurve.flat(math.log(1.09))        # continuous == ln(1+annual)
    res = perpetual_bond(face, coupon, curve, freq=1)
    assert res["price"] == pytest.approx(face * coupon / res["ytm"], rel=1e-12)
    assert res["ytm"] == pytest.approx(0.09, rel=1e-3)   # par(30y) ≈ уровень кривой


def test_deposit_zero_rate_curve_returns_maturity_value():
    from instruments.fixed_income import mm_deposit
    zero = YieldCurve.flat(1e-6)
    res = mm_deposit(1_000_000, 0.12, 0.5, zero)
    assert res["npv"] == pytest.approx(1_000_000 * 1.06, rel=1e-4)
    assert res["maturity_value"] == pytest.approx(1_060_000, rel=1e-12)


def test_tbill_yield_identities():
    """BEY == (F/P−1)/T и MMY == (F−P)/(P·T) — прямые определения."""
    from instruments.fixed_income import treasury_bill
    face, d, T = 1000.0, 0.09, 0.25
    res = treasury_bill(face, d, T)
    P = face * (1 - d * T)
    assert res["price"] == pytest.approx(P, rel=1e-12)
    assert res["bey"] == pytest.approx((face / P - 1) / T, rel=1e-9)


def test_commercial_paper_same_discount_convention():
    from instruments.fixed_income import commercial_paper, treasury_bill
    face, d, T = 1000.0, 0.11, 0.25
    cp = commercial_paper(face, d, T)
    tb = treasury_bill(face, d, T)
    assert cp["price"] == pytest.approx(tb["price"], rel=1e-12)


def test_repo_cash_and_carry_identity():
    """Форвард == spot·(1+r·T) − купоны; carry == купоны − финансирование."""
    from instruments.fixed_income import repo
    res = repo(102.0, 0.08, 0.5, coupon_income=3.5)
    assert res["forward_price"] == pytest.approx(102.0 * 1.04 - 3.5, rel=1e-12)
    assert res["carry"] == pytest.approx(3.5 - 102.0 * 0.08 * 0.5, rel=1e-12)


def test_stir_future_price_and_dv01():
    from instruments.fixed_income import stir_future
    res = stir_future(0.10, 1_000_000, 0.25)
    assert res["price"] == pytest.approx(90.0, rel=1e-12)
    assert res["dv01"] == pytest.approx(25.0, rel=1e-12)   # N·τ·1bp


def test_bond_future_invoice_and_ctd():
    """Invoice == futures·CF + accrued; CTD = минимальный net basis."""
    from instruments.fixed_income import bond_future
    cheap = {"name": "A", "clean_price": 98.0, "accrued": 1.0,
             "conversion_factor": 0.92, "coupon_income": 0.0, "dv01": 0.08}
    rich = {"name": "B", "clean_price": 105.0, "accrued": 1.0,
            "conversion_factor": 0.90, "coupon_income": 0.0, "dv01": 0.09}
    res = bond_future([cheap, rich], futures_price=106.0, repo_rate=0.08,
                      T_delivery=0.25)
    assert res["ctd"] == "A"
    assert res["invoice_price"] == pytest.approx(106.0 * 0.92 + 1.0, rel=1e-12)
    # net basis == forward − futures·CF, независимое вычисление для CTD
    fwd = 99.0 * (1 + 0.08 * 0.25)
    assert res["net_basis"] == pytest.approx(fwd - 106.0 * 0.92, rel=1e-9)


def test_swaption_black_formula_reference():
    """Black-76 свопцион == аннуитет · Black(F=пар-ставка) — независимая формула."""
    from instruments.fixed_income import swaption as swaption_fn
    from scipy.stats import norm as N
    notional, K, To, Ts, freq, sig = 1e6, 0.10, 1.0, 5.0, 2, 0.2
    res = swaption_fn(notional, K, To, Ts, freq, FLAT, sig, "payer")
    dt = 1.0 / freq
    pay_times = [To + (i + 1) * dt for i in range(int(Ts * freq))]
    annuity = sum(dt * FLAT.discount(t) for t in pay_times)
    F = (FLAT.discount(To) - FLAT.discount(To + Ts)) / annuity
    d1 = (math.log(F / K) + sig ** 2 * To / 2) / (sig * math.sqrt(To))
    d2 = d1 - sig * math.sqrt(To)
    ref = notional * annuity * (F * N.cdf(d1) - K * N.cdf(d2))   # аннуитет-нумерер
    assert res["price"] == pytest.approx(ref, rel=1e-9)


def test_fra_equals_forward_discounted():
    """FRA == N·(fwd−K)·τ·df(T2), fwd из дисконтов — независимое вычисление."""
    from instruments.fixed_income import fra as fra_fn
    notional, K, T1, T2 = 1e6, 0.10, 1.0, 1.5
    res = fra_fn(notional, K, T1, T2, FLAT)
    tau = T2 - T1
    fwd = (FLAT.discount(T1) / FLAT.discount(T2) - 1) / tau
    ref = notional * (fwd - K) * tau * FLAT.discount(T2)
    assert res["npv"] == pytest.approx(ref, rel=1e-9)


def test_garch_stationary_longrun_variance():
    """GARCH(1,1): долгосрочная дисперсия == ω/(1−α−β) точно."""
    from models.garch import GARCH11
    omega, alpha, beta = 4e-6, 0.08, 0.90
    lr = omega / (1 - alpha - beta)
    g = GARCH11(omega=omega, alpha=alpha, beta=beta)
    path = g.forecast(current_var=lr, horizon=50)
    assert float(path[-1]) == pytest.approx(lr, rel=1e-9), (
        "на длинном горизонте E[σ²] == ω/(1−α−β)")
    far = g.forecast(current_var=4 * lr, horizon=2000)
    assert float(far[-1]) == pytest.approx(lr, rel=1e-3)


# ── Prototype-пул против референсов ──────────────────────


def test_lsm_matches_crr_american_put():
    """Longstaff-Schwartz == CRR(2000) American put в пределах MC-шума."""
    from models.monte_carlo import lsm
    from models.trees import _crr_price_only
    S, K, T, r, sigma = 100.0, 105.0, 1.0, 0.06, 0.25
    ref = _crr_price_only(S, K, T, r, sigma, 0.0, 2000, "put", "american")
    res = lsm(S, K, T, r, sigma, n_sims=100_000, steps=50, opt="put", seed=11)
    assert abs(res["price"] - ref) < max(3 * res.get("stderr", 0.05), 0.10), (
        f"LSM {res['price']:.4f} vs CRR {ref:.4f}")


def test_heston_euler_mc_matches_cf():
    """Euler-reflection MC == Heston CF (медленнее QE, но обязан сходиться)."""
    from models.heston import heston_price
    from models.monte_carlo import heston_mc_price
    S, K, T, r, q = 100.0, 100.0, 1.0, 0.05, 0.0
    v0, kappa, theta, xi, rho = 0.04, 2.0, 0.04, 0.3, -0.5
    cf = heston_price(S, K, T, r, q, v0, kappa, theta, xi, rho, "call")["price"]
    mc = heston_mc_price(lambda p: np.maximum(p[:, -1] - K, 0.0),
                         S, v0, r, q, kappa, theta, xi, rho, T,
                         steps=200, n_sims=80_000, seed=13, scheme="euler")
    assert mc["price"] == pytest.approx(cf, rel=0.025)


def test_rainbow_mc_matches_stulz():
    """MC best-of-2 == точная формула Stulz (движок n=2 идёт closed-form —
    сверяем внутренний MC на тех же параметрах)."""
    from instruments.multi_asset import _best_of_2_cash, _rainbow_mc
    S = [100.0, 95.0]
    sig = [0.2, 0.3]
    rho = 0.3
    corr = np.array([[1.0, rho], [rho, 1.0]])
    exact = _best_of_2_cash(S[0], S[1], 90.0, 1.0, 0.05, sig[0], sig[1], rho)["price"]
    mc = _rainbow_mc(S, 90.0, 1.0, 0.05, sig, corr, [0.0, 0.0], "best",
                     n_sims=150_000)
    assert abs(mc["price"] - exact) < 3 * mc["stderr"] + 0.05, (
        f"rainbow MC {mc['price']:.3f} vs Stulz {exact:.3f}")


def test_callable_no_call_equals_straight():
    """Колл-цена → ∞ (не исполняется) ⇒ callable == обычный бонд."""
    from instruments.fixed_income import callable_bond, fixed_bond
    face, coupon, T, freq = 1000.0, 0.08, 5.0, 2
    res = callable_bond(face, coupon, T, freq, FLAT, sigma=0.15,
                        call_price=1e9, call_start=1.0, option="callable")
    straight = fixed_bond(face, coupon, T, freq, FLAT)
    assert res["price"] == pytest.approx(straight["dirty_price"], rel=2e-3)
    assert abs(res.get("option_value", 0.0)) < straight["dirty_price"] * 2e-3


def test_callable_call_reduces_price():
    from instruments.fixed_income import callable_bond, fixed_bond
    face, coupon, T, freq = 1000.0, 0.12, 5.0, 2      # премиальный бонд — колл дорог
    res = callable_bond(face, coupon, T, freq, FLAT, sigma=0.15,
                        call_price=face, call_start=1.0, option="callable")
    straight = fixed_bond(face, coupon, T, freq, FLAT)
    assert res["price"] < straight["dirty_price"]


def test_phoenix_degenerate_zero_coupon_high_barriers():
    """Автоколл-барьер → ∞, KI → 0, купон 0 ⇒ PV == 100%·df(T) точно
    (никогда не коллится, капитал не под риском, купонов нет)."""
    from instruments.structured.phoenix import phoenix
    r, T = 0.05, 3.0
    res = phoenix(100.0, r, 0.0, 0.2, T, obs_dates=[1.0, 2.0, 3.0],
                  autocall_barrier=1e9, coupon_barrier=1e9, ki_barrier=1e-9,
                  coupon_rate=0.0, n_sims=20_000, steps=60, seed=17)
    assert res["price"] == pytest.approx(math.exp(-r * T), rel=1e-3)


def test_phoenix_instant_autocall():
    """Автоколл-барьер 0 ⇒ коллится на первой дате: PV == (100% + купон)·df(t1)."""
    from instruments.structured.phoenix import phoenix
    r = 0.05
    res = phoenix(100.0, r, 0.0, 0.2, 3.0, obs_dates=[1.0, 2.0, 3.0],
                  autocall_barrier=1e-9, coupon_barrier=1e-9, ki_barrier=1e-9,
                  coupon_rate=0.10, n_sims=20_000, steps=60, seed=17)
    assert res["price"] == pytest.approx(1.10 * math.exp(-r), rel=1e-3)
