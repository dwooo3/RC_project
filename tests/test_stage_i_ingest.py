"""
Stage I — market-data loading. Fixture-based (no network): self-implied option
vols, CBR HTML parsers + official FX, bucketed corp curves, real curve / FX
futures / bondization ingest, and the backfill helpers.
"""
import json
from datetime import date

import pytest

from infra.db.market_data_db import MarketDataDB


# ── Self-implied option vols ─────────────────────────────

def test_parse_option_shortname():
    from infra.moex_iss.vol_surface import parse_option_shortname
    p = parse_option_shortname("Si-6.26M180626CA100000")
    assert p["underlying"] == "Si-6.26"
    assert p["expiry"] == "2026-06-18"
    assert p["cp"] == "call" and p["strike"] == 100000
    assert parse_option_shortname("garbage") is None
    put = parse_option_shortname("RI-6.26M180626PA250000")
    assert put["cp"] == "put"


def test_imply_option_vols_recovers_black76():
    """Settle prices generated from a known vol must imply that vol back."""
    from models.black_scholes import black76
    from infra.moex_iss.vol_surface import imply_option_vols
    F, T, sigma = 90000.0, 30 / 365.0, 0.40
    fut_secs = [{"SECID": "SiM6", "SHORTNAME": "Si-6.26", "PREVSETTLEPRICE": F}]
    fut_md = []
    opt_secs, opt_md = [], []
    for K in (80000, 90000, 100000):
        cp = "call" if K >= F else "put"
        price = black76(F, K, T, 0.0, sigma, cp).price
        name = f"Si-6.26M100726{'C' if cp=='call' else 'P'}A{K}"
        sid = f"Si{K}{cp[0]}"
        opt_secs.append({"SECID": sid, "SHORTNAME": name, "ASSETCODE": "Si",
                         "LASTTRADEDATE": "2026-07-10", "PREVOPENPOSITION": 100})
        opt_md.append({"SECID": sid, "SETTLEPRICE": price, "OPENPOSITION": 100})
    pts = imply_option_vols(opt_secs, opt_md, fut_secs, fut_md, date(2026, 6, 10))
    assert len(pts) == 3
    for p in pts:
        assert p["iv"] == pytest.approx(sigma, abs=1e-3), p["strike"]
    assert all(p["underlying"] == "Si" for p in pts)


def test_imply_option_vols_quality_filters():
    from infra.moex_iss.vol_surface import imply_option_vols
    fut = [{"SECID": "F", "SHORTNAME": "Si-6.26", "PREVSETTLEPRICE": 90000.0}]
    # zero OI and zero price must be dropped
    opt_secs = [{"SECID": "o1", "SHORTNAME": "Si-6.26M100726CA200000",
                 "ASSETCODE": "Si", "LASTTRADEDATE": "2026-07-10", "PREVOPENPOSITION": 0}]
    opt_md = [{"SECID": "o1", "SETTLEPRICE": 0.0, "OPENPOSITION": 0}]
    assert imply_option_vols(opt_secs, opt_md, fut, [], date(2026, 6, 10)) == []


# ── CBR HTML parsers + official FX ───────────────────────

def test_parse_keyrate_html():
    from infra.cbr.client import parse_keyrate_html
    html = "<table><tr><td>10.06.2026</td><td>14,50</td></tr>" \
           "<tr><td>09.06.2026</td><td>14,50</td></tr></table>"
    rows = parse_keyrate_html(html)
    assert ("2026-06-10", 0.145) in rows and len(rows) == 2


def test_parse_ruonia_html_transposed():
    from infra.cbr.client import parse_ruonia_html
    html = ("<tr><th>Дата ставки</th><td>09.06.2026</td><td>10.06.2026</td></tr>"
            "<tr><td>Ставка RUONIA, % годовых</td><td>14,05</td><td>13,96</td></tr>"
            "<tr><td>Объем сделок</td><td>772,00</td><td>749,22</td></tr>")
    rows = parse_ruonia_html(html)
    assert ("2026-06-10", 0.1396) in rows
    assert ("2026-06-09", 0.1405) in rows


def test_cbr_clients_fallback_to_records():
    """Injected JSON fixture (non-HTML) must still parse via the fallback."""
    from infra.cbr.client import CbrClient
    payload = json.dumps([{"date": "2026-06-10", "value": "14,50"}])
    c = CbrClient(fetch=lambda url: payload)
    assert c.get_key_rate(date(2026, 6, 10)) == [("2026-06-10", 0.145)]


def test_get_official_rates():
    from infra.cbr.client import CbrClient
    xml = ('<ValCurs><Valute ID="R01235"><CharCode>USD</CharCode>'
           '<Nominal>1</Nominal><Value>71,73</Value></Valute>'
           '<Valute ID="R01375"><CharCode>CNY</CharCode>'
           '<Nominal>10</Nominal><Value>106,06</Value></Valute></ValCurs>')
    c = CbrClient(fetch=lambda url: xml)
    rates = c.get_official_rates(date(2026, 6, 10))
    assert rates["USD/RUB"] == pytest.approx(71.73)
    assert rates["CNY/RUB"] == pytest.approx(10.606)        # per-nominal divided


# ── Bucketed corporate curve ─────────────────────────────

def test_bucketed_corp_curve_robust_to_outliers():
    from curves.yield_curve import YieldCurve
    from infra.moex_iss.calibration import build_corporate_curve_points_bucketed
    g = YieldCurve.flat(0.13)
    spreads = []
    for tenor in (0.9, 1.0, 1.1, 1.9, 2.0, 2.1, 4.8, 5.0, 5.2):
        spreads.append({"tenor": tenor, "spread": 0.02, "tier": "T1"})
    # outliers (defaulted prints) must be bounded out, not poison the median
    spreads += [{"tenor": 2.0, "spread": 0.95, "tier": "T1"},
                {"tenor": 1.0, "spread": -0.5, "tier": "T1"}]
    pts = build_corporate_curve_points_bucketed(g, spreads, "T1",
                                                min_bonds_per_bucket=3)
    assert len(pts) == 3                                    # 1y, 2y, 5y buckets
    for tenor, zero, _ in pts:
        assert zero == pytest.approx(0.13 + 0.02, abs=1e-9)  # clean median spread


# ── Real curve / FX futures / bondization ingest (mock ISS) ──

class _FakeIss:
    def __init__(self, blocks_map):
        self.blocks_map = blocks_map

    def get_blocks(self, path, params=None):
        for key, blocks in self.blocks_map.items():
            if key in path:
                return blocks
        return {}

    def get_block_paginated(self, path, block, params=None):
        return self.get_blocks(path, params).get(block, [])


def test_ingest_real_curve():
    from infra.moex_iss.ingest import MoexIngestor
    db = MarketDataDB(":memory:")
    iss = _FakeIss({"boards/TQOB/securities": {
        "securities": [
            {"SECID": "SU52002RMFS1", "MATDATE": "2028-06-10"},
            {"SECID": "SU52003RMFS9", "MATDATE": "2031-06-10"},
            {"SECID": "SU26238RMFS4", "MATDATE": "2041-06-10"},   # not a linker
        ],
        "marketdata": [
            {"SECID": "SU52002RMFS1", "YIELD": 8.5},
            {"SECID": "SU52003RMFS9", "YIELD": 7.5},
            {"SECID": "SU26238RMFS4", "YIELD": 15.0},
        ]}})
    n = MoexIngestor(iss, db).ingest_real_curve("s1", date(2026, 6, 10))
    assert n == 2                                           # only SU52* linkers
    pts = db.get_curve_points("s1", "REALCURVE_OFZIN")
    assert len(pts) == 2 and all(0.05 < p["zero_rate"] < 0.10 for p in pts)


def test_ingest_fx_futures():
    from infra.moex_iss.ingest import MoexIngestor
    db = MarketDataDB(":memory:")
    iss = _FakeIss({"forts/securities": {
        "securities": [
            {"SECID": "SiM6", "ASSETCODE": "Si", "LASTTRADEDATE": "2026-09-10",
             "PREVSETTLEPRICE": 73000},
            {"SECID": "SiH7", "ASSETCODE": "Si", "LASTTRADEDATE": "2027-03-10",
             "PREVSETTLEPRICE": 75000},
        ],
        "marketdata": []}})
    n = MoexIngestor(iss, db).ingest_fx_futures("s1", date(2026, 6, 10),
                                                spot_rates={"USD/RUB": 71.7})
    assert n == 1
    pts = db.get_curve_points("s1", "FXFWD_USD")
    assert len(pts) == 2 and all(p["zero_rate"] > 0 for p in pts)  # contango carry


def test_ingest_bondization():
    from infra.moex_iss.ingest import MoexIngestor
    db = MarketDataDB(":memory:")
    iss = _FakeIss({"bondization": {
        "coupons": [{"coupondate": "2026-12-10", "value": 35.4, "valueprc": 7.08},
                    {"coupondate": "2027-06-10", "value": 35.4, "valueprc": 7.08}],
        "amortizations": [{"amortdate": "2027-06-10", "value": 1000, "facevalue": 0}],
        "offers": []}})
    n = MoexIngestor(iss, db).ingest_bondization(["SU26238RMFS4"])
    assert n == 1
    sched = db.get_bond_schedule("SU26238RMFS4")
    assert len(sched["coupons"]) == 2 and len(sched["amortizations"]) == 1


# ── Backfill helpers ─────────────────────────────────────

def test_business_days():
    from infra.jobs.backfill import business_days
    days = business_days(date(2026, 6, 8), date(2026, 6, 14))  # Mon..Sun
    assert len(days) == 5 and days[0].weekday() == 0 and days[-1].weekday() == 4


def test_top_equities_by_volume_fallback():
    from infra.jobs.backfill import top_equities_by_volume
    db = MarketDataDB(":memory:")
    # empty DB -> fallback list
    assert top_equities_by_volume(db, 5) == ["SBER", "GAZP", "LKOH", "T", "ROSN"]
    # with quotes -> ranked by volume
    db.save_equity_quote("s1", {"secid": "AAA", "last": 1, "prevprice": 1,
                                "board": "TQBR", "volume": 100})
    db.save_equity_quote("s1", {"secid": "BBB", "last": 1, "prevprice": 1,
                                "board": "TQBR", "volume": 999})
    assert top_equities_by_volume(db, 2) == ["BBB", "AAA"]


def test_load_cpi_csv(tmp_path):
    from infra.jobs.backfill import load_cpi_csv
    p = tmp_path / "cpi.csv"
    p.write_text("# CPI index\n2026-04-01,112.3\n2026-05-01,113.1\n", encoding="utf-8")
    db = MarketDataDB(":memory:")
    n = load_cpi_csv(db, str(p))
    assert n == 2
    ts = db.get_time_series("CPI_RU", "index")
    assert ts[-1]["value"] == pytest.approx(113.1)


# ── DB schema additions ──────────────────────────────────

def test_bond_schedule_persistence():
    db = MarketDataDB(":memory:")
    db.save_bond_schedule("X", coupons=[{"date": "2026-12-10", "value": 35.4,
                                         "value_prc": 7.08}])
    sched = db.get_bond_schedule("X")
    assert sched["coupons"][0]["value"] == pytest.approx(35.4)
    assert sched["amortizations"] == [] and sched["offers"] == []
