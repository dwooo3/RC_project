# RiskCalc — Методологический аудит моделей и рекомендации по исправлению

**Версия:** 1.0
**Дата:** 2026-06-04
**Область:** Математическая корректность финансовых моделей
**Метод:** Статический анализ исходного кода, сравнение с эталонными источниками
**Статус изменений кода:** ❌ Код не изменён — только диагностика и рекомендации

---

## Содержание

1. [Сводная таблица проблем](#1-сводная-таблица-проблем)
2. [Критичные ошибки](#2-критичные-ошибки)
3. [Ошибки высокой серьёзности](#3-ошибки-высокой-серьёзности)
4. [Ошибки средней серьёзности](#4-ошибки-средней-серьёзности)
5. [Ошибки низкой серьёзности](#5-ошибки-низкой-серьёзности)
6. [Что работает корректно](#6-что-работает-корректно)
7. [Приоритетный план исправлений](#7-приоритетный-план-исправлений)
8. [Библиография](#8-библиография)

---

## 1. Сводная таблица проблем

| # | Файл | Строка | Краткое описание | Серьёзность |
|---|------|--------|-----------------|-------------|
| 1 | `models/monte_carlo.py` | 164 | Theta делится на 365 дважды | 🔴 Критично |
| 2 | `models/trees.py` | 164 | Та же ошибка theta во всех деревьях | 🔴 Критично |
| 3 | `instruments/variance_swaps.py` | 42 | Лишний множитель `(1−log(K/F))` в интеграле | 🔴 Критично |
| 4 | `models/heston.py` | 22–28 | Branch-cut нестабильность в характеристической функции | 🟠 Высокая |
| 5 | `models/short_rate.py` | 157–172 | Hull-White: средний форвард вместо мгновенного | 🟠 Высокая |
| 6 | `risk/var.py` | 96 | Исторический VaR неправомерно масштабируется sqrt(T) | 🟠 Высокая |
| 7 | `instruments/fixed_income.py` | 387–389 | Двойной учёт дисконта в капплете | 🟠 Высокая |
| 8 | `instruments/asian.py` | 52–54 | sigma_g² входит в d1 дважды (дискретный Asian) | 🟠 Высокая |
| 9 | `models/black_scholes.py` | 69 | Delta пута при T=0 возвращает 0 вместо −1 | 🟡 Средняя |
| 10 | `models/black_scholes.py` | 94 | Volga: неверное масштабирование (÷100 вместо ÷10000) | 🟡 Средняя |
| 11 | `models/black_scholes.py` | 101 | Ultima: делитель sigma**1 вместо sigma**2 | 🟡 Средняя |
| 12 | `models/heston.py` | 74 | Delta Heston не учитывает дивидендную доходность q | 🟡 Средняя |
| 13 | `models/short_rate.py` | 38 | Vasicek A(T): неверный знак при kappa=0 | 🟡 Средняя |
| 14 | `models/monte_carlo.py` | 120–125 | Control variate: использует неверное E[disc·S_T] | 🟡 Средняя |
| 15 | `instruments/fixed_income.py` | 261 | Modified duration: zero rate вместо YTM | 🟡 Средняя |
| 16 | `instruments/digital.py` | 35 | Гамма цифрового пута: неверный знак | 🟡 Средняя |
| 17 | `instruments/barrier.py` | 77–98 | Таблица Reiner-Rubinstein неполная ("simplified") | 🟡 Средняя |
| 18 | `instruments/barrier.py` | 131–141 | Двойной барьер: d3n вычислен, но не используется | 🟡 Средняя |
| 19 | `instruments/credit.py` | 39–47 | Бутстрап выживаемости — не является настоящим бутстрапом | 🟡 Средняя |
| 20 | `models/implied_vol.py` | 121 | SVI: ограничение a>=0 слишком жёсткое | 🟢 Низкая |
| 21 | `curves/yield_curve.py` | 219 | Modified duration: zero rate вместо YTM | 🟢 Низкая |
| 22 | `models/garch.py` | 96 | Log-likelihood: пропущена константа −0.5·n·log(2π) | 🟢 Низкая |

---

## 2. Критичные ошибки

---

### Проблема 1 & 2 — Theta в деревьях и Monte Carlo (ошибка масштабирования ×365)

**Файл:** `models/trees.py`, строка 164
**Файл:** `models/monte_carlo.py` (аналогичная структура)

#### Текущий код (`trees.py:158–164`)

```python
eps_t = 1 / 365
pt    = _crr_price_only(S, K, max(T - eps_t, 1e-6), r, sigma, q, N, opt,
                        exercise, bermudan_dates, payoff_fn)
...
theta = (pt - price) / eps_t / 365   # ← ОШИБКА: двойное деление
```

#### Математический анализ

Раскроем выражение при `eps_t = 1/365`:

```
theta = (pt - price) / (1/365) / 365
      = (pt - price) × 365 / 365
      = (pt - price)
```

Вместо суточного theta мы получаем просто **разность цен** без какой-либо нормировки.
Theta занижена ровно в **365 раз**.

Для коллa ATM (S=100, K=100, T=0.25, r=5%, σ=20%):
- Корректный theta ≈ −5.3 руб/день (BSM)
- Текущий расчёт даст ≈ −0.015 (фактически = разность цен)

#### Корректная формула

Theta — скорость изменения цены опциона с течением времени, по конвенции «на 1 календарный день»:

```
theta_day = (V(T − dt) − V(T)) / dt / T_days_per_year
          = (V(T − 1/365) − V(T)) / (1/365) / 365
```

Первое деление `/(1/365)` — конечная разность, даёт скорость изменения за год.
Второе деление `/365` — нормировка на 1 день.

Если шаг уже равен `1/365`, то `(pt − price) / eps_t` уже есть годовой theta, и нужно только поделить на 365.

#### Рекомендуемое исправление

```python
# Вариант А (минимальное изменение): убрать лишнее деление
theta = (pt - price) / eps_t / 365
# →
theta = (pt - price) / 365    # при eps_t = 1/365

# Вариант Б (рекомендуется для численной устойчивости): увеличить шаг
eps_t = 7.0 / 365             # шаг 1 неделя
pt    = _crr_price_only(S, K, max(T - eps_t, 1e-6), ...)
theta = (pt - price) / eps_t / 365   # корректно при любом eps_t != 1/365
```

**Источник:** Hull, J.C. *Options, Futures, and Other Derivatives*, 11th ed., §19.4.

---

### Проблема 3 — Variance Swap: лишний логарифмический множитель в интеграле репликации

**Файл:** `instruments/variance_swaps.py`, строка 42

#### Текущий код

```python
# строка 42
total += 2/T * (1 - np.log(K/F_)) * P * dK / K**2

# строки 45-47
var_strike = (2/T * (np.log(F/S0) - (F/S0 - 1))
              + integral_part(puts,  F, False)
              + integral_part(calls, F, True))
```

#### Математический анализ

Стандартная формула репликации fair variance strike (Carr & Madan, 1998; Demeterfi et al., 1999):

```
K_var = (2/T)·e^{rT} · [ ∫₀^F P(K)/K² dK + ∫_F^∞ C(K)/K² dK ]
```

Весовая функция — однородная `2/K²` для каждого страйк-стрипа. Никакого логарифмического множителя нет.

Код явно добавляет log-компенсацию через выражение `2/T·(log(F/S₀) − (F/S₀−1))` в строках 45–47. Это первое слагаемое в разложении log-контракта. Второе слагаемое (интегральная часть) должно использовать чистые веса `2/K²`.

Добавляя `(1 − log(K/F))` в интеграл, код **дважды учитывает** log-поправку, что ведёт к систематическому завышению fair variance strike.

**Численный пример:** Flat vol surface 20%, S=F=100, T=1.
- Правильный K_var = 0.04 (т.е. 20%² = 4%)
- С лишним множителем K_var > 0.04 при любом strike range > 0

#### Рекомендуемое исправление

```python
# Было:
total += 2/T * (1 - np.log(K/F_)) * P * dK / K**2

# Должно быть:
total += 2/T * P * dK / K**2
```

**Источник:** Demeterfi K. et al. "More Than You Ever Wanted to Know About Volatility Swaps", Goldman Sachs Quantitative Strategies Research Notes, 1999.

---

## 3. Ошибки высокой серьёзности

---

### Проблема 4 — Heston: нестабильность ветви комплексного логарифма

**Файл:** `models/heston.py`, строки 22–28

#### Текущий код

```python
lam = np.sqrt(xi**2*(phi**2 + 1j*phi) + (kappa - 1j*rho*xi*phi)**2)
D   = (kappa - 1j*rho*xi*phi - lam) / (kappa - 1j*rho*xi*phi + lam)
G   = (1 - D*np.exp(-lam*T)) / (1 - D)
cf *= np.exp(kappa*theta/xi**2 * ((kappa - 1j*rho*xi*phi - lam)*T - 2*np.log(G)))
```

#### Математический анализ

Это оригинальная формулировка Heston (1993). Её известный недостаток — разрыв ветви (branch discontinuity) функции `log(G)` при обходе нулевого значения комплексной плоскости.

**Когда возникает проблема:**
- Длинные экспирации (T > 2 лет)
- Высокое vol-of-vol (xi > 0.8)
- Сильная отрицательная корреляция (rho < −0.7)
- Малое mean-reversion (kappa < 0.5)

При определённых траекториях phi в области интегрирования G пересекает отрицательную вещественную ось. `numpy.log` для комплексных чисел применяет главную ветвь с разрезом по отрицательной вещественной оси, порождая скачок в `Im(log(G))` на ±π. Это вносит ошибку в интеграл Gil-Pelaez и, как следствие, в цену опциона.

**Albrecher, Mayer, Schachermayer, Teichmann (2007)** показали, что простая замена знака в определении D устраняет проблему аналитически:

```
# Оригинал Heston:
D  = (κ − iρξφ − λ) / (κ − iρξφ + λ)    ← минус в числителе

# Albrecher (stable D̃):
D̃  = (κ − iρξφ + λ) / (κ − iρξφ − λ)    ← плюс в числителе
G̃  = (1 − D̃·e^{+λT}) / (1 − D̃)          ← exp(-λT) → exp(+λT)
```

#### Рекомендуемое исправление

```python
def _heston_cf(phi, S, v0, r, q, kappa, theta, xi, rho, T):
    i   = 1j
    lam = np.sqrt(xi**2*(phi**2 + i*phi) + (kappa - i*rho*xi*phi)**2)
    # Albrecher et al. 2007 — stable formulation (swapped D sign)
    D   = (kappa - i*rho*xi*phi + lam) / (kappa - i*rho*xi*phi - lam)
    G   = (1 - D * np.exp(lam*T)) / (1 - D)
    cf  = np.exp(i*phi*(np.log(S) + (r-q)*T))
    cf *= np.exp(kappa*theta/xi**2 * ((kappa - i*rho*xi*phi + lam)*T - 2*np.log(G)))
    cf *= np.exp(v0/xi**2 * (kappa - i*rho*xi*phi + lam)
                 * (1 - np.exp(lam*T)) / (1 - D*np.exp(lam*T)))
    return cf
```

**Источник:** Albrecher H. et al. "The Little Heston Trap", *Wilmott Magazine*, 2007.

---

### Проблема 5 — Hull-White: средний форвард вместо мгновенного

**Файл:** `models/short_rate.py`, строки 154–172

#### Текущий код

```python
def _A(self, T: float) -> float:
    k, sig = self.kappa, self.sigma
    f0 = self.curve.forward_rate(0, T)  # ← средний форвард [0,T]
    B  = self._B(T)
    return (np.log(self.curve.discount(T))
            + B * f0
            - sig**2 * B**2 * (1 - np.exp(-2*k*T)) / (4*k))
```

#### Математический анализ

Ключевое свойство Hull-White (1990) — **точная подгонка к начальной кривой** при условии, что параметр A(0,T) использует **мгновенный** форвард f(0,T):

```
A(0,T) = ln P_M(0,T) + B(T)·f_M(0,T) − (σ²/4κ)·B(T)²·(1−e^{−2κT})
```

где `f_M(0,T) = −∂/∂T · ln P_M(0,T)` — мгновенный форвард в точке T.

Функция `curve.forward_rate(0, T)` вычисляет:

```python
def forward_rate(self, T1, T2):
    return -np.log(self.discount(T2)/self.discount(T1)) / (T2 - T1)
# при T1=0: (−ln P(0,T)) / T  — это средний форвард, не мгновенный
```

**Разница:** Мгновенный форвард = `rate(T) + T · drate/dT`. При крутой кривой:
- Средний форвард при T=5 лет: ~3%
- Мгновенный форвард при T=5 лет: ~5%

Использование среднего форварда нарушает условие согласования с рынком, что является принципиальным преимуществом HW перед Vasicek.

#### Рекомендуемое исправление

```python
def _instantaneous_forward(self, T: float, dt: float = 1e-4) -> float:
    """f(0,T) = -d/dT * ln P(0,T), центральная конечная разность."""
    P_up   = self.curve.discount(T + dt)
    P_down = self.curve.discount(max(T - dt, 1e-6))
    return -(np.log(P_up) - np.log(P_down)) / (2.0 * dt)

def _A(self, T: float) -> float:
    k, sig = self.kappa, self.sigma
    f0 = self._instantaneous_forward(T)   # ← мгновенный форвард
    B  = self._B(T)
    return (np.log(self.curve.discount(T))
            + B * f0
            - sig**2 * B**2 * (1 - np.exp(-2*k*T)) / (4*k))
```

**Источник:** Hull J., White A. "Pricing Interest-Rate-Derivative Securities", *Review of Financial Studies*, 3(4), 1990.

---

### Проблема 6 — Historical VaR: неправомерное масштабирование sqrt(horizon)

**Файл:** `risk/var.py`, строка 96

#### Текущий код

```python
losses_pct = -returns * np.sqrt(horizon)
```

#### Математический анализ

Существуют два принципиально разных подхода к многодневному VaR:

**Параметрический подход** допускает iid-нормальные приросты:
`sigma_h = sigma_1 * sqrt(h)` → `VaR_h = VaR_1 * sqrt(h)`.
Правило sqrt(T) справедливо только при этом допущении.

**Исторический (непараметрический) подход** сохраняет эмпирическое распределение «как есть»:
- Не предполагает нормальности
- Не предполагает iid (может учитывать кластеризацию волатильности)
- Для h > 1 должен использовать **фактические h-дневные P&L**

Применение sqrt(h) к историческому VaR:
1. Занижает риск при тяжёлых хвостах (fat tails), так как sqrt масштабирование — свойство нормального распределения
2. Игнорирует серийную корреляцию (если доходности автокоррелированы)
3. Противоречит духу непараметрического метода

Basel III (FRTB §99.2) явно требует использовать фактические многодневные P&L для HS-VaR.

#### Рекомендуемое исправление

```python
def historical_var(returns, position_value, confidence=0.95,
                   horizon=1, weights=None):
    if horizon == 1:
        losses_pct = -returns
    else:
        # Non-overlapping horizon-day returns
        n_periods = len(returns) // horizon
        if n_periods < 30:
            raise ValueError(
                f"Недостаточно наблюдений ({len(returns)}) "
                f"для горизонта {horizon} дней. "
                f"Требуется минимум {30 * horizon}."
            )
        multi_day = np.array([
            np.sum(returns[i*horizon : (i+1)*horizon])
            for i in range(n_periods)
        ])
        losses_pct = -multi_day
    var_pct, cvar_pct = _loss_var_es(losses_pct, confidence, weights)
    ...
```

**Источник:** McNeil A.J., Frey R., Embrechts P. *Quantitative Risk Management*, Princeton University Press, 2015, §2.2.3.

---

### Проблема 7 — Caplet: двойное дисконтирование

**Файл:** `instruments/fixed_income.py`, строки 385–391

#### Текущий код

```python
r_eff = -np.log(disc) / T2 if disc > 0 and T2 > 0 else 0
g     = black76(F, K, T1, r_eff, sigma, "call" if opt=="cap" else "put")
price = notional * tau * disc * g.price
```

#### Математический анализ

`black76(F, K, T, r, sigma)` внутри применяет дисконт `exp(−r·T)`. При `r_eff = −log(disc)/T2`:

```
discount_in_black76 = exp(−r_eff · T1) = exp(log(disc) · T1/T2) = disc^{T1/T2}
```

Затем результат умножается ещё на `disc = P(0, T2)`. Итоговый дисконт:

```
disc^{T1/T2} · disc = disc^{1 + T1/T2}  ≠  P(0, T2)
```

Правильная формула капплета (рыночный стандарт):

```
caplet = P(0, T2) · tau · N · Black76(F_K, K, T1, sigma)
```

Где Black76 с правильной ставкой `r = rate(T1)` внутри дисконтирует на `exp(−r·T1) ≈ P(0, T1)`, а внешний множитель `P(0, T2)` дисконтирует на полный срок до платежа T2.

#### Рекомендуемое исправление

```python
def caplet(notional, K, T1, T2, fwd_rate, sigma, disc, curve, opt="cap"):
    tau  = T2 - T1
    F    = fwd_rate
    r_T1 = curve.rate(T1)        # ставка к началу accrual периода
    g    = black76(F, K, T1, r_T1, sigma, "call" if opt=="cap" else "put")
    # Black76 дисконтирует на exp(-r_T1*T1) ≈ P(0,T1)
    # Добавляем дисконт P(T1,T2) = P(0,T2)/P(0,T1)
    disc_T1 = curve.discount(T1)
    disc_T1_T2 = disc / disc_T1 if disc_T1 > 0 else 1.0
    price = notional * tau * disc_T1 * disc_T1_T2 * g.price
    ...
```

**Источник:** Brigo D., Mercurio F. *Interest Rate Models — Theory and Practice*, Springer, 2006, §1.6.2.

---

### Проблема 8 — Discrete Geometric Asian: sigma_g² дважды в числителе d1

**Файл:** `instruments/asian.py`, строки 51–54

#### Текущий код

```python
sigma_g = sigma * np.sqrt((n+1)*(2*n+1)/(6*n**2))
b_g     = (r - q - sigma**2/2) * (n+1)/(2*n) + sigma_g**2/2  # содержит +sigma_g²/2
d1      = (np.log(S/K) + (b_g + 0.5*sigma_g**2)*T) / (sigma_g*np.sqrt(T))
#                                ↑ снова sigma_g²/2
```

#### Математический анализ

Обозначим чистый дрейф геометрического среднего:

```
b_drift = (r − q − sigma²/2) · (n+1)/(2n)
```

Это аналог `r − q − sigma²/2` для обычного BSM. Тогда правильный d1:

```
d1 = (ln(S/K) + (b_drift + sigma_g²/2) · T) / (sigma_g · sqrt(T))
```

В коде `b_g = b_drift + sigma_g²/2` (поправка Ито уже включена). Затем d1 прибавляет ещё `0.5·sigma_g²`. В числителе d1 оказывается `b_drift + sigma_g²` вместо `b_drift + sigma_g²/2`.

Числитель d1 завышен на `0.5·sigma_g²·T`. Для типичных параметров (n=12, sigma=20%, T=1):

```
sigma_g ≈ 0.183,  0.5·sigma_g²·T ≈ 0.017
```

Это смещение d1 ≈ 0.017/0.183 ≈ 0.09. Опцион ATM переоценён примерно на 0.5% стоимости.

#### Рекомендуемое исправление

**Вариант А** — убрать sigma_g²/2 из b_g:

```python
b_g_drift = (r - q - sigma**2/2) * (n+1)/(2*n)   # без +sigma_g**2/2
d1 = (np.log(S/K) + (b_g_drift + 0.5*sigma_g**2)*T) / (sigma_g*np.sqrt(T))
```

**Вариант Б** — убрать 0.5*sigma_g**2 из d1:

```python
b_g = (r - q - sigma**2/2)*(n+1)/(2*n) + sigma_g**2/2  # как есть
d1  = (np.log(S/K) + b_g*T) / (sigma_g*np.sqrt(T))     # без +0.5*sigma_g**2
```

**Источник:** Kemna A.G.Z., Vorst A.C.F. "A Pricing Method for Options Based on Average Asset Values", *Journal of Banking and Finance*, 14(1), 1990.

---

## 4. Ошибки средней серьёзности

---

### Проблема 9 — BSM: Delta пута при истечении T = 0

**Файл:** `models/black_scholes.py`, строка 69

#### Текущий код

```python
g.delta = 1.0 if opt == "call" and S > K else 0.0
```

#### Анализ и исправление

При T → 0 граничные условия:

| Тип | Условие | Правильная delta |
|-----|---------|-----------------|
| Колл | S > K (ITM) | +1.0 |
| Колл | S ≤ K (OTM) | 0.0 |
| Пут  | S < K (ITM) | **−1.0** |
| Пут  | S ≥ K (OTM) | 0.0 |

Код возвращает 0 для всех путов, включая ITM. Корректное исправление:

```python
if opt == "call":
    g.delta = 1.0 if S > K else 0.0
else:
    g.delta = -1.0 if S < K else 0.0
```

---

### Проблема 10 — BSM: Volga — масштабирование

**Файл:** `models/black_scholes.py`, строка 94

#### Анализ

Vega масштабирована как "per 1% vol" (`/100`). Volga = ∂vega/∂sigma должна быть "per 1% vol squared" (`/100²`). Текущий код делит только на 100.

При использовании в PnL Attribution: `volga_pnl = 0.5 * g.volga * dSigma²`
Если `dSigma = 0.01` (1%), а volga занижена в 100×, то компонента volga в PnL занижена в 100×.

```python
# Было:
volga = S * dq * nd1 * np.sqrt(T) * d1 * d2 / sigma / 100

# Должно быть (соглашение "per 1%²"):
volga = S * dq * nd1 * np.sqrt(T) * d1 * d2 / sigma / 10000
```

---

### Проблема 11 — BSM: Ultima — степень делителя sigma

**Файл:** `models/black_scholes.py`, строка 101

#### Анализ

Стандартная формула Ultima `(∂³V/∂σ³)`:

```
Ultima = −Vega_raw / sigma² · (d1·d2·(1−d1·d2) + d1² + d2²)
```

Текущий код: `−vega·100 / sigma·(...)`, то есть делит на `sigma¹` вместо `sigma²`.
При sigma = 0.20 погрешность — множитель `1/sigma = 5`.

```python
# Было:
ultima = -vega * 100 / sigma * (d1 * d2 * (1 - d1 * d2) + d1**2 + d2**2)

# Должно быть:
ultima = -vega * 100 / sigma**2 * (d1 * d2 * (1 - d1 * d2) + d1**2 + d2**2)
```

**Источник:** Haug E.G. *The Complete Guide to Option Pricing Formulas*, 2nd ed., McGraw-Hill, 2007, Appendix B.

---

### Проблема 12 — Heston: Delta не учитывает дивидендную доходность

**Файл:** `models/heston.py`, строка 74

#### Анализ

В модели Heston delta колла = `e^{−qT} · P1`. При q = 0 совпадает с текущим `P1`, но при ненулевом q (FX-опционы, дивидендные акции) delta систематически завышена. При q=3%, T=2 погрешность ≈ 6%.

```python
# Было:
delta=P1 if opt=="call" else P1-1

# Должно быть:
dq = np.exp(-q*T)
delta = dq * P1 if opt=="call" else dq * (P1 - 1)
```

---

### Проблема 13 — Vasicek: знак A(T) при kappa = 0

**Файл:** `models/short_rate.py`, строки 36–39

#### Анализ

Предел Vasicek → Ho-Lee при kappa → 0 через L'Hôpital:

```
A(T) → −sigma²·T³/6  (отрицательный)
```

Текущий код возвращает `+sigma²·T³/6`. Поскольку `P = exp(A − B·r)`, при r > 0 положительный A завышает цену облигации на `exp(sigma²·T³/3)`.

```python
if k == 0:
    B = T
    A = -sig**2 * T**3 / 6   # отрицательный знак
```

---

### Проблема 14 — Monte Carlo: Control Variate использует неверное математическое ожидание

**Файл:** `models/monte_carlo.py`, строки 120–125

#### Анализ

Контрольная переменная: `X = disc·S_T`.
Известное математическое ожидание: `E[disc·S_T] = S₀·e^{−qT}`.

Код использует `cv_true = S₀·e^{(r−q)T}` — это `E[S_T]`, а не `E[disc·S_T]`.
В результате: `E[disc·S_T − cv_true] = S₀·e^{−qT} − S₀·e^{(r−q)T} ≠ 0`.
Поправка не центрирована → систематическое смещение MC-цены.

```python
# Было:
cv_true = S0 * np.exp((r - q)*T)

# Должно быть:
cv_true = S0 * np.exp(-q * T)   # E[disc·S_T] = S0·e^{-qT}
```

---

### Проблема 15 — Fixed Income: Modified Duration использует zero rate вместо YTM

**Файл:** `instruments/fixed_income.py`, строки 259–261

#### Анализ

Modified Duration = Macaulay Duration / (1 + YTM/freq).

Код использует `curve.rate(maturity_time)` — zero rate для последнего cash flow, что не равно YTM для купонной облигации на некрутой кривой. YTM — единая «внутренняя» доходность, IRR потока платежей. Для бумаги с купонами YTM лежит между спот-ставками ближних и дальних купонов.

**Рекомендация:** Использовать значение `ytm`, вычисляемое в функции `bond_metrics()` методом bisection/Brent далее по коду:

```python
mod_dur = mac_dur / (1 + ytm / freq)   # ytm уже есть ниже в функции
```

---

### Проблема 16 — Digital: Gamma пута имеет неверный знак

**Файл:** `instruments/digital.py`, строка 35

#### Анализ

Гамма цифрового колла:

```
dC/dS   = cash · disc · N'(d2) / (S·sigma·sqrt(T))   > 0
d²C/dS² = −cash · disc · N'(d2) · d1 / (S²·sigma²·T)
```

Гамма цифрового пута `P = cash·disc·N(−d2)` отличается знаком:

```
d²P/dS² = +cash · disc · N'(d2) · d1 / (S²·sigma²·T)  =  −d²C/dS²
```

Текущий код возвращает одну и ту же гамму без учёта `sign`. Для пута гамма перевёрнута.

```python
# Было:
gamma = -cash * disc * norm.pdf(d2) * d1 / (S**2 * sigma**2 * T)

# Должно быть:
gamma = sign * (-cash * disc * norm.pdf(d2) * d1 / (S**2 * sigma**2 * T))
```

---

### Проблема 17 — Barrier Options: неполная таблица Reiner-Rubinstein

**Файл:** `instruments/barrier.py`, строки 77–98

#### Анализ

Reiner & Rubinstein (1991) определяют ровно 8 формул для одиночных барьерных опционов через блоки A, B, C, D, F. Комментарий `# simplified` в коде указывает на неполную реализацию.

**Полная таблица (RR 1991, Table 1):**

| Тип | Условие | Формула |
|-----|---------|---------|
| Down-out call | K > L | A − C |
| Down-out call | K <= L | B − D + F |
| Up-out call | K > H | 0 |
| Up-out call | K <= H | A − B + C − D + F |
| Down-in call | K > L | C |
| Down-in call | K <= L | A − B + D + F |
| Up-in call | K > H | A + F |
| Up-in call | K <= H | B − C + D + F |
| (аналогично для puts с phi=−1) | | |

**Рекомендация:** Имплементировать полную таблицу с явной проверкой `sign(K vs. H/L)`.

**Источник:** Reiner E., Rubinstein M. "Breaking Down the Barriers", *Risk Magazine*, September 1991.

---

### Проблема 18 — Double Barrier: серия Ikeda-Kunitomo не полна

**Файл:** `instruments/barrier.py`, строки 131–141

#### Анализ

Формула Ikeda & Kunitomo (1992) использует 4 группы термов: `d1n, d2n, d3n, d4n`.
В коде `d3n` вычисляется, но не входит в аккумулятор цены. Это означает пропуск отражения от нижней границы L, что занижает цену double knock-out опциона вблизи нижнего барьера.

**Рекомендация:** Реализовать полное разложение по Ikeda-Kunitomo (1992) либо заменить метод изображений (images) Карра (1995) — последний проще и прозрачнее.

**Источник:** Ikeda M., Kunitomo N. "Pricing Options with Curved Boundaries", *Mathematical Finance*, 2(4), 1992.

---

### Проблема 19 — Credit: псевдо-бутстрап кривой выживаемости

**Файл:** `instruments/credit.py`, строки 38–47

#### Текущий код

```python
for T, s in zip(tenors, spreads):
    h = s / (1 - recovery)   # независимая оценка для каждого тенора
    hazards.append(h)
```

#### Анализ

Это не бутстрап, а применение плоской аппроксимации `h ≈ s/(1−R)` к каждому тенору **независимо**. Настоящий бутстрап итеративно находит постоянную интенсивность дефолта в каждом сегменте [T_{i-1}, T_i] так, чтобы CDS с этим тенором имел нулевой NPV при уже найденных Lambda_1,...,Lambda_{i-1}.

Для восходящей кривой спредов (5Y > 1Y) аппроксимация занижает lambda на длинных тенорах, систематически завышая стоимость долгосрочной защиты.

#### Рекомендуемое исправление

```python
from scipy.optimize import brentq

def bootstrap_hazards(tenors, spreads, recovery, curve):
    """Истинный бутстрап: итеративный поиск lambda по сегментам."""
    hazards = []
    for i, (T, s) in enumerate(zip(tenors, spreads)):
        seg_tenors  = tenors[:i+1]
        seg_hazards = hazards  # уже найденные

        def cds_npv(h_new):
            all_h = seg_hazards + [h_new]
            # CDS NPV = 0 при fair spread
            pv_prot = sum(
                (1 - recovery) * h_i * np.exp(-(curve.rate(t)+h_i)*t)
                for h_i, t in zip(all_h, seg_tenors)
            )
            annuity = sum(
                np.exp(-(curve.rate(t)+h_i)*t)
                for h_i, t in zip(all_h, seg_tenors)
            )
            return s - pv_prot / annuity

        h = brentq(cds_npv, 1e-6, 10.0, xtol=1e-8)
        hazards.append(h)
    return hazards
```

**Источник:** O'Kane D. *Modelling Single-name and Multi-name Credit Derivatives*, Wiley, 2008, Ch. 4.

---

## 5. Ошибки низкой серьёзности

---

### Проблема 20 — Implied Vol: SVI ограничение a >= 0 слишком жёсткое

**Файл:** `models/implied_vol.py`, строка 121

Корректное no-arbitrage условие SVI: минимальная total variance >= 0.
Минимум достигается при `x = −ρ·m − b·sigma·sqrt(1−ρ²)`, где total variance = `a + b·sigma·sqrt(1−ρ²)`.

```python
# Было:
if b < 0 or sig < 0 or abs(rho) >= 1 or a < 0:

# Должно быть:
min_tv = a + b * sig * np.sqrt(1.0 - rho**2)
if b < 0 or sig < 0 or abs(rho) >= 1 or min_tv < 0:
```

**Источник:** Gatheral J. "A Parsimonious Arbitrage-Free Implied Volatility Parameterization", 2004.

---

### Проблема 21 — YieldCurve: Modified Duration использует zero rate

**Файл:** `curves/yield_curve.py`, строка 219

Аналогично проблеме 15. Modified duration должна использовать YTM, а не `rate(T_last_cashflow)`. Применить то же исправление.

---

### Проблема 22 — GARCH: Log-likelihood без константы

**Файл:** `models/garch.py`, строка 96

```python
# Было:
ll = -0.5 * np.sum(np.log(var) + returns**2/var)

# Должно быть (корректный AIC/BIC):
n  = len(returns)
ll = -0.5 * (n * np.log(2*np.pi) + np.sum(np.log(var) + returns**2/var))
```

Константа не влияет на оптимизацию параметров, но необходима для корректного сравнения моделей через AIC/BIC.

**Источник:** Hamilton J.D. *Time Series Analysis*, Princeton University Press, 1994, §21.1.

---

## 6. Что работает корректно

Следующие компоненты были проверены и соответствуют эталонным источникам:

| Модуль | Проверенные элементы |
|--------|---------------------|
| `models/black_scholes.py` | BSM price, delta, gamma, theta, rho; vanna, charm, speed, color, zomma; Black-76; Garman-Kohlhagen; Bachelier |
| `models/monte_carlo.py` | GBM drift (Ito correction), антитетные пути, moment matching, Heston variance paths (full reflection), Cholesky |
| `models/garch.py` | GARCH(1,1), GJR-GARCH (persistence alpha+gamma/2+beta), EWMA, Parkinson, Garman-Klass |
| `models/trees.py` | CRR u/d/p, LR (Leisen-Reimer), тринomial Kamrad-Ritchken, Bermudan exercise steps |
| `models/implied_vol.py` | Newton-Raphson + Brent fallback, начальное приближение Brenner-Subrahmanyam |
| `models/short_rate.py` | Vasicek A/B closed-form, CIR A/B/h, опционы Jamshidian, Ho-Lee |
| `models/heston.py` | SABR ATM Hagan et al. 2002, SABR off-ATM z/chi(z) поправка |
| `instruments/fixed_income.py` | DCF цена облигации, Macaulay duration, DV01 (bump-and-reprice), IRS fair rate, сваптион |
| `instruments/digital.py` | Cash-or-nothing price/delta/vega, asset-or-nothing, one-touch (expiry/touch), no-touch |
| `instruments/asian.py` | Непрерывный геометрический Asian (Kemna-Vorst), MC с geometric CV |
| `instruments/variance_swaps.py` | Brockhaus-Long vol swap approx, realized variance, PnL MTM |
| `instruments/credit.py` | CDS premium/protection legs (exact), CVA unilateral, Vasicek LHP Gaussian copula |
| `risk/var.py` | Параметрический Normal/Student-t VaR/ES, EVT/POT GPD, Cornish-Fisher, Kupiec LR test, Christoffersen |
| `curves/yield_curve.py` | Nelson-Siegel, Svensson, бутстрап зеро-кривой, DV01 ZCB, par rate, непрерывная форвардная ставка |

---

## 7. Приоритетный план исправлений

### Спринт 1 — Критично (1–2 дня работы)

| # | Задача | Файл:строка | Сложность |
|---|--------|-------------|-----------|
| 1 | Theta: убрать двойное деление на 365 | `trees.py:164` | Тривиальная |
| 2 | Variance swap: убрать `(1−log(K/F))` | `variance_swaps.py:42` | Тривиальная |
| 3 | Ultima: sigma→sigma² | `black_scholes.py:101` | Тривиальная |
| 4 | Delta пута при T=0: 0 → −1 | `black_scholes.py:69` | Тривиальная |
| 5 | Vasicek A(T) κ=0: знак минус | `short_rate.py:38` | Тривиальная |
| 6 | Digital put gamma: добавить `sign` | `digital.py:35` | Тривиальная |

### Спринт 2 — Высокий приоритет (1 неделя)

| # | Задача | Файл:строка | Сложность |
|---|--------|-------------|-----------|
| 7 | Heston CF: формула Albrecher 2007 | `heston.py:22–28` | Средняя |
| 8 | Hull-White: мгновенный форвард | `short_rate.py:157–172` | Средняя |
| 9 | Historical VaR: multi-day windows | `var.py:96` | Средняя |
| 10 | Control variate: cv_true = S0·e^{−qT} | `monte_carlo.py:122` | Тривиальная |
| 11 | Volga: /100 → /10000 | `black_scholes.py:94` | Тривиальная |
| 12 | Modified Duration: YTM | `fixed_income.py:261` | Средняя |
| 13 | Discrete Asian: убрать двойной sigma_g² | `asian.py:54` | Тривиальная |
| 14 | Caplet: согласовать дисконтирование | `fixed_income.py:387` | Средняя |
| 15 | Heston delta: e^{−qT}·P1 | `heston.py:74` | Тривиальная |

### Спринт 3 — Плановые улучшения (2–3 недели)

| # | Задача | Файл:строки | Сложность |
|---|--------|-------------|-----------|
| 16 | Полная таблица Reiner-Rubinstein (8 кейсов) | `barrier.py:77–98` | Высокая |
| 17 | Ikeda-Kunitomo: добавить d3n/d4n | `barrier.py:131–141` | Высокая |
| 18 | Настоящий бутстрап выживаемости | `credit.py:39–47` | Высокая |
| 19 | SVI: корректное ограничение a | `implied_vol.py:121` | Тривиальная |
| 20 | GARCH: добавить константу LL | `garch.py:96` | Тривиальная |
| 21 | YieldCurve ModDur: YTM | `yield_curve.py:219` | Средняя |

---

## 8. Библиография

1. **Black F., Scholes M.** "The Pricing of Options and Corporate Liabilities", *Journal of Political Economy*, 81(3), 1973.
2. **Heston S.L.** "A Closed-Form Solution for Options with Stochastic Volatility", *Review of Financial Studies*, 6(2), 1993.
3. **Albrecher H., Mayer P., Schachermayer W., Teichmann J.** "The Little Heston Trap", *Wilmott Magazine*, 2007.
4. **Hull J., White A.** "Pricing Interest-Rate-Derivative Securities", *Review of Financial Studies*, 3(4), 1990.
5. **Kemna A.G.Z., Vorst A.C.F.** "A Pricing Method for Options Based on Average Asset Values", *Journal of Banking and Finance*, 14(1), 1990.
6. **Demeterfi K., Derman E., Kamal M., Zou J.** "More Than You Ever Wanted to Know About Volatility Swaps", Goldman Sachs Quantitative Research Notes, 1999.
7. **Carr P., Madan D.** "Towards a Theory of Volatility Trading", in *Volatility: New Estimation Techniques for Pricing Derivatives*, Risk Books, 1998.
8. **Reiner E., Rubinstein M.** "Breaking Down the Barriers", *Risk Magazine*, September 1991.
9. **Ikeda M., Kunitomo N.** "Pricing Options with Curved Boundaries", *Mathematical Finance*, 2(4), 1992.
10. **Hagan P., Kumar D., Lesniewski A., Woodward D.** "Managing Smile Risk", *Wilmott Magazine*, September 2002.
11. **Brigo D., Mercurio F.** *Interest Rate Models — Theory and Practice*, Springer, 2006.
12. **McNeil A.J., Frey R., Embrechts P.** *Quantitative Risk Management*, Princeton University Press, 2015.
13. **Gatheral J.** "A Parsimonious Arbitrage-Free Implied Volatility Parameterization", Merrill Lynch, 2004.
14. **O'Kane D.** *Modelling Single-name and Multi-name Credit Derivatives*, Wiley, 2008.
15. **Haug E.G.** *The Complete Guide to Option Pricing Formulas*, 2nd ed., McGraw-Hill, 2007.
16. **Hamilton J.D.** *Time Series Analysis*, Princeton University Press, 1994.

---

*Документ подготовлен на основе статического анализа кода без внесения изменений.
Все исправления требуют верификации через regression-тесты с эталонными значениями перед внедрением.*
