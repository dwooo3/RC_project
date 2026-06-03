"""Fixed Income panel: Bond, IRS, Cap/Floor, Swaption."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt
from app.widgets import ParamForm, FieldRow, ResultsGrid, SectionHeader, Banner, make_spin, make_pct, make_combo, MetricCard
from app.chart import ChartWidget


class RatesPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(340); left.setMaximumWidth(420)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Fixed Income", "Bond · IRS · Cap/Floor · Swaption"))
        self.banner = Banner(); ll.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane{border:none;} ")

        # ── Bond ─────────────────────────────────────────
        bond_w = QWidget(); bf = ParamForm()
        self.b_face   = make_spin(1, 1e9,  100.0, 1, 2)
        self.b_coupon = make_pct(0.05, 0, 0.5)
        self.b_expiry = make_spin(0.1, 100, 5.0, 0.5, 2, " yr")
        self.b_rate   = make_pct(0.04)
        self.b_freq   = make_combo(["1","2","4","12"], "2")
        bf.add_group("Bond Parameters", [
            FieldRow("Face value",     self.b_face),
            FieldRow("Coupon rate",    self.b_coupon),
            FieldRow("Maturity",       self.b_expiry),
            FieldRow("Discount rate",  self.b_rate),
            FieldRow("Freq / year",    self.b_freq),
        ])
        bvl = QVBoxLayout(bond_w); bvl.setContentsMargins(0,0,0,0); bvl.addWidget(bf)
        self.tabs.addTab(bond_w, "Bond")

        # ── IRS ──────────────────────────────────────────
        irs_w = QWidget(); irf = ParamForm()
        self.i_notional  = make_spin(1e3, 1e12, 1e7, 1e5, 0)
        self.i_fixed     = make_pct(0.04)
        self.i_expiry    = make_spin(0.1, 50, 5.0, 0.5, 2, " yr")
        self.i_rate      = make_pct(0.035)
        self.i_freq      = make_combo(["1","2","4","12"], "4")
        self.i_pay_fixed = make_combo(["Pay fixed", "Receive fixed"])
        irf.add_group("Swap Parameters", [
            FieldRow("Notional",       self.i_notional),
            FieldRow("Fixed rate",     self.i_fixed),
            FieldRow("Maturity",       self.i_expiry),
            FieldRow("Discount rate",  self.i_rate),
            FieldRow("Freq / year",    self.i_freq),
            FieldRow("Direction",      self.i_pay_fixed),
        ])
        ivl = QVBoxLayout(irs_w); ivl.setContentsMargins(0,0,0,0); ivl.addWidget(irf)
        self.tabs.addTab(irs_w, "IRS")

        # ── Cap/Floor ────────────────────────────────────
        cap_w = QWidget(); capf = ParamForm()
        self.c_notional = make_spin(1e3, 1e12, 1e7, 1e5, 0)
        self.c_strike   = make_pct(0.05)
        self.c_expiry   = make_spin(0.1, 50, 5.0, 0.5, 2, " yr")
        self.c_rate     = make_pct(0.04)
        self.c_vol      = make_pct(0.20, 0.001, 5.0)
        self.c_freq     = make_combo(["1","2","4","12"], "4")
        self.c_type     = make_combo(["Cap", "Floor", "Collar"])
        capf.add_group("Cap/Floor Parameters", [
            FieldRow("Notional",       self.c_notional),
            FieldRow("Strike rate",    self.c_strike),
            FieldRow("Maturity",       self.c_expiry),
            FieldRow("Discount rate",  self.c_rate),
            FieldRow("Swaption vol",   self.c_vol),
            FieldRow("Freq / year",    self.c_freq),
            FieldRow("Instrument",     self.c_type),
        ])
        cvl = QVBoxLayout(cap_w); cvl.setContentsMargins(0,0,0,0); cvl.addWidget(capf)
        self.tabs.addTab(cap_w, "Cap / Floor")

        # ── Swaption ─────────────────────────────────────
        sw_w = QWidget(); swf = ParamForm()
        self.s_notional = make_spin(1e3, 1e12, 1e7, 1e5, 0)
        self.s_strike   = make_pct(0.04)
        self.s_t_opt    = make_spin(0.1, 20, 1.0, 0.25, 2, " yr")
        self.s_t_swap   = make_spin(0.5, 50, 5.0, 0.5,  2, " yr")
        self.s_rate     = make_pct(0.035)
        self.s_vol      = make_pct(0.20, 0.001, 5.0)
        self.s_freq     = make_combo(["1","2","4","12"], "4")
        swf.add_group("Swaption Parameters", [
            FieldRow("Notional",       self.s_notional),
            FieldRow("Fixed strike",   self.s_strike),
            FieldRow("Option expiry",  self.s_t_opt),
            FieldRow("Swap tenor",     self.s_t_swap),
            FieldRow("Discount rate",  self.s_rate),
            FieldRow("Normal vol",     self.s_vol),
            FieldRow("Freq / year",    self.s_freq),
        ])
        svl = QVBoxLayout(sw_w); svl.setContentsMargins(0,0,0,0); svl.addWidget(swf)
        self.tabs.addTab(sw_w, "Swaption")

        ll.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout(); btn_row.setContentsMargins(24,8,24,16); btn_row.setSpacing(10)
        self.btn_calc  = QPushButton("Calculate"); self.btn_calc.setObjectName("calc_btn")
        self.btn_clear = QPushButton("Clear");     self.btn_clear.setObjectName("clear_btn")
        btn_row.addWidget(self.btn_calc); btn_row.addWidget(self.btn_clear)
        ll.addLayout(btn_row)
        self.btn_calc.clicked.connect(self.calculate)
        self.btn_clear.clicked.connect(self.clear)

        # Right
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        lbl = QLabel("RESULTS"); lbl.setObjectName("results_title"); rl.addWidget(lbl)
        self.grid = ResultsGrid(
            ["Price / NPV", "YTM / Fair Rate", "Mac Duration", "Mod Duration",
             "Convexity", "DV01", "Z-spread", "Annuity"], cols=3)
        rl.addWidget(self.grid)

        # Cashflow table
        self.cf_table = QTableWidget(0, 3)
        self.cf_table.setHorizontalHeaderLabels(["Time (yr)", "Cash Flow", "PV"])
        self.cf_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cf_table.setMaximumHeight(200)
        self.cf_table.setAlternatingRowColors(True)
        rl.addWidget(self.cf_table)

        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        splitter.addWidget(left); splitter.addWidget(right)
        splitter.setStretchFactor(0,0); splitter.setStretchFactor(1,1)
        root.addWidget(splitter)

    def calculate(self):
        self.banner.clear(); self.grid.clear_all()
        tab = self.tabs.currentIndex()
        try:
            if tab == 0:   self._calc_bond()
            elif tab == 1: self._calc_irs()
            elif tab == 2: self._calc_cap()
            elif tab == 3: self._calc_swaption()
        except Exception as e:
            self.banner.show_error(str(e))

    def _calc_bond(self):
        from instruments.fixed_income import fixed_bond, YieldCurve
        curve = YieldCurve.flat(self.b_rate.value()/100)
        res = fixed_bond(self.b_face.value(), self.b_coupon.value()/100,
                         self.b_expiry.value(), int(self.b_freq.currentText()), curve)
        self.grid.set("Price / NPV",    res["price"], color="#d97757")
        self.grid.set("YTM / Fair Rate",res["ytm"])
        self.grid.set("Mac Duration",   res["mac_duration"])
        self.grid.set("Mod Duration",   res["mod_duration"])
        self.grid.set("Convexity",      res["convexity"])
        self.grid.set("DV01",           res["dv01"])
        if res.get("zspread") == res.get("zspread"):
            self.grid.set("Z-spread", res.get("zspread", 0))

        # cashflow table
        cfs = res.get("cash_flows", [])
        self.cf_table.setRowCount(len(cfs))
        r = self.b_rate.value()/100
        for i, (t, cf) in enumerate(cfs):
            import math
            pv = cf * math.exp(-r*t)
            self.cf_table.setItem(i, 0, QTableWidgetItem(f"{t:.4f}"))
            self.cf_table.setItem(i, 1, QTableWidgetItem(f"{cf:.2f}"))
            self.cf_table.setItem(i, 2, QTableWidgetItem(f"{pv:.4f}"))

        # yield curve plot
        tenors = [0.25, 0.5, 1, 2, 3, 5, 7, 10]
        rates  = [self.b_rate.value()/100] * len(tenors)
        self.chart.plot_yield_curve(tenors, rates)

    def _calc_irs(self):
        from instruments.fixed_income import irs, YieldCurve
        curve = YieldCurve.flat(self.i_rate.value()/100)
        pay_fixed = self.i_pay_fixed.currentText() == "Pay fixed"
        res = irs(self.i_notional.value(), self.i_fixed.value()/100,
                  self.i_expiry.value(), int(self.i_freq.currentText()), curve, pay_fixed)
        self.grid.set("Price / NPV",    res["npv"], color="#d97757")
        self.grid.set("YTM / Fair Rate",res["fair_rate"])
        self.grid.set("DV01",           res["dv01"])
        self.grid.set("Annuity",        res["annuity"])

    def _calc_cap(self):
        from instruments.fixed_income import cap_floor, collar, YieldCurve
        curve = YieldCurve.flat(self.c_rate.value()/100)
        K = self.c_strike.value()/100
        vol = self.c_vol.value()/100
        t = self.c_type.currentText()
        if t == "Collar":
            res = collar(self.c_notional.value(), K*1.02, K*0.98,
                         self.c_expiry.value(), int(self.c_freq.currentText()), curve, vol)
            self.grid.set("Price / NPV", res["price"], color="#d97757")
        else:
            res = cap_floor(self.c_notional.value(), K, self.c_expiry.value(),
                            int(self.c_freq.currentText()), curve, vol, t.lower())
            self.grid.set("Price / NPV", res["price"], color="#d97757")

    def _calc_swaption(self):
        from instruments.fixed_income import swaption, YieldCurve
        curve = YieldCurve.flat(self.s_rate.value()/100)
        for opt in ["payer", "receiver"]:
            res = swaption(self.s_notional.value(), self.s_strike.value()/100,
                           self.s_t_opt.value(), self.s_t_swap.value(),
                           int(self.s_freq.currentText()), curve, self.s_vol.value()/100, opt)
            lbl = "Price / NPV" if opt=="payer" else "Annuity"
            self.grid.set(lbl, res["price"], color="#d97757")
            self.grid.set("YTM / Fair Rate", res["fwd_swap_rate"])
            self.grid.set("Annuity", res["annuity"])

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
        self.cf_table.setRowCount(0)
