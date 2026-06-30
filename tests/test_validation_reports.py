"""Persisted validation reports (recommendations MD-002): the COMPUTED quality
status per snapshot is saved as an audit trail (deduped on no change)."""
import datetime as dt

import pytest

from infra.db.market_data_db import MarketDataDB
from infra.jobs.data_quality import persist_quality_report

SID = "moex-2026-06-26"


@pytest.fixture
def db():
    d = MarketDataDB(":memory:")
    d.save_snapshot_meta(snapshot_id=SID, valuation_date=dt.date(2026, 6, 26),
                         source="MOEX", quality="OK", fetch_ts=dt.datetime(2026, 6, 26, 19))
    return d


def test_report_is_persisted(db):
    report = persist_quality_report(db, SID)
    stored = db.latest_validation_report(db and SID)
    assert stored is not None
    assert stored["status"] == report["status"]
    assert stored["snapshot_id"] == SID


def test_dedup_on_no_change(db):
    persist_quality_report(db, SID)
    n = len(db.list_validation_reports(SID))
    persist_quality_report(db, SID)            # identical → no new row
    assert len(db.list_validation_reports(SID)) == n


def test_history_returned(db):
    persist_quality_report(db, SID)
    hist = db.list_validation_reports(SID)
    assert len(hist) >= 1
    assert "status" in hist[0] and "validation_ts" in hist[0]
