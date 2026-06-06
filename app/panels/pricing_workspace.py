"""Pricing workstation — interactive instrument pricers backed by PricingService.

A category SegmentedControl (Fixed Income, Option, Equity, FX, Swaps, Structured
Notes, Credit) lives in the shell toolbar (via ``header_controls``); below it an
instrument dropdown + Calculate drive a stack of PricingDetailScreen cards. Each
screen values its instrument through PricingService (governed: model status,
Market Snapshot, warnings, audit id) and can add it to the shared portfolio.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from app.panels.pricing_catalogue import CATEGORIES, products_by_category
from app.panels.pricing_detail import PricingDetailScreen
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService
from ui.components import SegmentedControl
from ui.theme import PALETTE


class PricingWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.market_data = MarketDataService()
        self.pricing = PricingService(market_data=self.market_data)
        self._screens: dict[tuple[str, str], PricingDetailScreen] = {}
        self._by_category: dict[str, list] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # Category selector — surfaced in the shell toolbar via header_controls().
        self._category = SegmentedControl(CATEGORIES, on_change=self._on_category)

        # Instrument dropdown + Calculate.
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self._instrument = QComboBox()
        self._instrument.setFixedWidth(300)
        self._instrument.currentIndexChanged.connect(lambda _i: self._show_current())
        controls.addWidget(self._instrument)
        self._calc_btn = QPushButton("Calculate")
        self._calc_btn.setFixedWidth(150)
        self._calc_btn.setStyleSheet(
            f"QPushButton{{background:{PALETTE.accent};color:{PALETTE.accent_on};border:none;"
            f"border-radius:10px;font-size:13px;font-weight:700;padding:8px 14px;}}"
            f"QPushButton:hover{{background:{PALETTE.accent_hi};}}")
        self._calc_btn.clicked.connect(self._calculate)
        controls.addWidget(self._calc_btn)
        controls.addStretch()
        root.addLayout(controls)

        # One detail screen per catalogue product.
        self._stack = QStackedWidget()
        for category in CATEGORIES:
            products = products_by_category(category)
            self._by_category[category] = products
            for product in products:
                screen = PricingDetailScreen(product, self.pricing)
                self._screens[(category, product.label)] = screen
                self._stack.addWidget(screen)
        root.addWidget(self._stack, 1)

        self._on_category(0)

    def header_controls(self) -> QWidget:
        """The category selector, hosted by the shell toolbar."""
        return self._category

    def _on_category(self, index: int):
        category = CATEGORIES[index]
        self._instrument.blockSignals(True)
        self._instrument.clear()
        for product in self._by_category.get(category, []):
            self._instrument.addItem(product.label)
        self._instrument.blockSignals(False)
        self._show_current()

    def _show_current(self):
        category = CATEGORIES[self._category.current_index()]
        screen = self._screens.get((category, self._instrument.currentText()))
        if screen is not None:
            self._stack.setCurrentWidget(screen)

    def _calculate(self):
        screen = self._stack.currentWidget()
        if hasattr(screen, "calculate"):
            screen.calculate()
