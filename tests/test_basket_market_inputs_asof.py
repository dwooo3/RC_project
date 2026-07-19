"""Snapshot/as-of and evidence contract for structured-product basket inputs."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from domain.market_data import MarketDataSnapshot, MarketDataSource
from infra.db.market_data_db import MarketDataDB
from services.market_data_service import MarketDataService


AS_OF = date(2026, 7, 1)
SID = "moex-2026-07-01"


def _snapshot() -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id=SID,
        valuation_date=AS_OF,
        source=MarketDataSource.MOEX,
        quality="OK",
    )


def _save_meta(db: MarketDataDB, sid: str, valuation_date: date) -> None:
    db.save_snapshot_meta(
        snapshot_id=sid,
        valuation_date=valuation_date,
        source="MOEX",
        quality="OK",
        fetch_ts=datetime.combine(valuation_date, datetime.min.time()),
    )


def _prices(start: date, count: int, initial: float, phase: int = 0):
    price = initial
    points = []
    for index in range(count):
        # Non-zero, deterministic return variance for volatility/correlation.
        shock = (0.008 if (index + phase) % 3 == 0 else
                 -0.004 if (index + phase) % 3 == 1 else 0.002)
        price *= np.exp(shock)
        points.append(((start + timedelta(days=index)).isoformat(), float(price)))
    return points


def _seed_governed_basket() -> tuple[MarketDataDB, MarketDataService]:
    db = MarketDataDB(":memory:")
    _save_meta(db, SID, AS_OF)
    db.save_equity_quote(SID, {"secid": "AAA", "last": 150.0, "board": "TQBR"})
    db.save_equity_quote(SID, {"secid": "BBB", "last": 250.0, "board": "TQBR"})

    # A later snapshot deliberately exists and must never leak into an explicitly
    # requested historical valuation.
    later = date(2026, 7, 10)
    later_sid = f"moex-{later.isoformat()}"
    _save_meta(db, later_sid, later)
    db.save_equity_quote(later_sid, {"secid": "AAA", "last": 999.0, "board": "TQBR"})
    db.save_equity_quote(later_sid, {"secid": "BBB", "last": 888.0, "board": "TQBR"})

    db.save_time_series(
        "AAA:price",
        "price",
        _prices(date(2026, 6, 1), 30, 100.0) + [("2026-07-02", 9_999.0)],
    )
    # Shifted calendar: both legs have 29 returns, but only 28 return dates overlap.
    db.save_time_series(
        "BBB:price",
        "price",
        _prices(date(2026, 6, 2), 30, 200.0, phase=1) + [("2026-07-02", 8_888.0)],
    )
    db.save_dividends("AAA", [
        {"registry_date": "2026-06-15", "value": 15.0, "currency": "RUB"},
        {"registry_date": "2026-07-05", "value": 900.0, "currency": "RUB"},
    ])
    db.save_dividends("BBB", [
        {"registry_date": "2026-05-15", "value": 25.0, "currency": "RUB"},
        {"registry_date": "2026-07-03", "value": 900.0, "currency": "RUB"},
    ])
    return db, MarketDataService(market_db=db)


def test_explicit_snapshot_cuts_future_data_and_ignores_latest_snapshot():
    db, service = _seed_governed_basket()
    specs = [
        {"secid": "AAA", "kind": "equity", "weight": 0.6},
        {"secid": "BBB", "kind": "equity", "weight": 0.4},
    ]

    constituents, corr, evidence = service.basket_market_inputs(
        specs, 3.0, snapshot=_snapshot(), include_evidence=True,
    )

    assert [item.spot for item in constituents] == [150.0, 250.0]
    assert constituents[0].income == pytest.approx(15.0 / 150.0)
    assert constituents[1].income == pytest.approx(25.0 / 250.0)
    assert evidence["snapshot"]["snapshot_id"] == SID
    assert evidence["snapshot"]["selection"] == "explicit"
    assert evidence["history_cutoff"] == AS_OF.isoformat()
    assert evidence["constituents"][0]["history"]["last_level_date"] == "2026-06-30"
    assert evidence["constituents"][1]["history"]["last_level_date"] == "2026-07-01"
    assert evidence["constituents"][0]["history"]["future_observations_excluded"] == 1
    assert evidence["constituents"][1]["history"]["future_observations_excluded"] == 1
    assert evidence["constituents"][0]["income"]["effective_date"] == "2026-06-15"
    assert evidence["constituents"][1]["income"]["effective_date"] == "2026-05-15"

    pair = evidence["correlation"]["pairs"][0]
    assert pair["source"] == "aligned_time_series_log_returns"
    assert pair["sample_count"] == 28
    assert pair["start_date"] == "2026-06-03"
    assert pair["end_date"] == "2026-06-30"
    assert not pair["fallback"]
    assert np.allclose(evidence["resolved_inputs"]["correlation"], corr)

    # Every externally effective observation is at or before the governed cutoff.
    effective_dates = []
    for item in evidence["constituents"]:
        effective_dates.extend(
            item[field]["effective_date"] for field in ("spot", "vol", "income")
            if item[field]["effective_date"] is not None
        )
    effective_dates.extend(
        row["effective_date"] for row in evidence["correlation"]["pairs"]
        if row["effective_date"] is not None
    )
    assert all(date.fromisoformat(value) <= AS_OF for value in effective_dates)

    # Changing excluded future observations cannot alter resolved pricing inputs/hash.
    original_hash = evidence["resolved_inputs_hash"]
    assert len(original_hash) == 64
    db.save_time_series("AAA:price", "price", [("2026-07-02", 1.0)])
    db.save_time_series("BBB:price", "price", [("2026-07-02", 2.0)])
    _, _, repeated = service.basket_market_inputs(
        specs, 3.0, snapshot=_snapshot(), include_evidence=True,
    )
    assert repeated["resolved_inputs_hash"] == original_hash
    assert repeated["resolved_inputs"] == evidence["resolved_inputs"]


def test_insufficient_history_fallback_is_explicit_with_reason_and_counts():
    db = MarketDataDB(":memory:")
    _save_meta(db, SID, AS_OF)
    db.save_time_series("CCC:price", "price", [
        ("2026-06-01", 100.0), ("2026-06-02", 101.0),
    ])
    db.save_time_series("DDD:price", "price", [
        ("2026-06-10", 100.0), ("2026-06-11", 99.0),
    ])
    service = MarketDataService(market_db=db)

    _, corr, evidence = service.basket_market_inputs(
        [
            {"secid": "CCC", "kind": "equity", "weight": 1.0},
            {"secid": "DDD", "kind": "equity", "weight": 1.0},
        ],
        1.0,
        snapshot=_snapshot(),
        include_evidence=True,
    )

    assert evidence["fallback_used"]
    assert evidence["fallback_flags"]
    for item in evidence["constituents"]:
        assert item["vol"]["fallback"]
        assert item["vol"]["source"] == "configured_default_volatility"
        assert item["vol"]["sample_count"] == 1
        assert "minimum is 20" in item["vol"]["reason"]
        assert item["income"]["fallback"]
        assert item["income"]["source"] == "zero_income_default"
        assert item["income"]["reason"]

    pair = evidence["correlation"]["pairs"][0]
    assert pair["fallback"]
    assert pair["source"] == "configured_asset_class_default"
    assert pair["sample_count"] == 0
    assert "minimum is 20" in pair["reason"]
    assert corr[0, 1] == pytest.approx(0.5)


def test_correlation_uses_common_price_intervals_when_one_leg_misses_a_day():
    db = MarketDataDB(":memory:")
    _save_meta(db, SID, AS_OF)
    days = [date(2026, 5, 20) + timedelta(days=index) for index in range(32)]
    x_levels = [100.0]
    y_levels = [200.0]
    for index in range(1, len(days)):
        x_return = 0.012 * np.sin(index * 0.73) + 0.003 * np.cos(index * 0.19)
        y_return = 0.45 * x_return + 0.009 * np.cos(index * 1.17)
        x_levels.append(x_levels[-1] * np.exp(x_return))
        y_levels.append(y_levels[-1] * np.exp(y_return))

    missing_index = 12
    db.save_time_series(
        "XXX:price", "price",
        [(day.isoformat(), value) for day, value in zip(days, x_levels)],
    )
    db.save_time_series(
        "YYY:price", "price",
        [(day.isoformat(), value) for index, (day, value) in
         enumerate(zip(days, y_levels)) if index != missing_index],
    )
    service = MarketDataService(market_db=db)
    _, corr, evidence = service.basket_market_inputs(
        [
            {"secid": "XXX", "kind": "equity", "weight": 0.5},
            {"secid": "YYY", "kind": "equity", "weight": 0.5},
        ],
        1.0,
        snapshot=_snapshot(),
        include_evidence=True,
    )

    common = [index for index in range(len(days)) if index != missing_index]
    expected = float(np.corrcoef(
        np.diff(np.log(np.array([x_levels[index] for index in common]))),
        np.diff(np.log(np.array([y_levels[index] for index in common]))),
    )[0, 1])
    expected = float(np.clip(expected, -0.95, 0.95))

    # The missing observation creates one shared two-day interval. Both legs must
    # use that same interval; independently-built return rows would mismatch it.
    pair = evidence["correlation"]["pairs"][0]
    assert pair["aligned_level_count"] == len(common)
    assert pair["sample_count"] == len(common) - 1
    assert corr[0, 1] == pytest.approx(expected)


def test_legacy_two_value_contract_is_preserved():
    _, service = _seed_governed_basket()
    result = service.basket_market_inputs(
        [{"secid": "AAA", "kind": "equity", "weight": 1.0}],
        1.0,
        snapshot=_snapshot(),
    )
    assert isinstance(result, tuple)
    assert len(result) == 2
