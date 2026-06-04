"""Market Data workstation: snapshots, curves, surfaces, FX, and credit data."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QStackedWidget, QTabWidget

from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class MarketWorkspace(WorkstationWorkspace):
    """Market Data owns data inputs and validation, not pricing workflows."""

    def __init__(self, parent=None):
        self._detail_stack = QStackedWidget()
        super().__init__(
            "Market Data",
            "Snapshots, sources, yield curves, vol surfaces, FX market data, and validation",
            chips=[DataSourceChip("DEMO"), StatusChip("Approximation", text="MOEX prepared")],
            actions=[make_action("Create Snapshot"), make_action("Import CSV"), make_action("Validate", True)],
            kpi_strip=KpiStrip(
                [
                    ("Snapshot", "v3", "DEMO"),
                    ("Val Date", "2026-06-04", "active"),
                    ("Curves", "4", "RUB/USD/EUR"),
                    ("Vol Surfaces", "2", "demo"),
                    ("FX Pairs", "8", "manual"),
                    ("Warnings", "2", "demo source"),
                ]
            ),
            left=self._build_sources(),
            center=self._build_overview(),
            right=self._build_validation(),
            bottom=self._build_detail_tabs(),
            context_items=[
                ("Layer", "Market Data"),
                ("Active Snapshot", "DEMO:snap_20260604:v3"),
                ("Source", "DEMO / MANUAL / CSV"),
                ("MOEX", "Interface prepared"),
                ("Bloomberg", "Interface only"),
                ("Reuters", "Interface only"),
            ],
            parent=parent,
        )

    def _build_sources(self):
        panel = WorkstationPanel("Snapshot / Sources")
        panel.layout.addWidget(
            DenseTable(
                ["Source", "State", "Use"],
                [
                    ["DEMO", "Healthy", "Default snapshot"],
                    ["MANUAL", "Available", "User-entered data"],
                    ["CSV", "Available", "Parsed import"],
                    ["MOEX", "Interface", "Prepared"],
                    ["Bloomberg", "Disabled", "No implementation"],
                    ["Reuters", "Disabled", "No implementation"],
                ],
            )
        )
        return panel

    def _build_overview(self):
        panel = WorkstationPanel("Market Data Summary")
        panel.layout.addWidget(
            DenseTable(
                ["Object", "Source", "Version", "Quality", "Warnings"],
                [
                    ["RUB_GOVT", "DEMO", "v3", "Warning", "Demo curve"],
                    ["RUB_OIS", "DEMO", "v3", "Warning", "Demo curve"],
                    ["FX_USDRUB", "MANUAL", "v1", "OK", "Manual source"],
                    ["EQVOL_DEMO", "DEMO", "v1", "Warning", "Flat vol"],
                    ["CREDIT_CORP", "DEMO", "v1", "Warning", "Spread demo"],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Curve", "1Y", "5Y", "10Y", "10Y-2Y"],
                [
                    ["RUB_GOVT", "7.20%", "7.80%", "8.10%", "42bp"],
                    ["RUB_OIS", "6.80%", "7.10%", "7.40%", "28bp"],
                    ["USD_SOFR", "4.90%", "4.35%", "4.10%", "-45bp"],
                ],
            )
        )
        return panel

    def _build_validation(self):
        panel = WorkstationPanel("Validation")
        panel.layout.addWidget(
            DenseTable(
                ["Check", "Status", "Detail"],
                [
                    ["No NaN", "Pass", "All demo objects"],
                    ["No inf", "Pass", "All demo objects"],
                    ["Positive DF", "Pass", "RUB curves"],
                    ["Monotonic DF", "Pass", "RUB curves"],
                    ["Source quality", "Warn", "Demo/manual data"],
                ],
            )
        )
        return panel

    def _build_detail_tabs(self):
        tabs = QTabWidget()
        tabs.addTab(self._wrap_legacy_yield_curves(), "Yield Curves")
        tabs.addTab(self._wrap_legacy_vol_surface(), "Vol Surfaces")
        tabs.addTab(self._fx_market_data(), "FX Market")
        tabs.addTab(self._credit_market_data(), "Credit Curves")
        return tabs

    def _wrap_legacy_yield_curves(self):
        from app.panels.yield_curve_panel import YieldCurvePanel
        return YieldCurvePanel()

    def _wrap_legacy_vol_surface(self):
        from app.panels.volsurface_panel import VolSurfacePanel
        return VolSurfacePanel()

    def _fx_market_data(self):
        panel = WorkstationPanel("FX Market Data")
        panel.layout.addWidget(
            DenseTable(
                ["Pair", "Spot", "Forward 1M", "Vol 1M", "Source"],
                [["USD/RUB", "90.00", "90.42", "14.2%", "MANUAL"], ["EUR/RUB", "98.00", "98.51", "13.8%", "MANUAL"]],
            )
        )
        return panel

    def _credit_market_data(self):
        panel = WorkstationPanel("Credit Curves")
        panel.layout.addWidget(
            DenseTable(
                ["Curve", "1Y", "3Y", "5Y", "Source"],
                [["CORP_1T", "100bp", "120bp", "145bp", "DEMO"], ["CORP_HY", "300bp", "360bp", "420bp", "DEMO"]],
            )
        )
        return panel
