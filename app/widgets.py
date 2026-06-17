"""Refined UI widgets.

Compatibility module for existing panels. Shared component ownership lives in
`ui.components`; this module keeps historical imports stable.
"""

from PySide6.QtWidgets import (  # noqa: F401  (legacy compat shim — keep the Qt surface)
    QWidget, QLabel, QDoubleSpinBox, QSpinBox, QComboBox,
    QFrame, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton,
    QGroupBox, QLineEdit
)
from PySide6.QtCore import Qt, QLocale
from ui.components import KpiCard as MetricCard  # noqa: F401  (backward-compat re-export)
from ui.components import ModelStatus, StatusChip as ModelStatusBadge  # noqa: F401
from ui.components import WarningBanner as Banner  # noqa: F401


# ── Force period decimal separator system-wide ───────────
_DOT_LOCALE = QLocale(QLocale.C)
_DOT_LOCALE.setNumberOptions(QLocale.RejectGroupSeparator)


def make_spin(lo=0.0, hi=1e9, val=100.0, step=1.0, dec=4, suffix="") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setLocale(_DOT_LOCALE)
    s.setRange(lo, hi)
    s.setValue(val)
    s.setSingleStep(step)
    s.setDecimals(dec)
    s.setButtonSymbols(QDoubleSpinBox.NoButtons)
    if suffix:
        s.setSuffix(f" {suffix.strip()}")
    return s


def make_pct(val=0.20, lo=-1.0, hi=10.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setLocale(_DOT_LOCALE)
    s.setRange(lo * 100, hi * 100)
    s.setValue(val * 100)
    s.setSingleStep(0.25)
    s.setDecimals(2)
    s.setSuffix(" %")
    s.setButtonSymbols(QDoubleSpinBox.NoButtons)
    return s


def make_combo(items: list, default: str = "") -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    if default and default in items:
        c.setCurrentText(default)
    return c


# ── Labelled field row ────────────────────────────────────

class FieldRow(QWidget):
    def __init__(self, label: str, widget: QWidget,
                 tooltip: str = "", parent=None):
        super().__init__(parent)
        lbl = QLabel(label)
        lbl.setObjectName("field_label")
        lbl.setFixedWidth(134)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if tooltip:
            lbl.setToolTip(tooltip)
            widget.setToolTip(tooltip)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(10)
        row.addWidget(lbl)
        row.addWidget(widget, 1)


# ── Results grid ──────────────────────────────────────────

class ResultsGrid(QWidget):
    def __init__(self, metrics: list, cols: int = 3,
                 highlight: str = "", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QGridLayout
        self._cards = {}
        grid = QGridLayout(self)
        grid.setSpacing(6)
        grid.setContentsMargins(14, 10, 14, 10)
        for i, name in enumerate(metrics):
            hl = (name.lower() == highlight.lower())
            card = MetricCard(name, highlight=hl)
            self._cards[name] = card
            grid.addWidget(card, i // cols, i % cols)

    def set(self, name: str, value, sub: str = "", color: str = ""):
        if name in self._cards:
            self._cards[name].set_value(value, sub, color)

    def update_dict(self, values: dict):
        for k, v in values.items():
            self.set(k, v)

    def clear_all(self):
        for card in self._cards.values():
            card.clear()


# ── Section header ────────────────────────────────────────

class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "",
                 status: "ModelStatus | None" = None, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 0)
        lay.setSpacing(3)

        # Title row with optional status badge
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("panel_title")
        title_row.addWidget(t)
        if status is not None:
            badge = ModelStatusBadge(status)
            title_row.addWidget(badge)
        title_row.addStretch()
        lay.addLayout(title_row)

        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("panel_subtitle")
            s.setWordWrap(True)
            lay.addWidget(s)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #2e2e33; margin-top: 8px;")
        lay.addWidget(line)


# ── Scrollable parameter form ─────────────────────────────

class ParamForm(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._inner = QWidget()
        self._lay = QVBoxLayout(self._inner)
        self._lay.setContentsMargins(14, 8, 14, 16)
        self._lay.setSpacing(4)
        self._lay.addStretch()

        scroll.setWidget(self._inner)
        outer.addWidget(scroll)

    def add(self, widget: QWidget):
        self._lay.insertWidget(self._lay.count() - 1, widget)

    def add_group(self, title: str, widgets: list) -> QGroupBox:
        grp = QGroupBox(title)
        lay = QVBoxLayout(grp)
        lay.setSpacing(5)
        lay.setContentsMargins(12, 14, 12, 10)
        for w in widgets:
            lay.addWidget(w)
        self.add(grp)
        return grp
