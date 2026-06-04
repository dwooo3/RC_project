# Current Issues & Remediation Plan

**Дата:** 2026-06-04
**Состояние ветки:** `main` (clean)
**Базовый коммит:** `4e6cba9 Implement Risk Workspace v1`
**Метод:** статическая сверка фактического кода с целевой архитектурой
[PRODUCT_ARCHITECTURE.md](PRODUCT_ARCHITECTURE.md) (§19, §21, §30, эпики A–E) и
методологическим бэклогом из [AUDIT.md](AUDIT.md), [FIXED_INCOME_AUDIT.md](FIXED_INCOME_AUDIT.md),
[RISK_MODEL_AUDIT.md](RISK_MODEL_AUDIT.md).

> **Назначение документа:** зафиксировать проблемы и недочёты на текущем этапе и предложить
> исправления. Это backlog, а не отчёт о правках — код по этому документу не менялся.

---

## 0. Сводка статуса по фазам

| Фаза (PRODUCT_ARCHITECTURE §30) | Статус | Подтверждение |
|---|---|---|
| Phase 1 — Architecture foundation | ✅ Сделано | `domain/`, `services/`, единственный `class YieldCurve` |
| Phase 2 — Risk & Portfolio foundation | ✅ В основном | `PortfolioService`, `RiskFactorExposure`, `domain/scenario.py`, Portfolio Workspace v1 |
| Phase 3 — Pricing refactor | ✅ В основном | `PricingService`, `PricingResult`, FI professionalization |
| Phase 4 — Governance | ✅ В основном | `governance_workspace.py`, `production_allowed` gating |
| Phase 5 — UI redesign | ✅ Сделано | пакет `ui/`, workstation shell, redesigned workspaces |
| Phase 6 — Persistence | ❌ Не начато | всё in-memory, нет SQLite/Postgres |

**Итог:** логически пройдены Phase 1–5. Открыты: Phase 6 и хвосты (структурные + методологические).

**Шкала уверенности находок:** 🟢 проверено напрямую в коде · 🟡 частично проверено · 🔵 из audit-бэклога, требует повторной верификации в коде.

---

## 1. Структурные расхождения с целевой архитектурой

### 1.1 🟢 Top-level пакеты целевой структуры не созданы — **P1**

§19 и §21 предполагают пакеты `market/`, `pricing/`, `portfolio/`, `governance/`,
`analytics/`. Ни одного из них нет. Вместо физического переноса реализовано логическое
разделение через `domain/` + `services/` поверх старых `curves/`, `instruments/`, `risk/`, `models/`.

| Домен | Цель (§21) | Факт |
|---|---|---|
| YieldCurve | `market/curves/` | [curves/yield_curve.py](curves/yield_curve.py) |
| Portfolio | `portfolio/` | [risk/portfolio.py](risk/portfolio.py) (facade) + `domain/` + `services/` |
| Model Registry | `governance/registry/` | [models/registry.py](models/registry.py) |
| VaR | `risk/var/` | [risk/var.py](risk/var.py) + [risk/historical_var.py](risk/historical_var.py) |

**Замечание:** §7.1 прямо допускает, что «слои — продуктовые концепции, не обязательно точные
Python-пакеты». Поэтому это расхождение можно трактовать как осознанный компромисс.

**Предложение:**
- **Вариант A (буквальный):** выполнить переезд по Module Ownership Matrix через strangler-паттерн
  (новый пакет → re-export из старого места → перевод импортов → удаление). Высокий риск, большой diff.
- **Вариант B (прагматичный, рекомендуется):** зафиксировать в `PRODUCT_ARCHITECTURE.md`, что
  слои реализуются логически через `domain/`+`services/`, и считать §19/§21 «концептуальной»,
  а не «файловой» целью. Тогда расхождение закрывается документально, без рискованного рефактора.

### 1.2 🟢 `historical_var.py` остаётся отдельным модулем — **P2**

§14.3: Historical VaR не должен быть отдельным top-level модулем. Логически он
консолидирован за `RiskService` (`4da4110 Consolidate VaR ES loss conventions`), но
файл-движок [risk/historical_var.py](risk/historical_var.py) и панель
[app/panels/histvar_panel.py](app/panels/histvar_panel.py) живут отдельно.

**Предложение:** свести historical/age-weighted/parametric/MC/EVT в единый VaR-движок с
выбором метода-параметром; панель `histvar` сделать вкладкой VaR-workspace, а не отдельным
пунктом. Низкий риск (логика уже за сервисом).

### 1.3 🟢 Обратная зависимость Market → Pricing — **P2**

[curves/russia.py:104](curves/russia.py#L104) импортирует `instruments.fixed_income.fixed_bond`,
что разворачивает направление Market Data → Pricing (нарушение §20.2).

**Предложение:** вынести `price_ofz`-обёртку из `curves/` в pricing-слой/сервис, оставив в
`curves/russia.py` только данные кривой (OFZ/RUONIA как DEMO-провайдер). Низкий риск.

### 1.4 🟢 Остаточный прямой импорт UI → engine — **P2**

Из ~38 панелей только [app/panels/analytics_workspace.py:12](app/panels/analytics_workspace.py#L12)
импортирует `models.registry` напрямую (`MODEL_REGISTRY`, `ModelStatus`), минуя
`GovernanceService`. Остальные панели переведены на сервисы (~12 явных импортов `services`).

**Предложение:** заменить прямой импорт на `GovernanceService` (метод выдачи списка моделей и
статусов для Analytics Lab). Низкий риск.

---

## 2. Незавершённые элементы целевой архитектуры

### 2.1 🟢 Phase 6 — Persistence не начата — **P1**

Нет SQLite/Postgres-слоя (§18, §30 Phase 6). Позиции, портфели, снапшоты рыночных данных и
результаты расчётов живут только в памяти. Это блокирует требования §27 (аудируемость и
воспроизводимость: сохранённый запрос → повторный расчёт).

**Предложение:** SQLite-прототип репозиториев для `portfolios`, `positions`,
`market_data_snapshots`, `pricing_results`, `risk_results` за интерфейсами в `services/`.
Начать с сохранения/загрузки портфеля.

### 2.2 🔵 Audit trail отсутствует/неполон — **P1**

§15.7 и §27 требуют журнал: кто/когда запустил, входы, версия модели, snapshot, результат,
warnings/errors. `AuditService` в списке требуемых сервисов (§10.2) не подтверждён в коде.

**Предложение:** добавить `AuditService` + доменный `AuditEvent`; писать событие при каждом
прогоне pricing/risk через сервисы. Зависит от 2.1 (хранилище).

### 2.3 🔵 CI/CD отсутствует — **P2**

§26.1 предлагает GitHub Actions (`pytest -q` на push/PR). Файла workflow в репозитории нет.
Тестов уже много ([tests/](tests/), 16 файлов), поэтому CI даст быстрый выигрыш.

**Предложение:** добавить `.github/workflows/tests.yml` и `requirements.txt` (зафиксировать
`scipy` и прочие зависимости — ранее ставились вручную).

---

## 3. Методологический бэклог (engine-уровень)

> Источник — audit-документы. Часть позиций закрыта архитектурной работой; статус ниже —
> на основе коммитов/тестов и требует точечной перепроверки в коде (🔵), где не помечено иначе.

### 3.1 Закрытые/частично закрытые

| ID | Тема | Статус | Доказательство |
|---|---|---|---|
| P0-006 | Mixed Greeks aggregation | 🟡 закрыто | `RiskFactorExposure` в [services/portfolio_service.py](services/portfolio_service.py) (factor buckets вместо суммы Greeks) |
| P0-008 | Demo-данные выглядят реальными | 🟡 закрыто | `MarketDataSource.DEMO` + флаги источников в market data foundation |
| P1-008 | Нет production gating | 🟢 закрыто | `production_allowed` в [models/registry.py:333](models/registry.py#L333), [services/governance_service.py:45](services/governance_service.py#L45) |
| P0-001 | Несогласованный weighted VaR/ES | 🟡 закрыто | `4da4110 Consolidate VaR ES loss conventions` (перепроверить age-weighted квантиль) |
| P1-006 | Dashboard содержит registry-таблицу | 🟡 закрыто | dashboard redesign + отдельный `governance_workspace.py` |

### 3.2 Открытые — требуют верификации и правок (🔵)

| ID | Область | Проблема | Предложение |
|---|---|---|---|
| P0-002 | Monte Carlo | Неверный expected value control variate | Использовать матожидание дисконтированного терминального spot |
| P0-003 | Monte Carlo | Баг формы при нечётном `n_sims` (Heston) | Принудительно чётное число симуляций / `actual_sims` |
| P0-004 | BSM | Краевые случаи zero-vol и истечения (в т.ч. put delta на экспирации) | Детерминированные ветки + тесты |
| P0-005 | Trees | Тихий клиппинг вероятностей | Заменить на валидацию/предупреждение |
| P0-007 | Stress | Вводящие в заблуждение тоталы P&L explain | Переименовать и скорректировать итоговые поля |
| P1-001 | Fixed Income | Нет дат/графика начислений у облигаций | Schedule-движок (частично — см. `42a0e2a Professionalize fixed income`) |
| P1-002 | Fixed Income | IRS single-curve | Dual-curve IRS (пока допустимо как approximation с видимым warning, §12.6) |
| P1-003 | Fixed Income | FRN без reset/projection-логики | Пересобрать ценообразование FRN |
| P1-004 | Curves | Слабая модель интерполяции/конвенций | Валидация кривой + опции интерполяции (частично сделано в curve validation) |
| P1-005 | Risk | Узкое покрытие бэктестинга | Краевые тесты Kupiec/Christoffersen |

> **FIXED_INCOME_AUDIT.md** содержит дополнительно 5×P0 и 12×P1 по конвенциям FI (off-coupon
> валюация, спот-стартующий IRS, accrued по OFZ и т.д.). Их следует пройти после решения по 1.1
> (куда уезжает FI-pricing) — это снижает двойную работу.

---

## 4. Приоритизированный план действий

**Сначала — дешёвые и безопасные (низкий риск, закрывают нарушения слоёв):**
1. 1.4 — убрать прямой импорт `models.registry` из `analytics_workspace.py`.
2. 1.3 — развернуть зависимость `curves.russia → instruments`.
3. 2.3 — добавить CI (`pytest`) + `requirements.txt`.
4. 1.2 — консолидировать historical VaR в единый движок/вкладку.

**Затем — решение по структуре:**
5. 1.1 — принять Вариант A (переезд) или Вариант B (документально зафиксировать логические слои).
   Рекомендуется B, если нет внешнего требования на точную файловую структуру §19.

**Далее — фундамент для production-готовности:**
6. 2.1 — SQLite-персистентность (портфели/позиции/снапшоты/результаты).
7. 2.2 — `AuditService` + `AuditEvent` поверх персистентности.

**Параллельно — методология (engine-уровень, §3.2):**
8. Закрыть оставшиеся P0 (MC, BSM, Trees, Stress) с тестами на каждый фикс.
9. Пройти FI-бэклог (FRN, dual-curve IRS, schedule/accrual) после решения по 1.1.

---

## 5. Метод и оговорки

- Находки 🟢 проверены напрямую в коде на коммите `4e6cba9`.
- Находки 🟡 подтверждены косвенно (коммиты/тесты/частичный код) — рекомендуется точечная перепроверка.
- Находки 🔵 взяты из audit-документов и **не** перепроверялись построчно в текущем коде; часть
  могла быть закрыта незадокументированно. Перед правкой каждого 🔵 — сначала верификация.
- Код в рамках этого документа не изменялся.
