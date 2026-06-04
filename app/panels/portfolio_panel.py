"""Portfolio workstation: positions, valuation, exposure, scenario P&L, attribution."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class PortfolioPanel(WorkstationWorkspace):
    """Portfolio-centered workspace for production risk workflows."""

    def __init__(self, parent=None):
        super().__init__(
            "Portfolio",
            "Positions, valuation, risk-factor exposure, scenario P&L, and attribution",
            chips=[DataSourceChip("DEMO"), StatusChip("Approximation", text="Valuation not run today")],
            actions=[
                make_action("Add Position"),
                make_action("Import"),
                make_action("Value", primary=True),
                make_action("Run Risk"),
                make_action("Export"),
            ],
            kpi_strip=KpiStrip(
                [
                    ("Market Value", "124.8m", "RUB"),
                    ("Daily P&L", "+482k", "Demo"),
                    ("Positions", "128", "Trading"),
                    ("Rates DV01", "42k", "RUB/bp"),
                    ("FX Delta", "-1.2m", "USD/RUB"),
                    ("Vol Vega", "318k", "1 vol pt"),
                    ("CS01", "76k", "Credit"),
                ]
            ),
            left=self._build_scope(),
            center=self._build_positions(),
            right=self._build_position_context(),
            bottom=self._build_exposure(),
            context_items=[
                ("Layer", "Portfolio"),
                ("Portfolio", "Main Portfolio"),
                ("Book", "Trading"),
                ("Base Currency", "RUB"),
                ("Snapshot", "DEMO:snap_20260604:v3"),
                ("Workflow", "Portfolio -> Risk -> Governance"),
            ],
            parent=parent,
        )

    def _build_scope(self):
        panel = WorkstationPanel("Portfolio Scope")
        panel.layout.addWidget(
            DenseTable(
                ["Filter", "Value"],
                [
                    ["Portfolio", "Main Portfolio"],
                    ["Book", "Trading"],
                    ["Currency", "RUB"],
                    ["Valuation Date", "2026-06-04"],
                    ["Snapshot", "DEMO:v3"],
                    ["Mode", "Demo"],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Action", "Shortcut"],
                [
                    ["Add Position", "N"],
                    ["Import Positions", "I"],
                    ["Value Portfolio", "V"],
                    ["Run VaR", "Shift+V"],
                    ["Scenario P&L", "S"],
                    ["P&L Explain", "A"],
                ],
            )
        )
        return panel

    def _build_positions(self):
        panel = WorkstationPanel("Positions")
        panel.layout.addWidget(
            DenseTable(
                ["ID", "Product", "Qty", "MV", "P&L", "Rates", "FX", "Vol", "Status"],
                [
                    ["pos_001", "Bond", "10m", "9.8m", "+12k", "8.2k", "-", "-", "Approx"],
                    ["pos_002", "IRS", "20m", "4.8m", "-31k", "11.4k", "-", "-", "Approx"],
                    ["pos_003", "FXO", "5m", "1.1m", "+22k", "-", "1.2m", "33k", "Validated"],
                    ["pos_004", "Equity Opt", "2m", "0.9m", "+8k", "-", "-", "18k", "Validated"],
                    ["pos_005", "CDS", "15m", "-0.4m", "-11k", "-", "-", "-", "Prototype"],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Risk Factor", "Bucket", "Exposure", "Contribution", "Limit", "Utilization"],
                [
                    ["rates.yield_curve", "Rates", "42k DV01", "-4.1m", "6.0m", "68%"],
                    ["fx.usdrub", "FX", "-1.2m delta", "-2.7m", "5.0m", "54%"],
                    ["vol.implied", "Volatility", "318k vega", "-0.9m", "2.0m", "45%"],
                    ["credit.spread", "Credit", "76k CS01", "-1.9m", "4.0m", "48%"],
                ],
            )
        )
        return panel

    def _build_position_context(self):
        panel = WorkstationPanel("Position Context")
        panel.layout.addWidget(
            DenseTable(
                ["Field", "Value"],
                [
                    ["Selected", "pos_002"],
                    ["Product", "IRS 5Y"],
                    ["Market Value", "4.8m"],
                    ["DV01", "11.4k"],
                    ["Model", "irs"],
                    ["Status", "Approximation"],
                    ["Warning", "Single-curve limitation"],
                ],
            )
        )
        return panel

    def _build_exposure(self):
        panel = WorkstationPanel("Scenario P&L / Attribution")
        panel.layout.addWidget(
            DenseTable(
                ["Scenario", "Rates", "FX", "Equity", "Credit", "Vol", "Total P&L"],
                [
                    ["2020 Liquidity Shock", "-4.1m", "-2.7m", "-0.8m", "-1.9m", "-0.1m", "-9.6m"],
                    ["Parallel +100bp", "-4.1m", "0.0m", "0.0m", "-0.2m", "0.0m", "-4.3m"],
                    ["RUB -12%", "0.0m", "-2.7m", "0.0m", "0.0m", "0.0m", "-2.7m"],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["P&L Component", "Amount", "Notes"],
                [
                    ["Delta P&L", "-2.7m", "FX/equity spot"],
                    ["Rate P&L", "-4.1m", "Curve shift"],
                    ["Credit P&L", "-1.9m", "Spread widening"],
                    ["Vega P&L", "-0.1m", "Vol shock"],
                    ["Residual", "-0.8m", "Model/scenario residual"],
                ],
            )
        )
        return panel
