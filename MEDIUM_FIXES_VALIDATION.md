# MEDIUM-Severity Model Fixes — Validation

**Дата:** 2026-06-04
**Область:** MEDIUM-severity пункты из [MODEL_REVIEW_AND_RECOMMENDATIONS.md](MODEL_REVIEW_AND_RECOMMENDATIONS.md) §4
**Изменённый код:** `models/black_scholes.py`, `models/heston.py`, `models/monte_carlo.py`,
`instruments/fixed_income.py`, `instruments/digital.py`, `models/registry.py`
**Новые тесты:** `tests/test_medium_severity_fixes.py`
**Сохранены API:** все сигнатуры функций без изменений.

> **Метод:** каждый подпункт проверен численно (аналитика / конечные разности / Monte Carlo)
> **до** правок. Применён фикс только там, где отклонение подтверждено. Прогоны воспроизводимы
> (numpy 2.4, scipy 1.17).

---

## Сводка

| # | Пункт | Вердикт | Действие |
|---|---|---|---|
| 1a | BSM put delta at expiry | ✅ Баг | Исправлено |
| 1b | BSM volga scaling | ✅ Баг (×100) | Исправлено |
| 1c | BSM ultima formula | ✅ Баг (/σ vs /σ²) | Исправлено |
| 2 | Heston dividend-adjusted delta | ✅ Баг | Исправлено |
| 3 | Vasicek kappa=0 limit | ❌ **Ложно** | Не менялось (код верен) |
| 4 | MC control-variate expectation | ✅ Баг | Исправлено |
| 5 | Modified duration uses YTM | ✅ Баг | Исправлено |
| 6 | Digital put gamma sign | ✅ Баг | Исправлено |

**Применено 7 фиксов. Отклонён 1 ложный пункт (Vasicek).**

---

## 1a. BSM — put delta на экспирации ✅

**Файл:** [models/black_scholes.py](models/black_scholes.py), ветка `T <= 0`.

- **Было:** `g.delta = 1.0 if opt == "call" and S > K else 0.0` → для пута всегда 0.
- **Стало:** call → +1 если ITM; put → **−1** если ITM (S<K), иначе 0.
- **Проверка:** аналитический предел `bsm(...,T=1e-6,'put').delta` = −1.0000 для S=90 (ITM),
  −0.0 для S=110 (OTM). Граничное условие воспроизводится.

## 1b. BSM — масштабирование volga ✅

**Файл:** [models/black_scholes.py](models/black_scholes.py), `volga`.

- **Было:** `... / sigma / 100` (per 1%).
- **Стало:** `... / sigma / 10000` (per 1%², согласовано с vega «per 1%»).
- **Проверка:** конечная разность `d(vega_per1%)/dσ · 1%` = **0.000985**; новая volga = 0.000985
  (старая = 0.098501, т.е. в 100× больше). Vega уже задокументирована как «per 1% σ move», поэтому
  volga должна быть «per 1%²».

## 1c. BSM — формула ultima ✅

**Файл:** [models/black_scholes.py](models/black_scholes.py), `ultima`.

- **Было:** `-vega*100 / sigma * (...)` (деление на σ¹).
- **Стало:** `-vega*100 / sigma**2 * (...)` (σ²).
- **Проверка:** конечная разность `∂(raw volga)/∂σ` = **−182.69**; версия /σ² = −182.69 (точно),
  версия /σ (старая) = −36.54. Соответствует Haug (2007), App. B:
  `Ultima = −vega_raw/σ²·[d1 d2(1−d1 d2)+d1²+d2²]`.

## 2. Heston — delta с поправкой на дивиденды ✅

**Файл:** [models/heston.py](models/heston.py), `heston_price`.

- **Было:** `delta = P1` (call) / `P1-1` (put) — без множителя `e^{-qT}`.
- **Стало:** `delta = e^{-qT}·P1` (call) / `e^{-qT}·(P1-1)` (put).
- **Проверка** (q=4%, T=2): код (=P1) = 0.5837; конечная разность `dC/dS` = **0.5388**;
  `P1·e^{-qT}` = 0.5388 (точно). При q=0 совпадает с прежним поведением.

## 3. Vasicek — предел kappa=0 ❌ ЛОЖНАЯ ТРЕВОГА (код не менялся)

**Файл:** [models/short_rate.py](models/short_rate.py), `Vasicek._AB` — **оставлен как есть**.

Обзор утверждал, что `A = +σ²T³/6` завышает цену облигации и знак должен быть отрицательным.

**Проверка опровергает это.** Для `dr = σ dW` (предел κ→0):
`P(0,T) = E[e^{−∫r ds}] = exp(−r₀T + ½Var(∫r)) = exp(−r₀T + σ²T³/6)`,
т.е. `A = +σ²T³/6` — **положительный** (выпуклость по Йенсену всегда повышает цену облигации).

| | значение (r₀=3%, σ=2%, T=5) |
|---|---|
| код, ветка k==0: A | +0.008333 |
| P (код) | 0.867911 |
| аналитика exp(−r₀T+σ²T³/6) | 0.867911 (точно) |
| Monte Carlo | 0.867719 (совпадает) |

Знак из обзора неверен; применение «фикса» занизило бы цены облигаций. Пункт отклонён.
*(Побочно: общая формула при κ→0⁺ численно неустойчива из-за катастрофического сокращения —
именно поэтому ветка k==0 необходима. Это отдельное наблюдение, вне области задачи.)*

## 4. Monte Carlo — матожидание контрольной переменной ✅

**Файл:** [models/monte_carlo.py](models/monte_carlo.py), `mc_price` (control variate).

- **Было:** `cv_true = S0·e^{(r−q)T}` = `E[S_T]` (недисконтированное).
- **Стало:** `cv_true = S0·e^{−qT}` = `E[disc·S_T]` (контрольная переменная — `disc·S_T`).
- **Проверка** (call ATM, r=5%, q=0, BSM=10.4506):
  - прежний код: **13.9022** (смещение **+3.45**),
  - фикс: **10.4468** (смещение −0.0037).
  Контрольная переменная теперь центрирована: `E[disc·S_T − cv_true] = 0`. Соответствует
  Glasserman (2004) §4.1.

## 5. Fixed Income — modified duration через YTM ✅

**Файл:** [instruments/fixed_income.py](instruments/fixed_income.py), `fixed_bond`.

- **Было:** `mod_dur = mac_dur / (1 + r_T/freq)`, где `r_T = curve.rate(maturity)` (zero rate).
- **Стало:** YTM вычисляется до modified duration; `mod_dur = mac_dur / (1 + ytm/freq)`
  (дублирующее вычисление YTM ниже удалено). По определению modified duration знаменатель —
  доходность к погашению, а не спот-ставка.
- **Проверка** (10y 5% bond, восходящая кривая): ytm=4.16%; mod_dur код (zero rate)=7.8663,
  фикс (YTM)=**7.8678** — ближе к численному `−dP/dy/P`=7.9023. На плоской кривой совпадает
  (zero rate = YTM).

## 6. Digital — знак gamma пута ✅

**Файл:** [instruments/digital.py](instruments/digital.py), `cash_or_nothing`.

- **Было:** `gamma = -cash·disc·φ(d2)·d1/(S²σ²T)` — без множителя `sign` (формула колла для обоих).
- **Стало:** `gamma = sign·(-cash·disc·φ(d2)·d1/(S²σ²T))` → для пута знак инвертируется.
- **Проверка** (put, ATM): код = −0.000414; конечная разность `∂(put delta)/∂S` = **+0.000414**.
  После фикса gamma пута = −gamma колла (как и должно быть).

> **Смежное наблюдение (вне области задачи):** `vega` cash-or-nothing пута тоже не несёт
> множителя `sign` ([digital.py](instruments/digital.py)). Это тот же класс ошибки; рекомендуется
> отдельный фикс. В рамках данной задачи (только «put gamma sign») не изменялось.

---

## Обновление метаданных реестра

[models/registry.py](models/registry.py) — `notes` обновлены для моделей с изменившимся поведением:

| model_id | обновление notes |
|---|---|
| `black_scholes` | expiry put delta = −1 при ITM; volga/ultima переведены в per-1% конвенцию |
| `mc_gbm` | матожидание контрольной переменной исправлено на `E[disc·S_T]=S0 e^{-qT}` |
| `heston_cf` | delta теперь с поправкой `e^{-qT}` |
| `fixed_bond` | modified duration через YTM, а не zero rate на погашении |
| `digital` | знак gamma пута исправлен |

Статусы моделей не менялись (поведенческие корректировки в рамках существующего статуса
`APPROXIMATION`).

---

## Результаты тестов

Новый модуль [tests/test_medium_severity_fixes.py](tests/test_medium_severity_fixes.py) — 16 тестов
(включая защитные тесты Vasicek для ложного пункта):

```text
tests/test_medium_severity_fixes.py  16 passed
```

Регрессия по всему не-UI набору:

```text
163 passed in 6.60s
```

> UI-модули тестов (`test_ui_*`, `test_workstation_navigation`) не собираются из-за отсутствия
> `PySide6` — предсуществующее ограничение окружения, не связанное с этими правками. `scipy`
> установлен для прогона; файл зависимостей не менялся.

---

## Изменённые файлы

| Файл | Изменение |
|---|---|
| [models/black_scholes.py](models/black_scholes.py) | put delta@expiry; volga /10000; ultima /σ² |
| [models/heston.py](models/heston.py) | delta = e^{-qT}·P1 |
| [models/monte_carlo.py](models/monte_carlo.py) | cv_true = S0·e^{-qT} |
| [instruments/fixed_income.py](instruments/fixed_income.py) | modified duration через YTM |
| [instruments/digital.py](instruments/digital.py) | знак gamma пута |
| [models/registry.py](models/registry.py) | обновлены notes 5 моделей |
| [tests/test_medium_severity_fixes.py](tests/test_medium_severity_fixes.py) | 16 новых тестов |
| MEDIUM_FIXES_VALIDATION.md | этот документ |

API не менялись; UI не затрагивался.
