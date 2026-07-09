"""Issuer ratings + z-spread hazard layer (ответ В3)."""

from __future__ import annotations

import os
import sqlite3

import pytest

from infra import ratings


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


def test_rating_upsert_and_lookup(conn):
    ratings.upsert(conn, "Газпром", "АКРА", "AAA(RU)", "Стабильный", "2025-09-15")
    hit = ratings.lookup(conn, "ГазпромКP6")          # выпуск матчится на эмитента
    assert hit is not None
    assert hit["rating"] == "AAA(RU)"
    assert hit["recovery"] == 0.40
    assert hit["recovery_source"] == "baseline"
    assert hit["stale"] is False


def test_recovery_buckets():
    assert ratings.recovery_for("AAA(RU)") == 0.40
    assert ratings.recovery_for("ruAA-") == 0.40
    assert ratings.recovery_for("A(RU)") == 0.35
    assert ratings.recovery_for("ruBBB+") == 0.30
    assert ratings.recovery_for("B(RU)") == 0.20
    assert ratings.recovery_for("ruCCC") == 0.15


def test_stale_detection(conn):
    ratings.upsert(conn, "Тест", "АКРА", "BB(RU)")
    conn.execute("UPDATE issuer_ratings SET updated_at='2020-01-01'")
    conn.commit()
    hit = ratings.lookup(conn, "Тест")
    assert hit["stale"] is True


_DB = os.path.join(os.path.dirname(__file__), "..", "data", "market_data.sqlite")


@pytest.mark.skipif(not os.path.exists(_DB), reason="live market store not present")
def test_issuer_hazard_live():
    from api.context import CONTEXT
    from api import credit

    try:
        out = credit.issuer_hazard(CONTEXT, "РЖД")
    except ValueError as exc:
        pytest.skip(f"no usable RZD bonds in the snapshot: {exc}")
    assert out["bonds"], "expected z-spread points"
    assert out["recovery_source"] == "baseline"
    assert out["hazard"][0]["lambda"] >= 0
    pds = [p["pd"] for p in out["pd"]]
    assert all(0 <= p < 1 for p in pds)
    assert pds == sorted(pds), "PD must be non-decreasing in T"
