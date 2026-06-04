# PROMPT — Интеграция рыночных данных MOEX ISS → локальная БД → прайсинг/риск

**Назначение:** готовый промт для агента-исполнителя (Codex/Claude). Описывает интеграцию,
валидацию и использование рыночных данных MOEX ISS поверх существующей архитектуры RiskCalc.
Данные хранятся в локальной БД (ещё не создана). Реализация — отдельными логическими коммитами
по фазам.

**Источник по ISS:** справочник https://iss.moex.com/iss/reference/ (эндпоинты ниже выверены
обращением к API; пометка ✅ — подтверждён, ⚠️ — уточнить/иной источник).

---

## 0. Контекст (на чём строим, НЕ переписывать)

Проект уже содержит:
- `domain/market_data.py`: `MarketDataSnapshot`, `MarketDataSource` (`DEMO/MANUAL/MOEX/BLOOMBERG/REUTERS`), `MarketDataStore` (in-memory).
- `services/market_data_service.py`: `MarketDataService` владеет снапшотами; `MoexProvider(ProviderInterface)` — **заглушка** (`load_snapshot` → `NotImplementedError`); есть `snapshot_lineage`, `manual_snapshot`, demo-фабрики.
- `curves/yield_curve.py`: `YieldCurve`, `NSCurve` (Nelson-Siegel), `SvenssonCurve`; валидация DF.
- `curves/russia.py`: DEMO OFZ/RUONIA/CBR/корпоративные кривые (помечены `MarketDataSource.DEMO`).
- `instruments/fixed_income.py`: `fixed_bond`, `price_ofz`, `irs` (single-curve), `frn`, `cap_floor`.
- `risk/var.py`: VaR требует временные ряды доходностей риск-факторов.

**Требования:** сохранить DEMO-fallback и существующие API; не менять количественные модели;
обеспечить воспроизводимость расчётов через snapshot lineage + audit.

---

## 1. Источник: MOEX ISS API

- База: `https://iss.moex.com/iss/...`. Публичный (без авторизации для EOD/задержанных данных; интрадей задержан ~15 мин).
- Форматы: `.json`/`.csv`/`.xml`. Всегда: `iss.meta=off`, `iss.only=<block>` (минимизация payload), `lang=en`.
- Пагинация: курсорная — блок `*.cursor` (INDEX/TOTAL/PAGESIZE), параметр `start`; выкачивать постранично до исчерпания.
- Вежливость: rate-limit (≤ ~5 rps), retry с backoff, таймауты, кэш по (URL, дата), User-Agent.
- Ответ ISS — набор именованных блоков (`securities`, `marketdata`, `history`, `yearyields`, `params`, …); парсить по `columns` + `data`.

---

## 2. Карта потребностей данных по модулям → эндпоинты ISS

| Модуль / прайсинг | Нужные данные | Эндпоинт ISS |
|---|---|---|
| **Bond / OFZ** (`fixed_bond`, `price_ofz`) | risk-free дисконт-кривая RUB (КБД), статика облигации, НКД, рыночные цены/YTM | ✅ G-curve: `/iss/engines/stock/zcyc.json` → `yearyields(period,value)` + `params(B1,B2,B3,T1)` (NSS); ✅ облигации: `/iss/engines/stock/markets/bonds/securities.json` (доска **TQOB** для ОФЗ) |
| **IRS / OIS** (`irs`, `ois`) | RUONIA OIS-кривая (для будущего dual-curve), своп-ставки | ⚠️ RUONIA-фиксинг **НЕ на ISS** → источник **ЦБ РФ** (cbr.ru); на MOEX только фьючерсы RUONIA (`secid` RFxx) + денежный рынок |
| **FRN** | проекционная кривая (RUONIA/ключевая ставка), история сбросов | ⚠️ RUONIA/ключевая → ЦБ РФ; кривая из КБД/денежного рынка |
| **Vanilla / Equity options** (`bsm`) | спот акции, risk-free (короткий конец КБД/ключевая ставка), див. доходность, implied vol | ✅ спот: `/iss/engines/stock/markets/shares/securities.json` (доска **TQBR**); ⚠️ vol: опционы FORTS (`engine=futures, market=options`); дивиденды — оценка |
| **FX options / forwards** (`garman_kohlhagen`) | спот FX, ставки RUB/USD/EUR/CNY, FX-фиксинги | ✅ `/iss/statistics/engines/currency/markets/selt/rates.json` (USD/RUB, EUR/RUB, CNY/RUB, золото, CBRF_*); ✅ фиксинги: `/iss/statistics/engines/currency/markets/fixing.json` |
| **Credit (CDS/CLN)** | issuer/sector спреды над ОФЗ, recovery | ⚠️ вывести из корпоблигаций (`bonds/securities` по эмитенту/сектору) минус КБД; recovery — допущение |
| **Structured** | спот + вол + корреляция + кривая | комбинация выше + история для корреляций |
| **VaR/ES, Stress, Backtesting** (`risk/var`) | временные ряды риск-факторов (цены акций, FX, доходности, индексы) | ✅ история: `/iss/history/engines/[engine]/markets/[market]/securities/[secid].json`; ✅ свечи: `/iss/engines/[engine]/markets/[market]/securities/[secid]/candles.json`; ✅ доходности: `/iss/history/.../yields[/secid].json` |
| **Index / vol benchmark** | IMOEX, RTSI, RVI (волатильность), отраслевые | ⚠️ значения индекса — через index market/history `/iss/history/engines/stock/markets/index/securities/IMOEX.json` (НЕ `/analytics` — там состав) |
| **Portfolio** | всё вышеперечисленное + FX для пересчёта в базовую валюту | как выше |

**Поля облигаций (подтверждены):** `COUPONPERCENT, COUPONVALUE, COUPONPERIOD, NEXTCOUPON,
MATDATE, OFFERDATE, PUTOPTIONDATE, CALLOPTIONDATE, FACEVALUE, FACEUNIT, CURRENCYID, ACCRUEDINT,
LOTSIZE, MINSTEP, LISTLEVEL, ISSUESIZE, YIELDATPREVWAPRICE, PREVPRICE, PREVWAPRICE`.

---

## 3. Локальная БД (создать; SQLite → позже Postgres)

Схема ложится на `MarketDataSnapshot`/`MarketDataStore` и обеспечивает воспроизводимость:

- `instruments` — `secid, isin, board, type, currency, facevalue, coupon_percent, coupon_period, next_coupon, mat_date, offer_date, lot_size, list_level, issuer, sector, static_json`.
- `market_data_snapshots` — `snapshot_id (PK), valuation_date, source, quality, created_at, fetch_ts, iss_request_urls(json), metadata(json)`.
- `yield_curves` — `snapshot_id, curve_id (GCURVE_RUB/RUONIA/CORP_x), method, nss_params(json: B1,B2,B3,T1), as_of`.
- `curve_points` — `snapshot_id, curve_id, tenor, zero_rate, discount_factor`.
- `fx_rates` — `snapshot_id, pair, rate, source(MOEX/CBR), trade_time`.
- `bond_quotes` — `snapshot_id, secid, clean_price, dirty_price, wap_price, accruedint, ytm, volume, board`.
- `equity_quotes` — `snapshot_id, secid, last, prevprice, board, volume`.
- `index_values` — `snapshot_id, indexid, value, trade_date`.
- `time_series` — `secid/factor_id, date, value, kind(price/yield/return)` (долгая история для VaR/бэктеста; отдельно от снапшотов).
- `vol_points` — `snapshot_id, underlying, expiry, strike, iv` (FORTS; может быть пусто на старте).
- `ingest_log` — `run_id, endpoint, status, rows, started_at, finished_at, error`.

Ключи/индексы: уникальность `(snapshot_id, curve_id, tenor)`, `(snapshot_id, secid)`; индекс `(secid, date)` в `time_series`.

---

## 4. Слой интеграции (новый код поверх существующего)

1. **ISS-клиент** (`infra/moex_iss/client.py`): низкоуровневые GET с курсорной пагинацией, retry, кэш, парсинг блоков → dict/dataclass. Без бизнес-логики.
2. **Ingestion/ETL** (`infra/moex_iss/ingest.py`): `ingest_gcurve()`, `ingest_bonds(board=TQOB)`, `ingest_fx()`, `ingest_equities(board=TQBR)`, `ingest_index([IMOEX,RVI])`, `ingest_history(secids, from, till)`. Инкрементальная загрузка по дате; запись в БД; лог в `ingest_log`.
3. **Реализовать `MoexProvider.load_snapshot(valuation_date)`** в `services/market_data_service.py`: собрать из БД консистентный `MarketDataSnapshot` (`source=MarketDataSource.MOEX`), заполнить `metadata` (ISS URLs, tradedate, fetch_ts), вычислить `quality` (§5). Если данных нет — понятная ошибка; `MarketDataService` делает **fallback на DEMO** с warning.
4. **Кривые из КБД:** `params(B1,B2,B3,T1)` → существующий `NSCurve`/`SvenssonCurve`, либо `curve_points` (`yearyields`) → `YieldCurve`. ОФЗ/RUB risk-free = `GCURVE_RUB`.
5. **RUONIA/ключевая ставка из ЦБ РФ** (мини-провайдер `cbr`): фиксинга на ISS нет — забирать с cbr.ru (или вручную), помечать `source`. На старте допустимо оставить RUONIA как DEMO с явным warning.

---

## 5. Валидация (data quality → `MarketDataSnapshot.quality`)

Жёсткие проверки на ингесте и при сборке снапшота:
- **Свежесть:** `TRADEDATE`/`as_of` == `valuation_date` (или в пределах N бизнес-дней); иначе `quality="STALE"` + warning.
- **Полнота:** обязательные поля присутствуют (купон/погашение/номинал для облигаций; ≥ минимальный набор тенетов кривой).
- **Кривая:** DF строго положительны и монотонно убывают; нет NaN/inf; форварды разумны (переиспользовать валидатор `YieldCurve`); NSS-параметры в адекватных диапазонах.
- **FX:** кросс-консистентность (USD/RUB, EUR/RUB, EUR/USD в пределах допуска); положительность.
- **Ликвидность/доска:** фильтр по доске (TQOB/TQBR/CETS), `VOLUME>0` / `LISTLEVEL<=2` для отсева неликвида.
- **Валюта:** `FACEUNIT/CURRENCYID` соответствуют ожидаемой.
- Итог: `quality ∈ {OK, STALE, PARTIAL, REJECTED}` + список warnings в снапшоте; `REJECTED` блокирует production-использование (§6).

---

## 6. Использование в модулях (через сервис, без обхода)

- Данные — **только** через `MarketDataService` (`get_curve`, `get_fx`, `get_vol`, `get_snapshot`); никакого прямого построения объектов рынка в UI/прайсерах.
- **Production gating:** снапшот `source=MOEX` и `quality=OK` → допускается в production; `DEMO/MANUAL` или `quality≠OK` → результат несёт warning «Demo/Manual/Stale market data. Not production valuation.» (механизм уже есть в сервисах).
- **Воспроизводимость:** снапшот хранит `valuation_date`, `source`, ISS request URLs, `fetch_ts`; audit (`AuditRecord`/`inputs_hash`) фиксирует `snapshot_id` → расчёт восстановим из БД.
- **Fallback:** при отсутствии/недоступности ISS — DEMO-кривые из `curves/russia.py` с предупреждением (не падать).
- Заменить вызовы DEMO-фабрик в боевых путях (bond/OFZ, FX) на снапшот из БД, оставив DEMO резервом.

---

## 7. Тесты

- ISS-клиент: парсинг блоков (фикстуры реальных JSON; без сети в CI), курсорная пагинация, retry.
- ETL→БД: идемпотентность загрузки, инкремент по дате.
- Сборка `MarketDataSnapshot` из БД: поля, lineage, `quality`.
- Валидация: каждое правило (stale/incomplete/curve-monotonic/fx-cross/liquidity) — позитив/негатив.
- Repricing из КБД: ОФЗ на `GCURVE_RUB` ≈ рыночной `YIELDATPREVWAPRICE` в пределах допуска.
- Production gating: MOEX/OK → без warning; DEMO/STALE → warning; REJECTED → блок.
- Fallback на DEMO при пустой БД.

---

## 8. Поэтапный план

1. **Phase A:** ISS-клиент + БД-схема + `ingest_gcurve` + `ingest_fx`. MOEX-снапшот кривой RUB и FX; валидация; wire bond/OFZ + FX forward на снапшот; DEMO-fallback.
2. **Phase B:** облигации (TQOB) + история доходностей; калибровка/спреды; корпоративные кривые (issuer/sector).
3. **Phase C:** time_series (equities TQBR, индексы) → подача в VaR/бэктест/стресс.
4. **Phase D:** ЦБ РФ RUONIA/ключевая ставка; FORTS-опционы → vol-поверхность (для dual-curve/опционов).
5. **Phase E:** SQLite → Postgres (та же схема); фоновые джобы ингеста; расписание EOD.

---

## 9. Ограничения и допущения (зафиксировать честно)

- RUONIA-фиксинг и ключевая ставка — **не из MOEX ISS**, а из ЦБ РФ; до интеграции остаются DEMO с warning.
- Полноценные vol-поверхности (equity/FX) ограничены доступностью опционов FORTS; на старте — manual/derived с пометкой.
- CDS-рынка на MOEX нет → кредитные спреды выводятся из корпоблигаций (аппроксимация).
- Интрадей задержан ~15 мин; для valuation использовать EOD.
- Эндпоинты, помеченные ⚠️, исполнитель обязан перепроверить перед реализацией.
