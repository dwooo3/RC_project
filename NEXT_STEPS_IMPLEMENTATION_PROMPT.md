# PROMPT — Next Steps: Interactive UI, Persistence, Reporting, Design/IA

**Назначение:** промт для агента-исполнителя. Доводит RiskCalc от service-backed
витрин до интерактивной workflow-workstation с персистентностью, рендером отчётов
и завершённой дизайн-системой/IA.

**Базовая ветка/состояние:** `main` (Phases A–E интеграции MOEX завершены), 280 тестов зелёные.

**Авторитетные источники (следовать им, НЕ переписывать архитектуру):**
- [PRODUCT_ARCHITECTURE.md](PRODUCT_ARCHITECTURE.md) — слои, dependency rules, north-star workflow §41.
- [RISKCALC_INFORMATION_ARCHITECTURE.md](RISKCALC_INFORMATION_ARCHITECTURE.md) — 7 слоёв, под-экраны, cross-layer workflows §10.
- [UI_REDESIGN.md](UI_REDESIGN.md) — детальный дизайн каждого workspace/модуля, acceptance §21.
- [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) — токены, компоненты, шаблоны экранов.
- [RISKCALC_SCREEN_WIREFRAMES.md](RISKCALC_SCREEN_WIREFRAMES.md) — каркасы экранов.
- [PRODUCTION_CANDIDATE_GAP_ANALYSIS.md](PRODUCTION_CANDIDATE_GAP_ANALYSIS.md) — разрывы/оценки.

> **Явно отложено:** детальная валидация количественных моделей против рыночных данных.
> Сначала — готовый проект по архитектуре, интерфейсу, дизайну и логике связей (модели/блоки).
> Модели не переписывать (они выправлены и покрыты тестами); только подключать через сервисы.

---

## 0. Контекст: что уже есть (строить поверх, не ломать)
- **Shell/UI:** `ui/` (theme, components, layouts.WorkstationWorkspace, shell). Все 7 workspaces
  + Dashboard на этом shell, service-backed (Market/Pricing/Risk/Portfolio/Governance/Analytics).
- **Сервисы:** `services/` — MarketData, Pricing, Risk, Portfolio, Governance, Audit, Reporting.
- **Данные:** `infra/` — MOEX/CBR ingest, SQLite/Postgres `MarketDataDB`, EOD-джоб + scheduler,
  governed `MarketDataSnapshot` с quality/lineage и DEMO-fallback.
- **Проблема №1:** workspaces — витрины. Интерактивная цепочка «ввод → сервис → результат»
  не реализована; старые калькуляторные панели (`app/panels/*_panel.py`, кроме workspace-ов и
  `portfolio_panel`) осиротели (нет в навигации, не встроены). Их переоформить как detail-views
  внутри workspaces или заменить — НЕ возвращать прямые вызовы движков из UI.

**Жёсткие правила (из dependency rules §20):** UI → services только; никакого построения рыночных
объектов/прямых вызовов моделей в виджетах; demo/stale данные несут видимый warning; результаты
несут snapshot_id + governance + audit (механизмы уже есть в сервисах).

---

## Phase F — Interactive Workflow UI (ядро)

Цель: каждый workspace получает интерактивные module-detail экраны со сквозной логикой
«ввод параметров → вызов сервиса → governed-результат». Результат всегда показывает: market
snapshot (source/quality/trade date), governance status/версия модели, warnings, audit id +
inputs hash (всё уже возвращают сервисы).

### F1. Pricing workspace (Rates/FX/Equity/Credit/Structured)
- Detail-формы: Bond/OFZ, IRS/OIS, FX Forward, FX/Equity Option (минимум — по §8–10 UI_REDESIGN).
- Поток: форма → `PricingService.price_*` (с выбранным снапшотом из `MarketDataService.moex_snapshot`/demo)
  → результат-панель (price, cashflows, sensitivities, warnings, audit).
- Снапшот выбирается явно; demo/stale → баннер «Not production valuation».

### F2. Risk workspace (VaR/ES, Stress, Backtesting)
- VaR-экран: выбор метода (historical/parametric/MC/EVT — единый `RiskService.var(method=…)`),
  confidence/horizon → результат (VaR, ES, распределение). Источник доходностей —
  `MarketDataService.get_returns(factor_id)` (Phase C).
- Stress: набор сценариев/шоков → `RiskService.stress_*` / portfolio scenario.
- Backtesting: P&L-ряд + VaR-ряд → Kupiec/Christoffersen/Basel (движок есть в `risk`); вывести как экран.

### F3. Portfolio workspace (центральный объект)
- Positions: загрузка/просмотр позиций; Exposure (risk-factor buckets); Scenario P&L; P&L Explain;
  Validation. Всё через `PortfolioService` (уже UI-boundary). Вкладки по §12 UI_REDESIGN / IA §3.

### F4. Market workspace
- Curve/FX/Vol/Credit explorers уже отображают source/quality/lineage. Добавить: построение/валидацию
  кривой (через `MarketDataService`), просмотр снапшота и его версий (lineage уже есть).

**Definition of Done (F):** из каждого workspace можно выполнить расчёт и увидеть governed-результат;
ни один виджет не вызывает движки напрямую; demo/stale несут warning; добавлены UI-тесты, проверяющие
поток ввод→сервис→результат (offscreen). Осиротевшие панели либо подключены как detail-views, либо удалены.

---

## Phase G — Persistence (SQLite → Postgres, слой готов)

Цель: убрать in-memory ограничение, обеспечить воспроизводимость (§27).
- Репозитории поверх существующего DB-слоя (`infra/db`, диалект-независимый): `portfolios`,
  `positions`, `calculation_results`, `audit_events` (+ уже есть market_data_*).
- `AuditService` → персистит записи (сейчас `_records: list`); чтение audit trail из БД.
- Сохранение/загрузка портфеля; сохранение результатов pricing/risk с `snapshot_id`+`inputs_hash`.
- Воспроизводимость: восстановление расчёта из сохранённого запроса (replay).

**DoD (G):** перезапуск приложения сохраняет портфели/историю/audit; результат восстановим из БД;
тесты на round-trip и replay; SQLite по умолчанию, путь Postgres (инъекция соединения) сохранён.

---

## Phase H — Reporting renderer

Цель: превратить PDF-ready структуры (`services/reporting_service` — 5 отчётов) в реальный вывод.
- Рендерер HTML и/или PDF (например reportlab/weasyprint), шаблоны по DESIGN_SYSTEM (токены/типографика).
- Экспорт-пайплайн + кнопки «Export» в workspaces (Portfolio/Risk/Governance) → файл.
- Отчёт несёт provenance: snapshot, модели/версии, warnings, audit id.

**DoD (H):** каждый из 5 отчётов рендерится в файл; экспорт доступен из UI; тест проверяет генерацию
непустого артефакта и наличие provenance-метаданных.

---

## Phase I — Design system & IA completion

Цель: единый визуальный язык и завершённая информационная архитектура.
- Привести все экраны к токенам/компонентам [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) (цвет/типографика/плотность/таблицы/чипы); убрать остаточные хардкод-стили.
- Реализовать под-экраны слоёв и cross-layer навигацию по IA §1–§10; собрать **north-star workflow**
  (Dashboard → Portfolio → Risk → Governance → Report, §41 PRODUCT_ARCHITECTURE).
- UI smoke-тесты (offscreen): приложение стартует; каждый workspace открывается; каждый module-landing
  рендерится; переключение темы; ни один модуль не падает молча (UI_REDESIGN §21 acceptance).

**DoD (I):** дизайн консистентен по чек-листу DESIGN_SYSTEM; north-star workflow проходится сквозь;
UI smoke-suite зелёная; acceptance-критерии UI_REDESIGN §21 выполнены.

---

## Сквозные правила и порядок
1. Инкрементальные коммиты (по под-фазам); каждая фаза — тесты + краткий отчёт.
2. Не трогать количественные модели; не переписывать архитектуру; следовать перечисленным docs.
3. Тесты без сети (фикстуры); UI-тесты под `QT_QPA_PLATFORM=offscreen`.
4. Полный прогон `pytest -q` зелёный после каждой под-фазы; обновлять существующие тесты при
   намеренной смене поведения (с пояснением).
5. **Порядок:** F (интерактив) → G (персистентность) → H (reporting) → I (дизайн/IA).
   F и I частично параллельны (F даёт экраны, I их причёсывает). G разблокирует reproducibility и H.

## Вне области (отложено)
- Детальная валидация моделей против рыночных данных MOEX (отдельная фаза J позже).
- Живое заполнение БД (нужна сеть; дата 2026-06-02) и подтверждение ⚠️-эндпоинтов ISS/CBR/FORTS.
- Dual-curve OIS (нужны OIS-своп котировки), реальные vol-поверхности FORTS с расчётом IV из премии.
