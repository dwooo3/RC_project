# План реализации замечаний из CALYPSO_RISK_MODULES_VALIDATION_2026_07_09

**Дата:** 2026-07-10. Код не менялся — только анализ отчёта против текущего состояния (HEAD `43ac4d8`) и план.
Отчёт датирован 2026-07-09 и частично описывает состояние ДО коммитов того же и следующего дня — ниже сверка.

---

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

### Этап 2 — методология Market Risk ✅ ВЫПОЛНЕН 2026-07-10
- [x] **M1**: `overlapping_horizon_pnl` (общий хелпер) — 10d VaR из 291-391 перекрывающегося окна (9.71M против 9.04M у √h — реальные хвосты толще); √h остался только как помеченный fallback (<50 окон, нота в data_quality + `horizon_method` в payload); hs_var/hs_age_weighted переведены.
- [x] **M2**: КБД 5 теноров в factor_shifts; `full_reprice_pnl(dr_curve=...)` — сдвиг интерполируется на срок КАЖДОЙ позиции (bucketed by maturity); равные сдвиги == параллельный кейс точно (тест); 2Y-шок бьёт по 2Y-свопу, а не по 5Y-бонду (тест).
- [x] **M4**: `mc_var_matrix` + GET /marketrisk/montecarlo — Cholesky от исторической ковариации 8 факторов (eq, 5×КБД, vol, fx) → joint-сценарии → полная переоценка; corr(eq, rates5y)=−0.54 из данных; нота о гауссовых хвостах в payload.
- [x] **M3 (шаги 1-2)**: per-name equity (`dS_by_name`, позиция с `params["secid"]` шокируется своим рядом, fallback IMOEX) и per-pair FX (`dfx_by_pair` по `ccy_pair`); факторные ряды подхватываются из книги автоматически. Шаг 3 (per-underlying vega) ждёт ≥60 IV-точек — wiring готов.
- [x] **M5**: EVT-диагностика — ξ по сетке порогов (0.7×/1×/1.3×), warnings при <30 превышений, ξ≥0.5/1, нестабильности ξ>0.3.

Тесты: `tests/test_validation_remarks_stage2.py` (12). Полный пул: 1139 passed при `-W error::RuntimeWarning`.
Примечание: 1d VaR демо-книги вырос 2.12M → 2.86M — короткий конец КБД в окне цикла КС волатильнее 5Y, bucketed-фактор это честно ловит. Swift не менялся (новые ключи payload аддитивны); UI-карточка для matrix-MC — после восстановления Xcode.

### Этап 3 — архитектура ✅ ВЫПОЛНЕН 2026-07-10
- [x] **A1. PricingEnvironment**: `domain/pricing_environment.py` (env_id/purpose/snapshot_id/curve_map/surface_map/pricer_overrides/default_params/measures), хранение в AppDB (`pricing_environments`), сид FO/RISK/EOD/VAR/STRESS при первом обращении; `price_ws(..., env=)` — контур задаёт дефолты движка (pricer_overrides), кривых по ролям (curve_map: discount/projection) и параметров (запрос всегда побеждает), тег `environment` в результате; REST: GET/PUT/DELETE `/environments`, `env_id` в /pricing/price. Проверено: RISK-контур подставил GCURVE_RUB (30k == прежний расчёт), кастомный контур переключил european_option на heston_cf. Важно: projection-роль в сид НЕ входит (dual-curve — только явным заданием, иначе тихо менялась семантика IRS 30k→10M). Ограничение v1 честно задокументировано: curve_map = дефолты каталога/адаптеров, не полный remapping внутренних вызовов PricingService.
- [x] **D4→A2. Durable audit**: общий `CONTEXT.audit = AuditService(db=app_db)` прошит в PricingService моста, PortfolioService книги, RiskService и GovernanceService; `audit_trail()` читает из `audit_records` (переживает перезапуск, статус Recorded), in-memory — fallback, placeholder — только для голого сервиса; лимит limit=200 на выдачу.
- [x] **A4. Books/trade filters**: `ctx.filtered_portfolio(book, instrument, currency)` + `ctx.books()`; `/portfolio?book=&instrument=&currency=` (+ books и filter в payload), `GET /portfolio/books`, `/marketrisk?book=` — VaR по срезу (без кэша); тождество «одна книга ⇒ срез == целое» тестом.

Тесты: `tests/test_validation_remarks_stage3.py` (9). Полный пул: 1148 passed при `-W error::RuntimeWarning`. Swift не менялся (ключи аддитивны); UI контуров/фильтров — после восстановления Xcode.

### Этап 4 — P&L, UI-допущения, внешний бенчмарк
- [ ] **A3. P&L Explained → actual vs hypothetical**: импорт actual P&L (ручной ввод/CSV за дату), split APL/HypPL в отчёте; lifecycle-эффекты первого порядка из книги (купоны/фиксинги/экспирации позиций между датами) как «system/time effects»; residual разделить на unexplained vs lifecycle.
- [ ] **A5. UI-sweep допущений**: вынести скрытые допущения в спеки (day count опционных T, bump sizes FD-грик, seed везде, EVT-порог, признак источника σ/кривой); у каждого — default/source/help. Аудит по чек-листу из отчёта (§UI/governance).
- [ ] **A6. Внешний benchmark-pack**: отдельный опциональный слой `validation/quantlib_benchmarks.py` (не в CI по умолчанию — зависимость QuantLib): bsm, black76, GK, fixed_bond, irs, capfloor, swaption, cds_isda, heston_cf, g2pp, lmm; tolerance-таблица + отчёт evidence. Это поднимает «Validated» с внутренних тождеств до внешней сверки.

### Этап 5 — расширение продуктовой линейки (по составу реальной книги)
Из таблицы «отсутствуют как workflow» — брать по мере появления таких позиций в книге, в порядке: FXO-конвенции (delta/premium/settlement + FX-версии barrier/digital/asian) → equity forward/swap/dividend swap → CDS index/asset swap → loans/MM lifecycle → ABS/MBS workflow UI. Сейчас книга bonds/IRS/FX — приоритет низкий.

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
Этап 4 (A3, A5, A6)           — A3 нуждается в источнике actual P&L (ручной ввод ок)
Этап 5                         — по составу книги
```
