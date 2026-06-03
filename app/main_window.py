"""Main application window — workflow-oriented 7-section navigation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QStackedWidget, QStatusBar, QFrame, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QColor, QKeySequence, QShortcut

from app.styles import APP_STYLE, LIGHT_STYLE


# ── Top-level navigation ──────────────────────────────────
NAV_ITEMS = [
    ("Dashboard",  "dashboard",   "⬛"),
    ("Market",     "market",      "⬛"),
    ("Pricing",    "pricing",     "⬛"),
    ("Portfolio",  "portfolio",   "⬛"),
    ("Risk",       "risk",        "⬛"),
    ("Analytics",  "analytics",   "⬛"),
    ("Settings",   "settings",    "⬛"),
]


class Sidebar(QWidget):
    def __init__(self, on_select, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(200)
        self._on_select = on_select
        self._buttons: dict[str, QPushButton] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Logo
        logo_w = QWidget()
        logo_w.setStyleSheet("background:#0f0f11;border-bottom:1px solid #2e2e33;")
        logo_w.setFixedHeight(64)
        ll = QVBoxLayout(logo_w)
        ll.setContentsMargins(18, 12, 18, 10)
        ll.setSpacing(2)
        t = QLabel("RiskCalc")
        t.setStyleSheet(
            "color:#f0f0f2;font-size:17px;font-weight:700;"
            "letter-spacing:-0.3px;background:transparent;")
        s = QLabel("Pricing & Risk Engine")
        s.setStyleSheet(
            "color:#d97757;font-size:10px;font-weight:500;"
            "letter-spacing:0.2px;background:transparent;")
        ll.addWidget(t); ll.addWidget(s)
        root.addWidget(logo_w)

        # Nav buttons
        nav_body = QWidget()
        nav_body.setStyleSheet("background:#1a1a1e;")
        nb = QVBoxLayout(nav_body)
        nb.setContentsMargins(8, 12, 8, 8)
        nb.setSpacing(2)

        for display, key, _ in NAV_ITEMS:
            btn = QPushButton(display)
            btn.setCheckable(True)
            btn.setObjectName("nav_btn")
            btn.setFixedHeight(38)
            btn.setStyleSheet("""
                QPushButton#nav_btn {
                    background: transparent;
                    color: #a0a0a8;
                    border: none;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: 500;
                    text-align: left;
                    padding: 0 12px;
                }
                QPushButton#nav_btn:hover {
                    background: #242428;
                    color: #f0f0f2;
                }
                QPushButton#nav_btn:checked {
                    background: #3a2518;
                    color: #d97757;
                    font-weight: 600;
                }
            """)
            # Use toggled so accessibility clicks (AppleScript/VoiceOver) also navigate
            btn.toggled.connect(lambda checked, k=key: checked and self._select(k))
            self._buttons[key] = btn
            nb.addWidget(btn)

        nb.addStretch()
        root.addWidget(nav_body, 1)

        # Footer
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2e2e33;max-height:1px;")
        root.addWidget(sep)
        ver = QLabel("v1.0  ·  MOEX pending")
        ver.setStyleSheet(
            "color:#38383d;font-size:10px;padding:8px 18px;background:#1a1a1e;")
        root.addWidget(ver)

    def _select(self, key: str):
        for k, btn in self._buttons.items():
            btn.blockSignals(True)
            btn.setChecked(k == key)
            btn.blockSignals(False)
        self._on_select(key)

    def select_key(self, key: str):
        self._select(key)

    def select_first(self):
        self._select(NAV_ITEMS[0][1])


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RiskCalc — Market Risk & Pricing Engine")
        self.resize(1440, 860)
        self.setMinimumSize(QSize(1100, 720))
        self._dark_mode = True
        self.setStyleSheet(APP_STYLE)
        self._panels: dict = {}
        self._build_ui()
        self._setup_shortcuts()
        QTimer.singleShot(0, lambda: self.sidebar.select_key("dashboard"))

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(self._show_panel)
        root.addWidget(self.sidebar)

        div = QFrame(); div.setFrameShape(QFrame.VLine)
        div.setStyleSheet("color:#2c2c2e;max-width:1px;")
        root.addWidget(div)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background:#0f0f11;")
        root.addWidget(self.stack, 1)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._section_lbl = QLabel("Dashboard")
        self._section_lbl.setStyleSheet("font-weight:600;color:#d97757;")
        sb.addWidget(QLabel("Section: "))
        sb.addWidget(self._section_lbl)
        self._data_lbl = QLabel("Data: Demo / Manual   ·   MOEX ISS: pending")
        self._data_lbl.setAlignment(Qt.AlignRight)
        sb.addPermanentWidget(self._data_lbl)

    # ── Panel factory (lazy loading) ──────────────────────

    def _make_panel(self, key: str) -> QWidget:
        if key == "dashboard":
            from app.panels.dashboard_panel import DashboardPanel
            return DashboardPanel()
        if key == "market":
            from app.panels.market_workspace import MarketWorkspace
            return MarketWorkspace()
        if key == "pricing":
            from app.panels.pricing_workspace import PricingWorkspace
            return PricingWorkspace()
        if key == "portfolio":
            from app.panels.portfolio_panel import PortfolioPanel
            return PortfolioPanel()
        if key == "risk":
            from app.panels.risk_workspace import RiskWorkspace
            return RiskWorkspace()
        if key == "analytics":
            from app.panels.analytics_workspace import AnalyticsWorkspace
            return AnalyticsWorkspace()
        if key == "settings":
            from app.panels.settings_panel import SettingsPanel
            return SettingsPanel()
        lbl = QLabel(f"Coming soon: {key}")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#8e8e93;font-size:16px;")
        return lbl

    def _get_panel(self, key: str) -> QWidget:
        if key not in self._panels:
            w = self._make_panel(key)
            self._panels[key] = w
            self.stack.addWidget(w)
        return self._panels[key]

    def _show_panel(self, key: str):
        panel = self._get_panel(key)
        self.stack.setCurrentWidget(panel)
        names = {k: d for d, k, _ in NAV_ITEMS}
        self._section_lbl.setText(names.get(key, key))

    # ── Shortcuts ─────────────────────────────────────────

    def _setup_shortcuts(self):
        keys = [item[1] for item in NAV_ITEMS]
        for i, key in enumerate(keys, 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self,
                      lambda checked=False, k=key: self.sidebar.select_key(k))
        # Theme toggle
        QShortcut(QKeySequence("Ctrl+T"), self, self._toggle_theme)

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self.setStyleSheet(APP_STYLE if self._dark_mode else LIGHT_STYLE)
