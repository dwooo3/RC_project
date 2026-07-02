# PLAN B — включить мощь данных (Market Data)

Всё ниже НЕ требует новых источников: данные уже в `market_data.sqlite`, движки
уже валидированы. Только выдача. Контекст — в
[MARKET_DATA_AUDIT_2026_07.md](MARKET_DATA_AUDIT_2026_07.md) §4.

## B1. Bonds: YTM в списке + сортировка (данные: bond_quotes 100%)

- `api/market_entity.list_instruments("bonds")`: JOIN последнего снапшота
  `bond_quotes` по `snapshot_key` → добавить `ytm` (и `wap`) в строку списка.
  Getter: `db.get_bond_quotes_map(snapshot_id) -> {secid: {ytm, wap_price, accruedint}}`.
- Swift `MDListItem`: `ytm: Double?`; строка списка облигаций — под ценой
  вторая колонка `YTM 15,95%` (вместо ISIN? нет — ISIN оставить, YTM справа под Δ%).
- Сортировка списка: меню «Сортировка: Имя | Цена | Δ% | YTM» в строке фильтров
  (client-side, `filtered` учитывает).
- Деталь: в dayStats уже есть Yield — добавить Accrued (НКД) и WAP из quote.

## B2. Bonds: G-spread колонка (данные: GCURVE в снапшоте + mat_date)

- Бэкенд: в `list_instruments("bonds")` для каждой бумаги с ytm и mat_date:
  `g = ytm - zero_gcurve(T_mat)*100` (проценты; zero — линейная интерполяция по
  `curve_points` GCURVE snapshot'а; загрузить кривую ОДИН раз на запрос).
  Поле `g_spread_bp` (в б.п., округлить до 1).
- Swift: колонка в списке (или в детали + карточке — если строка перегружена,
  в списке только YTM, G-spread в детали «Ключевые параметры»).
- Тест: синтетическая кривая + бумага → спред совпадает с ручным расчётом.

## B3. Futures: кривая фьючерсов в карточке (данные: chain готов)

- В `InstrumentCard` (category == futures) уже есть таблица chain — добавить над
  ней line-chart: X = last_trade_date, Y = last (только is_active + будущие),
  Swift Charts достаточно (это не таймсерия — TradingChart не нужен).
- Подпись: контанго/бэквордация (знак наклона первый→последний).
- Данные уже в `MDChainContract` — чисто Swift-задача.

## B4. → уехало в PLAN A (A2): честные индексы RVI/RUCBTRNS/RUSFAR.

## B5. Equities: дивидендная доходность (данные: dividends, 181 эмитент)

- Бэкенд: `db.dividend_yield_map(snapshot)`: сумма `dividends.value` за последние
  365 дней по registry_date / last price → `div_yield_pct` в `list_instruments("equities")`
  и в `instrument()` (деталь).
- Swift: в строке списка акций — `Див. 8,4%` мелким под Δ%; в детали — строка
  в keyInfo. В карточке таблица дивидендов уже есть.

## B6. Стат-строка инструмента (данные: price_history 5 лет)

- Бэкенд: `market_entity.instrument()` дополнить блоком `stats` (по
  `price_history` за 365д): `hi_52w, lo_52w, rv_30d (annualized, %), max_dd_pct`.
  Один SQL на бумагу + numpy на 250 точек — дёшево.
- Swift: строка чипов под dayStats: «52w 92,10–108,30 · RV30 6,8% · DD −12,4%».

## B7. RV vs IV (уникальная фича; данные: B6 + vol surface)

- Для 19 базовых активов опционов (underlying → фьючерс secid активного
  контракта): сравнить `rv_30d` фьючерса с ATM IV ближайшей экспирации
  (из `api/volsurface.surface` — atm_iv первой экспирации).
- Выдача: в Volatility-табе, шапка деталей underlying:
  «ATM IV 11,7% · RV30 8,9% → IV премия +2,8 п.п.» (цвет: IV>RV — warning tint).
- Бэкенд: `volsurface.surface()` уже кэширован — добавить в результат
  `rv_30d` (посчитать из price_history секьюрити активного фьючерса).

## B8. Skew-аналитика для всех активов (данные: SABR у 19 активов)

- `rr_bf_25delta` работает на любом смайле, не только FX. В
  `api/volsurface.surface()` для каждой экспирации добавить `rr25`, `bf25`
  (из уже посчитанного SABR: σ(K25c)−σ(K25p), (σ25c+σ25p)/2−σATM; K25 через
  существующий `_strike_for_delta`).
- Swift: в таблице «ATM срочная структура» → расширить карточку: три линии
  ATM/RR/BF (переиспользовать вид OTC-графика) для ЛЮБОГО актива; OTC-таб
  оставить как есть (FX-котировочная семантика).
- Ценность: skew-мониторинг GOLD/RTS/SBRF — то, чего нет в бесплатных терминалах.

## B9. → уехало в PLAN A (A3): интрадей для Indices.

## Definition of done (фаза 2)
- Каждый пункт: бэкенд-тест (pytest, fixtures без сети) + скрин.
- Список облигаций: YTM виден, сортировка по YTM работает, G-spread в детали.
- Карточка фьючерса: кривая контанго Si.
- Акции: див-доходность у ≥100 бумаг.
- Деталь: стат-строка 52w/RV/DD.
- Volatility: RV vs IV бейдж + RR/BF термструктура у не-FX активов.
