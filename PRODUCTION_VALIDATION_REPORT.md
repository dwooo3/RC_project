# Production Validation Report

**Дата:** 2026-06-04
**Коммит:** `4eb57ce` (main)
**Тип:** полная регрессионная валидация
**Результат:** ✅ **188 passed / 0 failed**

---

## 1. Окружение

| Компонент | Версия |
|---|---|
| Python | 3.14.0 |
| numpy | 2.4.4 |
| scipy | 1.17.1 |
| PySide6 | 6.11.1 (offscreen) |
| pytest | прогон под `QT_QPA_PLATFORM=offscreen` |

Зависимости зафиксированы в [requirements.txt](requirements.txt). UI-тесты выполнены headless
с установленным PySide6 (в предыдущих сессиях они не собирались из-за его отсутствия — теперь
включены в прогон).

---

## 2. Сводный результат

```text
pytest -q  (QT_QPA_PLATFORM=offscreen)
188 passed in 9.57s
0 failed · 0 errors · 0 skipped
```

| Категория | Тестов | Результат |
|---|---:|---|
| Pricing | 97 | ✅ pass |
| Risk | 39 | ✅ pass |
| Governance | 20 | ✅ pass |
| Workspace / UI | 15 | ✅ pass |
| Architecture / Foundation | 17 | ✅ pass |
| **Итого** | **188** | ✅ **pass** |

---

## 3. Разбивка по тест-модулям

| Модуль | Тестов | Категория | Результат |
|---|---:|---|---|
| tests/test_high_severity_fixes.py | 25 | Pricing/Risk | ✅ |
| tests/test_var.py | 20 | Risk | ✅ |
| tests/test_medium_severity_fixes.py | 16 | Pricing/Risk | ✅ |
| tests/test_portfolio_service.py | 13 | Risk | ✅ |
| tests/test_market_data_foundation.py | 12 | Pricing/Market | ✅ |
| tests/test_trees.py | 11 | Pricing | ✅ |
| tests/test_governance_platform.py | 11 | Governance | ✅ |
| tests/test_black_scholes.py | 11 | Pricing | ✅ |
| tests/test_architecture_cleanup.py | 10 | Architecture | ✅ |
| tests/test_service_boundaries.py | 9 | Governance/Arch | ✅ |
| tests/test_monte_carlo.py | 7 | Pricing | ✅ |
| tests/test_architecture_phase1.py | 7 | Architecture | ✅ |
| tests/test_workstation_navigation.py | 6 | Workspace | ✅ |
| tests/test_scenario_engine.py | 6 | Risk | ✅ |
| tests/test_critical_fixes.py | 6 | Pricing | ✅ |
| tests/test_ui_service_migration.py | 5 | Workspace | ✅ |
| tests/test_fixed_income_professionalization.py | 5 | Pricing | ✅ |
| tests/test_ui_replatforming.py | 4 | Workspace | ✅ |
| tests/test_fixed_income_pricing_service.py | 4 | Pricing | ✅ |
| **Итого** | **188** | | ✅ |

---

## 4. Верификация по требованиям

### 4.1 No pricing regressions ✅
97 pricing-тестов проходят, включая регрессии всех применённых фиксов:
- BSM put-call parity, ATM known value; put delta@expiry, volga/ultima scaling.
- Деревья CRR/LR/трином сходятся к BSM; theta = дневная (страж от ложного «фикса»).
- Monte Carlo vs BSM; контрольная переменная без смещения.
- Fixed income: clean/dirty/accrued, day-count, modified duration через YTM.
- Caplet: единичное дисконтирование; cap−floor паритет.
- Market data foundation: валидация кривой, source-флаги.
- Spot-check: put-call parity residual = 0.000000.

### 4.2 No risk regressions ✅
39 risk-тестов проходят:
- VaR/ES: квантиль, ES≥VaR (spot-check: True), многодневные окна vs sqrt-fallback.
- Унифицированный `RiskService.var(method=…)` — побитовое совпадение с индивидуальными методами.
- Portfolio service: risk-factor exposures, scenario P&L.
- Scenario engine.

### 4.3 No governance regressions ✅
20 governance/boundary-тестов проходят:
- production gating (`production_allowed`), статусы, normalization реестра.
- Service boundaries: панели через сервисы; analytics_workspace через GovernanceService
  (парность статусов с реестром).

### 4.4 No workspace regressions ✅
15 workspace/UI-тестов проходят headless (PySide6 offscreen):
- workstation navigation, UI replatforming, UI→service migration.

---

## 5. Passed / Failed

- **Passed:** 188 / 188.
- **Failed:** 0.
- **Errors:** 0.
- **Skipped:** 0.

Сбойных или нестабильных тестов в прогоне не выявлено.

---

## 6. Известные ограничения (known limitations)

Не баги, а осознанные границы текущей реализации:

1. **UI-тесты требуют PySide6 + offscreen.** Локально без PySide6 три модуля (`test_ui_*`,
   `test_workstation_navigation`) не собираются. В CI заданы Qt-библиотеки и
   `QT_QPA_PLATFORM=offscreen`; первый запуск GitHub Actions ещё не подтверждён эмпирически —
   возможна донастройка apt-пакетов Qt.
2. **Логические слои вместо физических пакетов.** Целевая структура §19 (`market/`, `pricing/`,
   `portfolio/`, `governance/`, `analytics/`) реализована через `domain/` + `services/`, а не
   отдельными top-level пакетами. Это осознанный компромисс (см. §7.1 PRODUCT_ARCHITECTURE).
3. **Historical VaR консолидирован на сервисном уровне**, не физически: `risk/historical_var.py`
   остаётся отдельным модулем (разделяет квантильное ядро с `risk/var.py`), единый вход —
   `RiskService.var(method=…)`.
4. **Демо-данные.** OFZ/RUONIA/CBR — DEMO-кривые (помечены `MarketDataSource.DEMO`); не
   производственные котировки. MOEX ISS интеграция не реализована.
5. **Без персистентности.** Портфели/снапшоты/результаты — in-memory (Phase 6 не начата).

---

## 7. Остаточный технический долг (residual technical debt)

Подтверждён валидацией; вне области закрытых задач:

**Архитектура / инфраструктура**
- Phase 6 (persistence: SQLite/Postgres) — не начата.
- `AuditService` / `AuditEvent` (§15.7, §27) — отсутствует; нет журнала расчётов.
- Первый зелёный прогон CI на GitHub Actions не подтверждён.

**Методология моделей (открытый бэклог из аудитов; требует точечной верификации)**
- **Digital put vega sign** — тот же класс ошибки, что и исправленная gamma; намеренно вне
  области прошлой задачи. Рекомендуется к фиксу.
- **Fixed income** ([FIXED_INCOME_AUDIT.md](FIXED_INCOME_AUDIT.md)): FRN без reset/projection,
  IRS single-curve (нет dual-curve OIS), off-coupon валюация, конвенции accrued по OFZ.
- **Credit**: псевдо-бутстрап кривой выживаемости (flat `s/(1-R)`, не итеративный).
- **Barrier**: неполная таблица Reiner-Rubinstein; Ikeda-Kunitomo (double barrier) без d3n/d4n.
- **LOW severity** ([MODEL_REVIEW_AND_RECOMMENDATIONS.md](MODEL_REVIEW_AND_RECOMMENDATIONS.md)):
  SVI no-arbitrage ограничение `a≥0` слишком жёсткое; GARCH log-likelihood без константы
  `−0.5·n·log(2π)`; YieldCurve modified duration использует zero rate (как исправлено в bond).

**Покрытие тестами**
- Нет UI smoke-теста «приложение стартует / каждый workspace открывается» полного цикла.
- Backtesting (Kupiec/Christoffersen) — узкое покрытие краевых случаев.

> **Замечание по проверенным «не-багам».** В ходе фиксов 5 пунктов аудита оказались ложными
> срабатываниями и **намеренно не менялись** (подтверждены тестами как корректные): theta
> деревьев и Monte Carlo, стабильная формулировка Heston («Little Heston Trap»), дискретный
> geometric Asian d1, предел Vasicek κ=0. Это не долг, а валидированная корректность.

---

## 8. Заключение

Полная регрессия — **188/188 passed**, регрессий в pricing, risk, governance и workspace
не обнаружено. Ключевые инварианты подтверждены независимыми spot-проверками (put-call parity,
ES≥VaR, репрайсинг кривой Hull-White). Кодовая база в текущем объёме готова к демо-уровню;
до production-кандидата остаётся методологический FI/credit-бэклог, персистентность и audit trail
(раздел 7).
