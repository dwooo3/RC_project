"""MR-4B: governed sticky-strike history for named volatility surfaces."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from api.marketrisk import factor_shifts
from domain.portfolio import Position
from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.vol_surface import PRIMARY_IV_METHOD, build_vol_surfaces
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService


def _dates(n: int = 61) -> list[str]:
    start = date(2026, 1, 1)
    return [(start + timedelta(days=index)).isoformat() for index in range(n)]


def _points(day: str, daily_offset: float = 0.0, *, verified: bool = True):
    as_of = date.fromisoformat(day)
    rows = []
    for tenor_days, base_vol in ((60, 0.25), (120, 0.30)):
        expiry = (as_of + timedelta(days=tenor_days)).isoformat()
        for strike in (90.0, 100.0, 110.0, 120.0):
            rows.append({
                "underlying": "TEST",
                "expiry": expiry,
                "strike": strike,
                "iv": base_vol + daily_offset + (strike - 100.0) * 0.0002,
                "forward": 100.0,
                "tenor_days": tenor_days,
                "open_interest": 100.0,
                "observation_date": day,
                "source": "MOEX_FORTS_FUTURES_SETTLEMENT",
                "method": PRIMARY_IV_METHOD,
                "observation_status": "verified" if verified else "unverified",
                "option_price_date": day,
                "forward_date": day,
                "option_price_source": "MOEX_FORTS_OPTION_SETTLEMENT",
                "forward_source": "MOEX_FORTS_FUTURES_SETTLEMENT",
                "option_price_basis": "settlement",
                "forward_basis": "settlement",
            })
    return rows


class _HistoryDB:
    def __init__(self, series, surfaces, current_points):
        self.series = series
        self.surfaces = surfaces
        self.current_points = list(current_points)

    def get_time_series(self, factor_id, kind=None):
        del kind
        return [dict(dt=dt, value=value)
                for dt, value in self.series.get(factor_id, [])]

    def get_vol_surface_history(self, surface_id, frm=None, till=None):
        return [
            row for row in self.surfaces.get(surface_id, [])
            if (not frm or row["dt"] >= str(frm)[:10])
            and (not till or row["dt"] <= str(till)[:10])
        ]

    def get_vol_points(self, snapshot_id):
        del snapshot_id
        return [
            {key: point.get(key) for key in (
                "underlying", "expiry", "strike", "iv",
            )}
            for point in self.current_points
        ]

    def get_vol_point_observations(self, snapshot_id):
        del snapshot_id
        return [dict(point) for point in self.current_points]


def _context(*, missing_day: str | None = None, verified: bool = True,
             two_surfaces: bool = False, flat_current: bool = False):
    dates = _dates()
    market = MarketDataService()
    snapshot_day = date(2026, 3, 2)
    current_points = _points(snapshot_day.isoformat(), daily_offset=0.03)
    if two_surfaces:
        alt_points = _points(snapshot_day.isoformat(), daily_offset=0.08)
        for point in alt_points:
            point["underlying"] = "ALT"
        current_points.extend(alt_points)
    surfaces = build_vol_surfaces(current_points)
    if flat_current:
        surfaces["TEST_FORTS"] = {"type": "flat", "vol": 0.28}
    snapshot = market.create_snapshot(
        snapshot_id="surface-history-2026-03-02",
        valuation_date=snapshot_day,
        vol_surfaces=surfaces,
    )
    service = PortfolioService(market_data=market, snapshot=snapshot)
    service.add(Position(
        id="opt-test", instrument="option", description="TEST surface",
        quantity=1.0,
        params={
            "S": 100.0, "K": 100.0, "T": 90 / 365,
            "r": 0.05, "sigma": 0.10, "q": 0.0, "opt": "call",
            "secid": "SAME", "vol_surface_id": "TEST_FORTS",
        },
    ))
    if two_surfaces:
        service.add(Position(
            id="opt-alt", instrument="option", description="ALT surface",
            quantity=1.0,
            params={
                "S": 100.0, "K": 100.0, "T": 90 / 365,
                "r": 0.05, "sigma": 0.10, "q": 0.0, "opt": "call",
                "secid": "SAME", "vol_surface_id": "ALT_FORTS",
            },
        ))
    series = {
        "IMOEX:price": list(zip(dates, 3000.0 + np.arange(len(dates)))),
        "RVI:price": list(zip(dates, 25.0 + np.arange(len(dates)) * 0.01)),
    }
    for tenor in (0.25, 1.0, 2.0, 5.0, 10.0):
        series[f"KBD:{tenor:g}Y"] = list(
            zip(dates, 0.10 + np.arange(len(dates)) * 0.0001))

    def observations(surface_id: str, daily_move: float):
        underlying = surface_id.removesuffix("_FORTS")
        rows = []
        for index, day in enumerate(dates):
            if day == missing_day:
                continue
            points = _points(day, index * daily_move, verified=verified)
            for point in points:
                point["underlying"] = underlying
            rows.append({
                "dt": day,
                "snapshot_id": f"{surface_id}-{day}",
                "surface_id": surface_id,
                "points": points,
            })
        return rows

    db = _HistoryDB(series, {
        "TEST_FORTS": observations("TEST_FORTS", 0.001),
        "ALT_FORTS": observations("ALT_FORTS", -0.0005),
    }, current_points)
    return SimpleNamespace(
        market_db=db, portfolio=service, market=market, snapshot=snapshot), service


def test_named_surface_history_routes_by_position_not_shared_secid():
    ctx, _service = _context(two_surfaces=True)

    shifts = factor_shifts(ctx, window=60)

    assert shifts["dvol_positions"]["opt-test"] == pytest.approx(
        np.full(60, 0.001), abs=5e-6)
    assert shifts["dvol_positions"]["opt-alt"] == pytest.approx(
        np.full(60, -0.0005), abs=5e-6)
    assert shifts["factor_diagnostics"]["surfaces"]["opt-test"]["ready"] is True


def test_named_surface_missing_date_fails_without_rvi_proxy():
    ctx, _service = _context(missing_day=_dates()[20])

    with pytest.raises(ValueError, match="IV30/RVI proxy is forbidden"):
        factor_shifts(ctx, window=60)


def test_named_surface_rejects_active_raw_provenance_value_mismatch():
    ctx, _service = _context()
    original = ctx.market_db.get_vol_points

    def mismatched(snapshot_id):
        rows = original(snapshot_id)
        rows[0]["iv"] += 0.10
        return rows

    ctx.market_db.get_vol_points = mismatched

    with pytest.raises(ValueError, match="raw/provenance payload"):
        factor_shifts(ctx, window=60)


def test_named_surface_rejects_cached_grid_that_differs_from_current_db_rows():
    ctx, _service = _context()
    # Mutate raw and provenance together under the same snapshot ID.  Their
    # lineage remains internally consistent, but the already-bound snapshot
    # still carries the old grid and must not be certified by the new rows.
    ctx.market_db.current_points[0]["iv"] += 0.10

    with pytest.raises(ValueError, match="cached_surface_snapshot_mismatch"):
        factor_shifts(ctx, window=60)


def test_named_surface_rejects_unverified_point_lineage():
    ctx, _service = _context(verified=False)

    with pytest.raises(ValueError, match="provenance"):
        factor_shifts(ctx, window=60)


def test_named_surface_rejects_flat_forts_alias_in_active_snapshot():
    ctx, _service = _context(flat_current=True)

    with pytest.raises(ValueError, match="not a governed FORTS grid identity"):
        factor_shifts(ctx, window=60)


def test_reprice_prefers_position_surface_move_over_per_name_proxy():
    _ctx, service = _context()

    exact = service.full_reprice_pnl(
        dvol=0.20,
        dvol_by_name={"SAME": 0.10},
        dvol_by_position={"opt-test": 0.01},
    )
    current_sigma, _warning = service.pricing.resolve_vol_surface(
        "TEST_FORTS", 100.0, 90 / 365, S=100.0,
        snapshot=service.snapshot,
    )
    expected_base = service.pricing.price_vanilla_option(
        100.0, 100.0, 90 / 365, 0.05, current_sigma, 0.0, "call",
        snapshot=service.snapshot,
    )["value"]
    expected_up = service.pricing.price_vanilla_option(
        100.0, 100.0, 90 / 365, 0.05, current_sigma + 0.01, 0.0, "call",
        snapshot=service.snapshot,
    )["value"]
    assert exact["pnl"] == pytest.approx(expected_up - expected_base)


def test_typed_surface_map_missing_position_and_invalid_sigma_fail_closed():
    _ctx, service = _context()

    with pytest.raises(ValueError, match="no node shift for vol surface"):
        service.full_reprice_pnl(dvol_by_position={})
    with pytest.raises(ValueError, match="invalid sigma"):
        service.full_reprice_pnl(dvol_by_position={"opt-test": -5.0})


def test_db_surface_history_uses_verified_table_and_rejects_identity_conflict():
    db = MarketDataDB(":memory:")
    points = _points("2026-01-02")
    db.replace_vol_surface("s1", points)
    db.replace_vol_surface("s2", points)
    history = db.get_vol_surface_history("TEST_FORTS")
    assert len(history) == 1
    assert history[0]["dt"] == "2026-01-02"
    assert len(history[0]["points"]) == 8

    changed = _points("2026-01-02")
    changed[0]["iv"] += 0.05
    db.replace_vol_surface("s2", changed)
    with pytest.raises(ValueError, match="conflicting snapshots"):
        db.get_vol_surface_history("TEST_FORTS")

    changed = _points("2026-01-02")
    changed[0]["tenor_days"] += 1
    db.replace_vol_surface("s2", changed)
    with pytest.raises(ValueError, match="conflicting snapshots"):
        db.get_vol_surface_history("TEST_FORTS")
    with pytest.raises(ValueError, match="no governed historical identity"):
        db.get_vol_surface_history("flat_demo")
    db.close()
