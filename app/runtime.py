"""
Application runtime wiring (Stage II).

Single place that decides whether the app runs on the real local market-data DB
or the demo fallback. Panels call `market_service()` / `active_snapshot()`
instead of constructing `MarketDataService()` directly, so connecting the real
snapshot is a one-line change rather than per-panel surgery.

DB resolution: $RISKCALC_DB, else data/market_data.sqlite next to the repo,
else None (demo mode). The MarketDataService is process-cached so every panel
shares one DB connection and one snapshot.
"""

from __future__ import annotations

import os
from pathlib import Path

from services.market_data_service import MarketDataService

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _REPO_ROOT / "data" / "market_data.sqlite"

_service: MarketDataService | None = None


def db_path() -> str | None:
    """Resolve the market-data DB path, or None for demo mode."""
    env = os.environ.get("RISKCALC_DB")
    if env:
        return env if Path(env).exists() else None
    return str(_DEFAULT_DB) if _DEFAULT_DB.exists() else None


def market_mode():
    """Operating contour from $RISKCALC_MODE (demo|research|production); default
    research (silent demo fallback allowed). Production forbids silent fallback."""
    from domain.market_data import MarketDataMode
    try:
        return MarketDataMode(os.environ.get("RISKCALC_MODE", "research").lower())
    except ValueError:
        return MarketDataMode.RESEARCH


def market_service(refresh: bool = False) -> MarketDataService:
    """Process-cached MarketDataService bound to the real DB when available."""
    global _service
    if _service is not None and not refresh:
        return _service
    path = db_path()
    mode = market_mode()
    if path:
        from infra.db.market_data_db import MarketDataDB
        _service = MarketDataService(market_db=MarketDataDB(path), mode=mode)
    else:
        _service = MarketDataService(mode=mode)
    return _service


def active_snapshot(svc: MarketDataService | None = None):
    """Best available snapshot: latest real MOEX, else demo."""
    svc = svc or market_service()
    return svc.best_available_snapshot()


def is_live() -> bool:
    """True when running on a real market-data DB (not demo)."""
    return db_path() is not None
