"""Rating refresh script (ответ на В3 отчёта 2026-07).

Проверяет свежесть рейтингов эмитентов и обновляет их:

    /usr/local/bin/python3.14 scripts/update_ratings.py            # csv -> DB + отчёт
    /usr/local/bin/python3.14 scripts/update_ratings.py --fetch    # + попытка HTTP

Источник правды — data/ratings_manual.csv (issuer_ru, agency, rating,
outlook, rating_date). У АКРА и Эксперт РА НЕТ публичного machine-readable
API; --fetch пробует их публичные страницы поиска и честно сообщает, если
формат недоступен/изменился — тогда обновите CSV вручную с сайтов
acra-ratings.ru / raexpert.ru.

Recovery rate агентства не публикуют — используется базовая шкала по
рейтинговой корзине (infra/ratings.BASELINE_RECOVERY), это явное допущение.
"""

from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infra import ratings  # noqa: E402

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ratings_manual.csv")


def _conn():
    from api.context import CONTEXT
    db = CONTEXT.market_db
    if db is None:
        raise SystemExit("market DB недоступна — нужен data/market_data.sqlite")
    return db.conn


def load_csv(conn) -> int:
    n = 0
    with open(CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not (row.get("issuer_ru") and row.get("rating")):
                continue
            ratings.upsert(conn, row["issuer_ru"].strip(), row.get("agency", "").strip(),
                           row["rating"].strip(), row.get("outlook", "").strip(),
                           row.get("rating_date", "").strip())
            n += 1
    return n


def try_fetch(conn) -> None:
    """Best-effort HTTP refresh. Обе публичные выдачи — динамические сайты без
    стабильного JSON-контракта, поэтому любой сбой не фатален."""
    import urllib.request

    from infra.certs import market_data_ssl_context as ssl_context  # certifi-based

    probes = {
        "АКРА": "https://www.acra-ratings.ru/ratings/issuers/",
        "Эксперт РА": "https://raexpert.ru/database/companies/",
    }
    for agency, url in probes.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RiskCalc/1.0"})
            with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as r:
                ok = r.status == 200
            print(f"  {agency}: страница доступна ({url})" if ok else
                  f"  {agency}: HTTP {r.status}")
            print(f"    ⚠ автоматический парсинг рейтингов не реализован — "
                  f"стабильного API нет; обновите data/ratings_manual.csv вручную")
        except Exception as exc:                       # noqa: BLE001
            print(f"  {agency}: недоступно ({exc}) — обновите CSV вручную")


def main() -> None:
    conn = _conn()
    n = load_csv(conn)
    print(f"Загружено из CSV: {n} рейтингов")

    if "--fetch" in sys.argv:
        print("Проверка публичных источников:")
        try_fetch(conn)

    rows = ratings.all_ratings(conn)
    stale = [r for r in rows if r["stale"]]
    print(f"\nВ базе {len(rows)} эмитентов; устаревших (> {ratings.STALE_AFTER_DAYS} дн): "
          f"{len(stale)}")
    for r in stale:
        print(f"  ⚠ {r['issuer_ru']}: {r['rating']} ({r['agency']}, "
              f"обновлён {r['updated_at'] or '—'})")
    print("\nRecovery — базовая шкала по корзинам (агентства не публикуют): "
          + ", ".join(f"{b}={rec:.0%}" for b, rec in ratings.BASELINE_RECOVERY[:6]))


if __name__ == "__main__":
    main()
