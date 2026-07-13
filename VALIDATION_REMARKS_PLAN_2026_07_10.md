# План реализации замечаний из CALYPSO_RISK_MODULES_VALIDATION_2026_07_09

**Дата исходного плана:** 2026-07-10<br>
**Дата актуализации:** 2026-07-13<br>
**Проверенная база:** `860308c`<br>
**Проверенный diff:** corrective packs 1–5 + adversarial hardening + bounded MR-8B2 rollout slice<br>
**Связанный статус:** `CALYPSO_RISK_MODULES_VALIDATION_2026_07_09.md`

Ниже первым приведён актуальный план по результатам повторной валидации. Разделы после него сохранены как история уже выполненной реализации; отметка `[x]` там означает, что изменение было внесено, но не обязательно что замечание остаётся закрытым после углублённой проверки.

## 0. Актуальный план после повторной валидации 2026-07-13

### 0.1. Статус этапов

| Этап | Текущий статус | Решение |
|---|---|---|
| 1. Точечные дефекты | ✅ Закрыт | D1–D3 и сопутствующие исправления подтверждены регрессией |
| 2. Методология Market Risk | 🟠 Пакеты 1–5 + hardening готовы | MR-4B1 закрывает exact historical routing full-native named curves и position-specific FORTS surfaces; MR-8B1/B2a добавляют deterministic rebuild, v3 certification и bounded read-only rollout CLI. Полная surface-node/index/fixing/CSA/credit/commodity карта, официальный replay, live IV30, внешний scheduler и реальный PostgreSQL остаются открыты |
| 3. Архитектура | 🟠 Частично | PricingEnvironment, durable audit и фильтры книг реализованы как MVP; сквозная интеграция и полнота аудита не закрыты |
| 4. P&L / допущения / benchmark | 🟠 MVP готов | QuantLib pack: 12 cross-benchmarks + coverage gate (`13/13` тестов); APL/HypPL пока не production-контур и требует официального источника и lifecycle |
| 5. Продукты | 🟠 Pricing-only | 50 продуктов в каталоге, 13 новых продуктов не доступны для capture/reprice в риск-книге; два подтверждённых edge case прайсеров исправлены |

Реализация подтверждена P0/P1-регрессиями `269 passed` с `RuntimeWarning` как error, финальным atomicity/IV30/provider/DB cluster `100 passed, 1 skipped` и полным Python-suite `1492 passed, 1 skipped` после всех исправлений. QuantLib — `13/13`, финальный Swift build/test — `19/19`; ранее выполненный strict Swift 6 прогон также был зелёным. Единственный skip — opt-in real PostgreSQL transaction/repeatability test без `RISKCALC_TEST_POSTGRES_DSN`. Validation program повторно зелёный для `113/113` Validated: последние `44` mapping заданы точными node IDs, evidence выполняется дедуплицированно и включён в CI.

### 0.2. P0 — корректность Market Risk

- [x] **MR-1. Age-weighted HS:** исправлено направление BRW-весов; два направленных теста различают старый и свежий экстремальный хвост.
- [x] **MR-2. Единая конвенция факторных доходностей:** historical equity/FX log returns преобразуются через `expm1` на границе repricing; scalar/granular VaR, Matrix-MC, P&L Explain и отдельный `RiskService.full_reprice_var` path имеют явную конвенцию. Legacy simple stress API сохранён.
- [x] **MR-3. Настоящий h-day full revaluation:** факторы агрегируются до переоценки, нелинейная книга reprice один раз на окно, даты привязаны к концу окна; короткая история сохраняет явно помеченный sqrt-time fallback.
- [x] **MR-4A. Исполняемая типизированная карта факторов:** книги привязаны к активному market snapshot; `curve_id`/`proj_curve_id` разрешаются раздельно, каждый узел именованной кривой шокируется, а maturity правее максимального tenor отклоняется. Узловая вол-поверхность используется только внутри калиброванной области K/T без thin median/extrapolation fallback; `flat`/`rr_bf` следуют собственному параметрическому контракту. Для spread/basket реализованы component Delta/Gamma/Vega, exposures и P&L attribution; повторяющиеся component IDs отклоняются. Strict reprice и все Market Risk consumers fail-closed на error/partial/non-finite. IRS DV01 считается совместным signed bump discount + projection curves, cap/floor vega сохраняет projection curve.
- [x] **MR-4B1. Exact history для named curve/surface dependencies:** discount и projection curve читаются из собственных snapshot grids по `as_of`; scenario map включает все native tenors и canonical tenors внутри полного native support, потому что global cubic не допускает локального усечения. Они маршрутизируются раздельно через Historical/h-day, Matrix-MC, incremental, P&L Explain и `RiskService`; KBD proxy для named curve запрещён. Первый/последний cashflow вне support, missing calendar, conflicting snapshots и method transition fail-closed. FORTS surface использует verified provenance и position-specific sticky-strike/constant-maturity move; IV30/RVI proxy для named surface запрещён. Holiday headers без nodes не считаются наблюдениями.
- [ ] **MR-4B2. Полная историческая типизированная карта:** добавить самостоятельные strike/expiry surface-node series/covariance и node-level smile/term attribution; rate-index/fixing/CSA, index, credit и commodity identities; governed mappings beyond `{UNDERLYING}_FORTS`; восстановить manifest/`snapshot_key` lineage legacy curve history официальным MOEX replay/backfill, не синтетической сертификацией. Математический exact path читает orphan GCURVE history, но production lineage не закрыт; большинство named curves имеют лишь 5–11 полноценных dates.
- [x] **MR-5. Incremental VaR:** вселенная строится один раз по base + what-if; base/with-trade/standalone переоцениваются на одинаковых dates/factors без main-book cache. `secid`/FX pair проходят через Swift → API → Position; unknown/noncanonical engine отклоняется и в incremental, и в capture. CDS/FX canonical routes проверены на pricing parity, включая legacy FX shape.
- [x] **MR-6. Matrix-MC и EVT:** Matrix-MC остаётся отдельным on-demand endpoint/card, использует `eq_names`/`vol_names`/`fx_pairs`, explicit base indices и aliases для identical series (USD/RUB не дублируется). EVT переносит effective confidence, ξ, exceedances, ξ-spread/grid и warnings; ES исправлен на `CVaR`, infinite ES отображается как неопределённый. Остаточный UX/API scope: провести book/stress/horizon controls в Matrix endpoint.
- [x] **MR-7. Валидация параметров и strict repricing:** неизвестный stress-window отклоняется; backtest требует минимум 60 in-sample + 20 out-of-sample и finite согласованные HypPL/dates; Kupiec имеет explicit non-applicable для `n_obs=0`, integrality guards и log-likelihood без underflow. Historical/HypPL, overview, backtest, Matrix-MC, incremental, P&L Explain и `RiskService` отклоняют partial/error/non-finite результаты и не используют stale cache после ошибки.
- [x] **MR-8A. Методология и lineage IV30:** source selection выполняется после определения rolling/stress calendar; короткая IV не сокращает requested window, RVI fallback и coverage diagnostics видны в API/UI. EOD рассчитывает ATM по log-moneyness и 30-day constant-maturity total variance по независимым option/forward date/source/basis, проверяет локальную календарную монотонность и атомарно публикует или отзывает полный набор `IV30:*`. Representative `WARN` не публикуется. Raw points и provenance заменяются атомарно; quality gate требует их 1:1 соответствия и IV30 для каждого underlying.
- [x] **MR-8B1. Локальный operational contour и certification:** offline job идемпотентно rebuild/revoke `IV30:*` только из stored raw+provenance и проверяет master calendar, full-window universe, contiguous shocks, stress/freshness/look-ahead, duplicates, raw↔provenance lineage, recomputed representative и canonical equality. Production consumers требуют актуальный `OK + production_eligible` report контракта `snapshot-binding-v3` с fingerprint manifest/curves/FX/vol/bonds/same-day IV30. Multi-table reads выполняются из одного SQLite/PostgreSQL DB snapshot; mutation после validation блокирует consumer.
- [x] **MR-8B2a. Bounded read-only rollout/observability:** `run_iv30_readiness.py check` и `schedule-status` имеют stable JSON schema и exit codes `0/2/64/70`; production gate требует `source=MOEX`, явный календарь и фиксированную universe. SQLite открывается `mode=ro + query_only`, не запускает migrations и сохраняет locking/change detection; active WAL без существующего `-shm` отклоняется. CLI не публикует и не запускает scheduler.
- [ ] **MR-8B2b. Внешний production rollout:** подключить внешний EOD scheduler/job invocation, накопить governed `IV30:*` до полного rolling/stress coverage, выпустить новые v3 validation reports и выполнить opt-in round-trip/repeatability на реальном PostgreSQL. Финальный live gate: `exit 2 / not_ready`, 1/5 snapshots, `IV30:MIX` = 0 levels/shocks, missing provenance и stale-contract certification. Legacy scalar-vol расчёт поэтому честно остаётся на RVI proxy.
- [x] **MR-9. Фильтр книг:** пустая или неизвестная книга возвращает нулевой портфель и согласованные metadata вместо metadata полной книги.

### 0.3. P0 — governance и validation gate

- [x] **GV-1. Production policy:** implicit fallback удалён; все четыре Approximation fail-closed в default service. Аналитический расчёт требует отдельного явного opt-in, не меняющего `production_allowed=False`; Analytics-Lab invariant нельзя переопределить registry-полями.
- [x] **GV-2. Полнота evidence:** missing mapping/file — ошибка; `113/113` Validated имеют исполняемый mapping, последние `44` — точные pytest node IDs (`90` направленных evidence-тестов). Runner использует текущий Python, `RuntimeWarning` как error, дедуплицирует green path и локализует red path; `--run` включён в CI перед полным suite.
- [ ] **GV-3. Метаданные sign-off:** заполнить `validation_date`, owner, references, tolerance matrix и итог independent review для каждой production-модели; отделить internally tested от independently approved.
- [ ] **GV-4. Количественный review:** закрыть или явно принять 101 Open и 14 Partially Validated записей; повторно сформировать количественный review теперь, когда executable gate зелёный.

### 0.4. P1 — доведение архитектуры до production-контура

- [ ] **AR-1. PricingEnvironment end-to-end:** провести `env_id` через Pricing grid/payoff/ladder/scenarios, Market Risk, APL, EOD и Stress; реально использовать `surface_map` и `measures`; добавить версионирование и историю изменений окружений.
- [ ] **AR-2. Полный durable audit:** отдельно фиксировать расчёты Market Risk overview/MC/PCA/backtest/incremental/P&L explain, импорт/удаление APL и изменения PricingEnvironment.
- [ ] **AR-3. APL/HypPL:** подключить официальный источник P&L, исторический состав книги, trade dates, купоны, fixing/exercise/maturity/corporate actions; выполнять импорт одной DB-транзакцией.
- [ ] **AR-4. Book model:** добавить иерархию книг, trader/trade-id и те же фильтры во все risk/P&L workflow.
- [ ] **AR-5. QuantLib evidence:** сохранить зелёные 12 cross-benchmarks + coverage gate (`13/13` тестов) и расширять adapters только вместе с данными/конвенциями; привязать результаты к governance evidence, owner и дате sign-off.
- [ ] **AR-6. Test-resource hygiene:** закрыть legacy незакрытые file/SQLite handles, чтобы весь Python-suite проходил не только с `RuntimeWarning` как error, но и с полным `-W error` без `ResourceWarning` на Python 3.14.

### 0.5. P1 — продуктовая линейка и UI

- [x] **PR-1. Исправить новые прайсеры:** `equity_swap.delta=0` согласована с реализованной spot-independent par-start формулой; `cds_index_option` валидирует finite/positive spread/strike/sigma, сроки, frequency, recovery и option side. Workstation minima также исключают нулевые spreads.
- [ ] **PR-2. Capture/reprice:** добавить все 13 новых продуктов этапа 5 в `TO_POSITION`/portfolio repricing и покрыть сквозными тестами Pricing → book → Market Risk. До этого не считать этап 5 закрытым.
- [ ] **PR-3. Новый функционал только после PR-1/PR-2:** FX window/flexible forward, correlation swap, quanto CDS и credit lifecycle добавлять по подтверждённой потребности и доступности факторов. Для ABS/MBS не создавать backend заново: он уже есть; требуются capture/UI и более реалистичная stochastic prepayment-модель.
- [x] **UI-1. Swift concurrency и stale state:** `CSVExport.save` помечен `@MainActor`; overview/backtest сначала получают согласованный результат, затем атомарно публикуют его, а error path очищает старые overview/backtest/MC данные и показывает явную ошибку. `swift test -Xswiftc -warnings-as-errors` — 19/19, warnings отсутствуют. Дополнительно capture payload сохраняет выбранный `secid`.
- [ ] **UI-2. Поведенческие тесты переходов состояния:** добавить Swift-тесты success → failure → recovery для overview/backtest/Matrix-MC; текущие 19 тестов проверяют главным образом контракты и декодирование.

### 0.6. Критерии закрытия актуального плана

- [x] Для каждого реализованного в corrective packs 1–5 и adversarial hardening P0/P1-дефекта есть направленная регрессия; незакрытые MR-4B2/MR-8B2b и GV-3/GV-4 остаются отдельными критериями, а не считаются закрытыми тестами.
- [x] Финальный полный Python-пул: `1492 passed, 1 skipped`; P0/P1 directed: `269 passed`; atomicity/IV30/provider/DB cluster: `100 passed, 1 skipped`; QuantLib — `13/13`, Swift — `19/19`. Skip только opt-in real PostgreSQL.
- [x] Validation gate не принимает модели без TEST_MAP/evidence; ни одна `Approximation` не разрешена для production по неявному fallback.
- [x] Fresh и existing PostgreSQL schema имеют идемпотентный snapshot/provenance upgrade contract; factor-date replacement и raw+provenance операции атомарны. SQLite WAL/rollback-journal repeatability и PostgreSQL `SET TRANSACTION ... REPEATABLE READ, READ ONLY` покрыты regressions.
- [ ] На реальном PostgreSQL подтверждены atomic writes и repeatable read-only bundle, а live `IV30:*` имеет достаточную rolling/stress глубину без proxy.
- [ ] Все продукты, заявленные как доступные пользователю, имеют согласованный pricing, capture, repricing и risk-factor coverage.
- [x] После пакетов 1–5 и hardening повторно актуализирован связанный статусный отчёт с фактическими командами, числами и остаточными рисками.

### 0.7. Подтверждение corrective package 5

```text
P0 + P1 directed regressions (-W error::RuntimeWarning): 269 passed
Final atomicity / IV30 / provider / DB cluster: 100 passed, 1 skipped in 2.57s
Validation evidence rerun: 113/113 Validated green; registry consistency ok
Full Python suite after all hardening: 1492 passed, 1 skipped in 638.97s
Only skip: opt-in real PostgreSQL transaction/repeatability (no RISKCALC_TEST_POSTGRES_DSN)
QuantLib 1.42.1: 12 cross-benchmarks + coverage gate, 13/13 tests
Swift final build/tests: 19/19 (prior strict warnings-as-errors run also green)
Python compileall / CI-critical Ruff / git diff --check: clean; whole-repo strict Ruff retains legacy style debt
```

Live evidence (`snapshot=moex-2026-07-08`): активная книга содержит 4 legacy scalar-позиции без curve/surface IDs. В БД `13` MOEX valuation dates; `GCURVE_RUB` имеет `1,257` полных dates, но большинство прочих curves — только `5–11`. `1,300/1,451` legacy curve headers и `13,706` points не имеют manifest/`snapshot_key`: exact math path их читает, production lineage требует официального replay. Исторический результат `500 scenarios / 7 nodes` получен до full-native hardening и не является текущим node-count evidence; активный GCURVE grid содержит 11 native tenors, которые теперь требуются полностью. Финальный read-only IV30 CLI вернул `exit 2 / not_ready`: 5 expected dates, 1 stored, 4 missing; `IV30:MIX` = 0 levels/shocks; 08.07 не имеет governed provenance и текущей v3 certification (`contract_version`/fingerprint mismatch). RVI остаётся только явным legacy scalar-vol fallback.

Следующий пакет: **MR-4B2 — surface-node/index/fixing/CSA/credit/commodity factors и официальный replay legacy curve lineage** плюс **MR-8B2b — внешний scheduler/live IV30/v3 reports/реальный PostgreSQL**, затем **GV-3/GV-4 metadata/sign-off** и **PR-2 capture новых 13 продуктов**. Параллельный долг: detailed key-rate/smile attribution, Swift state-transition tests, Matrix-MC book/stress/horizon controls, engine-aware `capturable`, legacy `ResourceWarning` и whole-repo Ruff style debt.

---

## Исторический план реализации 2026-07-10

## 1. Сверка: что уже закрыто (отчёт устарел в этих пунктах)

| Замечание отчёта | Статус | Чем закрыто |
|---|---|---|
| «Runtime portfolio — seeded demo book, нет trade capture» (зам. 2) | ✅ Закрыто | `2fb8533`: персистентная книга в `data/app.sqlite`, «В портфель» из Pricing (16 продуктов) и из Market Data (реальные бонды/акции/фьючерсы), удаление/сброс в UI |
| «HypPL cache key must include portfolio hash» | ✅ Закрыто by design | Любая мутация книги вызывает `marketrisk.invalidate_cache()` — в однопроцессном мосте эквивалентно хэшу. Вернуться к хэшу только при мультипроцессе |
| «Stress VaR не оформлен как workflow» (зам. 8) | ✅ Закрыто | `abd3d74`: `STRESS_WINDOWS` (2022, 2024h2), параметр `stress` в `/marketrisk`, пикер в UI |
| «Incremental VaR нет как workflow» (зам. 8) | ✅ Закрыто | `abd3d74`: `POST /marketrisk/incremental` (base/with-trade/standalone/diversification), кнопка What-if VaR |
| «No multi-tenor/PCA VaR workflow» (частично, зам. 5) | ✅/⚠️ Частично | `bd97611`: `GET /marketrisk/pca` (Level/Slope/Curvature, PCA-VaR vs parallel, KRD-вектор книги). **Остаток:** сам HypPL всё ещё шокирует ставки одним 5Y-фактором → M2 |
| «Vol factor RVI proxy; IV не копится» (зам. 6) | ✅/⚠️ Частично | `f7242b1`: шаг `iv_history` в EOD-ингесте (+бэкфилл), автопереход factor_shifts на `IV:MIX/MXI/RTS` при ≥60 точках. **Остаток:** per-underlying vega → M3 |
| «0 Validated — main production blocker» (зам. 11) | ✅/⚠️ Частично | Батчи 1–5 (`bd97611…43ac4d8`): **108 Validated / 0 Approximation / 5 Prototype**, `scripts/validation_program.py --run` как повторяемый гейт. Найдены и исправлены 2 бага (двойной rate-шок, Stulz K·df). **Остаток:** внешний benchmark-pack (QuantLib/vendor) → A6 |
| «frn — Prototype, replace» (таблица) | ✅ Закрыто | FRN переписан (dual-curve форвардная проекция), Validated |
| «Traffic light — ratio thresholds» | ✅ Приемлемо | 2×/4× ожидаемых == Basel 5/10 при 99%/250d точно; биномиальные зоны — как уточнение в M6 |
| «basket_note, short_rate Prototype» | ✅ Так и есть, осознанно | 5 Prototype с задокументированными причинами |

## 2. Подтверждённые дефекты (проверены по коду 2026-07-10)

| # | Дефект | Где | Подтверждение |
|---|---|---|---|
| **D1** | `christoffersen_test`: NaN при пустом/безпереходном ряде исключений — `pi=(T01+T11)/ΣT` без guard | `risk/var.py:366` | RuntimeWarning виден в наших же прогонах |
| **D2** | `basket_option(method="moment_matching")`: `sigma_b = sqrt(log(v/m1²))` **без /T** → тотальная σ передаётся в BSM, который снова умножает на √T; плюс спот-маппинг `S_b·e^{rT}` вместо Black-76 на `F=m1`. Для T≠1 материальное завышение (пример отчёта: 21.42 vs MC 15.30 при T=2) | `instruments/multi_asset.py` | Код подтверждает; **default = "mc"**, воркстейшен не затронут — режим достижим только прямым вызовом |
| **D3** | Устаревший docstring: «FX factor is zero» — фактор давно живой | `api/marketrisk.py:10-12` | Подтверждено |
| **D4** | `audit_trail()` — placeholder; `AuditService` in-memory, хотя таблица `audit_records` в AppDB уже есть | `services/governance_service.py:214` | Подтверждено |
| **D5** | `hs_var`/`hs_age_weighted`: √h-скейлинг исторического P&L (непараметрический метод так масштабировать нельзя); то же в `api/marketrisk.overview` | `risk/historical_var.py:36,64`; `api/marketrisk.py` | Подтверждено |

## 3. План реализации (по приоритетам)

### Этап 1 — дефекты и мелочи ✅ ВЫПОЛНЕН 2026-07-10
- [x] **D1**: guard в `christoffersen_test` — `applicable=False` при коротком ряде/без пробоев; кластер-кейс отклоняется; полный пул тестов проходит с `-W error::RuntimeWarning`.
- [x] **D2**: moment_matching по Levy исправлен (`σ_ann = sqrt(ln(m2/m1²)/T)` + Black-76 на `F=m1`): пример отчёта даёт 15.2865 (референс 15.2865, MC 15.33±0.05; было 21.42); вырождение 1 бумага == Black-76 точно.
- [x] **D3**: docstring `api/marketrisk.py` актуализирован.
- [x] **A7**: forward-fill фиксингов на торговую сетку — ненулевых FX-дней 386/500 (было 284), годовая вола 15.0% (было заниженные 10.9%); оставшиеся нули — честные «фиксинг не менялся».
- [x] **M6-lite**: поле `bias` (conservative/aggressive/in_line) в backtest + строка в UI; christoffersen вызывается всегда (self-guarding).

Тесты: `tests/test_validation_remarks_stage1.py` (8). Полный пул: 1127 passed при `-W error::RuntimeWarning`.
⚠️ Swift-сборка этапа не проверена: Xcode исчез из системы во время сессии (xcode-select указывает на CommandLineTools без SwiftUI-макросов) — изменение минимально (опциональное поле декодера + 2 UI-строки), проверить сборкой после восстановления Xcode.

### Этап 2 — методология Market Risk ⚠️ MVP РЕАЛИЗОВАН; КОРРЕКТИРУЮЩИЙ ЭТАП ОТКРЫТ
- [x] **M1**: `overlapping_horizon_pnl` (общий хелпер) — 10d VaR из 291-391 перекрывающегося окна (9.71M против 9.04M у √h — реальные хвосты толще); √h остался только как помеченный fallback (<50 окон, нота в data_quality + `horizon_method` в payload); hs_var/hs_age_weighted переведены.
- [x] **M2**: КБД 5 теноров в factor_shifts; `full_reprice_pnl(dr_curve=...)` — сдвиг интерполируется на срок КАЖДОЙ позиции (bucketed by maturity); равные сдвиги == параллельный кейс точно (тест); 2Y-шок бьёт по 2Y-свопу, а не по 5Y-бонду (тест).
- [x] **M4**: `mc_var_matrix` + GET /marketrisk/montecarlo — Cholesky от исторической ковариации 8 факторов (eq, 5×КБД, vol, fx) → joint-сценарии → полная переоценка; corr(eq, rates5y)=−0.54 из данных; нота о гауссовых хвостах в payload.
- [x] **M3 (шаги 1-2)**: per-name equity (`dS_by_name`, позиция с `params["secid"]` шокируется своим рядом, fallback IMOEX) и per-pair FX (`dfx_by_pair` по `ccy_pair`); факторные ряды подхватываются из книги автоматически. Шаг 3 (per-underlying vega) ждёт ≥60 IV-точек — wiring готов.
- [x] **M5**: EVT-диагностика — ξ по сетке порогов (0.7×/1×/1.3×), warnings при <30 превышений, ξ≥0.5/1, нестабильности ξ>0.3.

Тесты: `tests/test_validation_remarks_stage2.py` (12). Полный пул: 1139 passed при `-W error::RuntimeWarning`.
Примечание: 1d VaR демо-книги вырос 2.12M → 2.86M — короткий конец КБД в окне цикла КС волатильнее 5Y, bucketed-фактор это честно ловит. Swift не менялся (новые ключи payload аддитивны); UI-карточка для matrix-MC — после восстановления Xcode.

### Этап 3 — архитектура ⚠️ MVP РЕАЛИЗОВАН; СКВОЗНАЯ ИНТЕГРАЦИЯ НЕ ЗАКРЫТА
- [x] **A1. PricingEnvironment**: `domain/pricing_environment.py` (env_id/purpose/snapshot_id/curve_map/surface_map/pricer_overrides/default_params/measures), хранение в AppDB (`pricing_environments`), сид FO/RISK/EOD/VAR/STRESS при первом обращении; `price_ws(..., env=)` — контур задаёт дефолты движка (pricer_overrides), кривых по ролям (curve_map: discount/projection) и параметров (запрос всегда побеждает), тег `environment` в результате; REST: GET/PUT/DELETE `/environments`, `env_id` в /pricing/price. Проверено: RISK-контур подставил GCURVE_RUB (30k == прежний расчёт), кастомный контур переключил european_option на heston_cf. Важно: projection-роль в сид НЕ входит (dual-curve — только явным заданием, иначе тихо менялась семантика IRS 30k→10M). Ограничение v1 честно задокументировано: curve_map = дефолты каталога/адаптеров, не полный remapping внутренних вызовов PricingService.
- [x] **D4→A2. Durable audit**: общий `CONTEXT.audit = AuditService(db=app_db)` прошит в PricingService моста, PortfolioService книги, RiskService и GovernanceService; `audit_trail()` читает из `audit_records` (переживает перезапуск, статус Recorded), in-memory — fallback, placeholder — только для голого сервиса; лимит limit=200 на выдачу.
- [x] **A4. Books/trade filters**: `ctx.filtered_portfolio(book, instrument, currency)` + `ctx.books()`; `/portfolio?book=&instrument=&currency=` (+ books и filter в payload), `GET /portfolio/books`, `/marketrisk?book=` — VaR по срезу (без кэша); тождество «одна книга ⇒ срез == целое» тестом.

Тесты: `tests/test_validation_remarks_stage3.py` (9). Полный пул: 1148 passed при `-W error::RuntimeWarning`. Swift не менялся (ключи аддитивны); UI контуров/фильтров — после восстановления Xcode.

### Этап 4 — P&L, UI-допущения, внешний бенчмарк ⚠️ MVP РЕАЛИЗОВАН; PRODUCTION-КОНТУР НЕ ЗАКРЫТ
- [x] **A3. P&L Explained → actual vs hypothetical**: таблица `actual_pnl` в AppDB (upsert по дате) + REST `GET/POST /pnl/actual` (одна запись, rows или CSV-текст «date,pnl»; `;` и заголовок допускаются), `DELETE /pnl/actual/{dt}`; `pnl_explain` выдаёт блок `actual_vs_hypothetical` (APL, HypPL, gap + честная сноска: разрыв = новые сделки/комиссии/интрадей/lifecycle — их в HypPL нет по построению); `backtest` — Basel-схема «один VaR против обеих серий»: actual подмешивается в rows по датам (`actual_pnl`/`actual_breach`) + сводка `actual_backtest`. Lifecycle v1 честно ограничен: позиции книги не «стареют» (T статично), календарные купоны/экспирации не детектируемы — предупреждаем о позициях с T≤5 т.д.; полный lifecycle требует трейд-дат в позициях (отложено).
- [x] **A5. Sweep допущений**: help у T — «в годах, ACT/365»; ноты конвенций у barrier (непрерывный мониторинг, без Броди–Глассермана), asian (равномерные фиксинги, фиксированный seed), digital (разрывный payoff), lookback (непрерывный экстремум); блок `conventions` в payload каталога (7 глобальных конвенций: ACT/365, непрерывное начисление, MC seed, FD-бампы, снапшот последнего торгового дня, источники σ); EVT-порог GPD-фита — параметр `evt_threshold` в `/marketrisk` (был скрыт 0.10; кламп 0.02–0.5, в methods отдаётся `threshold_pct`).
- [x] **A6. Внешний benchmark-pack**: QuantLib 1.42.1 УСТАНОВЛЕН под python3.14 — пак живой, не заглушка. `validation/quantlib_benchmarks.py`: 12 кросс-бенчмарков (BSM call/put, Black76, Garman–Kohlhagen, American CRR-500 vs CRR-500, Heston CF vs AnalyticHestonEngine, барьер down-out, digital cash, lookback floating, дискретная геометрическая азиатка, fixed bond, IRS payer против VanillaSwap с явными 365-дневными расписаниями). 10/12 сходятся до ~1e-15 (машинная точность), Heston 1.2e-6, CRR-деревья 2.3e-6 (детали дискретизации, допуск 1e-5 с комментарием). Конвенции выровнены: ACT/365 + Continuous + явные даты (без високосных 366/365). Запуск: `python3.14 -m validation.quantlib_benchmarks` (таблица evidence); в CI — `tests/test_quantlib_benchmarks.py` через importorskip (без пакета пропускается). Из плана не вошли capfloor/swaption/cds/g2pp/lmm-обвязки: датная машинерия QL для них не сводится к нашим year-fraction конвенциям без месива адаптеров — покрыты внутренними тождествами batch-1..5; при появлении рыночных IRVOL-данных вернуться.

Тесты: `tests/test_validation_remarks_stage4.py` (7) + `tests/test_quantlib_benchmarks.py` (13).

Adversarial-ревью диффа (multi-agent, 3 линзы + верификация) — исправлено до коммита: (1) CSV-импорт коверкал ru-числа («2026-07-09;-1234,56» въезжал как −1234.0 без ошибки) — парсер локалей `_actual_pnl_number` (ru/en тысячи/десятичные), `;`-строки не сводятся к `,`; (2) импорт стал атомарным — валидация всех строк ДО записи (раньше 422 на k-й строке оставлял k−1 записей); (3) нечисловой pnl в `rows` давал 500 вместо 422; (4) даты через `date.fromisoformat` (2026-02-31 отвергается, регэксп пропускал); (5) `evt_threshold=0.02` тихо ронял EVT из methods (KeyError глотался) — причина пропуска теперь в `data_quality`; (6) кап 1000 строк `list_actual_pnl` в бэктесте → явные 100k; (7) нота actual_backtest различает «не импортирован» и «нет пересечения дат»; методологические честности: VaR текущей статичной книги vs исторический APL (каведж в ноте), Basel APL должен быть очищен от комиссий, theta сидит в разрыве APL−HypPL (HypPL без старения), «купоны непрерывные» → простые периодические выплаты.

### Этап 5 — расширение продуктовой линейки ✅ ЧАСТИЧНО 2026-07-12
Взят верхний приоритет таблицы «отсутствуют как workflow» (FXO → equity linear → CDS index/asset swap). Добавлено 6 продуктов (43 в каталоге):
- [x] **FXO**: `fx_barrier` (Garman-Kohlhagen carry q=r_f, непрерывный мониторинг, премия в domestic) — отдельный продукт поверх существующего движка. FX-конвенции (delta spot/fwd/premium-adj, премия dom/fgn/%) уже отдаёт `fx_option`.
- [x] **Equity linear** (`instruments/equity_linear.py`): `equity_forward` (точный cost-of-carry, Validated), `equity_swap` (total-return vs финансирование, непрерывный ресет, Approximation), `dividend_swap` (PV дивидендов S(1−e^{−qT}), Validated).
- [x] **Credit** (в `instruments/credit.py`): `asset_swap` (par-par ASW spread = (V*−P)/annuity, Validated), `cds_index` (гомогенный пул, плоский hazard из индекс-спреда ISDA-стиль, Approximation).
- Governance: реестр 111 Validated / 2 Approximation (честные упрощения) / 5 Prototype. Валидационные тождества: `tests/test_stage5_products.py` (11). Swift подхватывает автоматически (схемо-ориентированный каталог), 19 контракт-тестов зелёные.
- **Осталось на будущее (по составу книги)**: FX-версии digital/asian/lookback/window forward, equity future/warrant/correlation swap, CDS index option/quanto/asset swap lifecycle, loans/MM, ABS/MBS. Trade-capture новых продуктов в риск-книгу — когда появятся такие позиции (нужен reprice-путь в domain/portfolio).

### Этап 5-остаток — расширение продуктовой линейки ✅ ЧАСТИЧНО-2 2026-07-12
Добавлено ещё 7 продуктов (каталог 43→50):
- [x] **FX-экзотика** (`instruments/fx.py`, паттерн fx_barrier, q=r_f): `fx_digital`, `fx_asian`, `fx_lookback` — тонкие обёртки поверх доменных digital/asian/lookback движков (реюз model_id — уже Validated).
- [x] **Equity** (`instruments/equity_linear.py`): `equity_future` (фьючерсная конвенция: F=S·e^{(r−q)T}, MtM без дисконта, futures delta > forward, Validated), `warrant` (dilution-adjusted W=(N/(N+M))·C_BSM, Approximation).
- [x] **Credit** (`instruments/credit.py`): `cds_index_option` (Black на форвардном индекс-спреде с RPV01-нумерером, payer/receiver, Approximation).
- [x] **Money market** (`instruments/money_market.py` NEW): `term_deposit` (депозит/заём МБК, простое ACT/365 или непрерывное начисление, Validated).
- Реестр 113 Validated / 4 Approximation / 5 Prototype; taxonomy + `tests/test_stage5_products.py` (22). Swift автоматом (50 продуктов, 19 контракт-тестов). Adversarial-ревью пройден.
- **Осталось (глубокий хвост, нужна инфра)**: FX window/flexible forward, correlation swap (нужна correlation-поверхность), quanto CDS (нужна FX-vol корреляция), CDS asset-swap lifecycle, ABS/MBS (нужна prepayment-модель PSA/CPR). Trade-capture новых продуктов в риск-книгу — когда появятся позиции (reprice-путь в domain/portfolio).

## 4. Что из отчёта НЕ беру и почему

- **«Нельзя дать 100% confidence ни одной модели»** — принято как философия: закрывается A6 (внешний бенчмарк) + существующей программой; «100%» недостижим по определению model risk.
- **Вопросы (§Вопросы, §вопросы для sign-off)** — по указанию не разбираются (частично уже отвечены ранее: FX=фиксинги ЦБ, recovery=baseline-корзины, валидация=запущена).
- **«Bloomberg/Reuters заглушки»** — платных источников нет (ответ юзера ранее); остаётся как есть с честными пометками.
- **FRTB для regulatory use** — вне скоупа (education/analytics-уровень зафиксирован в notes реестра).

## 5. Порядок и зависимости

```
Этап 1 (D1,D2,D3,A7,M6-lite)  — независимы, одна сессия
Этап 2 (M1 → M2 → M4 → M3.1)  — M2 требует расширения full_reprice_pnl; M3 после M2
Этап 3 (A1 → A2, A4)          — A1 первым, на него ложатся Risk/EOD контуры
Этап 4 (A3, A5, A6) ✅         — выполнен 2026-07-12; actual P&L — ручной ввод/CSV через /pnl/actual
Этап 5                         — по составу книги
```

Этот порядок — история реализации MVP. Актуальная последовательность работ: **P0 Market Risk correctness → P0 governance/gate → P1 end-to-end architecture → P1 product capture → дальнейшее расширение каталога**.
