"""Risk workstation: portfolio VaR, ES, stress, backtesting, limits, and XVA."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QGridLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


RISK_MODULES = [
    ("VaR / ES", "var", "Historical, parametric, Monte Carlo, EVT"),
    ("Stress Testing", "stress", "Historical, hypothetical, regulatory shocks"),
    ("Backtesting", "histvar", "Exceptions and traffic-light review"),
    ("P&L Attribution", "pnl", "Factor attribution and residual"),
    ("Counterparty Risk / XVA", "xva", "CVA, DVA, FVA, exposure profile"),
    ("Greeks Ladder", "greeks", "Sensitivity drilldown"),
]


class RiskWorkspace(QWidget):
    """Risk workspace grouped around portfolio-level risk controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = QStackedWidget()
        self._panels: dict[str, QWidget] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
        self._landing = self._build_landing()
        self._stack.addWidget(self._landing)

    def _build_landing(self):
        return WorkstationWorkspace(
            "Risk",
            "Portfolio VaR, ES, stress, backtesting, limits, and contribution analysis",
            chips=[DataSourceChip("DEMO"), StatusChip("Approximation", text="Synthetic return warning")],
            actions=[make_action("Run VaR", True), make_action("Run Stress"), make_action("Backtest"), make_action("Export")],
            kpi_strip=KpiStrip(
                [
                    ("VaR 95%", "2.4m", "Demo"),
                    ("VaR 99%", "3.8m", "Demo"),
                    ("ES 99%", "5.1m", "Demo"),
                    ("Worst Stress", "-9.6m", "2020 shock"),
                    ("Exceptions", "2", "Backtest"),
                    ("Limit Util", "74%", "No breach"),
                ]
            ),
            left=self._build_controls(),
            center=self._build_modules(),
            right=self._build_context(),
            bottom=self._build_runs(),
            context_items=[
                ("Layer", "Risk"),
                ("Input", "Active Portfolio"),
                ("Market Data", "DEMO:snap_20260604:v3"),
                ("Loss Convention", "Positive losses"),
                ("Warnings", "Demo returns are not production P&L history"),
            ],
        )

    def _build_controls(self):
        panel = WorkstationPanel("Risk Controls")
        panel.layout.addWidget(
            DenseTable(
                ["Control", "Value"],
                [
                    ["Scope", "Main Portfolio"],
                    ["Book", "Trading"],
                    ["Method", "Historical"],
                    ["Confidence", "99%"],
                    ["Horizon", "10d"],
                    ["Returns", "Demo P&L"],
                ],
            )
        )
        return panel

    def _build_modules(self):
        panel = WorkstationPanel("Risk Workflows")
        grid = QGridLayout()
        grid.setSpacing(8)
        for idx, (name, key, hint) in enumerate(RISK_MODULES):
            button = QPushButton(f"{name}\n{hint}")
            button.setMinimumHeight(58)
            button.clicked.connect(lambda checked=False, k=key: self._open_module(k))
            grid.addWidget(button, idx // 2, idx % 2)
        panel.layout.addLayout(grid)
        panel.layout.addWidget(
            DenseTable(
                ["Scenario", "P&L", "Worst Book", "Limit", "Status"],
                [
                    ["2020 Liquidity Shock", "-9.6m", "Rates", "12.0m", "OK"],
                    ["Parallel +100bp", "-4.1m", "Rates", "6.0m", "OK"],
                    ["RUB -12%", "-2.7m", "FX", "5.0m", "OK"],
                ],
            )
        )
        return panel

    def _build_context(self):
        panel = WorkstationPanel("Risk Context")
        panel.layout.addWidget(
            DenseTable(
                ["Field", "Value"],
                [
                    ["Model status", "Approximation"],
                    ["Snapshot", "DEMO:v3"],
                    ["Observation count", "1000"],
                    ["Backtest zone", "Green"],
                    ["Data warning", "Synthetic/demo returns"],
                ],
            )
        )
        return panel

    def _build_runs(self):
        panel = WorkstationPanel("Risk Runs")
        panel.layout.addWidget(
            DenseTable(
                ["Run ID", "Time", "Method", "VaR", "ES", "Warnings"],
                [
                    ["var_84219", "10:42:18", "Historical", "3.8m", "5.1m", "Demo returns"],
                    ["stress_731", "10:45:02", "Historical", "-", "-", "Demo scenario"],
                ],
            )
        )
        return panel

    def _open_module(self, key: str):
        if key not in self._panels:
            panel = self._make_panel(key)
            if panel is None:
                return
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            back = QPushButton("< Risk")
            back.clicked.connect(lambda: self._stack.setCurrentWidget(self._landing))
            layout.addWidget(back)
            layout.addWidget(panel, 1)
            self._panels[key] = container
            self._stack.addWidget(container)
        self._stack.setCurrentWidget(self._panels[key])

    def _make_panel(self, key: str):
        try:
            if key == "var":
                from app.panels.var_panel import VarPanel; return VarPanel()
            if key == "histvar":
                from app.panels.histvar_panel import HistVarPanel; return HistVarPanel()
            if key == "stress":
                from app.panels.stress_panel import StressPanel; return StressPanel()
            if key == "pnl":
                from app.panels.pnl_panel import PnLPanel; return PnLPanel()
            if key == "xva":
                from app.panels.xva_panel import XVAPanel; return XVAPanel()
            if key == "greeks":
                from app.panels.greeks_panel import GreeksPanel; return GreeksPanel()
        except Exception:
            return None
        return None
