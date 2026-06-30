"""Strict-live mode (recommendations MD-001): production mode never falls back to
DEMO silently — it raises — while research/demo keep the historical fallback."""
import datetime as dt

import pytest

from domain.market_data import MarketDataMode
from services.market_data_service import MarketDataService, NoProductionMarketDataError


def test_mode_accepts_string():
    assert MarketDataService(mode="production").mode == MarketDataMode.PRODUCTION
    assert MarketDataService().mode == MarketDataMode.RESEARCH        # default


def test_research_falls_back_to_demo_without_db():
    svc = MarketDataService(mode="research")          # no market_db
    snap = svc.best_available_snapshot()
    assert snap.is_demo
    assert svc.last_fallback_used is True


def test_production_raises_without_db():
    svc = MarketDataService(mode="production")
    with pytest.raises(NoProductionMarketDataError):
        svc.best_available_snapshot()


def test_production_moex_snapshot_raises_without_data():
    svc = MarketDataService(mode="production")
    with pytest.raises(NoProductionMarketDataError):
        svc.moex_snapshot(dt.date(2026, 6, 26))       # no provider data → no silent demo


def test_research_moex_snapshot_falls_back():
    svc = MarketDataService(mode="research")
    snap = svc.moex_snapshot(dt.date(2026, 6, 26))
    assert snap.is_demo and svc.last_fallback_used is True


def test_explicit_fallback_flag_overrides_mode():
    svc = MarketDataService(mode="research")
    with pytest.raises(NoProductionMarketDataError):
        svc.moex_snapshot(dt.date(2026, 6, 26), fallback_to_demo=False)
