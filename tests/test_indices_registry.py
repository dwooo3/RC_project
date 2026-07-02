"""Honest indices (audit A2): the Indices tab lists only registered index series
(MOEX:price is the exchange's *share* backfill and must not appear), and rawdata
ordering is deterministic (A9)."""
import datetime as dt

import pytest

from api.market_entity import _INDICES, _list_indices
from infra.db.market_data_db import MarketDataDB


class _Ctx:
    def __init__(self, db):
        self.market_db = db


@pytest.fixture
def db():
    d = MarketDataDB(":memory:")
    # RVI — a real registered index; MOEX — the share backfill (must be excluded)
    d.save_time_series("RVI:price", "price", [("2026-06-20", 30.0), ("2026-06-23", 33.0)])
    d.save_time_series("MOEX:price", "price", [("2026-06-20", 160.0), ("2026-06-23", 165.0)])
    d.save_time_series("IMOEX:price", "price", [("2026-06-23", 2243.47)])
    return d


def test_moex_share_is_not_an_index(db):
    secids = [i["secid"] for i in _list_indices(_Ctx(db))["instruments"]]
    assert "MOEX" not in secids
    assert "MOEX" not in _INDICES


def test_registered_indices_listed_with_names_and_change(db):
    rows = {i["secid"]: i for i in _list_indices(_Ctx(db))["instruments"]}
    assert rows["RVI"]["issuer_ru"] == "Индекс волатильности"
    assert rows["RVI"]["last"] == 33.0
    assert rows["RVI"]["change_pct"] == pytest.approx(10.0)     # 30 → 33
    assert rows["IMOEX"]["change_pct"] is None                  # single point


def test_unstored_registry_entries_skipped(db):
    secids = [i["secid"] for i in _list_indices(_Ctx(db))["instruments"]]
    assert "RTSI" not in secids                                 # no data seeded


def test_last_two_points_getter(db):
    pts = db.last_two_points("RVI:price")
    assert [p["value"] for p in pts] == [33.0, 30.0]            # newest first


def test_ingest_log_rows_newest_first(db):
    for i in range(3):
        db.log_ingest(f"step{i}", "ok", i, dt.datetime(2026, 7, 1, 10, i), dt.datetime(2026, 7, 1, 10, i, 30))
    rows = db.table_rows("ingest_log", 10, newest_first=True)
    assert rows[0]["endpoint"] == "step2"
