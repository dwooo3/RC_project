"""MarketDataDB serializes access to its shared sqlite connection.

The API bridge shares one connection across the uvicorn thread pool; without
serialization, concurrent execute/fetch interleave and reads intermittently come
back empty ("unknown instrument" 404s in the UI) or raise "recursive use of
cursors". Hammer the DB from many threads and require every read to succeed.
"""
import threading

from infra.db.market_data_db import MarketDataDB


def _ref(secid):
    return {"secid": secid, "category": "bonds", "market": "bonds", "board": "TQOB",
            "isin": secid, "issuer_ru": "X", "name_ru": "X", "sec_type": None,
            "list_level": 1, "currency": "SUR", "asset_code": None,
            "last_trade_date": None, "is_active": 1, "last": 100.0, "change_pct": 0.0,
            "as_of": "2026-07-01", "day_json": "{}", "ref_json": "[]"}


def test_concurrent_reads_and_writes_never_lose_rows():
    db = MarketDataDB(":memory:")
    secids = [f"SEC{i:03d}" for i in range(20)]
    for s in secids:
        db.save_instrument_ref(_ref(s))

    errors: list[str] = []
    barrier = threading.Barrier(8)

    def reader(n):
        barrier.wait()
        for i in range(300):
            s = secids[(n * 7 + i) % len(secids)]
            try:
                row = db.get_instrument_ref(s)
                if not row or row.get("secid") != s:
                    errors.append(f"empty read for {s}")
                    return
            except Exception as exc:                      # noqa: BLE001 — the failure mode under test
                errors.append(f"{type(exc).__name__}: {exc}")
                return

    def writer(n):
        barrier.wait()
        for i in range(150):
            try:
                db.save_instrument_ref(_ref(secids[(n + i) % len(secids)]))
            except Exception as exc:                      # noqa: BLE001
                errors.append(f"writer {type(exc).__name__}: {exc}")
                return

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(6)] + \
              [threading.Thread(target=writer, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
