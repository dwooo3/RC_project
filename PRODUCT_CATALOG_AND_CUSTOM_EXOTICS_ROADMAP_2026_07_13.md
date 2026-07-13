# Product Catalogue & Custom Exotics Roadmap

**Дата аудита:** 2026-07-13

**Статус:** proposed implementation plan

**Область:** продуктовый каталог, структурные продукты, capture/repricing, lifecycle, Custom Product Engine
**Основные источники в коде:** `api/pricing_workstation.py`, `api/server.py`, `services/pricing_service.py`, `services/portfolio_service.py`, `domain/pricing_environment.py`, `domain/results.py`, `domain/scenario.py`, `instruments/`, `models/`, `macapp/Sources/RiskCalc/`

## 1. Резюме и прямой ответ

Нет, в текущем каталоге представлены не все значимые структурные продукты. Более того, для production-готовности недостаточно добавить ещё названия в меню: у продукта должны одновременно существовать строгий контракт сделки, валидируемые market data, допустимый pricer/model, воспроизводимый результат, risk/scenario analytics, capture, последующее repricing и lifecycle.

Текущее состояние сильное как количественная библиотека и pricing workstation:

- 50 продуктовых карточек в семи классах активов;
- 100 связок product/engine: 84 уникальных engine ID и 82 уникальных model ID;
- из 100 product/engine-связок 95 помечены `Validated`, 4 — `Approximation`, 1 — `Prototype`;
- 86 product/engine-связок имеют `production_allowed=true`;
- 16 из 50 продуктов имеют путь `TO_POSITION` для capture, то есть только 32% каталога можно передать в существующий portfolio workflow;
- для captured-позиций воспроизводится только канонический первый engine продукта, а произвольный выбранный engine не сохраняется как полноценная версия pricing policy.

Кроме основного каталога существует отдельный fixed-income/bond catalogue из 14 шаблонов в `api/instruments.py`. Таким образом, в двух UI/API-контурах фактически опубликовано 64 шаблона, но они не образуют единый registry и используют разные product/result contracts. Это не увеличивает production coverage до 64: сначала каталоги необходимо унифицировать.

Функциональности для создания собственной экзотики по множеству параметров пока недостаточно. Пользователь может настраивать параметры заранее заданного продукта, но не может безопасно описать произвольные наблюдения, события, состояния, ветвления, купоны, досрочное погашение, settlement и path dependency. Целевая архитектура должна быть не «ещё одна большая форма» и не исполнение пользовательского Python, а версионируемый декларативный Product Definition/Payoff Engine.

Главная рекомендация: сначала закрыть общий продуктовый контракт, lifecycle и parity между Pricing и Portfolio, затем расширять шаблоны. Иначе количество пунктов меню вырастет, а production-покрытие — нет.

## 2. Как измеряется полнота продукта

Наличие класса или формулы в `instruments/` либо `models/` не означает, что продукт готов для рабочего использования. Для этого плана используются уровни зрелости:

| Уровень | Определение | Минимальный результат |
|---|---|---|
| L0 — Quant primitive | В коде есть payoff, формула или модель | Unit-тест численного ядра |
| L1 — Catalogue | Продукт и engine опубликованы в catalogue | Schema параметров и governance metadata |
| L2 — Priceable | Сделка разрешается в полный pricing input | Цена, меры, ошибки и provenance |
| L3 — Risk-ready | Есть Greeks, factor mapping, scenarios и model eligibility | Стабильный risk contract |
| L4 — Position-ready | Есть capture и идентичное portfolio repricing | Round-trip Pricing → Portfolio → Pricing |
| L5 — Lifecycle-ready | Поддержаны fixing/event/cashflow/exercise/settlement/state transitions | Воспроизводимое состояние на любую дату |
| L6 — Production-approved | Версионирование, audit, maker-checker, limits, performance SLO | Контролируемый выпуск в production |

Значение `Validated` у engine — это важная характеристика model governance, но не доказательство уровней L4–L6 для продукта целиком.

## 3. Фактический каталог на 2026-07-13

### 3.1. Покрытие по классам активов

| Класс | Продуктов | Engine-связок | Capturable | Capture coverage |
|---|---:|---:|---:|---:|
| Equity | 12 | 43 | 5 | 41.7% |
| Rates | 9 | 16 | 6 | 66.7% |
| FX | 8 | 10 | 1 | 12.5% |
| Credit | 8 | 14 | 1 | 12.5% |
| Commodity | 2 | 4 | 0 | 0% |
| Inflation | 2 | 2 | 0 | 0% |
| Hybrid / Structured | 9 | 11 | 3 | 33.3% |
| **Итого** | **50** | **100** | **16** | **32.0%** |

45 из 50 продуктов имеют хотя бы один `production_allowed` engine. Без такого engine остаются `equity_swap`, `warrant`, `cds_index`, `cds_index_option` и `basket_note`. Это отдельный блокер: наличие карточки не должно создавать впечатление production-доступности.

### 3.2. Что уже опубликовано

| Класс | Продукты catalogue | Capturable сейчас |
|---|---|---|
| Equity | European, American, barrier, Asian, digital, lookback options; variance swap; equity forward/swap/future; dividend swap; warrant | European, barrier, Asian, digital, lookback |
| Rates | Term deposit, FRA, IRS, cap/floor, European and Bermudan swaptions, CMS swap, STIR future, bond future | FRA, IRS, cap/floor, European swaption, STIR future, bond future |
| FX | Forward, NDF, vanilla option, barrier, digital, Asian, lookback, cross-currency swap | FX forward |
| Credit | CDS/index/index option, asset swap, risky bond, structural credit, CDO tranche, kth-to-default | Single-name CDS |
| Commodity | Commodity option, commodity curve | — |
| Inflation | ZC inflation swap, YoY inflation swap | — |
| Hybrid | Spread/two-asset/basket/rainbow options, autocall, basket note, TARN, accumulator, convertible | Spread option, basket option, autocall |

### 3.3. Возможности, уже существующие в кодовой базе, но не превращённые в полный продуктовый workflow

Аудит `instruments/` и `models/` показывает дополнительный задел:

- digital variants: gap, one-touch, no-touch, double-no-touch, supershare;
- double barrier и Monte Carlo barrier;
- chooser, compound, forward-start, shout, power, cliquet, reset и range-accrual equity options;
- fixed/floating/callable/custom/amortizing/step/perpetual/linker bonds;
- OIS, basis swap, collar, bond option, CMS spread option;
- FX swap, risk reversal, strangle, straddle;
- exchange, quanto, Himalaya и Altiplano payoffs;
- volatility, gamma, corridor и conditional variance swaps;
- Phoenix, reverse convertible, principal-protected note, worst-of barrier reverse convertible;
- CLN, first-to-default basket, nth-to-default;
- MBS/ABS waterfall primitives.

Это ускоряет расширение, но каждый такой компонент пока следует считать L0/L1, пока не пройден общий Definition of Done из раздела 10.

### 3.4. Дополнительный bond/instrument catalogue

`api/instruments.py` отдельно публикует 14 fixed-income шаблонов: OFZ, fixed/step/amortizing/perpetual/custom bonds, FRN, inflation linker, callable/putable instruments, T-bill, commercial paper, deposit, repo и MBS. Их следует перенести в единый `ProductDefinitionRegistry`, сохранив migration aliases.

Сейчас также расходятся фактический workstation catalogue и `models/taxonomy.ENGINES`. Параллельные sources of truth создают риск, что Swift покажет одну model matrix, pricing dispatch использует другую, а Portfolio воспроизводит третью.

## 4. Что отсутствует в продуктовом списке

Полного конечного списка «всех структурных продуктов» не существует: рынок допускает новые комбинации payout и lifecycle. Практичная цель — покрыть основные торгуемые семейства готовыми шаблонами и предоставить безопасную композицию для остальных.

### 4.1. Высокоприоритетные семейства шаблонов

| Класс | Добавить в первую очередь | Следующая волна |
|---|---|---|
| Equity structured notes | Reverse convertible, barrier reverse convertible, capital-protected note, participation note, bonus certificate, worst/best-of autocall, Phoenix | Twin-win, callable yield note, cliquet note, dispersion/correlation note, outperformance note |
| Equity/FX exotics | One/no-touch, double barrier, chooser, compound, forward-start, cliquet, range accrual | Window barrier, Parisian, lookback variants, quanto/compo, multi-period digitals |
| FX structured | FX swap, TARF/TARN, accumulator, risk reversal, straddle/strangle, window/flexible forward | Dual-currency deposit/note, callable/target redemption structures, multi-currency basket |
| Rates | OIS, basis and cross-currency swaps, callable/putable/cancellable swap, CMS spread option, digital cap/floor | Ratchet/corridor/snowball, callable range accrual, Bermudan/callable bond, constant-maturity structures |
| Credit | CLN, CDS option, index tranche/base-correlation, first/nth-to-default | Callable CLN, recovery lock, quanto credit, credit spread option, equity-credit hybrid |
| Commodity | Forward, swap, Asian/average-price option, calendar/crack/spark spread | Swing, storage, take-or-pay, basket and multi-commodity structures |
| Inflation | ZC/YoY caps and floors, inflation-linked bond, LPI/RPI-linked products | Inflation swaptions, real-rate options, hybrid inflation/rates notes |
| Securitized | MBS/ABS pool, tranche and waterfall with prepayment/default | OAS, PAC/TAC/support tranches, IO/PO, scenario cashflow engine |
| Cross-asset hybrid | Quanto, dual-currency, equity-rate and equity-credit notes | Multi-asset callable notes, hybrid conversion/credit triggers |

### 4.2. Пробелы важнее новых названий

1. **Нет единого typed trade contract.** `Position.params` остаётся словарём, а schema workstation и portfolio domain расходятся.
2. **Нет общего event/cashflow graph.** Купон, observation, fixing, call, exercise, redemption и settlement не являются переиспользуемыми типизированными блоками.
3. **Нет полного lifecycle.** Нельзя надёжно восстановить состояние memory coupon, barrier hit, accrued amount, partial exercise или realised fixing на выбранную дату.
4. **Нет engine capability matrix.** Выбор модели не вычисляется из path dependency, exercise style, dimensionality, stochastic factors, market-data availability и governance policy.
5. **Нет capture/repricing parity для 34 продуктов.** Каталожная цена не гарантирует последующее portfolio full reprice.
6. **Нет versioned market/calibration bundle.** Pricing environment существует, но не фиксирует полностью curves, surfaces, fixings, calibration, model build и override reasons как один immutable bundle.
7. **Нет универсального risk mapping.** Требуются стабильные factor IDs, bucket conventions, quote units и cross-gamma semantics.
8. **Нет асинхронного расчётного слоя.** Тяжёлые grids, Monte Carlo, calibration и scenario batches должны иметь queue/progress/cancel/budgets.
9. **Нет workflow публикации custom product.** Нужны versioning, validation evidence, approval, deprecation и migration.
10. **Capture сейчас не lossless и не доказанно атомарен.** Отдельные adapters теряют `rebate`, numerical settings, CDS issuer, autocall memory/steps; запись позиции может предшествовать успешному repricing.
11. **Нет fail-closed server validation.** Runtime не обязан применять `ParameterSpec`, unknown fields могут игнорироваться, а неизвестный engine может заменяться default.
12. **Market dependencies не выводятся из продукта.** `surface_map` environment не применяется end-to-end, а значительная часть vol/correlation inputs остаётся ручными scalars.

## 5. Оценка текущей гибкости Custom Exotic

### 5.1. Что можно сделать сейчас

- выбрать одну из 50 карточек;
- выбрать опубликованный engine;
- изменять scalar/date/choice/schedule-параметры, предусмотренные schema;
- запустить price, ladder, 2D grid, payoff, implied volatility и ограниченный набор scenarios;
- capture для 16 явно сопоставленных типов.

### 5.2. Чего пользователь не может выразить

- произвольную последовательность observation/coupon/call/redemption events;
- memory, target, lock-in, ratchet и иные state variables;
- условия с несколькими underlyings и различными датами наблюдения;
- worst/best/average/ranked/conditional basket logic как композицию;
- continuous/discrete/window/barrier monitoring rules;
- несколько cashflow legs, currencies, calendars и settlement modes;
- early exercise, issuer call, holder put, physical delivery, conversion;
- realised fixings и изменение состояния сделки после события;
- funding, collateral, credit, recovery и quanto dependencies;
- пользовательские measures, factor mappings и model constraints;
- безопасное сохранение, версионирование и повторное исполнение собственной формулы.

**Итог:** текущая гибкость достаточна для parameterized templates, но не для Custom Exotic Engine production-уровня.

## 6. Целевая архитектура Custom Product Engine

### 6.1. Основной принцип

Custom product должен описываться декларативным, типизированным и версионируемым документом. Запрещаются `eval`, произвольный Python/Swift/JavaScript и загрузка пользовательских модулей в pricing process.

Отраслевые стандарты подтверждают нужное направление:

- [FINOS CDM Product Model](https://cdm.finos.org/docs/product-model/) строит economic terms из composable payout-блоков;
- [FINOS CDM Event Model](https://cdm.finos.org/docs/event-model/) отделяет неизменяемое определение продукта от состояния конкретной сделки и описывает lifecycle как state transitions;
- [FpML Product Summary](https://www.fpml.org/spec/index.html) даёт внешний ориентир для product coverage и interchange;
- [OpenGamma Strata API](https://strata.opengamma.io/apidocs/) разделяет immutable product/trade domain, market data, calculation measures, scenarios и pricers.

Нужно использовать эти источники как семантические ориентиры, но не копировать их модели целиком: внутренний contract должен оставаться компактным и соответствовать возможностям RiskCalc.

### 6.2. Версионируемые сущности

| Сущность | Назначение |
|---|---|
| `ProductDefinition` | Неизменяемая экономическая логика и metadata продукта |
| `ProductTemplate` | Опубликованный definition с параметрическими slots и defaults |
| `TradeTerms` | Конкретные значения slots, parties, quantity, price, dates |
| `TradeState` | Realised fixings, observed barriers, accrued/memory state, exercised/terminated state |
| `MarketContext` | Snapshot, curves, surfaces, fixings, reference data, overrides |
| `PricingPolicy` | Разрешённый model/engine, calibration, numerics, measures |
| `PricingRun` | Immutable request, input hash, seed, versions, result и audit |
| `BusinessEvent` | State transition: fixing, coupon, call, exercise, transfer, amendment, termination |

### 6.3. Типизированные building blocks

Минимальная версия DSL/AST должна включать:

- `Underlying`, `Observable`, `ReferenceDataRef`;
- `Date`, `Period`, `Calendar`, `BusinessDayAdjustment`, `Schedule`;
- `Money`, `Currency`, `Quantity`, `Rate`, `Price`, `Percentage`;
- `Constant`, `Parameter`, `StateVariable`, `Fixing`;
- арифметические операции, `min`, `max`, `average`, `rank`, `clamp`;
- логические условия и сравнения с явными units;
- `Basket` и aggregation: weighted, worst-of, best-of, nth, average;
- `Barrier` с direction, level, monitoring и observation source;
- `Coupon`, `Redemption`, `Cashflow`, `Leg`, `Settlement`;
- `Event`, `Condition`, `Exercise`, `Call`, `Put`, `Conversion`;
- state operations: set, accumulate, reset, lock, terminate;
- path operators: running average, extremum, count, consecutive observations;
- payout currency conversion и quanto/compo rules.

### 6.4. Два режима автора

1. **Template mode.** Пользователь клонирует утверждённый продукт и меняет разрешённые slots. Это default для FO и sales.
2. **Advanced graph/DSL mode.** Structurer/quant собирает event graph из разрешённых blocks, видит generated economic description и тестирует payoff. Публикация требует governance workflow.

Оба режима должны компилироваться в одинаковый внутренний `PayoffIR`; UI не должен становиться вторым pricing engine.

### 6.5. Pipeline компиляции

```text
ProductDefinition JSON
  → schema validation
  → name/type/unit/currency/date resolution
  → graph validation and path-dependency classification
  → PayoffIR + event/cashflow graph
  → engine capability matching
  → executable pricing plan
  → deterministic PricingRun
  → result + provenance + lifecycle instructions
```

### 6.6. Обязательные статические проверки

- JSON schema/version и неизвестные поля;
- типы, units и currency compatibility;
- schedule ordering, calendars, duplicate observations, maturity boundaries;
- отсутствие циклов и недостижимых branches;
- все state variables и fixings определены до использования;
- cashflow direction, settlement currency и payer/receiver;
- наличие payoff во всех terminating branches;
- bounded resource complexity: nodes, dates, paths, dimensions;
- path-dependency/exercise classification;
- совместимость engine с required features;
- наличие market data и reference data;
- governance eligibility для выбранной environment;
- предупреждения о discontinuity, unstable Greeks и extrapolation.

### 6.7. Engine capability contract

Каждый engine должен публиковать machine-readable capabilities:

- asset classes и supported payout primitives;
- max underlyings/factors;
- European/American/Bermudan/callable exercise;
- continuous/discrete monitoring;
- stochastic rates/vol/correlation/credit/recovery;
- analytic, tree, PDE, Fourier или Monte Carlo method;
- supported Greeks и risk factors;
- required market-data objects;
- calibration requirements;
- determinism/seed semantics;
- approximation/limitations;
- governance status и allowed environments;
- runtime/memory limits.

Engine выбирается compatibility resolver, а не только строкой из dropdown.

## 7. Приоритизированный backlog

### P0 — фундамент до расширения меню

| Epic | Результат | Критерий завершения |
|---|---|---|
| Product Contract v2 | Typed `ProductDefinition`, `TradeTerms`, schema registry и version migration | Один contract используется API, Swift, capture и portfolio |
| Unified Registry | Объединить основной catalogue, 14 bond templates и taxonomy/engine maps | Один versioned source of truth и migration aliases |
| Schedule/Cashflow/Event Core | Общие blocks для legs, observations, coupons, calls, redemptions и settlement | Не менее трёх разных семейств собираются без product-specific fields |
| Trade State & Lifecycle | Fixing/event store и детерминированные transitions | Сделка воспроизводится до/после coupon, call и maturity |
| Pricing Run Contract | Immutable inputs, versions, hash, seed, provenance и structured diagnostics | Один run можно повторить и получить объяснимо тот же результат |
| Capability Resolver | Product requirements ↔ engine/model/data/governance | Невалидная комбинация блокируется до расчёта |
| Atomic Capture/Repricing parity | Validate → pre-price → atomic persist; устранить `TO_POSITION` как узкое ручное отображение | Ошибка не оставляет позицию; round-trip для всех production product/engine pairs |
| Market/Calibration Bundle | Versioned curves/surfaces/fixings/calibrations/overrides | Result ссылается на полный immutable bundle |
| Async Calculation Jobs | Queue, progress, partial results, cancellation и quotas | MC/grid/scenario не блокируют request/UI thread |

### P1 — Custom Engine MVP и основные шаблоны

1. Реализовать AST/PayoffIR для scalar expressions, schedules, barriers, baskets, coupons, redemption и state.
2. Добавить template editor, clone/save/version/validate/compile/publish.
3. Поддержать Monte Carlo execution plan с common random numbers и reproducible seed.
4. Выпустить эталонные шаблоны: Phoenix, reverse convertible, capital-protected note, worst-of autocall, FX TARF, callable range accrual, CLN.
5. Довести FX option family, NDF, xccy, Bermudan swaption, CDS index/tranche и commodity Asian до L4.
6. Добавить generated natural-language term summary и machine-readable event/cashflow timeline.

### P2 — расширение классов и lifecycle

- rates structured family: CMS spread, snowball, corridor, ratchet, callable/putable swaps;
- credit baskets/tranches и callable CLN;
- commodity swing/storage/take-or-pay;
- inflation caps/floors и linked notes;
- securitized pool/waterfall/OAS;
- physical settlement, partial exercise, amendments, unwind и novation;
- interoperability adapters для FpML/CDM subsets.

### P3 — advanced structuring

- multi-currency and cross-asset event graph;
- reverse stress и solve-for coupon/barrier/strike;
- constrained structure optimization;
- exposure/XVA-aware pricing policy;
- controlled plugin SDK только для внутренних reviewed extensions, вне пользовательского runtime.

## 8. План реализации

Оценки ниже — плановый диапазон при команде backend/quant/frontend/QA, не календарное обещание.

| Фаза | Ориентир | Содержание | Exit criteria |
|---|---:|---|---|
| 0. Baseline | 1–2 спринта | Зафиксировать schemas, inventory, golden trades и maturity matrix | Все 50 продуктов классифицированы L0–L6 |
| 1. Contract foundation | 3–5 спринтов | Product/Trade/State/Market/PricingRun v2, migrations | API и Portfolio используют единые IDs/versions |
| 2. Event & payoff core | 4–6 спринтов | Schedule/cashflow/event blocks, AST, validators, PayoffIR | Собраны autocall, range accrual и CLN без special-case contract |
| 3. Execution & risk | 3–5 спринтов | Capability resolver, MC plan, Greeks, scenarios, async jobs | Reproducible price/risk и cancellation |
| 4. Authoring workflow | 3–5 спринтов | Template/advanced builder, validation, publish/approve | Custom definition проходит maker-checker и versioning |
| 5. Product waves | постоянно | P1/P2 templates по business score | Каждый продукт проходит общий DoD |
| 6. Production hardening | 2–4 спринта | SLO, audit, limits, security, recovery, load tests | Production readiness review пройден |

## 9. Как выбирать следующий продукт

Не следует планировать по принципу «закрыть как можно больше названий». Для каждого кандидата рассчитывается score:

| Фактор | Вес |
|---|---:|
| Business demand / expected usage | 25% |
| Reuse of new primitives by other products | 20% |
| Quant/model readiness | 15% |
| Market-data readiness | 10% |
| Risk and hedge relevance | 10% |
| Lifecycle/operations readiness | 10% |
| Regulatory/reporting relevance | 5% |
| Delivery effort and runtime cost | 5% |

Любой продукт с отсутствующим authoritative market data, lifecycle owner или validation owner не должен получать production flag независимо от итогового score.

## 10. Definition of Done для каждого нового продукта

Продукт считается production-ready только если выполнены все пункты:

- versioned typed schema и migration policy;
- положительные, отрицательные и boundary validation cases;
- authoritative market-data mapping, quote conventions и freshness policy;
- минимум один production-approved engine и documented fallback;
- independent benchmarks/golden trades и tolerance policy;
- price, cashflows, requested measures, Greeks и factor IDs;
- scenarios и explainability для ключевых risk drivers;
- convergence/error diagnostics для numerical methods;
- lossless сохранение экономического смысла при capture и совпадение Portfolio replay в утверждённом numerical tolerance;
- lifecycle events, fixings и state reconstruction;
- structured warnings/errors/limitations;
- immutable audit/provenance и deterministic seed policy;
- RBAC/maker-checker для overrides и custom definitions;
- unit, integration, property, regression и performance tests;
- Swift schema rendering без product-specific pricing logic;
- operator documentation и runbook.

## 11. Тестовая стратегия

### Контрактные тесты

- schema backward/forward compatibility;
- unknown enum/field handling в Swift;
- round-trip JSON canonicalization и input hash;
- Pricing → Capture → Portfolio → Reprice equivalence;
- environment/model/market version pinning.

### Quantitative tests

- closed-form limits и static replication где возможно;
- cross-engine comparison на frozen inputs;
- monotonicity, bounds, parity и homogeneity properties;
- convergence with steps/paths/grid refinement;
- common random numbers для what-if differences;
- adjoint/bump Greeks reconciliation.

### Lifecycle tests

- до/на/после observation date;
- missing/corrected fixing;
- barrier hit/no-hit, memory carry, target reached;
- call/exercise/termination/settlement;
- replay event history и idempotency.

### Operational tests

- cancellation, timeout, retry и duplicate idempotency key;
- large scenario batches и resource quotas;
- degraded/missing market data;
- audit completeness;
- recovery после worker restart.

## 12. Ключевые решения до начала P0

1. Утвердить канонический `ProductDefinition v2` и границы совместимости с FpML/CDM.
2. Выбрать durable store для immutable definitions, trade states, events и pricing runs.
3. Утвердить stable risk-factor taxonomy и units.
4. Назначить owners для product, quant model, market data, validation и lifecycle.
5. Определить environments и правила: research, FO indicative, FO executable, risk, EOD, regulatory.
6. Установить latency/resource SLO для analytic, PDE/tree, Monte Carlo и batch jobs.
7. Согласовать maker-checker и production publication workflow.

## 13. Рекомендуемая первая поставка

Первая целостная поставка должна доказать архитектуру на трёх разных формах path dependency:

1. **Worst-of Phoenix/autocall** — basket, observations, memory coupon, call и redemption state.
2. **Callable rates range accrual** — schedule, daily observations, coupon accrual и issuer exercise.
3. **Credit-linked note** — funding leg, credit event, recovery и contingent redemption.

Если эти три продукта проходят единый schema → validate → compile → price → scenario → capture → lifecycle → portfolio replay pipeline без специальных API-контрактов, фундамент достаточно гибок для дальнейшего расширения.

## 14. Итоговый статус

- Количественная база и breadth моделей: **сильные**.
- Каталог типовых продуктов: **широкий, но неполный**.
- Structured note coverage: **точечное и преимущественно шаблонное**.
- Capture/repricing parity: **критический пробел, 16/50**.
- Единый product registry: **отсутствует; 50 derivative + 14 bond templates разделены**.
- Lifecycle/event model: **требует нового общего слоя**.
- Custom exotic authoring: **недостаточно; нужен декларативный engine**.
- Правильный следующий шаг: **P0 product/lifecycle/run contracts, затем product waves**.
