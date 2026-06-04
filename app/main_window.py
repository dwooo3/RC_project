"""Main application window for the RiskCalc desktop workstation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QStackedWidget, QStatusBar, QFrame, QPushButton,
)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QKeySequence, QShortcut

from ui.components import CommandBar
from ui.theme import PALETTE, WORKSTATION_STYLE


# ── Top-level navigation ──────────────────────────────────
NAV_ITEMS = [
    ("Dashboard",     "dashboard"),
    ("Portfolio",     "portfolio"),
    ("Risk",          "risk"),
    ("Market Data",   "market"),
    ("Pricing",       "pricing"),
    ("Governance",    "governance"),
    ("Analytics Lab", "analytics"),
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
        logo_w.setStyleSheet(
            f"background:{PALETTE.bg_sidebar};border-bottom:1px solid {PALETTE.border_default};"
        )
        logo_w.setFixedHeight(64)
        ll = QVBoxLayout(logo_w)
        ll.setContentsMargins(18, 12, 18, 10)
        ll.setSpacing(2)
        t = QLabel("RiskCalc")
        t.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:16px;font-weight:700;background:transparent;"
        )
        s = QLabel("Market Risk Workstation")
        s.setStyleSheet(
            f"color:{PALETTE.accent};font-size:10px;font-weight:700;background:transparent;"
        )
        ll.addWidget(t); ll.addWidget(s)
        root.addWidget(logo_w)

        # Nav buttons
        nav_body = QWidget()
        nav_body.setStyleSheet(f"background:{PALETTE.bg_sidebar};")
        nb = QVBoxLayout(nav_body)
        nb.setContentsMargins(8, 12, 8, 8)
        nb.setSpacing(2)

        for idx, (display, key) in enumerate(NAV_ITEMS, 1):
            btn = QPushButton(display)
            btn.setCheckable(True)
            btn.setObjectName("nav_btn")
            btn.setFixedHeight(38)
            btn.setToolTip(f"Ctrl+{idx}")
            btn.setStyleSheet(f"""
                QPushButton#nav_btn {
                    background: transparent;
                    color: {PALETTE.txt1};
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    font-weight: 600;
                    text-align: left;
                    padding: 0 12px;
                }
                QPushButton#nav_btn:hover {
                    background: {PALETTE.bg_panel_elevated};
                    color: {PALETTE.txt0};
                }
                QPushButton#nav_btn:checked {
                    background: {PALETTE.accent_soft};
                    color: {PALETTE.accent};
                    font-weight: 700;
                    border-left: 3px solid {PALETTE.accent};
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
        sep.setStyleSheet(f"color:{PALETTE.border_default};max-height:1px;")
        root.addWidget(sep)
        ver = QLabel("DEMO data · Ctrl+K")
        ver.setStyleSheet(
            f"color:{PALETTE.txt2};font-size:10px;padding:8px 18px;background:{PALETTE.bg_sidebar};")
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
        self.resize(1440, 900)
        self.setMinimumSize(QSize(1280, 800))
        self.setStyleSheet(WORKSTATION_STYLE)
        self._panels: dict = {}
        self._build_ui()
        self._setup_shortcuts()
        QTimer.singleShot(0, lambda: self.sidebar.select_key("dashboard"))

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.command_bar = CommandBar()
        root.addWidget(self.command_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = Sidebar(self._show_panel)
        body_layout.addWidget(self.sidebar)

        div = QFrame(); div.setFrameShape(QFrame.VLine)
        div.setStyleSheet(f"color:{PALETTE.border_default};max-width:1px;")
        body_layout.addWidget(div)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background:{PALETTE.bg_workspace};")
        body_layout.addWidget(self.stack, 1)
        root.addWidget(body, 1)

        # Status bar
        sb = QStatusBar()
        sb.setStyleSheet(
            f"QStatusBar{{background:{PALETTE.bg_topbar};border-top:1px solid {PALETTE.border_default};"
            f"color:{PALETTE.txt2};font-size:10px;}}"
        )
        self.setStatusBar(sb)
        self._section_lbl = QLabel("Dashboard")
        self._section_lbl.setStyleSheet(f"font-weight:700;color:{PALETTE.accent};")
        sb.addWidget(QLabel("Section: "))
        sb.addWidget(self._section_lbl)
        self._data_lbl = QLabel("Last run: none   ·   Data: DEMO / snapshot v3   ·   F1 Help   ·   Ctrl+L Log")
        self._data_lbl.setAlignment(Qt.AlignRight)
        sb.addPermanentWidget(self._data_lbl)

    # ── Panel factory (lazy loading) ──────────────────────

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
        names = {k: d for d, k in NAV_ITEMS}
        self._section_lbl.setText(names.get(key, key))

    # ── Shortcuts ─────────────────────────────────────────

    def _setup_shortcuts(self):
        keys = [item[1] for item in NAV_ITEMS]
        for i, key in enumerate(keys, 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self,
                      lambda checked=False, k=key: self.sidebar.select_key(k))
        QShortcut(QKeySequence("Ctrl+K"), self, lambda: self.command_bar.search.setFocus())
