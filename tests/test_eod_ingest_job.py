"""Phase E — EOD ingest job orchestration + scheduler (fixtures, no network)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, datetime, timedelta

import pytest

from infra.db.market_data_db import MarketDataDB
from infra.jobs.eod_ingest import EodIngestJob
from infra.jobs.scheduler import EodSchedule, run_if_due

VAL = date(2026, 6, 2)

ZCYC = {"yearyields": [{"period": t, "value": v} for t, v in
                       [(0.25, 15.5), (0.5, 15.2), (1, 14.8), (2, 14.5), (5, 13.8), (10, 13.2)]],
        "params": [{"B1": 8.0, "B2": -1.0, "B3": 2.0, "T1": 3.0, "tradedate": "2026-06-02"}]}
SELT = {"wap_rates": [{"SECID": "USDTOM_UTS", "CLOSEPRICE": 74.36},
                      {"SECID": "EURRUB_TOM", "LAST": 86.27}]}
BONDS = {"securities": [{"SECID": "SU26240RMFS0", "MATDATE": "2036-07-30", "FACEVALUE": 1000.0,
                         "LISTLEVEL": 1, "YIELDATPREVWAPRICE": 14.2, "PREVPRICE": 78.5}],
         "marketdata": [{"SECID": "SU26240RMFS0", "YIELD": 14.1, "VALTODAY": 1e6}]}
SHARES = {"securities": [{"SECID": "SBER", "PREVPRICE": 305.0}],
          "marketdata": [{"SECID": "SBER", "LAST": 307.5, "VALTODAY": 1e9}]}
OPTIONS = {"securities": [{"SECID": "SR320", "ASSETCODE": "SBER", "STRIKE": 320.0, "LASTDELDATE": "2026-06-19"}],
           "marketdata": [{"SECID": "SR320", "VOLATILITY": 28.0}]}


class FakeIss:
    def __init__(self, blocks, paginated, fail_paths=()):
        self.blocks = blocks
        self.paginated = paginated
        self.fail_paths = set(fail_paths)

    def get_blocks(self, path, params=None):
        if path in self.fail_paths:
            raise OSError(f"iss down: {path}")
        return self.blocks.get(path, {})

    def get_block_paginated(self, path, block, params=None, **kw):
        if path in self.fail_paths:
            raise OSError(f"iss down: {path}")
        return self.paginated.get(path, {}).get(block, [])


class FakeCbr:
    def get_key_rate(self, from_date, till_date=None): return [("2026-06-02", 0.21)]
    def get_ruonia(self, from_date, till_date=None): return [("2026-06-02", 0.153)]


def _iss(fail_paths=()):
    blocks = {
        "engines/stock/zcyc": ZCYC,
        "statistics/engines/currency/markets/selt/rates": SELT,
        "engines/stock/markets/bonds/boards/TQOB/securities": BONDS,
        "engines/stock/markets/shares/boards/TQBR/securities": SHARES,
        "engines/futures/markets/options/securities": OPTIONS,
    }
    paginated = {
        "history/engines/stock/markets/index/securities/IMOEX":
            {"history": [{"TRADEDATE": "2026-06-02", "CLOSE": 3200.0}]},
        "history/engines/stock/markets/shares/boards/TQBR/securities/SBER":
            {"history": [{"TRADEDATE": "2026-06-02", "CLOSE": 307.5}]},
    }
    return FakeIss(blocks, paginated, fail_paths)


def _job(fail_paths=()):
    return EodIngestJob(MarketDataDB(":memory:"), _iss(fail_paths), FakeCbr(),
                        indices=["IMOEX"], equities=["SBER"])


# ── job orchestration ────────────────────────────────────

def test_eod_job_runs_all_sources_and_builds_snapshot():
    job = _job()
    summary = job.run(VAL)
    s = summary["steps"]
    assert s["gcurve"] == 6 and s["fx"] == 2 and s["bonds"] == 1
    assert s["equity_quotes"] == 1 and s["vol_surface"] == 1
    assert s["index:IMOEX"] == 1 and s["equity:SBER"] == 1
    assert s["cbr_key_rate"] == 1 and s["cbr_ruonia"] == 1
    snap = summary["snapshot"]
    assert snap["source"] == "MOEX" and snap["quality"] == "OK"
    assert "GCURVE_RUB" in snap["curves"]
    assert "KEYRATE_RUB" in snap["curves"] and "RUONIA_RUB" in snap["curves"]
    assert "SBER_FORTS" in snap["vol_surfaces"]


def test_eod_job_is_idempotent():
    from infra.moex_iss.ingest import MoexIngestor
    sid = MoexIngestor.snapshot_id_for(VAL)
    job = _job()
    job.run(VAL)
    first = job.db.get_fx_rates(sid)
    job.run(VAL)  # second run upserts, no duplication
    second = job.db.get_fx_rates(sid)
    assert first == second
    assert len(job.db.get_curve_points(sid, "GCURVE_RUB")) == 6  # one row per (snapshot, tenor)


def test_eod_job_isolates_failing_source():
    # options endpoint fails; everything else still ingests and snapshot still builds
    job = _job(fail_paths=["engines/futures/markets/options/securities"])
    summary = job.run(VAL)
    assert str(summary["steps"]["vol_surface"]).startswith("error:")
    assert summary["steps"]["gcurve"] == 6
    assert summary["snapshot"]["source"] == "MOEX"


def test_eod_job_without_cbr_client():
    job = EodIngestJob(MarketDataDB(":memory:"), _iss(), cbr_client=None,
                       indices=["IMOEX"], equities=["SBER"])
    summary = job.run(VAL)
    assert "cbr_key_rate" not in summary["steps"]
    assert summary["snapshot"]["source"] == "MOEX"


# ── scheduler ────────────────────────────────────────────

def test_schedule_due_after_run_time():
    sched = EodSchedule(run_time="19:00", weekdays_only=False)
    assert sched.is_due(datetime(2026, 6, 2, 19, 30)) is True
    assert sched.is_due(datetime(2026, 6, 2, 18, 0)) is False


def test_schedule_not_due_after_last_run():
    sched = EodSchedule(run_time="19:00", weekdays_only=False)
    last = datetime(2026, 6, 2, 19, 5)
    assert sched.is_due(datetime(2026, 6, 2, 19, 30), last_run=last) is False


def test_schedule_skips_weekends():
    sched = EodSchedule(run_time="19:00", weekdays_only=True)
    sat = date(2026, 6, 2)
    while sat.weekday() != 5:
        sat += timedelta(days=1)
    assert sched.is_due(datetime(sat.year, sat.month, sat.day, 19, 30)) is False


def test_run_if_due_invokes_job_once():
    sched = EodSchedule(run_time="19:00", weekdays_only=False)
    calls = {"n": 0}

    def job():
        calls["n"] += 1
        return "ran"

    ran, result = run_if_due(sched, job, now=datetime(2026, 6, 2, 19, 30))
    assert ran is True and result == "ran" and calls["n"] == 1
    ran2, _ = run_if_due(sched, job, now=datetime(2026, 6, 2, 18, 0))
    assert ran2 is False and calls["n"] == 1
