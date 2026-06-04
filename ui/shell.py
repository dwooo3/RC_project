"""Reusable workstation shell for all RiskCalc workspaces."""

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.components import CommandBar
from ui.theme import PALETTE


NAV_ITEMS = [
    ("Dashboard", "dashboard"),
    ("Portfolio", "portfolio"),
    ("Risk", "risk"),
    ("Market Data", "market"),
    ("Pricing", "pricing"),
    ("Governance", "governance"),
    ("Analytics Lab", "analytics"),
]


WORKSPACE_META = {
    "dashboard": (
        "Dashboard",
        "Daily control tower for portfolio, risk, market data, and model warnings",
    ),
    "portfolio": (
        "Portfolio",
        "Positions, valuation, risk-factor exposure, scenario P&L, and attribution",
    ),
    "risk": (
        "Risk",
        "Portfolio VaR, ES, stress, backtesting, limits, and contribution analysis",
    ),
    "market": (
        "Market Data",
        "Snapshots, sources, yield curves, vol surfaces, FX, credit, and validation",
    ),
    "pricing": (
        "Pricing",
        "Grouped instrument valuation using governed models and active market data",
    ),
    "governance": (
        "Governance",
        "Model registry, validation, audit trail, and production gating",
    ),
    "analytics": (
        "Analytics Lab",
        "Research models, numerical methods, experiments, and benchmarking",
    ),
}


class GlobalNavigation(QWidget):
    """Left navigation containing only approved product layers."""

    def __init__(self, on_select: Callable[[str], None], parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(196)
        self._on_select = on_select
        self._buttons: dict[str, QPushButton] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        logo = QWidget()
        logo.setFixedHeight(56)
        logo.setStyleSheet(
            f"background:{PALETTE.bg_topbar};border-bottom:1px solid {PALETTE.border_soft};"
        )
        logo_layout = QVBoxLayout(logo)
        logo_layout.setContentsMargins(14, 10, 14, 8)
        logo_layout.setSpacing(2)

        title = QLabel("RiskCalc")
        title.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:15px;font-weight:700;background:transparent;"
        )
        subtitle = QLabel("Market Risk Workstation")
        subtitle.setStyleSheet(
            f"color:{PALETTE.accent};font-size:10px;font-weight:700;background:transparent;"
        )
        logo_layout.addWidget(title)
        logo_layout.addWidget(subtitle)
        root.addWidget(logo)

        body = QWidget()
        body.setStyleSheet(f"background:{PALETTE.bg_topbar};")
        nav_layout = QVBoxLayout(body)
        nav_layout.setContentsMargins(6, 8, 6, 6)
        nav_layout.setSpacing(1)

        for idx, (display, key) in enumerate(NAV_ITEMS, 1):
            button = QPushButton(display)
            button.setCheckable(True)
            button.setObjectName("nav_btn")
            button.setFixedHeight(32)
            button.setToolTip(f"Ctrl+{idx}")
            button.setStyleSheet(
                f"""
                QPushButton#nav_btn {{
                    background: transparent;
                    color: {PALETTE.txt1};
                    border: none;
                    border-radius: 3px;
                    font-size: 12px;
                    font-weight: 600;
                    text-align: left;
                    padding: 0 10px;
                }}
                QPushButton#nav_btn:hover {{
                    background: {PALETTE.bg_panel_elevated};
                    color: {PALETTE.txt0};
                }}
                QPushButton#nav_btn:checked {{
                    background: {PALETTE.accent_soft};
                    color: {PALETTE.accent};
                    font-weight: 700;
                    border-left: 3px solid {PALETTE.accent};
                }}
                """
            )
            button.toggled.connect(lambda checked, k=key: checked and self.select_key(k))
            self._buttons[key] = button
            nav_layout.addWidget(button)

        nav_layout.addStretch()
        root.addWidget(body, 1)

        footer = QLabel("DEMO data · Ctrl+K")
        footer.setStyleSheet(
            f"color:{PALETTE.txt2};font-size:10px;padding:6px 14px;"
            f"background:{PALETTE.bg_topbar};border-top:1px solid {PALETTE.border_soft};"
        )
        root.addWidget(footer)

    def select_key(self, key: str):
        for item_key, button in self._buttons.items():
            button.blockSignals(True)
            button.setChecked(item_key == key)
            button.blockSignals(False)
        self._on_select(key)

    def select_first(self):
        self.select_key(NAV_ITEMS[0][1])


class WorkspaceHeaderBar(QWidget):
    """Shell-level workspace header shared by all workspaces."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setStyleSheet(
            f"background:{PALETTE.bg_workspace};border-bottom:1px solid {PALETTE.border_soft};"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.title = QLabel("")
        self.title.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:16px;font-weight:700;background:transparent;"
        )
        self.subtitle = QLabel("")
        self.subtitle.setStyleSheet(
            f"color:{PALETTE.txt2};font-size:11px;background:transparent;"
        )
        text_col.addWidget(self.title)
        text_col.addWidget(self.subtitle)
        layout.addLayout(text_col, 1)

        self.scope = QLabel("Scope: Main Portfolio / Trading / DEMO")
        self.scope.setStyleSheet(
            f"color:{PALETTE.txt1};font-size:11px;background:{PALETTE.bg_panel};"
            f"border:1px solid {PALETTE.border_soft};border-radius:3px;padding:2px 7px;"
        )
        layout.addWidget(self.scope)

    def set_workspace(self, key: str):
        title, subtitle = WORKSPACE_META.get(key, (key.title(), ""))
        self.title.setText(title)
        self.subtitle.setText(subtitle)


class ShellStatusBar(QWidget):
    """Bottom audit/status bar owned by the shell."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setStyleSheet(
            f"background:{PALETTE.bg_topbar};border-top:1px solid {PALETTE.border_soft};"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        self.section = QLabel("Section: Dashboard")
        self.section.setStyleSheet(f"color:{PALETTE.accent};font-size:10px;font-weight:700;")
        self.audit = QLabel(
            "Last run: none   ·   Data: DEMO / snapshot v3   ·   F1 Help   ·   Ctrl+L Log"
        )
        self.audit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.audit.setStyleSheet(f"color:{PALETTE.txt2};font-size:10px;")
        layout.addWidget(self.section)
        layout.addStretch()
        layout.addWidget(self.audit)

    def set_workspace(self, key: str):
        title, _subtitle = WORKSPACE_META.get(key, (key.title(), ""))
        self.section.setText(f"Section: {title}")


class WorkspaceShell(QWidget):
    """Reusable shell containing global navigation, context bar, header, content, and status."""

    def __init__(self, panel_factory: Callable[[str], QWidget], parent=None):
        super().__init__(parent)
        self.setMinimumSize(QSize(1280, 800))
        self._panel_factory = panel_factory
        self._panels: dict[str, QWidget] = {}
        self._build()
        self._setup_shortcuts()
        QTimer.singleShot(0, self.global_navigation.select_first)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.context_bar = CommandBar()
        root.addWidget(self.context_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.global_navigation = GlobalNavigation(self.show_workspace)
        body_layout.addWidget(self.global_navigation)

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet(f"color:{PALETTE.border_soft};max-width:1px;")
        body_layout.addWidget(divider)

        workspace_column = QWidget()
        workspace_layout = QVBoxLayout(workspace_column)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        self.workspace_header = WorkspaceHeaderBar()
        workspace_layout.addWidget(self.workspace_header)

        self.content_area = QStackedWidget()
        self.content_area.setStyleSheet(f"background:{PALETTE.bg_workspace};")
        workspace_layout.addWidget(self.content_area, 1)

        body_layout.addWidget(workspace_column, 1)
        root.addWidget(body, 1)

        self.status_bar = ShellStatusBar()
        root.addWidget(self.status_bar)

    def _setup_shortcuts(self):
        for idx, (_display, key) in enumerate(NAV_ITEMS, 1):
            QShortcut(QKeySequence(f"Ctrl+{idx}"), self, lambda checked=False, k=key: self.select_workspace(k))
        QShortcut(QKeySequence("Ctrl+K"), self, lambda: self.context_bar.search.setFocus())
        QShortcut(QKeySequence("Ctrl+L"), self, lambda: self.status_bar.audit.setText("Warnings: 4 · Demo data · Approximation models active"))

    def _get_panel(self, key: str) -> QWidget:
        if key not in self._panels:
            panel = self._panel_factory(key)
            self._panels[key] = panel
            self.content_area.addWidget(panel)
        return self._panels[key]

    def select_workspace(self, key: str):
        self.global_navigation.select_key(key)

    def show_workspace(self, key: str):
        panel = self._get_panel(key)
        self.content_area.setCurrentWidget(panel)
        self.workspace_header.set_workspace(key)
        self.status_bar.set_workspace(key)

    @property
    def search(self):
        return self.context_bar.search
