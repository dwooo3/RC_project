# Проверка реализации инструкции Calypso risk/pricing

**Дата проверки:** 2026-07-09  
**Инструкция:** `/Users/dmitriykiselev/Downloads/calypso_risk_modules_models_detailed.md`  
**Проект:** `/Users/dmitriykiselev/Library/Mobile Documents/com~apple~CloudDocs/Python/RC_project`  
**Ограничение:** код проекта не изменялся; создан только этот отчет.

## Итоговый вывод

Проект **частично и достаточно широко реализует** карту из инструкции: есть Front Office/Pricing Workstation, market data snapshots, curves/surfaces, portfolio/risk service, Desk Risk-style сценарии, Market Risk-style HypPL/VaR/ES/backtesting, P&L attribution, XVA/CCR слой, governance registry и UI/API endpoints.

Но текущая реализация больше соответствует **research/demo risk workstation**, а не production-grade Calypso-like risk stack. Главные разрывы: нет явного объекта `PricingEnvironment`/`PricerConfiguration`, нет полноценного trade capture -> book/trade filter -> persistent portfolio workflow, нет validated-моделей в реестре, факторная карта full revaluation укрупнена, а P&L Explained и Market Risk не закрывают lifecycle/official P&L/stress VaR/incremental VaR на уровне Calypso.

## Проверки

### Статическая проверка

Проверены ключевые слои:

- `api/server.py`, `api/context.py`, `api/marketrisk.py`, `api/pricing_workstation.py`
- `domain/market_data.py`, `domain/portfolio.py`, `domain/scenario.py`, `domain/risk_factors.py`, `domain/results.py`
- `services/pricing_service.py`, `services/risk_service.py`, `services/portfolio_service.py`, `services/market_data_service.py`, `services/governance_service.py`, `services/analytics_views.py`
- `risk/var.py`, `risk/historical_var.py`, `risk/stress.py`, `risk/xva.py`, `risk/vol_surface.py`, `risk/vol_cube.py`
- `models/*`, `instruments/*`, `curves/*`
- Swift UI screens in `macapp/Sources/RiskCalc/*`
- Existing project notes including `PRICING_RISK_ISSUES_AND_PLAN_2026_07.md`

### Тестовый прогон

Команда:

```bash
python3 -m pytest tests/test_marketrisk_api.py tests/test_var.py tests/test_portfolio_service.py tests/test_pricing_workstation.py tests/test_market_data_foundation.py tests/test_governance_platform.py tests/test_pricing_service_full_coverage.py tests/test_fixed_income_pricing_service.py tests/test_analytics_views.py tests/test_moex_validation.py tests/test_eod_ingest_job.py tests/test_validation_reports.py -q
```

Результат:

```text
205 passed, 1 warning in 153.80s
```

Warning:

- `risk/var.py:366 RuntimeWarning: invalid value encountered in scalar divide` в `christoffersen_test` при backtest edge case. Это не ломает текущий тест, но лучше обработать случай, когда нет переходов исключений.

### Runtime-проверка Market Risk

Локальная БД `data/market_data.sqlite` присутствует.

`api.marketrisk.factor_shifts(CONTEXT, window=500)`:

- scenarios: `500`
- factors: `IMOEX`, `KBD 5Y`, `RVI`, `USD/RUB fix`
- FX factor active: `has_fx=True`
- non-zero FX moves: `284 / 500`

`api.marketrisk.overview(CONTEXT, confidence=0.99, window=500, horizon=1)`:

- methods: `historical`, `parametric`, `parametric_t`, `monte_carlo`, `evt`
- historical VaR 99% / 1d: около `2.12 млн`
- ES 99% / 1d: около `2.90 млн`
- data quality warnings: `[]`

Backtest 99%:

- observations: `250`
- breaches: `1`
- traffic light: `green`

## Матрица соответствия

| Блок инструкции | Статус | Что реализовано | Основные замечания |
|---|---:|---|---|
| End-to-end цепочка `market data -> pricing environment -> trade -> portfolio -> risk -> drill-down` | Частично | Есть market data snapshots, pricing service, portfolio service, risk service, API/UI. | Нет явного `PricingEnvironment`/`PricerConfiguration`; runtime portfolio сейчас seeded demo book, а не полноценный trade capture/book filter контур. |
| Front Office / Pricing Workstation | Хорошо / частично | `api/pricing_workstation.py`: 37 products, 87 engines, 7 asset classes; UI `PricingWorkstationView.swift`; full-revaluation ladders/scenarios. | Нет сохранения сделки в реальный портфель как основного workflow; есть несколько параллельных pricing catalogues. |
| Market Data Manager / curves / surfaces | Частично хорошо | `MarketDataSnapshot`, versioning, MOEX provider, quality checks, curves, FX, vol surfaces, hazard curves, data-health endpoints. | Bloomberg/Reuters только prepared interfaces; IR vol demo; credit hazard mostly demo/tier-level; historical IV not accumulated as full factor history. |
| Desk Risk: sensitivities, simulations, what-if | Частично хорошо | Portfolio exposures, bucket/factor aggregation, full-reprice scenarios, historical scenario library, what-if grid, ladder. | Факторная карта coarse: equity/rate/vol/fx shocks применяются по общим параметрам; no full risk-factor mapping to exact curve/surface/quote/tenor. |
| Rates Sensitivity / bucketed DV01 | Частично | Bond KRD exists; DV01 exposures; rate shock scenarios. | Market Risk uses KBD 5Y as rate factor; no multi-tenor/PCA VaR workflow yet; steepener/flattener approximated by aggregate DV01. |
| Market Risk / ERS two-step process | Частично хорошо | `api/marketrisk.py` explicitly implements shifts generation + HypPL full revaluation + VaR/ES/backtesting. | Stress VaR and Incremental VaR are not first-class workflows; MC VaR is fitted-normal, not matrix-transform correlated factor simulation. |
| Historical VaR / ES | Реализовано | `risk/var.py`, `risk/historical_var.py`, `RiskService`, `api/marketrisk.py`; ES >= VaR tested. | For `api.marketrisk`, horizon > 1 still uses sqrt-time scaling, not overlapping HypPL windows. |
| Monte Carlo VaR | Частично | Return-based MC VaR and full-reprice helper exist. | No Calypso-style risk-factor covariance/matrix transform workflow for Market Risk scenarios. |
| Stress VaR | Не закрыто как workflow | Stress/scenario tools exist in `risk/stress.py` and workstation scenarios. | No dedicated stress VaR window/period methodology, report, or backtesting integration. |
| Incremental VaR / marginal/component VaR | Частично | Component/marginal functions exist in `risk/var.py` and `risk/historical_var.py`. | No user-facing Incremental VaR workflow `VaR(portfolio + trade) - VaR(portfolio)`. |
| HypPL | Частично хорошо | HypPL full revaluation over historical factor shifts in `api/marketrisk.py`. | Cache key is snapshot/window only; when real portfolio editing appears, it must include portfolio composition hash. |
| Backtesting | Реализовано частично | Rolling VaR vs next-day HypPL, Kupiec, Christoffersen, traffic light. | Christoffersen edge-case warning; UI/logic should distinguish conservative vs aggressive rejection. |
| Official P&L / Live P&L / P&L Explained | Частично | `PortfolioService.explain_pnl`, `risk/stress.pnl_explain`, analytics attribution. | This is factor/Greeks P&L explain, not official/live P&L with actual vs hypothetical, lifecycle/system effects, fees, new trades, resets, exercise, maturities. |
| XVA / CCR | Частично | IRS exposure profile, CVA/DVA/FVA/MVA/KVA, SA-CCR simplified, Hull-White exposure layer. | Primarily IRS/netting-set demo workflow; not integrated as universal pricing/risk layer for all derivatives. |
| Fixed Income / Bonds | Частично хорошо | Fixed bond, FRN, callable/putable, amortizing, step, inflation-linked, repo, futures, KRD, accrual/clean/dirty price. | Warnings explicitly say no holiday-calendar source, irregular stubs, ex-coupon, full callable/putable production mechanics. FRN noted as weak/prototype in internal plan. |
| Linear IRD | Частично | IRS, FRA, cap/floor and dual-curve support in places; xccy curve bootstrap. | No full trade capture conventions, reset calendars, payment lag/fixing calendars at Calypso depth. |
| Nonlinear IRD | Частично | Cap/floor, swaption, G2++, LMM, BK, Cheyette, AMC Bermudan, SABR/cube demo. | IRVOL source missing; calibration mostly demo/manual; no production model validation evidence. |
| FX / FXO | Частично | FX forward, NDF, Garman-Kohlhagen, smile/Vanna-Volga, FX RR/BF surface, USD/RUB factor in Market Risk. | FX factor is CBR-fixing based and sparse; no full premium/settlement convention workflow or live FX pricing contour. |
| Equity / EQD | Частично | Equity spot, vanilla/american/exotics, Heston/Fourier/PDE/trees, variance/correlation/basket/structured notes. | Many engines are approximation/prototype; dividends use rough/trailing assumptions, no full corporate action/lifecycle pipeline. |
| Credit derivatives | Частично | CDS, ISDA CDS, risky bond, CDO/kth-to-default, structural credit, hazard curves. | Real CDS market data absent; hazard mostly demo or proposed from z-spreads; no full credit event/index constituent workflow. |
| Money Market / Loans / structured flows | Частично | Deposits, T-bills, CP, repo, structured flows/products. | Not full loan lifecycle/rollover/reset workflow. |
| Data quality / scheduled tasks | Частично | EOD ingest, validation reports, data health, quality persistence tests. | Production sign-off workflow and durable calculation audit are incomplete. |
| Governance / model validation | Частично, production gap | Model registry, status, limitations, blocking research models by default, UI governance. | Registry summary: 113 models, 0 `Validated`, 101 `Approximation`, 12 `Prototype`. This is the main blocker for production risk use. |

## Модели и прайсеры: что отсутствует и что доработать

Текущий каталог Pricing Workstation содержит `37` продуктов и `87` engines; модельный реестр содержит `113` model IDs. Ниже список именно относительно Calypso-инструкции, а не относительно математической полноты библиотеки.

### Отсутствуют как явный product/pricer workflow

| Блок | Нет явного workflow / pricer | Комментарий |
|---|---|---|
| Core pricing setup | `PricingEnvironment`, `PricerConfiguration`, `PricingParameters`, mapping `product -> pricer -> curves/surfaces/measures` | Сейчас это распределено по `PricingService`, snapshot IDs и параметрам запроса; Calypso-like объект окружения оценки отсутствует. |
| IRD nonlinear | `LGMM` как явно названный pricer, `cancellable swap`, `capped swap`, `collar`, `spread cap/floor`, `inflation cap/floor` | Есть Hull-White tree, G2++, LMM, BK, Cheyette, cap/floor/swaption/Bermudan, но Calypso-линейка nonlinear IRD покрыта не полностью. |
| IRD linear / rates | полноценный `basis swap`, `single-leg swap`, `non-deliverable swap`, `CMS trade capture` как trade workflow | В registry есть `basis_swap`, есть IRS/FRA/CMS approximation, но не все выведено как полноценный продукт с conventions/cashflows/resets. |
| FX / FXO | FX-specific `barrier`, `digital`, `asian/averaging`, `accrual`, `lookback`, `window forward`, `flexible forward`, `merchant FX`, `precious metals` | Generic barrier/digital/asian/lookback есть в equity/hybrid engines, но без FXO delta/premium/settlement/barrier/fixing conventions. |
| Equity / EQD | `equity forward`, `equity future`, `equity swap`, `dividend swap`, `variance option`, `correlation swap`, `warrant`, ADR-specific workflow | Есть vanilla/exotics/variance swap/basket/structured engines, но не полная EQD trade-capture линейка. |
| Credit derivatives | `CDS Index`, `CDS Index Option`, `Quanto CDS`, `Credit Default Loan`, `Credit Default Swaption`, `Credit Futures`, `Asset Swap`, credit-event/index workflow | Есть single-name CDS, curve CDS, ISDA CDS, risky bond, copulas/structural credit; index/quanto/option/lifecycle часть отсутствует. |
| Securitized FI | ABS workflow, ABS tranche pricing UI, pool/tranche assumptions | `abs`/`mbs` есть в registry/code, но не как зрелый Calypso-style product workflow. |
| Money market / loans | `call notice`, `bank debt`, `commercial loan`, `dual-currency money market`, `intraday money market`, `Islamic loan/deposit`, `structured flows` | Есть deposit/T-bill/CP/repo, но loans/MM lifecycle покрыт узко. |
| Market Risk | `Stress VaR` как отдельный report, `Incremental VaR` workflow, MC VaR `matrix transform`, market-risk what-if для измененного портфеля | Есть VaR/ES/HypPL/backtesting и full-reprice scenarios, но эти Calypso workflows не оформлены отдельно. |
| P&L | `Official P&L`, `Live P&L`, actual vs hypothetical P&L source, lifecycle/system/time effects | Есть model/factor P&L attribution, но не official/live P&L контур. |

### Присутствуют, но требуют доработки

| Модель / группа | Текущий статус | Что доработать |
|---|---|---|
| Все production-кандидаты в `models/registry.py` | `0 Validated`, `101 Approximation`, `12 Prototype` | Запустить программу model validation: benchmark sources, tolerances, evidence, owner/sign-off, promotion to `Validated`. |
| `fixed_bond`, `frn`, `callable_bond`, `inflation_linked_bond` | Есть pricing/service/UI coverage | Calendar source, irregular stubs, ex-coupon, callable/putable event mechanics, FRN par-reset/projection logic, production conventions. |
| `mbs`, `abs` | Есть код/registry, частично UI for MBS | Pool assumptions, prepayment/default calibration, tranche cashflow reports, OAS/spread risk, production data inputs. |
| `irs`, `fra`, `basis_swap`, `xccy_swap` | IRS/FRA/XCCY есть, basis частично | Reset/fixing calendars, payment lags, day-count conventions per leg, generated cashflow audit, curve mapping by currency/index/CSA. |
| `capfloor`, `swaption`, `bermudan_swaption`, `short_rate`, `g2pp`, `lmm`, `bk`, `cheyette`, `swap_market_model` | Rates options toolkit широкий | Real IRVOL source, cap/floor vs swaption surface mapping, calibration errors, exercise/event handling, vega bucketing, stress stability. |
| `sabr`, `swaption_cube`, `risk.vol_surface.CalibratedSurface` | SABR есть, часть surface-aware pricing есть | Исторические IV-ряды, market quotes, interpolation/extrapolation policy, stale/missing quote handling, surface shock methodology. |
| `fx_forward`, `ndf`, `garman_kohlhagen`, `fx_smile`, `vanna_volga` | Есть FX линейка | FX delta conventions, premium/settlement currency, fixing schedules, smile from market data, separate FXO exotic workflows. |
| Equity vanilla/exotics: `black_scholes`, `black76`, `bachelier`, `heston_cf`, `bates`, `merton_jump`, `kou`, `variance_gamma`, `nig`, `cgmy`, `rough_bergomi`, `pde_cn`, `mc_lsm`, `asian`, `barrier`, `digital`, `lookback`, `variance_swap` | Много engines, часть Research/Prototype | Dividends/borrow curves, corporate actions, listed-option specs, MC common random numbers, external validation, market calibration. |
| Multi-asset/structured: `multi_asset`, `structured_autocall`, `structured_basket_note`, `tarn`, `accumulator`, `convertible_bond`, `afv_convertible` | Есть pricing engines | Correlations from history, basket builder workflow, issuer/credit/funding layer, payoff/lifecycle events, validation vs term sheets. |
| Credit: `cds`, `cds_curve`, `cds_isda`, `risky_bond`, `gaussian_copula`, `t_copula`, `clayton_copula`, `merton_structural`, `black_cox`, `kmv` | Есть single-name/portfolio credit toolkit | Real hazard curves from z-spreads/CDS where available, recovery governance, index constituents, credit events, JTD mapping, quanto/index option layer. |
| XVA/CCR: `cva_exposure`, `cva_dva`, `xva_suite`, `cva_wwr`, `frtb_sba`, `frtb_ima` | Есть IRS/netting-set/XVA/FRTB pieces | Integrate across derivative products, CSA/netting data model, real-world vs risk-neutral calibration, SA-CVA sensitivities, durable reports. |
| VaR stack: `var_historical`, `var_mc`, `var_parametric`, `var_full_reprice`, `evt_var`, `copula_var` | Есть VaR/ES/HypPL/backtesting | Multi-factor covariance/matrix transform MC, overlapping HypPL horizons, Stress VaR, Incremental VaR, factor attribution, missing-data policy. |
| Market data providers: MOEX, demo, manual, CSV; Bloomberg/Reuters interfaces | MOEX работает, Bloomberg/Reuters заглушки | Provider integration, source priority, production fallback policy, full history for FX/vol/credit/rates factors. |

## Замечания

1. **Нет явного Pricing Environment.** Сейчас `PricingService` принимает snapshot/curve/surface IDs и governance metadata, но нет единого объекта, где явно зафиксированы pricer selection, pricer configuration, pricing parameters, pricing measures, curve/surface/model mapping для FO/Risk/EOD/VaR/Stress контуров.

2. **Market Risk работает по demo book.** `api/context.py` создает 4 хардкод-позиции: equity call, fixed bond, IRS, USD/RUB forward. Это полезно для workstation, но не закрывает Calypso trade browser / trade filter / book hierarchy.

3. **Full revaluation есть, но factor mapping грубый.** `PortfolioService.full_reprice_pnl` шокирует поля по именам (`S`, `r`, `sigma`, FX spot-like params). Для реального портфеля нужен mapping `position -> risk factor -> quote/curve/surface/tenor/currency`.

4. **FX-фактор уже подключен, но ряд sparse.** В локальной БД USD/RUB factor активен, но ненулевые движения только 284 из 500 сценариев. Это лучше, чем нулевой FX, но методология даты фиксинга/пропусков требует согласования.

5. **Rate VaR пока односегментный.** Market Risk использует KBD 5Y rate factor. Для Calypso-style Rates Risk нужны multi-tenor shifts, bucketed VaR, PCA level/slope/curvature или full curve history.

6. **Vol factor использует RVI proxy.** RVI применяется как общий vol shock. Для vega-VaR нужны per-underlying/per-surface historical IV series.

7. **Horizon > 1 в Market Risk масштабируется `sqrt(horizon)`.** В `risk/var.py` уже есть overlapping-window logic для return-ряда, но `api/marketrisk.py` пока масштабирует HypPL через sqrt-time.

8. **Stress VaR и Incremental VaR не оформлены как пользовательские workflows.** Нужны отдельные reports/methodology inputs: stress window, included factors, current vs historical portfolio, full reval vs approximation.

9. **P&L Explained не равен Official/Live P&L.** Текущий explain - это факторная/Greeks attribution. Не хватает actual P&L source, HypPL/Actual split, lifecycle/system effects, reset/fixing/coupon/exercise/maturity/corporate action effects.

10. **Audit trail не durable.** `GovernanceService.audit_trail()` явно возвращает placeholder, если нет in-memory `AuditService`. Для production validation нужен persistent calculation audit.

11. **Model validation status production blocker.** Ни одна модель не имеет статуса `Validated`; сервисы честно показывают `Approximation`/`Prototype`, но это означает, что результаты нельзя трактовать как production model-approved.

12. **Комментарий в `api/marketrisk.py` устарел.** В начале файла указано, что FX history too short and FX factor is zero. По текущей локальной БД `has_fx=True`; комментарий стоит обновить при следующей правке.

## Вопросы

1. Какой реальный portfolio/book scope должен быть первым: облигации/IRS/FX, structured notes, equity derivatives, credit, или смешанная книга?

2. Нужен ли следующий шаг именно как Calypso-like production contour: `Trade Capture -> Book/Trade Filter -> Pricing Environment -> EOD/Market Risk reports`, или достаточно research/pricing workstation?

3. Какие FO/Risk/EOD/VaR/Stress pricing environments должны существовать и чем они должны отличаться?

4. Для FX-фактора использовать CBR fixings, futures Si/CR series или оба варианта? Нужны ли EUR/RUB и CNY/RUB факторы сейчас?

5. Есть ли источник IR volatility: Bloomberg/Cbonds/broker CSV/ручная ATM swaption matrix? Без него IR options remain demo/manual.

6. Для credit/hazard curves принять recovery 40%, 30%, 20% или per-issuer assumptions? Нужны tier-level curves или issuer-level curves?

7. Какой стандарт VaR нужен: confidence, horizon, history window, absolute/relative shifts, stress windows, treatment of missing data, current vs historical portfolio?

8. Нужен ли Incremental VaR для hypothetical trade до trade capture или только после появления persistent portfolio?

9. Откуда брать actual/official P&L для P&L Explained: ручной импорт, broker statement, accounting source, или пока считать только HypPL/model explain?

10. Запускать ли отдельную программу model validation с external benchmarks и промоушеном `Approximation -> Validated`?

## Рекомендации по приоритету

1. Ввести явный `PricingEnvironment` contract: name, purpose, snapshot, curve/surface mappings, pricer mappings, parameter set, measure set.

2. Сделать persistent portfolio/trade capture workflow и включить portfolio hash в HypPL cache key.

3. Перевести Market Risk с 4 generic factors на factor map: per-name equity, per-pair FX, multi-tenor rates, per-surface vol.

4. Добавить first-class reports: Stress VaR, Incremental VaR, Data Quality Analysis for Market Risk.

5. Развить P&L Explained до actual vs hypothetical + lifecycle/system/time/market-data effects.

6. Начать model validation program: выбрать 10-15 production-priority models, зафиксировать benchmarks, tolerances, validation evidence, owner/sign-off.

## math_validation

### Короткий вывод

После углубленной проверки я **не могу честно присвоить 100% уверенность ни одной модели как production-validated**. Причина не в том, что все модели плохие, а в том, что в проекте нет независимого model-validation пакета: benchmark vectors от внешних библиотек/вендоров, официальных market-data срезов, tolerance matrix, validation sign-off, owner approval и promotion в `Validated`.

Фактический статус реестра: `113` моделей, `0 Validated`, `101 Approximation`, `12 Prototype`. Полный тестовый прогон прошел, но с одним предупреждением:

```text
python3 -m pytest -q
1043 passed, 1 warning in 457.35s
```

Предупреждение:

```text
risk/var.py:366 RuntimeWarning: invalid value encountered in scalar divide
```

Итоговая классификация:

- **Confirmed defect:** `christoffersen_test`; `basket_option(..., method="moment_matching")`.
- **Material methodology gap:** Market Risk horizon scaling, MC VaR, historical VaR wrappers, full-reprice factor mapping, prototype/analytics-lab engines, demo/manual market data.
- **Conditionally acceptable under narrow assumptions:** vanilla closed-form, basic trees/PDE, fixed cashflow DCF, IRS/FRA/cap/floor/swaption Black-style pricing, Heston/Fourier/Levy models where internal parity/degeneration tests exist.
- **Not production-safe without remediation:** all `Prototype` models and all `Approximation` models that depend on calibration, market conventions, path simulation, credit correlation, XVA/FRTB/regulatory treatment, or structured-product lifecycle.

### Теоретическая база, по которой сверялось

- Black-Scholes-Merton: Black & Scholes, *The Pricing of Options and Corporate Liabilities*; Merton, *Theory of Rational Option Pricing*: [JSTOR Black-Scholes](https://www.jstor.org/stable/1831029), [JSTOR Merton](https://www.jstor.org/stable/3003143).
- CRR / lattice pricing: Cox-Ross-Rubinstein binomial model and backward induction: [Binomial options pricing model](https://en.wikipedia.org/wiki/Binomial_options_pricing_model).
- Heston stochastic volatility: stochastic variance/CIR process and semi-closed characteristic-function pricing: [Heston model](https://en.wikipedia.org/wiki/Heston_model).
- Fourier/Carr-Madan: option pricing from characteristic functions via Fourier/FFT: [Carr-Madan formula](https://en.wikipedia.org/wiki/Carr%E2%80%93Madan_formula).
- SABR: Hagan et al. market-standard smile approximation as referenced in RFR/SABR literature: [SABR smiles for RFR caplets](https://arxiv.org/abs/2004.04501).
- LMM/BGM: forward-rate lognormal market model for caps/swaptions: [LIBOR market model](https://en.wikipedia.org/wiki/LIBOR_market_model).
- VaR backtesting and HypPL/APL distinction: BIS Basel backtesting framework: [bcbs22.pdf](https://www.bis.org/publ/bcbs22.pdf).
- FRTB / market-risk requirements: BIS minimum capital requirements for market risk: [d457.pdf](https://www.bis.org/bcbs/publ/d457.pdf).
- ES/CVaR and EVT/POT/GPD: [Expected shortfall](https://en.wikipedia.org/wiki/Expected_shortfall), [Generalized Pareto distribution](https://en.wikipedia.org/wiki/Generalized_Pareto_distribution).

### Подтвержденные ошибки

| Severity | Модель / прайсер | Где | Что не так | Проверка / пример | Рекомендация |
|---|---|---|---|---|---|
| High | `christoffersen_test` | `risk/var.py:353-376` | При массиве исключений длиной `0` или без переходов знаменатель `T00+T01+T10+T11` равен нулю, `pi` становится `NaN`. Это подтверждено полным pytest warning. | `tests/test_marketrisk_api.py::test_backtest_coherent` дает `RuntimeWarning`. | Обработать `len(exceptions)<2` и нулевое число переходов: вернуть `not_applicable`/`insufficient_transitions`, не считать LR. |
| High | `basket_option(..., method="moment_matching")` | `instruments/multi_asset.py:159-171` | В lognormal moment matching неправильно маппится basket forward в BSM spot и не annualize-ится `sigma_b`. Для `T != 1` цена materially завышается. | Пример: assets `[100,100]`, weights `[0.5,0.5]`, `T=2`, `r=5%`, vols `[20%,25%]`, rho `0.3`: текущая формула `21.4188`, MC `15.3009 +/- 0.0928`, корректный Levy/Black forward moment-match около `15.2865`. | Для approximation использовать `sigma_ann=sqrt(log(m2/m1^2)/T)` и Black-76 on basket forward `F=m1`, либо убрать этот режим из production catalog до исправления. |

### Методологические ошибки и существенные ограничения

| Severity | Модель / блок | Где | Вывод |
|---|---|---|---|
| High | `api.marketrisk.overview` / `var_full_reprice` | `api/marketrisk.py:104-143` | HypPL для `horizon > 1` масштабируется через `sqrt(horizon)`. Для full-revaluation historical VaR это не исторический многодневный P&L; нужны overlapping h-day HypPL windows. Сам `risk.var._horizon_returns` уже содержит правильную идею, но API ее не использует. |
| High | `risk.historical_var.hs_var`, `hs_age_weighted` | `risk/historical_var.py:27-69` | Эти wrappers продолжают `sqrt(horizon)` scaling для historical P&L. Это допустимо только как parametric approximation, но не как non-parametric historical VaR. |
| High | `var_mc`, `montecarlo_var`, `mc_var_full_reprice` | `risk/var.py:181-200`, `risk/historical_var.py:144-180` | MC VaR строится из fitted normal или hardcoded independent shocks. Это не Calypso-style correlated risk-factor simulation/matrix transform и не отражает real factor covariance, fat tails, volatility surfaces, curve-tenor map. |
| High | Portfolio full revaluation factor map | `services/portfolio_service.py:142-175` | Full reprice действительно вызывает прайсеры, но shock mapping coarse: все spot-like поля, rates-like поля и vol-like поля шокируются generic ключами. Нет `position -> exact risk factor -> quote/curve/surface/tenor/currency/index` mapping. Для desk/market risk это может дать неверный P&L attribution. |
| Medium | Exotic finite-difference Greeks | `services/portfolio_service.py:627-680` | Для barrier/asian/lookback/spread/basket/autocall Greeks считаются bump-and-reprice с фиксированным seed/MC-шумом и грубым bump size. Это приемлемо для analytics, но не для production sensitivities/hedging. |
| Medium | `evt_var` | `risk/var.py:207-240` | POT/GPD реализован, но threshold selection, stability diagnostics, declustering, finite-input validation и regime checks отсутствуют. `sqrt(horizon)` после EVT также требует отдельного model assumption. |
| Medium | Backtesting traffic light | `api/marketrisk.py:189-194`, `risk/historical_var.py:210-218` | Есть Basel-like zones, Kupiec/Christoffersen, но логика зон упрощена ratio-thresholds; для regulatory interpretation лучше использовать binomial thresholds per confidence/window и отдельные HypPL/APL outcomes. |

### Условно корректные модели при узких допущениях

Эти модели выглядят математически согласованными с базовой теорией и внутренними тестами, но **не имеют production sign-off**:

| Группа | IDs | Условие корректности |
|---|---|---|
| Vanilla closed-form | `black_scholes`, `black76`, `garman_kohlhagen`, `bachelier` | European exercise, continuous rates/dividend/foreign-rate yield, no discrete dividends/corporate actions, clean inputs, no market-convention ambiguity. |
| Basic lattices / PDE | `binomial_crr`, `binomial_lr`, `binomial_jr`, `binomial_tian`, `trinomial`, `pde_cn` | Enough grid/time steps, no discontinuity/monitoring mismatch, accepted tolerance vs BSM/CRR/closed-form references. |
| Fourier / stochastic-vol / Levy | `heston_cf`, `bates`, `merton_jump`, `merton_cos`, `kou`, `variance_gamma`, `nig`, `cgmy`, `carr_madan`, `adi`, `heston_adi`, `mc_heston_qe` | Parameter domains valid, CF martingale compensator valid, numerical integration/truncation tolerances monitored, external benchmark pack added. |
| Vanilla rates | `fixed_bond`, `custom_bond`, `irs`, `fra`, `basis_swap`, `capfloor`, `swaption`, `cms_swap` | Regular schedules/conventions, supplied curves/vols are valid, no lifecycle/stub/calendar/ex-coupon/resets beyond implemented assumptions. |
| Linear FX | `fx_forward`, `ndf`, `garman_kohlhagen`, `fx_smile`, `vanna_volga` | Correct domestic/foreign currency convention, settlement/premium delta convention explicitly selected, smile source valid. |
| Basic credit | `cds`, `cds_curve`, `cds_isda`, `risky_bond`, `merton_structural`, `black_cox`, `kmv` | Flat or bootstrapped hazard assumptions accepted, recovery governed, ISDA/calendar/accrual conventions benchmarked externally. |
| Basic risk metrics | `var_historical`, `var_parametric`, `var_mc`, `evt_var`, `copula_var`, `var_full_reprice` | Only as analytics approximations until horizon methodology, factor map, data policy and backtesting edge-cases are fixed. |

### Модели, которые нужно доработать или не считать корректными для production

| Группа | IDs | Причина |
|---|---|---|
| Prototype models | `mc_lsm`, `mc_heston`, `callable_bond`, `frn`, `short_rate`, `asian`, `multi_asset`, `cva_dva`, `structured_autocall`, `cln_ftd`, `structured_basket_note`, `portfolio_aggregation` | В реестре статус `Prototype`; отсутствует достаточная validation evidence. |
| Analytics-lab stochastic/exotic models | `rough_bergomi`, `local_vol_mc`, `mc_gbm`, `mc_heston_qe`, `heston_cf`, `sabr`, `bates`, `kou`, `variance_gamma`, `nig`, `cgmy`, `garch` | Часть тестов есть, но нужны calibration evidence, market benchmark datasets, stability grids, arbitrage checks и model-risk limits. |
| Structured/hybrid | `structured_autocall`, `structured_basket_note`, `tarn`, `accumulator`, `convertible_bond`, `afv_convertible`, `multi_asset`, `basket_option`, `rainbow_option` | Payoff/lifecycle complexity, issuer/funding/credit layer, correlation calibration, pathwise Greeks and term-sheet validation не закрыты. |
| Callable/FRN/FI production | `callable_bond`, `frn`, `amortizing_bond`, `step_bond`, `inflation_linked_bond`, `bond_future`, `repo` | Есть полезные формулы, но календарь, stubs, ex-coupon, reset timing, CTD/conversion-factor governance, callable event schedules и OAS calibration не production-complete. |
| Rates exotics | `bermudan_swaption`, `amc`, `g2pp`, `lmm`, `bk`, `cheyette`, `swap_market_model`, `sabr`, `swaption_cube` | Теоретическая база есть, но требуется реальная IRVOL cube/strip calibration, exercise-boundary validation, calibration error reports, stress stability и benchmark against QuantLib/vendor. |
| Credit portfolio | `gaussian_copula`, `t_copula`, `clayton_copula`, `cdo_tranche`, `kth_to_default`, `cln_ftd` | Корреляция/PD/recovery/tenor model risk высок; Gaussian copula не отражает tail dependence, для tranche pricing нужны market quotes и calibration. |
| XVA/CCR | `cva_exposure`, `cva_dva`, `xva_suite`, `cva_wwr` | Реализация в основном IRS/netting-set oriented. Нет универсального trade model, CSA legal terms, collateral currencies, wrong-way calibration, IMM/SIMM/vendor benchmark. |
| FRTB | `frtb_sba`, `frtb_ima` | Реализация полезна как educational/analytics approximation; для regulatory use не хватает полного Basel bucket/risk-weight/correlation tables, NMRF, liquidity horizons, PLA, backtesting and desk eligibility workflow. |
| Market data dependent | all calibrated models | Demo/manual sources и sparse histories не дают статистической уверенности. Нужны source priority, stale/missing policy, official EOD snapshots and immutable audit. |

### Проверка по всем основным pricer families

| Asset class / family | Проверенные engines | Math validation status |
|---|---|---|
| Equity vanilla | `black_scholes`, `black76`, `bachelier`, `binomial_*`, `trinomial`, `pde_cn`, `mc_gbm`, `qmc` | Formula/test basis strong for vanilla; production sign-off absent. |
| Equity stochastic/jump | `heston_cf`, `bates`, `merton_jump`, `kou`, `variance_gamma`, `nig`, `cgmy`, `carr_madan`, `adi`, `rough_bergomi`, `local_vol_mc` | Internally coherent for research; calibration and external benchmarks missing. |
| Equity exotics | `barrier`, `asian`, `digital`, `lookback`, `variance_swap`, `discrete_div_bsm`, `lognormal_mixture`, `cev`, `displaced_diffusion`, `baw`, `bjerksund_stensland` | Some closed-form identities tested; path-dependent/MC/exercise models need benchmark grid and convention review. |
| Rates linear | `fixed_bond`, `frn`, `irs`, `fra`, `basis_swap`, `ois`, `repo`, `stir_future`, `bond_future`, `custom_bond` | DCF formulas largely reasonable under simplified conventions; FRN/callable/lifecycle limitations remain. |
| Rates nonlinear | `capfloor`, `swaption`, `bermudan_swaption`, `g2pp`, `lmm`, `bk`, `cheyette`, `swap_market_model`, `cms_swap` | Theoretical alignment good, but no production IR vol calibration/sign-off. |
| FX/FXO | `fx_forward`, `ndf`, `garman_kohlhagen`, `fx_smile`, `vanna_volga`, generic FX barrier/digital/asian via wrappers | Core formulas acceptable under explicit conventions; full FXO convention set incomplete. |
| Credit | `cds`, `cds_curve`, `cds_isda`, `risky_bond`, `gaussian_copula`, `t_copula`, `clayton_copula`, structural credit | Useful approximations; portfolio credit and CDS standard conventions need independent benchmark. |
| Commodity/inflation | `schwartz_smith`, `gibson_schwartz`, `commodity_seasonal`, `pilipovic`, `inflation_swap`, `jarrow_yildirim` | Present but calibration/data source evidence insufficient for validation confidence. |
| XVA/FRTB/Risk | `cva_exposure`, `xva_suite`, `cva_wwr`, `frtb_sba`, `frtb_ima`, `var_*`, `evt_var`, `copula_var` | Analytics implementation, not regulatory/production validation. |

### UI / governance recommendation

Все модельные допущения, которые влияют на цену, риск, Greeks, VaR/XVA/FRTB или статус валидации, должны быть явно визуализированы в программе и доступны для изменения в интерфейсе настройки конкретной модели/прайсера. Это включает как минимум: measure/numeraire, discount/forecast curves, day-count/calendar/business-day conventions, dividend/foreign-rate assumptions, vol/smile/surface source, correlation source, hazard/recovery assumptions, calibration date/dataset, MC seed/paths/time steps, PDE/tree grid, finite-difference bump sizes, VaR horizon/window/confidence/shock methodology, EVT threshold, XVA netting/CSA/collateral assumptions and FRTB bucket/risk-weight/correlation/liquidity-horizon assumptions. UI должен показывать default values, source, validation status, ограничения модели и audit trail изменения параметров; скрытые hardcoded assumptions недопустимы для production use.

### Что должно быть сделано для 100% confidence target

1. Ввести model validation pack per model: canonical examples, external reference prices, tolerance table, stress grid, edge-case grid, calibration dataset, owner/sign-off.

2. Для pricing: сравнить с QuantLib/vendor/Calypso-like benchmark по `black_scholes`, `black76`, `garman_kohlhagen`, `fixed_bond`, `irs`, `capfloor`, `swaption`, `cds_isda`, `heston_cf`, `lmm`, `g2pp`.

3. Для risk: заменить multi-day HypPL sqrt scaling на overlapping windows, исправить Christoffersen edge-case, разделить HypPL/APL, добавить actual P&L import and official P&L explanation.

4. Для Market Risk: построить explicit factor map: equity by name, FX by pair, rates by curve/tenor, vol by surface node, credit by issuer/curve, commodity by contract.

5. Для data: отключить silent demo/manual источники в production mode, сделать immutable EOD snapshots, source priority, stale/missing handling and calculation audit.

6. Для UI: вывести все модельные допущения в настройки модели/прайсера, разрешить пользователю менять их через интерфейс, показывать источник/default/status каждого допущения и логировать изменения в audit trail.

7. После исправлений перевести выбранные модели из `Approximation`/`Prototype` в `Validated` только через governance workflow.

### Вопросы для математического sign-off

1. Какие модели первыми считаем production-priority: rates vanilla, FI, FX, equity vanilla, credit, structured notes, Market Risk?

2. Какой независимый benchmark считать авторитетным: QuantLib, Bloomberg/OVME/SWPM/CDSW, Calypso export, internal spreadsheet, broker marks?

3. Какой стандарт VaR нужен: confidence, horizon, history length, overlapping/non-overlapping, absolute/relative shocks, HypPL/APL, stress window?

4. Какие market-data источники будут официальными для curves, vols, FX, credit, dividends, correlations and commodity forwards?

5. Нужен ли запрет на production use для всех `Prototype` и `Analytics Lab` models на уровне API/UI до прохождения validation?
