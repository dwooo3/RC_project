# Pricing_new · Design QA

## Артефакты и состояние

- Source visual truth: `/Users/dmitriykiselev/Downloads/IMG_1652.PNG`.
- Роль source: референс принципа Calypso — плотная параметрическая сетка и несколько сделок рядом. Это не pixel-perfect цель: пользователь прямо потребовал другую реализацию в дизайн-системе RiskCalc.
- Implementation screenshot: `design-qa/pricing-new-final.png`.
- Full-view comparison: `design-qa/pricing-new-comparison.png`.
- Focused comparison: `design-qa/pricing-new-focus-comparison.png`.
- Post-fix evidence/risk/history state: `design-qa/pricing-new-evidence-final.png`.
- Viewport: native macOS window, 1161 × 768 px, light theme, sidebar visible.
- State: `Pricing_new`, FO environment, restored immutable run with three RUB legs — two European options/Black–Scholes and one version-pinned custom Phoenix — plus typed aggregate PV, per-position outputs and Greek chart.

## Findings

Actionable P0/P1/P2 findings в финальной сборке отсутствуют.

- [Accepted] Информационная архитектура и layout. Реализация сохраняет главный принцип референса: сделки являются соседними колонками с product/pricer/model/contract/market inputs. При 1–5 позициях используется один worksheet и горизонтальный scroll, а результаты, риск и журнал остаются ниже на той же поверхности. Постоянные controls не скрыты.
- [Accepted] Typography. Используется системная macOS/SF-типографика и иерархия RiskCalc, а не табличная типографика Calypso. После исправлений title, snapshot и labels не разваливаются на вертикальные строки и не пересекаются.
- [Accepted] Spacing and rhythm. Header занимает две компактные строки; три legs видны как единая сетка. Колонки имеют стабильную ширину 324 pt, поэтому третья колонка частично продолжается за край узкого окна и доступна ожидаемым горизонтальным scroll — это намеренное поведение для 1–5 legs.
- [Accepted] Colors and tokens. Нейтральные glass/card surfaces, зелёные validated/market states, amber capability gates и фиолетовые position markers соответствуют существующей дизайн-системе RiskCalc. Яркая раскраска ячеек Calypso намеренно не переносилась.
- [Accepted] Image and icon fidelity. В прикладном экране нет продуктовых raster assets, которые требовалось бы копировать. Использованы штатные SF Symbols в одном стиле; screenshot реализации резкий, без растяжения и артефактов.
- [Accepted] Copy and content. Product, pricer, model, market/contract groups, immutable snapshot, aggregate PV, Greek outputs, risk capability и run hash читаются непосредственно на экране. Смешение русского языка с общепринятыми desk-терминами (`PV`, `Greeks`, `custom`, `full reprice`) соответствует остальному RiskCalc.
- [Accepted] Accessibility and states. Основные controls доступны через macOS accessibility tree; проверены enabled/disabled, stale inputs, successful pricing, risk result, risk-blocked capability и replay states. Результат не подменяет unsupported risk частичным числом.

## Full-view comparison evidence

`design-qa/pricing-new-comparison.png` подтверждает сохранение целевого принципа source: высокая плотность параметров, соседние сделки и минимальное число переходов. Визуальные отличия — sidebar, карточные surfaces, семантические status chips и отдельные result/risk blocks — являются согласованной адаптацией, а не drift от требования.

## Focused region comparison evidence

`design-qa/pricing-new-focus-comparison.png` увеличивает ключевую область: header и product/pricer/contract/market grid для трёх legs. Focused comparison необходим, потому что подписи, alignment и плотность controls слишком малы для уверенной проверки в полном кадре. В финальном crop нет наложений, вертикального побуквенного переноса или потери core controls.

## Comparison history

1. [P1, fixed] Первый native capture показал, что `Pricing_new` сжимался до вертикального побуквенного переноса в однострочном header. Header переведён в устойчивую двухстрочную компоновку; title получил `lineLimit(1)` и фиксированный intrinsic width. Post-fix evidence: `design-qa/pricing-new-final.png`.
2. [P2, fixed] После восстановления run длинный snapshot chip сжимался в узкую вертикальную колонку справа. Chip перенесён в action row и зафиксирован через `fixedSize()`. Post-fix evidence: `design-qa/pricing-new-final.png` и focused comparison.
3. [P2, fixed] Evidence label показывал literal `(evidenceLegs.count) priced legs`. Исправлена Swift interpolation; post-fix state показывает `3 priced legs` в `design-qa/pricing-new-evidence-final.png`.

## Primary interactions tested

- переход в `Pricing_new` и загрузка catalogue/environments/history;
- создание named run, общий price-and-save и immutable replay;
- добавление второй позиции и восстановление трёхпозиционного run;
- aggregate PV и per-position metrics/Greek chart;
- historical full-reprice VaR/ES для поддерживаемого book;
- открытие embedded custom builder, обязательные причины manual overrides, attach version/hash-pinned Phoenix и смешанный расчёт 3/3;
- currency gate: без явной валюты custom leg неттинг блокируется; после `RUB` aggregate PV рассчитывается;
- custom risk capability fail-closed с явным `product_not_repriceable`, без ложного частичного VaR.

## Runtime errors checked

Это native SwiftUI app, поэтому browser console неприменима. Проверены accessibility state и локальные FastAPI bridge logs: используемые `/health`, catalogue, environments, Pricing_new price/risk/capability/run/custom endpoints отвечали `200 OK`; traceback и error overlay отсутствовали.

## Follow-up polish

- [P3] При желании можно унифицировать русско-английские подписи, но desk terminology сейчас последовательна и не мешает задаче.
- [P3] Для очень широкого монитора можно предложить user-selectable compact column width; текущая ширина лучше сохраняет читаемость сложных contract fields.

final result: passed
