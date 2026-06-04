"""Pricing workstation: grouped product valuation with governed service context."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QGridLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


PRICING_GROUPS = {
    "Core Pricing": [
        ("Bond Pricing", "bond", "Approximation", "Fixed income, clean/dirty, DV01"),
        ("IRS / OIS", "irs", "Approximation", "Rates swaps and fair rate"),
        ("FX Forward & Options", "fx", "Validated", "GK, forwards, Greeks"),
        ("Vanilla Options", "option", "Validated", "BSM, Greeks, scenarios"),
    ],
    "Rates & Credit": [
        ("Cap / Floor / Swaption", "capfloor", "Prototype", "Black-76 caplets"),
        ("Credit / CDS", "credit", "Prototype", "Hazard and default leg"),
        ("Futures & Forwards", "futures", "Approximation", "Cost of carry"),
    ],
    "Structured & Exotic": [
        ("Barrier Options", "barrier", "Prototype", "Barrier / rebate"),
        ("Asian Options", "asian", "Prototype", "Arithmetic / geometric"),
        ("Digital / Touch", "digital", "Prototype", "Cash or asset digital"),
        ("Lookback Options", "lookback", "Prototype", "Fixed / floating strike"),
        ("Multi-Asset", "multiasset", "Prototype", "Basket and spread"),
        ("Variance Swaps", "varswap", "Prototype", "Variance and vol swaps"),
        ("Structured Products", "structured", "Prototype", "Phoenix / CLN / FTD"),
    ],
}


class PricingWorkspace(QWidget):
    """Grouped pricing landing plus legacy calculators for preserved functionality."""

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
            "Pricing",
            "Grouped instrument valuation using governed models and active market data",
            chips=[DataSourceChip("DEMO"), StatusChip("Approximation", text="6 approximation models")],
            actions=[make_action("Search Module"), make_action("Recent"), make_action("Export")],
            kpi_strip=KpiStrip(
                [
                    ("Active Snapshot", "DEMO:v3", "MarketDataService"),
                    ("Core Models", "4", "Rates / FX / Options"),
                    ("Approx", "6", "Warnings required"),
                    ("Prototype", "9", "Analytics caution"),
                    ("Blocked", "2", "Governance"),
                    ("Recent", "3", "Session"),
                ]
            ),
            left=self._build_groups(),
            center=self._build_recent(),
            right=self._build_context(),
            bottom=self._build_model_table(),
            context_items=[
                ("Layer", "Pricing"),
                ("Market Data", "Must consume active snapshot"),
                ("Governance", "Broken and Placeholder blocked by services"),
                ("Handoff", "Pricing result -> Portfolio position"),
                ("XVA", "Belongs under Risk, not generic Pricing"),
            ],
        )

    def _build_groups(self):
        panel = WorkstationPanel("Product Groups")
        for group, modules in PRICING_GROUPS.items():
            panel.layout.addWidget(DenseTable(["Group", "Modules"], [[group, len(modules)]]))
        return panel

    def _build_recent(self):
        panel = WorkstationPanel("Pricing Modules")
        grid = QGridLayout()
        grid.setSpacing(8)
        idx = 0
        for group, modules in PRICING_GROUPS.items():
            for name, key, status, hint in modules:
                button = QPushButton(f"{name}\n{status} · {hint}")
                button.setMinimumHeight(58)
                button.clicked.connect(lambda checked=False, k=key: self._open_module(k))
                grid.addWidget(button, idx // 3, idx % 3)
                idx += 1
        panel.layout.addLayout(grid)
        return panel

    def _build_context(self):
        panel = WorkstationPanel("Result Context")
        panel.layout.addWidget(
            DenseTable(
                ["Required Field", "State"],
                [
                    ["Model ID", "Visible in result"],
                    ["Model Status", "Visible in result"],
                    ["Snapshot ID", "Visible in result"],
                    ["Warnings", "Banner + context"],
                    ["Add to Portfolio", "Workflow action"],
                ],
            )
        )
        return panel

    def _build_model_table(self):
        panel = WorkstationPanel("Model Availability")
        rows = []
        for group, modules in PRICING_GROUPS.items():
            for name, _key, status, hint in modules:
                rows.append([group, name, status, hint])
        panel.layout.addWidget(DenseTable(["Group", "Module", "Status", "Description"], rows))
        return panel

    def _open_module(self, key: str):
        if key not in self._panels:
            panel = self._make_panel(key)
            if panel is None:
                return
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            back = QPushButton("< Pricing")
            back.clicked.connect(lambda: self._stack.setCurrentWidget(self._landing))
            layout.addWidget(back)
            layout.addWidget(panel, 1)
            self._panels[key] = container
            self._stack.addWidget(container)
        self._stack.setCurrentWidget(self._panels[key])

    def _make_panel(self, key: str):
        try:
            if key == "bond":
                from app.panels.bond_panel import BondPanel; return BondPanel()
            if key == "irs":
                from app.panels.irs_panel import IRSPanel; return IRSPanel()
            if key == "fx":
                from app.panels.fx_panel import FXPanel; return FXPanel()
            if key == "option":
                from app.panels.option_panel import OptionPanel; return OptionPanel()
            if key == "capfloor":
                from app.panels.capfloor_panel import CapFloorPanel; return CapFloorPanel()
            if key == "credit":
                from app.panels.credit_panel import CreditPanel; return CreditPanel()
            if key == "futures":
                from app.panels.futures_panel import FuturesPanel; return FuturesPanel()
            if key == "barrier":
                from app.panels.barrier_panel import BarrierPanel; return BarrierPanel()
            if key == "asian":
                from app.panels.asian_panel import AsianPanel; return AsianPanel()
            if key == "digital":
                from app.panels.digital_panel import DigitalPanel; return DigitalPanel()
            if key == "lookback":
                from app.panels.lookback_panel import LookbackPanel; return LookbackPanel()
            if key == "multiasset":
                from app.panels.multiasset_panel import MultiAssetPanel; return MultiAssetPanel()
            if key == "varswap":
                from app.panels.varswap_panel import VarSwapPanel; return VarSwapPanel()
            if key == "structured":
                from app.panels.structured_panel import StructuredPanel; return StructuredPanel()
        except Exception:
            return None
        return None
