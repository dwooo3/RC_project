"""Market workspace — Yield Curves · Vol Surface · FX Rates · Implied Vol."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget


class MarketWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        from app.panels.yield_curve_panel import YieldCurvePanel
        from app.panels.volsurface_panel  import VolSurfacePanel
        from app.panels.impliedvol_panel  import ImpliedVolPanel
        from app.panels.fx_panel          import FXPanel

        tabs.addTab(YieldCurvePanel(), "Yield Curves")
        tabs.addTab(VolSurfacePanel(),  "Vol Surface")
        tabs.addTab(ImpliedVolPanel(),  "Implied Vol")
        tabs.addTab(FXPanel(),          "FX Forward & Options")

        lay.addWidget(tabs)
