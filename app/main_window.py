"""Main application window hosting the shared RiskCalc workstation shell."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QMainWindow, QWidget

from ui.shell import NAV_ITEMS, WorkspaceShell
from ui.theme import PALETTE, WORKSTATION_STYLE


class MainWindow(QMainWindow):
    """Thin QMainWindow wrapper around WorkspaceShell."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RiskCalc — Market Risk Workstation")
        self.resize(1440, 900)
        self.setMinimumSize(QSize(1280, 800))
        self.setStyleSheet(WORKSTATION_STYLE)
        self.shell = WorkspaceShell(self._make_panel)
        self.setCentralWidget(self.shell)

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
