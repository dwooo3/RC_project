"""Bounded reconstruction contract for snapshot ids pinned by saved runs."""

from datetime import date, datetime

import pytest

from domain.market_data import MarketDataSource
from infra.db.market_data_db import MarketDataDB
from services.market_data_service import MarketDataService


VAL = date(2026, 6, 4)
SID = f"moex-{VAL.isoformat()}"


def _save_manifest(
    db: MarketDataDB,
    snapshot_id: str,
    valuation_date: date,
    *,
    source: str = "MOEX",
    quality: str = "OK",
) -> None:
    db.save_snapshot_meta(
        snapshot_id=snapshot_id,
        valuation_date=valuation_date,
        source=source,
        quality=quality,
        fetch_ts=datetime(2026, 6, 4, 19, 0),
        iss_request_urls=["https://iss.moex.com/pinned"],
        metadata={"lineage": "authoritative"},
    )


def _governed_moex_db(*, quality: str = "OK") -> MarketDataDB:
    db = MarketDataDB(":memory:")
    _save_manifest(db, SID, VAL, quality=quality)
    db.save_curve(
        SID,
        "GCURVE_RUB",
        method="points",
        nss_params={},
        as_of=VAL,
        points=[
            (0.25, 0.155, 0.962),
            (1.0, 0.145, 0.865),
            (5.0, 0.127, 0.530),
        ],
    )
    db.save_fx_rate(SID, "USD/RUB", 74.366, source="MOEX")
    db.save_fx_rate(SID, "EUR/RUB", 86.271, source="MOEX")
    return db


def test_resolver_returns_exact_in_memory_manual_snapshot_first():
    service = MarketDataService()
    original = service.manual_snapshot(
        "manual-pinned",
        valuation_date=VAL,
        fx_rates={"USD/RUB": 91.25},
    )

    assert service.resolve_pinned_snapshot("manual-pinned") is original
    assert service.resolve_snapshot("manual-pinned") is original
    assert service.last_fallback_used is False


def test_demo_id_is_deterministically_rebuilt_and_cached():
    service = MarketDataService()
    snapshot_id = "demo-2026-06-03"

    rebuilt = service.resolve_pinned_snapshot(snapshot_id)

    assert rebuilt.snapshot_id == snapshot_id
    assert rebuilt.valuation_date == date(2026, 6, 3)
    assert rebuilt.source == MarketDataSource.DEMO
    assert service.get_snapshot(snapshot_id) is rebuilt
    assert service.last_fallback_used is False  # explicitly pinned DEMO is not fallback


def test_moex_snapshot_is_reconstructed_from_exact_authoritative_manifest():
    db = _governed_moex_db(quality="WARN")
    # A later manifest is present to prove resolution is exact-id, not latest.
    later = date(2026, 6, 10)
    _save_manifest(db, f"moex-{later.isoformat()}", later)
    service = MarketDataService(market_db=db)

    rebuilt = service.resolve_pinned_snapshot(SID)

    assert rebuilt.snapshot_id == SID
    assert rebuilt.valuation_date == VAL
    assert rebuilt.source == MarketDataSource.MOEX
    assert rebuilt.quality == "WARN"  # authoritative historical verdict is preserved
    assert rebuilt.metadata["lineage"] == "authoritative"
    assert "GCURVE_RUB" in rebuilt.curves
    assert rebuilt.fx_rates["USD/RUB"] == pytest.approx(74.366)
    assert service.get_snapshot(SID) is rebuilt
    assert service.resolve_pinned_snapshot(SID) is rebuilt
    assert service.last_fallback_used is False


@pytest.mark.parametrize("snapshot_id", [
    "manual-after-restart",
    "csv-after-restart",
    "moex-2026-06-03",
    "unknown",
])
def test_unknown_or_unpersisted_snapshot_fails_closed(snapshot_id):
    service = MarketDataService(market_db=MarketDataDB(":memory:"))
    service.last_fallback_used = True  # stale state from an earlier broad resolution

    with pytest.raises(KeyError):
        service.resolve_pinned_snapshot(snapshot_id)

    assert service.last_fallback_used is False
    assert service.store.list_versions(snapshot_id) == []


def test_manual_manifest_cannot_reconstruct_missing_manual_payload():
    db = MarketDataDB(":memory:")
    _save_manifest(
        db,
        "manual-after-restart",
        VAL,
        source="MANUAL",
        quality="MANUAL",
    )
    service = MarketDataService(market_db=db)

    with pytest.raises(KeyError, match="cannot be reconstructed after restart"):
        service.resolve_pinned_snapshot("manual-after-restart")


def test_moex_shaped_id_without_manifest_does_not_use_raw_rows_or_demo():
    db = MarketDataDB(":memory:")
    db.save_curve(
        SID,
        "GCURVE_RUB",
        method="points",
        nss_params={},
        as_of=VAL,
        points=[(0.25, 0.155, 0.962), (1.0, 0.145, 0.865)],
    )
    db.save_fx_rate(SID, "USD/RUB", 74.366, source="MOEX")
    service = MarketDataService(market_db=db)

    with pytest.raises(KeyError, match="no authoritative DB manifest"):
        service.resolve_pinned_snapshot(SID)


def test_manifest_id_date_mismatch_fails_closed():
    db = MarketDataDB(":memory:")
    _save_manifest(db, SID, date(2026, 6, 5))
    service = MarketDataService(market_db=db)

    with pytest.raises(KeyError, match="id/date mismatch"):
        service.resolve_pinned_snapshot(SID)


@pytest.mark.parametrize("snapshot_id", [
    "demo-not-a-date",
    "demo-2026-6-3",
    " demo-2026-06-03",
    "demo-2026-06-03 ",
    "",
])
def test_malformed_demo_or_non_exact_id_is_rejected(snapshot_id):
    service = MarketDataService()

    with pytest.raises((KeyError, ValueError)):
        service.resolve_pinned_snapshot(snapshot_id)
