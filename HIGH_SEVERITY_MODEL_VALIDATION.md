# HIGH-Severity Model Fixes — Validation

**Дата:** 2026-06-04
**Область:** HIGH-severity пункты из [MODEL_REVIEW_AND_RECOMMENDATIONS.md](MODEL_REVIEW_AND_RECOMMENDATIONS.md) §3 (проблемы 4–8)
**Изменённый код:** `instruments/fixed_income.py`, `models/short_rate.py`, `risk/var.py`
**Новые тесты:** `tests/test_high_severity_fixes.py`
**НЕ затронуто:** UI (`app/`, `ui/`) — без изменений.

> **Метод:** каждый пункт проверен численно против эталона (аналитика / Monte Carlo /
> свойства модели) **до** правок. Применён фикс только там, где баг подтверждён. Прогоны
> воспроизводимы (numpy 2.4, scipy 1.17).

---

## Сводка

| # | Пункт | Вердикт | Действие |
|---|---|---|---|
| 4 | Heston CF stability | ❌ **Ложно** | Код уже стабилен; правка обзора ломает его |
| 5 | Hull-White instantaneous forward | ✅ **Баг** | Исправлен `bond_price` (не мёртвый `_A`) |
| 6 | Historical VaR horizon | ✅ **Подтверждено** | Оконная агрегация вместо sqrt-scaling |
| 7 | Caplet discounting | ✅ **Баг** | Убрано двойное дисконтирование |
| 8 | Discrete Asian sigma_g | ❌ **Ложно** | d1 корректен; правка обзора внесла бы ошибку |

**Применено 3 фикса (5, 6, 7). Отклонено 2 ложных пункта (4, 8).**

---

## 7. Caplet — двойное дисконтирование ✅ ИСПРАВЛЕНО

**Файл:** [instruments/fixed_income.py](instruments/fixed_income.py), `caplet()`.

### Previous behaviour
```python
r_eff = -np.log(disc) / T2 if disc > 0 and T2 > 0 else 0
g     = black76(F, K, T1, r_eff, sigma, ...)
price = notional * tau * disc * g.price
```
`black76` внутри домножает на `exp(-r_eff·T1) = disc^(T1/T2)`, после чего код домножает ещё
на `disc`. Итоговый дисконт — `disc^(1 + T1/T2)` вместо `P(0,T2)`.

### Corrected behaviour
```python
g     = black76(F, K, T1, 0.0, sigma, ...)   # undiscounted forward value
price = notional * tau * disc * g.price       # discount exactly once by P(0,T2)
```

### Numerical evidence
Параметры: N=1e6, K=3%, T1=1, T2=1.25, F=3.5%, σ=20%, disc=P(0,T2)=0.95.

| | Значение |
|---|---|
| Теоретическая (single discount) | 1381.68 |
| Прежний код | 1326.13 (**−4.02%**) |
| current/theo | 0.95980 = ровно `disc^(T1/T2)` |
| После фикса | 1381.68 (точное совпадение) |

Проверка паритета: `caplet_cap − caplet_floor` должна равняться `N·τ·disc·(F−K)` — выполняется
после фикса, нарушалась до него.

**Источник:** Brigo & Mercurio, *Interest Rate Models — Theory and Practice* (2006), §1.6.

---

## 5. Hull-White — точная подгонка к начальной кривой ✅ ИСПРАВЛЕНО

**Файл:** [models/short_rate.py](models/short_rate.py), `HullWhite.bond_price()` (+ `zero_rate`, `bond_option`, новый `_inst_forward`).

> **Уточнение к обзору:** обзор указывал на метод `_A` (строки 154–172). Фактически `_A` —
> **мёртвый код** (нигде не вызывается; проверено `grep`). Реальное ценообразование идёт через
> `bond_price`, где и находился баг. Поэтому фикс внесён в `bond_price`, а не в `_A`.

### Previous behaviour
```python
f0t = self.curve.forward_rate(t, T)   # СРЕДНИЙ форвард по [t,T]
A   = (P0T/P0t) * np.exp(B*f0t - ...)
```
А состояние короткой ставки в `zero_rate`/`bond_option` бралось как `curve.rate(0.001)`.
В результате модель **не репрайсила** собственную начальную кривую — фундаментальное
свойство no-arbitrage HW нарушалось.

### Corrected behaviour
```python
def _inst_forward(self, t, dt=1e-5):
    # f(0,t) = -d/dT ln P(0,T)|_{T=t}, центральная разность
    ...
f0t = self._inst_forward(t)            # МГНОВЕННЫЙ форвард в точке t
# состояние r(0) = f(0,0):
@property
def _r0(self): return self._inst_forward(0.0)
```

### Numerical evidence
Восходящая кривая (zero rates 2.0%→3.7% на 0.25–10 лет), kappa=0.1, sigma=0.01.
Репрайсинг `P_HW(0,T)` vs рыночного `P(0,T)`:

| T | abs err (прежний) | abs err (фикс) |
|---|---|---|
| 0.5 | 1.9e-03 | 0 |
| 1.0 | 6.5e-03 | 2.2e-16 |
| 2.0 | 1.7e-02 | 1.1e-16 |
| 5.0 | 5.2e-02 | 1.1e-16 |
| 10.0 | **8.8e-02 (≈9%)** | 0 |

После фикса кривая репрайсится с машинной точностью при любых (kappa, sigma).

**Источник:** Hull & White, "Pricing Interest-Rate-Derivative Securities", *RFS* 3(4), 1990.

---

## 6. Historical VaR — горизонт через фактические окна ✅ ИСПРАВЛЕНО

**Файл:** [risk/var.py](risk/var.py), `historical_var()` (+ новый `_horizon_returns`).

### Previous behaviour
```python
losses_pct = -returns * np.sqrt(horizon)
```
Масштабирование `sqrt(h)` — свойство i.i.d. нормального распределения. Применять его к
**непараметрической** исторической симуляции некорректно: оно игнорирует фактическую форму
многодневного распределения (тяжёлые хвосты, серийную корреляцию).

### Corrected behaviour
Для целого `horizon > 1` при достаточном числе наблюдений — агрегирование **перекрывающихся**
h-дневных доходностей (стиль Basel FRTB). Иначе (горизонт=1, нецелый, или мало данных) —
сохраняется прежнее sqrt-масштабирование (backward-compatible fallback, порог
`_MIN_HORIZON_WINDOWS = 50`).

```python
h = int(round(horizon)); n_windows = len(returns) - h + 1
if not is_integer or h <= 1 or n_windows < _MIN_HORIZON_WINDOWS:
    return returns * np.sqrt(horizon)        # legacy fallback
c = np.concatenate(([0.0], np.cumsum(returns)))
return c[h:] - c[:-h]                        # overlapping h-day sums
```

### Numerical evidence
Тяжёлые хвосты (Student-t, df=3), 2000 дней, 99% VaR, horizon=10:

| | VaR_pct |
|---|---|
| 1-дневный | 0.0430 |
| sqrt(10)-scaling (прежний) | 0.1359 |
| фактический 10-дневный эмпирический | 0.1142 |
| ошибка sqrt-scaling | **+19.1%** |

После фикса `historical_var(horizon=10)` точно совпадает с эмпирическим квантилем
перекрывающихся 10-дневных окон.

**Совместимость:** `horizon=1` не изменился; существующий тест на sqrt-scaling для малой
выборки (5 точек) проходит через fallback. Decay-веса EWMA выравниваются по концам окон.

**Источник:** McNeil, Frey & Embrechts, *Quantitative Risk Management* (2015), §2.2.3.

---

## 4. Heston CF stability — ❌ ЛОЖНАЯ ТРЕВОГА (код не менялся)

**Файл:** [models/heston.py](models/heston.py), `_heston_cf` — **оставлен как есть**.

Обзор утверждал, что текущий код использует нестабильную оригинальную формулировку Heston, и
предлагал «поменять знак D и `exp(-λT)→exp(+λT)`».

**Проверка показала обратное.** Текущий код уже реализует **стабильную** формулировку
Albrecher et al. («Little Heston Trap»): `D = (κ − iρξφ − λ)/(κ − iρξφ + λ)` с `exp(−λT)`. Это и
есть рекомендуемый устойчивый вариант (`g₂ = 1/g₁`, |e^{−λT}|≤1, нет пересечения branch cut).

Предложенная обзором замена даёт **нестабильную оригинальную** форму с `exp(+λT)`, которая
переполняется:

| T | xi | rho | текущий код | формула из обзора |
|---|---|---|---|---|
| 0.5 | 0.3 | −0.5 | 5.9451 | **NaN** |
| 2.0 | 0.6 | −0.7 | 11.3505 | **NaN** |
| 5.0 | 0.9 | −0.8 | 18.5648 | **NaN** |
| 10.0 | 1.0 | −0.9 | 28.8892 | **NaN** |

Текущий код также сходится к BSM при xi→0 (diff 0.00001). **Применение правки обзора
дестабилизировало бы рабочую модель**, поэтому она отклонена.

**Источник:** Albrecher, Mayer, Schachermayer, Teichmann, "The Little Heston Trap" (2007).

---

## 8. Discrete Asian sigma_g — ❌ ЛОЖНАЯ ТРЕВОГА (код не менялся)

**Файл:** [instruments/asian.py](instruments/asian.py), `geometric_asian_discrete` — **оставлен как есть**.

Обзор утверждал, что `d1` завышен на `0.5·σ_g²·T` (двойной учёт Ито), и опцион ATM переоценён ~0.5%.

**Проверка опровергает это.** Для логнормального геометрического среднего числитель `d1`
содержит **полную** дисперсию `σ_g²` (а не `σ_g²/2`): `d1 = (ln(S/K) + (μ + σ_g²)T)/(σ_g√T)`,
где `μ = (r−q−σ²/2)(n+1)/(2n)`. Код даёт ровно это (`b_g = μ + σ_g²/2`, затем `+0.5σ_g²` в d1).
Ошибку допустил обзор, перепутав параметризацию d1/d2.

Сверка с Monte Carlo (n=12, ATM, 20 сидов × 500k путей):

| | значение |
|---|---|
| Closed-form | 5.9402 |
| MC (среднее) | 5.9417 ± 0.0042 (95% CI) |
| отн. отклонение | **−0.026%** (closed внутри CI) |

Заявленного «+0.5% завышения» нет (отклонение даже отрицательное и статистически незначимо).
Discrete и continuous пределы согласованы (n=2000 → diff 0.0024). Правка отклонена.

**Источник:** Kemna & Vorst, "A Pricing Method for Options Based on Average Asset Values" (1990).

---

## Результаты тестов

Новый модуль [tests/test_high_severity_fixes.py](tests/test_high_severity_fixes.py) — 25 тестов
(dedicated + edge-case), включая защитные тесты для ложных пунктов:

```text
tests/test_high_severity_fixes.py  25 passed
```

- **Caplet:** single-discount, cap−floor parity, disc=1 edge, near-zero-vol edge.
- **Hull-White:** репрайсинг кривой (sloped/flat, разные kappa/sigma), zero_rate vs рынок,
  inst-forward > avg-forward.
- **Historical VaR:** horizon=1 без изменений, совпадение с окнами, отличие от sqrt на хвостах,
  fallback на малой выборке, ES≥VaR.
- **Heston (guard):** сходимость к BSM при xi→0; конечная и осмысленная цена на длинных сроках
  (упадёт, если применить нестабильную формулу обзора).
- **Asian (guard):** closed-form в пределах CI Monte Carlo.

Регрессия по всему не-UI набору:

```text
147 passed in 9.22s
```

> UI-модули тестов (`test_ui_*`, `test_workstation_navigation`) не собираются из-за отсутствия
> `PySide6` в окружении — предсуществующее ограничение, не связанное с этими правками. `scipy`
> установлен для прогона; файл зависимостей не менялся.

---

## Изменённые файлы

| Файл | Изменение |
|---|---|
| [instruments/fixed_income.py](instruments/fixed_income.py) | Caplet: `black76(r=0)` + единый внешний дисконт |
| [models/short_rate.py](models/short_rate.py) | HW: `_inst_forward`, `_r0`; `bond_price`/`zero_rate`/`bond_option` репрайсят кривую |
| [risk/var.py](risk/var.py) | Historical VaR: `_horizon_returns` (перекрывающиеся окна + sqrt-fallback) |
| [tests/test_high_severity_fixes.py](tests/test_high_severity_fixes.py) | 25 новых тестов |
| HIGH_SEVERITY_MODEL_VALIDATION.md | Этот документ |

UI не затрагивался.
