"""FX Instruments panel."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm, FieldRow, ResultsGrid, SectionHeader, Banner, make_spin, make_pct, make_combo
from app.chart import ChartWidget


class FXPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(340); left.setMaximumWidth(420)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("FX Instruments",
            "Forward · Option · Barrier · Risk Reversal · Straddle"))
        self.banner = Banner(); ll.addWidget(self.banner)

        form = ParamForm()
        self.spot    = make_spin(0.0001, 1e5, 1.08, 0.001, 5)
        self.strike  = make_spin(0.0001, 1e5, 1.09, 0.001, 5)
        self.expiry  = make_spin(0.001,  50,  0.25, 0.01, 4, " yr")
        self.r_d     = make_pct(0.04, -1, 1)
        self.r_f     = make_pct(0.02, -1, 1)
        self.sigma   = make_pct(0.08, 0.001, 5.0)
        self.notional= make_spin(1e3, 1e12, 1e6, 1e4, 0)
        self.opt     = make_combo(["Call", "Put"])
        self.barrier = make_spin(0.0001, 1e5, 1.05, 0.001, 5)
        self.btype   = make_combo(["down-out","down-in","up-out","up-in"])
        self.product = make_combo(["FX Forward", "FX Option (GK)", "FX Barrier",
                                   "Risk Reversal", "Straddle", "Strangle"])

        form.add_group("Market Parameters", [
            FieldRow("Spot (S)",         self.spot,     "Current FX spot rate"),
            FieldRow("Strike (K)",        self.strike,   "Option strike"),
            FieldRow("Expiry (T)",        self.expiry),
            FieldRow("Dom. rate (r_d)",   self.r_d,     "Domestic interest rate"),
            FieldRow("For. rate (r_f)",   self.r_f,     "Foreign interest rate"),
            FieldRow("Volatility (σ)",    self.sigma),
            FieldRow("Notional",          self.notional),
        ])
        form.add_group("Instrument", [
            FieldRow("Product",       self.product),
            FieldRow("Option type",   self.opt),
            FieldRow("Barrier level", self.barrier),
            FieldRow("Barrier type",  self.btype),
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
        hdr = QWidget(); hdr.setObjectName("results_header")
        hl  = QHBoxLayout(hdr); hl.setContentsMargins(16,9,16,9)
        lbl = QLabel("RESULTS"); lbl.setObjectName("results_title_lbl")
        hl.addWidget(lbl); rl.addWidget(hdr)
        self.grid = ResultsGrid(
            ["Price", "Fwd / Premium Dom.", "Delta Spot", "Delta Fwd",
             "Delta Prem-Adj.", "Gamma", "Vega", "Vanna", "Volga",
             "Swap Points", "Theta", "Rho"], cols=3)
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        splitter.addWidget(left); splitter.addWidget(right)
        splitter.setStretchFactor(0,0); splitter.setStretchFactor(1,1)
        root.addWidget(splitter)

    def calculate(self):
        self.banner.clear(); self.grid.clear_all()
        S=self.spot.value(); K=self.strike.value(); T=self.expiry.value()
        r_d=self.r_d.value()/100; r_f=self.r_f.value()/100
        sig=self.sigma.value()/100; N=self.notional.value()
        opt=self.opt.currentText().lower()
        prod = self.product.currentText()

        try:
            if prod == "FX Forward":
                from instruments.fx import fx_forward
                res = fx_forward(S, r_d, r_f, T, N)
                fwd = res["forward"]
                self.grid.set("Fwd / Premium Dom.", fwd, color="#d97757")
                self.grid.set("Swap Points", res["swap_points"])
                # Show forward rate vs tenor (1m–2y), no fake smile
                tenors = np.linspace(1/12, 2, 24)
                fwds   = [S * np.exp((r_d - r_f) * t) for t in tenors]
                self.chart.plot_payoff(tenors, fwds, "FX Forward Curve",
                                       S=T, barriers=None)
                self.chart._finish(self.chart.ax, "FX Forward vs Tenor",
                                   "Tenor (years)", f"Forward Rate")

            elif prod == "FX Option (GK)":
                from instruments.fx import fx_option
                res = fx_option(S, K, T, r_d, r_f, sig, N, opt)
                self.grid.set("Price",             res["price"], color="#d97757")
                self.grid.set("Fwd / Premium Dom.",res["premium_domestic"])
                self.grid.set("Delta Spot",        res["delta_spot"])
                self.grid.set("Delta Fwd",         res["delta_fwd"])
                self.grid.set("Delta Prem-Adj.",   res["delta_premium_adj"])
                self.grid.set("Gamma",             res["gamma"])
                self.grid.set("Vega",              res["vega"])
                self.grid.set("Vanna",             res["vanna"])
                self.grid.set("Volga",             res["volga"])
                self.grid.set("Theta",             res["theta"])
                # payoff diagram
                spots = np.linspace(S*0.7, S*1.3, 200)
                payoffs = [max(s-K,0)*N if opt=="call" else max(K-s,0)*N for s in spots]
                self.chart.plot_payoff(spots, payoffs, "FX Option Payoff", S, [K])

            elif prod == "FX Barrier":
                from instruments.fx import fx_barrier
                res = fx_barrier(S, K, self.barrier.value(), T, r_d, r_f, sig, opt,
                                 self.btype.currentText(), notional=N)
                self.grid.set("Price", res["price"], color="#d97757")
                self.grid.set("Fwd / Premium Dom.", res["premium_domestic"])

            elif prod in ("Risk Reversal", "Strangle", "Straddle"):
                from instruments.fx import risk_reversal, strangle, straddle
                K_call = K * 1.02; K_put = K * 0.98
                if prod == "Risk Reversal":
                    res = risk_reversal(S, K_call, K_put, T, r_d, r_f, sig, sig, N)
                elif prod == "Strangle":
                    res = strangle(S, K_call, K_put, T, r_d, r_f, sig, sig, N)
                else:
                    res = straddle(S, K, T, r_d, r_f, sig, N)
                self.grid.set("Price",      res["price"], color="#d97757")
                self.grid.set("Delta Spot", res["delta"])
                self.grid.set("Vega",       res["vega"])

        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
