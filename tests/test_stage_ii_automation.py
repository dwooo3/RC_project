"""
Stage II — automation: app auto-connect to the real DB (best_available_snapshot),
data-quality reporting, and the ISS smoke-test helpers. No network.
"""
from datetime import date, timedelta

import pytest

from infra.db.market_data_db import MarketDataDB
from services.market_data_service import MarketDataService


def _seed_real_snapshot(db, sid="moex-2026-06-10", vdate="2026-06-10"):
    """Minimal real-looking MOEX snapshot for completeness checks."""
    from datetime import datetime
    pts = [(0.5, 0.15, None), (1, 0.148, None), (2, 0.145, None),
           (5, 0.138, None), (10, 0.132, None)]
    db.save_curve(sid, "GCURVE_RUB", method="points", nss_params={}, as_of=vdate, points=pts)
    db.save_curve(sid, "CORP_T1", method="govt+spread", nss_params={}, as_of=vdate, points=pts)
    db.save_curve(sid, "REALCURVE_OFZIN", method="linker", nss_params={}, as_of=vdate,
                  points=[(2, 0.08, None), (3, 0.075, None), (5, 0.07, None)])
    db.save_curve(sid, "FXFWD_USD", method="futures", nss_params={}, as_of=vdate,
                  points=[(0.25, 0.1, None), (0.5, 0.095, None), (1, 0.09, None)])
    db.save_curve(sid, "KEYRATE_RUB", method="cbr_flat", nss_params={}, as_of=vdate, points=pts)
    db.save_curve(sid, "RUONIA_RUB", method="cbr_flat", nss_params={}, as_of=vdate, points=pts)
    for pair, rate in (("USD/RUB", 71.7), ("EUR/RUB", 82.8), ("CNY/RUB", 10.6)):
        db.save_fx_rate(sid, pair, rate)
    vol_observations = []
    expiry = (date.fromisoformat(vdate) + timedelta(days=30)).isoformat()
    for i in range(120):
        strike = 70000 + i * 100
        db.save_vol_point(sid, "Si", expiry, strike, 0.4)
        vol_observations.append({
            "underlying": "Si", "expiry": expiry, "strike": strike,
            "iv": 0.4, "forward": 76000.0, "tenor_days": 30,
            "oi": 100.0, "observation_date": vdate,
            "observation_status": "verified", "source": "MOEX_FORTS",
            "method": "black76_settlement",
            "option_price_date": vdate, "forward_date": vdate,
            "option_price_source": "MOEX_FORTS_OPTION_SETTLEMENT",
            "forward_source": "MOEX_FORTS_FUTURES_SETTLEMENT",
            "option_price_basis": "settlement", "forward_basis": "settlement",
        })
    db.replace_vol_point_observations(sid, vol_observations)
    db.save_time_series("IV30:Si", "vol", [(vdate, 0.4)])
    db.save_bond_quote(sid, {"secid": "SU26238RMFS4", "clean_price": 60.0,
                             "ytm": 0.15, "board": "TQOB"})
    db.save_snapshot_meta(snapshot_id=sid, valuation_date=vdate, source="MOEX",
                          quality="OK", fetch_ts=datetime(2026, 6, 10, 19, 30))


# ── Auto-connect / best_available_snapshot ───────────────

def test_best_available_snapshot_demo_without_db():
    svc = MarketDataService()                      # no market_db
    snap = svc.best_available_snapshot()
    assert snap.source_value == "DEMO"


def test_best_available_snapshot_prefers_real_moex():
    db = MarketDataDB(":memory:")
    _seed_real_snapshot(db)
    svc = MarketDataService(market_db=db)
    snap = svc.best_available_snapshot()
    assert snap.source_value == "MOEX"
    assert snap.snapshot_id == "moex-2026-06-10"
    assert "GCURVE_RUB" in snap.curves


def test_best_available_picks_latest_date():
    db = MarketDataDB(":memory:")
    _seed_real_snapshot(db, "moex-2026-06-09", "2026-06-09")
    _seed_real_snapshot(db, "moex-2026-06-10", "2026-06-10")
    svc = MarketDataService(market_db=db)
    assert svc.best_available_snapshot().snapshot_id == "moex-2026-06-10"


def test_best_available_never_raises_on_broken_db():
    db = MarketDataDB(":memory:")                  # empty: no snapshots at all
    svc = MarketDataService(market_db=db)
    snap = svc.best_available_snapshot()
    assert snap.source_value == "DEMO"             # graceful fallback


def test_latest_snapshot_meta_filters_source():
    db = MarketDataDB(":memory:")
    _seed_real_snapshot(db)
    assert db.latest_snapshot_meta(source="MOEX")["snapshot_id"] == "moex-2026-06-10"
    assert db.latest_snapshot_meta(source="BLOOMBERG") is None


def test_production_accepts_fresh_snapshot_bound_to_current_report():
    from infra.jobs.data_quality import persist_quality_report

    today = date.today()
    sid = f"moex-{today.isoformat()}"
    db = MarketDataDB(":memory:")
    _seed_real_snapshot(db, sid, today.isoformat())
    report = persist_quality_report(db, sid, valuation_date=today)

    assert report["status"] == "OK"
    snap = MarketDataService(market_db=db, mode="production").moex_snapshot(today)
    assert snap.snapshot_id == sid


def test_production_rejects_snapshot_mutated_after_quality_report():
    from infra.jobs.data_quality import persist_quality_report

    today = date.today()
    sid = f"moex-{today.isoformat()}"
    expiry = (today + timedelta(days=30)).isoformat()
    db = MarketDataDB(":memory:")
    _seed_real_snapshot(db, sid, today.isoformat())
    assert persist_quality_report(db, sid, valuation_date=today)["status"] == "OK"

    db.save_vol_point(sid, "Si", expiry, 70000, 0.99)

    with pytest.raises(Exception, match="no production MOEX snapshot"):
        MarketDataService(market_db=db, mode="production").moex_snapshot(today)


@pytest.mark.parametrize("offset", [-10, 7])
def test_production_latest_rejects_stale_or_future_snapshot_at_runtime(offset):
    from infra.jobs.data_quality import persist_quality_report

    snapshot_day = date.today() + timedelta(days=offset)
    sid = f"moex-{snapshot_day.isoformat()}"
    db = MarketDataDB(":memory:")
    _seed_real_snapshot(db, sid, snapshot_day.isoformat())
    # The historical report was valid at its own run date.  It must not admit
    # that payload indefinitely (or before its date) at today's runtime.
    assert persist_quality_report(
        db, sid, valuation_date=snapshot_day)["status"] == "OK"

    with pytest.raises(Exception, match="no production MOEX snapshot"):
        MarketDataService(
            market_db=db, mode="production").best_available_snapshot()


# ── Data-quality report ──────────────────────────────────

def test_quality_report_complete_snapshot():
    from infra.jobs.data_quality import snapshot_quality_report
    db = MarketDataDB(":memory:")
    _seed_real_snapshot(db)
    rep = snapshot_quality_report(db, "moex-2026-06-10", date(2026, 6, 10))
    assert rep["status"] == "OK"
    assert rep["completeness_pct"] == 100.0
    assert rep["staleness_days"] == 0
    assert rep["alerts"] == []
    assert rep["checks"]["vol_points"] >= 100
    assert rep["checks"]["contract_version"].endswith("snapshot-binding-v3")
    assert len(rep["checks"]["snapshot_fingerprint"]) == 64


def test_quality_report_flags_missing_and_stale():
    from infra.jobs.data_quality import snapshot_quality_report
    db = MarketDataDB(":memory:")
    from datetime import datetime
    # only a govt curve + one FX, thin vols, old date
    db.save_curve("s1", "GCURVE_RUB", method="points", nss_params={}, as_of="2026-06-01",
                  points=[(1, 0.15, None), (5, 0.14, None), (10, 0.13, None)])
    db.save_fx_rate("s1", "USD/RUB", 71.7)
    db.save_snapshot_meta(snapshot_id="s1", valuation_date="2026-06-01", source="MOEX",
                          quality="OK", fetch_ts=datetime(2026, 6, 1))
    rep = snapshot_quality_report(db, "s1", date(2026, 6, 10))
    assert rep["status"] in ("WARN", "FAIL")
    assert any("missing curves" in a for a in rep["alerts"])
    assert any("missing FX" in a for a in rep["alerts"])
    assert any("thin vol" in a for a in rep["alerts"])
    assert any("stale" in a for a in rep["alerts"])
    assert rep["completeness_pct"] < 100


def test_history_depth_report():
    from infra.jobs.data_quality import history_depth_report
    db = MarketDataDB(":memory:")
    db.save_time_series("SBER:price", "price",
                        [(f"2026-01-{d:02d}", 100 + d) for d in range(1, 29)])
    db.save_time_series("DEEP:price", "price",
                        [(f"2025-{m:02d}-01", 50 + m) for m in range(1, 13)] * 6)
    rep = history_depth_report(db)
    assert rep["n_series"] == 2
    assert "SBER:price" in rep["thin_series"]      # 28 < 60 days
    assert rep["alerts"]


def test_format_report_renders():
    from infra.jobs.data_quality import format_report, snapshot_quality_report
    db = MarketDataDB(":memory:")
    _seed_real_snapshot(db)
    text = format_report(snapshot_quality_report(db, "moex-2026-06-10", date(2026, 6, 10)))
    assert "moex-2026-06-10" in text and "[OK]" in text


# ── Smoke-test helpers ───────────────────────────────────

def test_smoke_network_error_classifier():
    import scripts.smoke_iss as smoke
    assert smoke._is_network_error(Exception("ISS request failed after 3 attempts"))
    assert smoke._is_network_error(Exception("SSL: CERTIFICATE_VERIFY_FAILED"))
    assert not smoke._is_network_error(Exception("block 'securities' empty"))


# ── EOD job attaches a quality report ────────────────────

def test_eod_job_attaches_quality_report():
    from infra.jobs.eod_ingest import EodIngestJob

    class _Iss:
        def get_blocks(self, path, params=None):
            if "zcyc" in path:
                return {"yearyields": [{"period": 1, "value": 14.5},
                                       {"period": 5, "value": 14.0}], "params": []}
            return {"securities": [], "marketdata": []}

        def get_block_paginated(self, path, block, params=None):
            return []

    db = MarketDataDB(":memory:")
    summary = EodIngestJob(db, _Iss(), None).run(date(2026, 6, 10))
    assert "quality_report" in summary
    assert "status" in summary["quality_report"]
