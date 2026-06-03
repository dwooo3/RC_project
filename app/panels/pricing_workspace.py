"""
Pricing workspace — landing cards + internal tabs for all pricing modules.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QFrame, QScrollArea, QSizePolicy, QStackedWidget, QPushButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from app.widgets import ModelStatusBadge
from models.registry import MODEL_REGISTRY, ModelStatus


_BG1  = "#1a1a1e"
_BG2  = "#1e1e22"
_BOR  = "#2e2e33"
_TXT0 = "#f0f0f2"
_TXT1 = "#a0a0a8"
_TXT2 = "#606068"
_ACC  = "#d97757"


PRICING_MODULES = [
    ("Vanilla Options",      "option",      "black_scholes",   "BSM · Black-76 · Greeks · Scenarios"),
    ("Bond Pricing",         "bond",        "fixed_bond",      "Duration · Convexity · DV01 · Cashflows"),
    ("IRS / OIS",            "irs",         "irs",             "Fixed vs Float · NPV · Fair Rate · DV01"),
    ("Cap / Floor / Swptn",  "capfloor",    "capfloor",        "Black-76 caplets · Swaption pricing"),
    ("FX Forward & Options", "fx",          "garman_kohlhagen","GK · Delta · Vega · Smile"),
    ("Barrier Options",      "barrier",     "barrier",         "Up/Down · In/Out · Rebate"),
    ("Asian Options",        "asian",       "asian",           "Arithmetic · Geometric · MC"),
    ("Digital / Touch",      "digital",     "digital",         "Cash-or-Nothing · One-Touch"),
    ("Lookback Options",     "lookback",    "lookback",        "Fixed / Floating strike"),
    ("Multi-Asset",          "multiasset",  "multi_asset",     "Basket · Best-of · Worst-of"),
    ("Variance Swaps",       "varswap",     "variance_swap",   "Replication · Strike · P&L"),
    ("Credit / CDS",         "credit",      "cds",             "Hazard rate · Default leg · Spread"),
    ("XVA",                  "xva",         "cva_dva",         "CVA · DVA · FVA · Exposure profile"),
    ("Structured Products",  "structured",  "structured_autocall", "Autocall · Phoenix · CLN · FTD"),
    ("Futures & Forwards",   "futures",     "fx_forward",      "Cost of carry · Roll · Convergence"),
    ("IR Derivatives",       "irderiv",     "capfloor",        "Caplet vol · Swaption grid"),
    ("Commodity Deriv.",     "commodity",   "black76",         "Black-76 commodity · Energy · Metals"),
]


def _status_from_key(model_key: str) -> ModelStatus:
    entry = MODEL_REGISTRY.get(model_key, {})
    return entry.get("status", ModelStatus.PLACEHOLDER)


class _ModuleCard(QFrame):
    def __init__(self, title: str, model_key: str, hint: str,
                 on_click=None, parent=None):
        super().__init__(parent)
        self.setObjectName("module_card")
        status = _status_from_key(model_key)
        self.setStyleSheet(
            f"QFrame#module_card{{background:{_BG2};border:1px solid {_BOR};"
            f"border-radius:8px;}}"
            f"QFrame#module_card:hover{{background:#242428;border-color:#4a4a52;}}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(74)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)

        row = QHBoxLayout()
        row.setSpacing(8)
        t = QLabel(title)
        t.setStyleSheet(f"color:{_TXT0};font-size:13px;font-weight:600;background:transparent;")
        row.addWidget(t)
        row.addStretch()
        row.addWidget(ModelStatusBadge(status))
        lay.addLayout(row)

        h = QLabel(hint)
        h.setStyleSheet(f"color:{_TXT2};font-size:10px;background:transparent;")
        lay.addWidget(h)

        self._on_click = on_click

    def mousePressEvent(self, e):
        if self._on_click:
            self._on_click()


class PricingWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: dict = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()

        # ── Landing page ──────────────────────────────────
        landing = self._build_landing()
        self._stack.addWidget(landing)
        self._landing = landing

        root.addWidget(self._stack)

    def _build_landing(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background:{_BG1};")
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        body = QWidget()
        body.setStyleSheet(f"background:{_BG1};")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 28)
        lay.setSpacing(20)

        # Header
        hdr_row = QHBoxLayout()
        title = QLabel("Pricing")
        title.setStyleSheet(
            f"color:{_TXT0};font-size:24px;font-weight:700;"
            f"letter-spacing:-0.5px;background:transparent;")
        sub = QLabel("Select an instrument to open the pricing module")
        sub.setStyleSheet(f"color:{_TXT2};font-size:12px;background:transparent;")
        col = QVBoxLayout(); col.setSpacing(2)
        col.addWidget(title); col.addWidget(sub)
        hdr_row.addLayout(col); hdr_row.addStretch()
        lay.addLayout(hdr_row)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_BOR};max-height:1px;")
        lay.addWidget(sep)

        # Cards grid — 3 columns
        from PySide6.QtWidgets import QGridLayout
        sec_lbl = QLabel("INSTRUMENTS")
        sec_lbl.setStyleSheet(
            f"color:{_TXT2};font-size:10px;font-weight:700;"
            f"letter-spacing:1px;background:transparent;")
        lay.addWidget(sec_lbl)

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (title_m, key, mkey, hint) in enumerate(PRICING_MODULES):
            card = _ModuleCard(title_m, mkey, hint,
                               on_click=lambda k=key: self._open_module(k))
            grid.addWidget(card, i // 3, i % 3)
        lay.addLayout(grid)
        lay.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll)
        return w

    def _open_module(self, key: str):
        if key not in self._panels:
            panel = self._make_panel(key)
            if panel is None:
                return
            # Wrap in tab container with Back button
            container = self._wrap_panel(key, panel)
            self._panels[key] = container
            self._stack.addWidget(container)
        self._stack.setCurrentWidget(self._panels[key])

    def _wrap_panel(self, key: str, panel: QWidget) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background:{_BG1};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Top bar with back button
        bar = QWidget()
        bar.setStyleSheet(f"background:#141416;border-bottom:1px solid {_BOR};")
        bar.setFixedHeight(40)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 0, 14, 0)
        back = QPushButton("← Pricing")
        back.setStyleSheet(
            f"background:transparent;color:{_ACC};font-size:12px;font-weight:600;"
            f"border:none;padding:0;")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self._stack.setCurrentWidget(self._landing))
        bl.addWidget(back)
        bl.addStretch()
        lay.addWidget(bar)
        lay.addWidget(panel, 1)
        return w

    def _make_panel(self, key: str) -> "QWidget | None":
        try:
            if key == "option":
                from app.panels.option_panel import OptionPanel; return OptionPanel()
            if key == "bond":
                from app.panels.bond_panel import BondPanel; return BondPanel()
            if key == "irs":
                from app.panels.irs_panel import IRSPanel; return IRSPanel()
            if key == "capfloor":
                from app.panels.capfloor_panel import CapFloorPanel; return CapFloorPanel()
            if key == "fx":
                from app.panels.fx_panel import FXPanel; return FXPanel()
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
            if key == "credit":
                from app.panels.credit_panel import CreditPanel; return CreditPanel()
            if key == "xva":
                from app.panels.xva_panel import XVAPanel; return XVAPanel()
            if key == "structured":
                from app.panels.structured_panel import StructuredPanel; return StructuredPanel()
            if key == "futures":
                from app.panels.futures_panel import FuturesPanel; return FuturesPanel()
            if key == "irderiv":
                from app.panels.irderiv_panel import IRDerivPanel; return IRDerivPanel()
            if key == "commodity":
                from app.panels.commodity_panel import CommodityPanel; return CommodityPanel()
        except Exception:
            pass
        return None

    def open_key(self, key: str):
        """External navigation hook."""
        self._open_module(key)
