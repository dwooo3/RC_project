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

### Этап 1 — дефекты и мелочи (быстро, без вопросов)
- [ ] **D1**: guard в `christoffersen_test` — при `len(exceptions)<2` или нулевых переходах вернуть `{applicable: False, reason: "insufficient_transitions"}`; обновить потребителей (backtest, UI-подпись).
- [ ] **D2**: починить moment_matching по Levy: `σ_ann = sqrt(ln(m2/m1²)/T)`, цена = дисконтированный Black-76 на `F=m1`; regression-тест против MC (T=2 из отчёта) и `T=1`-инвариантность со старым поведением не требуется — фикс честный.
- [ ] **D3**: обновить docstring `api/marketrisk.py` (FX-фактор живой, автопереход vega).
- [ ] **A7**: конвенция FX-фиксингов — сдвиг даты (ЦБ публикует «на завтра») + carry-forward пропусков вместо нулевых движений; цель ≥95% ненулевых дней в окне.
- [ ] **M6-lite**: в backtest-ответ добавить направление отклонения (консервативна/агрессивна) — сейчас Kupiec reject без знака.

### Этап 2 — методология Market Risk (ядро валидных замечаний)
- [ ] **M1. Overlapping h-day HypPL**: для `horizon>1` строить перекрывающиеся h-дневные суммы HypPL (логика уже есть в `risk/var._horizon_returns` — переиспользовать); √h оставить только как помеченный fallback при <50 окон. Затронет `api/marketrisk.overview` и `hs_var`/`hs_age_weighted`.
- [ ] **M2. Multi-tenor rate factor в HypPL**: совместные дневные сдвиги КБД по 5 тенорам (история есть) → `full_reprice_pnl` принимает вектор `dr_by_tenor`; бонды переоцениваются через KRD-корзины/сдвинутую кривую, свопы — по ближайшему тенору. Сверка: сумма по тенорам ≈ старый параллельный кейс при равных сдвигах.
- [ ] **M4. Correlated MC VaR (Calypso Matrix Transform)**: ковариация факторного вектора (equity, 5×rates, vol, fx) → Cholesky → симуляция joint-сценариев → full reprise → VaR/ES; сверка с historical на том же окне. Новый метод в `/marketrisk` methods.
- [ ] **M3. Factor map позиция→фактор (поэтапно)**: шаг 1 — per-name equity (история 30 имён есть; позиция с `secid` шокируется своим рядом, прочие — IMOEX); шаг 2 — per-pair FX (EUR/CNY истории загружены); шаг 3 — per-underlying vega (ждёт ≥60 точек IV, wiring готов). Требует `params["secid"]` в позициях — уже пишется при capture из Market Data.
- [ ] **M5. EVT-диагностика**: минимум excesses, стабильность ξ по сетке порогов, предупреждение в payload.

### Этап 3 — архитектура (главное структурное замечание отчёта)
- [ ] **A1. PricingEnvironment**: явный контракт `{name, purpose(FO/Risk/EOD/VaR/Stress), snapshot_id, curve_map(index/ccy→curve_id), surface_map, pricer_overrides, default_params, measures}`; хранение в AppDB; `PricingService`/workstation/marketrisk принимают `env_id`; дефолтные окружения FO (live snapshot) и Risk (=FO пока). Это скелет — без него замечания про «разные контуры оценки» не закрыть.
- [ ] **D4→A2. Durable audit**: писать `CalculationRecord` в `AppDB.audit_records` (append из AuditService), `GovernanceService.audit_trail()` читает оттуда; ретеншн/лимит; смоук-тест перезапуска.
- [ ] **A4. Books/trade filters**: поле `book` уже есть у позиций — фильтр по book/инструменту/валюте в `/portfolio` и Market Risk (VaR по срезу книги). После A1.

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
