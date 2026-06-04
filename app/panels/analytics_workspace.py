"""Analytics workspace — Model Lab: Trees · MC · Heston/SABR · Short Rate · Real Options."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QScrollArea, QStackedWidget, QPushButton, QGridLayout
)
from PySide6.QtCore import Qt

from app.widgets import ModelStatusBadge
from services.governance_service import GovernanceService


_BG1 = "#1a1a1e"
_BG2 = "#1e1e22"
_BOR = "#2e2e33"
_TXT0 = "#f0f0f2"
_TXT2 = "#606068"
_ACC  = "#d97757"


ANALYTICS_MODULES = [
    ("Binomial Trees",    "binomial",    "binomial_crr",   "CRR · LR · Trinomial · American pricing"),
    ("Monte Carlo Lab",   "montecarlo",  "mc_gbm",         "GBM · LSM · Heston MC · Convergence"),
    ("Heston / SABR",     "stochvol",    "heston_cf",      "Stochastic vol · Smile calibration"),
    ("Short Rate Models", "shortrate",   "short_rate",     "Hull-White · Vasicek · CIR"),
    ("Real Options",      "realoptions", "placeholder",    "Invest / Abandon / Expand decisions"),
    ("GARCH / EWMA",      "garch_panel", "garch",          "Volatility forecasting · Stationarity"),
]


_GOVERNANCE = GovernanceService()


def _status_from_key(model_key: str) -> str:
    """Model status string, sourced through the governance service (not the raw registry)."""
    return _GOVERNANCE.get_model(model_key).status


class _ModuleCard(QFrame):
    def __init__(self, title: str, model_key: str, hint: str, on_click=None, parent=None):
        super().__init__(parent)
        self.setObjectName("acard")
        status = _status_from_key(model_key)
        self.setStyleSheet(
            "QFrame#acard{background:#1e1e22;border:1px solid #2e2e33;border-radius:8px;}"
            "QFrame#acard:hover{background:#242428;border-color:#4a4a52;}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(74)
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 10, 14, 10); lay.setSpacing(3)
        row = QHBoxLayout(); row.setSpacing(8)
        t = QLabel(title)
        t.setStyleSheet(f"color:{_TXT0};font-size:13px;font-weight:600;background:transparent;")
        row.addWidget(t); row.addStretch(); row.addWidget(ModelStatusBadge(status))
        lay.addLayout(row)
        h = QLabel(hint)
        h.setStyleSheet(f"color:{_TXT2};font-size:10px;background:transparent;")
        lay.addWidget(h)
        self._on_click = on_click

    def mousePressEvent(self, e):
        if self._on_click:
            self._on_click()


class AnalyticsWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: dict = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self._stack = QStackedWidget()
        self._landing = self._build_landing()
        self._stack.addWidget(self._landing)
        root.addWidget(self._stack)

    def _build_landing(self) -> QWidget:
        w = QWidget(); w.setStyleSheet(f"background:{_BG1};")
        outer = QVBoxLayout(w); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(); body.setStyleSheet(f"background:{_BG1};")
        lay = QVBoxLayout(body); lay.setContentsMargins(28, 24, 28, 28); lay.setSpacing(20)

        hdr = QHBoxLayout()
        title = QLabel("Analytics")
        title.setStyleSheet(
            f"color:{_TXT0};font-size:24px;font-weight:700;"
            f"letter-spacing:-0.5px;background:transparent;")
        sub = QLabel("Model Lab — pricing models, simulation engines and analytics tools")
        sub.setStyleSheet(f"color:{_TXT2};font-size:12px;background:transparent;")
        col = QVBoxLayout(); col.setSpacing(2); col.addWidget(title); col.addWidget(sub)
        hdr.addLayout(col); hdr.addStretch(); lay.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_BOR};max-height:1px;"); lay.addWidget(sep)

        sec = QLabel("MODEL LAB")
        sec.setStyleSheet(
            f"color:{_TXT2};font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;")
        lay.addWidget(sec)

        grid = QGridLayout(); grid.setSpacing(8)
        for i, (title_m, key, mkey, hint) in enumerate(ANALYTICS_MODULES):
            card = _ModuleCard(title_m, mkey, hint,
                               on_click=lambda k=key: self._open_module(k))
            grid.addWidget(card, i // 3, i % 3)
        lay.addLayout(grid)
        lay.addStretch()
        scroll.setWidget(body); outer.addWidget(scroll)
        return w

    def _open_module(self, key: str):
        if key not in self._panels:
            panel = self._make_panel(key)
            if panel is None:
                return
            container = self._wrap_panel(panel)
            self._panels[key] = container
            self._stack.addWidget(container)
        self._stack.setCurrentWidget(self._panels[key])

    def _wrap_panel(self, panel: QWidget) -> QWidget:
        w = QWidget(); w.setStyleSheet(f"background:{_BG1};")
        lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        bar = QWidget()
        bar.setStyleSheet(f"background:#141416;border-bottom:1px solid {_BOR};")
        bar.setFixedHeight(40)
        bl = QHBoxLayout(bar); bl.setContentsMargins(14, 0, 14, 0)
        back = QPushButton("← Analytics")
        back.setStyleSheet(
            f"background:transparent;color:{_ACC};font-size:12px;"
            f"font-weight:600;border:none;padding:0;")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self._stack.setCurrentWidget(self._landing))
        bl.addWidget(back); bl.addStretch()
        lay.addWidget(bar); lay.addWidget(panel, 1)
        return w

    def _make_panel(self, key: str):
        try:
            if key == "binomial":
                from app.panels.binomial_panel import BinomialPanel; return BinomialPanel()
            if key == "montecarlo":
                from app.panels.montecarlo_panel import MonteCarloPanel; return MonteCarloPanel()
            if key == "stochvol":
                from app.panels.stochvol_panel import StochVolPanel; return StochVolPanel()
            if key == "shortrate":
                from app.panels.shortrate_panel import ShortRatePanel; return ShortRatePanel()
            if key == "realoptions":
                from app.panels.realoptions_panel import RealOptionsPanel; return RealOptionsPanel()
        except Exception:
            pass
        return None
