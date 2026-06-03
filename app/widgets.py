"""Refined UI widgets."""

from enum import Enum
from PySide6.QtWidgets import (
    QWidget, QLabel, QDoubleSpinBox, QSpinBox, QComboBox,
    QFrame, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton,
    QGroupBox, QLineEdit, QSizePolicy, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QLocale
from PySide6.QtGui import QFont, QColor


# ── Model status taxonomy ────────────────────────────────

class ModelStatus(Enum):
    VALIDATED    = "Validated"
    APPROXIMATION = "Approximation"
    PROTOTYPE    = "Prototype"
    PLACEHOLDER  = "Placeholder"
    BROKEN       = "Broken"

_STATUS_STYLES = {
    ModelStatus.VALIDATED:     ("background:#182a1c;color:#30d158;border:1px solid #246030;",     "✓ Validated"),
    ModelStatus.APPROXIMATION: ("background:#2a2518;color:#ffd60a;border:1px solid #604820;",     "~ Approximation"),
    ModelStatus.PROTOTYPE:     ("background:#242430;color:#a0a0f0;border:1px solid #404060;",     "⚗ Prototype"),
    ModelStatus.PLACEHOLDER:   ("background:#2a2020;color:#d97757;border:1px solid #6a3020;",     "◌ Placeholder"),
    ModelStatus.BROKEN:        ("background:#2a1a18;color:#ff453a;border:1px solid #6a2820;",     "✕ Broken"),
}


class ModelStatusBadge(QLabel):
    """Small badge showing model validation status."""
    def __init__(self, status: ModelStatus, parent=None):
        super().__init__(parent)
        style, text = _STATUS_STYLES.get(status, ("", str(status.value)))
        self.setText(text)
        self.setStyleSheet(
            f"{style} border-radius:4px; padding:2px 8px; "
            f"font-size:10px; font-weight:600; letter-spacing:0.3px;"
        )
        self.setToolTip(f"Model status: {status.value}")


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


# ── Metric card ───────────────────────────────────────────

class MetricCard(QFrame):
    def __init__(self, name: str, highlight: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("metric_card_highlight" if highlight else "metric_card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(72)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(1)

        self._name_lbl = QLabel(name.upper())
        self._name_lbl.setObjectName("metric_name")

        self._val_lbl = QLabel("—")
        self._val_lbl.setObjectName("metric_value")
        f = QFont()
        f.setPointSize(18); f.setBold(True)
        self._val_lbl.setFont(f)

        self._sub_lbl = QLabel("")
        self._sub_lbl.setObjectName("metric_sub")

        lay.addWidget(self._name_lbl)
        lay.addWidget(self._val_lbl)
        lay.addWidget(self._sub_lbl)

    def set_value(self, v, sub: str = "", color: str = ""):
        if isinstance(v, float):
            av = abs(v)
            if av == 0:           text = "0"
            elif av >= 1_000_000: text = f"{v:,.0f}"
            elif av >= 1000:      text = f"{v:,.2f}"
            elif av >= 10:        text = f"{v:.4f}"
            elif av >= 0.001:     text = f"{v:.6f}"
            else:                 text = f"{v:.4e}"
        elif isinstance(v, int):
            text = f"{v:,}"
        else:
            text = str(v)
        self._val_lbl.setText(text)
        self._sub_lbl.setText(sub)
        if color:
            c = color
        elif isinstance(v, (int, float)):
            c = "#30d158" if v > 0 else ("#ff453a" if v < 0 else "#f0f0f2")
        else:
            c = "#f0f0f2"
        self._val_lbl.setStyleSheet(
            f"color:{c}; font-size:17px; font-weight:700; letter-spacing:-0.4px; background:transparent;")

    def clear(self):
        self._val_lbl.setText("—")
        self._val_lbl.setStyleSheet(
            "color:#38383d; font-size:17px; font-weight:700; background:transparent;")
        self._sub_lbl.setText("")


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


# ── Inline banner ─────────────────────────────────────────

class Banner(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setContentsMargins(14, 0, 14, 0)
        self.hide()

    def show_error(self, msg: str):
        self.setStyleSheet(
            "background:#2a1a18;border:1px solid #6a2820;border-radius:6px;"
            "color:#ff6b5a;padding:7px 14px;font-size:11px;margin:4px 14px;")
        self.setText(f"⚠  {msg}")
        self.show()

    def show_ok(self, msg: str):
        self.setStyleSheet(
            "background:#182a1c;border:1px solid #246030;border-radius:6px;"
            "color:#30d158;padding:7px 14px;font-size:11px;margin:4px 14px;")
        self.setText(f"✓  {msg}")
        self.show()

    def clear(self):
        self.hide()
        self.setText("")
