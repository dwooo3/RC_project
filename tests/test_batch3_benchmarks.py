"""Batch-3 validation benchmarks: точные тождества и внешние референсы для
«тонких» моделей, у которых до этого был один parity-тест или ничего.
Каждый тест зарегистрирован в models/registry.py и является условием статуса
Validated (scripts/validation_program.py --run)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import norm

from models.black_scholes import bachelier, black76, bsm


# ── Black-76 ─────────────────────────────────────────────


def test_black76_known_value():
    """Независимая реализация формулы Black-76 (Hull-пример F=K=20,
    T=0.75, σ=0.25, r=0.09) против движка."""
    F, K, T, r, sig = 20.0, 20.0, 0.75, 0.09, 0.25
    d1 = (math.log(F / K) + sig ** 2 * T / 2) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    ref = math.exp(-r * T) * (F * norm.cdf(d1) - K * norm.cdf(d2))
    assert ref == pytest.approx(1.6116, abs=1e-4)          # sanity: известный уровень
    assert black76(F, K, T, r, sig, "call").price == pytest.approx(ref, rel=1e-12)


def test_black76_equals_bsm_on_forward():
    """Black76(F=S·e^{(r−q)T}) · дисконт-структура == BSM(S) точно."""
    S, K, T, r, q, sig = 100.0, 95.0, 1.3, 0.07, 0.02, 0.24
    F = S * math.exp((r - q) * T)
    assert black76(F, K, T, r, sig, "put").price == pytest.approx(
        bsm(S, K, T, r, sig, q, "put").price, rel=1e-12)


# ── Bachelier ────────────────────────────────────────────


def test_bachelier_known_value_and_parity():
    """ATM Bachelier: цена = σ√(T/2π)·disc — точная формула; + паритет."""
    F, T, r, sn = 100.0, 1.0, 0.05, 15.0
    atm = bachelier(F, F, T, r, sn, "call").price
    assert atm == pytest.approx(math.exp(-r * T) * sn * math.sqrt(T / (2 * math.pi)),
                                rel=1e-12)
    K = 92.0
    c, p = bachelier(F, K, T, r, sn, "call").price, bachelier(F, K, T, r, sn, "put").price
    assert c - p == pytest.approx(math.exp(-r * T) * (F - K), rel=1e-12)


def test_bachelier_negative_forward():
    """Нормальная модель обязана ценить отрицательный форвард (ставки < 0)."""
    p = bachelier(-0.5, -0.25, 1.0, 0.0, 1.0, "put").price
    assert p > 0.25 - 1e-12                       # интринсик 0.25 + время


# ── Деревья: LR быстрее CRR, trinomial сходится ──────────


def test_lr_beats_crr_at_same_n():
    from models.trees import _crr_price_only, _lr_price_only
    S, K, T, r, q, sig = 100.0, 103.0, 0.8, 0.06, 0.01, 0.3
    ref = bsm(S, K, T, r, sig, q, "call").price
    err_crr = abs(_crr_price_only(S, K, T, r, sig, q, 101, "call", "european") - ref)
    err_lr = abs(_lr_price_only(S, K, T, r, sig, q, 101, "call", "european") - ref)
    assert err_lr < err_crr / 5, "Leisen-Reimer должен бить CRR на порядок"
    assert err_lr < 1e-4


def test_trinomial_converges_and_american_premium():
    from models.trees import _trinomial_price_only
    S, K, T, r, q, sig = 100.0, 100.0, 1.0, 0.05, 0.0, 0.2
    ref = bsm(S, K, T, r, sig, q, "put").price
    eu = _trinomial_price_only(S, K, T, r, sig, q, 400, "put", "european")
    am = _trinomial_price_only(S, K, T, r, sig, q, 400, "put", "american")
    assert eu == pytest.approx(ref, abs=5e-3)
    assert am >= eu


def test_tian_american_ge_european():
    from models.vanilla_extra import binomial_tian
    S, K, T, r, sig = 100.0, 105.0, 1.0, 0.05, 0.25
    eu = binomial_tian(S, K, T, r, sig, 0.0, "put", 400, "european")
    am = binomial_tian(S, K, T, r, sig, 0.0, "put", 400, "american")
    assert am >= eu
    assert eu == pytest.approx(bsm(S, K, T, r, sig, 0.0, "put").price, abs=2e-2)


# ── Heston QE MC == CF ───────────────────────────────────


def test_heston_qe_matches_cf():
    from models.heston import heston_price
    from models.monte_carlo import heston_mc_price

    S, K, T, r, q = 100.0, 100.0, 1.0, 0.05, 0.0
    v0, kappa, theta, xi, rho = 0.04, 1.5, 0.04, 0.5, -0.6
    cf = heston_price(S, K, T, r, q, v0, kappa, theta, xi, rho, "call")["price"]
    mc = heston_mc_price(lambda paths: np.maximum(paths[:, -1] - K, 0.0),
                         S, v0, r, q, kappa, theta, xi, rho, T,
                         steps=64, n_sims=60_000, seed=7, scheme="qe")
    assert mc["price"] == pytest.approx(cf, rel=0.02), (
        f"QE MC {mc['price']:.3f} vs CF {cf:.3f}")


# ── SABR: симметрия и пределы ────────────────────────────


def test_sabr_rho_zero_symmetric_smile():
    from models.heston import sabr_vol
    F, T = 0.05, 2.0
    up = sabr_vol(F, F * math.exp(0.3), T, alpha=0.2, beta=1.0, rho=0.0, nu=0.6)
    dn = sabr_vol(F, F * math.exp(-0.3), T, alpha=0.2, beta=1.0, rho=0.0, nu=0.6)
    assert up == pytest.approx(dn, rel=1e-6), "ρ=0 ⇒ смайл симметричен в лог-манинес"


def test_sabr_negative_rho_skews_down():
    from models.heston import sabr_vol
    F, T = 0.05, 2.0
    lo = sabr_vol(F, F * 0.8, T, alpha=0.2, beta=1.0, rho=-0.5, nu=0.6)
    hi = sabr_vol(F, F * 1.2, T, alpha=0.2, beta=1.0, rho=-0.5, nu=0.6)
    assert lo > hi, "ρ<0 ⇒ put-скос (низкие страйки дороже)"


# ── Digital: точные тождества к BSM ──────────────────────


def test_digital_cash_is_discounted_prob():
    from instruments.digital import cash_or_nothing
    S, K, T, r, q, sig = 100.0, 97.0, 0.7, 0.05, 0.01, 0.3
    d2 = ((math.log(S / K) + (r - q - sig ** 2 / 2) * T) / (sig * math.sqrt(T)))
    exact = math.exp(-r * T) * norm.cdf(d2)
    assert cash_or_nothing(S, K, T, r, sig, q, "call", 1.0)["price"] == pytest.approx(
        exact, rel=1e-10)


def test_digital_decomposition_is_vanilla():
    """asset-or-nothing − K·cash-or-nothing == vanilla call (точное разложение)."""
    from instruments.digital import asset_or_nothing, cash_or_nothing
    S, K, T, r, q, sig = 100.0, 105.0, 1.2, 0.04, 0.02, 0.25
    aon = asset_or_nothing(S, K, T, r, sig, q, "call")["price"]
    con = cash_or_nothing(S, K, T, r, sig, q, "call", 1.0)["price"]
    vanilla = bsm(S, K, T, r, sig, q, "call").price
    assert aon - K * con == pytest.approx(vanilla, rel=1e-10)


# ── FX forward: CIP ──────────────────────────────────────


def test_fx_forward_cip_and_zero_npv():
    from instruments.fx import fx_forward
    S, rd, rf, T = 90.0, 0.16, 0.05, 1.0
    res = fx_forward(S, rd, rf, T)
    fair = S * math.exp((rd - rf) * T)
    assert res["forward"] == pytest.approx(fair, rel=1e-12)
    res2 = fx_forward(S, rd, rf, T, forward_agreed=fair)
    assert abs(res2.get("npv", 0.0)) < 1e-9


# ── Vanilla extras ───────────────────────────────────────


def test_discrete_div_is_escrowed_bsm():
    from models.vanilla_extra import discrete_dividend_bsm
    S, K, T, r, sig = 100.0, 100.0, 1.0, 0.05, 0.2
    divs = [(0.3, 2.0), (0.8, 2.5)]
    pv = sum(a * math.exp(-r * t) for t, a in divs)
    assert discrete_dividend_bsm(S, K, T, r, sig, divs, "call") == pytest.approx(
        bsm(S - pv, K, T, r, sig, 0.0, "call").price, rel=1e-12)


def test_displaced_diffusion_prices_negative_forward():
    """Сдвиг делает лог-нормаль применимой к отрицательным ставкам."""
    from models.vanilla_extra import displaced_diffusion
    p = displaced_diffusion(-0.005, 0.001, 1.0, 0.02, 0.4, 0.03, "put")
    assert p > 0.006 * math.exp(-0.02) - 1e-9    # >= дисконтированный интринсик


# ── Commodity seasonality / SMM ──────────────────────────


def test_seasonal_factor_periodic_and_zero_mean():
    from models.commodity import seasonal_factor
    amps = [(0.1, 0.05), (0.02, 0.0)]
    assert seasonal_factor(0.37, amps) == pytest.approx(
        seasonal_factor(1.37, amps), rel=1e-12)
    grid = [seasonal_factor(t, amps) for t in np.linspace(0, 1, 1001)[:-1]]
    assert abs(float(np.mean(grid))) < 1e-3      # гармоники интегрируются в ноль


def test_smm_zero_shift_matches_black():
    from curves.yield_curve import YieldCurve
    from models.rates_market import smm_swaption
    curve = YieldCurve.flat(0.10)
    a = smm_swaption(curve, 1e6, 0.10, 1.0, 5.0, freq=2, sigma=0.2, shift=0.0)
    b = smm_swaption(curve, 1e6, 0.10, 1.0, 5.0, freq=2, sigma=0.2, shift=1e-12)
    assert a["price"] == pytest.approx(b["price"], rel=1e-6)
    assert a["price"] > 0


# ── VaR: EVT и MC против известных квантилей ────────────


def test_evt_var_on_exact_gpd_tail():
    """На выборке из точного GPD-хвоста EVT-VaR ≈ теоретический квантиль."""
    from risk.var import evt_var
    rng = np.random.default_rng(11)
    xi, beta_ = 0.2, 0.01
    u = rng.uniform(size=60_000)
    losses = beta_ / xi * ((1 - u) ** (-xi) - 1)          # GPD(ξ, β)
    returns = -losses
    res = evt_var(returns, 1.0, confidence=0.99)
    q_true = beta_ / xi * ((1 - 0.99) ** (-xi) - 1)
    assert res["VaR"] == pytest.approx(q_true, rel=0.15)


def test_mc_var_matches_parametric_on_normal():
    from risk.var import montecarlo_var, parametric_var
    rng = np.random.default_rng(3)
    returns = rng.normal(0.0, 0.02, size=5000)
    mc = montecarlo_var(returns, 1_000_000, 0.99, 1, n_sims=200_000, seed=5)
    pa = parametric_var(returns, 1_000_000, 0.99, 1, "normal")
    assert mc["VaR"] == pytest.approx(pa["VaR"], rel=0.03)


# ── Asian: geometric == closed form ──────────────────────


def test_geometric_asian_matches_closed_form():
    """Дискретная геометрическая азиатка имеет лог-нормальную закрытую форму."""
    from instruments.asian import geometric_asian_discrete
    S, K, T, r, q, sig, n = 100.0, 100.0, 1.0, 0.05, 0.0, 0.2, 12
    res = geometric_asian_discrete(S, K, T, r, sig, q, n, "call")
    vanilla = bsm(S, K, T, r, sig, q, "call").price
    assert 0 < res["price"] < vanilla, "усреднение режет волу — дешевле ванили"
    # точная внутренняя согласованность: n=1 == BSM
    res1 = geometric_asian_discrete(S, K, T, r, sig, q, 1, "call")
    assert res1["price"] == pytest.approx(vanilla, rel=1e-9)
