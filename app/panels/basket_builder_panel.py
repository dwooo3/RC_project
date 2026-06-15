"""Basket-note builder — structured notes on baskets of *real* instruments.

Assemble a basket from the live market universe (stocks, bonds, both, or indices),
choose the wrapper (principal protection on/off, guaranteed coupon on/off,
participation, cap, worst-of/average), and value it through the governed
``PricingService.price_basket_note`` engine. Surfaced in Pricing → Structured Notes
via the catalogue's ``custom_screen`` hook.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.chart import ChartWidget
from app.widgets import (
    Banner, FieldRow, ParamForm, ResultsGrid, SectionHeader, make_combo, make_pct,
    make_spin,
)
from ui.components import ModelStatus


_KIND_FILTERS = ["Stocks", "Bonds", "Both", "Indices"]
_FILTER_KINDS = {"Stocks": "equity", "Bonds": "bond", "Both": "all", "Indices": "index"}
_KIND_LABEL = {"equity": "Stock", "bond": "Bond", "index": "Index"}


class BasketBuilderPanel(QWidget):
    def __init__(self, pricing=None, parent=None):
        super().__init__(parent)
        from app.runtime import market_service
        from services.pricing_service import PricingService

        # Resolve real instruments against the live market store when available;
        # the workspace's demo service is bypassed so the basket sees real prices.
        self.market = market_service()
        self.pricing = (pricing if pricing is not None
                        and getattr(pricing.market_data, "market_db", None) is not None
                        else PricingService(market_data=self.market))
        self._universe: list[dict] = []
        self._build_ui()
        self._reload_universe()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sp = QSplitter(Qt.Horizontal)
        sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        left = QWidget()
        left.setObjectName("center_panel")
        left.setMinimumWidth(390)
        left.setMaximumWidth(470)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        ll.addWidget(SectionHeader(
            "Basket Note Builder",
            "Stocks · Bonds · Indices  ·  capital protection & guaranteed coupon",
            status=ModelStatus.PROTOTYPE))
        self.banner = Banner()
        ll.addWidget(self.banner)

        # Instrument-type filter + search + universe list.
        pick = QVBoxLayout()
        pick.setContentsMargins(14, 8, 14, 4)
        pick.setSpacing(6)
        self.kind_filter = make_combo(_KIND_FILTERS)
        self.kind_filter.currentIndexChanged.connect(lambda _i: self._reload_universe())
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search ticker / issuer…")
        self.search.textChanged.connect(lambda _t: self._refilter())
        kr = QHBoxLayout()
        kr.setSpacing(8)
        kr.addWidget(QLabel("Underlying:"))
        kr.addWidget(self.kind_filter, 1)
        pick.addLayout(kr)
        pick.addWidget(self.search)
        self.universe_list = QListWidget()
        self.universe_list.setMaximumHeight(150)
        self.universe_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.universe_list.itemDoubleClicked.connect(lambda _i: self._add_selected())
        pick.addWidget(self.universe_list)
        add_btn = QPushButton("+  Add to basket")
        add_btn.setObjectName("clear_btn")
        add_btn.clicked.connect(self._add_selected)
        pick.addWidget(add_btn)
        ll.addLayout(pick)

        # Basket table (weights editable, remove per row).
        self.basket = QTableWidget(0, 4)
        self.basket.setHorizontalHeaderLabels(["Instrument", "Type", "Weight", ""])
        self.basket.verticalHeader().setVisible(False)
        self.basket.setMaximumHeight(150)
        hh = self.basket.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        bt = QVBoxLayout()
        bt.setContentsMargins(14, 2, 14, 4)
        bt.addWidget(QLabel("Basket"))
        bt.addWidget(self.basket)
        ll.addLayout(bt)

        # Structure controls.
        pf = ParamForm()
        self.protection = make_combo(["With protection", "Without protection"])
        self.protect_lvl = make_pct(1.0, 0.0, 1.0)
        self.guarantee = make_combo(["No guaranteed coupon", "With guaranteed coupon"])
        self.cpn_rate = make_pct(0.08, 0.0, 1.0)
        self.cpn_freq = make_spin(1, 12, 1, 1, 0)
        self.participation = make_pct(1.0, 0.0, 5.0)
        self.cap = make_pct(0.0, 0.0, 5.0)
        self.basket_type = make_combo(["Average (weighted)", "Worst-of", "Best-of"])
        self.maturity = make_spin(0.25, 15, 3, 0.25, 2, "yr")
        self.face = make_spin(1, 1e9, 1000, 100, 0)
        self.rate = make_pct(0.16, -0.1, 1.0)
        self.n_sims = make_spin(2000, 200000, 20000, 1000, 0)

        pf.add_group("Principal", [
            FieldRow("Protection", self.protection, "Capital guarantee on/off"),
            FieldRow("Protected level", self.protect_lvl, "Fraction of notional guaranteed"),
        ])
        pf.add_group("Guaranteed coupon", [
            FieldRow("Coupon", self.guarantee, "Fixed coupon paid regardless of performance"),
            FieldRow("Coupon rate", self.cpn_rate),
            FieldRow("Freq / year", self.cpn_freq),
        ])
        pf.add_group("Upside", [
            FieldRow("Participation", self.participation, "Share of basket upside"),
            FieldRow("Upside cap", self.cap, "0 % = uncapped"),
            FieldRow("Basket", self.basket_type, "Average / worst-of / best-of return"),
        ])
        pf.add_group("Terms", [
            FieldRow("Maturity", self.maturity),
            FieldRow("Notional", self.face),
            FieldRow("Discount rate", self.rate),
            FieldRow("MC paths", self.n_sims),
        ])
        ll.addWidget(pf, 1)

        bb = QHBoxLayout()
        bb.setContentsMargins(16, 10, 16, 14)
        bb.setSpacing(8)
        self.btn = QPushButton("Price Note")
        self.btn.setObjectName("calc_btn")
        self.btn.setFixedHeight(38)
        self.clr = QPushButton("Clear")
        self.clr.setObjectName("clear_btn")
        self.clr.setFixedHeight(38)
        self.clr.setFixedWidth(90)
        bb.addWidget(self.btn, 1)
        bb.addWidget(self.clr)
        ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate)
        self.clr.clicked.connect(self._clear)

        # Results.
        right = QWidget()
        right.setObjectName("results_panel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        hdr = QWidget()
        hdr.setObjectName("results_header")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 10, 18, 10)
        lb = QLabel("RESULTS")
        lb.setObjectName("results_title_lbl")
        hl.addWidget(lb)
        rl.addWidget(hdr)
        self.grid = ResultsGrid(
            ["Fair Value", "Fair Value %", "Fair Participation", "Bond Floor",
             "Option Budget", "Guaranteed Cpn PV", "Capital Loss Prob",
             "Expected Return", "Std Error"],
            cols=3, highlight="Fair Value")
        rl.addWidget(self.grid)
        self.chart = ChartWidget()
        self.chart.clear()
        rl.addWidget(self.chart, 1)

        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setSizes([440, 900])
        root.addWidget(sp)

    # ── universe ──────────────────────────────────────────────────────
    def _reload_universe(self):
        kind = _FILTER_KINDS[self.kind_filter.currentText()]
        try:
            self._universe = self.market.basket_universe(kind)
        except Exception as exc:
            self._universe = []
            self.banner.show_error(f"Universe load failed: {exc}")
        self._refilter()

    def _refilter(self):
        q = self.search.text().strip().lower()
        self.universe_list.clear()
        for u in self._universe:
            hay = f"{u['secid']} {u.get('label', '')}".lower()
            if q and q not in hay:
                continue
            label = u["secid"]
            if u.get("label") and u["label"] != u["secid"]:
                label = f"{u['secid']} — {u['label']}"
            item = QListWidgetItem(f"{label}  ·  {_KIND_LABEL.get(u['kind'], u['kind'])}")
            item.setData(Qt.UserRole, u)
            self.universe_list.addItem(item)

    # ── basket table ──────────────────────────────────────────────────
    def _add_selected(self):
        existing = {self.basket.item(r, 0).text() for r in range(self.basket.rowCount())}
        for item in self.universe_list.selectedItems() or []:
            u = item.data(Qt.UserRole)
            if u and u["secid"] not in existing:
                self._add_row(u["secid"], u["kind"])
                existing.add(u["secid"])

    def _add_row(self, secid: str, kind: str, weight: float = 1.0):
        r = self.basket.rowCount()
        self.basket.insertRow(r)
        id_item = QTableWidgetItem(secid)
        id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)
        id_item.setData(Qt.UserRole, kind)
        self.basket.setItem(r, 0, id_item)
        kind_item = QTableWidgetItem(_KIND_LABEL.get(kind, kind))
        kind_item.setFlags(kind_item.flags() & ~Qt.ItemIsEditable)
        self.basket.setItem(r, 1, kind_item)
        self.basket.setItem(r, 2, QTableWidgetItem(f"{weight:g}"))
        rm = QPushButton("✕")
        rm.setFixedWidth(28)
        rm.clicked.connect(lambda _c=False, b=id_item: self._remove_row(b))
        self.basket.setCellWidget(r, 3, rm)

    def _remove_row(self, id_item):
        row = id_item.row()
        if row >= 0:
            self.basket.removeRow(row)

    def _basket_specs(self) -> list[dict]:
        specs = []
        for r in range(self.basket.rowCount()):
            secid = self.basket.item(r, 0).text()
            kind = self.basket.item(r, 0).data(Qt.UserRole) or "equity"
            try:
                weight = float(self.basket.item(r, 2).text())
            except (ValueError, AttributeError):
                weight = 1.0
            specs.append({"secid": secid, "kind": kind, "weight": weight})
        return specs

    # ── pricing ───────────────────────────────────────────────────────
    def calculate(self):
        self.banner.clear()
        self.grid.clear_all()
        specs = self._basket_specs()
        if not specs:
            self.banner.show_error("Add at least one instrument to the basket.")
            return
        protection = (self.protect_lvl.value() / 100
                      if self.protection.currentText().startswith("With") else 0.0)
        guaranteed = (self.cpn_rate.value() / 100
                      if self.guarantee.currentText().startswith("With") else 0.0)
        cap = self.cap.value() / 100 or None
        btype = {"Average (weighted)": "average", "Worst-of": "worst_of",
                 "Best-of": "best_of"}[self.basket_type.currentText()]
        try:
            res = self.pricing.price_basket_note(
                specs, self.rate.value() / 100, self.maturity.value(),
                principal_protection=protection, guaranteed_coupon=guaranteed,
                coupon_freq=int(self.cpn_freq.value()),
                participation=self.participation.value() / 100, cap=cap,
                basket_type=btype, face=self.face.value(), n_sims=int(self.n_sims.value()))
        except Exception as exc:
            self.banner.show_error(str(exc))
            return
        if res.get("errors"):
            self.banner.show_error("; ".join(res["errors"]))
            return
        self._render(res, protection, cap, btype)

    def _render(self, res, protection, cap, btype):
        raw = res.get("raw") or {}
        face = self.face.value()
        fv = raw.get("price", 0.0)
        self._set("Fair Value", fv, sub=f"{res.get('model_status', '')}")
        self._set("Fair Value %", raw.get("price_ratio", 0.0) * 100, sub="of notional")
        fp = raw.get("fair_participation")
        self._set("Fair Participation", (fp * 100 if fp is not None else float("nan")),
                  sub="at par")
        self._set("Bond Floor", raw.get("bond_floor", 0.0))
        self._set("Option Budget", raw.get("option_budget", 0.0))
        self._set("Guaranteed Cpn PV", raw.get("guaranteed_coupon_pv", 0.0))
        self._set("Capital Loss Prob", raw.get("capital_loss_prob", 0.0) * 100, sub="%")
        self._set("Expected Return", raw.get("expected_return", 0.0) * 100, sub="%")
        self._set("Std Error", raw.get("stderr", 0.0))
        self._plot(protection, cap, btype, face)

    def _set(self, name, value, sub=""):
        card = self.grid._cards.get(name)
        if card is not None:
            card.set_value(value, sub=sub)

    def _plot(self, protection, cap, btype, face):
        part = self.participation.value() / 100
        perf = np.linspace(0.3, 1.8, 120)
        capital = protection + (1 - protection) * np.minimum(perf, 1.0)
        upside = part * np.maximum(perf - 1.0, 0.0)
        if cap is not None:
            upside = np.minimum(upside, cap)
        redemption = (capital + upside) * face
        title = f"Basket note redemption · {btype.replace('_', '-')}"
        self.chart.plot_payoff(perf * 100, redemption, title, S=100.0,
                               barriers=[protection * 100] if protection > 0 else None)
        self.chart._finish(self.chart.ax, title, "Basket level (% of initial)",
                           "Redemption")

    def _clear(self):
        self.grid.clear_all()
        self.chart.clear()
        self.banner.clear()
