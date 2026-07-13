"""Package 5 persistence contracts exposed by adversarial review."""

from __future__ import annotations

import pytest

from infra.db.market_data_db import MarketDataDB


def test_factor_date_replace_removes_date_and_timestamp_variants_only():
    db = MarketDataDB(":memory:")
    db.save_time_series(
        "IV30:OLD",
        "vol",
        [
            ("2026-06-08", 0.20),
            ("2026-06-08T12:30:00", 0.21),
            ("2026-06-09T00:00:00", 0.22),
        ],
    )
    db.save_time_series("IVX30:KEEP", "vol", [("2026-06-08T12:30:00", 0.90)])

    db.replace_iv30_for_date("2026-06-08", {"NEW": 0.25})

    assert db.get_time_series("IV30:OLD", "vol") == [
        {"dt": "2026-06-09T00:00:00", "value": 0.22},
    ]
    assert db.get_time_series("IV30:NEW", "vol") == [
        {"dt": "2026-06-08", "value": 0.25},
    ]
    assert db.get_time_series("IVX30:KEEP", "vol") == [
        {"dt": "2026-06-08T12:30:00", "value": 0.90},
    ]

    with pytest.raises(ValueError, match="finite"):
        db.replace_iv30_for_date("2026-06-08", {"BAD": float("nan")})
    assert db.get_time_series("IV30:NEW", "vol") == [
        {"dt": "2026-06-08", "value": 0.25},
    ]


def test_same_date_curve_method_conflict_fails_even_for_identical_grid():
    db = MarketDataDB(":memory:")
    db.save_curve(
        "s1", "DISC", method="points", nss_params={}, as_of="2026-01-02",
        points=[(1.0, 0.10, None)],
    )
    db.save_curve(
        "s2", "DISC", method="ois_bootstrap", nss_params={},
        as_of="2026-01-02", points=[(1.0, 0.10, None)],
    )

    with pytest.raises(ValueError, match="conflicting methodologies"):
        db.get_curve_history("DISC")


def test_curve_history_rejects_malformed_full_observation_date():
    db = MarketDataDB(":memory:")
    db.save_curve(
        "s1", "DISC", method="points", nss_params={},
        as_of="2026-01-02T00:00:00garbage",
        points=[(1.0, 0.10, None)],
    )

    with pytest.raises(ValueError, match="invalid observation date"):
        db.get_curve_history("DISC")
