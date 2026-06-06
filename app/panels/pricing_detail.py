"""Interactive pricing detail screen — inputs -> PricingService -> governed result."""
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from app.panels.pricing_catalogue import Product
from app.panels.session import shared_portfolio
from domain.portfolio import Position
from ui.components import DataSourceChip, DenseTable, SectionLabel, StatusChip, WorkstationPanel
from ui.theme import PALETTE

_GREEK_KEYS = [
    ("delta", "Delta"), ("gamma", "Gamma"), ("vega", "Vega"), ("theta", "Theta"),
    ("rho", "Rho"), ("dv01", "DV01"), ("pv01", "PV01"), ("cs01", "CS01"),
    ("mac_duration", "Mac Duration"), ("mod_duration", "Mod Duration"),
    ("effective_duration", "Eff Duration"), ("convexity", "Convexity"),
    ("ytm", "YTM"), ("ytc", "YTC"), ("ytp", "YTP"), ("ytw", "YTW"),
    ("clean_price", "Clean"), ("dirty_price", "Dirty"), ("accrued_interest", "Accrued"),
    ("z_spread", "Z-Spread"), ("zspread", "Z-Spread"), ("g_spread", "G-Spread"),
    ("i_spread", "I-Spread"), ("discount_margin", "Disc Margin"), ("spread_dv01", "Spread DV01"),
    ("discount_yield", "Disc Yield"), ("money_market_yield", "MM Yield"), ("bey", "BEY"),
    ("maturity_value", "Maturity Val"), ("real_yield", "Real Yield"),
    ("indexed_principal", "Indexed Prin"), ("inflation_dv01", "Infl DV01"),
    ("forward_price", "Forward"), ("carry", "Carry"), ("funding_dv01", "Funding DV01"),
    ("financing_cost", "Financing"), ("repo_rate", "Repo Rate"),
    ("theoretical_futures", "Theo Futures"), ("invoice_price", "Invoice"),
    ("net_basis", "Net Basis"), ("gross_basis", "Gross Basis"),
    ("implied_repo", "Implied Repo"), ("futures_dv01", "Futures DV01"),
    ("hedge_ratio", "Hedge Ratio"), ("conversion_factor", "Conv Factor"),
    ("implied_rate", "Implied Rate"),
    ("oas", "OAS"), ("straight_value", "Straight"), ("option_value", "Option Value"),
    ("fair_spread", "Fair spread"), ("npv", "NPV"), ("delta_S", "Delta"), ("annuity", "Annuity"),
]


class PricingDetailScreen(QWidget):
    def __init__(self, product: Product, pricing_service, parent=None):
        super().__init__(parent)
        self.product = product
        self.pricing = pricing_service
        self._inputs: dict[str, QWidget] = {}
        self._last_result: dict | None = None
        self._build()

    # -- UI --------------------------------------------------------------
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # input panel
        form_panel = WorkstationPanel(f"{self.product.label} — Inputs")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(5)
        for f in self.product.fields:
            if f.choices is not None:
                w = QComboBox()
                w.addItems(f.choices)
                w.setCurrentText(str(f.default))
            else:
                w = QLineEdit(str(f.default))
            w.setStyleSheet(
                f"background:{PALETTE.bg_panel_elevated};color:{PALETTE.txt0};"
                f"border:1px solid {PALETTE.border_default};border-radius:3px;padding:3px 6px;")
            self._inputs[f.key] = w
            lab = QLabel(f.label)
            lab.setStyleSheet(f"color:{PALETTE.txt1};font-size:11px;")
            form.addRow(lab, w)

        # curve selectors (discount / projection) for curve-based products
        self._disc_combo = None
        self._proj_combo = None
        if self.product.curve_roles:
            combo_css = (f"background:{PALETTE.bg_panel_elevated};color:{PALETTE.txt0};"
                         f"border:1px solid {PALETTE.border_default};border-radius:3px;padding:3px 6px;")
            names = ["flat(r)"] + self._curve_names()
            self._disc_combo = QComboBox(); self._disc_combo.addItems(names)
            self._disc_combo.setStyleSheet(combo_css)
            dl = QLabel("Discount curve"); dl.setStyleSheet(f"color:{PALETTE.txt1};font-size:11px;")
            form.addRow(dl, self._disc_combo)
            if "proj" in self.product.curve_roles:
                self._proj_combo = QComboBox(); self._proj_combo.addItems(names)
                self._proj_combo.setStyleSheet(combo_css)
                pl = QLabel("Projection curve"); pl.setStyleSheet(f"color:{PALETTE.txt1};font-size:11px;")
                form.addRow(pl, self._proj_combo)
        form_panel.layout.addLayout(form)

        calc = QPushButton("Calculate")
        calc.setCursor(Qt.PointingHandCursor)
        calc.setStyleSheet(
            f"background:{PALETTE.accent};color:#1a1a1e;font-weight:700;border:none;"
            f"border-radius:4px;padding:6px 14px;")
        calc.clicked.connect(self.calculate)
        form_panel.layout.addWidget(calc)
        form_panel.layout.addStretch(1)        # pin inputs to the top (no leading gap)
        form_panel.setMaximumWidth(320)

        # result panel
        self.result_panel = WorkstationPanel(f"{self.product.label} — Result")
        self._price_label = QLabel("—")
        self._price_label.setStyleSheet(
            f"color:{PALETTE.accent};font-size:22px;font-weight:700;background:transparent;")
        self.result_panel.layout.addWidget(self._price_label)

        self._provenance = QHBoxLayout()
        self._provenance.setSpacing(6)
        prov_wrap = QWidget(); prov_wrap.setLayout(self._provenance)
        self.result_panel.layout.addWidget(prov_wrap)

        self.result_panel.layout.addWidget(SectionLabel("SENSITIVITIES"))
        self._greeks = DenseTable(["Greek", "Value"], [])
        self.result_panel.layout.addWidget(self._greeks)

        self._cf_label = SectionLabel("CASHFLOW SCHEDULE")
        self.result_panel.layout.addWidget(self._cf_label)
        self._cf_table = DenseTable(["Time (y)", "Cashflow"], [])
        self.result_panel.layout.addWidget(self._cf_table)
        self._cf_label.setVisible(False)
        self._cf_table.setVisible(False)

        self._warnings = QLabel("")
        self._warnings.setWordWrap(True)
        self._warnings.setStyleSheet(f"color:{PALETTE.amber};font-size:10px;background:transparent;")
        self.result_panel.layout.addWidget(self._warnings)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Qty"))
        self._qty = QLineEdit("1")
        self._qty.setMaximumWidth(60)
        self._qty.setStyleSheet(
            f"background:{PALETTE.bg_panel_elevated};color:{PALETTE.txt0};"
            f"border:1px solid {PALETTE.border_default};border-radius:3px;padding:2px 5px;")
        add_row.addWidget(self._qty)
        self._add_btn = QPushButton("Add to portfolio")
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(
            f"background:{PALETTE.bg_panel_elevated};color:{PALETTE.txt0};"
            f"border:1px solid {PALETTE.border_strong};border-radius:4px;padding:5px 12px;")
        self._add_btn.clicked.connect(self.add_to_portfolio)
        add_row.addWidget(self._add_btn)
        add_row.addStretch()
        self._confirm = QLabel("")
        self._confirm.setStyleSheet(f"color:{PALETTE.green};font-size:10px;")
        add_row.addWidget(self._confirm)
        self.result_panel.layout.addLayout(add_row)
        self.result_panel.layout.addStretch()

        root.addWidget(form_panel)
        root.addWidget(self.result_panel, 1)

    # -- logic -----------------------------------------------------------
    def _values(self) -> dict:
        out = {}
        for f in self.product.fields:
            w = self._inputs[f.key]
            if isinstance(w, QComboBox):
                out[f.key] = w.currentText()
            else:
                text = w.text().strip()
                try:
                    out[f.key] = float(text)
                except ValueError:
                    out[f.key] = text
        # inject UI-selected discount/projection curves (None = flat(r) fallback)
        if self._disc_combo is not None:
            snap = self._snapshot()
            dn = self._disc_combo.currentText()
            if dn != "flat(r)":
                out["__disc_curve"] = snap.curves.get(dn)
            if self._proj_combo is not None:
                pn = self._proj_combo.currentText()
                if pn != "flat(r)":
                    out["__proj_curve"] = snap.curves.get(pn)
        return out

    def _snapshot(self):
        if getattr(self, "_snap_cache", None) is None:
            self._snap_cache = self.pricing.market_data.demo_snapshot()
        return self._snap_cache

    def _curve_names(self):
        try:
            return sorted(self._snapshot().curves.keys())
        except Exception:
            return []

    def calculate(self):
        self._confirm.setText("")
        try:
            res = self.product.price(self.pricing, self._values())
        except Exception as exc:
            self._price_label.setText("error")
            self._warnings.setText(str(exc))
            self._add_btn.setEnabled(False)
            return
        self._last_result = res
        self._render(res)

    def _render(self, res: dict):
        value = res.get("value")
        self._price_label.setText(f"{value:,.4f}" if isinstance(value, (int, float)) else "—")

        # provenance chips
        while self._provenance.count():
            item = self._provenance.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        status = res.get("model_status") or "Unknown"
        self._provenance.addWidget(StatusChip(status))
        src = res.get("market_data_source") or "—"
        self._provenance.addWidget(DataSourceChip(src))
        snap = res.get("market_data_snapshot_id") or ""
        ver = res.get("model_version") or ""
        meta = QLabel(f"model {res.get('model_id','')} v{ver}  ·  snap {snap[:18]}")
        meta.setStyleSheet(f"color:{PALETTE.txt2};font-size:10px;")
        self._provenance.addWidget(meta)
        self._provenance.addStretch()

        raw = res.get("raw") or {}
        rows = []
        seen = set()
        for key, label in _GREEK_KEYS:
            if key in raw and key not in seen and isinstance(raw[key], (int, float)):
                rows.append([label, f"{raw[key]:,.6f}"])
                seen.add(key)
        self._greeks.set_rows(rows) if hasattr(self._greeks, "set_rows") else self._refresh_table(rows)

        # cashflow schedule (auto-generated by the pricer; manual via Custom Bond)
        cfs = raw.get("cash_flows") or raw.get("cashflows") or []
        cf_rows = [[f"{t:.3f}", f"{a:,.2f}"] for (t, a) in cfs[:80]
                   if isinstance(t, (int, float)) and isinstance(a, (int, float))]
        has_cf = bool(cf_rows)
        self._cf_label.setVisible(has_cf)
        self._cf_table.setVisible(has_cf)
        if has_cf:
            self._cf_table.setRowCount(len(cf_rows))
            from PySide6.QtWidgets import QTableWidgetItem
            for rr, row in enumerate(cf_rows):
                for cc, val in enumerate(row):
                    self._cf_table.setItem(rr, cc, QTableWidgetItem(str(val)))

        warnings = res.get("warnings") or []
        self._warnings.setText("  ·  ".join(warnings[:4]))
        self._add_btn.setEnabled(value is not None and not res.get("errors"))

    def _refresh_table(self, rows):
        self._greeks.setRowCount(len(rows))
        from PySide6.QtWidgets import QTableWidgetItem
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self._greeks.setItem(r, c, QTableWidgetItem(str(val)))

    def add_to_portfolio(self):
        try:
            qty = float(self._qty.text())
        except ValueError:
            qty = 1.0
        instrument, params, desc = self.product.to_position(self._values())
        res = self._last_result or {}
        pos = Position(
            id=f"{self.product.id}-{uuid.uuid4().hex[:6]}",
            instrument=instrument, description=desc, quantity=qty, params=params,
            market_data_snapshot_id=res.get("market_data_snapshot_id", ""),
            model_id=res.get("model_id", ""), model_status=res.get("model_status", ""),
        )
        shared_portfolio().add(pos)
        self._confirm.setText(f"✓ added {desc} ×{qty:g}")
