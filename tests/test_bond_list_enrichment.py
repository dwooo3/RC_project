"""Bond list enrichment (plan B1/B2): YTM from bond_quotes and G-spread vs the
GCURVE zero at maturity, computed from data already in the store."""
import datetime as dt

import pytest

from api.market_entity import _gcurve_zero, list_instruments
from infra.db.market_data_db import MarketDataDB

SID = "moex-2026-07-01"


class _Snap:
    snapshot_id = SID


class _Ctx:
    def __init__(self, db):
        self.market_db = db
        self.snapshot = _Snap()


def _mkdb():
    db = MarketDataDB(":memory:")
    db.save_snapshot_meta(snapshot_id=SID, valuation_date=dt.date(2026, 7, 1),
                          source="MOEX", quality="OK", fetch_ts=dt.datetime(2026, 7, 1, 19))
    # flat-ish GCURVE: 10% at 1y → 12% at 5y (decimals)
    db.save_curve(SID, "GCURVE_RUB", method="nss", nss_params=None,
                  as_of="2026-07-01", points=[(1.0, 0.10, None), (5.0, 0.12, None)])
    # a bond maturing in ~2 years with YTM 14% (stored as a decimal fraction)
    mat = (dt.date(2026, 7, 1) + dt.timedelta(days=730)).isoformat()
    db._upsert("instruments", {"secid": "BOND1", "mat_date": mat})
    db.save_bond_quote(SID, {"secid": "BOND1", "clean_price": 95.0, "accruedint": 12.3,
                             "wap_price": 95.1, "ytm": 0.14, "volume": 100, "board": "TQOB"})
    db.save_instrument_ref({"secid": "BOND1", "category": "bonds", "market": "bonds",
                            "board": "TQOB", "isin": "RU1", "issuer_ru": "Тест",
                            "name_ru": "Тест", "sec_type": None, "list_level": 1,
                            "currency": "SUR", "asset_code": None, "last_trade_date": None,
                            "is_active": 1, "last": 95.0, "change_pct": 0.1,
                            "as_of": "2026-07-01", "day_json": "{}", "ref_json": "[]"})
    return db


def test_gcurve_interpolator():
    zero = _gcurve_zero([{"tenor": 1.0, "zero_rate": 0.10}, {"tenor": 5.0, "zero_rate": 0.12}])
    assert zero(1.0) == pytest.approx(0.10)
    assert zero(3.0) == pytest.approx(0.11)
    assert zero(10.0) == pytest.approx(0.12)          # flat extrapolation


def test_bond_list_carries_ytm_and_gspread():
    ctx = _Ctx(_mkdb())
    rows = list_instruments(ctx, "bonds")["instruments"]
    b = rows[0]
    assert b["ytm"] == pytest.approx(14.0)
    # T≈2y → zero≈10.5%; spread = (14% − 10.5%) = ~350 bp
    assert b["g_spread_bp"] == pytest.approx(350.0, abs=5.0)


def test_junk_ytm_filtered():
    db = _mkdb()
    db.save_bond_quote(SID, {"secid": "BOND1", "clean_price": 95.0, "accruedint": 0,
                             "wap_price": None, "ytm": 100.0, "volume": 1, "board": "TQOB"})
    rows = list_instruments(_Ctx(db), "bonds")["instruments"]
    assert "ytm" not in rows[0]
