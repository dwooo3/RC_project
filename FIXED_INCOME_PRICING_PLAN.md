# Fixed Income Pricing — Implementation Plan

**Источник:** ТЗ «Модуль прайсинга Fixed Income» (bond + связанные инструменты).
**Дата:** 2026-06-05
**Принцип:** расширять существующие движки до рыночной практики, не ломая текущие;
каждый инструмент проходит цепочку engine → registry → PricingService → catalogue →
portfolio dispatch (DV01/key-rate/spread exposures) → UI detail-экран.

---

## 1. Текущее состояние vs ТЗ (gap-матрица)

Движки в `instruments/fixed_income.py`: `zcb`, `fixed_bond` (+ schedule/BDC/settlement
инфраструктура), `frn`, `fra`, `irs`, `ois`, `basis_swap`, `caplet`, `cap_floor`,
`collar`, `swaption`, `bond_option`, `cms_spread_option`. OFZ-обёртка `price_ofz`.

| ТЗ | Есть | Нет (добавить) |
|---|---|---|
| 1.1 Fixed bond | clean/dirty/accrued, YTM, Mac/Mod dur, convexity, DV01, Z-spread | **YTC, YTP, YTW, Effective Dur, Key-Rate Dur, PV01/BPV алиасы, G/I-spread, ASW, OAS** |
| 1.2 FRN | price, DV01, spread_pv, duration (par-reset) | **clean/dirty/accrued, Discount Margin, Yield, Spread-DV01 vs IR-DV01, Eff Dur** |
| 1.3 Zero-coupon | price, YTM, duration, convexity, DV01 | ✅ (привести к единому контракту) |
| 1.4 Inflation-linked | — | **весь: indexed principal, real yield, real DV01, inflation DV01** |
| 1.5 Amortizing | — | **весь: график амортизации, метрики** |
| 1.6 Step-Up/Down | — | **весь: график меняющегося купона** |
| 2. Money Market (Deposit/CP/T-Bill) | — | **весь: discount yield, MM yield, BEY, NPV, DV01** |
| 3. Repo / Reverse Repo | — | **весь: repo rate, forward price, carry, funding DV01** |
| 4. Bond Futures / STIR | `bond_option` частично | **весь: futures price, invoice, CTD, hedge ratio; STIR** |
| 5. Spread analytics | Z-spread | **G/I-spread, ASW, Discount Margin, OAS** |
| 6. Единый набор риск-метрик | частично | **унифицировать по всем инструментам** |

---

## 2. Единый контракт риск-метрик (§6 ТЗ)

Ввести доменный результат `domain/fixed_income.py: FixedIncomeResult` — каждый FI-прайсер
обязан его заполнять (None где неприменимо):

```text
npv, clean_price, dirty_price, accrued_interest, yield_,
mac_duration, mod_duration, effective_duration,
convexity, dv01, pv01, bpv,                       # pv01/bpv = алиасы dv01
key_rate_durations: dict[tenor -> KRD],
spreads: { g_spread, i_spread, z_spread, asw, discount_margin, oas },
ytc, ytp, ytw,                                    # для callable/putable/опционных
cashflows, cashflow_schedule,
model_id, warnings
```

`PricingService` уже оборачивает движок в governed-результат — добавим маппинг этих полей в
`raw`, а сводку (price/greeks) в `value` + exposures (DV01, key-rate buckets, spread) для
портфеля/факторного VaR.

---

## 3. Общие аналитические хелперы (переиспользуемые)

Реализовать один раз в `instruments/fixed_income_analytics.py` и применять ко всем бондам:

1. **Yield-солверы:** YTM (есть), **YTC/YTP** (к дате колла/пута по call/put price),
   **YTW = min(YTM, YTC, YTP)** по расписанию опционов.
2. **Effective Duration / Convexity:** bump кривой ±Δy, репрайс: `(P- − P+)/(2·P·Δy)`.
3. **Key-Rate Duration:** bump каждого узла кривой по очереди (бакеты 3M/1Y/2Y/5Y/10Y…),
   репрайс → вектор KRD; сумма ≈ effective duration.
4. **Spread analytics:**
   - **G-Spread** = YTM − интерполированная govt-доходность на тот же срок.
   - **I-Spread** = YTM − своп-ставка на тот же срок.
   - **Z-Spread** (есть) — параллельный сдвиг zero-кривой до match price.
   - **ASW (asset-swap spread)** — par/par asset swap.
   - **Discount Margin** (FRN) — solver спреда к проекционной кривой.
   - **OAS** — Z-spread с учётом опциональности (через короткоставочное дерево, см. §6 Phase FI-6).
5. **PV01/BPV** = DV01 (алиасы), плюс money-DV01 на номинал.

---

## 4. Новые/расширяемые движки (математика)

| Инструмент | Движок | Ключевая математика |
|---|---|---|
| Amortizing bond | `amortizing_bond` | график падающего номинала (linear/annuity/custom) → DCF |
| Step-up/down | `step_bond` | купон-вектор по периодам → DCF |
| Inflation-linked | `inflation_linked_bond` | indexed principal = face·(CPI_t/CPI_0); real vs nominal; нужна **inflation curve** |
| Perpetual | расширить `fixed_bond` | бесконечный аннуитет: price = coupon/y |
| Deposit | `mm_deposit` | NPV = notional·(1+r·τ)·disc; accrued |
| Commercial Paper | `commercial_paper` | discount yield, MM yield |
| Treasury Bill | `treasury_bill` | discount yield, BEY, price=face·(1−d·τ) |
| Repo / Reverse | `repo` | forward = (S+accrued)·(1+repo·τ) − coupon carry; funding DV01 |
| Bond Futures | `bond_future` | CTD-выбор (max implied repo / min net basis), invoice=futures·CF+accrued, hedge ratio = BPV_ctd/(CF·BPV_fut) |
| STIR Futures | `stir_future` | price=100−forward rate; DV01=notional·0.25·0.0001 |

Новые рыночные данные (тянет блок Market Data, см. `MARKET_DATA_FOR_PRICING.md`):
- **inflation curve / CPI fixings** (для linkers),
- **swap curve** (I-spread, ASW),
- **govt benchmark curve** (G-spread) — уже есть КБД,
- **repo curve** (repo/futures funding).

---

## 5. Фазовый план

**Phase FI-1 — Единый контракт + аналитика на существующих бондах**
- `FixedIncomeResult` + `fixed_income_analytics` (eff dur, key-rate dur, YTC/YTP/YTW, G/I-spread, ASW, PV01/BPV).
- Дополнить `fixed_bond`, `zcb` до контракта; FRN — clean/dirty/accrued + Discount Margin + spread/IR DV01.
- Portfolio dispatch: добавить key-rate exposures (бакеты) и spread-DV01.
- Тесты: KRD сумма ≈ eff dur; YTW ≤ YTM; spreads знак/монотонность.

**Phase FI-2 — Расширение семейства бондов**
- `amortizing_bond`, `step_bond`, `perpetual`, `inflation_linked_bond` (+ inflation curve stub).
- registry + service + catalogue + dispatch + UI поля.

**Phase FI-3 — Money Market**
- `mm_deposit`, `commercial_paper`, `treasury_bill` (discount/MM/BEY yields).

**Phase FI-4 — Repo**
- `repo` / reverse (forward price, carry, funding DV01).

**Phase FI-5 — Interest Rate Futures**
- `bond_future` (CTD, invoice, hedge ratio), `stir_future`.

**Phase FI-6 — Spread analytics + OAS**
- Полный spread-блок; OAS через короткоставочное дерево (Hull-White/BDT) для callable/putable.
- Callable/Putable bond поверх OAS-движка → YTC/YTP/YTW «вживую».

**Cross-cutting (в каждой фазе):** запись в `models/registry.py`, метод `PricingService.price_*`,
продукт в `app/panels/pricing_catalogue.py` (вкладка Fixed Income), ветка в `PortfolioService`
dispatch с корректными exposures, поля detail-экрана; тесты-санити (parity/bounds/monotonicity).

---

## 6. Новые поля/переменные (сводно)

- Bond input: `call_schedule`, `put_schedule`, `amort_schedule`, `coupon_schedule` (step),
  `index_ratio`/`base_cpi` (linker), `settlement_lag`, `day_count`, `bdc`, `redemption`.
- Output (см. §2 контракт): YTC/YTP/YTW, effective_duration, key_rate_durations,
  g_spread/i_spread/asw/discount_margin/oas, pv01/bpv, indexed_principal, real_yield.
- Money market: `discount_yield`, `mm_yield`, `bey`.
- Futures: `ctd`, `conversion_factor`, `invoice_price`, `net_basis`, `hedge_ratio`.
- Repo: `repo_rate`, `forward_price`, `carry`, `funding_dv01`.

---

## 7. Порядок и зависимости
1. FI-1 (контракт+аналитика) — фундамент, разблокирует единые метрики везде.
2. FI-2/FI-3/FI-4/FI-5 — независимы, параллелятся.
3. FI-6 (OAS) — после FI-1; нужен для callable/putable и точного YTW.
4. Inflation linker и swap-spread метрики зависят от соответствующих кривых в Market Data.

> Детальная калибровка/валидация против рыночных данных — отдельная фаза позже
> (по решению владельца), после готовности движков и интерфейса.
