"""Versioned bond schedule (recommendations §7.3/§34).

A new schedule version is cut only when the coupon/amortization/offer schedule
changes; bond_coupons/_amortizations/_offers stay the live latest rows.
"""
import pytest

from infra.db.market_data_db import MarketDataDB

SECID = "SU26238RMFS4"


def _coupons(n=2):
    return [{"date": f"2026-0{i}-15", "value": 40.0, "value_prc": 8.0} for i in range(1, n + 1)]


@pytest.fixture
def db():
    return MarketDataDB(":memory:")


def test_first_schedule_creates_v1(db):
    db.save_bond_schedule(SECID, coupons=_coupons(2))
    vs = db.get_bond_schedule_versions(SECID)
    assert len(vs) == 1
    assert vs[0]["version"] == 1 and vs[0]["valid_to"] is None and vs[0]["n_coupons"] == 2


def test_unchanged_schedule_no_new_version(db):
    db.save_bond_schedule(SECID, coupons=_coupons(2))
    db.save_bond_schedule(SECID, coupons=_coupons(2))
    assert len(db.get_bond_schedule_versions(SECID)) == 1


def test_schedule_change_cuts_new_version(db):
    db.save_bond_schedule(SECID, coupons=_coupons(2))
    db.save_bond_schedule(SECID, coupons=_coupons(3))      # extra coupon
    vs = db.get_bond_schedule_versions(SECID)
    assert [v["version"] for v in vs] == [1, 2]
    assert vs[0]["valid_to"] is not None and vs[1]["valid_to"] is None
    assert vs[1]["n_coupons"] == 3


def test_empty_schedule_no_version(db):
    db.save_bond_schedule(SECID, coupons=[], amortizations=[], offers=[])
    assert db.get_bond_schedule_versions(SECID) == []


def test_backfill_seeds_v1(db):
    db._upsert_many("bond_coupons", [{"secid": SECID, "coupon_date": "2026-01-15",
                                      "value": 40.0, "value_prc": 8.0}])
    assert db.get_bond_schedule_versions(SECID) == []
    db._migrate_schedule_versions()
    assert len(db.get_bond_schedule_versions(SECID)) == 1
