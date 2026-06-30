"""Raw-data browser + data dictionary (Data Controls / dev section).

A read-only window onto the normalized market store for developers/admins — a
table browser and a field dictionary. Kept out of the user-facing Market Data
showcase. Only an allow-list of tables is exposed; rows are stringified so the
client can render any table uniformly.
"""

from __future__ import annotations

# Allow-list of browsable tables (matches the recommendations' Advanced/Raw list).
TABLES: list[str] = [
    "instrument_ref", "instrument_versions", "bond_schedule_versions",
    "bond_quotes", "equity_quotes", "fx_rates", "yield_curves",
    "curve_points", "vol_points", "option_quotes", "price_history", "bond_coupons",
    "bond_amortizations", "bond_offers", "commodity_quotes", "dividends",
    "time_series", "ingest_log",
    "ref_currencies", "ref_boards", "ref_sources",
    "market_data_validation_reports",
]

# Curated business meanings for common fields (best-effort; unknown → "").
_MEANING: dict[str, str] = {
    "snapshot_id": "Идентификатор снапшота рыночных данных",
    "secid": "Код инструмента (MOEX SECID)",
    "isin": "ISIN инструмента",
    "issuer_ru": "Эмитент (рус.)",
    "name_ru": "Наименование (рус.)",
    "category": "Класс инструмента",
    "board": "Режим торгов (board)",
    "currency": "Валюта",
    "last": "Последняя цена",
    "prevprice": "Цена предыдущего закрытия",
    "change_pct": "Изменение за день, %",
    "as_of": "Дата актуальности",
    "dt": "Дата",
    "trade_date": "Дата торгов",
    "open": "Цена открытия", "high": "Максимум", "low": "Минимум", "close": "Закрытие",
    "volume": "Объём", "value": "Оборот", "numtrades": "Число сделок",
    "yield": "Доходность", "wap": "Средневзвешенная цена",
    "pair": "Валютная пара", "rate": "Курс", "source": "Источник", "trade_time": "Время сделки",
    "curve_id": "Идентификатор кривой", "tenor": "Срок (тенор)", "zero": "Zero-ставка",
    "discount": "Дисконт-фактор", "factor_id": "Идентификатор риск-фактора", "kind": "Тип ряда",
    "underlying": "Базовый актив", "expiry": "Экспирация", "strike": "Страйк", "iv": "Implied vol",
    "opt_type": "Тип опциона (C/P)", "oi": "Открытый интерес", "central_strike": "Центральный страйк",
    "asset": "Базовый актив (commodity)", "settle": "Расчётная цена", "open_interest": "Открытый интерес",
    "coupon": "Купон", "amount": "Сумма", "amortization": "Амортизация", "offer": "Оферта",
    "registry_date": "Дата фиксации реестра", "endpoint": "Точка загрузки (ingest)",
    "status": "Статус", "rows": "Загружено строк", "error": "Текст ошибки",
    "started_at": "Старт", "finished_at": "Финиш",
    "code": "Код", "name": "Наименование", "market": "Рынок",
    "version": "Версия", "valid_from": "Действует с", "valid_to": "Действует по",
    "payload_hash": "Хеш содержимого", "n_coupons": "Купонов", "n_amort": "Амортизаций",
    "n_offers": "Оферт",
}


def _stringify(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def tables(ctx) -> dict:
    db = ctx.market_db
    if db is None:
        return {"tables": []}
    return {"tables": [{"name": t, "rows": db.table_count(t)} for t in TABLES]}


def rows(ctx, table: str, limit: int = 200) -> dict:
    db = ctx.market_db
    if db is None or table not in TABLES:
        return {"table": table, "columns": [], "rows": [], "count": 0, "shown": 0}
    cols = [c["name"] for c in db.table_columns(table)]
    raw = db.table_rows(table, min(max(int(limit), 1), 1000))
    out = [[_stringify(r.get(c)) for c in cols] for r in raw]
    return {"table": table, "columns": cols, "rows": out,
            "count": db.table_count(table), "shown": len(out)}


def dictionary(ctx) -> dict:
    db = ctx.market_db
    if db is None:
        return {"tables": []}
    out = []
    for t in TABLES:
        fields = [{"name": c["name"], "type": c["type"], "meaning": _MEANING.get(c["name"], "")}
                  for c in db.table_columns(t)]
        out.append({"table": t, "fields": fields})
    return {"tables": out}
