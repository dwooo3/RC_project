# Production Candidate — Gap Analysis

**Дата:** 2026-06-04
**Базовый коммит:** `51e5bac`
**Метод:** сверка фактического кода с целевой архитектурой [PRODUCT_ARCHITECTURE.md](PRODUCT_ARCHITECTURE.md)
(§7–22 слои/ownership, §32 production readiness, §43 roadmap).
**Шкала:** 0–10. Target = 10 = полное соответствие целевой архитектуре.
**Тесты на момент анализа:** 206 passed.

> Оценки обоснованы конкретными артефактами в коде. Effort — T-shirt (S ≈ ≤1 нед,
> M ≈ 1–3 нед, L ≈ 3–6 нед, XL ≈ >6 нед) на одного разработчика.

---

## 0. Сводная таблица

| # | Область | Current | Target | Gap | Effort |
|---|---|:---:|:---:|:---:|:---:|
| 1 | Architecture | 7 | 10 | 3 | M |
| 2 | Market Data | 5 | 10 | 5 | L |
| 3 | Pricing | 6 | 10 | 4 | L |
| 4 | Portfolio | 7 | 10 | 3 | M |
| 5 | Risk | 6 | 10 | 4 | M |
| 6 | Governance | 8 | 10 | 2 | S–M |
| 7 | Analytics | 7 | 10 | 3 | S–M |
| 8 | Auditability | 6 | 10 | 4 | M |
| 9 | Reporting | 5 | 10 | 5 | M |
| 10 | UX | 7 | 10 | 3 | M |
| | **Среднее** | **6.4** | **10** | **3.6** | |

**Дистанция до целевой архитектуры: ≈ 64%.**

---

## 1. Architecture — 7 → 10

**Сейчас:** логические слои `domain/` + `services/` + `ui/`; зависимости UI → service → engine
в основном соблюдены; единый `YieldCurve`; service boundaries покрыты тестами.

**Пробелы / blockers:**
- Физические целевые пакеты `market/`, `pricing/`, `portfolio/`, `governance/`, `analytics/`
  (§19) не созданы — слои реализованы логически (осознанный компромисс, §7.1).
- Нет слоя персистентности (всё in-memory) — архитектурно нужен `repositories/`.
- `historical_var.py` остаётся отдельным модулем (консолидирован только на сервисном уровне).

**Effort:** M (физический переезд опционален; persistence-граница — основная работа).

## 2. Market Data — 5 → 10

**Сейчас:** `MarketDataService` владеет снапшотами; `MarketDataStore` (in-memory) + `snapshot_lineage`;
доменные `MarketDataSnapshot`/`MarketDataSource`; 4 UI-эксплорера (Curve/FX/Vol/Credit) с source/quality/validation/lineage.

**Пробелы / blockers:**
- **Провайдеры — заглушки.** `MoexProvider`/`BloombergProvider`/`ReutersProvider` бросают
  `NotImplementedError`. Все данные — `DEMO`/`MANUAL`. Реальной MOEX ISS интеграции нет.
- Нет персистентности снапшотов (lineage живёт в памяти).
- Vol surface / credit curve — преимущественно демо-структуры, без калибровки к рынку.

**Effort:** L (реальный провайдер + persistence + калибровка поверхностей).

## 3. Pricing — 6 → 10

**Сейчас:** `PricingService` (vanilla option, bond, IRS, FX forward, FX option) → `PricingResult`
с governance-метаданными, market snapshot, warnings, audit id, inputs hash. Ядро (BSM Greeks,
bond, caplet) методологически выправлено.

**Пробелы / blockers:**
- **IRS — single-curve** (нет dual-curve OIS-дисконтирования); FRN — прототип (нет reset/projection).
- Экзотика — research-only (barrier/asian/structured за governance-баннером, не production).
- Конвенции FI (стабы, календари, ex-coupon) частично; см. [FIXED_INCOME_AUDIT.md](FIXED_INCOME_AUDIT.md).

**Effort:** L (dual-curve IRS + FRN + конвенции — методологически ёмко).

## 4. Portfolio — 7 → 10

**Сейчас:** `PortfolioService` — центральный объект: `RiskFactorExposure` (без смешения Greeks),
scenario P&L, PnL explain, position-level статусы, audit records, переработанный workstation.

**Пробелы / blockers:**
- Нет персистентности портфелей/позиций (in-memory).
- Книжная иерархия (Portfolio→Book→Desk→Strategy) частична.
- Жизненный цикл позиции (trade vs position, settlement) упрощён.

**Effort:** M.

## 5. Risk — 6 → 10

**Сейчас:** единый `RiskService.var(method=…)` (historical/parametric/MC/EVT), `expected_shortfall`,
`stress_option`/`reverse_stress`, portfolio scenario; ES≥VaR; многодневные окна вместо sqrt-scaling.

**Пробелы / blockers:**
- **Backtesting не выведен как сервис/воркфлоу** (Kupiec/Christoffersen есть в движке `risk/var.py`,
  но без service-обёртки и UI).
- Нет Limit Monitoring и Capital (§14.2, §14.7).
- Стресс — пока на уровне инструмента/сценария; нет регуляторных/reverse-наборов как данных.

**Effort:** M.

## 6. Governance — 8 → 10

**Сейчас:** реестр, `production_allowed`, `quant_review_status` (Fixed / False Positive /
Partially Validated / Open), warnings, `audit_trail`, Governance Workspace со счётчиками статусов.
Сильнейшая область.

**Пробелы / blockers:**
- Нет approval-workflow (approve/downgrade/disable) и его персистентности.
- `owner`/`validation_date`/`references` частично дефолтные, не заполнены по моделям.

**Effort:** S–M.

## 7. Analytics — 7 → 10

**Сейчас:** Analytics Lab workspace на `GovernanceService`, чёткая граница research vs production
(research-модели не production_allowed; bypass только через `allow_analytics_lab=True`).

**Пробелы / blockers:**
- Нет диагностик сходимости/калибровки и бенчмаркинга в UI (§16.3).
- Промоушн research→production не формализован.

**Effort:** S–M.

## 8. Auditability — 6 → 10

**Сейчас:** `AuditRecord`/`CalculationRecord`, детерминированный `inputs_hash`, интеграция в
Pricing/Risk/Portfolio; результаты несут `calculation_id`, `snapshot_id`, `model_id`,
`model_version`, `inputs_hash`.

**Пробелы / blockers:**
- **Только in-memory** (`AuditService._records: list`). Между сессиями записи не сохраняются.
- Нет воспроизведения «из записи» (replay сохранённого request → пересчёт) — метаданные есть,
  исполняемого реплея нет (§27.2).

**Effort:** M (зависит от персистентности).

## 9. Reporting — 5 → 10

**Сейчас:** `ReportingService` — 5 отчётов (portfolio/risk/var/scenario/governance) как
renderer-neutral PDF-ready структуры (`as_dict()`); интеграция с Portfolio/Risk/Governance.

**Пробелы / blockers:**
- **Нет рендерера.** `final_pdf_styling: pending`; нет reportlab/weasyprint, нет HTML/PDF-вывода,
  нет экспорт-пайплайна и шаблонов.
- Нет хранения/версионирования отчётов.

**Effort:** M.

## 10. UX — 7 → 10

**Сейчас:** workstation-shell (Bloomberg/Calypso pass), эксплореры рынка, секционные workspaces
(Pricing/Risk/Portfolio/Governance/Analytics), data-source/status чипы, KPI-полосы.

**Пробелы / blockers:**
- Состояния «реальных данных» отсутствуют (только демо); нет live-индикаторов.
- Нет UI smoke-тестов полного цикла (старт → каждый workspace → toggle темы).
- Полировка плотности/типографики, доступность.

**Effort:** M.

---

## 11. Дистанция до вех

### 11.1 Professional Workstation — ✅ ≈ 90% (достигнута на demo-уровне)

Критерии §32 «professional-workstation-ready»:

| Критерий | Статус |
|---|---|
| market data snapshots | ✅ есть (демо) |
| pricing services | ✅ |
| portfolio service | ✅ |
| VaR / stress services | ✅ |
| governance screen | ✅ |
| audit trail | ⚠️ есть, но in-memory |

**Остаток до полной отметки:** персистентность audit trail, рендеринг отчётов, UI smoke-тесты,
полировка. **Effort: ≈ M (3–5 нед).**

### 11.2 Production Candidate — ⛔ ≈ 55–60% (значимо не достигнута)

Критерии §32 «production-candidate»:

| Критерий | Статус |
|---|---|
| fixed income conventions real | ⛔ частично |
| IRS dual-curve | ⛔ single-curve |
| FRN reset/projection | ⛔ прототип |
| market data source & valuation date | ✅ (но данные демо) |
| models have validation status & tests | ✅ |
| calculation results reproducible | ⚠️ метаданные есть, нет персистентности/replay |

**Критический путь (blockers, по приоритету):**
1. **Persistence layer** (SQLite→Postgres): снапшоты, позиции/портфели, результаты, audit. → разблокирует воспроизводимость и пункт 8. **L.**
2. **Real market data** (MOEX ISS провайдер вместо заглушек). **L.**
3. **FI methodology**: dual-curve IRS, FRN reset/projection, конвенции. **L.**
4. **Reporting renderer** (PDF/HTML + шаблоны). **M.**
5. **Risk extensions**: backtesting-сервис, limit monitoring, capital. **M.**
6. **Governance approval workflow** + персистентность одобрений. **S–M.**

**Суммарная оценка до Production Candidate: ≈ 4–6 месяцев** одного разработчика
(параллелизуемо: persistence + market data + FI — независимые треки).

---

## 12. Резюме

```text
Demo workstation        : достигнут
Professional Workstation : ~90% (остаток ~3–5 нед: persistence audit, reporting render, smoke-tests)
Production Candidate      : ~55–60% (критпуть: persistence, real data, FI dual-curve/FRN, reporting, risk ext.)
Целевая архитектура      : ~64%
```

RiskCalc — зрелый профессиональный workstation демо-уровня с сильным governance/audit-каркасом.
Основной разрыв до production-кандидата — не UI и не базовые модели (они выправлены и покрыты
тестами), а **инфраструктура достоверности**: персистентность + реальные рыночные данные +
производственная методология FI + рендеринг отчётов.
