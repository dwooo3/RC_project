# RiskCalc — План перехода на новый дизайн (светлая тема)

**Статус:** черновик к исполнению
**Источник истины (макет):** [design/pricing_v6_light.svg](design/pricing_v6_light.svg) · растр [design/pricing_v6_light.png](design/pricing_v6_light.png)
**Эталонный экран:** Pricing → Fixed Income → Bond / OFZ
**Дата:** 2026-06-06

Цель — перевести десктоп-приложение (PySide6) на единый светлый визуальный язык
в стиле macOS 2026, зафиксированный в макете `pricing_v6_light`. Бизнес-логика,
сервисный слой и движки прайсинга **не меняются** — переход касается только
слоёв `ui/` и `app/panels/*`.

> Вне рамок: порт на Swift, валидация моделей с рыночными данными, нативное окно
> macOS (светофор/скругление окна/обои даёт ОС — мы рисуем только содержимое окна).

---

## 1. Текущее состояние

| Слой | Файл | Что есть сейчас |
|---|---|---|
| Токены темы | [ui/theme.py](ui/theme.py) | один **тёмный** `PALETTE` (frozen dataclass), `WORKSTATION_STYLE` (f-string QSS), `status_style()`, `value_color()` |
| Компоненты | [ui/components.py](ui/components.py) | `WorkspaceCard`, `WorkstationPanel`, `KpiCard`, `StatusChip`, `DataSourceChip`, `WarningBanner`, `SectionLabel`, `WorkspaceHeader`, `CommandBar`, `ContextDrawer`, `KpiStrip`, `DenseTable`, `make_action`, `QuickNavCard` |
| Оболочка | [ui/shell.py](ui/shell.py) | `GlobalNavigation`, `WorkspaceHeaderBar`, `ShellStatusBar`, `WorkspaceShell` — стили заданы инлайн через `PALETTE` |
| Раскладка | [ui/layouts.py](ui/layouts.py) | `WorkstationWorkspace` (header + splitter + опц. context drawer) |
| Хаб прайсинга | [app/panels/pricing_workspace.py](app/panels/pricing_workspace.py), [pricing_detail.py](app/panels/pricing_detail.py), [pricing_catalogue.py](app/panels/pricing_catalogue.py) | категории-табы → dropdown → detail-экран через `PricingService` |

**Главная техническая сложность:** `PALETTE` — единственный замороженный
тёмный инстанс, который десятки мест импортируют как `from ui.theme import PALETTE`
и подставляют в f-string-стили на этапе импорта модуля. Смена темы = смена
значений токенов + точечная замена там, где тёмная тема «зашита» цветом.

---

## 2. Целевой визуальный язык (из `pricing_v6_light`)

### 2.1. Палитра (light)

| Токен | Значение | Назначение |
|---|---|---|
| `bg_workspace` | `#EBEEF4 → #E1E6EF` | фон рабочей области (мягкий градиент) |
| `bg_window` | `#FBFBFD` | фон окна под карточками |
| `bg_card` | `#FFFFFF` | карточки: sidebar, Valuation, Parameters |
| `bg_field` | `#F3F5F9` | поля ввода |
| `bg_footer` | `#F5F7FA` | зафиксированный футер Valuation |
| `border_default` | `#2A2F3A @ 8%` | кромка карточек, делители |
| `txt0` / `txt_strong` | `#1C2026` / `#15181D` | основной текст / крупные числа |
| `txt1` | `#6B7280` | вторичный текст |
| `txt2` | `#8A91A0` | подписи полей, провенанс |
| `txt3` | `#9AA1AC` | заголовки секций, плейсхолдеры |
| `txt_table` | `#3A414C` | данные таблиц |
| `txt_nav` | `#4A5260` | пункты меню |
| `accent` | `#D9633F` | акцент, кнопки, активный пункт-иконка |
| `accent_pressed` | `#C4502E` | текст активного пункта/нажатие |
| `accent_soft` | `#D9633F @ 12%` | подложка активного пункта меню |
| `positive` | `#0E8A5A` (bg `#12A06A @ 14%`) | статус OK / положительные значения |
| `warn_text` / `warn_dot` / `warn_bg` | `#9A7300` / `#B5860B` / `#E0A800 @ 16%` | статус «Approximation» |
| `scroll_track` / `scroll_thumb` | `#2A2F3A @ 6%` / `@ 22%` | скроллбар |

### 2.2. Форма и тень

- Скругления: окно `22` (нативное), карточки/sidebar `16`, поля `9–10`, пилюли типов `8`, активный пункт меню `10`, статус-пилюли `6`.
- Тени (через `QGraphicsDropShadowEffect`, не QSS):
  - карточка: `dy 8, blur 16, #5A6378 @ 18%`
  - окно: нативное.
- Кромка карточек: `1px #2A2F3A @ 8%`.

### 2.3. Типографика

- Семейство: `SF Pro Display` / `SF Pro Text` (fallback `-apple-system`, `Inter`).
- Цена: `44 / 700`. Заголовок экрана: `23 / 700`. Заголовки секций: `11`, uppercase, letter-spacing.
- Метрики: подпись `13`, значение `13 / 600`. Поля: подпись `11`, значение `13.5`.
- Меню: `13.5 / 500`, активный `600`. Числа в таблицах — моноширинные (`SF Mono`), выравнивание по правому краю.

### 2.4. Раскладка (сетка эталонного экрана 1440×900)

```
┌ окно (нативное, rx22) ───────────────────────────────────────────────┐
│ ●●●  RiskCalc            Pricing   [FI|Options|…]                      │ тулбар
│                          [ Bond / OFZ  ▼ ]   [ Calculate ]            │
│ ┌ sidebar ┐  ┌ Valuation (скролл) ───────────┐  ┌ Parameters ─────┐  │
│ │ • Dash  │  │ VALUATION      ●Approx ●OK     │  │ Face   Coupon   │  │
│ │ • Mkts  │  │ 799.39                         │  │ Freq   Maturity │  │
│ │ ▸Pricing│  │ метрики (2 кол.)               │  │ Settle Rate     │  │
│ │ • Port. │  │ CASHFLOW SCHEDULE (таблица)    │  │ DayCnt Compnd   │  │
│ │ • Risk  │  │ DISCOUNT CURVE (таблица)       │  │ Discount curve  │  │
│ │ • Gov.  │  ├────────────────────────────────┤  │ Projection curve│  │
│ │ • Anal. │  │ MV 1 998 475 ₽  QTY [..] [Add] │← │ Call schedule   │  │
│ │ • Data  │  └ фикс. футер, низ скруглён ─────┘  └─────────────────┘  │
│ └─────────┘                                                            │
└───────────────────────────────────────────────────────────────────────┘
```

- Sidebar — отдельная скруглённая карточка-плитка от верха окна, шире контента (240px), без блока аккаунта; пункты с равным шагом; активный — подложка `accent_soft` + иконка/текст в акценте.
- Три блока (sidebar / Valuation / Parameters) — равные промежутки 20px; Valuation и Parameters на одном уровне (общий верх/низ).
- Тулбар: бренд слева, заголовок экрана, сегмент-контрол типов справа от заголовка; ниже — dropdown инструмента + акцентная кнопка Calculate. Подзаголовка под «Pricing» нет, поиск/Demo/Live нет.
- Valuation — скролл-контейнер (метрики → таблица платежей → таблица кривой) + **зафиксированный** футер (Market value + QTY слева от поля + «Add to portfolio»), низ футера скруглён по карточке.
- Parameters — **только параметры расчёта**; скролл появляется только если полей много.

---

## 3. Стратегия темизации

**v1 (этот переход): светлая тема — единственная активная.**

1. В `ui/theme.py` добавить `LIGHT` и `DARK` инстансы `ThemePalette`, расширив
   dataclass недостающими токенами (см. §2.1). Текущие значения → `DARK`.
2. Ввести активную тему: `PALETTE = LIGHT` (модульный алиас сохраняем — чтобы
   `from ui.theme import PALETTE` продолжал работать без правок импортов).
3. `WORKSTATION_STYLE` пересобрать из активного `PALETTE` (уже так и есть).
4. Тени и скруглённый клиппинг — через `QGraphicsDropShadowEffect` и контейнеры
   с `border-radius` (QSS тени Qt не поддерживает).

**Будущее (вне v1): рантайм-переключение темы.** Ввести `ThemeManager` с сигналом
`themeChanged`; компоненты читают токены через геттер, а не через захваченный на
импорте f-string. Помечается как отдельная задача, в этот переход не входит.

> Принцип: **имена токенов не меняем**, меняем значения и добавляем новые. Это
> минимизирует диффы по всему `ui/` и `app/panels/*`.

---

## 4. Карта соответствия «макет → компонент»

| Элемент макета | Существующее | Изменения |
|---|---|---|
| Sidebar-плитка | `GlobalNavigation` (shell) | в скруглённую карточку с тенью; бренд сверху; плоский список (без групп/поиска/аккаунта); активный пункт = `accent_soft` пилюля; равный шаг |
| Тулбар (бренд+заголовок+типы) | `WorkspaceHeaderBar` | убрать подзаголовок; добавить сегмент-контрол типов справа от заголовка |
| Сегмент-контрол типов | — (новый) | `SegmentedControl` (QButtonGroup checkable в скруглённом контейнере) |
| Карточка | `WorkspaceCard` / `WorkstationPanel` | белый фон, `rx16`, кромка 8%, drop-shadow effect |
| Статус-пилюли | `StatusChip`, `DataSourceChip` | перекрасить в light (amber/mint), радиус 6 |
| Метрики Valuation | `KpiCard` (не подходит) | новый `KeyValueGrid` (2 кол. label→value) вместо боксов |
| Таблицы платежей/кривой | `DenseTable` | light-стиль: без рамок, моно-числа, выравнивание вправо |
| Заголовки секций | `SectionLabel` | uppercase, letter-spacing, `txt3` |
| Кнопки Calculate/Add | `make_action(primary=True)` | акцентная заливка `accent`, белый текст |
| Провенанс/варнинг | `WarningBanner` | в эталоне свёрнут в строку провенанса; баннер оставить для состояний `Broken/Prototype` |
| Drawer контекста | `ContextDrawer` | в Pricing не используется (уже отключён) |

---

## 5. Поэтапный план (каждый этап = отдельный коммит)

### Этап 0 — Токены и базовые примитивы
**Файлы:** `ui/theme.py`, `ui/components.py`
- `ThemePalette`: добавить токены §2.1; создать `LIGHT`/`DARK`; `PALETTE = LIGHT`.
- Хелперы: `card_shadow(widget)` (QGraphicsDropShadowEffect), `apply_radius`.
- `WorkspaceCard`: белый фон, `rx16`, кромка 8%, тень.
- Обновить `status_style()`/`value_color()` под light.
**Тесты:** `tests/test_theme_light.py` — наличие токенов, контраст текст/фон ≥ AA для основных пар; smoke-импорт `WORKSTATION_STYLE`.

### Этап 1 — Оболочка (shell)
**Файлы:** `ui/shell.py`, `ui/layouts.py`
- `GlobalNavigation` → плитка-sidebar (240px, скругление, тень, бренд, плоский список, активный пункт, без аккаунта).
- `WorkspaceHeaderBar` → тулбар без подзаголовка + слот под сегмент-контрол типов.
- Светлый фон рабочей области; промежутки/отступы по §2.4 (равные 20px, выравнивание блоков).
- Новый `SegmentedControl` в `ui/components.py`.
**Тесты:** обновить `tests/test_workstation_navigation.py` (плоский список, отсутствие поиска/аккаунта, `not isHidden()` офскрин).

### Этап 2 — Pricing: карточка Valuation
**Файлы:** `app/panels/pricing_detail.py`, `ui/components.py`
- Контейнер карточки = `QScrollArea` (тело) + зафиксированный футер внутри одной скруглённой рамки; низ футера скруглён (контейнер с `border-radius`, прозрачный scroll-area).
- Тело: `VALUATION` + статус-пилюли (Approximation/MOEX OK), цена `44/700`, строка провенанса, делитель, `KeyValueGrid` метрик (YTM, Eff/Mod/Macaulay duration, Convexity, DV01, Z-/G-spread), таблица `CASHFLOW SCHEDULE` (Date/Coupon/Principal/DF/PV), таблица `DISCOUNT CURVE` (Tenor/Zero/DF).
- Футер: Market value (слева) + `QTY` (label слева от поля) + акцентная «Add to portfolio»; поле и кнопка выровнены и центрированы по вертикали.
- Скроллбар в light-стиле.
**Тесты:** `tests/test_pricing_workspace_ui.py` — наличие таблиц, футер не скроллится (вне области прокрутки), «Add to portfolio» добавляет позицию в `shared_portfolio()`.

### Этап 3 — Pricing: карточка Parameters
**Файлы:** `app/panels/pricing_detail.py`, `pricing_catalogue.py`
- Только поля расчёта (по `Product`/`curve_roles`): 2-колоночная сетка + полноширинные (Discount/Projection curve, Call schedule).
- Скролл включается только при переполнении (много полей у инструмента).
- Light-поля, подписи `txt2`.
**Тесты:** расширить проверки полей по нескольким продуктам (bond, frn, irs) — наличие нужных полей и кривых.

### Этап 4 — Полировка и состояния
**Файлы:** `ui/components.py`, `app/panels/pricing_detail.py`
- Состояния: loading (скелет), ошибка ввода (подсветка поля + сообщение), stale-данные (amber-строка), `Validated/Broken/Prototype` статусы.
- Focus/hover, табуляция, выравнивание по сетке 4px, проверка отступов §2.4.
**Тесты:** unit на рендер состояний (offscreen), отсутствие исключений.

### Этап 5 — Раскатка на остальные рабочие области
**Файлы:** `app/panels/dashboard_panel.py`, `portfolio_panel.py`, `risk_workspace.py`, `market_workspace.py`, `governance_workspace.py`, `analytics_workspace.py`
- Применить shell/карточки/токены; KPI-полоса и таблицы в light; единые отступы.
- Каждая область — отдельный коммит.
**Тесты:** соответствующие `test_*` офскрин-проверки видимости/состава.

### Этап 6 — Чистка и фиксация
- Убрать тёмные «зашитые» цвета из мигрированных экранов (grep по hex).
- Решение по легаси-калькуляторам (`option_panel.py` и пр.), вытесняемым хабом Pricing: пере-темизировать минимально или пометить deprecated.
- Прогнать полный `pytest`, обновить снапшоты/скриншоты.

---

## 6. Тестирование и приёмка

- Среда: `QT_QPA_PLATFORM=offscreen`; видимость проверять через `not isHidden()` (офскрин `isVisible()` ложно-false).
- Регресс: полный `pytest` (сейчас зелёный — поддерживать зелёным после каждого этапа).
- Опционально визуальный регресс: рендер виджета в PNG и сравнение с эталоном `design/pricing_v6_light.png` (порог по diff).
- **Definition of Done:** эталонный экран Pricing совпадает с `pricing_v6_light` по структуре/палитре; нет тёмных остатков на мигрированных экранах; все тесты зелёные; сервисный слой не затронут.

---

## 7. Риски и митигации

| Риск | Митигация |
|---|---|
| `PALETTE` зашит на импорте по всему `ui/` | имена токенов не меняем; только значения + новые токены; `PALETTE = LIGHT` |
| Тени/скруглённый клиппинг в Qt | `QGraphicsDropShadowEffect` + контейнеры с `border-radius`; футер в общей скруглённой рамке |
| Скролл + липкий футер | `QScrollArea` (тело) + отдельный футер-виджет в одной рамке карточки |
| Сегмент-контрол отсутствует | новый компонент `SegmentedControl` (переиспользуемый) |
| Регрессии в легаси-панелях | вне scope v1; темизируются на этапе 5/6 или помечаются deprecated |
| Контраст в светлой теме | проверка пар текст/фон на этапе 0 |

---

## 8. Порядок исполнения (резюме)

0 → 1 → 2 → 3 → 4 — доводят эталонный экран Pricing до `pricing_v6_light`.
5 → 6 — распространяют язык на остальные экраны и закрывают долги.
Каждый этап — атомарный коммит с прогоном `pytest`.
