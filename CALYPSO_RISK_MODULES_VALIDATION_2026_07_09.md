# Проверка реализации инструкции Calypso risk/pricing

**Дата исходной проверки:** 2026-07-09<br>
**Дата актуализации:** 2026-07-13<br>
**Проверенная база:** `860308c`<br>
**Проверенный diff:** corrective packs 1–5 + adversarial hardening + bounded MR-8B2 rollout slice<br>
**Инструкция:** `/Users/dmitriykiselev/Downloads/calypso_risk_modules_models_detailed.md`<br>
**Проект:** `/Users/dmitriykiselev/Library/Mobile Documents/com~apple~CloudDocs/Python/RC_project`<br>
**Ограничение исходной проверки:** на 2026-07-09 код проекта не изменялся; был создан только этот отчет. При первой актуализации 2026-07-13 код также только проверялся. После команды начать реализацию внесены описанные ниже corrective packs 1–5, затем выполнены adversarial hardening и безопасный read-only срез MR-8B2.

## Актуализация текущего статуса от 2026-07-13

Эта секция является текущим статусом проекта и заменяет вывод актуализации от 2026-07-10 ниже. Проверены изменения этапов 3–5 (`4465ea4..860308c`), затем реализованы и повторно проверены пять corrective-пакетов Market Risk/governance/pricing/EOD, snapshot atomicity/certification hardening и bounded MR-8B2 rollout slice.

### Текущий вывод

Проект существенно расширился, а пять корректирующих пакетов и последующий hardening реализованы и провалидированы. Пакет 4 довёл исполняемую часть MR-4: активный snapshot привязан к основной и фильтрованной книге; именованные discount/projection curves реально участвуют в valuation/full reprice, а cashflow ниже или выше native tenor support отклоняется. Узловая именованная vol surface разрешается только внутри калиброванной K/T-области — silent clipping/extrapolation и thin-surface median запрещены; параметризации `flat` и `rr_bf` следуют собственному контракту без узловой K/T-границы. Spread/basket получили component Delta/Gamma/Vega, именованные exposures и component P&L attribution; неоднозначные duplicate IDs отклоняются.

Пакет 5 реализовал первый production-oriented срез MR-4B. Для каждой именованной discount/projection curve исторические сценарии теперь строятся из её собственных snapshot-bound grids по фактической `as_of`-дате и используют все native tenors плюс canonical tenors внутри полного native support: глобальная cubic-интерполяция не допускает локального усечения узлов. Маршрутизация разделена через Historical/h-day, Matrix-MC, incremental, P&L Explain и `RiskService`; неполная история, конфликт двух snapshots за дату, смена методологии или неподдержанный первый/последний cashflow отклоняются. Общий RUB KBD proxy разрешён только legacy scalar-rate позициям и больше не подменяет named curve. Именованная FORTS surface получает position-specific sticky-strike/constant-maturity total-variance move из проверенного point provenance; отсутствующий день, K/T вне support или невалидный lineage отклоняются без IV30/RVI proxy. Это ещё не полная динамика каждого strike/expiry node и не key-rate/smile attribution.

Политика переоценки стала fail-closed на уровне producer и всех Market Risk consumers: partial/error/non-finite valuation не попадает в HypPL, VaR/ES, Matrix-MC, backtest, incremental или P&L Explain. Dual-curve IRS DV01 и cap/floor vega теперь считаются на согласованных discount+projection curves. Swift очищает stale metrics до запроса и публикует overview/backtest только атомарной успешной парой.

EOD формирует отдельный `IV30:{underlying}` как ATM-forward 30-calendar-day IV: smile-интерполяция по `log(K/F)=0`, затем total-variance interpolation по сроку; exact/nearest также проходят calendar-variance guard. Option и forward даты/source/basis хранятся раздельно и проходят whitelist. Raw surface + provenance, а также publish/revoke IV30 за дату заменяются атомарно; representative с `WARN` теперь вообще не публикуется в canonical IV30. Quality gate требует 1:1 point keys и IV30 для каждого underlying. Offline operational job детерминированно переиздаёт IV30 из сохранённых snapshots и проверяет master calendar, full-window universe, contiguous shocks, stress/freshness/look-ahead, duplicate snapshots, raw↔provenance lineage и canonical equality. Локальный rebuild остаётся диагностическим контуром; production consumers дополнительно требуют актуальный per-snapshot validation report.

Production snapshot/readiness теперь защищены от torn reads: `MoexProvider`, Market Risk `factor_shifts`, quality/fingerprint и IV30 readiness/accessor читают связанный multi-table bundle в одной транзакции (`BEGIN` для SQLite; `REPEATABLE READ READ ONLY` для PostgreSQL). Контракт `2026-07-13.snapshot-binding-v3` связывает validation report с manifest, curve headers/points, FX, raw/provenance vol, bonds и same-day canonical IV30. Production принимает только текущий `OK + production_eligible` report с совпадающим fingerprint и повторно проверяет runtime quality. Любая последующая мутация данных делает certification неактуальной и блокирует consumer.

MR-8B2 частично реализован безопасным read-only срезом: `run_iv30_readiness.py check` и `schedule-status` имеют стабильный JSON-контракт и exit codes `0/2/64/70`; production gate требует `source=MOEX`, явный непустой календарь и фиксированную universe. SQLite открывается `mode=ro + query_only`, без migrations; активный WAL без существующего `-shm` отклоняется. CLI не публикует IV30 и не запускает scheduler. PostgreSQL получил DSN factory и идемпотентную additive migration, но реальный серверный round-trip ещё не выполнен.

Validation-gate повторно зелёный для `113/113` Validated-моделей и включён в CI. Проект всё ещё **не готов к production sign-off**: code routing для собственных curve/surface histories теперь есть и fail-closed, но в активной БД достаточную глубину имеет главным образом `GCURVE_RUB`; большинство остальных curves имеют лишь 5–11 observation dates, а governed surface provenance и `IV30:*` отсутствуют. Legacy GCURVE history математически читается exact path, но `1,300/1,451` headers и `13,706` points остаются orphan без manifest/`snapshot_key`, поэтому production lineage требует официального MOEX replay/backfill, а не синтетического certification. Не реализованы полная strike/expiry node dynamics, rate-index/fixing/CSA и части index/credit/commodity факторов. Реальный PostgreSQL round-trip, внешний scheduler/live accumulation, governance metadata/sign-off, Stage 3–4 production-контур и capture новых Stage 5 продуктов также остаются незавершёнными.

### Статус этапов 3–5

| Блок | Текущий статус | Проверенная оценка |
|---|---:|---|
| A1 `PricingEnvironment` | **Частично закрыто** | Контракт, AppDB, REST, env picker и применение в `/pricing/price` есть. Но `surface_map`/`measures` не используются; env не применяется к grid/payoff/ladder/scenarios, Market Risk, APL/EOD/Stress; version history отсутствует. Это рабочий FO pricing MVP, а не сквозной valuation contour. |
| A2 durable audit | **Частично закрыто** | Pricing/Portfolio/Risk/Governance используют общий persistent `AuditService`. Но Market Risk overview/MC/PCA/backtest/incremental/P&L explain не создают собственный `CalculationRecord`; import/delete APL и изменения environments также не аудируются. |
| A4 books/trade filters | **Частично закрыто** | Есть book/instrument/currency slice, REST и book filter в Market Risk/UI. Metadata пустого среза исправлены: `positions=0`, value `0`. По-прежнему хранится один `bridge_book`, нет hierarchy/trader/trade-id. |
| A3 Actual P&L / APL vs HypPL | **Частично закрыто** | Durable manual/CSV import, split/gap, APL backtest leg и UI реализованы. Official/live source, исторический состав книги, trade dates, coupons/fixings/exercise/maturity/corporate actions отсутствуют; lifecycle пока только warning. |
| A5 disclosure допущений | **Закрыто как MVP UI/API** | Каталог показывает глобальные conventions и help, EVT threshold вынесен в параметр. Полный per-model assumptions sweep, provenance и audit изменений параметров еще не закрыты. |
| A6 QuantLib benchmark-pack | **Частично закрыто** | Локально подтверждены `12` cross-benchmarks + coverage gate (`13/13` тестов): BSM, Black-76, GK, CRR, Heston, barrier, digital, lookback, Asian, bond и IRS. Нет внешних benchmark adapters для cap/floor, swaption, CDS, G2++, LMM/XVA; evidence не заполняет owner/date/references/sign-off в registry. |
| Matrix-MC / EVT UI | **Закрыто как корректный MVP** | Matrix path остаётся отдельным on-demand endpoint/card и не смешан с fitted-normal MC в overview. Он использует `eq_names`/`vol_names`/`fx_pairs`, alias для USD/RUB и explicit factor routes. EVT ξ-grid/exceedances/spread/warnings доходят до API/UI; ES берётся из `CVaR`, infinite ES отображается как неопределённый. Остаток: book/stress/horizon controls ещё не проведены в Matrix-MC endpoint. |
| Stage 5 products | **Частично закрыто** | Каталог: `50` продуктов, `100` engines. Добавлено 13 pricing workflows (FX exotics, equity linear/future/warrant, CDS index/option, ASW, deposit), но всего `16/50` продуктов capturable; ни один из новых 13 не имеет `TO_POSITION`/portfolio reprice workflow. |
| Swift UI | **Проверено** | Environments, books, Matrix-MC и Actual P&L UI/decoders собраны; `CSVExport.save` изолирован через `@MainActor`, выбранный `secid` включён в capture/incremental payload. Market Risk очищает stale state и атомарно публикует overview/backtest. Строгая Swift 6 сборка: `19 tests`, `0 failures`, warnings отсутствуют. |

### Текущая governance-статистика

- registry: `122` модели = `113 Validated / 4 Approximation / 5 Prototype`;
- executable `TEST_MAP` есть у `113/113` Validated; для последних `44` добавлены точные pytest node IDs (`90` направленных evidence-тестов), все селекторы собраны и исполнены;
- пять новых Validated Stage 5 (`asset_swap`, `dividend_swap`, `equity_forward`, `equity_future`, `term_deposit`) теперь также имеют model-specific mapping;
- `scripts/validation_program.py --run` выполняет дедуплицированный green path и при падении локализует результат по моделям; consistency + evidence gate включены в `.github/workflows/tests.yml` перед полным suite;
- у моделей не заполнены назначенный owner, validation date и external references; общий quant review остается преимущественно `Open`;
- `equity_swap`, `cds_index`, `cds_index_option`, `warrant` теперь получают `production_allowed=False`; default Pricing/Risk services блокируют их, аналитический bridge использует отдельный явный opt-in и сохраняет non-production metadata.

Статус `Validated` по-прежнему следует читать как **internally tested**, а не как independent production approval.

### Реализованные corrective packs 1–5 и adversarial hardening

| Пункт | Статус после реализации | Направленное подтверждение |
|---|---:|---|
| Age-weighted HS | **Исправлено** | Старый экстремум: VaR `10`; тот же экстремум в свежем хвосте: VaR `100`. Ошибочный reverse весов удалён. |
| Log/simple return convention | **Исправлено** | Исторический `log(1.1)` преобразуется через `expm1` и даёт ровно тот же P&L, что simple `+10%`, включая per-name/per-pair и второй `RiskService.full_reprice_var` path. |
| Multi-day full revaluation и даты | **Исправлено для Market Risk HypPL** | Факторы сначала агрегируются, затем книга переоценивается один раз; дата — конец окна. Два дня `+10%`: nonlinear call `16.6186`, тогда как прежняя ошибочная сумма 1d P&L была `14.4247`. |
| Futures risk (`F`) | **Исправлено для typed `instrument="future"`** | `F=100`, quantity `10`, multiplier `2`, shock `+10%` даёт P&L `200`, в simple и log-конвенциях. Bond/STIR futures не затронуты. |
| P&L Explain equity/FX | **Исправлено** | Relative moves переводятся в absolute по spot каждой позиции; FX использует собственный `dfx`, per-name/per-pair карты доходят до attribution. Legacy absolute `dS` сохранён. |
| Approximation production policy | **Исправлено** | Все четыре реальные Approximation имеют `production_allowed=False`; default service возвращает governed error, аналитический opt-in явный. Analytics-Lab invariant нельзя переопределить полями registry. |
| Validation gate fail-closed | **Исправлено** | Missing mapping/file теперь `False`/exit `1`; runner использует текущий Python, `RuntimeWarning` как error и запускает evidence всех 113 Validated, а не исторические 108. Green path дедуплицирован и включён в CI. |
| Empty book / unknown stress | **Исправлено** | Пустой/неизвестный book возвращает согласованные zero metadata; неизвестный stress-window отклоняется. Короткая backtest history также теперь fail-closed отдельным guard. |
| Incremental VaR universe / engine | **Исправлено** | Factor universe строится один раз по base + what-if; base/union/solo получают одинаковые dates/factors и обходят обычный cache. `secid`/FX pair сохраняются, неизвестный или невоспроизводимый engine отклоняется и в incremental, и в `/portfolio/add`. |
| Capture parity | **Исправлено для 16 существующих capturable routes** | FX forward сохраняет notional, contractual `K` и pair; legacy quantity-as-notional не умножается дважды. CDS сохраняет выбранный flat hazard. NaN/Inf и reprice errors больше не дают тихий NaN-VaR. |
| Backtest / Kupiec guards | **Исправлено** | Backtest требует минимум `60` lookback + `20` out-of-sample, проверяет даты/finite HypPL; `n_obs=0` явно non-applicable. Kupiec отклоняет дробные counts и считает likelihood в log-space без underflow. |
| Validation evidence | **Исправлено** | `113/113` mappings, последние `44` — node-level; evidence gate зелёный и включён в CI. |
| Stage 5 pricer edge cases | **Исправлено** | `equity_swap` delta приведена к `0` для реализованной spot-independent par-start формулы; `cds_index_option` валидирует finite/positive spreads, sigma, сроки, frequency, recovery и option side. |
| Swift actor isolation | **Исправлено** | `CSVExport.save` помечен `@MainActor`; strict warnings-as-errors build и `19/19` тестов зелёные. |
| Typed multi-asset spot/vol | **Исправлено для capturable spread/basket** | Capture сохраняет aligned unique `component_secids`; basket list-поля больше не имеют нулевого shock effect, spread legs и basket components получают собственные `dS_by_name`/`dvol_by_name`, Delta/Gamma/Vega exposures и P&L attribution. Missing identity остаётся совместимым global-proxy fallback, но явно попадает в warnings; duplicate/colliding IDs отклоняются. |
| Named curve dependencies | **Исправлено для current + historical routing** | Книга и book slices используют активный snapshot. `curve_id`/`proj_curve_id` разрешаются раздельно; current valuation и historical scenario получают exact curve map, scalar `r`/RUB KBD не применяются второй раз и не подменяют missing named history. Snapshot grids читаются по `as_of`; scenario map включает все native tenors и canonical tenors внутри полного native support. Неполный календарь, unsupported lower/upper cashflow, конфликт и method transition отклоняются. Dual-curve IRS DV01 согласован с joint 1bp FD. |
| Named surface dependencies | **Частично исправлено: current + position history** | Current узловая `vol_surface_id` разрешает sigma по K/T без DEMO fallback; `flat`/`rr_bf` используют свой контракт. Historical scenario для FORTS surface теперь position-specific: verified provenance → sticky-strike + constant-maturity total variance без extrapolation и IV30/RVI proxy. Остаются отдельная covariance/routing каждого strike/expiry node и node-level smile/term attribution. |
| Strict reprice policy | **Исправлено** | Producer и Historical/h-day, overview, backtest, Matrix-MC, incremental, P&L Explain и `RiskService.full_reprice_var` отвергают error/partial/invalid/non-finite результаты с scenario/date context. Неуспешные серии не кэшируются; Swift не оставляет stale/partial metrics. |
| Dual-curve Greeks / P&L Explain | **Исправлено в поддержанном контуре** | IRS DV01 и cap/floor vega используют те же discount/projection curves, что и valuation. Exposure valuation fail-closed; P&L Explain full reprice получает полный KBD tenor shock. First-order rate attribution всё ещё aggregate-DV01, поэтому curve-shape/cross effects явно остаются в residual/warning. |
| Per-underlying IV factor | **Исправлено на уровне routing/readiness** | `vol_names` строится по approved mapping и проходит через Historical/h-day/P&L Explain/Matrix-MC. Canonical `IV30:*` используется только как цельная сертифицированная v3-серия без splice с legacy `IV:*`; при отсутствии certification production consumer fail-closed. Только явно legacy scalar-vol path может остаться на диагностированном RVI/`IV:*` proxy. |
| Matrix-MC granular routing | **Исправлено** | Базовые factor indices фиксированы явно; per-name equity, per-underlying vol и non-global FX добавляются в covariance matrix. Идентичные series становятся alias, поэтому USD/RUB не создаёт сингулярную duplicate-column. |
| EVT API/UI contract | **Исправлено** | Overview переносит ξ, threshold grid, число превышений, ξ-spread и warnings. Исправлена подмена EVT ES: используется `CVaR`, а при `ξ≥1` возвращается `null`/«—». |
| IV readiness | **Исправлено для Risk source selection** | Проверяются aligned endpoints, минимум `max(60, horizon+49)` daily shocks, полное покрытие requested window/stress period и текущая v3 certification каждого snapshot. `60` levels больше не считаются `60` shocks; короткая IV не укорачивает VaR window. |
| EOD IV30 methodology / lineage | **Исправлено в коде; live history ещё не накоплена** | ATM-forward и 30D total-variance methodology, calendar guard, независимые даты/source/basis, whitelist, atomic raw+provenance replace и atomic IV30 publish/revoke реализованы. Representative `WARN` не публикуется; quality требует полного key/underlying coverage. |
| IV30 operational readiness / MR-8B2 | **Bounded read-only slice реализован; внешний rollout открыт** | Offline job идемпотентно rebuild/revoke series; production readiness требует master-calendar/full-universe coverage, contiguous shock depth, stress/freshness, отсутствия look-ahead/duplicates, полного raw↔provenance lineage, canonical equality и current v3 validation fingerprint. CLI `check`/`schedule-status` только читает и выдаёт `0/2/64/70`. Внешний scheduler, live history и реальный PostgreSQL остаются открыты. |
| Snapshot atomicity / PostgreSQL | **Исправлено контрактно; реальный сервер не проверен** | Multi-table production reads выполняются из одного DB snapshot. SQLite `mode=ro + query_only` сохраняет locking/change detection; WAL и rollback-journal regressions закрывают mixed-bundle. PostgreSQL первым statement задаёт `SET TRANSACTION ... REPEATABLE READ, READ ONLY`; unit и opt-in concurrent-writer test добавлены. Fresh/additive schema и atomic writes покрыты, но real-PG test пропущен без `RISKCALC_TEST_POSTGRES_DSN`. |
| FX initial forward-fill | **Уточнено** | Sparse fixing grid инициализируется последней доступной фиксацией до начала окна; первый scenario больше не получает ложный zero/fallback только потому, что дата старта не была fixing day. |

### Что остаётся открытым

| Severity | Пункт | Остаток |
|---|---|---|
| **High** | Historical factor map | Exact named discount/projection curve history и position-specific FORTS surface history реализованы и fail-closed. Остаются самостоятельная динамика/covariance каждого strike/expiry surface node, rate-index/fixing/CSA, index/credit/commodity mappings и расширение governed identity beyond `{UNDERLYING}_FORTS`. Legacy scalar positions продолжают использовать RUB KBD/RVI по явному контракту; named dependencies ими больше не подменяются. |
| **Medium** | Rate attribution | P&L Explain actual HypPL использует полный KBD tenor shock, но first-order rates effect остаётся aggregate DV01; curve-shape и cross effects попадают в явно описанный residual. Для полного explain нужны key-rate exposures по каждому curve role/node. |
| **Medium / operational** | IV30 live rollout | Методология, lineage, atomicity, quality gate, offline rebuild и bounded read-only CLI закрыты в коде, но live gate всё ещё `not_ready`: только 1/5 required snapshots, `IV30:MIX` имеет 0 levels/shocks, provenance отсутствует, а report от 2026-07-08 не соответствует v3 contract/fingerprint. Нужны внешний scheduler, устойчивый trading-day EOD, накопление полного календаря и новые v3 reports. PostgreSQL контракты проверены локально, но не реальным server round-trip. |
| **Medium** | Matrix-MC controls | Granular routing и EVT propagation закрыты; Matrix-MC endpoint пока считает полную книгу, rolling 1-day window и не принимает выбранные в UI book/stress/horizon controls. |
| **High / governance** | Sign-off metadata | Исполняемый gate закрыт, но owner, validation date, references, tolerance matrix и независимый review остаются незаполненными; 101 Open и 14 Partially Validated quant-review записей требуют решения. |
| **High** | Stage 3–4 production contour | PricingEnvironment, durable audit, APL/HypPL и books остаются MVP без сквозного env/versioning, официального P&L/lifecycle и полного calculation/config audit. |
| **High** | Stage 5 capture | Все 13 новых pricing workflows по-прежнему не имеют `TO_POSITION`/portfolio repricing; PR-1 исправлен, но PR-2 открыт. |
| **Low / UX** | Engine-aware capture UI | Backend корректно отклоняет неканонический engine, но `capturable` пока product-level: кнопка видна и пользователь получает controlled 400 вместо предварительно disabled state. |
| **Low / test hygiene** | All-warnings mode | Штатный CI/full suite зелёный, а validation runner трактует `RuntimeWarning` как error. Более широкий `-W error` на Python 3.14 дополнительно поднимает legacy `ResourceWarning` из незакрытых файлов/SQLite connections; это не численный дефект пакета 4, но ресурсную гигиену тестов следует закрыть. |

### Валидация 2026-07-13

```text
P0 + P1 directed regressions (-W error::RuntimeWarning): 269 passed
Final atomicity / IV30 / provider / DB cluster: 100 passed, 1 skipped in 2.57s
Validation evidence rerun: 113/113 Validated models green; registry consistency ok
Full Python suite after all hardening: 1492 passed, 1 skipped in 638.97s
The only skip: opt-in real PostgreSQL transaction/repeatability test (no RISKCALC_TEST_POSTGRES_DSN)
QuantLib 1.42.1: 12 cross-benchmarks + coverage gate, 13/13 tests passed
Swift 6 build/tests after final changes: 19 tests, 0 failures
Validation program: consistency ok; --run green; CI gate enabled
Python compileall and CI-critical Ruff rules: clean; strict whole-repo Ruff retains legacy style debt
git diff --check: clean
```

Read-only live audit активной `data/market_data.sqlite` на 2026-07-13: `13` MOEX valuation dates (`2026-06-09..2026-07-08`). Последний snapshot `moex-2026-07-08` содержит `15` curves / `111` nodes, `1,013` raw vol nodes / `19` underlyings, `3,067` bonds, `497` equities и `3` FX; по всей БД — `11,593` raw vol nodes в `11` snapshots, но `vol_point_observations=0` и `IV30:* = 0`. Legacy IV имеет `185` points / `24` factors / максимум `11` dates. `GCURVE_RUB` имеет `1,257` полноценных observation dates с nodes (`2021-06-24..2026-07-07`) и покрывает текущую 501-level risk-сетку; ещё `54` holiday-placeholder headers без nodes теперь корректно игнорируются как не-наблюдения. Большинство прочих curves имеют лишь `5–11` полноценных dates, `RUONIA-OIS-CBONDS` — одну, а `RUONIA_RUB` меняет методику `cbr_flat → ois_bootstrap` и потому fail-closed на пересекающем переход окне. Поэтому новый exact named-curve path практически применим прежде всего к GCURVE и блокирует короткие/несогласованные histories; named-surface path сейчас закономерно блокируется отсутствием provenance.

Lineage curve history также ещё не production-grade: `1,300/1,451` legacy curve headers и `13,706` points не имеют manifest/`snapshot_key`; активная bridge book состоит из четырёх scalar-позиций без `curve_id`, `proj_curve_id` или `vol_surface_id`. Математический exact path читает эту историю, но production governance требует официального MOEX replay/backfill. Прежняя read-only проверка `500 scenarios / 7 nodes` была выполнена до full-native hardening и больше не является текущим node-count evidence: активный GCURVE snapshot содержит 11 native nodes (`0.25, 0.5, 0.75, 1, 2, 3, 5, 7, 10, 15, 20Y`), а новая логика требует полный поддержанный набор. Same-date identical grids дедуплицируются; conflicts отклоняются.

Quality, пересчитанный новым кодом, — `WARN`, completeness `80%`, `production_eligible=false`: отсутствуют provenance и все `19` IV30 последнего snapshot. Сохранённый старый report `OK/100%/true` создан прежним контрактом и не является актуальным evidence. Финальный read-only CLI (`2026-07-06..10`, `as_of=2026-07-13`) вернул `exit 2 / not_ready`: 5 expected dates, 1 stored, 4 missing (`06, 07, 09, 10 июля`), `IV30:MIX` — 0 levels/shocks; snapshot 08.07 имеет ungoverned lineage и failures `validation_contract_version_mismatch` + `validation_snapshot_fingerprint_mismatch`. Blockers: `missing_snapshot_dates`, `snapshot_iv30_lineage_not_governed`, `snapshot_validation_not_current`, `factor_coverage_or_depth_insufficient`. Для legacy scalar-vol позиций RVI остаётся явно диагностированным fallback; canonical IV30 consumers fail-closed. Технические `created_at/fetch_ts` сознательно не использованы как признак рыночной свежести.

Python/QuantLib/Swift regressions и validation gate зелёные. Повторный Swift build/test после финального Python-suite прошёл `19/19`. CI-critical Ruff rules, compileall и `git diff --check` чисты; строгий Ruff по всему legacy-коду не является зелёным baseline и сохраняется как отдельный style debt.

### Актуальный приоритет

1. Продолжить MR-4B после закрытого exact curve/position-surface routing: добавить governed strike/expiry node dynamics и covariance, key-rate/smile attribution, rate-index/fixing/CSA, index/credit/commodity identities; расширять history только без proxy-подмены named dependencies.
2. Подключить bounded IV30 readiness к внешнему production scheduler, накопить полный master calendar, выпустить актуальные v3 validation reports и провести реальный PostgreSQL round-trip/repeatability test; переход legacy scalar-vol позиций с RVI разрешать только после зелёного gate.
3. Заполнить owner/date/references/tolerances, привязать QuantLib evidence к registry и провести решение по Open/Partially Validated review; executable evidence уже закрыто.
4. Довести Stage 3–4 до сквозного контура: PricingEnvironment для Risk/EOD/VaR/Stress и всех pricing analytics, CalculationRecord для risk/config/APL mutations, official P&L/lifecycle и book hierarchy.
5. Добавить portfolio capture/reprice для новых 13 products; провести book/stress/horizon controls в Matrix-MC, сделать capture control engine-aware и добавить Swift state-transition tests.
6. Закрыть legacy ResourceWarning hygiene и после следующего пакета снова повторить полный Python/QuantLib/Swift suite перед изменением production status моделей.

---

## Предыдущая актуализация от 2026-07-10 (исторический срез)

### Вывод на 2026-07-10

Правки заметно продвинули проект: подтвержденные дефекты Christoffersen и basket moment matching исправлены, появился персистентный trade capture, Stress VaR, Incremental VaR, пятиузловой rate factor, per-name/per-pair wiring, overlapping horizons, matrix-transform MC endpoint и EVT diagnostics. Целевой regression-набор этапов 1–2 проходит полностью.

При этом статус «этапы 1–2 выполнены» нельзя трактовать как полное закрытие исходных замечаний. Несколько решений являются рабочими приближениями, а независимая проверка нашла новые дефекты и ряд незавершенных интеграций. Проект стал сильнее как research/risk workstation, но до production-grade Calypso-like контура по-прежнему не хватает явного Pricing Environment, official/actual P&L, сквозного durable audit, book/trade filters, полного risk-factor mapping и независимого model-validation sign-off.

### Проверенный статус правок

| Правка / замечание | Статус после проверки | Оценка |
|---|---:|---|
| `christoffersen_test` без пробоев / короткий ряд | **Закрыто** | Guard возвращает `applicable=False`; `NaN` и прежний `RuntimeWarning` устранены, кластерный кейс тестируется. Для вырожденного ряда из одних пробоев отдельного guard пока нет, но основной подтвержденный дефект закрыт. |
| `basket_option(method="moment_matching")` | **Закрыто** | Волатильность annualized, цена считается Black-76 на basket forward. Пример `T=2` дает `15.2865` и согласуется с MC; одноименное вырождение совпадает с Black-76. |
| FX forward-fill | **Закрыто для текущего набора данных** | `has_fx=True`, ненулевых движений `386/500` вместо `284/500`; тест на правдоподобную annualized volatility проходит. |
| Backtest bias | **Закрыто как UI/API-функция** | Добавлены `conservative/aggressive/in_line` и отображение направления смещения. Regulatory traffic-light для произвольных confidence/window все еще является упрощением. |
| Persistent trade capture | **Частично закрыто** | Книга хранится в `data/app.sqlite`, позиции добавляются из Pricing/Market Data, удаляются и сбрасываются; HypPL cache инвалидируется при API-мутации. Остаются одна bridge-книга, отсутствие book hierarchy/trade filters и portfolio hash для multi-process/external mutation. |
| Stress VaR | **Закрыто как MVP** | Есть named windows `2022` и `2024h2`, API и UI. Нет настраиваемой/утверждаемой методологии stress period и отдельного governance workflow. |
| Incremental VaR | **Частично закрыто как MVP** | Реализован what-if `VaR(book + trade) - VaR(book)` с standalone/diversification результатами. Но factor universe строится по исходной книге: новое имя/FX-пара гипотетической сделки молча получают IMOEX/USD-RUB proxy; переданный `engine` также не определяет pricer сохраненной/what-if позиции. |
| Multi-day Historical/HypPL VaR | **Частично закрыто** | Вместо немого `sqrt(h)` используются overlapping sums, fallback явно маркируется. Но это сумма однодневных P&L текущего портфеля, а не одна full revaluation на агрегированном h-day factor shock; для нелинейной книги методы не эквивалентны. Также даты окон в API сейчас сдвинуты к началу окна. |
| Rates 5Y -> 5 tenors | **Частично закрыто** | Есть КБД `0.25/1/2/5/10Y`, сдвиг интерполируется по maturity позиции. Это лучше parallel 5Y, но пока один scalar rate shock на позицию, а не переоценка всех cashflows по точным curve/index/CSA nodes. |
| Per-name equity / per-pair FX | **Частично закрыто** | Historical HypPL умеет `dS_by_name` и `dfx_by_pair`. При отсутствии ряда молча используются IMOEX/USD-RUB proxies; текущая bridge-книга не содержит equity `secid`, а equity-option capture теряет `secid`. Matrix-MC и P&L Explain granular maps не используют; futures с полем `F` и baskets с `assets` вообще не входят в `_SPOT_KEYS`. |
| Matrix-transform Monte Carlo VaR | **Частично закрыто, backend** | Новый endpoint моделирует коррелированные Gaussian shocks для 8 факторов и делает full reprice. Основной overview/UI продолжает показывать старый fitted-normal MC; отдельной UI-карточки нет, per-name/per-pair/per-surface факторы не входят, convergence/parameter checks минимальны. |
| EVT diagnostics | **Частично закрыто** | В `evt_var` есть threshold grid, число exceedances, `xi` stability и warnings. `overview()` отбрасывает diagnostics/warnings, UI их не видит; declustering, автоматический threshold selection и корректная multi-day EVT methodology не реализованы. |
| Model registry `0 Validated` | **Численно закрыто, production sign-off не закрыт** | Реестр теперь содержит `108 Validated / 0 Approximation / 5 Prototype`. Это внутренняя test/identity validation: у всех `113` записей отсутствуют validation date, назначенный owner и внешние references; quant review: `92 Open`, `14 Partially Validated`, `5 Fixed`, `2 False Positive`. |
| FRN prototype | **Закрыто на уровне текущей модели** | Реализована dual-curve forward projection, модель переведена в `Validated`; production conventions/calendar/stubs по-прежнему ограничены. |
| Устаревшие комментарии Market Risk | **Частично закрыто** | FX-комментарий обновлен, но заголовок `api/marketrisk.py` все еще говорит о KBD 5Y/demo book, а `pca_rates()` — о single-factor HypPL, хотя код уже использует пять теноров. |
| `PricingEnvironment` / `PricerConfiguration` | **Не закрыто** | Явного контракта FO/Risk/EOD/VaR/Stress и versioned mappings по curves/surfaces/pricers/measures нет. |
| Durable calculation audit | **Не закрыто сквозным образом** | AppDB и `AuditService(db=...)` умеют сохранять записи, но runtime создает несвязанные in-memory services, а `GovernanceService.audit_trail()` продолжает возвращать placeholder без общего persistent audit. |
| Official/Live P&L, APL vs HypPL, lifecycle effects | **Не закрыто** | Текущий `pnl_explain` — model/factor HypPL текущей книги по последним factor moves; actual/official P&L source, fees/new trades/fixings/coupons/exercise/maturity/corporate actions отсутствуют. |

### Новые подтвержденные замечания

| Severity | Где | Что подтверждено | Влияние / требуемая правка |
|---|---|---|---|
| **High** | `risk/historical_var.py`, `hs_age_weighted` | Веса уже создаются в порядке «старое мало -> новое много», после чего `w[::-1]` переворачивает их. В контрольном примере функция дала VaR `100`, тогда как корректное recent-heavy weighting дает VaR `10`. | Age-weighted HS систематически придает больший вес старым наблюдениям. Убрать reversal и добавить направленный regression-тест, а не только проверки `VaR >= 0`/`ES >= VaR`. |
| **High / methodology** | `api/marketrisk.py`, `overview`; `risk/historical_var.py` | h-day результат строится суммой независимых 1d full-reprice P&L, каждый из которых рассчитан от одной и той же текущей базы. | Для nonlinear/full-revaluation VaR сначала агрегировать h-day factor shocks (equity/FX compounding, rates/vol absolute sums), затем один раз переоценивать книгу на каждом overlapping window. |
| **High / governance** | `scripts/validation_program.py` | Из `108` promoted IDs только `69` имеют запись в `TEST_MAP`; `39` получают `None`, не считаются ошибкой, а `--run` не запускает обещанный общий pool вместо них. | Validation gate может завершиться успешно, не выполнив model-specific test path для 39 promoted моделей. Сделать отсутствие mapping ошибкой либо реально запускать полный suite один раз и сохранять evidence. |
| **High** | `api/underlying.py`; `services/portfolio_service.py` | Реальный future сохраняется с параметром `F`, pricer читает `F`, но `_SPOT_KEYS` его не шокирует. Probe для `F=100`, quantity `10`, `dS=10%` и per-name `20%` вернул P&L `0` без ошибок. | Добавить типизированный factor mapping для futures и regression-тест capture -> HypPL; не ограничиваться добавлением `F` в общий список без проверки FX/rates futures conventions. |
| **High** | `api/marketrisk.py`, `incremental` / `hyppl` | What-if portfolio передается в repricing, но `_book_secids()`/`_book_fx_pairs()` по-прежнему читают `ctx.portfolio`; выбранный `engine` игнорируется при создании позиции. | Строить factor universe по фактически оцениваемому portfolio и сохранять product -> engine/pricer mapping в trade/PricingEnvironment. |
| **High** | `api/marketrisk.py` -> `PortfolioService.full_reprice_pnl` | Equity/FX факторы формируются как log-return, но spot шокируется через `S * (1 + shock)`. Для роста уровня на 10% переданный `ln(1.10)` дает P&L `9.531` вместо `10` на линейной позиции `S=100`; в stress tails ошибка усиливается. | Преобразовывать log-return через `exp(r)-1` либо хранить simple returns и однозначно зафиксировать factor convention. |
| **Medium** | `api/marketrisk.py`, `overview` | Для horizon `10` и `120` исходных сценариев API вернул `111` P&L-точек с датами `2025-12-29 … 2026-06-09`, тогда как даты концов окон должны быть `2026-01-15 … 2026-06-23`. `worst/best` смещены так же. | Привязать overlapping P&L к `dates[horizon-1:]`; добавить тест на первую и последнюю дату окна. |
| **Medium** | `api/marketrisk.py`, `mc_var_matrix` / `overview` | Новый matrix-MC не включен в `methods`, не использует `eq_names`/`fx_pairs`, а EVT warnings не прокидываются в payload. | Интегрировать новый расчет в основной report/UI и показывать proxy/fallback/EVT data-quality diagnostics. |
| **Medium** | `api/marketrisk.py`, IV auto-switch | После появления первых `60` IV levels код переключится с длинного RVI-ряда на короткую IV-серию, из которой получится около `59` shocks; проверка `>=60 joint dates` и старые stress windows могут перестать работать. Сейчас IV-ряды имеют только около `11` точек, поэтому дефект латентный. | Разделить readiness levels/returns, не сокращать factor history молча, иметь датированный fallback и stress-period availability check. |
| **Medium** | `api/marketrisk.py`, параметры API/backtest | Неизвестный `stress` молча превращается в rolling report с непустой stress-меткой; слишком короткий `window` может дать `n_obs=0` и деление на ноль в Kupiec. | Валидировать enum/ranges на API-границе и явно отклонять неподдерживаемые stress periods/недостаточную backtest history. |

### Повторная валидация

Команда целевого regression-прогона:

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/local/bin/python3.14 -m pytest \
  tests/test_validation_remarks_stage1.py \
  tests/test_validation_remarks_stage2.py \
  -q -W error::RuntimeWarning -p no:cacheprovider
```

Результат:

```text
20 passed in 220.44s
```

Расширенная регрессия по VaR, Market Risk API, portfolio dispatch, exotic pricing, basket note и API bridge:

```bash
PYTHONDONTWRITEBYTECODE=1 /opt/miniconda3/bin/python3 -m pytest \
  tests/test_var.py tests/test_marketrisk_api.py \
  tests/test_portfolio_service.py tests/test_portfolio_exotic_dispatch.py \
  tests/test_pricing_service_exotics.py tests/test_basket_note.py \
  tests/test_api_bridge.py \
  -q -W error::RuntimeWarning -p no:cacheprovider
```

```text
89 passed in 282.47s
```

Дополнительные проверки:

- `scripts/validation_program.py`: `Validated: 108`, `Approximation: 0`, согласованность реестра формально `ok`;
- runtime `factor_shifts(window=500)`: `500` сценариев, `has_fx=True`, `386` ненулевых FX-движений; рабочий vol factor все еще `RVI`, так как per-underlying IV history не достиг порога;
- направленный probe подтвердил reversal весов `hs_age_weighted`;
- runtime probe подтвердил неверную датировку 10-day overlapping окон;
- `git diff --check` проходит; Ruff на измененных Python-файлах показывает `14 x E702`, из них две новые ошибки стиля находятся в `api/marketrisk.py` в строках с объединенными statement для matrix-MC;
- Swift/Xcode установлен, но `swift test` в текущей sandbox-сессии не смог записать `~/.cache/clang/ModuleCache`; это ограничение окружения, а не выявленная ошибка Swift-кода. Сборка клиента остается непроверенной в этой актуализации.

Последний полный результат `1139 passed`, записанный в плане реализации, относится к прогону автора правок. В этой актуализации независимо повторены целевой набор и расширенная регрессия выше; полный suite следует повторить после исправления новых замечаний и перед release/sign-off.

### Что осталось — рекомендуемый порядок

1. Исправить `hs_age_weighted`, датировку overlapping windows, log/simple-return convention и нулевой risk shock для futures; добавить направленные end-to-end тесты.
2. Для multi-day full-revaluation агрегировать исторические factor shocks до переоценки, а не суммировать однодневные nonlinear P&L.
3. Усилить validation gate: 100% mapping promoted model -> executable evidence, owner, validation date, references, tolerance matrix и независимый sign-off. До этого UI-статус `Validated` трактовать как **internally tested**, не production-approved.
4. Довести factor map до exact curve/surface/quote/tenor/issuer/contract mapping; строить его по оцениваемой, включая what-if, книге; запретить молчаливые IMOEX/USD-RUB/KBD fallbacks либо явно показывать их как data-quality warnings.
5. Включить matrix-MC и EVT diagnostics в основной Market Risk report/UI; добавить статистические convergence/stability tests.
6. Реализовать `PricingEnvironment`, общий persistent calculation audit и book/trade filters.
7. Развить P&L Explained до APL vs HypPL с lifecycle/system/time effects.
8. После восстановления доступной Swift build-среды прогнать `swift test` и проверить новые поля backtest decoder/UI.

---

## Исходный отчет от 2026-07-09 (исторический срез)

Ниже сохранена исходная проверка для audit trail. Ее численные статусы и выводы о состоянии кода не следует использовать как текущие без секции актуализации выше.

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
