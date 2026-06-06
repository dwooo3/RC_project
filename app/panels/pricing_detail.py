"""Interactive pricing detail screen — inputs -> PricingService -> governed result.

v6 layout: a scrollable Valuation card (price, provenance, key metrics, cashflow
table, discount-curve table) with a pinned Add-to-portfolio footer, next to an
inputs-only Parameters card.
"""
import math
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.panels.pricing_catalogue import Product
from app.panels.session import shared_portfolio
from domain.portfolio import Position
from ui.components import (
    DataSourceChip, DenseTable, KeyValueGrid, ScrollableCard, SectionLabel,
    StatusChip, WorkspaceCard, fit_table_height, mark_invalid,
)
from ui.theme import PALETTE

_GREEK_KEYS = [
    ("ytm", "YTM"), ("current_yield", "Current yield"),
    ("mac_duration", "Macaulay dur."), ("mod_duration", "Mod. duration"),
    ("effective_duration", "Eff. duration"), ("convexity", "Convexity"),
    ("dv01", "DV01"), ("pv01", "PV01"),
    ("z_spread", "Z-spread"), ("zspread", "Z-spread"), ("g_spread", "G-spread"),
    ("i_spread", "I-spread"), ("oas", "OAS"),
    ("delta", "Delta"), ("delta_S", "Delta"), ("gamma", "Gamma"), ("vega", "Vega"),
    ("theta", "Theta"), ("rho", "Rho"), ("cs01", "CS01"),
    ("ytc", "YTC"), ("ytp", "YTP"), ("ytw", "YTW"),
    ("discount_margin", "Disc margin"), ("spread_dv01", "Spread DV01"),
    ("discount_yield", "Disc yield"), ("money_market_yield", "MM yield"), ("bey", "BEY"),
    ("maturity_value", "Maturity val"), ("real_yield", "Real yield"),
    ("indexed_principal", "Indexed prin"), ("inflation_dv01", "Infl DV01"),
    ("forward_price", "Forward"), ("carry", "Carry"), ("funding_dv01", "Funding DV01"),
    ("financing_cost", "Financing"), ("repo_rate", "Repo rate"),
    ("theoretical_futures", "Theo futures"), ("invoice_price", "Invoice"),
    ("net_basis", "Net basis"), ("gross_basis", "Gross basis"),
    ("implied_repo", "Implied repo"), ("futures_dv01", "Futures DV01"),
    ("hedge_ratio", "Hedge ratio"), ("conversion_factor", "Conv factor"),
    ("implied_rate", "Implied rate"),
    ("straight_value", "Straight"), ("option_value", "Option value"),
    ("fair_spread", "Fair spread"), ("npv", "NPV"), ("annuity", "Annuity"),
]

_PCT_KEYS = {"ytm", "ytc", "ytp", "ytw", "current_yield", "real_yield",
             "discount_yield", "money_market_yield", "bey", "implied_rate", "repo_rate"}
_BP_KEYS = {"z_spread", "zspread", "g_spread", "i_spread", "discount_margin",
            "fair_spread", "oas"}
_MAX_METRICS = 10


def _fmt_metric(key: str, v: float) -> str:
    if key in _PCT_KEYS:
        return f"{v * 100:.2f}%" if abs(v) < 1 else f"{v:.2f}%"
    if key in _BP_KEYS:
        return f"{v * 10000:.0f} bp" if abs(v) < 1 else f"{v:.0f} bp"
    av = abs(v)
    if av == 0:
        return "0"
    if av >= 1000:
        return f"{v:,.2f}"
    if av >= 1:
        return f"{v:.4f}"
    return f"{v:.6f}"


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
        root.setSpacing(16)
        root.addWidget(self._build_valuation_card(), 1)
        root.addWidget(self._build_parameters_card())
        self._set_idle()

    def _build_valuation_card(self) -> QWidget:
        card = ScrollableCard(elevated=True)
        body = card.body_layout

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(SectionLabel("VALUATION"))
        head.addStretch()
        self._pills = QHBoxLayout()
        self._pills.setSpacing(6)
        pill_wrap = QWidget()
        pill_wrap.setLayout(self._pills)
        head.addWidget(pill_wrap)
        body.addLayout(head)

        self._price_label = QLabel("—")
        self._price_label.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:40px;font-weight:700;background:transparent;")
        body.addWidget(self._price_label)

        self._prov_sub = QLabel("")
        self._prov_sub.setWordWrap(True)
        self._prov_sub.setStyleSheet(f"color:{PALETTE.txt2};font-size:11px;background:transparent;")
        body.addWidget(self._prov_sub)

        # Input-validation error (red).
        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(f"color:{PALETTE.red_text};font-size:11px;background:transparent;")
        self._error_label.setVisible(False)
        body.addWidget(self._error_label)

        # Demo / stale market-data banner (amber).
        self._stale_label = QLabel("")
        self._stale_label.setWordWrap(True)
        self._stale_label.setStyleSheet(
            f"color:{PALETTE.warn_text};background:{PALETTE.warn_soft};"
            "border-radius:8px;padding:6px 10px;font-size:11px;")
        self._stale_label.setVisible(False)
        body.addWidget(self._stale_label)

        # Model warnings (amber).
        self._warnings = QLabel("")
        self._warnings.setWordWrap(True)
        self._warnings.setStyleSheet(f"color:{PALETTE.warn_text};font-size:11px;background:transparent;")
        self._warnings.setVisible(False)
        body.addWidget(self._warnings)

        body.addWidget(self._divider())
        self._metrics = KeyValueGrid()
        body.addWidget(self._metrics)

        self._cf_label = SectionLabel("CASHFLOW SCHEDULE")
        body.addWidget(self._cf_label)
        self._cf_table = DenseTable(["Time (y)", "Cashflow", "DF", "PV"], [])
        self._cf_table.setSortingEnabled(False)
        body.addWidget(self._cf_table)
        self._cf_label.setVisible(False)
        self._cf_table.setVisible(False)

        self._curve_label = SectionLabel("DISCOUNT CURVE")
        body.addWidget(self._curve_label)
        self._curve_table = DenseTable(["Tenor", "Zero rate", "Disc factor"], [])
        self._curve_table.setSortingEnabled(False)
        body.addWidget(self._curve_table)
        self._curve_label.setVisible(False)
        self._curve_table.setVisible(False)

        body.addStretch(1)
        card.set_footer(self._build_footer())
        return card

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setFixedHeight(66)
        row = QHBoxLayout(footer)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(12)

        mv_col = QVBoxLayout()
        mv_col.setSpacing(1)
        mv_caption = QLabel("MARKET VALUE")
        mv_caption.setStyleSheet(
            f"color:{PALETTE.txt2};font-size:10px;font-weight:700;letter-spacing:0.5px;background:transparent;")
        self._mv_value = QLabel("—")
        self._mv_value.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:16px;font-weight:700;background:transparent;")
        mv_col.addWidget(mv_caption)
        mv_col.addWidget(self._mv_value)
        row.addLayout(mv_col)
        row.addStretch()

        qty_lbl = QLabel("QTY")
        qty_lbl.setStyleSheet(f"color:{PALETTE.txt2};font-size:11px;background:transparent;")
        row.addWidget(qty_lbl)
        self._qty = QLineEdit("1")
        self._qty.setFixedWidth(72)
        self._qty.textChanged.connect(self._update_market_value)
        row.addWidget(self._qty)

        self._add_btn = QPushButton("+  Add to portfolio")
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setFixedWidth(196)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(
            f"QPushButton{{background:{PALETTE.accent};color:{PALETTE.accent_on};border:none;"
            f"border-radius:10px;font-size:13px;font-weight:700;padding:8px 14px;}}"
            f"QPushButton:hover{{background:{PALETTE.accent_hi};}}"
            f"QPushButton:disabled{{background:{PALETTE.accent_soft};color:{PALETTE.accent_pressed};}}")
        self._add_btn.clicked.connect(self.add_to_portfolio)
        row.addWidget(self._add_btn)

        self._confirm = QLabel("")
        self._confirm.setStyleSheet(f"color:{PALETTE.green};font-size:11px;background:transparent;")
        row.addWidget(self._confirm)
        return footer

    def _build_parameters_card(self) -> QWidget:
        card = WorkspaceCard(object_name="workspace_card", elevated=True)
        card.setFixedWidth(384)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        lay.addWidget(SectionLabel("PARAMETERS"))

        # Scroll only when the parameter grid overflows the card height.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        scroll.viewport().setStyleSheet("background:transparent;")

        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 0, 6, 0)
        outer.setSpacing(0)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        cursor = {"row": 0, "col": 0}

        def _place(cell: QWidget, wide: bool):
            if wide:
                if cursor["col"] != 0:
                    cursor["row"] += 1
                    cursor["col"] = 0
                grid.addWidget(cell, cursor["row"], 0, 1, 2)
                cursor["row"] += 1
            else:
                grid.addWidget(cell, cursor["row"], cursor["col"])
                cursor["col"] += 1
                if cursor["col"] >= 2:
                    cursor["col"] = 0
                    cursor["row"] += 1

        for f in self.product.fields:
            if f.choices is not None:
                w = QComboBox()
                w.addItems(f.choices)
                w.setCurrentText(str(f.default))
            else:
                w = QLineEdit(str(f.default))
            self._inputs[f.key] = w
            _place(self._field_cell(f.label, w), wide=f.wide)

        self._disc_combo = None
        self._proj_combo = None
        if self.product.curve_roles:
            names = ["flat(r)"] + self._curve_names()
            self._disc_combo = QComboBox()
            self._disc_combo.addItems(names)
            _place(self._field_cell("Discount curve", self._disc_combo), wide=True)
            if "proj" in self.product.curve_roles:
                self._proj_combo = QComboBox()
                self._proj_combo.addItems(names)
                _place(self._field_cell("Projection curve", self._proj_combo), wide=True)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)
        outer.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        self._param_grid = grid
        self._param_scroll = scroll
        return card

    def _field_cell(self, label_text: str, widget: QWidget) -> QWidget:
        cell = QWidget()
        col = QVBoxLayout(cell)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        lab = QLabel(label_text)
        lab.setStyleSheet(f"color:{PALETTE.txt2};font-size:11px;background:transparent;")
        col.addWidget(lab)
        col.addWidget(widget)
        return cell

    def _divider(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{PALETTE.divider};")
        return line

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

    def _discount_fn(self):
        """Best-effort t->discount-factor for cashflow PV (selected curve or flat rate)."""
        try:
            if self._disc_combo is not None:
                name = self._disc_combo.currentText()
                if name != "flat(r)":
                    curve = self._snapshot().curves.get(name)
                    if curve is not None and callable(getattr(curve, "discount", None)):
                        return curve.discount
        except Exception:
            pass
        try:
            vals = self._values()
        except Exception:
            vals = {}
        for k in ("r", "rate", "flat_rate", "y", "ytm", "yield"):
            rv = vals.get(k)
            if isinstance(rv, (int, float)):
                return lambda t, _r=float(rv): math.exp(-_r * t)
        return None

    def _set_idle(self):
        """Empty state shown before the first valuation."""
        self._price_label.setText("—")
        self._price_label.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:40px;font-weight:700;background:transparent;")
        self._prov_sub.setText("Press Calculate to value this instrument.")
        self._metrics.set_pairs([])
        for lbl in (self._error_label, self._stale_label, self._warnings):
            lbl.setVisible(False)
        for tbl, lab in ((self._cf_table, self._cf_label), (self._curve_table, self._curve_label)):
            tbl.setVisible(False)
            lab.setVisible(False)
        self._mv_value.setText("—")
        self._add_btn.setEnabled(False)

    def _validate(self) -> list[str]:
        """Mark numeric fields that don't parse; return the labels that failed."""
        errors = []
        for f in self.product.fields:
            w = self._inputs[f.key]
            if isinstance(w, QLineEdit) and not isinstance(f.default, str):
                ok = True
                try:
                    float(w.text().strip())
                except ValueError:
                    ok = False
                mark_invalid(w, not ok)
                if not ok:
                    errors.append(f.label)
            elif isinstance(w, QLineEdit):
                mark_invalid(w, False)
        return errors

    def calculate(self):
        self._confirm.setText("")
        errors = self._validate()
        if errors:
            self._error_label.setText("Check these fields: " + ", ".join(errors))
            self._error_label.setVisible(True)
            self._price_label.setText("—")
            self._add_btn.setEnabled(False)
            return
        self._error_label.setVisible(False)
        try:
            res = self.product.price(self.pricing, self._values())
        except Exception as exc:
            self._price_label.setText("error")
            self._error_label.setText(str(exc))
            self._error_label.setVisible(True)
            self._add_btn.setEnabled(False)
            return
        self._last_result = res
        self._render(res)

    def _render(self, res: dict):
        value = res.get("value")
        self._price_label.setText(f"{value:,.4f}" if isinstance(value, (int, float)) else "—")
        status = res.get("model_status") or "Unknown"
        price_color = PALETTE.red if status == "Broken" else PALETTE.txt0
        self._price_label.setStyleSheet(
            f"color:{price_color};font-size:40px;font-weight:700;background:transparent;")
        self._update_market_value()

        # status pills
        while self._pills.count():
            item = self._pills.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        src = res.get("market_data_source") or "—"
        self._pills.addWidget(StatusChip(status))
        self._pills.addWidget(DataSourceChip(src))

        # demo / stale market-data banner
        snap_id = res.get("market_data_snapshot_id") or ""
        stale = str(src).upper() in {"DEMO", "MANUAL"} or "demo" in snap_id.lower()
        self._stale_label.setText("Demo / manual market data — not production-validated.")
        self._stale_label.setVisible(stale)

        # provenance subline
        raw = res.get("raw") or {}
        parts = []
        for key, cap in (("clean_price", "Clean"), ("dirty_price", "Dirty"),
                         ("accrued_interest", "Accrued")):
            if isinstance(raw.get(key), (int, float)):
                parts.append(f"{cap} {raw[key]:,.2f}")
        snap = res.get("market_data_snapshot_id") or ""
        if snap:
            parts.append(f"snapshot {snap[:22]}")
        mid = res.get("model_id") or ""
        ver = res.get("model_version") or ""
        if mid:
            parts.append(f"{mid} v{ver}")
        self._prov_sub.setText("  ·  ".join(parts))

        # key metrics
        pairs = []
        seen = set()
        for key, label in _GREEK_KEYS:
            if key in seen or label in {p[0] for p in pairs}:
                continue
            v = raw.get(key)
            if isinstance(v, (int, float)):
                pairs.append((label, _fmt_metric(key, v)))
                seen.add(key)
            if len(pairs) >= _MAX_METRICS:
                break
        self._metrics.set_pairs(pairs)

        self._render_cashflows(raw)
        self._render_curve()

        warnings = res.get("warnings") or []
        text = "  ·  ".join(warnings[:4])
        short = (text[:150].rstrip() + "…") if len(text) > 150 else text
        self._warnings.setText(short)
        self._warnings.setToolTip(text)
        self._warnings.setVisible(bool(warnings))
        self._add_btn.setEnabled(value is not None and not res.get("errors"))

    def _render_cashflows(self, raw: dict):
        cfs = raw.get("cash_flows") or raw.get("cashflows") or []
        disc = self._discount_fn()
        rows = []
        for cf in cfs[:80]:
            try:
                t, a = cf
            except (TypeError, ValueError):
                continue
            if not (isinstance(t, (int, float)) and isinstance(a, (int, float))):
                continue
            df = pv = None
            if disc is not None:
                try:
                    df = float(disc(float(t)))
                    pv = a * df
                except Exception:
                    df = pv = None
            rows.append([
                f"{t:.3f}", f"{a:,.2f}",
                f"{df:.4f}" if isinstance(df, (int, float)) else "—",
                f"{pv:,.2f}" if isinstance(pv, (int, float)) else "—",
            ])
        has = bool(rows)
        self._cf_label.setVisible(has)
        self._cf_table.setVisible(has)
        if has:
            self._set_table(self._cf_table, rows)

    def _render_curve(self):
        rows = []
        try:
            if self._disc_combo is not None:
                name = self._disc_combo.currentText()
                curve = None if name == "flat(r)" else self._snapshot().curves.get(name)
                if curve is not None and hasattr(curve, "tenors"):
                    for t in curve.tenors:
                        tf = float(t)
                        zr = curve.rate(tf) if callable(getattr(curve, "rate", None)) else None
                        df = curve.discount(tf) if callable(getattr(curve, "discount", None)) else None
                        rows.append([
                            f"{tf:g}y",
                            f"{zr * 100:.2f}%" if isinstance(zr, (int, float)) else "—",
                            f"{df:.4f}" if isinstance(df, (int, float)) else "—",
                        ])
        except Exception:
            rows = []
        has = bool(rows)
        self._curve_label.setVisible(has)
        self._curve_table.setVisible(has)
        if has:
            self._set_table(self._curve_table, rows)

    def _set_table(self, table: DenseTable, rows: list[list[str]]):
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if c > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, item)
        fit_table_height(table)

    def _update_market_value(self):
        res = self._last_result or {}
        value = res.get("value")
        if not isinstance(value, (int, float)):
            self._mv_value.setText("—")
            return
        try:
            qty = float(self._qty.text())
        except (ValueError, AttributeError):
            qty = 1.0
        self._mv_value.setText(f"{value * qty:,.2f}")

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
        self._confirm.setText(f"✓ added ×{qty:g}")
