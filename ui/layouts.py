"""Reusable workstation layout primitives."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from ui.components import ContextDrawer, WorkspaceHeader
from ui.theme import PALETTE


class WorkstationWorkspace(QWidget):
    """Standard dense workspace layout with optional KPI strip and context drawer."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        chips: list[QWidget] | None = None,
        actions: list[QWidget] | None = None,
        kpi_strip: QWidget | None = None,
        left: QWidget | None = None,
        center: QWidget | None = None,
        right: QWidget | None = None,
        bottom: QWidget | None = None,
        context_items: list[tuple[str, str]] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet(f"background:{PALETTE.bg_workspace};")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # The shell toolbar owns the page title; the workspace only shows a slim
        # right-aligned chips/actions row when it has any (no duplicate title).
        if chips or actions:
            root.addWidget(WorkspaceHeader("", "", chips=chips, actions=actions))
        if kpi_strip is not None:
            root.addWidget(kpi_strip)

        main = QSplitter(Qt.Horizontal)
        main.setHandleWidth(1)
        main.setStyleSheet(f"QSplitter::handle{{background:{PALETTE.divider};}}")
        if left is not None:
            left.setMinimumWidth(260)
            left.setMaximumWidth(340)
            main.addWidget(left)
        if center is not None:
            main.addWidget(center)
        if right is not None:
            right.setMinimumWidth(260)
            right.setMaximumWidth(360)
            main.addWidget(right)
        # Context drawer is optional: only shown when context items are supplied.
        if context_items:
            context = ContextDrawer()
            context.set_items(context_items)
            main.addWidget(context)
            self.context = context
        else:
            self.context = None

        root.addWidget(main, 1)
        if bottom is not None:
            bottom.setMinimumHeight(132)
            root.addWidget(bottom)


def horizontal_split(*widgets: QWidget) -> QSplitter:
    splitter = QSplitter(Qt.Horizontal)
    splitter.setHandleWidth(1)
    splitter.setStyleSheet(f"QSplitter::handle{{background:{PALETTE.divider};}}")
    for widget in widgets:
        splitter.addWidget(widget)
    return splitter


def vertical_stack(*widgets: QWidget, margins: tuple[int, int, int, int] = (0, 0, 0, 0), spacing: int = 8) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def horizontal_stack(
    *widgets: QWidget,
    margins: tuple[int, int, int, int] = (0, 0, 0, 0),
    spacing: int = 8,
) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return container
