"""Phase D — FORTS option vol surface (normalise, ingest, snapshot)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pytest

from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.ingest import MoexIngestor
from infra.moex_iss.vol_surface import normalise_option_rows, build_vol_surfaces
from services.market_data_service import MarketDataService

VAL = date(2026, 6, 2)


def test_normalise_option_rows_percent_to_decimal_and_underlying():
    rows = [
        {"SECID": "SR65000BF6", "ASSETCODE": "SBER", "STRIKE": 320.0, "VOLATILITY": 28.0,
         "LASTDELDATE": "2026-06-19"},
        {"SECID": "SR70000BF6", "STRIKE": 330.0, "IV": 0.30, "LASTDELDATE": "2026-06-19"},  # already decimal
        {"SECID": "X", "STRIKE": None, "VOLATILITY": 25.0},  # dropped (no strike)
    ]
    pts = normalise_option_rows(rows)
    assert len(pts) == 2
    assert pts[0]["underlying"] == "SBER" and pts[0]["iv"] == pytest.approx(0.28)
    assert pts[1]["underlying"] == "SR" and pts[1]["iv"] == pytest.approx(0.30)


def test_build_vol_surfaces_groups_by_underlying():
    pts = [
        {"underlying": "SBER", "expiry": "2026-06-19", "strike": 320.0, "iv": 0.28},
        {"underlying": "SBER", "expiry": "2026-06-19", "strike": 330.0, "iv": 0.30},
    ]
    surf = build_vol_surfaces(pts)
    assert "SBER_FORTS" in surf
    s = surf["SBER_FORTS"]
    assert s["type"] == "grid" and s["n_points"] == 2
    assert s["median_vol"] == pytest.approx(0.29)


class FakeClient:
    def __init__(self, blocks): self.blocks = blocks
    def get_blocks(self, path, params=None): return self.blocks.get(path, {})


def _vol_db():
    db = MarketDataDB(":memory:")
    path = "engines/futures/markets/options/securities"
    client = FakeClient({path: {
        "securities": [
            {"SECID": "SR320", "ASSETCODE": "SBER", "STRIKE": 320.0, "LASTDELDATE": "2026-06-19"},
            {"SECID": "SR330", "ASSETCODE": "SBER", "STRIKE": 330.0, "LASTDELDATE": "2026-06-19"},
        ],
        "marketdata": [
            {"SECID": "SR320", "VOLATILITY": 28.0},
            {"SECID": "SR330", "VOLATILITY": 30.0},
        ],
    }})
    sid = MoexIngestor.snapshot_id_for(VAL)
    MoexIngestor(client, db).ingest_option_vol_surface(sid, VAL)
    return db, sid


def test_ingest_option_vol_surface_writes_points():
    db, sid = _vol_db()
    pts = db.get_vol_points(sid)
    assert len(pts) == 2
    assert {p["strike"] for p in pts} == {320.0, 330.0}
    assert all(0 < p["iv"] < 1 for p in pts)  # decimals


def test_vol_surface_in_moex_snapshot():
    db, sid = _vol_db()
    # add minimal govt curve + fx so the snapshot assembles
    db.save_curve(sid, "GCURVE_RUB", method="points", nss_params={}, as_of=VAL,
                  points=[(0.5, 0.15, None), (1, 0.148, None), (2, 0.145, None),
                          (5, 0.138, None), (10, 0.132, None)])
    db.save_fx_rate(sid, "USD/RUB", 74.36)
    svc = MarketDataService(market_db=db)
    snap = svc.moex_snapshot(VAL)
    assert "SBER_FORTS" in snap.vol_surfaces
    surf = svc.get_vol_surface("SBER_FORTS", snapshot=snap)
    assert surf["n_points"] == 2 and surf["median_vol"] == pytest.approx(0.29)
