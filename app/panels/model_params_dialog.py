"""
Model & parameters dialog — a pop-up to inspect and edit the pricing model.

For any instrument the dialog shows: the selectable model(s), the model's
governance card (name, validation status, asset-class / family / method, notes),
and editable model + numerical parameters (from models.parameters.engine_params).
A pure-analytic model simply shows its card with no editable knobs.

Used from the pricing detail screen ("Model & parameters…" button) so the model
behind every priced instrument is always visible and, where it has parameters,
adjustable.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
    QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from ui.theme import PALETTE


def model_metadata(engine: str) -> dict:
    """Governance + taxonomy metadata for a model id (best-effort)."""
    from models import registry as R
    from models import taxonomy as tax
    reg = R.get(engine)
    cls = tax.classify(engine)
    status = reg.get("status")
    return {
        "name": reg.get("name", engine),
        "status": status.value if hasattr(status, "value") else (status or "—"),
        "asset_class": cls.get("asset_class") or "—",
        "family": cls.get("model_family") or "—",
        "method": cls.get("method") or "—",
        "notes": reg.get("notes", ""),
    }


class ModelParamsDialog(QDialog):
    """Select a model and edit its parameters for one instrument."""

    def __init__(self, engines: list[str], current_engine: str | None = None,
                 current_values: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Model & parameters")
        self.setMinimumWidth(460)
        self._engines = engines or []
        self._values = dict(current_values or {})
        self._inputs: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        self._combo = None
        if len(self._engines) > 1:
            self._combo = QComboBox()
            self._combo.addItems(self._engines)
            if current_engine in self._engines:
                self._combo.setCurrentText(current_engine)
            form = QFormLayout()
            form.addRow(self._lbl("Model"), self._combo)
            root.addLayout(form)
            self._combo.currentIndexChanged.connect(lambda _i: self._rebuild())
        self._current = current_engine or (self._engines[0] if self._engines else None)

        self._meta_card = QFrame()
        self._meta_card.setStyleSheet(
            f"background:{PALETTE.bg2};border:1px solid {PALETTE.divider};border-radius:8px;")
        self._meta_layout = QVBoxLayout(self._meta_card)
        self._meta_layout.setContentsMargins(12, 10, 12, 10)
        self._meta_layout.setSpacing(4)
        root.addWidget(self._meta_card)

        self._param_host = QWidget()
        self._param_grid = QGridLayout(self._param_host)
        self._param_grid.setContentsMargins(0, 0, 0, 0)
        self._param_grid.setHorizontalSpacing(12)
        self._param_grid.setVerticalSpacing(8)
        root.addWidget(self._param_host)
        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._rebuild()

    def _lbl(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(f"color:{PALETTE.txt2};font-size:11px;background:transparent;")
        return lab

    def selected_engine(self) -> str | None:
        return self._combo.currentText() if self._combo else self._current

    def _rebuild(self):
        from models.parameters import engine_params
        engine = self.selected_engine()
        # metadata card
        while self._meta_layout.count():
            w = self._meta_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        m = model_metadata(engine) if engine else {}
        title = QLabel(f"<b>{m.get('name', engine)}</b>")
        title.setStyleSheet(f"color:{PALETTE.txt0};font-size:13px;background:transparent;")
        title.setWordWrap(True)
        self._meta_layout.addWidget(title)
        sub = QLabel(f"status: {m.get('status','—')}  ·  {m.get('asset_class','—')} / "
                     f"{m.get('family','—')} / {m.get('method','—')}")
        sub.setStyleSheet(f"color:{PALETTE.txt2};font-size:11px;background:transparent;")
        self._meta_layout.addWidget(sub)
        if m.get("notes"):
            notes = QLabel(m["notes"])
            notes.setWordWrap(True)
            notes.setStyleSheet(f"color:{PALETTE.txt2};font-size:10px;background:transparent;")
            self._meta_layout.addWidget(notes)

        # param editors
        while self._param_grid.count():
            w = self._param_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._inputs = {}
        specs = engine_params(engine) if engine else []
        if not specs:
            hint = QLabel("No adjustable model parameters (analytic / closed form).")
            hint.setStyleSheet(f"color:{PALETTE.txt2};font-size:11px;background:transparent;")
            self._param_grid.addWidget(hint, 0, 0, 1, 2)
            return
        for row, spec in enumerate(specs):
            cur = self._values.get(spec.key, spec.default)
            if spec.choices:
                w = QComboBox()
                w.addItems([str(c) for c in spec.choices])
                w.setCurrentText(str(cur))
            else:
                w = QLineEdit(str(cur))
            self._inputs[spec.key] = (w, spec)
            cell = QWidget()
            col = QVBoxLayout(cell)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(3)
            col.addWidget(self._lbl(f"{spec.label}  ·{spec.group}"))
            col.addWidget(w)
            self._param_grid.addWidget(cell, row // 2, row % 2)

    def result_values(self) -> dict:
        """{'__engine': engine, **edited params} — merge into the pricing values."""
        out = {"__engine": self.selected_engine()}
        for key, (w, spec) in self._inputs.items():
            if isinstance(w, QComboBox):
                out[key] = w.currentText()
            else:
                text = w.text().strip()
                if spec.dtype == "int":
                    try:
                        out[key] = int(float(text))
                    except ValueError:
                        out[key] = spec.default
                elif spec.dtype == "choice":
                    out[key] = text
                else:
                    try:
                        out[key] = float(text)
                    except ValueError:
                        out[key] = spec.default
        return out
