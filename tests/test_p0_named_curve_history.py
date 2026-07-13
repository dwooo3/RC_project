"""MR-4B: snapshot-bound historical routing for exact named curves."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from api.marketrisk import aggregate_factor_shifts, factor_shifts
from curves.yield_curve import YieldCurve
from domain.portfolio import Position
from infra.db.market_data_db import MarketDataDB
from risk.factor_history import supported_curve_history_tenors
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService


def _dates(n: int = 61) -> list[str]:
    start = date(2026, 1, 1)
    return [(start + timedelta(days=index)).isoformat() for index in range(n)]


def _curve(label: str, rate: float) -> YieldCurve:
    tenors = np.array([1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10], dtype=float)
    return YieldCurve(tenors, np.full(len(tenors), rate), label=label)


class _HistoryDB:
    def __init__(self, series: dict, curves: dict[str, list[dict]]):
        self.series = series
        self.curves = curves

    def get_time_series(self, factor_id, kind=None):
        del kind
        return [dict(dt=dt, value=value)
                for dt, value in self.series.get(factor_id, [])]

    def get_curve_history(self, curve_id, frm=None, till=None):
        return [
            row for row in self.curves.get(curve_id, [])
            if (not frm or row["dt"] >= str(frm)[:10])
            and (not till or row["dt"] <= str(till)[:10])
        ]


def _curve_observations(curve: YieldCurve, dates: list[str], daily_move: float,
                        method: str = "points") -> list[dict]:
    rows = []
    for index, dt in enumerate(dates):
        rows.append({
            "dt": dt,
            "snapshot_id": f"{curve.label}-{dt}",
            "method": method,
            "points": [
                {"tenor": float(tenor),
                 "zero_rate": float(rate + index * daily_move),
                 "discount_factor": None}
                for tenor, rate in zip(curve.tenors, curve.zero_rates)
            ],
        })
    return rows


def _context(*, omit_projection_date: str | None = None,
             projection_method_change: bool = False,
             history_days: int = 61):
    dates = _dates(history_days)
    market = MarketDataService()
    discount = _curve("DISC", 0.10)
    projection = _curve("PROJ", 0.06)
    snapshot = market.create_snapshot(
        snapshot_id="named-history-2026-03-02",
        valuation_date=date(2026, 3, 2),
        curves={"DISC": discount, "PROJ": projection},
    )
    service = PortfolioService(market_data=market, snapshot=snapshot)
    service.add(Position(
        id="irs", instrument="irs", description="dual curve", quantity=1.0,
        params={
            "notional": 1_000_000.0, "fixed_rate": 0.08, "T": 5.0,
            "freq": 4, "r": 0.50, "pay_fixed": True,
            "curve_id": "DISC", "proj_curve_id": "PROJ",
        },
    ))
    series = {
        "IMOEX:price": list(zip(dates, 3000.0 + np.arange(len(dates)))),
        "RVI:price": list(zip(dates, 25.0 + np.arange(len(dates)) * 0.01)),
    }
    for tenor in (0.25, 1.0, 2.0, 5.0, 10.0):
        series[f"KBD:{tenor:g}Y"] = list(
            zip(dates, 0.10 + np.arange(len(dates)) * 0.0003))
    projection_rows = _curve_observations(projection, dates, -0.0002)
    if omit_projection_date:
        projection_rows = [row for row in projection_rows
                           if row["dt"] != omit_projection_date]
    if projection_method_change:
        projection_rows[-1]["method"] = "ois_bootstrap_v2"
    db = _HistoryDB(series, {
        "DISC": _curve_observations(discount, dates, 0.0001),
        "PROJ": projection_rows,
    })
    return SimpleNamespace(
        market_db=db, portfolio=service, market=market, snapshot=snapshot), service


def test_factor_shifts_routes_opposite_histories_by_exact_curve_id():
    ctx, _service = _context()

    shifts = factor_shifts(ctx, window=60)

    assert set(shifts["dr_curves"]) == {"DISC", "PROJ"}
    for values in shifts["dr_curves"]["DISC"].values():
        assert values == pytest.approx(np.full(60, 0.0001))
    for values in shifts["dr_curves"]["PROJ"].values():
        assert values == pytest.approx(np.full(60, -0.0002))
    assert shifts["factor_diagnostics"]["curves"]["DISC"]["ready"] is True
    assert "named curves: DISC, PROJ" in shifts["factors"][1]


def test_factor_calendar_is_capped_at_active_snapshot_valuation_date():
    ctx, _service = _context(history_days=65)

    shifts = factor_shifts(ctx, window=60)

    assert shifts["dates"][-1] == ctx.snapshot.valuation_date.isoformat()
    assert all(day <= ctx.snapshot.valuation_date.isoformat()
               for day in shifts["dates"])


def test_explicit_till_after_active_snapshot_fails_closed():
    ctx, _service = _context(history_days=65)

    with pytest.raises(ValueError, match="after active snapshot valuation date"):
        factor_shifts(ctx, frm="2026-01-01", till="2026-03-03")


def test_calendar_filter_rejects_invalid_iso_suffix_instead_of_truncating():
    ctx, _service = _context(history_days=65)

    with pytest.raises(ValueError, match="must be an ISO calendar date"):
        factor_shifts(ctx, till="2026-03-02garbage")


def test_named_curve_missing_one_calendar_date_fails_without_kbd_proxy():
    missing = _dates()[30]
    ctx, _service = _context(omit_projection_date=missing)

    with pytest.raises(ValueError, match="generic KBD proxy is forbidden"):
        factor_shifts(ctx, window=60)


def test_named_curve_methodology_transition_is_not_a_market_shock():
    ctx, _service = _context(projection_method_change=True)

    with pytest.raises(ValueError, match="changes methodology"):
        factor_shifts(ctx, window=60)


def test_discount_and_projection_receive_independent_node_maps():
    _ctx, service = _context()
    original = service.positions[0]
    base = copy.deepcopy(original)
    shocked = copy.deepcopy(original)
    discount_move = [(tenor, 0.001) for tenor in
                     supported_curve_history_tenors(
                         service.market_data.get_curve("DISC", service.snapshot), 5.0)]
    projection_move = [(tenor, -0.002) for tenor in
                       supported_curve_history_tenors(
                           service.market_data.get_curve("PROJ", service.snapshot), 5.0)]

    service._bind_scenario_curves(
        base, shocked, dr=0.50, dr_curve=[(5.0, 0.25)],
        dr_curves={"DISC": discount_move, "PROJ": projection_move},
    )

    assert shocked.params["curve"].rate(3.0) - base.params["curve"].rate(3.0) \
        == pytest.approx(0.001)
    assert (shocked.params["proj_curve"].rate(3.0)
            - base.params["proj_curve"].rate(3.0)) == pytest.approx(-0.002)


def test_typed_curve_map_missing_projection_fails_closed():
    _ctx, service = _context()
    nodes = supported_curve_history_tenors(
        service.market_data.get_curve("DISC", service.snapshot), 5.0)

    with pytest.raises(ValueError, match="no node shifts for curve 'PROJ'"):
        service.full_reprice_pnl(
            dr_curves={"DISC": [(tenor, 0.001) for tenor in nodes]})


def test_typed_curve_map_rejects_empty_exact_node_set():
    _ctx, service = _context()
    nodes = supported_curve_history_tenors(
        service.market_data.get_curve("PROJ", service.snapshot), 5.0)

    with pytest.raises(ValueError, match="has no node shifts"):
        service.full_reprice_pnl(
            dr=0.50,
            dr_curves={
                "DISC": [],
                "PROJ": [(tenor, -0.001) for tenor in nodes],
            },
        )


def test_curve_history_grid_uses_native_boundary_as_right_bracket():
    curve = YieldCurve(
        np.array([1.0, 6.0]), np.array([0.10, 0.11]), label="SHORT_GRID")

    nodes = supported_curve_history_tenors(curve, required_tenor=5.5)

    assert nodes == pytest.approx((1.0, 2.0, 3.0, 5.0, 6.0))
    assert nodes[-2] < 5.5 < nodes[-1]


def test_curve_history_grid_includes_noncanonical_terminal_native_node():
    curve = YieldCurve(
        np.array([1.0, 6.0]), np.array([0.10, 0.11]), label="SHORT_GRID")

    nodes = supported_curve_history_tenors(curve, required_tenor=6.0)

    assert nodes[-1] == pytest.approx(6.0)


def test_curve_history_grid_preserves_noncanonical_interior_native_nodes():
    curve = YieldCurve(
        np.array([1.0, 4.0, 10.0]), np.array([0.10, 0.13, 0.11]),
        label="NATIVE_INTERIOR", interp="cubic",
    )

    nodes = supported_curve_history_tenors(curve, required_tenor=5.0)

    assert 4.0 in nodes
    assert nodes[0] == pytest.approx(1.0)
    assert nodes[-1] == pytest.approx(10.0)


def test_named_curve_rejects_required_tenor_below_native_support():
    curve = YieldCurve(
        np.array([1.0, 6.0]), np.array([0.10, 0.11]), label="SHORT_GRID")

    with pytest.raises(ValueError, match="starts at 1Y"):
        supported_curve_history_tenors(curve, required_tenor=0.5)


def test_exact_curve_map_must_cover_complete_native_support():
    _ctx, service = _context()

    with pytest.raises(ValueError, match="below native upper support 10Y"):
        service.full_reprice_pnl(
            dr_curves={"DISC": [(1.0 / 12.0, 0.001), (1.0, 0.001)],
                       "PROJ": [(1.0 / 12.0, 0.001), (1.0, 0.001)]},
        )

    with pytest.raises(ValueError, match="above native lower support"):
        service.full_reprice_pnl(
            dr_curves={"DISC": [(1.0, 0.001), (5.0, 0.001)],
                       "PROJ": [(1.0, 0.001), (5.0, 0.001)]},
        )


def test_cubic_curve_scenario_cannot_flat_extrapolate_beyond_held_maturity():
    _ctx, service = _context()

    # A 5Y IRS still uses a globally interpolated cubic curve whose 7Y/10Y
    # native nodes influence rates inside 5Y.  A map ending at 5Y must fail.
    with pytest.raises(ValueError, match="below native upper support 10Y"):
        service.full_reprice_pnl(
            dr_curves={
                "DISC": [(1.0 / 12.0, 0.001), (1.0, 0.002), (5.0, 0.003)],
                "PROJ": [(1.0 / 12.0, 0.001), (1.0, 0.002), (5.0, 0.003)],
            },
        )


def test_named_irs_curve_must_cover_first_coupon_not_only_maturity():
    market = MarketDataService()
    short = YieldCurve(
        np.array([1.0, 5.0, 10.0]), np.array([0.10, 0.09, 0.08]),
        label="TOO_LATE", interp="cubic",
    )
    snapshot = market.create_snapshot(
        snapshot_id="late-start", valuation_date=date(2026, 3, 2),
        curves={"TOO_LATE": short},
    )
    service = PortfolioService(market_data=market, snapshot=snapshot)
    service.add(Position(
        id="irs", instrument="irs", description="quarterly IRS", quantity=1.0,
        params={
            "notional": 1_000_000.0, "fixed_rate": 0.08, "T": 5.0,
            "freq": 4, "curve_id": "TOO_LATE", "pay_fixed": True,
        },
    ))

    result = service.price_all()

    assert any("above first required 0.25Y" in error for error in result.errors)


def test_horizon_aggregation_preserves_nested_curve_identity():
    ctx, _service = _context()
    daily = factor_shifts(ctx, window=60)

    aggregated, method = aggregate_factor_shifts(daily, 2, min_windows=1)

    assert method == "factor_aggregation_full_reprice"
    for values in aggregated["dr_curves"]["DISC"].values():
        assert values == pytest.approx(np.full(59, 0.0002))
    for values in aggregated["dr_curves"]["PROJ"].values():
        assert values == pytest.approx(np.full(59, -0.0004))


def test_curve_replace_removes_stale_nodes_and_rejects_invalid_before_delete():
    db = MarketDataDB(":memory:")
    db.save_curve(
        "s1", "DISC", method="points", nss_params={}, as_of="2026-01-02",
        points=[(1.0, 0.10, None), (5.0, 0.12, None)],
    )
    db.save_curve(
        "s1", "DISC", method="points", nss_params={}, as_of="2026-01-02",
        points=[(2.0, 0.11, None)],
    )
    assert db.get_curve_points("s1", "DISC") == [{
        "tenor": 2.0, "zero_rate": 0.11, "discount_factor": None,
    }]

    with pytest.raises(ValueError, match="duplicate tenor"):
        db.save_curve(
            "s1", "DISC", method="points", nss_params={}, as_of="2026-01-02",
            points=[(2.0, 0.11, None), (2.0, 0.12, None)],
        )
    assert db.get_curve_points("s1", "DISC") == [{
        "tenor": 2.0, "zero_rate": 0.11, "discount_factor": None,
    }]
    db.close()


def test_curve_history_deduplicates_identical_date_and_rejects_conflict():
    db = MarketDataDB(":memory:")
    for snapshot_id in ("s1", "s2"):
        db.save_curve(
            snapshot_id, "DISC", method="points", nss_params={},
            as_of="2026-01-02", points=[(1.0, 0.10, None)],
        )
    history = db.get_curve_history("DISC")
    assert len(history) == 1
    assert history[0]["dt"] == "2026-01-02"

    db.save_curve(
        "s2", "DISC", method="points", nss_params={},
        as_of="2026-01-02", points=[(1.0, 0.20, None)],
    )
    with pytest.raises(ValueError, match="conflicting snapshots"):
        db.get_curve_history("DISC")
    db.close()


def test_curve_history_ignores_holiday_header_without_nodes():
    db = MarketDataDB(":memory:")
    db.save_curve(
        "holiday", "DISC", method="points", nss_params={},
        as_of="2026-01-01", points=[(1.0, 0.10, None)],
    )
    db._exec(  # noqa: SLF001 - reproduce a legacy placeholder header
        "DELETE FROM curve_points WHERE snapshot_id=? AND curve_id=?",
        ("holiday", "DISC"),
    )
    db.save_curve(
        "trading-day", "DISC", method="points", nss_params={},
        as_of="2026-01-02", points=[(1.0, 0.11, None)],
    )

    history = db.get_curve_history("DISC")

    assert [(row["dt"], len(row["points"])) for row in history] == [
        ("2026-01-02", 1),
    ]
    db.close()
