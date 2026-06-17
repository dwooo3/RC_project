"""Dashboard workstation: daily risk control tower.

Two tabs keep the noise out of the way: **Overview** carries only the data and
calculations (market overview + top movers, headline KPIs), while **Operations**
holds the daily checklist, warnings / required actions, model-status counts and
alerts — the operational chrome that used to crowd the main screen.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class DashboardPanel(WorkstationWorkspace):
    """Daily operating console — data/calculations on Overview, chrome on Operations."""

    def __init__(self, parent=None):
        from app.runtime import active_snapshot, is_live
        snap = active_snapshot()
        src = snap.source_value
        val_date = str(snap.valuation_date) if snap.valuation_date else "—"
        mode = "Live" if is_live() else "Demo"
        super().__init__(
            "Dashboard",
            "Market risk and pricing control tower",
            chips=[DataSourceChip(src), StatusChip("Approximation", text="Warnings: 4")],
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
            center=self._build_tabs(),
            context_items=[
                ("Portfolio", "Main Portfolio"),
                ("Book", "Trading"),
                ("Valuation Date", val_date),
                ("Snapshot", snap.snapshot_id),
                ("Mode", mode),
                ("Last Calculation", "No run in this session"),
            ],
            parent=parent,
        )

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_status(), "Overview")
        tabs.addTab(self._build_operations(), "Operations")
        return tabs

    def _build_operations(self) -> QWidget:
        """Operational chrome moved off the main view: checklist, warnings,
        model status and alerts."""
        host = QWidget()
        host.setStyleSheet("background:transparent;")
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        col.addWidget(self._build_checklist())
        col.addWidget(self._build_warnings())
        col.addWidget(self._build_alerts())
        col.addStretch(1)
        return host

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
        """Real Market Overview from the active snapshot (Stage V dashboard)."""
        panel = WorkstationPanel("Market Overview")
        try:
            from app.runtime import active_snapshot, market_service
            from services import market_views as mv
            svc = market_service()
            ov = mv.market_overview(getattr(svc, "market_db", None), active_snapshot(svc))
        except Exception:
            ov = None

        if not ov:
            panel.layout.addWidget(DenseTable(["Status"], [["Snapshot unavailable"]]))
            return panel

        # headline: КБД, ключевая ставка, FX
        head = []
        for t, label in ((1, "КБД 1Y"), (5, "КБД 5Y"), (10, "КБД 10Y")):
            if t in ov["kbd"]:
                head.append([label, f"{ov['kbd'][t]:.2f}%"])
        if ov.get("key_rate") is not None:
            head.append(["Key rate", f"{ov['key_rate']:.2f}%"])
        for pair, rate in ov["fx"].items():
            head.append([pair, f"{rate:.4f}"])
        for und, v in ov.get("key_vols", {}).items():
            head.append([f"{und} ATM vol", f"{v:.1f}%"])
        panel.layout.addWidget(DenseTable(["Indicator", "Value"], head))

        # top movers
        if ov.get("top_movers"):
            panel.layout.addWidget(DenseTable(
                ["Top mover", "Last", "Chg", "Volume"],
                [[m["secid"], f"{m['last']:,.2f}", f"{m['chg_pct']:+.2f}%",
                  f"{m['volume']:,.0f}"] for m in ov["top_movers"]]))
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
