"""Main application window — a frameless, rounded RiskCalc surface.

The window paints its own soft light backdrop with rounded corners and carries
macOS-style traffic-light controls, so floating cards (sidebar, valuation, …) read
on the wallpaper-like surface exactly as in design/pricing_v6_light.svg.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizeGrip, QVBoxLayout, QWidget,
)

from ui.shell import NAV_ITEMS, WorkspaceShell
from ui.theme import PALETTE, WORKSTATION_STYLE


class _TrafficLight(QPushButton):
    def __init__(self, color: str, hover: str, on_click):
        super().__init__()
        self.setFixedSize(13, 13)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton{{background:{color};border:none;border-radius:6px;}}"
            f"QPushButton:hover{{background:{hover};}}")
        self.clicked.connect(on_click)


class _TitleBar(QWidget):
    """Draggable top strip carrying the traffic lights."""

    def __init__(self, window: QMainWindow):
        super().__init__()
        self._win = window
        self._drag = None
        self.setFixedHeight(40)
        self.setStyleSheet("background:transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 0, 18, 0)
        row.setSpacing(8)
        row.addWidget(_TrafficLight("#FF5F57", "#FF4036", window.close))
        row.addWidget(_TrafficLight("#FEBC2E", "#F0A800", window.showMinimized))
        row.addWidget(_TrafficLight("#28C840", "#1CA833", self._toggle_max))
        row.addStretch()

    def _toggle_max(self):
        self._win.showNormal() if self._win.isMaximized() else self._win.showMaximized()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton) and not self._win.isMaximized():
            self._win.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self._toggle_max()


class _Surface(QWidget):
    """Rounded window surface that paints the soft light backdrop."""

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.setClipPath(path)

        grad = QLinearGradient(0, 0, r.width(), r.height())
        grad.setColorAt(0.0, QColor("#EBEEF4"))
        grad.setColorAt(1.0, QColor("#E1E6EF"))
        p.fillPath(path, QBrush(grad))

        w, h = r.width(), r.height()
        for cx, cy, rad, (cr, cg, cb, ca) in (
            (w * 0.16, h * 0.10, 360, (150, 120, 230, 38)),
            (w * 0.92, h * 0.08, 320, (240, 150, 200, 36)),
            (w * 0.88, h * 0.96, 400, (120, 200, 220, 34)),
        ):
            rg = QRadialGradient(cx, cy, rad)
            rg.setColorAt(0.0, QColor(cr, cg, cb, ca))
            rg.setColorAt(1.0, QColor(cr, cg, cb, 0))
            p.fillRect(r, QBrush(rg))

        p.setClipping(False)
        p.setPen(QPen(QColor(42, 47, 58, 30), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class MainWindow(QMainWindow):
    """Frameless, rounded shell host."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RiskCalc — Market Risk Workstation")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1440, 900)
        self.setMinimumSize(QSize(1180, 760))
        self.setStyleSheet(WORKSTATION_STYLE)

        surface = _Surface()
        lay = QVBoxLayout(surface)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(_TitleBar(self))
        self.shell = WorkspaceShell(self._make_panel)
        lay.addWidget(self.shell, 1)
        self.setCentralWidget(surface)

        self._grip = QSizeGrip(surface)
        self._grip.setFixedSize(16, 16)
        self._grip.setStyleSheet("background:transparent;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._grip.move(self.width() - 20, self.height() - 20)
        self._grip.raise_()

    def _make_panel(self, key: str) -> QWidget:
        if key == "dashboard":
            from app.panels.dashboard_panel import DashboardPanel
            return DashboardPanel()
        if key == "portfolio":
            from app.panels.portfolio_panel import PortfolioPanel
            return PortfolioPanel()
        if key == "risk":
            from app.panels.risk_workspace import RiskWorkspace
            return RiskWorkspace()
        if key == "market":
            from app.panels.market_workspace import MarketWorkspace
            return MarketWorkspace()
        if key == "pricing":
            from app.panels.pricing_workspace import PricingWorkspace
            return PricingWorkspace()
        if key == "governance":
            from app.panels.governance_workspace import GovernanceWorkspace
            return GovernanceWorkspace()
        if key == "analytics":
            from app.panels.analytics_workspace import AnalyticsWorkspace
            return AnalyticsWorkspace()

        label = QLabel(f"Coming soon: {key}")
        label.setStyleSheet(f"color:{PALETTE.txt2};font-size:16px;")
        return label
