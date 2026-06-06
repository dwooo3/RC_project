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

from ui.components import card_shadow
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
    """Left navigation as a floating rounded glass-card tile (no account row)."""

    def __init__(self, on_select: Callable[[str], None], parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(240)
        self._on_select = on_select
        self._buttons: dict[str, QPushButton] = {}
        self._build()

    def _build(self):
        self.setStyleSheet(
            f"QWidget#sidebar{{background:{PALETTE.bg_card};"
            f"border:1px solid {PALETTE.card_border};border-radius:16px;}}"
        )
        card_shadow(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 16, 14, 16)
        root.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(8)
        logo = QLabel("R")
        logo.setFixedSize(24, 24)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            f"background:{PALETTE.accent};color:{PALETTE.accent_on};border-radius:7px;"
            "font-size:14px;font-weight:800;"
        )
        name = QLabel("RiskCalc")
        name.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:15px;font-weight:700;background:transparent;"
        )
        brand.addWidget(logo)
        brand.addWidget(name)
        brand.addStretch()
        root.addLayout(brand)
        root.addSpacing(12)

        for idx, (display, key) in enumerate(NAV_ITEMS, 1):
            button = QPushButton(display)
            button.setCheckable(True)
            button.setObjectName("nav_btn")
            button.setFixedHeight(38)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(f"Ctrl+{idx}")
            button.setStyleSheet(
                f"""
                QPushButton#nav_btn {{
                    background: transparent;
                    color: {PALETTE.txt_nav};
                    border: none;
                    border-radius: 10px;
                    font-size: 13px;
                    font-weight: 500;
                    text-align: left;
                    padding: 0 12px;
                }}
                QPushButton#nav_btn:hover {{
                    background: {PALETTE.bg_field};
                    color: {PALETTE.txt0};
                }}
                QPushButton#nav_btn:checked {{
                    background: {PALETTE.accent_soft};
                    color: {PALETTE.accent_lo};
                    font-weight: 600;
                }}
                """
            )
            button.toggled.connect(lambda checked, k=key: checked and self.select_key(k))
            self._buttons[key] = button
            root.addWidget(button)

        root.addStretch()

    def select_key(self, key: str):
        for item_key, button in self._buttons.items():
            button.blockSignals(True)
            button.setChecked(item_key == key)
            button.blockSignals(False)
        self._on_select(key)

    def select_first(self):
        self.select_key(NAV_ITEMS[0][1])


class WorkspaceHeaderBar(QWidget):
    """Shell-level toolbar: page title + per-workspace controls slot + scope chip.

    The subtitle under the title was removed in the v6 design; ``self.subtitle``
    is kept (hidden) for backward compatibility. Workspaces inject their own
    controls (e.g. a SegmentedControl) into the right-of-title slot via
    :meth:`set_controls`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setStyleSheet(f"background:{PALETTE.bg_workspace};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 8, 16, 8)
        layout.setSpacing(14)

        self.title = QLabel("")
        self.title.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:22px;font-weight:700;background:transparent;"
        )
        layout.addWidget(self.title)

        # Per-workspace controls slot (right of the title).
        self._controls = QHBoxLayout()
        self._controls.setSpacing(8)
        self._controls.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._controls)

        layout.addStretch()

        self.scope = QLabel("Main Portfolio · Trading · DEMO")
        self.scope.setStyleSheet(
            f"color:{PALETTE.txt1};font-size:11px;background:{PALETTE.bg_card};"
            f"border:1px solid {PALETTE.card_border};border-radius:8px;padding:3px 9px;"
        )
        layout.addWidget(self.scope)

        # Kept for compatibility; not displayed in the v6 toolbar.
        self.subtitle = QLabel("")
        self.subtitle.hide()

    def set_workspace(self, key: str):
        title, subtitle = WORKSPACE_META.get(key, (key.title(), ""))
        self.title.setText(title)
        self.subtitle.setText(subtitle)

    def set_controls(self, widget: QWidget | None):
        """Replace the controls-slot content with ``widget`` (or clear it)."""
        while self._controls.count():
            item = self._controls.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        if widget is not None:
            self._controls.addWidget(widget)


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

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(16, 8, 16, 16)
        body_layout.setSpacing(16)

        self.global_navigation = GlobalNavigation(self.show_workspace)
        body_layout.addWidget(self.global_navigation)

        workspace_column = QWidget()
        workspace_column.setStyleSheet("background:transparent;")
        workspace_layout = QVBoxLayout(workspace_column)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(8)

        self.workspace_header = WorkspaceHeaderBar()
        workspace_layout.addWidget(self.workspace_header)

        self.content_area = QStackedWidget()
        self.content_area.setStyleSheet("background:transparent;")
        workspace_layout.addWidget(self.content_area, 1)

        body_layout.addWidget(workspace_column, 1)
        root.addWidget(body, 1)

    def _setup_shortcuts(self):
        for idx, (_display, key) in enumerate(NAV_ITEMS, 1):
            QShortcut(QKeySequence(f"Ctrl+{idx}"), self, lambda checked=False, k=key: self.select_workspace(k))

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
        self.current_key = key
        # Workspaces may surface their own controls (e.g. Pricing's category
        # selector) in the toolbar's controls slot.
        controls = panel.header_controls() if hasattr(panel, "header_controls") else None
        self.workspace_header.set_controls(controls)
