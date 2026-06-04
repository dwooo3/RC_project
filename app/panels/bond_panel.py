"""Bond pricing panel."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
import math
from datetime import date
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView, QFrame
)
from PySide6.QtCore import Qt

from app.widgets import (ModelStatus, 
    ParamForm, FieldRow, ResultsGrid, SectionHeader,
    Banner, make_spin, make_pct, make_combo
)
from app.chart import ChartWidget
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService


class BondPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.market_data = MarketDataService()
        self.pricing = PricingService(market_data=self.market_data)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sp = QSplitter(Qt.Horizontal)
        sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        # ── Left: params ──────────────────────────────────
        left = QWidget()
        left.setObjectName("center_panel")
        left.setMinimumWidth(320)
        left.setMaximumWidth(400)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        ll.addWidget(SectionHeader("Bond Pricing",
                 "Price · YTM · Z-spread · Duration · Convexity · DV01",
                 status=ModelStatus.APPROXIMATION))
        self.banner = Banner()
        ll.addWidget(self.banner)

        f = ParamForm()
        self.face   = make_spin(1, 1e9, 100, 1, 2)
        self.coupon = make_pct(0.05, 0, 0.5)
        self.T      = make_spin(0.1, 100, 5, 0.5, 2, "yr")
        self.freq   = make_combo(["1", "2", "4", "12"], "2")

        self.curve_type = make_combo([
            "Flat (manual rate)",
            "OFZ G-curve (preset)",
            "CBR Key rate curve",
            "Corporate 1st tier (OFZ+100bps)",
            "Corporate HY (OFZ+300bps)",
            "RUONIA OIS",
        ])
        self.rate    = make_pct(0.04)
        self.zspread = make_spin(-1000, 5000, 0, 10, 0)

        f.add_group("Bond Parameters", [
            FieldRow("Face value",    self.face),
            FieldRow("Coupon rate",   self.coupon),
            FieldRow("Maturity",      self.T),
            FieldRow("Freq / year",   self.freq),
        ])
        f.add_group("Discount Curve", [
            FieldRow("Curve type",    self.curve_type),
            FieldRow("Flat rate",     self.rate),
            FieldRow("Z-spread (bps)", self.zspread),
        ])
        ll.addWidget(f, 1)

        # Button bar
        bb_w = QWidget()
        bb_w.setStyleSheet("background:#1a1a1e; border-top:1px solid #2e2e33;")
        bb = QHBoxLayout(bb_w)
        bb.setContentsMargins(14, 10, 14, 12)
        bb.setSpacing(8)
        self.btn = QPushButton("Calculate")
        self.btn.setObjectName("calc_btn")
        self.btn.setFixedHeight(36)
        self.clr = QPushButton("Clear")
        self.clr.setObjectName("clear_btn")
        self.clr.setFixedHeight(36)
        self.clr.setFixedWidth(80)
        bb.addWidget(self.btn, 1)
        bb.addWidget(self.clr)
        ll.addWidget(bb_w)

        self.btn.clicked.connect(self.calculate)
        self.clr.clicked.connect(self.clear)

        # ── Right: results ────────────────────────────────
        right = QWidget()
        right.setObjectName("results_panel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        hdr = QWidget()
        hdr.setObjectName("results_header")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 9, 16, 9)
        lb = QLabel("RESULTS")
        lb.setObjectName("results_title_lbl")
        hl.addWidget(lb)
        rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["Price", "YTM", "Z-spread",
             "Mac Duration", "Mod Duration", "Convexity",
             "DV01", "Accrued", "Clean Price"],
            cols=3, highlight="Price",
        )
        rl.addWidget(self.grid)

        # Cash-flow table
        self.cf_table = QTableWidget(0, 3)
        self.cf_table.setHorizontalHeaderLabels(["Time (yr)", "Cash Flow", "Present Value"])
        self.cf_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cf_table.setMaximumHeight(160)
        self.cf_table.setAlternatingRowColors(True)
        rl.addWidget(self.cf_table)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2e2e33; max-height:1px;")
        rl.addWidget(sep)

        self.chart = ChartWidget()
        self.chart.clear()
        rl.addWidget(self.chart, 1)

        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setSizes([360, 900])
        root.addWidget(sp)

    def _curve_selection(self):
        ct = self.curve_type.currentText()
        zs = self.zspread.value() / 10000

        if "Flat" in ct:
            curve_id = "manual_flat"
            curve = self.market_data.flat_curve(self.rate.value() / 100)
        elif "OFZ" in ct:
            curve_id = "ofz_demo"
            curve = self.market_data.ofz_curve()
        elif "CBR" in ct:
            curve_id = "cbr_key_demo"
            curve = self.market_data.cbr_key_rate_curve()
        elif "Corporate 1st" in ct:
            curve_id = "corp_1t_demo"
            curve = self.market_data.corporate_curve("1st")
        elif "HY" in ct:
            curve_id = "corp_hy_demo"
            curve = self.market_data.corporate_curve("HY")
        else:
            curve_id = "ruonia_demo"
            curve = self.market_data.ruonia_curve()

        if zs != 0:
            curve = curve.add_spread(self.market_data.flat_curve(zs, label="zspread"))
            curve_id = f"{curve_id}_zspread"
        return curve_id, curve

    def _market_data_snapshot(self):
        curve_id, curve = self._curve_selection()
        source = "MANUAL" if "Flat" in self.curve_type.currentText() else "DEMO"
        snapshot = self.market_data.snapshot_from_curves(
            {curve_id: curve},
            snapshot_id=f"bond-panel-{curve_id}-{date.today().isoformat()}",
            source=source,
            valuation_date=date.today(),
            metadata={"warning": "BondPanel market data is demo/manual and not production valuation."},
        )
        return snapshot, curve_id

    def calculate(self):
        self.banner.clear()
        try:
            snapshot, curve_id = self._market_data_snapshot()
            service_res = self.pricing.price_bond(
                self.face.value(),
                self.coupon.value() / 100,
                self.T.value(),
                int(self.freq.currentText()),
                snapshot=snapshot,
                curve_id=curve_id,
            )
            if service_res["errors"]:
                raise ValueError("; ".join(service_res["errors"]))
            if service_res["warnings"]:
                self.banner.show_error("Warnings: " + " ".join(service_res["warnings"][:3]))
            res = service_res["raw"] or {}

            self.grid.set("Price",        res["price"],        color="#d97757")
            self.grid.set("YTM",          res["ytm"],          sub=f"{res['ytm']*100:.3f}%")
            zs = res.get("zspread", 0) or 0
            self.grid.set("Z-spread",     zs,                  sub=f"{zs*10000:.1f} bps")
            self.grid.set("Mac Duration", res["mac_duration"],  sub="years")
            self.grid.set("Mod Duration", res["mod_duration"],  sub="years")
            self.grid.set("Convexity",    res["convexity"])
            self.grid.set("DV01",         res["dv01"],          sub="per 1bp")
            self.grid.set("Accrued",      0.0)
            self.grid.set("Clean Price",  res["price"])

            # Cash-flow table
            r_flat = self.rate.value() / 100
            cfs    = res.get("cash_flows", [])
            self.cf_table.setRowCount(len(cfs))
            cf_times = []; cf_vals = []
            for i, (t, cf) in enumerate(cfs):
                pv = cf * math.exp(-r_flat * t)
                self.cf_table.setItem(i, 0, QTableWidgetItem(f"{t:.3f}"))
                self.cf_table.setItem(i, 1, QTableWidgetItem(f"{cf:.2f}"))
                self.cf_table.setItem(i, 2, QTableWidgetItem(f"{pv:.4f}"))
                cf_times.append(t); cf_vals.append(cf)

            # Chart: price-yield + duration + cashflows
            r_mid     = max(0.001, r_flat)
            yields    = np.linspace(max(0.001, r_mid - 0.05), r_mid + 0.05, 80)
            prices_y  = []
            dur_mods  = []
            for y in yields:
                c2 = self.market_data.flat_curve(y)
                r2 = self.pricing.price_bond(
                    self.face.value(),
                    self.coupon.value() / 100,
                    self.T.value(),
                    int(self.freq.currentText()),
                    curve=c2,
                )
                raw = r2["raw"] or {}
                prices_y.append(raw["price"])
                dur_mods.append(raw["mod_duration"])

            self.chart.plot_bond_analysis(
                yields_pct   = yields * 100,
                prices       = prices_y,
                dur_yields   = yields * 100,
                durations    = dur_mods,
                cf_times     = cf_times,
                cf_vals      = cf_vals,
                coupon_pct   = self.coupon.value(),
                rate_pct     = r_flat * 100,
                mac_dur      = res["mac_duration"],
                mod_dur      = res["mod_duration"],
                dv01         = res["dv01"],
            )

        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all()
        self.chart.clear()
        self.banner.clear()
        self.cf_table.setRowCount(0)
