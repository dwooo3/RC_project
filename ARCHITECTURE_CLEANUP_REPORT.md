# Architecture Cleanup Report

**Дата:** 2026-06-04
**Область:** структурная очистка по [CURRENT_ISSUES_AND_REMEDIATION.md](CURRENT_ISSUES_AND_REMEDIATION.md)
**Ограничение:** количественные модели не изменялись (только границы слоёв, маршрутизация, инфраструктура).
**Новые тесты:** [tests/test_architecture_cleanup.py](tests/test_architecture_cleanup.py)

> Все изменения — структурные. Численные результаты pricing/risk не затронуты (подтверждено
> тестами на побитовое совпадение, см. ниже).

---

## Сводка

| # | Пункт (CURRENT_ISSUES) | Статус |
|---|---|---|
| 1 | analytics_workspace → GovernanceService | ✅ Сделано |
| 2 | curves.russia → убрать pricing-зависимость | ✅ Сделано |
| 3 | Консолидация Historical VaR | ✅ Сделано (единый диспетчер) |
| 4 | CI workflow | ✅ Добавлен |
| 5 | requirements.txt | ✅ Добавлен |

---

## 1. analytics_workspace → GovernanceService

**Файл:** [app/panels/analytics_workspace.py](app/panels/analytics_workspace.py)

**Было:** панель импортировала `models.registry` напрямую (нарушение §20.2 «panels → raw engines»):
```python
from models.registry import MODEL_REGISTRY, ModelStatus
def _status_from_key(model_key): 
    return MODEL_REGISTRY.get(model_key, {}).get("status", ModelStatus.PLACEHOLDER)
```

**Стало:** статус берётся через сервисный слой:
```python
from services.governance_service import GovernanceService
_GOVERNANCE = GovernanceService()
def _status_from_key(model_key) -> str:
    return _GOVERNANCE.get_model(model_key).status
```

`StatusChip` (бейдж) уже принимает `ModelStatus | str`, поэтому строковый статус из сервиса
рендерится без изменений. Для незарегистрированных ключей `registry.get` отдаёт `Placeholder` —
прежнее fallback-поведение сохранено.

**Парность:** статусы через сервис побитово совпадают с прямым доступом к реестру для всех
ключей analytics-модулей (`binomial_crr`, `mc_gbm`, `heston_cf`, `short_rate`, `placeholder`,
`garch`). Это был последний прямой импорт UI → engine (из ~38 панелей).

---

## 2. curves.russia → удаление pricing-зависимости

**Файлы:** [curves/russia.py](curves/russia.py), [instruments/fixed_income.py](instruments/fixed_income.py)

**Проблема:** `curves/russia.py` (market-data слой) содержал `price_ofz`, который импортировал
`instruments.fixed_income.fixed_bond` — обратная зависимость Market → Pricing (§20.2).

**Решение:** функция `price_ofz` перенесена в pricing-слой
([instruments/fixed_income.py](instruments/fixed_income.py)), где уже живёт `fixed_bond` и
корректный импорт `curves.yield_curve` (Pricing → Market). Из `curves/russia.py` удалена;
направление зависимости восстановлено:
```text
instruments.fixed_income  ->  curves.yield_curve     (Pricing -> Market, OK)
curves.russia             ->  (нет импорта instruments)
```

**Совместимость:** у `price_ofz` не было ни одного вызова в кодовой базе (проверено `grep`).
Логика wrapper-а не менялась — это перемещение, а не переписывание. Новый путь:
`from instruments.fixed_income import price_ofz`.

`curves/russia.py` теперь не импортирует `instruments` вообще (проверяется AST-тестом).

---

## 3. Консолидация Historical VaR

**Файл:** [services/risk_service.py](services/risk_service.py)

**Контекст:** `risk/historical_var.py` и `risk/var.py` уже разделяют квантильное ядро
(`_loss_var_es`, валидаторы импортируются из `risk/var.py`). Недоставало единой точки входа —
Historical VaR выглядел как отдельный workflow.

**Решение:** добавлен унифицированный диспетчер `RiskService.var(method=...)` — чистое
делегирование к существующим движкам, **без изменения вычислений**:
```python
rs.var(returns, pv, method="historical")   # -> historical_var
rs.var(returns, pv, method="parametric")    # -> parametric_var
rs.var(returns, pv, method="monte_carlo")   # -> monte_carlo_var
rs.var(returns, pv, method="evt")           # -> evt_var
```
Поддержаны алиасы (`hs`, `mc`, `t`, `pot`, …); неизвестный метод возвращает структурированную
ошибку. Historical VaR теперь — один из методов за единым входом, а не отдельный top-level
поток (§14.3).

**Подтверждение неизменности чисел:** для каждого метода `var(method=…)["value"]` побитово равно
результату соответствующего индивидуального метода (`historical_var`, `parametric_var`,
`monte_carlo_var`, `evt_var`). Индивидуальные методы и движки `risk/var.py`,
`risk/historical_var.py` не трогались.

> Физическое слияние `risk/historical_var.py` в `risk/var.py` намеренно не делалось: оно несёт
> риск изменить поведение и затрагивает уникальные функции (`filtered_hs_var`, `portfolio_hs_var`,
> `pca_var`, `backtest_var`), не являющиеся дубликатами. Консолидация выполнена на сервисном
> уровне — там, где этого требует целевая архитектура (UI → service).

---

## 4. CI workflow

**Файл:** [.github/workflows/tests.yml](.github/workflows/tests.yml)

GitHub Actions по §26.1: на `push` и `pull_request`, Python 3.11, установка зависимостей из
`requirements.txt`, прогон `pytest -q`. Для UI-тестов на PySide6 в headless-окружении заданы
системные Qt-библиотеки и `QT_QPA_PLATFORM=offscreen`, чтобы виджеты конструировались без дисплея.

```yaml
- name: Run test suite
  env:
    QT_QPA_PLATFORM: offscreen
  run: pytest -q
```

---

## 5. requirements.txt

**Файл:** [requirements.txt](requirements.txt)

Зафиксированы зависимости (ранее отсутствовал файл; `scipy` ставился вручную):
`numpy`, `scipy`, `PySide6`, `matplotlib`, `pytest` — с разумными нижними границами версий.
Это разблокирует воспроизводимую установку и CI.

---

## Результаты тестов

Новый модуль [tests/test_architecture_cleanup.py](tests/test_architecture_cleanup.py) — 10 тестов:
- curves.russia без импорта `instruments` (AST);
- `price_ofz` перенесён и работает; удалён из `curves.russia`;
- парность статусов governance ↔ registry; analytics_workspace не импортирует raw registry;
- `var(method=…)` совпадает с индивидуальными методами; алиасы; ошибка на неизвестный метод;
- наличие `requirements.txt` и CI workflow.

```text
tests/test_architecture_cleanup.py  10 passed
весь не-UI набор:                    173 passed
```

> UI-модули тестов (`test_ui_*`, `test_workstation_navigation`) локально не собираются из-за
> отсутствия `PySide6`; в CI они выполняются под `QT_QPA_PLATFORM=offscreen`.

---

## Изменённые / новые файлы

| Файл | Изменение |
|---|---|
| [app/panels/analytics_workspace.py](app/panels/analytics_workspace.py) | статус через `GovernanceService` |
| [curves/russia.py](curves/russia.py) | удалён `price_ofz`; нет зависимости от `instruments` |
| [instruments/fixed_income.py](instruments/fixed_income.py) | добавлен `price_ofz` (pricing-слой) |
| [services/risk_service.py](services/risk_service.py) | добавлен диспетчер `var(method=…)` |
| [requirements.txt](requirements.txt) | новый |
| [.github/workflows/tests.yml](.github/workflows/tests.yml) | новый CI |
| [tests/test_architecture_cleanup.py](tests/test_architecture_cleanup.py) | 10 новых тестов |
| ARCHITECTURE_CLEANUP_REPORT.md | этот отчёт |

Количественные модели не изменялись.
