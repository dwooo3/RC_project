"""Yield curve construction panel — Russia focus."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QTabWidget, QDoubleSpinBox
)
from PySide6.QtCore import Qt
from app.widgets import ParamForm, FieldRow, ResultsGrid, SectionHeader, Banner, make_spin, make_pct, make_combo
from app.chart import ChartWidget


OFZ_DEFAULTS = [
    (0.083, 15.5), (0.25, 15.2), (0.5, 14.8), (1.0, 14.5),
    (2.0, 13.8), (3.0, 13.3), (5.0, 12.7), (7.0, 12.3), (10.0, 12.0),
    (15.0, 11.8), (20.0, 11.7),
]


class YieldCurvePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._curve = None
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp = QSplitter(Qt.Horizontal); sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        # Left
        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(330); left.setMaximumWidth(420)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Yield Curves", "OFZ · RUONIA · Corporate  —  Bootstrap · Nelson-Siegel · Svensson"))
        self.banner = Banner(); ll.addWidget(self.banner)

        tabs = QTabWidget()

        # Tab 1: Input
        input_w = QWidget(); il = QVBoxLayout(input_w); il.setContentsMargins(8,8,8,8)
        self.method = make_combo(["Cubic spline (bootstrap)","Nelson-Siegel","Svensson"])
        il.addWidget(FieldRow("Fitting method", self.method))
        self.curve_type = make_combo(["OFZ G-curve","RUONIA OIS","Corporate 1st tier",
                                       "Corporate 2nd tier","Corporate HY","Custom"])
        il.addWidget(FieldRow("Curve type", self.curve_type))
        self.key_rate = make_pct(0.21, 0, 1)
        il.addWidget(FieldRow("CBR Key rate", self.key_rate))

        il.addWidget(QLabel("  Tenor / Rate table (edit rates in %):"))
        self.tbl = QTableWidget(len(OFZ_DEFAULTS), 2)
        self.tbl.setHorizontalHeaderLabels(["Tenor (yr)", "Rate (%)"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i, (T, r) in enumerate(OFZ_DEFAULTS):
            self.tbl.setItem(i, 0, QTableWidgetItem(str(T)))
            self.tbl.setItem(i, 1, QTableWidgetItem(str(r)))
        il.addWidget(self.tbl, 1)
        tabs.addTab(input_w, "Market Data")

        # Tab 2: Scenario
        sc_w = QWidget(); sl = QVBoxLayout(sc_w); sl.setContentsMargins(8,8,8,8)
        self.scenario = make_combo(["CBR rate hike +200bp","CBR rate hike +100bp",
                                    "CBR rate cut -100bp","CBR rate cut -200bp",
                                    "Steepener +50bp 10Y","Flattener -50bp 10Y",
                                    "2022 March shock","Geopolitical stress","Custom shift"])
        self.custom_shift = make_pct(0, -10, 10)
        sl.addWidget(FieldRow("Scenario", self.scenario))
        sl.addWidget(FieldRow("Custom shift (bps)", self.custom_shift))
        self.grid_sc = ResultsGrid(["Key rate","1Y rate","5Y rate","10Y rate","Slope (10Y-1Y)","Status"],
                                    cols=3, highlight="Key rate")
        sl.addWidget(self.grid_sc)
        sl.addStretch()
        tabs.addTab(sc_w, "Scenario")

        ll.addWidget(tabs, 1)

        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Build Curve"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr = QPushButton("Reset"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn, 1); bb.addWidget(self.clr); ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate); self.clr.clicked.connect(self.clear)

        # Right
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lb = QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(["1M rate","6M rate","1Y rate","2Y rate","5Y rate","10Y rate",
                                  "DV01 (1M)","DV01 (5Y)","DV01 (10Y)","Curve slope","RMSE","Method"],
                                 cols=3, highlight="1Y rate")
        rl.addWidget(self.grid)

        self.out_tbl = QTableWidget(0, 5)
        self.out_tbl.setHorizontalHeaderLabels(["Tenor","Zero rate","Fwd rate","Par rate","Discount"])
        self.out_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.out_tbl.setMaximumHeight(220); self.out_tbl.setAlternatingRowColors(True)
        rl.addWidget(self.out_tbl)
        self.chart = ChartWidget(); self.chart.clear(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,920])
        root.addWidget(sp)

    def _read_table(self):
        tenors = []; rates = []
        for i in range(self.tbl.rowCount()):
            ti = self.tbl.item(i,0); ri = self.tbl.item(i,1)
            if ti and ri and ti.text().strip() and ri.text().strip():
                try:
                    tenors.append(float(ti.text())); rates.append(float(ri.text())/100)
                except ValueError:
                    pass
        return tenors, rates

    def calculate(self):
        self.banner.clear()
        tenors, rates = self._read_table()
        if len(tenors) < 2:
            self.banner.show_error("Need at least 2 tenor/rate pairs"); return
        try:
            from curves.yield_curve import YieldCurve, NSCurve, SvenssonCurve
            method = self.method.currentText()
            if "Nelson" in method:
                curve = NSCurve.fit(tenors, rates, label="OFZ NS")
                rmse = getattr(curve, "rmse", 0)
            elif "Svensson" in method:
                curve = SvenssonCurve.fit(tenors, rates, label="OFZ SV")
                rmse = getattr(curve, "rmse", 0)
            else:
                curve = YieldCurve(tenors, rates, label="OFZ Bootstrap", interp="cubic")
                rmse = 0.0
            self._curve = curve

            disp_tenors = [0.083, 0.5, 1, 2, 5, 10, 15, 20]
            self.grid.set("1M rate",  curve.rate(0.083), sub=f"{curve.rate(0.083)*100:.2f}%")
            self.grid.set("6M rate",  curve.rate(0.5),   sub=f"{curve.rate(0.5)*100:.2f}%")
            self.grid.set("1Y rate",  curve.rate(1.0),   color="#d97757", sub=f"{curve.rate(1.0)*100:.2f}%")
            self.grid.set("2Y rate",  curve.rate(2.0),   sub=f"{curve.rate(2.0)*100:.2f}%")
            self.grid.set("5Y rate",  curve.rate(5.0),   sub=f"{curve.rate(5.0)*100:.2f}%")
            self.grid.set("10Y rate", curve.rate(10.0),  sub=f"{curve.rate(10.0)*100:.2f}%")
            self.grid.set("DV01 (1M)", curve.dv01(0.083, 1e6))
            self.grid.set("DV01 (5Y)", curve.dv01(5.0, 1e6))
            self.grid.set("DV01 (10Y)",curve.dv01(10.0, 1e6))
            slope = curve.rate(10.0) - curve.rate(1.0)
            self.grid.set("Curve slope", slope, sub=f"{slope*100:.0f}bps 10Y-1Y")
            self.grid.set("RMSE", rmse, sub=f"{rmse*10000:.1f}bps" if rmse else "exact")
            self.grid.set("Method", method[:12])

            # Output table
            out_tenors = [0.083, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20]
            self.out_tbl.setRowCount(len(out_tenors))
            for i, T in enumerate(out_tenors):
                z = curve.rate(T); f = curve.forward_rate(T, T+0.5)
                p = curve.par_rate(T); d = curve.discount(T)
                for j, v in enumerate([f"{T:.3f}", f"{z*100:.3f}%", f"{f*100:.3f}%",
                                        f"{p*100:.3f}%", f"{d:.6f}"]):
                    self.out_tbl.setItem(i, j, QTableWidgetItem(v))

            # Chart: zero, par, fwd curves
            t_plot = np.linspace(0.1, 20, 100)
            zeros  = [curve.rate(T)*100 for T in t_plot]
            pars   = [curve.par_rate(T)*100 for T in t_plot]
            fwds   = [curve.forward_rate(T, T+0.5)*100 for T in t_plot]
            ax = self.chart._reset()
            ax.plot(t_plot, zeros, color="#d97757", lw=2, label="Zero curve")
            ax.plot(t_plot, pars,  color="#30d158", lw=2, ls="--", label="Par curve")
            ax.plot(t_plot, fwds,  color="#ff9f0a", lw=1.5, ls=":", label="Fwd 6M")
            ax.scatter(tenors, [r*100 for r in rates], color="#ff3b30", zorder=5,
                       s=40, label="Market quotes", marker="o")
            ax.axhline(self.key_rate.value(), color="#bf5af2", lw=1, ls="--",
                       label=f"CBR Key rate {self.key_rate.value():.1f}%")
            ax.legend(fontsize=8)
            self.chart._finish(ax, "Yield Curve", "Maturity (years)", "Rate (%)")

        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self._curve = None
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
        self.out_tbl.setRowCount(0)
