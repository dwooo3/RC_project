"""Pricing workstation — interactive instrument pricers backed by PricingService.

Seven category tabs (Fixed Income, Option, Equity, FX, Swaps, Structured Notes,
Credit) each list their products; selecting one opens a detail pricer that values
the instrument through PricingService (governed: model status, Market Snapshot,
warnings, audit id) and can add it to the shared portfolio with its sensitivities.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import (
    QHBoxLayout, QListWidget, QStackedWidget, QTabWidget, QWidget,
)

from app.panels.pricing_catalogue import CATEGORIES, products_by_category
from app.panels.pricing_detail import PricingDetailScreen
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService
from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel
from ui.layouts import WorkstationWorkspace
from ui.theme import PALETTE


class PricingWorkspace(WorkstationWorkspace):
    def __init__(self, parent=None):
        self.market_data = MarketDataService()
        self.pricing = PricingService(market_data=self.market_data)
        super().__init__(
            "Pricing",
            "Value any instrument, view sensitivities, add it to the portfolio",
            chips=[DataSourceChip("DEMO"), StatusChip("Approximation", text="GOVERNED")],
            kpi_strip=self._kpi_strip(),
            center=self._category_tabs(),
            right=self._governance_panel(),
            bottom=self._audit_trail_panel(),
            context_items=[
                ("Service", "PricingService boundary"),
                ("Market Snapshot", "via MarketDataService"),
                ("Governance", "model status + warnings per result"),
                ("Portfolio", "Add to portfolio with sensitivities"),
            ],
        )

    def _kpi_strip(self):
        total = sum(len(products_by_category(c)) for c in CATEGORIES)
        return KpiStrip([
            ("Categories", str(len(CATEGORIES)), "instrument groups"),
            ("Products", str(total), "service-backed pricers"),
            ("Boundary", "PricingService", "no direct engine calls"),
            ("Provenance", "Audit", "snapshot + model + hash"),
        ])

    def _category_tabs(self):
        tabs = QTabWidget()
        for category in CATEGORIES:
            tabs.addTab(self._category_page(category), category)
        return tabs

    def _category_page(self, category: str) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        products = products_by_category(category)
        nav = QListWidget()
        nav.setMaximumWidth(170)
        nav.setStyleSheet(
            f"QListWidget{{background:{PALETTE.bg_panel};color:{PALETTE.txt1};"
            f"border:1px solid {PALETTE.border_soft};border-radius:4px;font-size:11px;}}"
            f"QListWidget::item:selected{{background:{PALETTE.bg_selected};color:{PALETTE.txt0};}}")
        stack = QStackedWidget()
        for product in products:
            nav.addItem(product.label)
            stack.addWidget(PricingDetailScreen(product, self.pricing))
        nav.currentRowChanged.connect(stack.setCurrentIndex)
        if products:
            nav.setCurrentRow(0)

        lay.addWidget(nav)
        lay.addWidget(stack, 1)
        return page

    def _governance_panel(self) -> QWidget:
        panel = WorkstationPanel("Governance")
        panel.layout.addWidget(DenseTable(
            ["Guardrail", "State"],
            [
                ["Pricing boundary", "PricingService only"],
                ["Market data", "Snapshot via MarketDataService"],
                ["Model status", "Shown per result"],
                ["Prototype models", "Warned, not blocked"],
                ["Reproducibility", "snapshot_id + inputs_hash"],
            ],
        ))
        return panel

    def _audit_trail_panel(self) -> QWidget:
        panel = WorkstationPanel("Pricing Audit Trail")
        try:
            trail = self.pricing.audit.audit_trail()
        except Exception:
            trail = []
        rows = [
            [
                str(r.get("calculation_type", "")),
                str(r.get("model_id", "")),
                str(r.get("inputs_hash", ""))[:12],
                str(r.get("record_id", ""))[:12],
            ]
            for r in trail[-12:]
        ]
        panel.layout.addWidget(DenseTable(["Type", "Model", "Inputs hash", "Audit id"], rows))
        return panel
