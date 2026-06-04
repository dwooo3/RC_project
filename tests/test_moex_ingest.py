"""MOEX ingestion ETL (spec §4) — fixtures, no network."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pytest

from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.ingest import MoexIngestor, extract_fx_rates


class FakeClient:
    """Returns canned ISS blocks keyed by endpoint path."""
    def __init__(self, responses):
        self.responses = responses

    def get_blocks(self, path, params=None):
        return self.responses[path]


ZCYC = {
    "yearyields": [
        {"tradedate": "2026-06-04", "period": 0.25, "value": 15.5},
        {"tradedate": "2026-06-04", "period": 0.5, "value": 15.2},
        {"tradedate": "2026-06-04", "period": 1.0, "value": 14.8},
        {"tradedate": "2026-06-04", "period": 2.0, "value": 14.5},
        {"tradedate": "2026-06-04", "period": 5.0, "value": 13.8},
    ],
    "params": [{"tradedate": "2026-06-04", "B1": 8.0, "B2": -1.0, "B3": 2.0, "T1": 3.0}],
}

SELT_RATES = {
    "wap_rates": [
        {"SECID": "USDTOM_UTS", "CLOSEPRICE": 74.366, "TRADETIME": "15:29:59"},
        {"SECID": "CNYRUB_TOM", "LAST": 10.95},
        {"SECID": "CBRF_EUR", "CLOSEPRICE": 86.2712},
    ],
}

BONDS_TQOB = {
    "securities": [{
        "SECID": "SU26240RMFS0", "ISIN": "RU000A1014T1", "COUPONPERCENT": 6.9,
        "COUPONPERIOD": 182, "NEXTCOUPON": "2026-07-15", "MATDATE": "2036-07-30",
        "FACEVALUE": 1000.0, "FACEUNIT": "SUR", "CURRENCYID": "SUR",
        "ACCRUEDINT": 12.3, "LOTSIZE": 1, "LISTLEVEL": 1, "SECNAME": "ОФЗ 26240",
        "PREVPRICE": 78.5, "YIELDATPREVWAPRICE": 14.2,
    }],
    "marketdata": [{
        "SECID": "SU26240RMFS0", "LAST": 78.6, "WAPRICE": 78.55,
        "YIELD": 14.1, "VALTODAY": 1_000_000,
    }],
}


@pytest.fixture
def setup():
    db = MarketDataDB(":memory:")
    client = FakeClient({
        "engines/stock/zcyc": ZCYC,
        "statistics/engines/currency/markets/selt/rates": SELT_RATES,
        "engines/stock/markets/bonds/boards/TQOB/securities": BONDS_TQOB,
    })
    ing = MoexIngestor(client, db)
    yield ing, db
    db.close()


def test_extract_fx_rates_tolerant():
    rates, times = extract_fx_rates(SELT_RATES)
    assert rates == {"USD/RUB": pytest.approx(74.366),
                     "CNY/RUB": pytest.approx(10.95),
                     "EUR/RUB": pytest.approx(86.2712)}
    assert times["USD/RUB"] == "15:29:59"


def test_ingest_gcurve_writes_decimal_points_and_nss(setup):
    ing, db = setup
    sid = ing.snapshot_id_for(date(2026, 6, 4))
    n = ing.ingest_gcurve(sid, date(2026, 6, 4))
    assert n == 5
    pts = db.get_curve_points(sid, "GCURVE_RUB")
    assert [p["tenor"] for p in pts] == [0.25, 0.5, 1.0, 2.0, 5.0]
    assert pts[0]["zero_rate"] == pytest.approx(0.155)  # percent -> decimal
    # discount factors strictly decreasing
    dfs = [p["discount_factor"] for p in pts]
    assert all(b < a for a, b in zip(dfs, dfs[1:]))
    curve = db.get_curve(sid, "GCURVE_RUB")
    assert curve["method"] == "nss"


def test_ingest_fx_writes_rates(setup):
    ing, db = setup
    sid = ing.snapshot_id_for(date(2026, 6, 4))
    ing.ingest_fx(sid, date(2026, 6, 4))
    fx = db.get_fx_rates(sid)
    assert fx["USD/RUB"] == pytest.approx(74.366)
    assert fx["EUR/RUB"] == pytest.approx(86.2712)


def test_ingest_bonds_writes_instrument_and_quote(setup):
    ing, db = setup
    sid = ing.snapshot_id_for(date(2026, 6, 4))
    n = ing.ingest_bonds(sid, date(2026, 6, 4), board="TQOB")
    assert n == 1
    quotes = db.get_bond_quotes(sid)
    q = quotes[0]
    assert q["secid"] == "SU26240RMFS0"
    assert q["ytm"] == pytest.approx(0.141)   # marketdata YIELD 14.1% -> decimal
    assert q["accruedint"] == pytest.approx(12.3)
    inst = db.conn.execute("SELECT * FROM instruments WHERE secid=?", ("SU26240RMFS0",)).fetchone()
    assert inst["coupon_percent"] == pytest.approx(6.9)
    assert inst["mat_date"] == "2036-07-30"


def test_ingest_all_logs_each_endpoint(setup):
    ing, db = setup
    counts = ing.ingest_all(date(2026, 6, 4))
    # Phase B adds corporate-curve calibration; the single OFZ here is tier T1
    # with < min_bonds, so 0 corporate curves are produced (still logged ok).
    assert counts == {"gcurve": 5, "fx": 3, "bonds": 1, "corporate": 0}
    logs = db.conn.execute("SELECT endpoint, status FROM ingest_log").fetchall()
    assert {r["status"] for r in logs} == {"ok"}
    assert len(logs) == 4


def test_ingest_logs_error_on_failure():
    db = MarketDataDB(":memory:")
    class Boom:
        def get_blocks(self, path, params=None):
            raise OSError("iss down")
    ing = MoexIngestor(Boom(), db)
    with pytest.raises(OSError):
        ing.ingest_gcurve("moex-x", date(2026, 6, 4))
    row = db.conn.execute("SELECT status, error FROM ingest_log").fetchone()
    assert row["status"] == "error" and "iss down" in row["error"]
    db.close()
