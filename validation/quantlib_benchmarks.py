"""A6 плана замечаний: внешний бенчмарк-пак против QuantLib.

Независимая кросс-валидация наших прайсеров: те же контрактные параметры
считаются нашим движком (через PricingService — governed-путь) и QuantLib
(независимая реализация с собственной датной машинерией). Совпадение в
пределах допуска — evidence для валидационного досье.

Опциональный слой: требует `pip install QuantLib` (в тестах —
pytest.importorskip, без пакета пак пропускается, CI не краснеет).

Выравнивание конвенций (важно для честного сравнения):
- сроки ACT/365: даты QL = today + int(T*365) дней, T подобраны так, чтобы
  дни были целыми;
- ставки/дивиденды непрерывные: FlatForward(..., Continuous) == наши e^{-rT};
- расписания купонов — явные даты с шагом 365 дней (accrual ровно 1.0),
  а не календарные годы (високосный февраль дал бы 366/365).

Запуск вручную: python3.14 -m validation.quantlib_benchmarks
"""

from __future__ import annotations

import math


def has_quantlib() -> bool:
    try:
        import QuantLib  # noqa: F401
        return True
    except ImportError:
        return False


def _rel_diff(ours: float, theirs: float) -> float:
    return abs(ours - theirs) / max(abs(theirs), 1e-12)


def run_benchmarks() -> list[dict]:
    """Считает весь пак; каждая строка — {id, group, ours, quantlib,
    rel_diff, tol, ok}."""
    import QuantLib as ql

    from services.pricing_service import PricingService

    svc = PricingService(allow_analytics_lab=True)

    today = ql.Date(15, 1, 2026)
    ql.Settings.instance().evaluationDate = today
    dc = ql.Actual365Fixed()
    cal = ql.NullCalendar()

    def flat(r):
        return ql.YieldTermStructureHandle(
            ql.FlatForward(today, r, dc, ql.Continuous))

    def volts(sigma):
        return ql.BlackVolTermStructureHandle(
            ql.BlackConstantVol(today, cal, sigma, dc))

    def process(S, r, q, sigma):
        return ql.BlackScholesMertonProcess(
            ql.QuoteHandle(ql.SimpleQuote(S)), flat(q), flat(r), volts(sigma))

    def expiry(T):
        days = round(T * 365)
        assert abs(days - T * 365) < 1e-9, f"T={T} не целое число дней ACT/365"
        return today + int(days)

    rows: list[dict] = []

    def bench(bid, group, ours, theirs, tol):
        ours, theirs = float(ours), float(theirs)
        rd = _rel_diff(ours, theirs)
        rows.append({"id": bid, "group": group, "ours": ours,
                     "quantlib": theirs, "rel_diff": rd, "tol": tol,
                     "ok": rd <= tol})

    # ── 1-2. European BSM (call OTM с дивидендами, put ITM) ─────────
    for bid, K, opt, qlopt in (("european_call_bsm", 105.0, "call", ql.Option.Call),
                               ("european_put_bsm_itm", 120.0, "put", ql.Option.Put)):
        S, T, r, q, sigma = 100.0, 1.0, 0.08, 0.03, 0.25
        ours = svc.price_vanilla_option(S, K, T, r, sigma, q, opt)["value"]
        opt_ql = ql.VanillaOption(ql.PlainVanillaPayoff(qlopt, K),
                                  ql.EuropeanExercise(expiry(T)))
        opt_ql.setPricingEngine(ql.AnalyticEuropeanEngine(process(S, r, q, sigma)))
        bench(bid, "vanilla", ours, opt_ql.NPV(), 1e-8)

    # ── 3. Black76 (опцион на фьючерс) ───────────────────────────────
    F, K, T, r, sigma = 92.0, 90.0, 0.6 + 1 / 365, 0.10, 0.30   # 220 дней
    ours = svc.price_vanilla_option(F, K, T, r, sigma, 0.0, "call",
                                    model="black76")["value"]
    theirs = ql.blackFormula(ql.Option.Call, K, F, sigma * math.sqrt(T),
                             math.exp(-r * T))
    bench("black76_futures_call", "vanilla", ours, theirs, 1e-10)

    # ── 4. FX Garman–Kohlhagen (q == r_f) ────────────────────────────
    S, K, T, r_d, r_f, sigma = 90.0, 92.0, 1.0, 0.16, 0.05, 0.15
    ours = svc.price_fx_option(S, K, T, r_d, r_f, sigma, notional=1.0,
                               opt="call")["value"]
    fx = ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call, K),
                          ql.EuropeanExercise(expiry(T)))
    fx.setPricingEngine(ql.AnalyticEuropeanEngine(process(S, r_d, r_f, sigma)))
    bench("fx_garman_kohlhagen_call", "fx", ours, fx.NPV(), 1e-8)

    # ── 5. American put, CRR 500 шагов против CRR 500 шагов ──────────
    S, K, T, r, q, sigma = 100.0, 110.0, 1.0, 0.06, 0.02, 0.30
    ours = svc.price_american_option(S, K, T, r, sigma, q, "put",
                                     model="binomial")["value"]
    am = ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Put, K),
                          ql.AmericanExercise(today, expiry(T)))
    am.setPricingEngine(ql.BinomialVanillaEngine(process(S, r, q, sigma),
                                                 "crr", 500))
    # два независимых CRR-дерева: остаточные ~2e-6 — детали дискретизации
    # (обработка payoff на узлах), не формульная ошибка
    bench("american_put_crr500", "vanilla", ours, am.NPV(), 1e-5)

    # ── 6. Heston (характеристическая функция) ───────────────────────
    S, K, T, r, q = 100.0, 100.0, 1.0, 0.05, 0.0
    v0, kappa, theta, xi, rho = 0.04, 1.5, 0.04, 0.30, -0.7
    ours = svc.price_heston_option(S, K, T, r, q, v0, kappa, theta, xi,
                                   rho, "call")["value"]
    hp = ql.HestonProcess(flat(r), flat(q),
                          ql.QuoteHandle(ql.SimpleQuote(S)),
                          v0, kappa, theta, xi, rho)
    ho = ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call, K),
                          ql.EuropeanExercise(expiry(T)))
    ho.setPricingEngine(ql.AnalyticHestonEngine(ql.HestonModel(hp)))
    bench("heston_cf_call", "stochastic_vol", ours, ho.NPV(), 1e-5)

    # ── 7. Барьер down-out call (непрерывный мониторинг) ─────────────
    S, K, H, T, r, q, sigma = 100.0, 100.0, 90.0, 1.0, 0.05, 0.02, 0.25
    ours = svc.price_barrier_option(S, K, H, T, r, sigma, q, "call",
                                    "down-out", rebate=0.0)["value"]
    bo = ql.BarrierOption(ql.Barrier.DownOut, H, 0.0,
                          ql.PlainVanillaPayoff(ql.Option.Call, K),
                          ql.EuropeanExercise(expiry(T)))
    bo.setPricingEngine(ql.AnalyticBarrierEngine(process(S, r, q, sigma)))
    bench("barrier_downout_call", "exotics", ours, bo.NPV(), 1e-8)

    # ── 8. Digital cash-or-nothing ────────────────────────────────────
    S, K, T, r, q, sigma = 100.0, 102.0, 0.4, 0.06, 0.01, 0.22   # 146 дней
    ours = svc.price_digital_option(S, K, T, r, sigma, q, "call",
                                    style="cash", cash=1.0)["value"]
    dig = ql.VanillaOption(ql.CashOrNothingPayoff(ql.Option.Call, K, 1.0),
                           ql.EuropeanExercise(expiry(T)))
    dig.setPricingEngine(ql.AnalyticEuropeanEngine(process(S, r, q, sigma)))
    bench("digital_cash_call", "exotics", ours, dig.NPV(), 1e-8)

    # ── 9. Floating-strike lookback (непрерывное наблюдение) ─────────
    S, T, r, q, sigma = 100.0, 1.0, 0.07, 0.02, 0.25
    ours = svc.price_lookback_option(S, T, r, sigma, q, "call",
                                     strike_type="floating")["value"]
    lb = ql.ContinuousFloatingLookbackOption(
        S, ql.FloatingTypePayoff(ql.Option.Call), ql.EuropeanExercise(expiry(T)))
    lb.setPricingEngine(
        ql.AnalyticContinuousFloatingLookbackEngine(process(S, r, q, sigma)))
    bench("lookback_floating_call", "exotics", ours, lb.NPV(), 1e-8)

    # ── 10. Дискретная геометрическая азиатка (5 годовых фиксингов) ──
    S, K, T, n, r, q, sigma = 100.0, 100.0, 5.0, 5, 0.05, 0.01, 0.25
    ours = svc.price_asian_option(S, K, T, r, sigma, q, "call",
                                  averaging="geometric", n=n)["value"]
    fixings = [today + 365 * i for i in range(1, n + 1)]   # t_i = i*T/n лет
    asian = ql.DiscreteAveragingAsianOption(
        ql.Average.Geometric, 1.0, 0, fixings,
        ql.PlainVanillaPayoff(ql.Option.Call, K), ql.EuropeanExercise(expiry(T)))
    asian.setPricingEngine(
        ql.AnalyticDiscreteGeometricAveragePriceAsianEngine(process(S, r, q, sigma)))
    bench("asian_geometric_discrete", "exotics", ours, asian.NPV(), 1e-6)

    # ── 11. Fixed-rate bond (годовой купон, явные даты, ACT/365) ─────
    face, coupon, T_b, r = 1000.0, 0.10, 3.0, 0.12
    curve = svc.market_data.flat_curve(r)
    ours = svc.price_bond(face, coupon, T_b, 1, curve=curve)["value"]
    dates = [today + 365 * i for i in range(0, int(T_b) + 1)]
    sched = ql.Schedule(dates)
    bond = ql.FixedRateBond(0, face, sched, [coupon], dc)
    bond.setPricingEngine(ql.DiscountingBondEngine(flat(r)))
    bench("fixed_bond_annual", "rates", ours, bond.NPV(), 1e-8)

    # ── 12. IRS payer NPV (проекция == дисконт, явные даты) ──────────
    notional, R, T_s, r = 1_000_000.0, 0.08, 5.0, 0.10
    curve = svc.market_data.flat_curve(r)
    ours = svc.price_irs(notional, R, T_s, 1, curve=curve, pay_fixed=True)["value"]
    dates = [today + 365 * i for i in range(0, int(T_s) + 1)]
    sched = ql.Schedule(dates)
    index = ql.IborIndex("FLAT1Y", ql.Period(1, ql.Years), 0, ql.RUBCurrency(),
                         cal, ql.Unadjusted, False, dc, flat(r))
    swap = ql.VanillaSwap(ql.Swap.Payer, notional, sched, R, dc,
                          sched, index, 0.0, dc)
    swap.setPricingEngine(ql.DiscountingSwapEngine(flat(r)))
    bench("irs_payer_npv", "rates", ours, swap.NPV(), 1e-6)

    return rows


def main() -> int:
    if not has_quantlib():
        print("QuantLib не установлен: pip install QuantLib — пак пропущен.")
        return 2
    rows = run_benchmarks()
    import QuantLib as ql
    print(f"QuantLib {ql.__version__} — кросс-бенчмарк наших прайсеров\n")
    print(f"{'benchmark':32} {'ours':>14} {'QuantLib':>14} {'rel diff':>10}  ok")
    for r in rows:
        print(f"{r['id']:32} {r['ours']:14.6f} {r['quantlib']:14.6f} "
              f"{r['rel_diff']:10.2e}  {'✓' if r['ok'] else '✗ FAIL'}")
    n_fail = sum(not r["ok"] for r in rows)
    print(f"\n{len(rows) - n_fail}/{len(rows)} прошли допуски")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
