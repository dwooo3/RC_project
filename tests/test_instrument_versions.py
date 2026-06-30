"""Versioned instrument reference (recommendations §7.2/§34).

A new reference version is cut only when the descriptive payload changes; daily
quote changes (last / change_pct) do not. instrument_ref stays the live latest.
"""
import pytest

from infra.db.market_data_db import MarketDataDB


def _ref(secid="SU26238RMFS4", *, name="ОФЗ 26238", last=97.0, change=0.1, as_of="2026-06-01"):
    return {"secid": secid, "category": "bonds", "market": "bonds", "board": "TQOB",
            "isin": "RU000A1038V6", "issuer_ru": "Минфин", "name_ru": name,
            "sec_type": "ofz_bond", "list_level": 1, "currency": "SUR",
            "asset_code": None, "last_trade_date": None, "is_active": 1,
            "last": last, "change_pct": change, "as_of": as_of,
            "day_json": "{}", "ref_json": "[]"}


@pytest.fixture
def db():
    return MarketDataDB(":memory:")


def test_first_save_creates_v1(db):
    db.save_instrument_ref(_ref())
    vs = db.get_instrument_versions("SU26238RMFS4")
    assert len(vs) == 1
    assert vs[0]["version"] == 1 and vs[0]["valid_to"] is None


def test_unchanged_ref_no_new_version(db):
    db.save_instrument_ref(_ref())
    db.save_instrument_ref(_ref())                       # identical reference
    assert len(db.get_instrument_versions("SU26238RMFS4")) == 1


def test_daily_quote_change_no_new_version(db):
    db.save_instrument_ref(_ref(last=97.0, change=0.1))
    db.save_instrument_ref(_ref(last=98.5, change=1.5, as_of="2026-06-02"))   # only quote moved
    assert len(db.get_instrument_versions("SU26238RMFS4")) == 1


def test_reference_change_cuts_new_version(db):
    db.save_instrument_ref(_ref(name="ОФЗ 26238", as_of="2026-06-01"))
    db.save_instrument_ref(_ref(name="ОФЗ 26238 (ренейм)", as_of="2026-06-05"))
    vs = db.get_instrument_versions("SU26238RMFS4")
    assert [v["version"] for v in vs] == [1, 2]
    assert vs[0]["valid_to"] == "2026-06-05"             # old version closed
    assert vs[1]["valid_to"] is None                     # new version open
    assert vs[1]["valid_from"] == "2026-06-05"


def test_live_ref_still_latest(db):
    db.save_instrument_ref(_ref(name="A", as_of="2026-06-01"))
    db.save_instrument_ref(_ref(name="B", as_of="2026-06-05"))
    assert db.get_instrument_ref("SU26238RMFS4")["name_ru"] == "B"


def test_backfill_seeds_v1(db):
    # row written straight to instrument_ref (bypassing versioning), then migrate
    db._upsert("instrument_ref", _ref())
    assert db.get_instrument_versions("SU26238RMFS4") == []
    db._migrate_instrument_versions()
    assert len(db.get_instrument_versions("SU26238RMFS4")) == 1
