# План: выбор и визуализация данных в нужных местах

**Дата:** 2026-06-13
**Сделано к этому моменту:** расширен сбор (commodity futures, dividends — V.4);
создан **Data Browser** — вкладка Market Data с выпадающим выбором датасета
(8 листов, как Excel) на тестируемом presenter-слое `services/market_views`.
**Этот документ:** где ещё нужен выбор данных и где подключить графику.

---

## 1. Принцип (неизменен)

`presenter (services/market_views, чистый+тестируемый) → тонкая Qt-обёртка`.
Data Browser задал паттерн: `dataset_catalog()` (что выбрать) + `dataset_table()`
(что показать). Графику добавляем тем же путём: presenter готовит (x, y, серии) →
`ChartWidget` рисует. UI не импортирует curves/* напрямую.

## 2. Где нужен ВЫБОР данных (селекторы)

| Место | Селектор | Состояние |
|---|---|---|
| Market Data → Data Browser | датасет (dropdown) | ✅ сделано |
| Market Data → Data Browser | **снапшот/дата** (06-09 / 06-10 / 06-13) | ⬜ добавить второй dropdown |
| Vol Surface Explorer | базовый актив (28 шт) | ⬜ сейчас авто-первый |
| Curve Explorer | кривые для оверлея (мультивыбор) | ⬜ |
| Risk → Factors | набор факторов корреляции | ⬜ фикс-список |
| Pricing | curve_id / vol_surface_id / hazard_id из снапшота | 🟡 частично (curve roles) |
| Time Series Explorer (новый) | фактор + тенор + окно | ⬜ |

**Приоритет селекторов:** (1) выбор даты снапшота в Data Browser — он уже листает
датасеты, дата сделает его полноценным «обозревателем выгрузок»; (2) выбор
underlying в Vol Explorer; (3) выбор факторов в Risk.

## 3. Где нужна ВИЗУАЛИЗАЦИЯ (графики)

`ChartWidget` (matplotlib) уже умеет рисовать, но подключён только в Pricing.
Подключаем к реальным данным через presenter'ы:

| График | Данные (presenter) | Куда | Приоритет |
|---|---|---|---|
| Оверлей кривых (КБД+CORP+real) | curve_table | Curve Explorer | P1 |
| История тенора (КБД:5Y…) | curve_history_series | Curve Explorer / Data Browser | P1 |
| Vol smile + SVI-фит | vol_smile_slices | Vol Explorer | P1 |
| ATM терм-структура волы | atm_term_structure | Vol Explorer | P2 |
| Корреляц. heatmap факторов | factor_series | Risk → Factors | P1 |
| Bond scatter YTM×дюрация | (новый) bond_scatter | Bond Explorer | P2 |
| Commodity фьюч-кривая | (новый) commodity_curve | Commodity panel | P2 |
| Breakeven-кривая | breakeven_term_structure | Curve Explorer | P2 |
| Дивидендная история бумаги | get_dividends | Data Browser drill-down | P3 |

## 4. План внедрения (поэтапно, тестируемо)

### Шаг 1 — Снапшот-селектор в Data Browser (~0.5 дня)
Второй dropdown: список снапшотов из `market_data_snapshots`. Меняет дату →
`dataset_catalog/table` перестраиваются на выбранный snapshot_id. Превращает
Data Browser в полный «обозреватель всех выгрузок по датам».
Presenter: `available_snapshots(db)` → [{id, date, source, quality}].

### Шаг 2 — Графический слой в ChartWidget (~2-3 дня, фундамент)
Подключить P1-графики: оверлей кривых, история тенора, vol smile+SVI,
корреляц. heatmap. Каждый — presenter (chart-ready арреи) + вызов ChartWidget;
новый метод `plot_heatmap` для корреляций. Smoke-тесты под offscreen.

### Шаг 3 — Vol Explorer 2.0 с выбором актива (~1-2 дня)
Dropdown из 28 underlyings → смайлы по экспирациям (график) + ATM-терм +
SVI-параметры. Переиспользует vol_smile_slices.

### Шаг 4 — Bond & Commodity explorer'ы (~2-3 дня)
Bond: scatter YTM×дюрация (presenter bond_scatter из bond_quotes+instruments),
drill в cashflow-расписание (bond_schedule). Commodity: фьюч-кривая по активу.

### Шаг 5 — Графики в Risk и замена demo-дашборда (~2-3 дня)
Risk Factors: корреляц. heatmap + динамика вол. Dashboard: реальный
Market Overview (КБД, топ-движения, FX, волы) вместо хардкода.

### Шаг 6 — Time Series Explorer (~1-2 дня)
Отдельный таб: выбор фактора/тенора + окна, график уровня и доходностей,
rolling-vol. На factor_series / curve_history_series.

## 5. Порядок и зависимости

Шаг 1 (дата-селектор) — быстрый, сразу повышает ценность Data Browser →
делать первым. Шаг 2 (графический фундамент) — разблокирует 3–6. Дальше по
приоритету P1→P3. Сбор под визуализацию (default-флаги, веса индексов) — из
DATA_INFRASTRUCTURE_PLAN V.4, параллельно, не блокирует.

## 6. Критерий готовности
Любая выгруженная величина (кривая, бумага, поверхность, ряд, товар, дивиденд)
доступна в UI: выбирается селектором и показывается таблицей И, где осмысленно,
графиком — на реальных данных через app.runtime, с headless-тестами presenter'ов.
