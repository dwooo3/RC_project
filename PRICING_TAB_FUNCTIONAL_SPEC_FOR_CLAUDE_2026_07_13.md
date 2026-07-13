# Pricing Workspace — Production Functional Specification for Claude

**Дата:** 2026-07-13

**Статус:** implementation-ready functional blueprint

**Исполнитель Swift-оболочки:** Claude

**Design ownership:** Claude; этот документ задаёт функции, данные, состояния, контракты и критерии приёмки, но не предписывает визуальный стиль

**Целевые клиенты:** macOS SwiftUI в первую очередь; API должен оставаться пригодным для web/automation
**Связанный roadmap:** `PRODUCT_CATALOG_AND_CUSTOM_EXOTICS_ROADMAP_2026_07_13.md`

## 1. Цель

Создать production-grade Pricing Workspace, в котором пользователь может:

- выбрать стандартный продукт или версию custom product;
- полностью задать economic terms и lifecycle state;
- выбрать воспроизводимый market snapshot/environment;
- выбрать только совместимую и разрешённую model/engine/calibration configuration;
- валидировать и разрешить все inputs до запуска;
- получить price, quote, cashflows, Greeks, measures и diagnostics;
- проводить payoff, sensitivity, scenario, what-if, simulation, convergence и model-comparison analysis;
- конструировать custom exotic из безопасных декларативных primitives;
- сохранить template/draft/run, согласовать расчёт и атомарно capture сделку в Portfolio;
- воспроизвести любой прошлый расчёт по immutable IDs и hashes.

Swift-клиент является управляемой schema-driven оболочкой. Pricing logic, model eligibility, default resolution, market-data selection и validation остаются на backend.

## 2. Не входит в задачу

- конкретная визуальная тема, цветовая палитра, typography и декоративная композиция;
- перенос pricing formulas в Swift;
- выполнение пользовательского Python/JavaScript/Swift;
- обещание поддержки произвольной экзотики до реализации backend Custom Product Engine;
- скрытая подмена отсутствующих market data или неподдерживаемой модели;
- silent fallback на другой engine;
- сохранение позиции до успешной validation и pre-price.

Claude может выбирать layout и interaction patterns, но не должен менять описанные ниже бизнес-состояния, contract semantics и governance gates.

## 3. Текущий baseline

### 3.1. Существующие сильные стороны

- `api/pricing_workstation.py` публикует metadata-driven catalogue: 50 продуктов, 100 product/engine-связок, группы параметров, defaults, ranges, choices, units, help и governance.
- Swift уже строит общую форму по schema, а не отдельный экран на каждый продукт.
- Есть базовый price, ladder, 2D grid, payoff, implied volatility, scenario pack и underlying lookup.
- Результат нормализует value, Greeks, measures, series, warnings, errors и limitations.
- Есть pricing environments и 16 capture adapters.

### 3.2. Ограничения, которые новая реализация обязана устранить

1. Derivative catalogue из 50 продуктов и bond/instrument catalogue из 14 шаблонов живут отдельно и используют разные contracts.
2. Только 16/50 продуктов capturable; сохраняется лишь canonical first engine.
3. Capture теряет отдельные terms, включая barrier rebate, Asian numerical settings, CDS issuer и autocall memory/steps.
4. Позиция может сохраниться до успешного repricing; pricing exception после записи подавляется.
5. `ParameterSpec` не является обязательным runtime validator; неизвестные поля могут игнорироваться.
6. Неизвестный engine в базовом price может быть заменён default engine вместо ошибки.
7. Часть опубликованных numerical controls не передаётся в фактический pricer; наличие поля в catalogue ещё не доказывает его влияние.
8. Environment применяется непоследовательно: ladder/grid/payoff/scenarios/capture могут использовать active context вместо выбранного environment.
9. `surface_map` и `measures` environment не работают end-to-end.
10. Market-data selectors покрывают лишь часть продуктов; многие options/structured products используют ручные scalar vol/correlation inputs.
11. Pricing result теряет часть уже доступного provenance: calculation ID, input hash, model version/owner, snapshot lineage/quality и audit metadata.
12. Grid, ladder и Monte Carlo выполняются синхронно; progress/cancel/quotas отсутствуют.
13. Swift `BridgeValue` недостаточен для typed arrays, objects, legs, schedules и matrices.
14. Графический contract ограничен XY series и простой heatmap.
15. Ошибки некоторых вторичных расчётов подавляются через `try?` и не видны пользователю.
16. Текущий API не имеет production auth/entitlement boundary, а CORS разрешает `*`; это блокер выпуска, а не UI-задача «на потом».

Новая вкладка не должна маскировать эти backend-пробелы. Функции, для которых contract ещё не реализован, включаются capability flags и показываются как недоступные с машинно-читаемой причиной.

## 4. Product principles

1. **Server authoritative.** Backend определяет schema, defaults, compatibility, validation, market dependencies и result semantics.
2. **Fail closed.** Неподдерживаемая модель, stale/missing data, неизвестный параметр или governance violation блокируют production run.
3. **Immutable evidence.** Каждый расчёт имеет run ID, canonical request hash и полный provenance.
4. **One context everywhere.** Один `PricingContext` применяется к price, charts, scenarios, simulations, capture и subsequent reprice.
5. **No hidden defaults.** Для каждого resolved input виден источник: trade, template, environment, market, model default или governed override.
6. **Schema-driven UI.** Новый product/engine не требует отдельной Swift-формы.
7. **Async by default for heavy work.** Monte Carlo, calibration, grids, scenario sets и comparisons являются cancellable jobs.
8. **Comparable results.** Все значения содержат measure ID, unit, currency/quote convention и factor identity.
9. **Progressive complexity.** Простая сделка запускается быстро; advanced parameters доступны без потери полноты.
10. **Accessible and testable.** Каждое состояние доступно keyboard/VoiceOver и воспроизводится fixtures.

## 5. Пользователи и основные workflows

| Роль | Основной workflow | Особые права/ограничения |
|---|---|---|
| Trader / Structurer | Создать/изменить terms, price, Greeks, what-if, compare models | Governed overrides; publish custom product только через approval |
| Sales | Использовать утверждённые templates, indicative price и payoff | Нет model/numerical overrides production-класса |
| Quant | Диагностировать model, calibration, convergence, simulations | Research environments; не может маркировать модель production-approved единолично |
| Model Validator | Сравнить engines, увидеть evidence/limitations, approve policy | Read/approve, immutable comments/evidence |
| Risk | Запустить scenarios, sensitivities, capture и portfolio replay | Только certified snapshots/models для official runs |
| Operations | Lifecycle, fixings, cashflows, settlement и exceptions | Не меняет pricing model без отдельного разрешения |
| Auditor | Воспроизвести run и просмотреть lineage | Read-only, без скрытых полей |

### Обязательные пользовательские сценарии

1. Быстрая indicative valuation стандартного продукта.
2. Полная production valuation с pinned snapshot и approved engine.
3. Клонирование template и изменение структуры.
4. Сравнение двух или более models на одинаковых resolved inputs.
5. 1D/2D/N-D what-if с выбором output measure.
6. Monte Carlo distribution и convergence analysis.
7. Solve-for strike/coupon/barrier/vol/price.
8. Сохранение draft и восстановление без запуска.
9. Re-run исторического расчёта с тем же context.
10. Roll-forward на новую дату/snapshot с объяснением difference.
11. Policy-required approval и атомарный capture.
12. Построение, валидация и публикация custom exotic.

## 6. Два уровня состояния

### 6.1. Бизнес-состояние workspace

```text
Draft → Validated → Priced ───────────────→ Captured
  ↑         │          └→ Approved ───────→    ↑
  └─ edited/stale ─────┴───────────────────────┘
```

- `Draft`: есть несохранённые либо невалидированные inputs.
- `Validated`: server подтвердил schema, terms, data dependencies и model eligibility.
- `Priced`: существует completed immutable run для текущего input hash.
- `Approved`: run прошёл maker-checker workflow, когда его требует product/environment/override policy.
- `Captured`: создана position/trade reference; результат capture содержит replay evidence.
- Если approval policy не применяется, eligible `Priced` run может перейти сразу в `Captured`; если применяется — capture разрешён только из `Approved` для того же exact run hash.
- Любое изменение economic, market, model или numerical input делает прежний result `stale`, но не удаляет его.

### 6.2. Техническое состояние расчёта

```text
idle → validating → resolving → submitting → queued → running
                                                ├→ partial
                                                ├→ completed
                                                ├→ failed
                                                └→ cancelling → cancelled
```

Дополнительные состояния: `offline`, `reconnecting`, `expired`, `stale`, `permissionDenied`.

UI никогда не должен представлять stale result как результат текущих inputs.

## 7. Функциональные области workspace

Это функциональное деление, не обязательный layout.

### 7.1. Product & Template

- поиск по product ID/name/asset class/family/tag;
- recently used, favourites и approved desk templates;
- distinct labels для Standard, Custom Draft, Custom Published, Deprecated;
- product/version selector;
- clone as draft;
- product capability summary: path dependency, exercise, underlyings, market dependencies, compatible engines;
- migration warning при открытии старой version;
- сравнение terms двух versions.

### 7.2. Trade Terms & Lifecycle

- contract, underlyings, quantities/notionals, currencies, dates;
- legs, schedules, calendars, day counts и business-day conventions;
- observation/fixing/coupon/call/redemption schedules;
- barrier/basket/correlation matrices;
- settlement, physical/cash delivery, premiums и fees;
- realised fixings и current trade state;
- projected event/cashflow timeline;
- validation summary с переходом к конкретному полю;
- import/export canonical JSON, но только после schema validation.

### 7.3. Market Context

- valuation date/time/timezone;
- environment ID/version/purpose;
- snapshot ID/version/as-of/source/quality;
- curves, surfaces, cubes, fixings, dividends, borrow, recovery, correlation, reference data;
- dependency resolution status по каждому объекту;
- stale/missing/extrapolated indicators;
- governed override с old/new value, reason, owner и expiry;
- возможность сравнить два snapshots без изменения сделки;
- запрет production run при несертифицированном dependency, если policy не разрешает exception.

### 7.4. Model, Engine & Numerics

- только compatible engines по resolved product requirements;
- model family, method, version, owner, governance status;
- production/research eligibility и limitations;
- calibration ID/version/time/status/residual summary;
- numerical parameters с units/ranges и estimated cost;
- seed, random generator, antithetic/control variate/QMC settings;
- PDE/tree/grid/paths/time steps/convergence controls;
- requested measures;
- reference engine для comparison;
- причина недоступности engine;
- reset to policy defaults;
- явный diff от environment/template defaults.

#### Model/pricer catalogue requirements

Клиент обязан выводить все определения, возвращённые registry, и группировать их по capabilities, не по hardcoded списку. Registry должен покрывать как минимум следующие семейства: analytic/closed-form, approximation, lattice/tree, PDE/FDM, Fourier/characteristic-function, Monte Carlo/QMC/LSM, local/stochastic/rough volatility, jump/Lévy, rates term-structure and short-rate, LMM, credit reduced-form/structural/correlation, commodity/seasonal, inflation, securitized cashflow/waterfall и hybrid/multi-factor.

Для каждого `EngineDefinition` показываются либо доступны в details:

- stable engine/model IDs and versions;
- product/payout capabilities и incompatibility reasons;
- method and model family;
- required market objects and calibrations;
- complete parameter schema, defaults, units, ranges and constraints;
- supported outputs/Greeks/scenarios/simulations;
- numerical complexity, deterministic/seed semantics and limits;
- validation/governance status, owner, approval date and allowed environments;
- known limitations, benchmark evidence and deprecation;
- expected latency class and async requirement.

`ModelDefinition` и `EngineDefinition` не следует смешивать: одна model может иметь несколько numerical engines, а один product может поддерживать несколько model/engine combinations.

### 7.5. Validation & Run Control

- local format validation для немедленной обратной связи;
- authoritative server validation;
- resolved-input preview;
- cost estimate и sync/async classification;
- Run, Cancel, Retry, Clone Run;
- queue position, phase, progress, elapsed time и partial result readiness;
- idempotency: повторный submit одного request не создаёт дубликат;
- сохранение run history в рамках workspace.

### 7.6. Results & Evidence

- headline value/quote с currency, unit, scale и valuation timestamp;
- requested measures и Greeks;
- cashflows/events;
- warnings, limitations и errors без потери structured detail;
- provenance, calculation ID, request hash и consumed market objects;
- runtime/numerical diagnostics;
- download/export machine-readable result;
- approve/capture только для eligible completed run.

### 7.7. Reference functional mockup

Ниже показана карта функций, а не требование к геометрии или стилю. Claude может изменить размещение, если сохраняет доступность контекста, состояния и evidence.

```text
Workspace identity / Draft-Validated-Priced-[Approved if required]-Captured / input hash
────────────────────────────────────────────────────────────────────────
Product + version | Template | Environment + snapshot | Engine + model
────────────────────────────────────────────────────────────────────────
Authoring/configuration                 Validation and run control
  Product terms                          Issues by field
  Legs & schedules                       Resolved dependencies/defaults
  Lifecycle state                        Cost / queue / progress
  Market context                         Validate / Run / Cancel
  Model & numerics
  Custom definition, when enabled
────────────────────────────────────────────────────────────────────────
Current immutable result / historical stale results
  Valuation | Cashflows & events | Greeks | What-if | Simulation
  Models & calibration | Diagnostics | Provenance & audit
────────────────────────────────────────────────────────────────────────
Save draft | Clone | Export | Submit/Approve | Atomic Capture
```

Инварианты функционального макета:

- выбранные product version, environment/snapshot и engine видны при любом result view;
- validation/running/stale/research status нельзя определить только по цвету;
- switching result tabs не изменяет inputs;
- historical result остаётся доступным после edit, но явно отделён от current draft;
- Capture относится к конкретному immutable run, а не к текущему внешнему виду формы.

## 8. Schema-driven parameter contract

Swift не должен хардкодить формы 50 продуктов. Backend публикует `FieldSchema` и `GroupSchema`.

### 8.1. Поддерживаемые типы

| Schema type | Swift semantic type | Пример |
|---|---|---|
| `decimal` | `Decimal` | strike, rate, volatility |
| `integer` | `Int` | steps, paths |
| `boolean` | `Bool` | memory coupon |
| `string` | `String` | free description |
| `enum` | forward-compatible enum/value | call/put, buy/sell |
| `local_date` | date-only type | maturity |
| `instant` | `Date` + timezone metadata | market as-of |
| `period` | typed tenor/period | 3M, 5Y |
| `currency` | ISO currency value | USD |
| `money` | amount + currency | premium |
| `quantity` | amount + unit | commodity quantity |
| `percentage` | decimal + display scale | coupon |
| `quote` | value + quote convention | FX/price/yield |
| `reference` | stable object ID/version | curve, surface, underlying |
| `schedule` | structured dates/rules | observation dates |
| `vector` | typed homogeneous vector | basket weights |
| `matrix` | labelled typed matrix | correlations |
| `table` | repeatable typed rows | cashflow leg |
| `object` | nested schema | settlement terms |
| `union` | discriminated variants | cash vs physical settlement |
| `expression` | approved AST only | custom payoff expression |

На transport boundary требуется recursive `JSONValue` с `null/bool/number/string/array/object`, но после decode значения должны проходить schema/type resolution. Денежные и иные точные decimal-поля не хранить в `Double` и передавать в canonical decimal-string format из §9.1.

### 8.2. Поля schema

Каждое поле должно иметь:

- stable `field_id` и JSON pointer;
- label/help/category/order;
- type, unit, currency/quote semantics;
- required/default/read-only/advanced;
- min/max/exclusive bounds/step/precision;
- enum values с stable IDs и display labels;
- source: trade/template/environment/market/model/generated;
- visibility/required/enabled conditions;
- cross-field constraint references;
- sensitivity/scenario eligibility;
- override policy;
- deprecation/replacement;
- confidentiality if applicable;
- examples.

### 8.3. Validation response

Каждая проблема содержит:

```json
{
  "code": "OBSERVATION_AFTER_MATURITY",
  "severity": "error",
  "message": "Observation date must not exceed maturity",
  "json_pointer": "/trade/terms/observations/7/date",
  "related_pointers": ["/trade/terms/maturity"],
  "source": "product_rule",
  "suggested_fix": {"kind": "set_value", "value": "2031-06-20"},
  "documentation_uri": "/docs/errors/OBSERVATION_AFTER_MATURITY"
}
```

Client может предлагать fix, но применяет его только после действия пользователя.

### 8.4. Conditions and extension policy

`visible_when`, `required_when` и `enabled_when` используют один безопасный condition AST. Разрешены только:

- `and`, `or`, `not`;
- `eq`, `ne`, `lt`, `lte`, `gt`, `gte`;
- `in`, `contains` для явно совместимых scalar/list types;
- `exists` и `is_null`;
- ссылки на поля только через schema-declared JSON pointers;
- typed literals без функций, regex, network/file access и произвольного кода.

Пример:

```json
{
  "op": "and",
  "args": [
    {"op": "eq", "field": "/trade/terms/settlement/type", "value": "physical"},
    {"op": "exists", "field": "/trade/terms/underlying/security_id"}
  ]
}
```

Backend вычисляет условия авторитетно; Swift использует ту же семантику только для responsive rendering. Ошибка evaluation блокирует validation, а не делает поле молча видимым/невидимым.

По умолчанию object schemas имеют `additionalProperties: false`. Расширения допустимы только в объявленном namespaced `extensions` object с отдельной schema/version. Swift может сохранять неизвестное optional extension value только внутри такого разрешённого namespace; неизвестные business fields вне него отклоняются fail-closed.

## 9. Pricing context and resolution

Один `PricingContext` обязателен для всех расчётов:

```json
{
  "valuation_instant": "2026-07-13T12:00:00+03:00",
  "environment": {"id": "FO_INDICATIVE", "version": 12},
  "market_snapshot": {"id": "mkt-20260713-1200", "version": 4},
  "reference_data_version": "ref-2026.07",
  "calibration_policy_id": "desk-default-v8",
  "override_set_id": null,
  "reporting_currency": "USD"
}
```

`resolve` возвращает:

- canonical trade terms;
- applied defaults с источником каждого значения;
- consumed and missing dependencies;
- eligible model/engine combinations и причины исключения остальных;
- selected calibration artifacts;
- effective numerical configuration;
- validation issues;
- estimated calculation class/cost;
- canonical input hash.

Swift отправляет только user intent и explicit overrides. Он не должен всегда повторно отправлять catalogue defaults, иначе environment policy не сможет их заменить.

### 9.1. Canonical serialization and hash

Canonical request создаёт и хеширует backend; Swift может проверить его, но server hash остаётся authoritative. Правила обязательны для Python/Swift parity:

- точные economic/model decimals передаются JSON strings без exponent и leading `+`; trailing fractional zeros удаляются, `-0` нормализуется в `0`;
- integer counters/versions остаются JSON integers;
- `NaN`, `Infinity` и `-Infinity` запрещены;
- object keys сортируются lexicographically по Unicode code points; insignificant whitespace отсутствует; encoding — UTF-8;
- `local_date` — `YYYY-MM-DD`; instant нормализуется в UTC `Z` с фиксированной политикой fractional seconds;
- absence и explicit `null` различаются согласно schema;
- array order сохраняется; schema-declared sets сортируются по stable ID до сериализации;
- enum/reference IDs используют canonical raw values, не localized labels;
- canonicalization version включается в preimage;
- `request_hash = SHA-256(canonicalization_version || 0x00 || canonical_json_bytes)`.

Любая migration, меняющая экономический смысл или canonical bytes, создаёт новую product/schema version; старые runs сохраняют прежний canonicalization version.

## 10. PricingRun contract

### 10.1. Request

```json
{
  "schema_version": "2.0",
  "client_request_id": "019b...",
  "purpose": "fo_indicative",
  "product": {
    "id": "autocall",
    "version": "2.1.0",
    "definition_hash": "sha256:..."
  },
  "trade": {
    "trade_id": null,
    "terms": {},
    "state_id": null
  },
  "context": {},
  "pricing_policy": {
    "model": {
      "id": "local_vol_multi_asset",
      "version": "2.3.0",
      "parameters": {}
    },
    "engine": {
      "id": "autocall_mc",
      "version": "3.4.1"
    },
    "calibration_ids": [],
    "numerical": {"paths": 200000, "seed": 731944},
    "requested_measures": ["pv", "delta", "vega"]
  },
  "analytics": [],
  "tags": {"workspace_id": "ws-..."}
}
```

HTTP header `Idempotency-Key` обязателен для create/capture/publish operations.

### 10.2. Accepted response

```json
{
  "run_id": "prun-...",
  "status": "queued",
  "request_hash": "sha256:...",
  "queue": {"position": 2},
  "links": {
    "self": "/api/v2/pricing/runs/prun-...",
    "events": "/api/v2/pricing/runs/prun-.../events",
    "result": "/api/v2/pricing/runs/prun-.../result"
  }
}
```

### 10.3. Result envelope

Обязательные поля:

- `run_id`, `calculation_id`, `status`, `request_hash`, timestamps/duration;
- product ID/version/definition hash;
- trade/state IDs and versions;
- engine/model ID/version/governance/owner;
- environment/snapshot/reference/calibration IDs and fingerprints;
- complete resolved inputs or secure reference to immutable artifact;
- consumed market objects and their quality;
- headline value: amount, currency, unit, quote convention;
- typed measures;
- sensitivities with stable factor IDs, tenors/nodes, units and bump convention;
- projected/realised cashflows and events;
- numerical diagnostics, confidence intervals and convergence;
- structured warnings/errors/limitations;
- audit actor/purpose/override reasons;
- server build and pricing-library versions.

## 11. Result analytics

### 11.1. Valuation

- PV/NPV/clean/dirty/quote/yield/spread в зависимости от product capabilities;
- premium, accrued, carry/theta и settlement value;
- base/reporting currency conversion с FX lineage;
- bid/mid/ask, если snapshot и policy это поддерживают;
- comparison with reference/previous run.

### 11.2. Greeks and factor risk

- delta/gamma/vega/theta/rho и product-specific measures;
- curve-node PV01/DV01, bucketed vega, CS01, recovery, correlation, inflation, commodity and FX risk;
- stable `risk_factor_id`, source quote, node/tenor, bump type/size;
- aggregation hierarchy: underlying → curve/surface → asset class → total;
- first- and supported second-order cross sensitivities;
- method: analytic/AAD/bump and numerical error warning.

### 11.3. Cashflows and events

- projected and realised cashflows;
- event type, observation/fixing/payment dates;
- payer/receiver, currency, amount/formula/state;
- discount factor, present value and source inputs;
- call/exercise/redemption probability where applicable;
- timeline remains data, not only a rendered chart.

### 11.4. Diagnostics

- calibration residuals and rejected quotes;
- convergence by paths/steps/grid;
- standard error/confidence interval;
- runtime breakdown and resource usage;
- extrapolation, non-smooth payoff and unstable Greek warnings;
- model limitations and governance evidence.

## 12. Required visualization data contracts

Claude выбирает visual design and chart implementation. Backend/API должны уметь вернуть данные для:

| Visualization | Required semantics |
|---|---|
| Payoff/PV profile | x variable, valuation horizon, current marker, payoff and PV series |
| 1D sensitivity/ladder | factor, shock unit, base point, one or more measures |
| 2D heatmap/surface | two factors, labelled axes, cells, missing/error masks |
| Term structure | dates/tenors, zero/forward/discount/spread values |
| Vol smile/surface | expiry, strike/delta, vol, market/model, residual |
| Cashflow/event timeline | typed events and cashflows with state/probability |
| Histogram/PDF/CDF | bins/points, probability mass, percentiles, moments |
| Path fan | time grid, percentile bands, optional sampled paths |
| Convergence | effort axis, estimate, error/confidence bands, reference |
| Greeks by factor/node | factor IDs, signed values, units and hierarchy |
| Scenario waterfall | ordered contribution from base to shocked value |
| Tornado | low/high shock outcomes and ranking |
| Model comparison | price/risk/runtime/error/governance per engine |
| Event/state tree | branches, conditions, probabilities and payments |

Каждый chart payload содержит title/measure/unit/currency, axis semantics, data provenance, base point, warning annotations и exportable table. Нельзя передавать только pixels или preformatted labels.

## 13. What-If Engine

### 13.1. Shock model

```json
{
  "shock_id": "eq-spot-up-5",
  "target": {"factor_ids": ["EQ:US:AAPL:SPOT"]},
  "operator": "relative",
  "value": "0.05",
  "application": "simultaneous",
  "recalibration": "policy_default"
}
```

Поддержать:

- absolute, relative, log, basis-point и volatility-point shifts;
- spot/forward, curve node/parallel/twist, surface node/smile/term shifts;
- dividend, borrow, fixing, basis, credit spread, recovery, correlation and commodity shocks;
- time roll/business date roll;
- historical and hypothetical scenario sets;
- conditional and sequential shocks;
- full reprice либо явно маркированную approximation;
- recalibration policy: frozen, partial, full.

### 13.2. Режимы анализа

- single scenario;
- 1D ladder;
- 2D grid;
- N-dimensional batch;
- named scenario set;
- historical replay;
- tornado and scenario waterfall;
- break-even/solve-for;
- reverse stress: найти минимальный shock, нарушающий threshold;
- constrained optimization для coupon/strike/barrier при заданных limits.

### 13.3. Численная согласованность

- base и shocked runs используют один frozen context;
- Monte Carlo differences используют common random numbers;
- seed и random-stream policy сохраняются;
- каждая cell имеет status/warnings, а не только number;
- partial cells stream по мере готовности;
- пользователь может cancel job;
- quotas ограничивают dimensions, cells, paths и runtime;
- cache key учитывает product, state, context, engine, numerics, scenario set and requested measures.

## 14. Simulation Lab

Обязательные функции для simulation-capable engine:

- sampled path preview и percentile fan;
- terminal/path-dependent payoff distribution;
- PDF/CDF/histogram/percentiles/moments;
- probability of barrier hit, call, exercise, default, target reach;
- expected coupon/redemption date;
- exposure profile, если engine это поддерживает;
- convergence by paths/steps и confidence interval;
- variance-reduction comparison;
- deterministic seed/replay;
- correlation diagnostics и PSD adjustment disclosure;
- export aggregated data; raw path export ограничивается policy/size.

Пользователь должен видеть, является ли результат pricing simulation, risk simulation или illustrative path preview. Эти сущности нельзя смешивать.

## 15. Model Comparison & Calibration

### Model comparison

- frozen resolved trade/context для всех engines;
- price/quote/Greek differences relative to selected reference;
- runtime, convergence/error estimate и required data;
- governance status, production eligibility, limitations;
- причина невозможности запуска отдельного engine;
- общие units и normalized factor mapping;
- side-by-side resolved model/calibration parameters.

### Calibration workspace

- consumed market instruments/quotes;
- target vs fitted values и residuals;
- parameter bounds/constraints;
- calibration algorithm/status/timestamp/version;
- rejected/missing/stale quotes;
- sensitivity to calibration inputs;
- immutable calibration artifact ID;
- publish/approve только согласно роли.

Pricing tab может запускать или ссылаться на calibration job, но не должен скрыто калибровать новую модель без сохранения artifact.

## 16. Custom Product Engine

### 16.1. Authoring modes

1. **Template mode:** clone approved template, edit exposed slots, validate and price.
2. **Advanced mode:** assemble typed payout/event graph from approved primitives.

Оба режима создают один `ProductDefinition` и компилируются в `PayoffIR` на backend.

### 16.2. Primitives

- underlying/observable/fixing;
- calendar/schedule/observation;
- scalar/money/rate/percentage/quantity;
- arithmetic, min/max/average/rank/clamp/indicator;
- basket, worst/best/nth/weighted aggregation;
- barrier and monitoring;
- coupon, memory account, accrual and target;
- call/put/exercise/early redemption;
- cashflow/leg/settlement/conversion;
- credit event/recovery;
- state variable and state transition;
- terminal and path-dependent payout.

### 16.3. Builder functions

- add/remove/reorder allowed nodes;
- connect typed inputs/outputs;
- parameterize selected values as template slots;
- validate incrementally and on server;
- generated natural-language economic summary;
- generated event/cashflow timeline;
- payoff preview on deterministic test vectors;
- dependency and compatible-engine report;
- version diff;
- save draft, submit, approve, publish, deprecate;
- clone published version; published artifact is immutable.

### 16.4. Compiler checks

- schema, types, units, currencies and dimensions;
- cycles/unreachable branches/uninitialized state;
- schedule and maturity consistency;
- payout in every terminating branch;
- required fixings and market dependencies;
- path/exercise/dimensionality classification;
- engine/model/data/governance compatibility;
- resource bounds;
- generated regression vectors;
- canonical definition hash.

### 16.5. Publication workflow

```text
draft → validated → compiled → tested → submitted
      → approved → published → deprecated/retired
```

Ни UI, ни backend не исполняют произвольный user code. Advanced expression — только allowlisted typed AST.

## 17. `/api/v2` contract surface

Точные resource names можно согласовать с backend owner до coding, но semantics обязательны.

### Discovery and schema

| Method | Endpoint | Назначение |
|---|---|---|
| GET | `/api/v2/capabilities` | API/features/schema versions, limits, streaming support |
| GET | `/api/v2/session` | Authenticated actor, desk/tenant context and session expiry |
| GET | `/api/v2/entitlements` | Effective product/model/environment/action permissions |
| GET | `/api/v2/products` | Unified derivative/bond/custom product catalogue |
| GET | `/api/v2/products/{id}` | Product metadata and versions |
| GET | `/api/v2/products/{id}/schema` | Terms schema, constraints, outputs, dependencies |
| POST | `/api/v2/products/{id}/resolve` | Resolve defaults/dependencies/eligible engines |
| GET | `/api/v2/models` | Model definitions, parameters, governance and versions |
| GET | `/api/v2/models/{id}` | One model version and evidence |
| GET | `/api/v2/engines` | Numerical/pricer engine definitions and capabilities |
| GET | `/api/v2/engines/{id}` | One engine version, limits and compatible models |
| GET | `/api/v2/environments` | Allowed pricing environments |
| GET | `/api/v2/market/snapshots` | Search/list snapshots by as-of, source and quality |
| GET | `/api/v2/market/snapshots/{id}` | Snapshot lineage/quality summary |

### Workspace, trade state and lifecycle

| Method | Endpoint | Назначение |
|---|---|---|
| GET/POST | `/api/v2/pricing/workspaces` | List/create server-backed workspace draft |
| GET/PUT | `/api/v2/pricing/workspaces/{id}` | Restore/update draft intent with optimistic concurrency |
| GET | `/api/v2/pricing/workspaces/{id}/runs` | Immutable run history for workspace |
| GET | `/api/v2/trades/{id}` | Canonical captured trade and product version |
| GET | `/api/v2/trades/{id}/state` | Current/versioned `TradeState` |
| GET | `/api/v2/trades/{id}/events` | Ordered business-event history |
| POST | `/api/v2/trades/{id}/events/validate` | Validate proposed fixing/coupon/exercise/etc. transition |
| POST | `/api/v2/trades/{id}/events` | Idempotently apply an authorised business event |
| GET | `/api/v2/fixings` | Query realised fixings visible to the user/context |

Workspace draft хранит user intent и ссылки, но не подменяет immutable `Trade`, `TradeState`, `BusinessEvent` или `PricingRun`.

### Market dependencies, overrides and calibration

| Method | Endpoint | Назначение |
|---|---|---|
| POST | `/api/v2/market/dependencies/resolve` | Resolve required/consumed/missing objects for product/context |
| GET | `/api/v2/market/objects/{id}` | Object lineage, nodes, quality and permissions |
| GET/POST | `/api/v2/market/override-sets` | Search/create governed override draft |
| GET/PUT | `/api/v2/market/override-sets/{id}` | Read/update mutable override draft |
| POST | `/api/v2/market/override-sets/{id}/submit` | Submit material overrides for approval |
| POST | `/api/v2/market/override-sets/{id}/approve` | Maker-checker approval |
| GET/POST | `/api/v2/calibrations` | Search/create calibration job |
| GET | `/api/v2/calibrations/{id}` | Status, inputs, diagnostics and immutable artifact link |
| GET | `/api/v2/calibrations/{id}/events` | Progress/partial calibration diagnostics |
| POST | `/api/v2/calibrations/{id}/cancel` | Cooperative cancellation |
| POST | `/api/v2/calibrations/{id}/approve` | Approve artifact when policy requires |

### Validation and pricing

| Method | Endpoint | Назначение |
|---|---|---|
| POST | `/api/v2/pricing/validate` | Authoritative request validation |
| POST | `/api/v2/pricing/resolve` | Canonical resolved inputs and hash |
| POST | `/api/v2/pricing/runs` | Create idempotent sync/async run |
| GET | `/api/v2/pricing/runs/{id}` | Status/progress metadata |
| GET | `/api/v2/pricing/runs/{id}/events` | SSE/WebSocket event stream; polling fallback |
| GET | `/api/v2/pricing/runs/{id}/result` | Typed result envelope |
| POST | `/api/v2/pricing/runs/{id}/cancel` | Cooperative cancellation |
| POST | `/api/v2/pricing/runs/{id}/clone` | New request from immutable prior run |

### Analytics

| Method | Endpoint | Назначение |
|---|---|---|
| POST | `/api/v2/pricing/runs/{id}/analytics` | Create ladder/grid/scenario/simulation/convergence job |
| GET | `/api/v2/analytics/{id}` | Job status |
| GET | `/api/v2/analytics/{id}/events` | Partial results/progress |
| GET | `/api/v2/analytics/{id}/result` | Typed chart/table/result payload |
| POST | `/api/v2/pricing/comparisons` | Multi-engine or multi-context comparison |
| POST | `/api/v2/solvers` | Solve-for/break-even/reverse stress |

### Templates and custom products

| Method | Endpoint | Назначение |
|---|---|---|
| GET/POST | `/api/v2/templates` | Search/create template draft |
| GET/PUT | `/api/v2/templates/{id}` | Versioned template draft operations |
| POST | `/api/v2/custom-products/validate` | AST/definition validation |
| POST | `/api/v2/custom-products/compile` | Compile to immutable candidate artifact |
| POST | `/api/v2/custom-products` | Create draft/version |
| GET/PUT | `/api/v2/custom-products/{id}` | Read/update mutable draft only |
| POST | `/api/v2/custom-products/{id}/submit` | Submit for approval |
| POST | `/api/v2/custom-products/{id}/approve` | Maker-checker approval |
| POST | `/api/v2/custom-products/{id}/publish` | Publish immutable version |

### Approval and capture

| Method | Endpoint | Назначение |
|---|---|---|
| POST | `/api/v2/pricing/runs/{id}/approve` | Approve eligible immutable run |
| POST | `/api/v2/pricing/runs/{id}/capture` | Validate → pre-price → atomic persist → replay evidence |
| GET | `/api/v2/positions/{id}/pricing-lineage` | Captured versions and replay lineage |

Create/update endpoints используют optimistic concurrency (`ETag`/version) и structured conflict responses.

## 18. Async job protocol

Event stream types:

- `accepted`, `queued`, `started`;
- `phase_changed`;
- `progress` with completed/total/unit;
- `partial_result` with sequence and resumable cursor;
- `warning`;
- `completed`, `failed`, `cancelled`, `expired`.

Требования:

- events упорядочены per job;
- reconnect поддерживает `Last-Event-ID`;
- cancellation idempotent;
- retry не дублирует completed calculation;
- partial result маркирован incomplete;
- job сохраняет error code, retryability и correlation ID;
- user navigation не отменяет job автоматически, если пользователь явно не выбрал это;
- UI task cancellation не обязана означать server job cancellation — это отдельное действие.

## 19. Structured errors and warnings

Минимальная taxonomy:

- `SCHEMA_*` — version/type/unknown field;
- `TERMS_*` — economic cross-field rules;
- `MARKET_DATA_*` — missing/stale/quality/extrapolation;
- `MODEL_*` — unsupported/not approved/calibration failed;
- `NUMERICAL_*` — convergence/instability/resource limit;
- `GOVERNANCE_*` — role/environment/approval violation;
- `JOB_*` — queue/timeout/cancel/worker;
- `CAPTURE_*` — atomicity/conflict/replay mismatch;
- `CUSTOM_PRODUCT_*` — AST/compiler/publication.

Каждая ошибка имеет code, severity, retryable, message, pointers, details, correlation ID и documentation URI. Swift не заменяет её общей строкой «Request failed».

## 20. Governance, permissions and audit

- role/environment/purpose-based model eligibility;
- maker != checker для governed custom product и material override;
- reason и expiry для manual market/model override;
- immutable audit of validation, run, approval, export and capture;
- explicit research watermark/status для non-production run;
- prohibited capture для research/approximation result, если policy не разрешает;
- sensitive data redaction в logs/analytics;
- server-side authorization на каждый resource, не только скрытие control;
- calculation and definition retention policy;
- reproducibility report доступен auditor role.

## 21. Swift implementation instructions for Claude

### 21.1. Architecture

- Использовать SwiftUI, structured concurrency и `async/await`.
- Feature state хранить в `@MainActor @Observable` store либо эквивалентной однонаправленной state architecture.
- Network, cache и event-stream clients определить protocols и внедрять как dependencies.
- Long-running work изолировать actors; UI mutation только на MainActor.
- Разделить domain DTO, resolved domain models, feature state и view-specific presentation models.
- Не использовать pricing formulas или model-selection logic в клиенте.
- Не размножать product-specific `switch` там, где contract содержит schema/capability.

Рекомендуемая модульная граница:

```text
PricingFeature/
  Domain/
  API/
  Schema/
  State/
  Components/
  Analytics/
  CustomProduct/
  Fixtures/
  Tests/
```

Это рекомендация по ownership, не требование к визуальному layout.

### 21.2. Codable and compatibility

- Генерировать стабильные DTO из OpenAPI/JSON Schema, где возможно.
- Forward-compatible enums должны сохранять unknown raw value.
- Date-only не декодировать как local-time `Date` без calendar semantics.
- Money/precise decimal — `Decimal`, не `Double`.
- Recursive `JSONValue` допускается только на dynamic schema boundary.
- Проверять `schema_version`, поддерживать declared compatible minor versions.
- Unknown required semantic type блокирует edit/run с понятной ошибкой.
- Catalogue/schema cache keyed by version/hash/ETag.

### 21.3. State and concurrency

- Debounce только non-authoritative preview/validation; explicit Run не debounce.
- Каждая async response проверяет workspace revision/input hash перед применением.
- Editing не уничтожает running job, но отделяет его result как historical/stale.
- Cancel Swift task при смене запроса; отдельно вызывать server cancel по команде пользователя.
- Reconnect stream и fallback polling с exponential backoff/jitter.
- Не использовать `try?` для business operations; error должен попасть в state.
- Idempotency key хранить до terminal response.

### 21.4. Form renderer

- recursive fields/groups/objects/unions;
- repeatable legs/rows;
- schedule editor;
- labelled matrix/vector editor;
- conditional visibility/required/enabled rules;
- inline local issues + server issues по JSON pointer;
- source/default/override indicator;
- units, scale and precision;
- accessible labels/help/error association;
- preserve unknown optional values only inside a schema-declared namespaced `extensions` object; reject unknown business fields.

### 21.5. Analytics renderer

- работать по typed chart payload, не угадывать смысл series по имени;
- table fallback для любого chart;
- selection/crosshair/tooltip semantics доступны keyboard/VoiceOver;
- base point, units, missing/error cell и warning annotations обязательны;
- large datasets downsample only with explicit disclosure; raw aggregate remains exportable;
- partial data не смешивать с completed result.

### 21.6. Persistence

- локально хранить только draft intent, UI preferences и cacheable public schema;
- не считать local draft authoritative trade record;
- secure tokens/credentials — только platform-secure storage;
- immutable runs/definitions не редактировать client-side;
- restore workspace должен сверять versions и stale status с server.

## 22. Non-functional requirements

Конкретные SLO утверждаются product/backend owners, но архитектура должна поддержать:

- catalogue/schema response cache and ETag;
- p95 local UI input response < 100 ms;
- p95 validate/resolve target < 1 s при warm dependencies;
- async acknowledgement target < 500 ms;
- progress для jobs дольше 2 s;
- cancellation acknowledgement target < 2 s;
- отсутствие блокировки MainActor network/decode/large chart transforms;
- deterministic replay within documented numerical tolerance;
- accessibility: keyboard, VoiceOver, Dynamic Type where applicable, non-colour-only status;
- localization-ready labels/messages, при этом IDs и units не локализуются;
- observability: correlation/run/job IDs в client and server logs;
- graceful offline/read-only viewing of cached completed runs where policy allows.

## 23. Security requirements

- TLS and authenticated API transport;
- documented auth/session contract (OIDC/OAuth2 or approved platform equivalent), token refresh/expiry and explicit logout;
- effective entitlements loaded from server and rechecked server-side for every action;
- server-side authorization and tenant/desk boundaries;
- production CORS allowlist; wildcard `*` prohibited, and cookie-based auth requires CSRF protection;
- deny-by-default access to product definitions, snapshots, runs, trades and exports outside actor scope;
- no arbitrary code execution in custom expressions;
- input size, AST depth, grid/path/runtime quotas;
- sanitised export/file names and safe decoding;
- secrets and tokens never in diagnostics export;
- audit-safe logs without full sensitive terms unless policy permits;
- signed/hashed published product definitions and result artifacts where required.

## 24. Migration from current v1

### Stage A — Preserve current capability

- создать v2 facade вокруг `/pricing/catalogue` и `/pricing/price`;
- определить auth/session/entitlement contract, закрыть production API deny-by-default и заменить CORS `*` на allowlist;
- вернуть schema/catalogue versions и provenance без изменения старого Swift flow;
- добавить strict engine/parameter validation behind feature flag;
- создать fixtures из текущих 50 продуктов.

### Stage B — Unified context and runs

- все operations принимают один `PricingContext`;
- price становится `PricingRun`;
- ladder/grid/scenarios/payoff переводятся в analytics jobs;
- Swift получает новый run state machine и typed errors.

### Stage C — Unified product registry and capture

- объединить derivative и bond catalogues;
- заменить ручной canonical-engine capture;
- validate → price → atomic persist;
- добавить round-trip parity tests.

### Stage D — Advanced analytics

- typed factor shocks, N-D jobs, simulation, convergence, model comparison;
- новые visualization payloads;
- calibration artifacts.

### Stage E — Custom Product Engine

- template authoring;
- typed AST/event graph;
- validate/compile/test/approve/publish;
- lifecycle/capture/replay.

Старые endpoints удалять только после telemetry-backed parity, documented deprecation window и migration of saved drafts.

## 25. Implementation phases for Claude

### Phase 0 — Contract fixtures

Deliverables:

- v2 DTOs/OpenAPI snapshot;
- mock `PricingAPI` and event stream;
- mock authenticated session, expiry and entitlement changes;
- fixtures: vanilla, multi-leg rates, autocall, failed validation, stale result, partial scenario;
- feature flags and capability handling.

Exit: все state transitions можно демонстрировать без live backend.

### Phase 1 — Core workspace

- product/template selection;
- recursive schema form;
- environment/model/numerical selection;
- authenticated session, desk/tenant context and action entitlements;
- validate/resolve/run;
- base result, warnings/errors/provenance;
- server-backed draft/run history and stale handling;
- read-only current `TradeState`, realised fixings and business-event timeline for existing trades.

Exit: standard product проходит Draft → Validated → Priced.

### Phase 2 — Analytics

- cashflows/Greeks;
- payoff/ladder/grid;
- scenarios/what-if;
- async stream/progress/cancel;
- chart table fallbacks.

Exit: partial/cancel/fail/retry paths покрыты тестами.

### Phase 3 — Simulation and comparison

- distribution/path fan/convergence;
- model comparison;
- calibration diagnostics;
- solve-for.

Exit: identical frozen context visibly подтверждён для comparisons.

### Phase 4 — Custom product

- template mode;
- advanced typed graph/DSL editor;
- validate/compile/version diff;
- approval/publication states.

Exit: Phoenix/autocall definition создаётся без product-specific Swift code.

### Phase 5 — Approval and capture

- approval evidence;
- atomic capture call;
- returned position/replay lineage;
- authorised lifecycle-event validation/application shell;
- conflict and permission handling.

Exit: capture работает только для exact current completed run hash и, когда policy требует, только после approval того же run.

## 26. Required test suite

### Swift unit/contract tests

- decode all field/chart/job/result variants;
- unknown enum and compatible minor schema version;
- Decimal/date/timezone round-trip;
- shared Python/Swift canonical JSON/hash vectors, including decimal normalization, `-0`, null/absent, key order and timezone;
- condition-AST equivalence/fail-closed behavior, extension policy and JSON pointer mapping;
- workspace revision rejects stale async response;
- state machine including reconnect/cancel/retry;
- idempotency key reuse;
- session expiry/refresh, permission loss and cross-desk denial;
- no swallowed business errors;
- environment propagated to every operation;
- chart table fallback.

### Backend contract tests

- unknown engine/field rejected;
- independently versioned model and engine blocks resolved and persisted without silent substitution;
- every declared effective parameter has influence or is `display_only`;
- cross-field validation;
- environment/context equality across price and analytics;
- complete provenance;
- deterministic replay;
- canonicalization/hash vectors match the Swift fixtures;
- product/engine capability enforcement;
- authentication required, per-resource authorization, tenant/desk isolation, CORS/CSRF policy and audit coverage;
- job partial ordering/cancel/idempotency;
- capture rollback on pricing/replay failure;
- captured price parity.

### Quant/golden tests

- closed-form and independent benchmarks;
- cross-engine comparison;
- convergence and confidence interval coverage;
- scenario/common-random-number stability;
- custom DSL vs dedicated pricer equivalence;
- lifecycle before/on/after event dates.

### UI/accessibility tests

- loading/empty/validation/running/partial/failed/stale/completed states;
- keyboard-only critical workflows;
- VoiceOver labels and error associations;
- large text and non-colour status;
- snapshot tests for representative schemas, not every product ID.

## 27. Acceptance criteria

MVP production candidate принимается только если:

1. Ни одна pricing operation не использует context, отличный от выбранного и показанного пользователю.
2. Unknown engine/parameter не приводит к silent fallback.
3. Все effective controls доказуемо влияют на result/diagnostics либо помечены `display_only`.
4. Completed result содержит calculation ID, input hash, product/model/environment/snapshot/calibration versions и consumed-data lineage.
5. Edit после run немедленно делает result stale.
6. Heavy jobs показывают progress, поддерживают cancel/reconnect и не блокируют UI.
7. Любой chart имеет typed data contract и accessible table fallback.
8. Validation issue ведёт к точному field/JSON pointer.
9. Capture атомарен и сохраняет exact product/engine/model/market/numerical definition.
10. Capture требует approval только когда это предписано effective policy; в таком случае unapproved run отклоняется, а в остальных случаях eligible `Priced` run допускает прямой capture.
11. Immediate portfolio replay совпадает с captured run в утверждённом tolerance.
12. Research/non-production result невозможно выдать за production run.
13. Новый standard product со schema-supported fields не требует product-specific Swift pricing code.
14. Published custom product immutable, versioned, hashed и maker-checker approved.
15. Произвольный пользовательский код не исполняется.
16. Authenticated session и server-side entitlements enforced; cross-desk/tenant access denied, production CORS не использует wildcard.
17. Python и Swift дают одинаковые canonical bytes/hash на общем наборе versioned fixtures.
18. Contract, concurrency, security, failure, accessibility и golden tests зелёные.

## 28. Deliverables checklist for Claude

- [ ] Зафиксированный v2 API/OpenAPI contract или versioned fixtures.
- [ ] Swift domain/API/state modules.
- [ ] Authenticated session, entitlement and tenant/desk boundary handling.
- [ ] Recursive schema renderer.
- [ ] Product/template/environment/model/numerical workflows.
- [ ] Validation/resolve/run state machine.
- [ ] Typed result and provenance views.
- [ ] Async progress/cancel/reconnect.
- [ ] Typed analytics/chart contracts and table fallbacks.
- [ ] What-if/scenario/simulation/model-comparison functions.
- [ ] Custom product template and advanced authoring shell.
- [ ] Approval/capture workflow.
- [ ] Workspace draft restore and trade-state/lifecycle integration.
- [ ] Mocks, fixtures, tests and accessibility evidence.
- [ ] Migration notes and feature-flag plan.
- [ ] No duplicated pricing logic in Swift.

## 29. Instructions Claude must follow

1. Сначала согласовать DTOs, states и fixtures; только затем строить final UI.
2. Не придумывать отсутствующие backend fields silently. Оформить contract gap и mock it behind capability flag.
3. Не хардкодить формы по product ID.
4. Не переносить model selection/default resolution в Swift.
5. Не подавлять ошибки через `try?` в business flow.
6. Не считать completed historical result текущим после edit.
7. Не разрешать capture без exact completed run hash; дополнительно требовать approval, когда это предписано effective policy.
8. Любая новая визуализация должна иметь typed payload, units, provenance и table fallback.
9. Каждый этап завершать runnable demo, contract tests и updated fixtures.
10. Design decisions документировать отдельно; функциональный контракт этого файла сохранять.

## 30. Внешние семантические ориентиры

- [FINOS CDM Product Model](https://cdm.finos.org/docs/product-model/) — composable economic terms and payouts;
- [FINOS CDM Event Model](https://cdm.finos.org/docs/event-model/) — trade state, events and state transitions;
- [FpML Products Framework](https://www.fpml.org/products-and-messaging-framework/) — cross-asset product representation and interchange reference;
- [OpenGamma Strata API](https://strata.opengamma.io/apidocs/) — separation of product/trade domain, market data, calculations, scenarios and pricers.

Эти источники задают отраслевую семантику. Реализация не обязана копировать их API, но должна сохранять ясное разделение Product, Trade, State, Market Data, Model, Calculation и Business Event.

## 31. Финальный критерий качества

Вкладка Pricing считается production-grade не тогда, когда на ней много controls и графиков, а когда любой показанный результат можно:

1. объяснить через resolved inputs и model/data lineage;
2. воспроизвести по immutable identifiers;
3. безопасно исследовать через scenarios/simulations;
4. согласовать согласно governance;
5. атомарно превратить в позицию без потери economic terms;
6. переоценить в Portfolio тем же engine/context;
7. провести через lifecycle и audit.
