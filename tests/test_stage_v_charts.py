"""
Stage V.1+V.2 — snapshot selector + chart presenters and ChartWidget smoke
(offscreen). Presenter logic headless; widgets constructed under offscreen Qt.
"""
import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from infra.db.market_data_db import MarketDataDB
from services.market_data_service import MarketDataService
from services import market_views as mv


@pytest.fixture(scope="module")
def demo():
    return MarketDataService().demo_snapshot(date(2026, 6, 13))


# ── Snapshot selector ────────────────────────────────────

def test_available_snapshots_newest_first():
    from datetime import datetime
    db = MarketDataDB(":memory:")
    for d in ("2026-06-09", "2026-06-10", "2026-06-13"):
        db.save_snapshot_meta(snapshot_id=f"moex-{d}", valuation_date=d,
                              source="MOEX", quality="OK", fetch_ts=datetime(2026, 6, 13))
    snaps = mv.available_snapshots(db)
    assert [s["valuation_date"] for s in snaps] == ["2026-06-13", "2026-06-10", "2026-06-09"]
    assert mv.available_snapshots(db, source="BLOOMBERG") == []
    assert mv.available_snapshots(None) == []


# ── Chart-ready presenters ───────────────────────────────

def test_curve_overlay_chart(demo):
    series = mv.curve_overlay_chart(demo, ["ofz_demo", "ruonia_demo"])
    assert len(series) == 2
    for label, xs, ys in series:
        assert len(xs) == len(ys) and all(isinstance(v, float) for v in ys)
        assert max(ys) < 100                                 # percent, not decimal
    # tenors capped at each curve's max
    real = mv.curve_overlay_chart(demo, ["ofzin_real_demo"])
    assert real and max(real[0][1]) <= 10.0


def test_commodity_curve_chart():
    db = MarketDataDB(":memory:")
    db.save_commodity_quotes("moex-2026-06-13", [
        {"asset": "BR", "secid": "BRN6", "expiry": "2026-09-01", "settle": 85.0,
         "open_interest": 1000, "volume": 50},
        {"asset": "BR", "secid": "BRZ6", "expiry": "2026-12-01", "settle": 84.0,
         "open_interest": 500, "volume": 20},
    ])
    series = mv.commodity_curve_chart(db, "moex-2026-06-13")
    assert len(series) == 1 and series[0][0] == "BR"
    xs, ys = series[0][1], series[0][2]
    assert xs == sorted(xs) and ys == [85.0, 84.0]           # sorted by expiry


# ── ChartWidget smoke (offscreen) ────────────────────────

def test_chartwidget_new_methods_render():
    from PySide6.QtWidgets import QApplication
    from app.chart import ChartWidget
    app = QApplication.instance() or QApplication([])
    c = ChartWidget()
    # plot_curves
    c.plot_curves([("КБД", [1, 2, 5], [14.0, 14.2, 14.5]),
                   ("CORP", [1, 2, 5], [15.0, 15.3, 15.6])])
    # plot_series (history)
    c.plot_series(["2026-06-08", "2026-06-09", "2026-06-10"],
                  [("KBD 5Y", [14.4, 14.5, 14.42])], ylabel="Rate (%)")
    # plot_heatmap (correlation)
    c.plot_heatmap([[1.0, 0.6, 0.3], [0.6, 1.0, 0.5], [0.3, 0.5, 1.0]],
                   ["SBER", "GAZP", "LKOH"])
    assert c.canvas is not None


def test_data_browser_dropdowns_construct(demo, monkeypatch):
    """Market workspace builds with the Data Browser snapshot+dataset selectors."""
    from PySide6.QtWidgets import QApplication, QComboBox
    app = QApplication.instance() or QApplication([])
    from app.panels.market_workspace import MarketWorkspace
    w = MarketWorkspace()
    assert w.findChild(QComboBox, "dataset_selector") is not None
    assert w.findChild(QComboBox, "snapshot_selector") is not None
