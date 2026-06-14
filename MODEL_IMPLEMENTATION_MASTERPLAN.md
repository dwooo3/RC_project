# Мастер-план: глобальное внедрение всех моделей

**Дата:** 2026-06-13
**Цель:** довести RiskCalc до полного отраслевого покрытия моделей
([MODELS_CATALOGUE.md](MODELS_CATALOGUE.md)), исправив две системные проблемы:
(1) **группировка моделей** — текущая плоская таксономия не масштабируется;
(2) **ввод параметров** — поля фиксированы per-product, нет ручной настройки
каждого параметра модели.

Документ — фундамент (рефакторинг таксономии + параметрической системы),
затем фазы внедрения недостающих моделей.

---

## Часть A. Проблема 1 — таксономия (реструктуризация)

### A.1 Что сейчас (и почему не подходит)
- `models/registry.py`: плоское поле `domain ∈ {Pricing, Analytics, Risk,
  Portfolio, Market}` — это про слой, не про природу модели.
- `pricing_catalogue.py`: `CATEGORIES = [Fixed Income, Option, Equity, FX,
  Swaps, Structured Notes, Credit]` — смешивает **класс актива** (Equity, FX),
  **тип инструмента** (Option, Swaps) и **обёртку** (Structured Notes).
- Один инструмент жёстко привязан к одному движку (vanilla → BSM); нельзя
  выбрать «оценить барьер на Heston» или «бонд на PDE».

Это рушится при 150+ моделях: некуда класть Lévy-движки, нет места «выбрать модель».

### A.2 Новая таксономия — 3 независимые оси
Каждая модель/прайсер классифицируется по трём осям:

1. **Asset class** — `rates · credit · equity · fx · inflation · commodity · hybrid`
2. **Instrument** — что оцениваем (vanilla option, swaption, CDS, convertible…)
3. **Engine (model × method)** — чем оцениваем:
   - *model family*: `analytic · local_vol · stoch_vol · jump · levy · short_rate ·
     market_model · copula · structural · reduced_form`
   - *method*: `closed_form · lattice · pde · monte_carlo · fourier`

Пример: барьерный опцион (instrument) на акции (equity) можно оценить движками
{analytic/RR, pde/CN, mc/GBM, stoch_vol/Heston-MC, jump/Merton-MC}. Пользователь
выбирает asset class → instrument → engine.

### A.3 Изменения в коде
- `models/registry.py`: заменить `domain` на `asset_class`, `model_family`,
  `method`, `instruments` (список применимых). Добавить `ENGINES` — реестр
  «instrument → допустимые движки». Сохранить статус/тесты/notes.
- Новый `models/taxonomy.py`: перечисления осей + матрица instrument×engine.
- `pricing_catalogue.py`: продукт = (asset_class, instrument); движок —
  выбираемый параметр, а не зашит в `price`.
- UI: трёхуровневый выбор (asset class chips → instrument dropdown →
  engine dropdown), вместо одного CATEGORIES-сегмента.

---

## Часть B. Проблема 2 — параметрическая система (ручная настройка)

### B.1 Что сейчас
`Field(key, label, default, choices, wide)` — плоский список, всё «вручную
вбей число». Нет групп, нет диапазонов, нет связи со снапшотом, и **нет полей
для параметров моделей** (Heston κ/θ/ξ/ρ/v0, SABR α/β/ρ/ν, jump λ/μ_J/δ_J,
численных n_sims/steps/grid/scheme). Добавить модель = переписать форму.

### B.2 Новая система — `ParameterSpec` с группами
```python
@dataclass
class ParameterSpec:
    key: str
    label: str
    default: float | str
    group: str          # contract | market | model | numerical
    dtype: str = "float"   # float | int | choice | text | date | schedule
    choices: list | None = None
    minimum: float | None = None
    maximum: float | None = None
    source: str = "manual"   # manual | snapshot:<curve_id> | snapshot:fx:<pair> | derived
    advanced: bool = False
    unit: str = ""
    help: str = ""
```

**Четыре группы параметров** (всегда видны contract+market; model+numerical —
в сворачиваемой секции «Advanced», но КАЖДЫЙ редактируем):
- **contract** — термины сделки (strike, maturity, notional, freq, opt type).
- **market** — рыночные входы (spot, rate, vol, div); `source` тянет из снапшота
  с возможностью переопределить вручную (override-флажок у поля).
- **model** — параметры выбранного движка (Heston κ/θ/ξ/ρ/v0; SABR α/β/ρ/ν;
  Merton λ/μ_J/δ_J; HW κ/σ; …). Появляются динамически по выбору engine.
- **numerical** — настройки метода (n_sims, steps, tree N, PDE grid Ns/Nt,
  scheme euler/qe, FFT N/α, seed).

### B.3 Изменения в коде
- Новый `models/parameters.py`: `ParameterSpec` + библиотека готовых наборов
  параметров на движок (`ENGINE_PARAMS["heston"] = [...]`).
- `pricing_catalogue.py`: продукт описывает contract+market параметры; model+
  numerical берутся из выбранного движка автоматически.
- `pricing_detail.py`: рендер по группам — секции Contract / Market (с
  override) / Advanced (Model + Numerical, collapsible). Каждый параметр
  получает тип-специфичный виджет (spin/combo/date/schedule) с min/max
  валидацией.
- Снапшот-подстановка: market-параметры с `source=snapshot:*`
  предзаполняются из активного снапшота (app.runtime), флажок «manual» отвязывает.

### B.4 Результат
Любой инструмент × любой совместимый движок; каждый параметр модели и метода
настраивается вручную (как в Numerix/Murex pricing blotter), с дефолтами из
рынка и валидацией диапазонов.

---

## Часть C. Фазы внедрения моделей

Порядок: фундамент (M0) → дешёвые/ценные движки → стратегические.
Каждая фаза: **identity/benchmark-тест первым**, затем движок (presenter-first),
регистрация в новой таксономии, параметры в `ENGINE_PARAMS`, UI авто-подхватывает.

### M0 — Фундамент (таксономия + параметры) — 4-6 дней
Части A и B целиком. Без этого новые модели некуда класть и нечем настраивать.
Миграция существующих 66 моделей в новую таксономию; существующие fields →
ParameterSpec (автоконвертер). Все 586 тестов остаются зелёными.

### M1 — Lévy / скачки + Fourier-движки — 5-7 дней
Дёшево, высокая ценность (fat tails, быстрая калибровка):
- Kou (double-exponential), Variance Gamma, CGMY, NIG.
- Fourier: Carr-Madan FFT, COS-метод (Fang-Oosterlee) — общий движок для всех
  моделей с известной CF (Heston/Bates/VG/CGMY/NIG).
- Калибровка CF-моделей к рыночной поверхности (SVI/смайл уже есть).

### M2 — Продвинутая стох-вол — 5-7 дней
- Stochastic-Local Vol (SLV, particle/PDE).
- ZABR / no-arbitrage SABR (Hagan 2014), Antonov.
- Rough volatility (rough Bergomi, rough Heston) — современный фронт.
- Промоут heston_cf/mc_heston/sabr/bates из Prototype через бенчмарк-харнес.

### M3 — Рыночные модели ставок — 8-10 дней
- Hull-White 2F / G2++, Black-Karasinski.
- HJM, LIBOR Market Model (LMM/BGM), SABR-LMM, Cheyette.
- Path-dependent ставочная экзотика (Bermudan/callable на LMM, TARN).
- Cross-currency basis bootstrap (под XCCY).

### M4 — XVA-полнота — 6-8 дней
- FVA, MVA (initial margin / SIMM), KVA, ColVA.
- Netting sets + collateral (CSA), wrong-way risk.
- American Monte Carlo для экспозиций портфеля (микс инструментов).

### M5 — Commodity — 4-5 дней
- Gibson-Schwartz (2-фактор), Schwartz-Smith (short/long).
- Mean-reverting (Pilipovic), сезонность.
- Спред-опционы Bjerksund-Stensland; на готовых фьючерсных кривых (есть).

### M6 — Численные методы (добор) — 4-5 дней
- Американские аналитич. аппрокс.: Barone-Adesi-Whaley, Bjerksund-Stensland.
- Quasi-MC (Sobol/Halton) с Brownian bridge.
- ADI для 2D PDE (Heston-PDE, quanto).
- Биномиальные Jarrow-Rudd/Tian.

### M7 — Кредит (добор) — 5-6 дней
- ISDA standard CDS model (IMM-даты, fixed coupon + upfront).
- Structural: Black-Cox, KMV/Merton-distance-to-default.
- t-copula / Clayton / Marshall-Olkin; base correlation для траншей.

### M8 — Прочее / нишевое — по запросу
- Convertible AFV (Ayache-Forsyth-Vetzal PDE с кредитом).
- MBS/prepayment (PSA/OAS) — нужен источник пулов.
- FRTB SA + IMA, регуляторный капитал.
- Displaced diffusion, CEV, discrete-dividend Merton.

---

## Часть D. Сквозные принципы

1. **Identity-first**: каждый движок входит с тестом-тождеством/бенчмарком
   (предельный случай, паритет, сверка с эталоном) — иначе статус ≤ Prototype.
2. **Промоушн статуса**: Prototype → Approximation (тождества) → Validated
   (эталонный бенчмарк + синхронный `tests[]`); из STATE_AUDIT F1.
3. **Presenter-first UI**: движок → ParameterSpec → авто-рендер формы; никакого
   ручного Qt на каждую модель.
4. **Снапшот-связь**: market-параметры по умолчанию из app.runtime, ручной
   override доступен всегда.
5. **Бенчмарк-харнес**: единый модуль сверки CF/MC/PDE/аналитики между собой
   и с опубликованными значениями (расширение validation_audit).

## Часть E. Порядок и оценка
M0 — обязателен первым (без него остальное некуда встраивать). Дальше по
ценности для рынка РФ и стоимости: **M1 (Lévy+Fourier) → M2 (стох-вол) →
M4 (XVA) → M3 (rate market models) → M5/M6/M7 → M8**. Суммарно ~50-65
человеко-дней до near-complete отраслевого покрытия; каждая фаза самодостаточна
и оставляет тесты зелёными.
