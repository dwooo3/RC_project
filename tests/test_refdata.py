"""Unified reference look-ups (recommendations §8): currencies / boards / sources,
seeded from data and kept current on ingest."""
import pytest

from infra.db.market_data_db import MarketDataDB


@pytest.fixture
def db():
    return MarketDataDB(":memory:")


def _ref(secid, currency, board, market="bonds"):
    return {"secid": secid, "category": "bonds", "market": market, "board": board,
            "isin": None, "issuer_ru": "X", "name_ru": "X", "sec_type": None,
            "list_level": 1, "currency": currency, "asset_code": None,
            "last_trade_date": None, "is_active": 1, "last": 1.0, "change_pct": 0.0,
            "as_of": "2026-06-01", "day_json": "{}", "ref_json": "[]"}


def test_sources_seeded(db):
    codes = {s["code"] for s in db.list_ref_sources()}
    assert {"MOEX", "CBR"} <= codes


def test_currency_seeded_with_name_on_ingest(db):
    db.save_instrument_ref(_ref("SU1", "SUR", "TQOB"))
    cur = {c["code"]: c["name"] for c in db.list_ref_currencies()}
    assert cur.get("SUR") == "Российский рубль"


def test_board_seeded_on_ingest(db):
    db.save_instrument_ref(_ref("SU1", "SUR", "TQOB"))
    db.save_instrument_ref(_ref("EQ1", "RUB", "TQBR", market="shares"))
    boards = {b["board"]: b["market"] for b in db.list_ref_boards()}
    assert boards.get("TQOB") == "bonds"
    assert boards.get("TQBR") == "shares"


def test_unknown_currency_falls_back_to_code(db):
    db.save_instrument_ref(_ref("X1", "XXX", "TQOB"))
    cur = {c["code"]: c["name"] for c in db.list_ref_currencies()}
    assert cur.get("XXX") == "XXX"


def test_idempotent_seed(db):
    db.save_instrument_ref(_ref("SU1", "SUR", "TQOB"))
    n = len(db.list_ref_currencies())
    db._migrate_refdata()
    assert len(db.list_ref_currencies()) == n
