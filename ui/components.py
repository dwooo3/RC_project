"""Shared UI components for future replatforming."""

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import PALETTE, status_style, value_color


class ModelStatus(Enum):
    VALIDATED = "Validated"
    APPROXIMATION = "Approximation"
    PROTOTYPE = "Prototype"
    PLACEHOLDER = "Placeholder"
    BROKEN = "Broken"


class WorkspacePage(QWidget):
    """Base page container for workspace screens."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workspace_page")


class WorkspaceCard(QFrame):
    """Shared elevated card surface."""

    def __init__(self, parent=None, *, object_name: str = "workspace_card", fixed_height: int | None = None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFrameShape(QFrame.StyledPanel)
        if fixed_height is not None:
            self.setFixedHeight(fixed_height)


class KpiCard(WorkspaceCard):
    """Single KPI tile with stable dimensions."""

    def __init__(
        self,
        label: str,
        value: str = "—",
        sub: str = "",
        color: str = "",
        highlight: bool = False,
        parent=None,
    ):
        super().__init__(
            parent,
            object_name="metric_card_highlight" if highlight else "metric_card",
        )
        self.setMinimumHeight(88)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(3)

        self._name_lbl = QLabel(label.upper())
        self._name_lbl.setObjectName("metric_name")

        self._val_lbl = QLabel(str(value))
        self._val_lbl.setObjectName("metric_value")
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        self._val_lbl.setFont(font)

        self._sub_lbl = QLabel(sub)
        self._sub_lbl.setObjectName("metric_sub")

        lay.addWidget(self._name_lbl)
        lay.addWidget(self._val_lbl)
        lay.addWidget(self._sub_lbl)
        self.set_value(value, color=color, sub=sub)

    def set_value(self, value, color: str = "", sub: str = ""):
        self._val_lbl.setText(self._format_value(value))
        self._sub_lbl.setText(sub)
        resolved_color = color or value_color(value)
        self._val_lbl.setStyleSheet(
            f"color:{resolved_color};font-size:17px;font-weight:700;"
            "letter-spacing:-0.4px;background:transparent;"
        )

    def clear(self):
        self._val_lbl.setText("—")
        self._val_lbl.setStyleSheet(
            f"color:{PALETTE.bg4};font-size:17px;font-weight:700;background:transparent;"
        )
        self._sub_lbl.setText("")

    def _format_value(self, value) -> str:
        if isinstance(value, float):
            av = abs(value)
            if av == 0:
                return "0"
            if av >= 1_000_000:
                return f"{value:,.0f}"
            if av >= 1000:
                return f"{value:,.2f}"
            if av >= 10:
                return f"{value:.4f}"
            if av >= 0.001:
                return f"{value:.6f}"
            return f"{value:.4e}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)


class StatusChip(QLabel):
    """Small chip showing validation/status state."""

    def __init__(self, status: ModelStatus | str, parent=None, *, prefix: str = "", text: str | None = None):
        super().__init__(parent)
        status_value = status.value if hasattr(status, "value") else str(status)
        style, default_text = status_style(status_value)
        self.setText(text or f"{prefix}{default_text}")
        self.setStyleSheet(
            f"{style} border-radius:4px; padding:2px 8px; "
            "font-size:10px; font-weight:600; letter-spacing:0.3px;"
        )
        self.setToolTip(f"Status: {status_value}")


class WarningBanner(QLabel):
    """Inline warning/success banner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setContentsMargins(14, 0, 14, 0)
        self.hide()

    def show_error(self, msg: str):
        self.setObjectName("banner_error")
        self.setStyleSheet(
            f"background:{PALETTE.status_broken_bg};border:1px solid {PALETTE.status_broken_border};"
            f"border-radius:6px;color:{PALETTE.red_text};padding:7px 14px;"
            "font-size:11px;margin:4px 14px;"
        )
        self.setText(f"⚠  {msg}")
        self.show()

    def show_ok(self, msg: str):
        self.setObjectName("banner_ok")
        self.setStyleSheet(
            f"background:{PALETTE.status_valid_bg};border:1px solid {PALETTE.status_valid_border};"
            f"border-radius:6px;color:{PALETTE.green};padding:7px 14px;"
            "font-size:11px;margin:4px 14px;"
        )
        self.setText(f"✓  {msg}")
        self.show()

    def clear(self):
        self.hide()
        self.setText("")


class QuickNavCard(WorkspaceCard):
    """Shared quick navigation card used by workspace/dashboard screens."""

    def __init__(self, name: str, hint: str, on_click=None, parent=None):
        super().__init__(parent, object_name="nav_quick", fixed_height=58)
        self.setStyleSheet(
            f"QFrame#nav_quick{{background:{PALETTE.bg2_alt};border:1px solid {PALETTE.bg3};"
            "border-radius:8px;}}"
            f"QFrame#nav_quick:hover{{background:{PALETTE.bg2};border-color:{PALETTE.bg5};}}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(1)

        title = QLabel(name)
        title.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:12px;font-weight:600;background:transparent;"
        )
        subtitle = QLabel(hint)
        subtitle.setStyleSheet(f"color:{PALETTE.txt2};font-size:10px;background:transparent;")
        lay.addWidget(title)
        lay.addWidget(subtitle)

    def mousePressEvent(self, event):
        if self._on_click:
            self._on_click()
        super().mousePressEvent(event)


def add_horizontal_separator(layout: QVBoxLayout | QHBoxLayout):
    separator = QFrame()
    separator.setFrameShape(QFrame.HLine)
    separator.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    separator.setStyleSheet(f"color:{PALETTE.bg3};max-height:1px;")
    layout.addWidget(separator)
    return separator
