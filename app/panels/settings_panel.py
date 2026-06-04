"""Settings panel — theme, data sources, about."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QPushButton, QComboBox
)
from PySide6.QtCore import Qt

_BG1 = "#1a1a1e"
_BG2 = "#1e1e22"
_BOR = "#2e2e33"
_TXT0 = "#f0f0f2"
_TXT1 = "#a0a0a8"
_TXT2 = "#606068"
_ACC  = "#d97757"


class SettingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        body = QWidget()
        body.setStyleSheet(f"background:{_BG1};")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 28)
        lay.setSpacing(20)

        title = QLabel("Settings")
        title.setStyleSheet(
            f"color:{_TXT0};font-size:24px;font-weight:700;"
            f"letter-spacing:0;background:transparent;")
        lay.addWidget(title)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_BOR};max-height:1px;")
        lay.addWidget(sep)

        # Theme section
        self._add_section(lay, "APPEARANCE")
        theme_row = QHBoxLayout()
        theme_lbl = QLabel("Theme")
        theme_lbl.setStyleSheet(f"color:{_TXT1};font-size:13px;background:transparent;")
        theme_lbl.setFixedWidth(160)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["Dark (default)", "Light"])
        self._theme_combo.setFixedWidth(200)
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(self._theme_combo)
        theme_row.addStretch()
        lay.addLayout(theme_row)

        note = QLabel("Keyboard shortcut: Ctrl+T toggles dark/light theme")
        note.setStyleSheet(f"color:{_TXT2};font-size:11px;background:transparent;")
        lay.addWidget(note)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color:{_BOR};max-height:1px;")
        lay.addWidget(sep2)

        # Data sources section
        self._add_section(lay, "DATA SOURCES")
        for source, status, color in [
            ("Manual Input",  "Active",           "#30d158"),
            ("CSV / Excel",   "Not configured",   _TXT2),
            ("MOEX ISS Live", "Integration pending", _TXT2),
        ]:
            row = QHBoxLayout()
            src_lbl = QLabel(source)
            src_lbl.setStyleSheet(f"color:{_TXT1};font-size:13px;background:transparent;")
            src_lbl.setFixedWidth(160)
            st_lbl = QLabel(status)
            st_lbl.setStyleSheet(f"color:{color};font-size:12px;background:transparent;")
            row.addWidget(src_lbl); row.addWidget(st_lbl); row.addStretch()
            lay.addLayout(row)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.HLine)
        sep3.setStyleSheet(f"color:{_BOR};max-height:1px;")
        lay.addWidget(sep3)

        # About section
        self._add_section(lay, "ABOUT")
        for line in [
            "RiskCalc  ·  Market Risk & Pricing Engine",
            "Version: 1.0  ·  Status: Development / Portfolio prototype",
            "Models are classified as Validated / Approximation / Prototype.",
            "Do not use Prototype or Placeholder models for production trading decisions.",
            "",
            "All market data is currently manual/demo unless explicitly loaded from CSV or live source.",
        ]:
            lbl = QLabel(line)
            lbl.setStyleSheet(
                f"color:{_TXT2 if not line.startswith('RiskCalc') else _TXT1};"
                f"font-size:12px;background:transparent;")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)

        lay.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll)

    def _add_section(self, lay, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{_TXT2};font-size:10px;font-weight:700;"
            f"letter-spacing:1px;background:transparent;")
        lay.addWidget(lbl)
