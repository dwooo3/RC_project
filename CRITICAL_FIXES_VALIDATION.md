# Critical Mathematical Fixes — Validation

**Дата:** 2026-06-04
**Область:** только CRITICAL-пункты из [MODEL_REVIEW_AND_RECOMMENDATIONS.md](MODEL_REVIEW_AND_RECOMMENDATIONS.md) §2
**Затронуто кодом:** `instruments/variance_swaps.py` (исправление), `tests/test_critical_fixes.py` (регрессии)
**НЕ затронуто:** UI, `services/`, workspaces, архитектура — без изменений.

> **Метод:** каждый заявленный CRITICAL-баг проверен численно против эталонных значений
> из перечисленных в обзоре источников **до** внесения правок. Применён только тот фикс,
> который подтвердился. Два пункта оказались ложными — правки по ним не вносились, чтобы не
> сломать корректный код. Численные прогоны воспроизводимы (`python3`, numpy 2.4, scipy 1.17).

---

## Сводка верификации

| # | Заявленный CRITICAL-баг | Вердикт | Действие |
|---|---|---|---|
| 1 | Theta в `models/trees.py` занижена в 365× («двойное деление») | ❌ **Ложно** — код уже корректен | Не менялось; добавлен регресс-тест |
| 2 | Theta в `models/monte_carlo.py` — та же ошибка | ❌ **Ложно** — theta там не вычисляется | Не менялось; добавлен тест-документация |
| 3 | Variance swap: лишний `(1 − log(K/F))` в интеграле | ✅ **Подтверждено** — систематическое завышение ~1% | **Исправлено** + регресс-тесты |

---

## 1. Theta в `models/trees.py` — баг НЕ подтверждён

### Заявление обзора
`theta = (pt - price) / eps_t / 365` при `eps_t = 1/365` алгебраически равно `(pt - price)`,
из чего обзор делает вывод, что theta «занижена ровно в 365 раз», и предлагает заменить на
`(pt - price) / 365`.

### Анализ
Алгебраическое тождество верное, но интерпретация — нет. `eps_t = 1/365` года = **1 день**.
Поэтому `(pt − price) = V(T − 1день) − V(T)` — это и есть изменение стоимости за один
календарный день, т.е. **дневная theta напрямую**.

Разложение конечной разности:

```
(pt − price)              = изменение за 1 день           = ДНЕВНАЯ theta
(pt − price)/eps_t        = ×365 = годовая theta
(pt − price)/eps_t/365    = годовая/365 = ДНЕВНАЯ theta    ← текущий код (корректно)
```

Формула `(pt − price)/eps_t/365` даёт дневную theta при **любом** `eps_t`, а не только при
`1/365`, — это устойчивая, а не случайно работающая запись.

### Previous behaviour (= corrected behaviour: без изменений)
Численная проверка, call ATM S=100, K=100, T=0.25, r=5%, σ=20%, q=0:

| Величина | Значение |
|---|---|
| BSM theta (аналитическая, per day) | **−0.028696** |
| CRR theta, текущий код (N=2000)    | **−0.028754** |
| Расхождение | 0.00006 (дискретизация дерева) |
| `(pt−price)/eps_t` (годовая)        | −10.495 |
| Предложенный «фикс» `(pt−price)/365` | **−0.0000788** ← в 365× меньше истинной |

Вывод: текущая theta совпадает с аналитической BSM (per day). Предложенный «фикс» внёс бы
ошибку масштабирования в 365 раз. **Правка не применялась.**

> Числовой пример в обзоре («корректная theta ≈ −5.3 руб/день») некорректен: −5.3/день
> соответствовало бы ≈ −1934/год для опциона стоимостью ~$4, что невозможно. Истинная
> дневная theta ≈ −0.029, и код её уже воспроизводит.

**Источник проверки:** Hull, *Options, Futures, and Other Derivatives*, 11th ed., §19.5
(theta квотируется «per calendar day», деление годовой на 365).

---

## 2. Theta в `models/monte_carlo.py` — отсутствует

`mc_price()` возвращает `price, stderr, ci95, delta, gamma, vega, n_sims` — **theta не
вычисляется вообще**. `lsm()` и `heston_mc_price()` также theta не возвращают. Строка
`monte_carlo.py:164`, на которую ссылается обзор, находится внутри `_lsm_price_only` и не
имеет отношения к theta.

Следовательно, исправлять нечего. Добавлен тест `test_mc_price_has_no_theta_key`,
фиксирующий это явно.

---

## 3. Variance swap — баг ПОДТВЕРЖДЁН и исправлен

**Файл:** [instruments/variance_swaps.py](instruments/variance_swaps.py), функция
`variance_swap_fair_strike` → внутренняя `integral_part`.

### Previous behaviour

```python
total += 2/T * (1 - np.log(K/F_)) * P * dK / K**2
```

Веса страйп-стрипов модулировались множителем `(1 − log(K/F))`. При этом ведущий член
`2/T·(log(F/S0) − (F/S0 − 1))` уже несёт log-контрактную поправку (формулировка Demeterfi с
точкой разложения S* = S0). Множитель в интеграле **дублировал** эту поправку.

### Corrected behaviour

```python
# Log-contract replication uses a pure 1/K^2 weight per strike strip.
total += 2/T * P * dK / K**2
```

Чистый вес `2/K²` на стрип — каноническая реплика log-контракта (Demeterfi et al. 1999;
Carr–Madan 1998; Gatheral, *The Volatility Surface*).

### Numerical examples

Flat implied vol 20%, S₀ = F = 100, r = q = 0, T = 1 ⇒ истинный `K_var = σ² = 0.04`.

| Диапазон страйков / шаг | Текущий (с багом) | Исправленный | Истинное |
|---|---|---|---|
| 50–150, шаг 1.0   | 0.04033 | 0.03986 | 0.04000 |
| 20–300, шаг 0.5   | 0.04040 | **0.04000** | 0.04000 |
| 10–400, шаг 0.25  | 0.04040 | **0.04000** | 0.04000 |

Ключевое наблюдение: с измельчением сетки исправленная версия **сходится к 0.04000**, а
версия с багом застывает на **0.04040** (+1.0%) — смещение систематическое и от
дискретизации не зависит. Это исключает объяснение «ошибка интегрирования» и доказывает,
что лишний множитель искажает саму подынтегральную функцию.

### Влияние
- Завышение fair variance strike ⇒ завышение vol strike (√): при истинных 20% выдавалось ≈ 20.1%
  на узкой сетке и систематически выше на широкой.
- Через [variance_swap_pnl](instruments/variance_swaps.py) смещение strike напрямую искажало MTM
  P&L позиции по variance swap.

**Источник:** Demeterfi K., Derman E., Kamal M., Zou J., "More Than You Ever Wanted to Know
About Volatility Swaps", Goldman Sachs Quantitative Strategies Research Notes, 1999.

---

## Результаты тестов

Новый модуль [tests/test_critical_fixes.py](tests/test_critical_fixes.py) (8 тестов):

```text
tests/test_critical_fixes.py ........                                    [100%]
8 passed
```

Покрытие:
- `test_variance_swap_flat_vol_recovers_sigma_squared` — K_var = 0.04 при flat 20%.
- `test_variance_swap_no_systematic_overestimate_under_refinement` — нет +1% смещения на мелкой сетке.
- `test_crr_theta_matches_bsm_per_day` — theta дерева = аналитической BSM (per day); **упадёт**, если применить ошибочный `(pt−price)/365`.
- `test_crr_theta_is_daily_scale_not_annual` — theta дневного масштаба, не годового.
- `test_crr_theta_sign_for_put` — знак/масштаб put theta.
- `test_mc_price_has_no_theta_key` — фиксирует отсутствие theta в `mc_price`.

Регрессия по затронутым и смежным модулям:

```text
tests/test_critical_fixes.py tests/test_trees.py tests/test_monte_carlo.py
24 passed in 4.92s

весь не-UI набор: 122 passed in 8.06s
```

> Примечание по окружению: `scipy` отсутствовал в активном интерпретаторе — установлен для
> прогона (`pip install scipy`); файл зависимостей не менялся. UI-модули тестов
> (`test_ui_*`, `test_workstation_navigation`) не собираются из-за отсутствия `PySide6` —
> это предсуществующее ограничение окружения, не связанное с данными правками.

---

## Изменённые файлы

| Файл | Изменение |
|---|---|
| [instruments/variance_swaps.py](instruments/variance_swaps.py) | Убран лишний множитель `(1 − log(K/F))` в реплике variance swap |
| [tests/test_critical_fixes.py](tests/test_critical_fixes.py) | Новые регресс-тесты по всем трём CRITICAL-пунктам |
| CRITICAL_FIXES_VALIDATION.md | Этот документ |

UI, `services/`, workspaces и архитектура **не затрагивались**.
