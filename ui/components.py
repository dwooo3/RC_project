"""Shared UI components for future replatforming."""

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.theme import PALETTE, status_style, value_color


def mark_invalid(widget: QWidget, invalid: bool = True):
    """Toggle the red invalid-field border (driven by the [invalid] QSS selector)."""
    widget.setProperty("invalid", "true" if invalid else "false")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def card_shadow(widget: QWidget, *, blur: int = 18, dy: int = 8, color: str | None = None,
                alpha: int | None = None) -> QGraphicsDropShadowEffect:
    """Apply the standard soft card elevation shadow to ``widget``.

    Qt stylesheets cannot express shadows, so cards use a graphics effect. A
    widget may hold only one graphics effect; calling this replaces any prior.
    """
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(dy)
    c = QColor(color or PALETTE.shadow_color)
    c.setAlpha(PALETTE.shadow_alpha if alpha is None else alpha)
    effect.setColor(c)
    widget.setGraphicsEffect(effect)
    return effect


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
        self.setStyleSheet(f"background:{PALETTE.bg_workspace};")


class WorkspaceCard(QFrame):
    """Shared elevated card surface (white, rounded, hairline border)."""

    def __init__(
        self,
        parent=None,
        *,
        object_name: str = "workspace_card",
        fixed_height: int | None = None,
        radius: int = 14,
        elevated: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFrameShape(QFrame.StyledPanel)
        if fixed_height is not None:
            self.setFixedHeight(fixed_height)
        if object_name == "metric_card_highlight":
            bg, border = PALETTE.accent_soft, PALETTE.accent_lo
        else:
            bg, border = PALETTE.bg_card, PALETTE.card_border
        self.setStyleSheet(
            f"QFrame#{object_name}{{background:{bg};"
            f"border:1px solid {border};border-radius:{radius}px;}}"
        )
        if elevated:
            card_shadow(self)


class WorkstationPanel(WorkspaceCard):
    """Dense bordered panel used in workstation multi-panel layouts."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent, object_name="workstation_panel")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(9, 7, 9, 8)
        self.layout.setSpacing(6)
        if title:
            label = SectionLabel(title)
            self.layout.addWidget(label)


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
        self.setMinimumHeight(64)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(1)

        self._name_lbl = QLabel(label.upper())
        self._name_lbl.setObjectName("metric_name")

        self._val_lbl = QLabel(str(value))
        self._val_lbl.setObjectName("metric_value")
        font = QFont()
        font.setPointSize(15)
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
            f"color:{resolved_color};font-size:15px;font-weight:700;"
            "letter-spacing:0;background:transparent;"
        )

    def clear(self):
        self._val_lbl.setText("—")
        self._val_lbl.setStyleSheet(
            f"color:{PALETTE.bg4};font-size:15px;font-weight:700;background:transparent;"
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
        self.setStyleSheet(f"{style} border-radius:3px; padding:1px 6px; "
                           "font-size:9px; font-weight:700; letter-spacing:0.2px;")
        self.setToolTip(f"Status: {status_value}")


class DataSourceChip(QLabel):
    """Small chip for market data source ownership."""

    _COLORS = {
        "DEMO": (PALETTE.bg_warning, PALETTE.amber),
        "MANUAL": (PALETTE.bg_panel_elevated, PALETTE.blue),
        "CSV": (PALETTE.bg_panel_elevated, PALETTE.cyan),
        "MOEX": (PALETTE.bg_success, PALETTE.green),
        "BLOOMBERG": (PALETTE.bg_success, PALETTE.green),
        "REUTERS": (PALETTE.bg_success, PALETTE.green),
    }

    def __init__(self, source: str, parent=None):
        super().__init__(parent)
        key = str(source).upper()
        bg, fg = self._COLORS.get(key, (PALETTE.bg_panel_elevated, PALETTE.txt1))
        self.setText(key)
        self.setStyleSheet(
            f"background:{bg};color:{fg};border:1px solid {PALETTE.border_soft};"
            "border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700;"
        )


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
            f"border-radius:4px;color:{PALETTE.red_text};padding:6px 10px;"
            "font-size:11px;margin:2px 0;"
        )
        self.setText(f"WARN | {msg}")
        self.show()

    def show_ok(self, msg: str):
        self.setObjectName("banner_ok")
        self.setStyleSheet(
            f"background:{PALETTE.status_valid_bg};border:1px solid {PALETTE.status_valid_border};"
            f"border-radius:4px;color:{PALETTE.green};padding:6px 10px;"
            "font-size:11px;margin:2px 0;"
        )
        self.setText(f"OK | {msg}")
        self.show()

    def clear(self):
        self.hide()
        self.setText("")


class SectionLabel(QLabel):
    """Uppercase compact section title."""

    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(
            f"color:{PALETTE.txt2};font-size:9px;font-weight:700;"
            "letter-spacing:0.6px;background:transparent;"
        )


class SegmentedControl(QWidget):
    """Rounded segmented control (macOS-style) with an accent-filled active pill."""

    def __init__(self, items: list[str], parent=None, *, on_change=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self._on_change = on_change
        self._buttons: list[QPushButton] = []
        self.setStyleSheet(
            f"QWidget#segmented{{background:{PALETTE.bg_field};"
            f"border:1px solid {PALETTE.card_border};border-radius:16px;}}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, label in enumerate(items):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("seg_btn")
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                f"""
                QPushButton#seg_btn {{
                    background: transparent; border: none; border-radius: 13px;
                    color: {PALETTE.txt2}; padding: 4px 14px;
                    font-size: 12px; font-weight: 600;
                }}
                QPushButton#seg_btn:hover:!checked {{ color: {PALETTE.txt0}; }}
                QPushButton#seg_btn:checked {{
                    background: {PALETTE.accent}; color: {PALETTE.accent_on};
                }}
                """
            )
            self._group.addButton(button, index)
            row.addWidget(button)
            self._buttons.append(button)

        if self._buttons:
            self._buttons[0].setChecked(True)
        self._group.idClicked.connect(self._emit)

    def _emit(self, index: int):
        if self._on_change is not None:
            self._on_change(index)

    def current_index(self) -> int:
        return self._group.checkedId()

    def set_current_index(self, index: int):
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)


def fit_table_height(table: QTableWidget, *, max_rows: int | None = None):
    """Lock a table to the height of its rows so it renders as a static block
    inside an outer scroll area (no inner scrollbar)."""
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    rows = table.rowCount() if max_rows is None else min(table.rowCount(), max_rows)
    row_h = table.verticalHeader().defaultSectionSize()
    header_h = table.horizontalHeader().height() or 22
    table.setFixedHeight(header_h + rows * row_h + 4)


class KeyValueGrid(QWidget):
    """Compact two-column key→value metric grid (column-major fill)."""

    def __init__(self, parent=None, *, columns: int = 2):
        super().__init__(parent)
        self._columns = columns
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(28)
        self._grid.setVerticalSpacing(8)

    def set_pairs(self, pairs: list[tuple[str, str]]):
        import math
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not pairs:
            return
        rows = max(1, math.ceil(len(pairs) / self._columns))
        for i, (label, value) in enumerate(pairs):
            col, row = divmod(i, rows)
            lbl = QLabel(str(label))
            lbl.setStyleSheet(f"color:{PALETTE.txt2};font-size:13px;background:transparent;")
            val = QLabel(str(value))
            val.setStyleSheet(
                f"color:{PALETTE.txt0};font-size:13px;font-weight:600;background:transparent;")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._grid.addWidget(lbl, row, col * 2)
            self._grid.addWidget(val, row, col * 2 + 1)
        for c in range(self._columns):
            self._grid.setColumnStretch(c * 2 + 1, 1)


class ScrollableCard(QFrame):
    """Rounded card with a scrollable body and an optional pinned footer.

    The body scrolls; ``set_footer`` pins a footer below it (outside the scroll)
    whose bottom corners are rounded to match the card.
    """

    def __init__(self, parent=None, *, radius: int = 16, elevated: bool = True):
        super().__init__(parent)
        self._radius = radius
        self.setObjectName("scroll_card")
        self.setStyleSheet(
            f"QFrame#scroll_card{{background:{PALETTE.bg_card};"
            f"border:1px solid {PALETTE.card_border};border-radius:{radius}px;}}")
        if elevated:
            card_shadow(self)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._scroll.viewport().setStyleSheet("background:transparent;")

        self._body = QWidget()
        self._body.setStyleSheet("background:transparent;")
        self.body_layout = QVBoxLayout(self._body)
        self.body_layout.setContentsMargins(20, 18, 20, 16)
        self.body_layout.setSpacing(8)
        self._scroll.setWidget(self._body)
        self._outer.addWidget(self._scroll, 1)

    def set_footer(self, widget: QWidget):
        widget.setObjectName("card_footer")
        widget.setStyleSheet(
            f"QWidget#card_footer{{background:{PALETTE.bg_footer};"
            f"border-top:1px solid {PALETTE.card_border};"
            f"border-bottom-left-radius:{self._radius}px;"
            f"border-bottom-right-radius:{self._radius}px;}}")
        self._outer.addWidget(widget)


class WorkspaceHeader(QWidget):
    """Standard workspace title, scope chips, and action row."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        chips: list[QWidget] | None = None,
        actions: list[QPushButton] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:18px;font-weight:700;background:transparent;"
        )
        title_col.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet(
                f"color:{PALETTE.txt2};font-size:11px;background:transparent;"
            )
            title_col.addWidget(subtitle_label)
        row.addLayout(title_col, 1)

        for chip in chips or []:
            row.addWidget(chip, alignment=Qt.AlignVCenter)
        for action in actions or []:
            row.addWidget(action, alignment=Qt.AlignVCenter)


class CommandBar(QWidget):
    """Global workstation command/context bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setStyleSheet(
            f"background:{PALETTE.bg_topbar};border-bottom:1px solid {PALETTE.border_soft};"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)

        title = QLabel("RiskCalc")
        title.setStyleSheet(f"color:{PALETTE.txt0};font-size:14px;font-weight:700;")
        row.addWidget(title)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Ctrl+K Search command or screen...")
        self.search.setFixedWidth(260)
        row.addWidget(self.search)

        self.portfolio = QComboBox()
        self.portfolio.addItems(["Main Portfolio"])
        row.addWidget(self.portfolio)

        self.book = QComboBox()
        self.book.addItems(["Trading", "All Books"])
        row.addWidget(self.book)

        for text in ["Date: 2026-06-04", "Snapshot: DEMO:v3", "Mode: Demo", "Warnings: 4"]:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color:{PALETTE.txt1};font-size:11px;background:transparent;")
            row.addWidget(lbl)

        row.addStretch()
        for label, primary in [("Run", True), ("Save", False), ("Export", False)]:
            button = QPushButton(label)
            if primary:
                button.setObjectName("primary_action")
            row.addWidget(button)


class ContextDrawer(WorkspaceCard):
    """Right-side selected object and provenance drawer."""

    def __init__(self, title: str = "Context", parent=None):
        super().__init__(parent, object_name="context_drawer")
        self.setFixedWidth(320)
        self.setStyleSheet(
            f"QFrame#context_drawer{{background:{PALETTE.bg_panel};"
            f"border-left:1px solid {PALETTE.border_soft};border-radius:0;}}"
        )
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 8, 10, 10)
        self.layout.setSpacing(6)
        self.title = SectionLabel(title)
        self.layout.addWidget(self.title)

    def set_items(self, items: list[tuple[str, str]]):
        while self.layout.count() > 1:
            item = self.layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for label, value in items:
            row = QHBoxLayout()
            row.setSpacing(6)
            l = QLabel(label)
            l.setStyleSheet(f"color:{PALETTE.txt2};font-size:10px;background:transparent;")
            v = QLabel(value)
            v.setStyleSheet(f"color:{PALETTE.txt0};font-size:11px;background:transparent;")
            v.setWordWrap(True)
            row.addWidget(l)
            row.addStretch()
            row.addWidget(v)
            self.layout.addLayout(row)
        self.layout.addStretch()


class KpiStrip(QWidget):
    """One-row compact KPI strip."""

    def __init__(self, metrics: list[tuple[str, str, str]], parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self.cards: dict[str, KpiCard] = {}
        for idx, metric in enumerate(metrics):
            label, value, sub = metric
            card = KpiCard(label, value, sub)
            card.setMinimumHeight(58)
            self.cards[label] = card
            grid.addWidget(card, 0, idx)


class DenseTable(QTableWidget):
    """Dense sortable table with workstation defaults."""

    def __init__(self, headers: list[str], rows: list[list] | None = None, parent=None):
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(24)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        if rows:
            self.set_rows(rows)

    def set_rows(self, rows: list[list]):
        self.setSortingEnabled(False)
        self.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            for col_idx, value in enumerate(row):
                item = QTableWidgetItem(self._format(value))
                if isinstance(value, (int, float)):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.setItem(row_idx, col_idx, item)
        self.setSortingEnabled(True)

    def _format(self, value) -> str:
        if isinstance(value, float):
            return f"{value:,.4f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)


def make_action(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    if primary:
        button.setObjectName("primary_action")
    return button


class QuickNavCard(WorkspaceCard):
    """Shared quick navigation card used by workspace/dashboard screens."""

    def __init__(self, name: str, hint: str, on_click=None, parent=None):
        super().__init__(parent, object_name="nav_quick", fixed_height=58)
        self.setStyleSheet(
            f"QFrame#nav_quick{{background:{PALETTE.bg2_alt};border:1px solid {PALETTE.border_soft};"
            "border-radius:4px;}}"
            f"QFrame#nav_quick:hover{{background:{PALETTE.bg2};border-color:{PALETTE.border_strong};}}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
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
