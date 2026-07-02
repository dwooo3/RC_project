# PLAN A — дефекты кода и полировка (Market Data)

> **СТАТУС: ✅ ВЫПОЛНЕНО 2026-07-02** — коммиты `9f21e32` (A1), `13c0960` (A2+A9),
> `3487428` (A3+A10), `5333ab5` (A4), `c6af9c2` (A5–A8). DoD проверен на экране:
> индексы честные (5 шт., RVI/RUSFAR добавлены, MOEX-акция убрана), FX без LIVE,
> свитч вкладок без рефетча (1 запрос списка на сессию), Yield скрыт при
> интрадее, объём скрыт у индексов, зум переживает toggles. Отложено в v2:
> маппинг USDRUB→USD000UTSTOM для настоящего FX-интрадея.

Инструкции для исполнителя (мне же). Контекст и номера пунктов — в
[MARKET_DATA_AUDIT_2026_07.md](MARKET_DATA_AUDIT_2026_07.md). Порядок ниже =
порядок выполнения; каждый блок — отдельный commit с тестом/скрин-проверкой.

## A1. Select stale-write guard (P0)

`macapp/Sources/RiskCalc/MarketEntityView.swift`, `MarketEntityVM`:

- В `select(_ secid:)` после КАЖДОГО `await` проверять актуальность:
  ```swift
  func select(_ secid: String) async {
      selectedID = secid
      loadingDetail = true
      let e = try? await client.mdInstrument(category: category, secid: secid)
      guard selectedID == secid else { return }          // клик ушёл дальше
      ...
      await loadBars(secid)
      guard selectedID == secid else { return }
      entity = e
      loadingDetail = false
  }
  ```
- `loadBars(_ secid:)` — тоже guard перед присвоением `bars`.
- `changeRange`/`changeInterval` создают неструктурированные `Task {}` — держать
  один `loadTask: Task<Void, Never>?`, отменять предыдущий (`loadTask?.cancel()`),
  внутри уважать `Task.isCancelled`.
- Проверка: быстро прощёлкать 5 бумаг — заголовок/график/день всегда одной бумаги.

## A2. Честные индексы (P0)

`api/market_entity.py::_list_indices`:

- Убрать из аллоулиста `MOEX` (это акция биржи из equity-бэкфилла).
- Явный реестр индексов с человеческими именами:
  ```python
  _INDICES = {"IMOEX": "Индекс МосБиржи", "RGBI": "Индекс гособлигаций",
              "RVI": "Индекс волатильности", "RUCBTRNS": "Индекс корп. облигаций",
              "RUSFAR": "RUSFAR (ставка)", "RTSI": "Индекс РТС"}
  ```
  Выдавать только те, у кого есть точки; `issuer_ru` = имя из реестра.
- Перф (аудит P2): не читать всю серию — добавить в `MarketDataDB`
  `last_two_points(factor_id)` c `ORDER BY dt DESC LIMIT 2` (+ индекс уже есть).
- Тест: `_list_indices` не содержит MOEX; содержит RVI при наличии данных;
  change_pct считается из двух последних точек.

## A3. Интрадей-гейтинг per-category (P1)

- Swift: в `MarketEntityVM` добавить `var supportsIntraday: Bool` —
  `["bonds","shares","equities","futures","forts","commodities","indices"].contains(...)`
  фактически: category ∈ {bonds, equities, futures, options?, commodities, indices};
  **fx — false** (CBR-фиксинги не торгуются на selt под нашими secid).
  В `rangeBar` рисовать пикер интервалов только при `supportsIntraday`.
- `api/intraday.py`: принять `market` как есть, но на неизвестный/`fx` возвращать
  `{"points": [], "count": 0, "unsupported": true}` — клиент не должен полировать.
- Индексы: уже работает (`stock/index`, проверено IMOEX/RGBI 60м) — просто
  убедиться, что Indices-таб получает пикер.
- Опционально (v2): маппинг USDRUB→USD000UTSTOM (board CETS) для настоящего
  FX-интрадея — отдельной задачей, вместе с A2-стилем реестром пар.

## A4. Кэш VM между свитчами под-вкладок (P1)

`macapp/Sources/RiskCalc/MarketScreen.swift`:

- Вместо `MarketEntityView(category: instrument).id(instrument)` держать словарь
  VM в родителе:
  ```swift
  @State private var entityVMs: [String: MarketEntityVM] = [:]
  private func vmFor(_ cat: String) -> MarketEntityVM {
      if let vm = entityVMs[cat] { return vm }
      let vm = MarketEntityVM(category: cat); entityVMs[cat] = vm; return vm
  }
  // content: MarketEntityView(vm: vmFor(instrument))
  ```
  `MarketEntityView` принимает готовый VM (`init(vm:)`), `.id()` убрать.
- Удалить мёртвый `onChange(of: category)` в `MarketEntityView` (category — let).
- Проверка: свитч Bonds→Equities→Bonds не дёргает `/md/list/bonds` повторно
  (смотреть лог моста), выбранная бумага и зум сохранены.

## A5. Сохранение вьюпорта чарта на toggle SMA/Log (P1)

`TradingChart.swift` (JS `render`):

- Перед пересозданием серий сохранить видимый диапазон, после `setData` —
  восстановить, `fitContent()` звать только при смене САМОЙ серии (первый рендер
  или новый инструмент/интервал):
  ```js
  const keepView = cfg.keepView === true;
  const range = keepView ? chart.timeScale().getVisibleLogicalRange() : null;
  ...
  if (range) chart.timeScale().setVisibleLogicalRange(range);
  else chart.timeScale().fitContent();
  ```
- Swift: в `configJSON()` добавить `keepView` — true, когда staticSig отличается
  ТОЛЬКО флагами sma/log (сохранить в координаторе предыдущие bars-идентичность:
  first/last/count совпали → keepView).

## A6. Скрыть Yield при интрадее (P2)

`TradingChart.swift` controls: если `bars.last?.ts != nil` — не включать `.yield`
в набор режимов (и если текущий mode == .yield, переключить на .candle).

## A7. Empty-state чарта (P2)

JS `render`: при `bars.length === 0` показывать в `#legend` (или отдельном div по
центру) «Нет данных — торги закрыты или источник недоступен». Убирать при
непустом рендере.

## A8. Прятать объём без данных (P2)

JS `render`: `const hasVol = bars.some(b => (b.volume ?? 0) > 0);` — histogram
создавать только при hasVol.

## A9. rawdata детерминизм (P2)

`market_data_db.table_rows`: добавить `ORDER BY rowid` (и `DESC` для
`ingest_log`, чтобы виден был хвост). `api/rawdata.rows` прокинуть `order`.

## A10. intraday: категория → рынок на бэке (P2)

`api/intraday.py`: принимать `category` (bonds/equities/…) и маппить в
engine/market на сервере (сейчас Swift шлёт готовый market — второй потребитель
API может ошибиться). Обратная совместимость: `market=` оставить.

## Definition of done (фаза 1)
- pytest: новые тесты A2/A3/A9 зелёные, полный md-набор зелёный.
- Скрин-чек: (1) быстрые клики — без рассинхрона; (2) Indices = IMOEX/RGBI/RVI/
  RUCBTRNS/RUSFAR (+RTSI если появится), интрадей работает; (3) FX без LIVE;
  (4) свитч вкладок мгновенный без рефетча; (5) зум живёт при SMA/Log;
  (6) выходной день — на графике текст, а не пустота.
