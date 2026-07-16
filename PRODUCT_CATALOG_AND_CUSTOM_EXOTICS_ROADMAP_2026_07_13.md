# Product Catalogue & Custom Exotics Roadmap

**Дата аудита:** 2026-07-13

**Расширение model universe:** 2026-07-14

**Статус:** implementation in progress — QW0 completed, QW1 foundation implemented and under hardening

**Начало выполнения / последняя проверка:** 2026-07-15

**Область:** продуктовый каталог, структурные продукты, capture/repricing, lifecycle, Custom Product Engine
**Основные источники в коде:** `api/pricing_workstation.py`, `api/server.py`, `services/pricing_service.py`, `services/portfolio_service.py`, `domain/pricing_environment.py`, `domain/results.py`, `domain/scenario.py`, `instruments/`, `models/`, `macapp/Sources/RiskCalc/`

## 1. Резюме и прямой ответ

Нет, в текущем каталоге представлены не все значимые структурные продукты. Более того, для production-готовности недостаточно добавить ещё названия в меню: у продукта должны одновременно существовать строгий контракт сделки, валидируемые market data, допустимый pricer/model, воспроизводимый результат, risk/scenario analytics, capture, последующее repricing и lifecycle.

Текущее состояние сильное как количественная библиотека и pricing workstation:

- 50 продуктовых карточек в семи классах активов;
- 103 уникальные связки `(product, selector)`: 87 глобально уникальных selector ID и 86 canonical implementation-component ID;
- из 103 связок 98 имеют legacy component status `Validated`, 4 — `Approximation`, 1 — `Prototype`; этот status больше не используется как синоним production approval;
- authoritative QW1 ledger содержит 104 versioned `EngineEligibility` (два runtime-варианта Carr–Madan): 84 временно исполнимы по `legacy_transition` до 2027-01-31, 15 являются `research-only`, 5 — `non-production`; независимо одобренных engine-связок пока 0;
- enriched publication ledger для всех 124 canonical components содержит 85 реально `published`, 18 только `routed`, 20 `research-only` и 1 `deprecated` запись;
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

Legacy component status `Validated` у implementation component — это характеристика внутреннего registry, а не engine approval и не доказательство уровней L4–L6 для продукта целиком.

## 3. Фактический каталог и программа расширения моделей

### 3.1. Покрытие по классам активов

| Класс | Продуктов | Engine-связок | Capturable | Capture coverage |
|---|---:|---:|---:|---:|
| Equity | 12 | 46 | 5 | 41.7% |
| Rates | 9 | 16 | 6 | 66.7% |
| FX | 8 | 10 | 1 | 12.5% |
| Credit | 8 | 14 | 1 | 12.5% |
| Commodity | 2 | 4 | 0 | 0% |
| Inflation | 2 | 2 | 0 | 0% |
| Hybrid / Structured | 9 | 11 | 3 | 33.3% |
| **Итого** | **50** | **103** | **16** | **32.0%** |

45 из 50 продуктов имеют хотя бы один engine, временно разрешённый transition policy. Это не независимый production approval: все 84 таких допуска истекают 2027-01-31. Без transition-allowed engine остаются `equity_swap`, `warrant`, `cds_index`, `cds_index_option` и `basket_note`. Наличие карточки не должно создавать впечатление production-доступности.

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

### 3.5. Что означает цель «все модели и продукты рынка»

Буквально конечного перечня всех деривативов не существует: OTC-сделки допускают новые комбинации payout, observation rules, lifecycle events и underlyings. Поэтому полнота должна определяться не размером статического меню, а двумя проверяемыми условиями:

1. все стандартизованные и экономически значимые семейства контрактов и моделей находятся в едином coverage registry;
2. нестандартная комбинация выражается типизированными payoff/event primitives без изменения pricing core и без пользовательского исполняемого кода.

Для управления каталогом необходимо разделять четыре сущности, которые сейчас местами смешаны:

| Сущность | Что это | Примеры | Единица versioning/governance |
|---|---|---|---|
| Product | Экономический контракт и lifecycle | perpetual American option, autocall, CDS tranche, swing option | `product_definition_id` |
| Model | Динамика факторов и вероятностные допущения | Heston, Hull–White, LMM, local volatility, intensity model | `model_id` + parameter set |
| Numerical method | Способ решения | closed form, tree, PDE/PIDE, FFT/COS, Monte Carlo/LSM | `solver_id` + numerical settings |
| Pricing engine | Разрешённая связка product × model × solver | American option × Heston × LCP-PDE | `engine_id` + capability contract |

Следовательно, новый perpetual option — это прежде всего новый contract/lifecycle family, а не одно дополнительное название модели. Для него может понадобиться несколько engines: closed form при допустимых постоянных коэффициентах; stationary free-boundary PDE только для time-homogeneous dynamics; либо специализированный infinite-horizon solver. Обычный LSM или finite-horizon PDE допустимы лишь с объявленным truncation horizon, long-run extrapolation policy и доказанной оценкой truncation error.

### 3.6. Уровни зрелости количественной модели

Product maturity `L0–L6` из раздела 2 необходимо хранить отдельно от model maturity. Шкала `Q0–Q6` ниже относится только к `ModelDefinition`. Numerical solver получает отдельный `SolverEvidenceRecord`, а готовность конкретной комбинации product × model × solver хранится в `EngineEligibility`; product capture/lifecycle остаются исключительно в `L`-шкале.

| Уровень | Состояние модели | Обязательное доказательство |
|---|---|---|
| Q0 — Candidate | Модель занесена в target universe | Мотивация, первоисточники, предполагаемые use cases |
| Q1 — Specified | Формально заданы dynamics, measure, state variables и parameter domain | Математическая спецификация, well-posedness assumptions и limitations |
| Q2 — Implemented | Реализованы model dynamics и parameter resolution | Unit/property tests; solver и product binding оцениваются отдельно |
| Q3 — Parameter-ready | Есть устойчивая calibration либо обоснованная policy `not_applicable` | Objective/constraints/diagnostics или детерминированный parameter source |
| Q4 — Benchmarked | Model-implied distributions, moments, calibration behavior и limiting properties сверены с challenger/reference | Model benchmark report и regression fixtures; solver convergence хранится отдельно |
| Q5 — Governed | Model package версионируется, воспроизводится и наблюдается | Immutable build, approved calibration/parameter policy, limits и monitoring |
| Q6 — Independently validated | Пройдена независимая model validation для определённых use cases | Validation approval, findings closure, version/deprecation policy |

Статус комбинации должен записываться многомерно, например `(product=L4, model=Q5, solver=validated, engine=integrated)`. Флаг `production_allowed` принадлежит `engine_id`, а не модели, и требует допустимых product, model, solver/calibration и market-data policy. Текущее поле `Validated` в registry не следует автоматически интерпретировать как `Q6`: оно не доказывает calibration, external benchmark и независимую model validation.

### 3.7. Фактический model universe в кодовой базе

После QW0/QW1 и проверки 2026-07-15 `MODEL_REGISTRY` содержит 124 canonical entries с legacy component status: 115 `Validated`, 4 `Approximation` и 5 `Prototype`. Workstation публикует 103 product-qualified selector-связки, 87 уникальных selector ID и 86 canonical implementation-component ID; все они присутствуют в registry, ещё 38 записей не используются как workstation engine. Множества ID в `MODEL_REGISTRY`, `models.taxonomy.CLASSIFICATION` и явном `component_kind`-разбиении совпадают 124/124/124, без unknown и duplicate ID. Ни 124, ни 86 не являются числом самостоятельных stochastic models: registry намеренно содержит несколько разных типов quant-компонентов.

QW1 физически разделил governance contracts:

- 39 versioned `ModelDefinition`: 18 на Q2 и 21 на Q1; Q3+ пока 0, поскольку immutable calibration/parameter artifacts и model benchmark packages ещё не созданы;
- 107 `SolverDefinition` и 107 `SolverEvidenceRecord`: 17 самостоятельных canonical numerical solvers и 90 implementation-qualified solver routes для формул/деревьев/MC, ранее скрытых внутри model/product components; у routes, связанных с implementation components с legacy status `Validated`, есть executable test references, но performance envelope пока не документирован;
- 104 `EngineEligibility` для 103 default selector-пар: 84 `legacy-transition`, 15 `research-only`, 5 `non-production`; Carr–Madan публикует отдельные BSM/Heston runtime variants;
- 124 enriched `ComponentPublication`: 85 `published`, 18 `routed`, 20 `research-only`, 1 `deprecated`; это authoritative routing ledger, но только `published` означает существующий пользовательский contour, а `routed` — назначенную цель без завершённой UI/API integration.

Фактическое разбиение после QW0: 56 `product_pricer`, 28 `stochastic_model`, 17 `numerical_solver`, 13 `risk_methodology`, 4 `market_infrastructure`, по 3 `market_model` и `smile_parameterization`, 0 самостоятельных `calibration_method`. Пустая последняя группа — не пропуск ID, а зафиксированный gap отдельного calibration registry.

| Область | Уже реализованные модели и методы | Основной незакрытый шаг |
|---|---|---|
| Vanilla equity/FX | BSM, Black-76, Bachelier, Garman–Kohlhagen, displaced diffusion, CEV, discrete dividends, Jarrow–Rudd, Tian, lognormal mixture, Vanna–Volga | Единая calibration/market-data policy и публикация полного набора engines |
| Volatility and jumps | Heston CF/MC/ADI, Bates, Merton, Kou, Variance Gamma, NIG, CGMY, rough Bergomi, Dupire/local-vol primitives, GARCH/GJR/EWMA, SVI slice fitting | No-arbitrage surfaces, production calibration, SLV и независимые benchmarks |
| Numerical stack | CRR/Leisen–Reimer/JR/Tian/trinomial trees, Crank–Nicolson, 2D ADI, Monte Carlo/LSM, Sobol QMC, Carr–Madan FFT, COS/Fourier | Общие convergence controls, LCP/PIDE, AAD и portfolio-scale acceleration |
| Rates | Vasicek, CIR, Hull–White, Ho–Lee, HW tree, G2++, Black–Karasinski, Cheyette quasi-Gaussian HJM, LMM/BGM, Swap Market Model, SABR, swaption cube | Multi-curve/RFR semantics, robust calibration, callable/CMS correlation engines |
| Credit/XVA | Flat/piecewise hazard, ISDA-style CDS, Merton/KMV/Black–Cox, Gaussian/t/Clayton copulas, LHP/base correlation, CVA/DVA/WWR primitives | Stochastic intensity/recovery, dynamic portfolio credit и unified XVA exposure engine |
| Commodity | Schwartz–Smith, Gibson–Schwartz, Pilipović, deterministic seasonality | Forward-curve HJM, spikes/regimes, physical optionality и multi-commodity correlation |
| Inflation | CPI forward and breakeven identities | Полная stochastic nominal/real/inflation dynamics; текущий `jarrow_yildirim` ещё не является полной JY-моделью |
| Hybrid/securitized | Correlated GBM, Margrabe, Kirk, Stulz, Tsiveriotis–Fernandes convertible, PSA/MBS/OAS/ABS waterfall primitives | Cross-asset calibration, loan-level behavior, default/conversion consistency |
| Market/portfolio risk | Historical/parametric/MC/full-reprice VaR, EVT, copula VaR, FRTB SBA/IMA, aggregation | Это risk methodologies/overlays, а не risk-neutral pricing models; нужны единый factor taxonomy, modellability evidence и production aggregation |

GARCH/GJR/EWMA также являются physical-measure/statistical volatility components, пока отдельно не доказаны pricing-measure dynamics и calibration. Их нельзя предлагать как взаимозаменяемую замену Heston/local-vol в derivative-pricing dropdown.

38 записей registry, ещё не используемых как workstation `model_id`, не образуют однородный backlog: 13 уже реально `published` в отдельном bond catalogue, 18 пока только `routed` в целевые semantic contours, 6 изолированы как `research-only`, 1 корректно `deprecated`. Следовательно, integration backlog составляют прежде всего 18 routed components; только настоящие альтернативные pricing engines следует показывать в model selector, а products, risk analytics и market infrastructure — довести до назначенных разделов/API. Полный inventory этих 38 записей:

| Группа | Существующие registry IDs |
|---|---|
| Rates, bonds, money market | `amortizing_bond`, `basis_swap`, `callable_bond`, `commercial_paper`, `custom_bond`, `fixed_bond`, `frn`, `mm_deposit`, `perpetual_bond`, `repo`, `sabr`, `short_rate`, `step_bond`, `swaption_cube`, `treasury_bill` |
| Equity/volatility | `garch`, `local_vol_mc` |
| Commodity/inflation | `commodity_seasonal`, `pilipovic`, `inflation_linked_bond`, `jarrow_yildirim` |
| Credit/XVA/securitized | `abs`, `cln_ftd`, `cva_dva`, `cva_exposure`, `cva_wwr`, `mbs`, `xva_suite` |
| Risk/platform | `copula_var`, `evt_var`, `frtb_ima`, `frtb_sba`, `portfolio_aggregation`, `var_full_reprice`, `var_historical`, `var_mc`, `var_parametric` |
| FX infrastructure | `xccy_curve` |

#### QW0 — Inventory and identity: выполнено 2026-07-15

- `merton_cos` зарегистрирован как callable canonical engine, получил параметры, workstation route, Analytics Lab gate и executable validation evidence;
- `cva_exposure_risk` оставлен compatibility alias к canonical `cva_exposure` и исключён из canonical inventory;
- перегруженный `adi` разделён на `two_asset_adi` и `heston_adi`; публичный selector `adi` сохранён как alias к two-asset solver, historical provenance разрешается по `calculation_type`, а Heston ADI больше не обходит Analytics Lab governance;
- `afv_convertible` сохранён как совместимый ID, но metadata и документация честно фиксируют Andersen–Buffum-style equity-linked hazard CRR и прямо исключают Ayache–Forsyth–Vetzal PDE;
- `jarrow_yildirim` зафиксирован как Q1 deterministic flat nominal/real CPI carry/breakeven scope, не как полная stochastic JY model;
- дополнительно устранён найденный identity defect structural-credit dispatch: canonical `merton_structural` и `kmv` больше не возвращают результат/audit под `black_cox`;
- registry consistency/alias/engine-reference validation включена fail-closed при инициализации governance; workstation price path применяет ту же `ParameterSpec`-валидацию, что `/pricing/validate`; result и audit сохраняют canonical и requested legacy ID.

Проверка QW0 (2026-07-15): полный Python regression — **1506 passed, 1 skipped**; validation program — consistency `ok` и executable evidence для **115/115 `Validated` components**; Swift package — **19/19 tests passed**. Это синхронизировало canonical quant-component identity и дало context-aware migration для legacy `adi`; старые записи `adi` без `calculation_type` остаются неоднозначными.

#### QW1 — Classify and expose: реализованный foundation 2026-07-15

- введены самостоятельные immutable contracts `ModelDefinition`, `SolverDefinition`, `SolverEvidenceRecord`, `EngineEligibility` и `ComponentPublication`; legacy `ModelRegistryEntry` больше не маскируется под новый тип;
- model Q1 contract хранит dynamics, measure, numeraire, state factors, parameter domain и well-posedness assumptions отдельно от implementation notes; Q2 требует executable model evidence и не повышается автоматически до Q6 из legacy `Validated`;
- каждый workstation engine разрешается по `(product, selector, runtime variant)` к точным model/solver definitions; generic solver placeholders заменены implementation-qualified evidence records;
- один fail-closed gate применяется к validate, price, scenarios, ladder, grid2d и payoff; research/non-production permission задаётся server-owned map только для зарезервированного environment ID `LAB` с purpose `research`, `LAB` защищён от удаления, а редактируемая metadata других environments не может повысить права;
- transition approval проверяется по сроку: дата 2027-01-31 включительно разрешена, с 2027-02-01 возвращается `ENGINE_APPROVAL_EXPIRED`;
- Carr–Madan/Heston исправлен как исполнимый runtime variant; catalogue и Swift выбирают точную BSM/Heston eligibility, не наследуя BSM approval;
- pricing result/audit/Swift provenance сохраняют eligibility, model, solver, implementation component и runtime variant; Governance UI показывает aggregate KPI по components/models/solvers/eligibilities и implementation-component registry, подробные раздельные ledgers доступны через governance API; legacy `Validated` больше не называется production approval.

Проверка QW1 foundation после hardening (2026-07-15): полный Python regression — **1529 passed, 1 skipped**; validation program — consistency `ok` и executable evidence **115/115**; Swift package — **26/26 tests passed**. Отдельные acceptance checks покрывают прямой и workstation Carr–Madan/Heston gate, BSM/Heston catalogue variants, общий gate всех pricing/what-if endpoints, environment-effective derived calculations, запрет повышения прав через environment metadata, effective-vs-declared production state и inclusive expiry boundary.

Что остаётся до полного закрытия QW1:

1. превратить 18 `routed` не-workstation components в реальные semantic catalogues/API contours; сохранить 13 уже опубликованных bond components в едином product registry, 6 research components — в Analytics Lab, а deprecated component — вне исполнимых контуров;
2. задокументировать convergence/bias/Greeks/performance envelopes для 107 solver routes и заменить тестовые node references полноценными benchmark artifacts;
3. поднять приоритетные модели с Q2 до Q3/Q4 через immutable calibration/parameter bundles, diagnostics и external/challenger benchmarks;
4. заменить 84 временных transition approvals независимыми maker-checker decisions до 2027-01-31; сейчас independently approved = 0;
5. распространить product-qualified eligibility на Market Risk/XVA/portfolio paths и создать единый `ProductDefinitionRegistry`; текущие 124 publication records не означают полную UI/API integration.

Дополнительно следует опубликовать уже существующие callable primitives, отсутствующие в текущем перечне §3.3: Bermudan equity option, default digital, credit spread option, zero-coupon bond, caplet/floorlet, CMS swaplet, standalone best/worst-of, defaultable straight bond, continuous geometric Asian и discrete-monitoring lookback.

### 3.8. Целевой model universe: модели, которых ещё нет

Ниже приведён backlog семейств, обнаруживаемых в академических первоисточниках, open-source quant libraries, product standards и биржевых каталогах. Это target universe, а не обещание одновременно допустить все модели в production. Приоритеты model-очереди: `MQ1` — рыночная база, `MQ2` — сложные востребованные инструменты, `MQ3` — специализированные/новые рынки, `MQR` — research-only до отдельной валидации.

| Домен | Добавить модели/подходы | Приоритет и целевое применение |
|---|---|---|
| Market-state construction | CSA/OIS/multi-curve bootstrap, FX basis/triangulation, curve interpolation/extrapolation, inflation/commodity forwards, arbitrage-free surface/cube assembly | MQ1: обязательная calibrated market foundation для всех последующих models |
| Equity/FX local-stochastic volatility | Arbitrage-controlled implied trees/Dupire, Heston–Dupire SLV/LSV, leverage/particle calibration | MQ1: barriers, cliquets, forward-start, autocalls, smile-consistent Greeks |
| Alternative stochastic volatility | 3/2, 4/2, Stein–Stein/Scott, Schöbel–Zhu, stochastic alpha/beta/rho | MQ2: long-dated smile, variance and hybrid payoffs |
| Rough/forward variance | Multi-factor Bergomi, rough Heston, rough SABR, Volterra-Heston/Markovian lifts | MQR: forward-skew and volatility exotics; сначала Analytics Lab |
| Smile parameterizations | No-arbitrage SVI/SSVI/eSSVI, normal/lognormal/shifted/no-arbitrage SABR, ZABR, Antonov-style free-boundary SABR, normal/lognormal mixtures, stochastic skew, regime-switching smiles | MQ1/MQ2: arbitrage-controlled surfaces and extrapolation |
| Dividends, borrow and equity financing | Stochastic dividend yields, discrete stochastic dividends, stochastic borrow/repo, dividend term-structure models | MQ2: dividend derivatives, long-dated equity exotics, hard-to-borrow names |
| Jump/Lévy extensions | Generalized Hyperbolic, Meixner, Normal Tempered Stable, time-changed/local Lévy, Hawkes/self-exciting and Markov-modulated jumps | MQ2/MQR: gap risk, short-dated skew, event/contagion dynamics |
| FX hybrid dynamics | Heston–Hull–White, local/SLV with stochastic domestic and foreign rates, stochastic cross-currency basis | MQ1/MQ2: long-dated FX, quanto/compo, callable multi-currency notes |
| Short-rate/term-structure | Black–Derman–Toy, CIR++, two-factor Hull–White, LGM/GSR, affine/quadratic-Gaussian term structures, generic Gaussian/non-Gaussian HJM/Musiela, Markov-functional | MQ1/MQ2: callable rates, Bermudans, CMS and structured notes |
| Rates market models | Shifted/displaced multi-curve LMM, stochastic-volatility LMM, DD-SV-LMM, SABR-LMM, stochastic-basis/cross-currency LMM, RFR/compounded-rate market models | MQ1/MQ2: caps, swaptions, CMS, basis and callable products |
| Rates correlation/delivery | CMS/CMS-spread correlation, co-terminal swap models, stochastic correlation, smile-consistent annuity mapping, futures convexity, bond-future CTD/delivery-option models | MQ2: CMS spread options, range accruals, PRDC, Bermudans and delivered futures |
| Inflation | Full Jarrow–Yildirim, nominal-real HJM, inflation market model, seasonality-aware stochastic CPI, inflation smile/correlation | MQ1/MQ2: ZC/YoY options, LPI, inflation swaptions and hybrids |
| Credit intensity | Jarrow–Turnbull, Duffie–Singleton, CIR/JCIR/CIR++, stochastic recovery, rating migration and reduced-form multi-state models | MQ1: risky bonds, CDS options, callable credit and counterparty default |
| Portfolio credit | Gaussian/t/Clayton/Marshall–Olkin extensions, dynamic copulas, contagion/common-shock intensities, top-down GPL/Markov loss, bottom-up interacting intensities, stochastic base correlation | MQ2/MQR: bespoke/index tranches, tranche options, nth-to-default |
| Structural credit/capital structure | Leland–Toft, CreditGrades, stochastic asset volatility, equity-credit joint models | MQ2: convertible/CoCo, capital structure arbitrage and hybrid Greeks |
| Counterparty/XVA | Wrong-way stochastic exposure, collateral/margin period of risk, funding/liquidity, initial margin/MVA and KVA models | MQ1/MQ2: netting-set XVA with pathwise collateral and default |
| Commodity forwards | Schwartz one-factor, Lucia–Schwartz for power, multi-factor forward-curve HJM, stochastic seasonality, mean-reverting jump/spike and regime-switching models | MQ1/MQ2: power/gas/oil curves, calendar/location/quality spreads |
| Physical commodity optionality | Storage/swing stochastic-control models, inventory constraints, tolling/load-following and take-or-pay models | MQ2: operational assets and structured supply contracts |
| Cross-commodity/environmental | Dynamic power–gas–emissions correlation, carbon allowance and renewable certificate dynamics, freight and weather mean-reversion/jump models | MQ3: spark/dark spreads, carbon/REC/GO, FFA and weather derivatives |
| Cross-asset dependence | Wishart covariance, local/stochastic correlation, dynamic factor copulas, joint rates–FX–equity–credit models | MQ2/MQR: rainbow, quanto, hybrid callable and correlation products |
| Volatility/correlation/dividend | Forward-variance/Bergomi framework, VIX/VVIX term-structure, covariance/correlation/dispersion and dividend-index models | MQ1/MQ2: variance, volatility, VIX, dispersion and dividend derivatives |
| Securitized products | Loan-level prepayment/default/severity/delinquency, burnout/refinancing, stochastic rates–housing linkage, CLO collateral and waterfall models | MQ2/MQ3: RMBS, CMBS, ABS, CLO, IO/PO, PAC/TAC and MSR |
| Digital assets | Funding/basis/perpetual dynamics, inverse/quanto settlement, liquidation-aware and jump/fragmentation models, staking/yield and hash-rate factors | MQ2/MQ3: perpetual futures/options, crypto options, staking and mining contracts |
| Insurance and alternative risk | Compound-Poisson/EVT/spatial catastrophe loss, Lee–Carter and Cairns–Blake–Dowd mortality, longevity intensity, weather, real-estate and climate-transition factor models | MQ3: cat bonds/options, longevity swaps, weather and real-estate derivatives |
| Data-driven research | Neural SDE, deep hedging, deep BSDE/PDE, signature/rough-path models and learned local volatility with hard no-arbitrage constraints | MQR: benchmark sandbox only; запрет production fallback без explainability и validation |

Модели не следует добавлять как взаимозаменяемые пункты dropdown. `EngineCapability` должен разрешать связку по типу exercise, monitoring, path dependency, размерности, stochastic factors, доступности calibration instruments и governance level.

### 3.9. Perpetual и open-ended инструменты

Пример «опциона без даты экспирации» требует отдельной семантики. Нельзя моделировать отсутствие maturity датой `9999-12-31`: это ломает day-count, schedules, discounting, risk horizons и validation.

| Семейство | Экономическая сущность | Требуемый pricing подход |
|---|---|---|
| Perpetual American option | Бессрочное право exercise; infinite-horizon optimal stopping | Closed form только после well-posedness checks; time-homogeneous stationary free-boundary/LCP или infinite-horizon tree; controlled truncation — только с error bound |
| Everlasting option | Funding-based perpetual contract, поддерживающий payoff профиля опциона | Funding rule, mark/index methodology, discrete settlement and liquidation model; не смешивать с American option |
| Perpetual future/swap | Бессрочная линейная экспозиция с funding/margin | Mark/index/funding basis, margin, liquidation, exchange rules |
| Perpetual bond/preferred/CoCo | Денежные потоки без contractual maturity либо с contingent call/conversion | Credit, call policy, deferral, recovery and capital-trigger model |
| Open-ended fund/index/certificate | Погашение по запросу или termination event | NAV/index rules, liquidity gates, fees and event-driven termination |
| Timer option | Случайная maturity при исчерпании variance budget | Joint price/realized-variance process; это не perpetual option |

В `TradeTerms` необходимо разделить `legal_maturity = fixed_date | none`, `termination_rule.kind = none | holder_redemption | stopping_time | event_driven`, `exercise_rule`, `funding_rule` и optional solver `hard_stop`. `perpetual` выводится из отсутствия legal maturity и mandatory termination, а не задаётся как termination rule. `open_ended` следует хранить как redeemability/termination feature, а timer option — как stopping-time termination с optional cap date. `hard_stop` является только параметром approximation и не подменяет юридическую maturity.

До запуска расчёта engine обязан fail-closed проверить well-posedness: integrability и finite present value, transversality, допустимые characteristic roots, существование/единственность value и exercise boundary, long-run dynamics и extrapolation beyond calibrated market horizons. При нарушении условия результатом должен быть structured `unsupported_model_region`/`non_finite_value`, а не silent fallback на очень далёкую дату.

Минимальный perpetual backlog:

- `MQ1`: perpetual American call/put с dividends/carry и проверкой finite value/exercise boundary;
- `MQ2`: perpetual futures, inverse/quanto perpetuals и venue-specific funding/margin/liquidation rules;
- `MQ2`: perpetual callable/subordinated bond, preferred, AT1 и perpetual/undated CoCo variants;
- `MQR/monitor`: perpetual barrier, chooser/exchange и real-option variants до доказательства well-posedness и business demand;
- `MQR/monitor`: everlasting call/put и funding-sensitive option variants как отдельные product types до подтверждения venue, liquidity, legal terms и owner;
- termination при credit event, delisting, market disruption, benchmark cessation и regulatory event.

Validation должна покрывать zero/negative rates, разные знаки carry/dividend, extreme volatility, credit termination, отсутствие конечной exercise boundary, infinite/non-unique value, finite-horizon convergence и sensitivity к truncation/model horizon. Stationary solver разрешается только для time-homogeneous постановки либо после доказанного Markov state augmentation.

### 3.10. Сложные производные инструменты как anchor-набор для моделей

Model roadmap считается полезным только тогда, когда новые dynamics открывают реальные contract families. Следующие anchors дополняют продуктовый backlog раздела 4 и должны войти в coverage registry:

| Рынок | Расширенный anchor universe |
|---|---|
| Equity/path-dependent | Perpetual, Canary/multi-exercise, timer, Russian, game/Israeli, installment, reload, extendible/cancellable, multi-shout, partial-time/Parisian/window/step/fader/soft barriers, touch/no-touch, drawdown/drawup, ladder, occupation/corridor, passport, alpha-quantile, cliquet/reverse-cliquet |
| Multi-asset | Exchange/spread/ratio/outperformance, best/worst/nth-of, rainbow, Himalaya/Everest/Altiplano/Atlas/Pagoda, quanto/compo, dynamic basket, target-vol and decrement-index options |
| Structured notes | Reverse convertible, Phoenix/autocall/snowball, principal-protected/participation, bonus/twin-win/airbag, callable yield, ELN, accumulator/decumulator, TARN/TARF, PRDC, CPPI and repacks |
| Volatility/correlation/dividend | Variance/volatility options and futures, gamma/corridor/conditional/knock-out variance, forward variance, VIX/VVIX, covariance/correlation/dispersion, skew/kurtosis research, dividend futures/options/swaps |
| Rates | OIS/basis/xccy/three-leg swaps, variable-notional and compounding variants, CMS/CMT/CMS spread, callable/cancellable swaps, digital/flexi/sticky caps, midcurve/xccy swaptions, ratchet/snowball/inverse/steepener/range accrual, deliverable swap futures and bond-future options |
| FX | Flexible/window/participating forwards, collars/seagulls, TARF variants, accrual forwards/options, performance swaps, FX variance/volatility agreements, baskets/triangular products and dual-currency investments |
| Credit | Loan/mortgage CDS, CDS forwards/options/index swaptions, recovery derivatives, TRS, CLN/callable CLN, bespoke/index tranches, forward tranche, tranche option, CDO-squared and CPDO research |
| Commodity/power | Forwards/swaps/swaptions, calendar/location/quality, crack/spark/dark/sour spreads, swing/storage/take-or-pay/tolling, load-following and full-requirements contracts |
| Inflation | ZC/YoY cap/floor and swaptions, LPI/RPI structures, real-rate options, inflation-linked callable notes and cross-currency inflation hybrids |
| Securitized | RMBS/CMBS/ABS/CLO/CMO, IO/PO, PAC/TAC/support, MSR and prepayment options, resecuritization and scenario waterfalls |
| Hybrid/capital | Convertible, exchangeable, mandatory convertible, CoCo/AT1, dual-currency, equity-credit and multi-asset callable notes |
| Alternative/digital | Carbon/REC/GO/biofuel, freight/FFA, HDD/CDD/rain/wind weather, real-estate, catastrophe/industry-loss warranty, mortality q-forward/longevity swap, crypto perpetuals/options/variance, staking and hash-rate contracts |

Для каждого anchor-контракта registry должен явно отвечать: какие models допустимы, какие market objects нужны, какие Greeks/scenarios доступны и какие комбинации пока запрещены.

### 3.11. Расширение numerical и calibration infrastructure

Новые stochastic dynamics без общей инфраструктуры создадут набор несопоставимых pricers. Параллельно с model universe необходимо реализовать:

- единый parameter-resolution/calibration framework с policy `calibrate | market_implied | configured | not_applicable`, multi-start, regularization, parameter transforms, identifiability metrics и сохранением residuals/Jacobian там, где calibration применима;
- arbitrage diagnostics для discount/forward curves, volatility surfaces, smiles, correlations и loss surfaces;
- complementarity solvers `LCP/PSOR` для American/game contracts, PIDE для jumps, adaptive grids, finite elements, quadrature и FFT/FRFT/COS reference routes;
- stochastic mesh, dual upper/lower bounds и regression diagnostics для Bermudan/American Monte Carlo;
- governed semi-analytic approximation library, включая Turnbull–Wakeman/Levy/Curran Asian methods, с явным `product_pricer` kind и error envelope;
- common random numbers, antithetics, control variates, stratification, Sobol/Halton scrambling, Brownian bridge, reproducible seeds и confidence intervals;
- automatic/adjoint differentiation с обязательной сверкой против bump-and-revalue и pathwise/likelihood-ratio estimators;
- portfolio batching, GPU/parallel execution, deterministic CPU reference path, budgets/cancel/progress и performance baselines;
- независимый benchmark harness: closed-form/limiting cases, second implementation, reference fixtures и convergence reports.

Deep PDE/BSDE, neural SDE и learned hedging остаются research methods и не могут автоматически заменять deterministic reference engine.

### 3.12. План поставки model universe

| Волна | Статус | Содержание | Exit criteria |
|---|---|---|---|
| QW0 — Inventory and identity | **Completed — 2026-07-15** | Синхронизировать canonical inventories registry/taxonomy/catalogue; исправить `merton_cos`, `adi`, `afv_convertible`, `jarrow_yildirim`; явно маркировать model/solver roles | Выполнено: три canonical inventory синхронизированы и защищены fail-closed consistency checks; роли размечены явно; zero unknown/duplicate canonical IDs. Физическое разделение выполнено в QW1 foundation |
| QW1 — Classify and expose what exists | **In progress — foundation implemented 2026-07-15** | Классифицировать 38 registry-only entries; создать model/solver/evidence/publication ledgers и product-qualified eligibility; направить products/risk/market components в свои semantic contours | Foundation выполнен: 39 models (18 Q2 / 21 Q1), 107 solver/evidence records, 104 eligibility, 124 enriched publications (85 published / 18 routed / 20 research-only / 1 deprecated), общий fail-closed gate и Swift contracts. Exit ещё не достигнут: 18 routes остаются ledger-only, Q3+ и independent approvals отсутствуют, solver benchmark/performance evidence неполон |
| QW2 — Market baseline | Planned | SVI/SSVI, calibrated local/SLV, multi-curve/RFR rates, robust LMM/HW/G2++, stochastic-intensity credit, commodity forward curves, full inflation model | Приоритетные vanilla/smile/rates/credit products имеют calibration, Greeks и external benchmarks |
| QW3 — Complex derivatives | Planned | Perpetual/open-ended, stochastic-control swing/storage, cross-asset hybrid, securitized loan-level, volatility/correlation and power models | Anchor contracts из §3.10 достигают минимум product L3/model Q4 и имеют отдельный solver evidence |
| QW4 — Production integration | Planned | Выполнить связанные platform epics §§7–8: capture/reprice parity, lifecycle, immutable parameter/calibration bundles, scenario/risk, async scale, model monitoring | Model package достигает Q5, engine — `integrated`, product — L4–L5 |
| QW5 — Independent approval | Planned | Независимая model/solver validation, challenger models, limits, documentation, maker-checker and release gates | Model достигает Q6; `production_allowed=true` получает только независимо одобренная engine-связка |
| QWR — Research stream | Ongoing research | Rough/dynamic-copula/neural/ML и иные экспериментальные approaches | Изолированный Analytics Lab; promotion только через полный Q0–Q6 gate |

Внутри каждой волны приоритет определяется не числом новых названий, а покрытием `(contract feature × model factor × solver × risk measure)`. Первой должна поставляться минимальная независимая вертикаль: market data → calibration → price → Greeks → scenario → capture/reprice → audit.

### 3.13. Definition of Done и coverage ledger для модели

Coverage package должен иметь следующие артефакты. Пункты 1–5 и 11 определяют model `Q`; пункты 6–10 прикрепляются к `SolverEvidenceRecord`/`EngineEligibility` и не должны искусственно повышать `Q` модели:

1. формальное описание dynamics, state variables, measure, numeraire, parameter domain и units;
2. условия существования, no-arbitrage, moment explosion/stability и известные ограничения;
3. parameter-resolution policy; для calibratable model — instruments, objective, weights, constraints, regularization и identifiability diagnostics, иначе обоснованный `not_applicable`;
4. immutable parameter artifact с market snapshot, timestamps и build provenance; calibration residuals/Jacobian — когда применимо;
5. closed-form/limiting benchmarks и независимая реализация либо внешний эталон;
6. convergence, bias, Monte Carlo confidence interval и reproducibility evidence;
7. Greeks и сверка bump/AAD/pathwise estimators с заявленной differentiability;
8. полный market-dependency и engine-capability contract;
9. unsupported regions, fallback policy и запрет silent substitution модели;
10. performance envelope по dimension/path/grid/portfolio size;
11. independent validation, owner, version, change history, monitoring and deprecation policy.

Единый `QuantComponentCoverageRecord` должен содержать как минимум:

```text
component_id, component_kind, component_version, asset_class,
state_factors, dynamics, measure, numeraire, parameter_schema,
parameter_resolution_policy, calibration_set,
market_dependencies, supported_product_features, numerical_methods,
risk_measures, limitations, q_level_if_model, component_evidence_status,
solver_evidence_refs, engine_eligibility_refs, governance_status,
benchmark_references, implementation_owner, validation_owner
```

Обязательный `component_kind`: `stochastic_model | market_model | smile_parameterization | numerical_solver | calibration_method | product_pricer | risk_methodology | market_infrastructure`. Разрешённые статусы: `identified`, `researching`, `implemented`, `calibratable`, `benchmarked`, `integrated`, `validated`, `production`, `research-only`, `out-of-scope`, `deprecated`. Coverage dashboard должен строиться из registry и отдельно показывать product `L`, model `Q`, solver evidence и engine eligibility, а не выводить готовность из наличия Python-функции.

### 3.14. Внешняя база полноты и регулярный gap review

Coverage registry необходимо пересматривать не реже одного раза в квартал и при появлении нового product request. Базовые внешние ориентиры:

- [FpML Product List](https://www.fpml.org/docs/FpML5-products.pdf) и [FpML Products Framework](https://www.fpml.org/docs/FpML5-products-framework.pdf) — стандартизованные OTC-семейства и extensible generic products;
- [FINOS Common Domain Model: Product Model](https://cdm.finos.org/docs/product-model/) — композиция economic terms и payout primitives;
- официальные каталоги [QuantLib instruments](https://github.com/lballabio/QuantLib/tree/master/ql/instruments) и [pricing engines](https://github.com/lballabio/QuantLib/tree/master/ql/pricingengines) — open-source benchmark breadth и независимые engine candidates;
- [OpenGamma Strata Product Coverage](https://strata.opengamma.io/product_coverage/) и [API](https://strata.opengamma.io/apidocs/) — typed products, measures, scenarios и market-data architecture;
- биржевые product universes [Cboe](https://www.cboe.com/tradable-products/product-list), [CME](https://www.cmegroup.com/markets/products) и [ICE](https://www.ice.com/products/) — listed options/futures, volatility, commodity, weather, environmental и alternative markets;
- [Cboe FLEX specifications](https://www.cboe.com/tradable_products/equity_indices/flex_options/specifications) — настраиваемые listed contract terms;
- академический первоисточник по [perpetual American options](https://arxiv.org/abs/0812.0556), первоначальный research proposal [everlasting options](https://www.paradigm.xyz/2021/05/everlasting-options/) и regulatory consultation [CFTC request for comment on perpetual derivatives](https://www.cftc.gov/media/12041/Perpetuals_RFC042125/download) — контекст для разграничения infinite-horizon exercise и funding-based perpetual contracts; proposal/RFC не являются доказательством production maturity.

Quarterly review должен выдавать machine-readable diff: новые/изменённые contract families, недостающие models, solver gaps, regulatory/market conventions, приоритет, owner и решение `implement | research | monitor | out-of-scope`. Этот процесс вместе с composable Custom Product Engine позволяет систематически приближаться к полноте и явно фиксировать непокрытые области.

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
11. **Fail-closed server validation закрыта частично в QW0.** `/pricing/validate` и workstation `/pricing/price` теперь применяют одну effective schema после environment defaults и отклоняют unknown engine/fields, type/choice/range violations. Остаются required-field semantics, cross-field/product well-posedness и унификация проверки остальных API-контуров.
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
- Quant component identity: **QW0 закрыт; QW1 foundation реализован — 124 enriched publications (85 published / 18 routed / 20 research-only / 1 deprecated), 39 model definitions (18 Q2 / 21 Q1), 107 solver/evidence records и 104 product-qualified eligibility; contour/evidence hardening остаётся**.
- Каталог типовых продуктов: **широкий, но неполный**.
- Structured note coverage: **точечное и преимущественно шаблонное**.
- Capture/repricing parity: **критический пробел, 16/50**.
- Единый product registry: **отсутствует; 50 derivative + 14 bond templates разделены**.
- Lifecycle/event model: **требует нового общего слоя**.
- Custom exotic authoring: **недостаточно; нужен декларативный engine**.
- Правильный следующий шаг: **закрыть QW1 contour/evidence hardening и одновременно начать P0 единого product/lifecycle/run contract; затем QW2 market baseline и product waves**.
