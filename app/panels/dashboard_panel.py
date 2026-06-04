"""Dashboard workstation: daily risk control tower."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class DashboardPanel(WorkstationWorkspace):
    """Daily operating console for portfolio, risk, data, and model status."""

    def __init__(self, parent=None):
        super().__init__(
            "Dashboard",
            "Market risk and pricing control tower",
            chips=[DataSourceChip("DEMO"), StatusChip("Approximation", text="Warnings: 4")],
            actions=[
                make_action("Refresh"),
                make_action("Run Daily Pack", primary=True),
                make_action("Export"),
            ],
            kpi_strip=KpiStrip(
                [
                    ("Market Value", "124.8m RUB", "+0.4%"),
                    ("Daily P&L", "+482k", "Demo portfolio"),
                    ("VaR 99%", "3.8m", "Not run today"),
                    ("ES 99%", "5.1m", "Not run today"),
                    ("Worst Stress", "-9.6m", "2020 shock"),
                    ("Warnings", "4", "Open log"),
                ]
            ),
            left=self._build_checklist(),
            center=self._build_status(),
            right=self._build_warnings(),
            bottom=self._build_alerts(),
            context_items=[
                ("Portfolio", "Main Portfolio"),
                ("Book", "Trading"),
                ("Valuation Date", "2026-06-04"),
                ("Snapshot", "DEMO:snap_20260604:v3"),
                ("Mode", "Demo"),
                ("Last Calculation", "No run in this session"),
            ],
            parent=parent,
        )

    def _build_checklist(self):
        panel = WorkstationPanel("Daily Checklist")
        panel.layout.addWidget(
            DenseTable(
                ["Done", "Task", "Action"],
                [
                    ["Yes", "Market data snapshot", "Open Market Data"],
                    ["Yes", "Portfolio loaded", "Open Portfolio"],
                    ["No", "Portfolio valued today", "Value Portfolio"],
                    ["No", "VaR run today", "Run VaR"],
                    ["No", "Stress pack run", "Run Stress"],
                    ["No", "Export report", "Export"],
                ],
            )
        )
        return panel

    def _build_status(self):
        panel = WorkstationPanel("Portfolio / Risk Status")
        panel.layout.addWidget(
            DenseTable(
                ["Area", "Metric", "Value", "Status"],
                [
                    ["Portfolio", "Positions", "128", "Loaded"],
                    ["Portfolio", "Market Value", "124.8m RUB", "Stale"],
                    ["Risk", "VaR 99%", "3.8m", "Needs run"],
                    ["Risk", "Worst Stress", "-9.6m", "Needs run"],
                    ["Market Data", "Snapshot", "DEMO:v3", "Demo"],
                    ["Governance", "Blocked Models", "2", "Review"],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Time", "Type", "Status", "Warnings"],
                [
                    ["10:42:18", "VaR", "Demo", "Synthetic returns"],
                    ["10:31:18", "Market Data", "Created", "Demo source"],
                    ["09:55:02", "Bond Pricing", "Approx", "Methodology warning"],
                ],
            )
        )
        return panel

    def _build_warnings(self):
        panel = WorkstationPanel("Warnings / Required Actions")
        panel.layout.addWidget(
            DenseTable(
                ["Severity", "Message", "Action"],
                [
                    ["Warning", "Demo market data active", "Open Market Data"],
                    ["Warning", "Bond model approximation", "Open Governance"],
                    ["Error", "Broken model blocked", "Open Model Registry"],
                    ["Warning", "IRS single-curve limitation", "Open Pricing"],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Model Status", "Count"],
                [["Validated", 8], ["Approximation", 6], ["Prototype", 9], ["Blocked", 2]],
            )
        )
        return panel

    def _build_alerts(self):
        panel = WorkstationPanel("Alerts")
        panel.layout.addWidget(
            DenseTable(
                ["Severity", "Object", "Message", "Owner", "Action"],
                [
                    ["P1", "Market Data", "Snapshot uses demo data", "MarketDataService", "Validate"],
                    ["P1", "Portfolio", "Valuation not run today", "PortfolioService", "Value"],
                    ["P1", "Risk", "VaR based on synthetic returns", "RiskService", "Load P&L"],
                    ["P2", "Governance", "Validation evidence incomplete", "GovernanceService", "Review"],
                ],
            )
        )
        return panel
