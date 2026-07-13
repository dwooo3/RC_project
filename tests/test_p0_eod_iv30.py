"""Governed EOD IV30 history: provenance, date guards and methodology."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from infra.db.market_data_db import MarketDataDB, _TABLES, _schema_statements
from infra.jobs.eod_ingest import EodIngestJob
from infra.moex_iss.ingest import MoexIngestor
from infra.moex_iss.vol_surface import imply_option_vols, iv30_representative
from models.black_scholes import black76


VAL = date(2026, 6, 10)


def _point(expiry_days: int, strike: float, iv: float, *, status="verified",
           observation_date: str = VAL.isoformat(),
           option_price_source="MOEX_FORTS_OPTION_SETTLEMENT",
           forward_source="MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT",
           option_price_basis="settlement",
           forward_basis="underlying_settlement") -> dict:
    return {
        "underlying": "TEST",
        "expiry": (VAL + timedelta(days=expiry_days)).isoformat(),
        "strike": strike,
        "iv": iv,
        "forward": 100.0,
        "T": expiry_days / 365.0,
        "tenor_days": expiry_days,
        "oi": 100.0,
        "observation_date": observation_date,
        "observation_status": status,
        "source": forward_source,
        "method": "black76_settlement",
        "option_price_date": observation_date,
        "forward_date": observation_date,
        "option_price_source": option_price_source,
        "forward_source": forward_source,
        "option_price_basis": option_price_basis,
        "forward_basis": forward_basis,
    }


def _smile(expiry_days: int, iv: float) -> list[dict]:
    return [_point(expiry_days, 90.0, iv), _point(expiry_days, 110.0, iv)]


def _seed_governed_surface(db, points, *, snapshot_id: str = "s1") -> None:
    db.save_snapshot_meta(
        snapshot_id=snapshot_id,
        valuation_date=VAL,
        source="MOEX",
        quality="OK",
        fetch_ts=VAL,
    )
    db.replace_vol_surface(snapshot_id, points)


def test_iv30_interpolates_atm_then_total_variance():
    points = _smile(20, 0.20) + _smile(40, 0.30)

    result = iv30_representative(points, VAL)

    w20 = 0.20**2 * 20 / 365.0
    w40 = 0.30**2 * 40 / 365.0
    expected = math.sqrt((w20 + 0.5 * (w40 - w20)) / (30 / 365.0))
    assert result["accepted"] is True
    assert result["method"] == "atm_forward_total_variance_30d"
    assert result["quality"] == "OK"
    assert result["value"] == pytest.approx(expected)
    assert [row["tenor_days"] for row in result["selected_expiries"]] == [20, 40]


def test_iv30_uses_atm_forward_not_wing_median():
    points = [
        _point(30, 50.0, 1.40),
        _point(30, 95.0, 0.19),
        _point(30, 105.0, 0.21),
        _point(30, 150.0, 1.20),
    ]

    result = iv30_representative(points, VAL)

    assert result["accepted"] is True
    assert result["value"] == pytest.approx(0.20, abs=0.002)
    assert result["selected_expiries"][0]["strikes"] == [95.0, 105.0]


def test_iv30_bounded_nearest_tenor_is_warn_and_far_tenor_rejected():
    near = iv30_representative(_smile(27, 0.25), VAL)
    far = iv30_representative(_smile(38, 0.25), VAL)

    assert near["accepted"] is True
    assert near["quality"] == "WARN"
    assert near["method"] == "atm_forward_nearest_tenor"
    assert near["warnings"]
    assert far["accepted"] is False
    assert far["reason"] == "no_30d_bracket_or_bounded_nearest"


@pytest.mark.parametrize("selected_days", [30, 27])
def test_iv30_exact_and_nearest_reject_local_calendar_variance_inversion(selected_days):
    points = _smile(20, 1.00) + _smile(selected_days, 0.20)
    if selected_days == 30:
        points += _smile(40, 0.30)

    result = iv30_representative(points, VAL)

    assert result["accepted"] is False
    assert result["reason"] == "calendar_total_variance_inversion"
    assert result["inversion_pair"]


def _implied_rows(*, option_date="2026-06-10", forward_date="2026-06-10"):
    F, sigma, days = 100.0, 0.25, 30
    expiry = VAL + timedelta(days=days)
    option_secs, option_md = [], []
    for strike in (90.0, 110.0):
        cp = "call" if strike >= F else "put"
        price = black76(F, strike, days / 365.0, 0.0, sigma, cp).price
        secid = f"O{int(strike)}"
        option_secs.append({
            "SECID": secid,
            "SHORTNAME": (
                f"Si-6.26M{expiry.day:02d}{expiry.month:02d}{expiry.year % 100:02d}"
                f"{'C' if cp == 'call' else 'P'}A{int(strike)}"),
            "ASSETCODE": "Si",
            "LASTTRADEDATE": expiry.isoformat(),
            "UNDERLYINGSETTLEPRICE": F,
            "TRADEDATE": forward_date,
            "PREVOPENPOSITION": 100,
        })
        option_md.append({
            "SECID": secid,
            "SETTLEPRICE": price,
            "OPENPOSITION": 100,
            "TRADEDATE": option_date,
        })
    return option_secs, option_md


def test_primary_implied_rows_preserve_governed_provenance():
    option_secs, option_md = _implied_rows()

    rows = imply_option_vols(option_secs, option_md, [], [], VAL)

    assert len(rows) == 2
    assert all(row["forward"] == 100.0 for row in rows)
    assert all(row["tenor_days"] == 30 and row["oi"] == 100.0 for row in rows)
    assert all(row["observation_date"] == VAL.isoformat() for row in rows)
    assert all(row["observation_status"] == "verified" for row in rows)
    assert all(row["method"] == "black76_settlement" for row in rows)
    assert all(row["source"] == "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT"
               for row in rows)
    assert all(row["option_price_date"] == VAL.isoformat() for row in rows)
    assert all(row["forward_date"] == VAL.isoformat() for row in rows)
    assert all(row["option_price_source"] == "MOEX_FORTS_OPTION_SETTLEMENT"
               for row in rows)
    assert all(row["forward_source"]
               == "MOEX_FORTS_OPTION_UNDERLYING_SETTLEMENT" for row in rows)
    assert all(row["option_price_basis"] == "settlement" for row in rows)
    assert all(row["forward_basis"] == "underlying_settlement" for row in rows)


def test_primary_implied_rows_expose_date_mismatch():
    option_secs, option_md = _implied_rows(
        option_date="2026-06-10", forward_date="2026-06-09")

    rows = imply_option_vols(option_secs, option_md, [], [], VAL)

    assert rows
    assert all(row["observation_status"].startswith("date_mismatch:") for row in rows)


def test_direct_forward_without_own_date_is_never_verified_from_option_date():
    option_secs, option_md = _implied_rows()
    for row in option_secs:
        row.pop("TRADEDATE")

    rows = imply_option_vols(option_secs, option_md, [], [], VAL)

    assert rows
    assert all(row["option_price_date"] == VAL.isoformat() for row in rows)
    assert all(row["forward_date"] is None for row in rows)
    assert all(row["observation_status"] == "missing_forward_date" for row in rows)


def test_futures_forward_preserves_its_independent_date_source_and_basis():
    option_secs, option_md = _implied_rows()
    for row in option_secs:
        row.pop("UNDERLYINGSETTLEPRICE")
    futures_secs = [{"SECID": "F", "SHORTNAME": "Si-6.26"}]
    futures_md = [{
        "SECID": "F", "SETTLEPRICE": 100.0, "TRADEDATE": VAL.isoformat(),
    }]

    rows = imply_option_vols(
        option_secs, option_md, futures_secs, futures_md, VAL)

    assert rows
    assert all(row["observation_status"] == "verified" for row in rows)
    assert all(row["forward_date"] == VAL.isoformat() for row in rows)
    assert all(row["forward_source"] == "MOEX_FORTS_FUTURES_SETTLEMENT"
               for row in rows)
    assert all(row["forward_basis"] == "settlement" for row in rows)


def test_dated_futures_forward_wins_over_undated_direct_forward():
    option_secs, option_md = _implied_rows()
    for row in option_secs:
        row.pop("TRADEDATE")
    futures_secs = [{"SECID": "F", "SHORTNAME": "Si-6.26"}]
    futures_md = [{
        "SECID": "F", "SETTLEPRICE": 100.0, "TRADEDATE": VAL.isoformat(),
    }]

    rows = imply_option_vols(
        option_secs, option_md, futures_secs, futures_md, VAL)

    assert rows
    assert all(row["observation_status"] == "verified" for row in rows)
    assert all(row["forward_source"] == "MOEX_FORTS_FUTURES_SETTLEMENT"
               for row in rows)


def test_provenance_table_roundtrip_replace_and_dialect_sql():
    db = MarketDataDB(":memory:")
    first = _smile(20, 0.20) + [_point(20, 100.0, 0.19)]
    db.replace_vol_point_observations("s1", first)
    assert len(db.get_vol_point_observations("s1")) == 3

    db.replace_vol_point_observations("s1", _smile(20, 0.20))
    stored = db.get_vol_point_observations("s1")
    assert len(stored) == 2
    assert stored[0]["forward"] == 100.0
    assert stored[0]["observation_date"] == VAL.isoformat()
    assert stored[0]["source"].startswith("MOEX_FORTS")
    assert stored[0]["option_price_source"] == "MOEX_FORTS_OPTION_SETTLEMENT"
    assert stored[0]["forward_source"].startswith("MOEX_FORTS")
    assert stored[0]["option_price_basis"] == "settlement"
    assert stored[0]["forward_basis"] == "underlying_settlement"

    assert any("CREATE TABLE IF NOT EXISTS vol_point_observations" in sql
               for sql in _schema_statements("postgres"))
    columns, conflict = _TABLES["vol_point_observations"]
    db.dialect, db.ph = "postgres", "%s"
    sql = db._upsert_sql("vol_point_observations", columns, conflict)
    assert "%s" in sql and "?" not in sql and "ON CONFLICT" in sql


def test_surface_refresh_is_atomic_and_removes_disappeared_raw_strikes():
    db = MarketDataDB(":memory:")
    first = _smile(20, 0.20) + [_point(20, 100.0, 0.19)]
    db.replace_vol_surface("s1", first)

    second = _smile(20, 0.20)
    db.replace_vol_surface("s1", second)

    raw = db.get_vol_points("s1")
    observations = db.get_vol_point_observations("s1")
    raw_keys = {(row["underlying"], row["expiry"], row["strike"]) for row in raw}
    observation_keys = {
        (row["underlying"], row["expiry"], row["strike"])
        for row in observations
    }
    assert len(raw) == len(observations) == 2
    assert raw_keys == observation_keys

    with pytest.raises(ValueError):
        db.replace_vol_surface("s1", [{"underlying": "TEST", "strike": "bad"}])
    assert len(db.get_vol_points("s1")) == 2
    assert len(db.get_vol_point_observations("s1")) == 2


def test_eod_publishes_separate_iv30_series_and_is_idempotent():
    db = MarketDataDB(":memory:")
    points = _smile(20, 0.20) + _smile(40, 0.30)
    _seed_governed_surface(db, points)
    job = EodIngestJob(db, iss_client=None)

    first = job._iv_history("s1", VAL)
    second = job._iv_history("s1", VAL)

    assert first["status"] == second["status"] == "ok"
    assert first["saved"] == second["saved"] == 1
    assert db.get_time_series("IV:TEST", "vol") == []
    iv30 = db.get_time_series("IV30:TEST", "vol")
    assert len(iv30) == 1 and iv30[0]["dt"] == VAL.isoformat()


def test_eod_never_publishes_warn_nearest_tenor_as_canonical_iv30():
    db = MarketDataDB(":memory:")
    _seed_governed_surface(db, _smile(27, 0.25))

    result = EodIngestJob(db, iss_client=None).publish_iv30("s1", VAL)

    assert result["status"] == "skipped"
    assert result["rejected"]["TEST"]["quality"] == "WARN"
    assert (result["rejected"]["TEST"]["reason"]
            == "representative_not_production_quality")
    assert db.get_time_series("IV30:TEST", "vol") == []


def test_eod_publisher_requires_manifest_and_matching_raw_lineage():
    db = MarketDataDB(":memory:")
    points = _smile(30, 0.25)
    db.replace_vol_surface("s1", points)
    job = EodIngestJob(db, iss_client=None)

    missing_manifest = job.publish_iv30("s1", VAL)
    assert missing_manifest["reason"] == "snapshot_manifest_missing"

    _seed_governed_surface(db, points)
    db.save_vol_point(
        "s1", "TEST", points[0]["expiry"], points[0]["strike"], 0.99)
    mismatch = job.publish_iv30("s1", VAL)

    assert mismatch["status"] == "skipped"
    assert mismatch["reason"] == "raw_provenance_payload_mismatch"
    assert db.get_time_series("IV30:TEST", "vol") == []


def test_eod_rejected_rerun_atomically_revokes_existing_iv30_date():
    db = MarketDataDB(":memory:")
    job = EodIngestJob(db, iss_client=None)
    _seed_governed_surface(db, _smile(30, 0.25))
    assert job._iv_history("s1", VAL)["status"] == "ok"

    rejected = [
        _point(30, strike, 0.25, status="missing_forward_date",
               observation_date=None)
        for strike in (90.0, 110.0)
    ]
    _seed_governed_surface(db, rejected)

    result = job._iv_history("s1", VAL)

    assert result["status"] == "skipped"
    assert db.get_time_series("IV30:TEST", "vol") == []


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("option_price_source", None, "option_price_source_not_allowed"),
        ("forward_source", "UNAPPROVED", "forward_source_not_allowed"),
        ("option_price_basis", "last_trade", "option_price_basis_not_allowed"),
        ("forward_basis", "indicative", "forward_basis_not_allowed"),
    ],
)
def test_eod_rejects_unapproved_source_and_basis(field, value, reason):
    db = MarketDataDB(":memory:")
    points = _smile(30, 0.25)
    for point in points:
        point[field] = value
    _seed_governed_surface(db, points)

    result = EodIngestJob(db, iss_client=None)._iv_history("s1", VAL)

    assert result["status"] == "skipped"
    assert result["rejected"]["TEST"]["reason"] == reason
    assert db.get_time_series("IV30:TEST", "vol") == []


@pytest.mark.parametrize(
    ("status", "observation_date", "reason"),
    [
        ("missing_option_date", None, "observation_date_not_verified"),
        ("date_mismatch:2026-06-09!=2026-06-10", "2026-06-09",
         "observation_date_not_verified"),
        ("verified", "2026-06-09", "observation_date_mismatch"),
    ],
)
def test_eod_missing_or_mismatched_date_never_publishes(status, observation_date, reason):
    db = MarketDataDB(":memory:")
    points = [
        _point(30, strike, 0.25, status=status,
               observation_date=observation_date)
        for strike in (90.0, 110.0)
    ]
    _seed_governed_surface(db, points)

    result = EodIngestJob(db, iss_client=None)._iv_history("s1", VAL)

    assert result["status"] == "skipped"
    rejected = result["rejected"]["TEST"]
    assert rejected["reason"] == reason
    assert db.get_time_series("IV30:TEST", "vol") == []


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda point: point.update({
                "option_price_date": f"{VAL.isoformat()}garbage",
                "forward_date": f"{VAL.isoformat()}garbage",
            }),
            "observation_date_not_verified",
        ),
        (
            lambda point: point.update({"observation_date": "2026-06-09"}),
            "observation_date_mismatch",
        ),
    ],
)
def test_eod_rejects_malformed_or_independently_misaligned_lineage_date(
    mutate, reason,
):
    db = MarketDataDB(":memory:")
    points = _smile(30, 0.25)
    for point in points:
        mutate(point)
    _seed_governed_surface(db, points)

    result = EodIngestJob(db, iss_client=None)._iv_history("s1", VAL)

    assert result["status"] == "skipped"
    assert result["rejected"]["TEST"]["reason"] == reason
    assert db.get_time_series("IV30:TEST", "vol") == []


def test_eod_weekend_is_fail_closed_even_with_matching_label():
    saturday = date(2026, 6, 13)
    db = MarketDataDB(":memory:")
    points = [
        {**_point(30, strike, 0.25),
         "observation_date": saturday.isoformat(),
         "expiry": (saturday + timedelta(days=30)).isoformat()}
        for strike in (90.0, 110.0)
    ]
    db.replace_vol_point_observations("s1", points)

    result = EodIngestJob(db, iss_client=None)._iv_history("s1", saturday)

    assert result["status"] == "skipped"
    assert result["reason"] == "valuation_date_is_not_a_trading_weekday"
    assert db.get_time_series("IV30:TEST", "vol") == []


class _Iss:
    def __init__(self, option_secs, option_md):
        self.option_secs = option_secs
        self.option_md = option_md

    def get_blocks(self, path, params=None):
        del params
        if "/options/" in path:
            return {"securities": self.option_secs, "marketdata": self.option_md}
        return {"securities": [], "marketdata": []}


def test_option_ingest_wires_primary_point_provenance():
    option_secs, option_md = _implied_rows()
    db = MarketDataDB(":memory:")

    count = MoexIngestor(_Iss(option_secs, option_md), db).ingest_option_vol_surface(
        "s1", VAL)
    observations = db.get_vol_point_observations("s1")

    assert count == len(observations) == 2
    assert all(row["forward"] == 100.0 for row in observations)
    assert all(row["tenor_days"] == 30 for row in observations)
    assert all(row["observation_status"] == "verified" for row in observations)


def test_quality_gate_rejects_raw_vol_without_governed_date_lineage():
    from datetime import datetime

    from infra.jobs.data_quality import snapshot_quality_report

    db = MarketDataDB(":memory:")
    sid = "moex-2026-06-10"
    for index in range(120):
        db.save_vol_point(sid, "TEST", "2026-09-18", 80.0 + index, 0.25)
    db.save_snapshot_meta(
        snapshot_id=sid, valuation_date=VAL, source="MOEX", quality="OK",
        fetch_ts=datetime(2026, 6, 10, 19, 30),
    )

    report = snapshot_quality_report(db, sid, VAL)

    assert report["checks"]["vol_points"] == 120
    assert report["checks"]["vol_observation_points"] == 0
    assert any("provenance missing" in alert for alert in report["alerts"])
    assert any("IV30 representative missing" in alert for alert in report["alerts"])
    assert report["production_eligible"] is False


def _complete_quality_db():
    from datetime import datetime

    from infra.jobs.data_quality import EXPECTED_CURVES, EXPECTED_FX

    db = MarketDataDB(":memory:")
    sid = "moex-2026-06-10"
    db.save_snapshot_meta(
        snapshot_id=sid, valuation_date=VAL, source="MOEX", quality="OK",
        fetch_ts=datetime(2026, 6, 10, 19, 30),
    )
    for curve_id in EXPECTED_CURVES:
        db.save_curve(
            sid, curve_id, method="test", nss_params={}, as_of=VAL,
            points=[(1.0, 0.1, 0.9)],
        )
    for pair in EXPECTED_FX:
        db.save_fx_rate(sid, pair, 1.0)
    db.save_bond_quote(sid, {"secid": "BOND", "clean_price": 100.0})
    return db, sid


def test_quality_gate_requires_iv30_for_every_surface_underlying():
    from infra.jobs.data_quality import snapshot_quality_report

    db, sid = _complete_quality_db()
    points = []
    for underlying in ("A", "B"):
        for index in range(50):
            point = _point(30, 76.0 + index, 0.25)
            point["underlying"] = underlying
            points.append(point)
    db.replace_vol_surface(sid, points)
    db.replace_iv30_for_date(VAL, {"A": 0.25})

    report = snapshot_quality_report(db, sid, VAL)

    assert report["checks"]["iv30_missing_underlyings"] == ["B"]
    assert any("IV30 representative missing" in alert for alert in report["alerts"])
    assert report["production_eligible"] is False


def test_quality_gate_requires_one_to_one_raw_provenance_key_coverage():
    from infra.jobs.data_quality import snapshot_quality_report

    db, sid = _complete_quality_db()
    points = [_point(30, 50.0 + index, 0.25) for index in range(100)]
    db.replace_vol_surface(sid, points)
    db.replace_vol_point_observations(sid, _smile(30, 0.25))
    db.replace_iv30_for_date(VAL, {"TEST": 0.25})

    report = snapshot_quality_report(db, sid, VAL)

    assert report["checks"]["vol_key_coverage_complete"] is False
    assert report["checks"]["vol_keys_missing_provenance"] == 98
    assert any("key coverage mismatch" in alert for alert in report["alerts"])
    assert report["production_eligible"] is False


def test_quality_gate_rejects_raw_provenance_iv_value_mismatch():
    from infra.jobs.data_quality import snapshot_quality_report

    db, sid = _complete_quality_db()
    points = [_point(30, 50.0 + index, 0.25) for index in range(100)]
    db.replace_vol_surface(sid, points)
    db.save_vol_point(sid, "TEST", points[0]["expiry"], points[0]["strike"], 0.99)
    db.replace_iv30_for_date(VAL, {"TEST": 0.25})

    report = snapshot_quality_report(db, sid, VAL)

    assert report["checks"]["vol_key_coverage_complete"] is True
    assert report["checks"]["vol_payload_match_complete"] is False
    assert report["checks"]["vol_iv_value_mismatches"] == 1
    assert any("IV value mismatch" in alert for alert in report["alerts"])
    assert report["production_eligible"] is False


def test_quality_gate_rejects_canonical_value_that_differs_from_representative():
    from infra.jobs.data_quality import snapshot_quality_report

    db, sid = _complete_quality_db()
    points = [_point(30, 50.0 + index, 0.25) for index in range(100)]
    db.replace_vol_surface(sid, points)
    db.replace_iv30_for_date(VAL, {"TEST": 0.99})

    report = snapshot_quality_report(db, sid, VAL)

    assert report["checks"]["iv30_underlyings"] == []
    assert report["checks"]["iv30_value_mismatch_underlyings"] == ["TEST"]
    assert any("differs from recomputed" in alert for alert in report["alerts"])
    assert report["production_eligible"] is False


def test_primary_provenance_rejects_expired_or_inconsistent_tenor():
    from infra.moex_iss.vol_surface import primary_iv_provenance_error

    expired = _point(30, 100.0, 0.25)
    expired["expiry"] = VAL.isoformat()
    expired["tenor_days"] = 0
    assert primary_iv_provenance_error(expired, VAL) == "invalid_expiry"

    inconsistent = _point(30, 100.0, 0.25)
    inconsistent["tenor_days"] = 29
    assert primary_iv_provenance_error(inconsistent, VAL) == "invalid_tenor_days"

    fractional = _point(30, 100.0, 0.25)
    fractional["tenor_days"] = 30.9
    assert primary_iv_provenance_error(fractional, VAL) == "invalid_tenor_days"
    with pytest.raises(ValueError, match="positive integer"):
        MarketDataDB(":memory:").replace_vol_surface("s1", [fractional])


def test_quality_gate_rejects_invalid_raw_and_provenance_payload():
    from infra.jobs.data_quality import snapshot_quality_report

    db, sid = _complete_quality_db()
    points = [_point(30, 50.0 + index, 0.25) for index in range(100)]
    points[0]["iv"] = None
    db.replace_vol_surface(sid, points)
    db.replace_iv30_for_date(VAL, {"TEST": 0.25})

    report = snapshot_quality_report(db, sid, VAL)

    assert report["checks"]["vol_key_coverage_complete"] is True
    assert report["checks"]["vol_payload_match_complete"] is False
    assert report["checks"]["vol_raw_payloads_invalid"] == 1
    assert report["checks"]["vol_observation_payloads_invalid"] == 1
    assert any("invalid vol point payload" in alert for alert in report["alerts"])
    assert report["production_eligible"] is False
