"""Pricing workstation — interactive instrument pricers backed by PricingService.

Seven category tabs (Fixed Income, Option, Equity, FX, Swaps, Structured Notes,
Credit) each list their products; selecting one opens a detail pricer that values
the instrument through PricingService (governed: model status, Market Snapshot,
warnings, audit id) and can add it to the shared portfolio with its sensitivities.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import (
    QComboBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from app.panels.pricing_catalogue import CATEGORIES, products_by_category
from app.panels.pricing_detail import PricingDetailScreen
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService
from ui.components import DataSourceChip
from ui.layouts import WorkstationWorkspace
from ui.theme import PALETTE


class PricingWorkspace(WorkstationWorkspace):
    def __init__(self, parent=None):
        self.market_data = MarketDataService()
        self.pricing = PricingService(market_data=self.market_data)
        super().__init__(
            "Pricing",
            "Value any instrument, view sensitivities, add it to the portfolio",
            chips=[DataSourceChip("DEMO")],
            center=self._category_tabs(),
        )

    def _category_tabs(self):
        tabs = QTabWidget()
        for category in CATEGORIES:
            tabs.addTab(self._category_page(category), category)
        return tabs

    def _category_page(self, category: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)

        products = products_by_category(category)
        selector = QComboBox()
        selector.setMaximumWidth(280)
        selector.setStyleSheet(
            f"QComboBox{{background:{PALETTE.bg_panel_elevated};color:{PALETTE.txt0};"
            f"border:1px solid {PALETTE.border_default};border-radius:4px;padding:4px 8px;font-size:12px;}}")
        stack = QStackedWidget()
        for product in products:
            selector.addItem(product.label)
            stack.addWidget(PricingDetailScreen(product, self.pricing))
        selector.currentIndexChanged.connect(stack.setCurrentIndex)
        if products:
            selector.setCurrentIndex(0)

        lay.addWidget(selector)
        lay.addWidget(stack, 1)
        return page
