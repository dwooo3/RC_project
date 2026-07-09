"""Batch-4 validation benchmarks: платёжные референсы для трёх последних
кандидатов — TARN, accumulator, арифметическая азиатка. Каждый тест —
точное разложение пейоффа в закрытые формы (стрип путов / форварды−путы /
Turnbull-Wakeman), а не property-check."""

from __future__ import annotations

import math

import pytest
from scipy.stats import norm

from models.black_scholes import bsm


def _put(S, K, T, r, sigma, q=0.0):
    return float(bsm(S, K, T, r, sigma, q, "put").price)


# ── TARN: target→∞ == стрип дисконтированных путов ───────


def test_tarn_uncapped_is_put_strip():
    """Купон max(K−S_i,0)/freq без кэпа (target→∞) — это в точности
    1/freq · Σ BSM-путов на каждую дату фиксинга."""
    from models.exotics_extra import tarn
    S0, K, T, freq, r, sigma, q = 100.0, 100.0, 2.0, 4, 0.05, 0.25, 0.0
    res = tarn(S0, K, T, freq, r, sigma, target=1e9, q=q, n_sims=150_000, seed=3)
    strip = sum(_put(S0, K, (i + 1) / freq, r, sigma, q)
                for i in range(int(T * freq))) / freq
    assert res["price"] == pytest.approx(strip, rel=0.02), (
        f"TARN {res['price']:.4f} vs put strip {strip:.4f}")


def test_tarn_capped_below_uncapped_and_target():
    """Кэп режет купоны: value(target) <= min(value(∞), PV(target))."""
    from models.exotics_extra import tarn
    S0, K, T, freq, r, sigma = 100.0, 100.0, 2.0, 4, 0.05, 0.25
    capped = tarn(S0, K, T, freq, r, sigma, target=0.05, n_sims=60_000, seed=3)
    uncapped = tarn(S0, K, T, freq, r, sigma, target=1e9, n_sims=60_000, seed=3)
    assert capped["price"] <= uncapped["price"] + 1e-9
    assert capped["price"] <= 0.05 + 1e-9          # нельзя получить больше таргета


# ── Accumulator: barrier→∞ == форварды − путы ────────────


def test_accumulator_no_barrier_is_forwards_minus_puts():
    """qty·(S−K) + qty·(S−K)·1{S<K} на фиксинг ⇒
    PV = Σ qty·[S0e^{−qt} − Ke^{−rt} − put(t)] точно (E[(S−K)1{S<K}] = −put)."""
    from models.exotics_extra import accumulator
    S0, K, T, freq, r, sigma, q, qty = 100.0, 95.0, 1.0, 12, 0.05, 0.3, 0.01, 1.0
    res = accumulator(S0, K, 1e9, T, freq, r, sigma, q=q, qty=qty,
                      n_sims=200_000, seed=5)
    ref = sum(qty * (S0 * math.exp(-q * t) - K * math.exp(-r * t)
                     - _put(S0, K, t, r, sigma, q))
              for t in [(i + 1) / freq for i in range(int(T * freq))])
    # пейофф с неограниченной дисперсией — критерий по доверительному интервалу
    assert abs(res["price"] - ref) < 3.0 * res["stderr"], (
        f"accumulator {res['price']:.3f} ± {res['stderr']:.3f} vs "
        f"forwards−puts {ref:.3f}")


def test_accumulator_knockout_cheapens():
    from models.exotics_extra import accumulator
    S0, K, T, freq, r, sigma = 100.0, 95.0, 1.0, 12, 0.05, 0.3
    with_ko = accumulator(S0, K, 110.0, T, freq, r, sigma, n_sims=60_000, seed=5)
    no_ko = accumulator(S0, K, 1e9, T, freq, r, sigma, n_sims=60_000, seed=5)
    assert with_ko["price"] < no_ko["price"], "KO режет выгодные высокие сценарии"


# ── Asian arithmetic: Turnbull-Wakeman + AM-GM ───────────


def _turnbull_wakeman(S0, K, T, r, sigma, q, n):
    """Независимая реализация TW-аппроксимации (моменты среднего, лог-нормаль)."""
    ts = [(i + 1) * T / n for i in range(n)]
    b = r - q
    m1 = sum(S0 * math.exp(b * t) for t in ts) / n
    m2 = 0.0
    for ti in ts:
        for tj in ts:
            m2 += S0 ** 2 * math.exp(b * (ti + tj) + sigma ** 2 * min(ti, tj))
    m2 /= n ** 2
    sig_a = math.sqrt(max(math.log(m2 / m1 ** 2), 1e-12) / T)
    d1 = (math.log(m1 / K) + sig_a ** 2 * T / 2) / (sig_a * math.sqrt(T))
    d2 = d1 - sig_a * math.sqrt(T)
    return math.exp(-r * T) * (m1 * norm.cdf(d1) - K * norm.cdf(d2))


def test_arithmetic_asian_matches_turnbull_wakeman():
    from instruments.asian import arithmetic_asian
    S0, K, T, r, sigma, q, n = 100.0, 100.0, 1.0, 0.05, 0.25, 0.0, 12
    res = arithmetic_asian(S0, K, T, r, sigma, q, n, "call", 200_000)
    tw = _turnbull_wakeman(S0, K, T, r, sigma, q, n)
    assert res["price"] == pytest.approx(tw, rel=0.015), (
        f"arithmetic MC {res['price']:.4f} vs Turnbull-Wakeman {tw:.4f}")


def test_arithmetic_asian_geq_geometric():
    """AM-GM: среднее арифметическое ≥ геометрического ⇒ колл дороже."""
    from instruments.asian import arithmetic_asian, geometric_asian_discrete
    S0, K, T, r, sigma, q, n = 100.0, 100.0, 1.0, 0.05, 0.25, 0.0, 12
    arith = arithmetic_asian(S0, K, T, r, sigma, q, n, "call", 120_000)
    geo = geometric_asian_discrete(S0, K, T, r, sigma, q, n, "call")
    assert arith["price"] >= geo["price"] - 2 * arith.get("stderr", 0.05)
