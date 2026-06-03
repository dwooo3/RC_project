"""Barrier options panel."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm, FieldRow, ResultsGrid, SectionHeader, Banner, make_spin, make_pct, make_combo
from app.chart import ChartWidget


class BarrierPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal)

        # Left
        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(340); left.setMaximumWidth(420)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Barrier Options",
                 "Single / Double · Knock-In / Knock-Out · Exact & MC",
                 status=ModelStatus.PROTOTYPE))
        self.banner = Banner(); ll.addWidget(self.banner)

        form = ParamForm()
        self.spot    = make_spin(0.01, 1e7, 100.0, 1.0, 4)
        self.strike  = make_spin(0.01, 1e7, 100.0, 1.0, 4)
        self.barrier = make_spin(0.01, 1e7,  85.0, 1.0, 4)
        self.lower   = make_spin(0.01, 1e7,  80.0, 1.0, 4)
        self.upper   = make_spin(0.01, 1e7, 120.0, 1.0, 4)
        self.expiry  = make_spin(0.001, 50, 0.25, 0.01, 4, " yr")
        self.rate    = make_pct(0.05)
        self.sigma   = make_pct(0.20, 0.001, 10.0)
        self.div     = make_pct(0.00)
        self.rebate  = make_spin(0.0, 1e6, 0.0, 0.1, 4)
        self.opt     = make_combo(["Call", "Put"])
        self.btype   = make_combo(["down-out", "down-in", "up-out", "up-in"])
        self.style   = make_combo(["Single barrier", "Double barrier"])
        self.method  = make_combo(["Closed-form", "Monte Carlo"])

        form.add_group("Market Parameters", [
            FieldRow("Spot (S)",       self.spot),
            FieldRow("Strike (K)",     self.strike),
            FieldRow("Expiry (T)",     self.expiry),
            FieldRow("Risk-free rate", self.rate),
            FieldRow("Volatility (σ)", self.sigma),
            FieldRow("Dividend (q)",   self.div),
        ])
        form.add_group("Barrier Settings", [
            FieldRow("Option type",    self.opt),
            FieldRow("Barrier type",   self.btype),
            FieldRow("Style",          self.style),
            FieldRow("Single barrier", self.barrier),
            FieldRow("Lower barrier",  self.lower, "For double barrier"),
            FieldRow("Upper barrier",  self.upper, "For double barrier"),
            FieldRow("Rebate",         self.rebate, "Paid if knocked out"),
            FieldRow("Pricing method", self.method),
        ])
        ll.addWidget(form, 1)

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
        self.grid = ResultsGrid(["Price", "Vanilla", "Barrier", "Rebate", "MC StdErr"], cols=3)
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        splitter.addWidget(left); splitter.addWidget(right)
        splitter.setStretchFactor(0,0); splitter.setStretchFactor(1,1)
        root.addWidget(splitter)

    def calculate(self):
        self.banner.clear()
        p = dict(S=self.spot.value(), K=self.strike.value(), H=self.barrier.value(),
                 T=self.expiry.value(), r=self.rate.value()/100, sigma=self.sigma.value()/100,
                 q=self.div.value()/100, opt=self.opt.currentText().lower(),
                 barrier_type=self.btype.currentText(), rebate=self.rebate.value())
        try:
            if self.style.currentText() == "Double barrier":
                from instruments.barrier import double_barrier_ko
                res = double_barrier_ko(p["S"], p["K"], self.lower.value(), self.upper.value(),
                                        p["T"], p["r"], p["sigma"], p["q"], p["opt"])
                self.grid.set("Price", res["price"], color="#d97757")
                self.grid.set("Barrier", f"{self.lower.value():.2f} / {self.upper.value():.2f}")
            elif self.method.currentText() == "Monte Carlo":
                from instruments.barrier import barrier_mc
                res = barrier_mc(**p, n_sims=50_000)
                self.grid.set("Price",    res["price"],  color="#d97757")
                self.grid.set("MC StdErr",res["stderr"])
            else:
                from instruments.barrier import single_barrier
                res = single_barrier(**p)
                self.grid.set("Price",   res["price"],   color="#d97757")
                self.grid.set("Vanilla", res["vanilla"])
                self.grid.set("Rebate",  res["rebate"])

            # payoff chart
            spots = np.linspace(p["S"]*0.5, p["S"]*1.5, 300)
            payoffs = []
            for s in spots:
                if p["opt"] == "call":
                    pf = max(s - p["K"], 0)
                else:
                    pf = max(p["K"] - s, 0)
                if "out" in self.btype.currentText():
                    if "down" in self.btype.currentText() and s <= p["H"]: pf = p["rebate"]
                    elif "up" in self.btype.currentText()   and s >= p["H"]: pf = p["rebate"]
                payoffs.append(pf)
            barriers = [p["H"]] if self.style.currentText() == "Single barrier" else [self.lower.value(), self.upper.value()]
            self.chart.plot_payoff(spots, payoffs, "Barrier payoff", p["S"], barriers)
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
