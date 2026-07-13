"""Workstation IV defaults must respect lineage and the active snapshot date."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from api.underlying import _atm_iv, _iv_history_last
from infra.db.market_data_db import MarketDataDB
from infra.jobs.data_quality import (
    QUALITY_CONTRACT_VERSION,
    snapshot_data_fingerprint,
)
from infra.moex_iss.vol_surface import build_vol_surfaces
from services.market_data_service import MarketDataService


class _SeriesDB:
    def __init__(self, rows):
        self.rows = rows

    def get_time_series(self, factor_id, kind):
        assert kind == "vol"
        return list(self.rows.get(factor_id, []))


def _ctx(rows):
    return SimpleNamespace(
        snapshot=SimpleNamespace(valuation_date=date(2026, 7, 13)),
        market_db=_SeriesDB(rows),
    )


def test_workstation_rejects_fresh_orphan_iv30_and_uses_legacy_fallback():
    ctx = _ctx({
        "IV30:MIX": [{"dt": "2026-07-10", "value": 0.31}],
        "IV:MIX": [{"dt": "2026-07-13", "value": 0.22}],
    })

    assert _iv_history_last(ctx, "MIX") == 0.22


def test_workstation_ignores_stale_or_future_iv_and_uses_fresh_fallback():
    ctx = _ctx({
        "IV30:MIX": [
            {"dt": "2026-06-30", "value": 0.40},
            {"dt": "2026-07-14", "value": 0.50},
        ],
        "IV:MIX": [{"dt": "2026-07-11", "value": 0.24}],
    })

    assert _iv_history_last(ctx, "MIX") == 0.24


def test_workstation_returns_none_when_all_iv_is_stale():
    ctx = _ctx({
        "IV30:MIX": [{"dt": "2026-06-30", "value": 0.40}],
        "IV:MIX": [{"dt": "2026-07-01", "value": 0.24}],
    })

    assert _iv_history_last(ctx, "MIX") is None


def test_workstation_accepts_iv30_only_with_governed_snapshot_lineage():
    day = date(2026, 7, 13)
    db = MarketDataDB(":memory:")
    db.save_snapshot_meta(
        snapshot_id=f"moex-{day.isoformat()}",
        valuation_date=day,
        source="MOEX",
        quality="OK",
        fetch_ts=datetime.combine(day, datetime.min.time()),
    )

    def point(strike: float) -> dict:
        return {
            "underlying": "MIX",
            "expiry": (day + timedelta(days=30)).isoformat(),
            "strike": strike,
            "iv": 0.31,
            "forward": 100.0,
            "tenor_days": 30,
            "open_interest": 100.0,
            "observation_date": day.isoformat(),
            "source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
            "method": "black76_settlement",
            "observation_status": "verified",
            "option_price_date": day.isoformat(),
            "forward_date": day.isoformat(),
            "option_price_source": "MOEX_FORTS_OPTION_SETTLEMENT",
            "forward_source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
            "option_price_basis": "settlement",
            "forward_basis": "underlying_settlement",
        }

    db.replace_vol_surface(
        f"moex-{day.isoformat()}", [point(90.0), point(110.0)])
    db.replace_iv30_for_date(day, {"MIX": 0.31})
    snapshot_id = f"moex-{day.isoformat()}"
    db.save_validation_report(snapshot_id, {
        "status": "OK",
        "production_eligible": True,
        "completeness_pct": 100.0,
        "staleness_days": 0,
        "alerts": [],
        "checks": {
            "contract_version": QUALITY_CONTRACT_VERSION,
            "snapshot_fingerprint": snapshot_data_fingerprint(
                db, snapshot_id
            ),
        },
    })
    ctx = SimpleNamespace(
        snapshot=SimpleNamespace(valuation_date=day),
        market_db=db,
    )

    assert _iv_history_last(ctx, "MIX") == 0.31


def test_workstation_surface_must_match_rows_bound_to_active_snapshot():
    day = date(2026, 7, 13)
    sid = f"moex-{day.isoformat()}"
    db = MarketDataDB(":memory:")

    def point(strike: float, iv: float) -> dict:
        return {
            "underlying": "MIX",
            "expiry": (day + timedelta(days=30)).isoformat(),
            "strike": strike,
            "iv": iv,
            "forward": 100.0,
            "tenor_days": 30,
            "open_interest": 100.0,
            "observation_date": day.isoformat(),
            "source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
            "method": "black76_settlement",
            "observation_status": "verified",
            "option_price_date": day.isoformat(),
            "forward_date": day.isoformat(),
            "option_price_source": "MOEX_FORTS_OPTION_SETTLEMENT",
            "forward_source": "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
            "option_price_basis": "settlement",
            "forward_basis": "underlying_settlement",
        }

    original = [point(90.0, 0.31), point(110.0, 0.31)]
    db.replace_vol_surface(sid, original)
    market = MarketDataService(market_db=db)
    snapshot = market.create_snapshot(
        snapshot_id=sid,
        valuation_date=day,
        vol_surfaces=build_vol_surfaces(original),
    )
    ctx = SimpleNamespace(snapshot=snapshot, market_db=db, market=market)

    assert _atm_iv(ctx, "MIX", 100.0) == 0.31
    db.replace_vol_surface(sid, [point(90.0, 0.45), point(110.0, 0.45)])
    assert _atm_iv(ctx, "MIX", 100.0) is None
