"""RUONIA OIS curves — RUSFAR bootstrap (MOEX) + cbonds reference."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pytest

from infra.cbonds import CBONDS_RUONIA_OIS, ingest_cbonds_ruonia_ois
from infra.curves_ois import bootstrap_ois
from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.ingest import MoexIngestor

VAL = date(2026, 6, 23)


class _FakeIssRusfar:
    def get_blocks(self, path, params=None):
        return {"marketdata": [
            {"SECID": "RUSFAR", "CURRENTVALUE": 14.16},
            {"SECID": "RUSFAR1W", "CURRENTVALUE": 14.18},
            {"SECID": "RUSFAR2W", "CURRENTVALUE": 14.09},
            {"SECID": "RUSFAR1M", "CURRENTVALUE": 14.10},
            {"SECID": "RUSFAR3M", "CURRENTVALUE": 14.01},
        ]}


# ── bootstrap math ───────────────────────────────────────

def test_bootstrap_money_market_short_end_inverts():
    # tenor <= 1y: DF = 1/(1+r*t); back-out simple rate recovers the input.
    (t, z, df), = bootstrap_ois([0.25], [0.14])
    assert df == pytest.approx(1.0 / (1.0 + 0.14 * 0.25), rel=1e-12)
    assert (1.0 / df - 1.0) / t == pytest.approx(0.14, rel=1e-9)


def test_bootstrap_annual_coupon_par():
    # flat 10% par at 1y/2y -> DF(2) = (1 - r*DF(1))/(1+r).
    pts = {round(t, 4): df for t, _, df in bootstrap_ois([1.0, 2.0], [0.10, 0.10])}
    df1 = 1.0 / 1.10
    assert pts[1.0] == pytest.approx(df1, rel=1e-12)
    assert pts[2.0] == pytest.approx((1.0 - 0.10 * df1) / 1.10, rel=1e-12)


def test_bootstrap_dfs_monotonic():
    pts = bootstrap_ois([t for t, _ in CBONDS_RUONIA_OIS],
                        [r / 100 for _, r in CBONDS_RUONIA_OIS])
    dfs = [df for _, _, df in pts]
    assert all(b < a for a, b in zip(dfs, dfs[1:]))


# ── MOEX RUSFAR bootstrap ingest ─────────────────────────

def test_rusfar_bootstrap_curve():
    db = MarketDataDB(":memory:")
    sid = "moex-2026-06-23"
    n = MoexIngestor(_FakeIssRusfar(), db).ingest_ruonia_ois(sid, VAL)
    assert n == 5
    assert db.get_curve(sid, "RUONIA_RUB")["method"] == "ois_bootstrap"
    pts = db.get_curve_points(sid, "RUONIA_RUB")
    p3m = next(p for p in pts if abs(p["tenor"] - 91 / 365) < 1e-6)
    simple = (1.0 / p3m["discount_factor"] - 1.0) / p3m["tenor"]
    assert simple == pytest.approx(0.1401, abs=1e-4)          # recovers RUSFAR 3M


def test_rusfar_too_few_tenors_raises():
    class _Thin:
        def get_blocks(self, path, params=None):
            return {"marketdata": [{"SECID": "RUSFAR", "CURRENTVALUE": 14.16}]}

    db = MarketDataDB(":memory:")
    with pytest.raises(ValueError):
        MoexIngestor(_Thin(), db).ingest_ruonia_ois("moex-2026-06-23", VAL)


# ── cbonds reference curve ───────────────────────────────

def test_cbonds_reference_curve():
    db = MarketDataDB(":memory:")
    sid = "moex-2026-06-23"
    n = ingest_cbonds_ruonia_ois(db, sid)
    assert n == len(CBONDS_RUONIA_OIS) == 10
    assert db.get_curve(sid, "RUONIA-OIS-CBONDS")["method"] == "ois_bootstrap_cbonds"
    dfs = [p["discount_factor"] for p in db.get_curve_points(sid, "RUONIA-OIS-CBONDS")]
    assert all(b < a for a, b in zip(dfs, dfs[1:]))


def test_moex_and_cbonds_agree_short_end():
    # cross-validation: RUSFAR-bootstrapped vs cbonds within 15bp out to 3M.
    db = MarketDataDB(":memory:")
    sid = "moex-2026-06-23"
    MoexIngestor(_FakeIssRusfar(), db).ingest_ruonia_ois(sid, VAL)
    ingest_cbonds_ruonia_ois(db, sid)
    moex = {round(p["tenor"], 4): p["zero_rate"] for p in db.get_curve_points(sid, "RUONIA_RUB")}
    cb = {round(p["tenor"], 4): p["zero_rate"] for p in db.get_curve_points(sid, "RUONIA-OIS-CBONDS")}
    common = set(moex) & set(cb)
    assert common
    for t in common:
        assert abs(moex[t] - cb[t]) < 0.0015                 # < 15 bp
