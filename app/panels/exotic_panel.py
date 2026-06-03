"""Exotic, Asian, Digital, Lookback options panel."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSplitter, QTabWidget
)
from PySide6.QtCore import Qt
from app.widgets import ParamForm, FieldRow, ResultsGrid, SectionHeader, Banner, make_spin, make_pct, make_combo
from app.chart import ChartWidget


def _base_fields():
    spot   = make_spin(0.01, 1e7, 100.0, 1.0, 4)
    strike = make_spin(0.01, 1e7, 100.0, 1.0, 4)
    expiry = make_spin(0.001, 50, 0.5, 0.01, 4, " yr")
    rate   = make_pct(0.05)
    sigma  = make_pct(0.20, 0.001, 10.0)
    div    = make_pct(0.00)
    opt    = make_combo(["Call", "Put"])
    return spot, strike, expiry, rate, sigma, div, opt


class ExoticPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(340); left.setMaximumWidth(420)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Exotic Options",
            "Asian · Digital · Lookback · Chooser · Cliquet · Compound"))
        self.banner = Banner(); ll.addWidget(self.banner)

        self.tabs = QTabWidget()

        # ── Asian ─────────────────────────────────────────
        aw = QWidget(); af = ParamForm()
        self.a_spot, self.a_strike, self.a_expiry, self.a_rate, self.a_sigma, self.a_div, self.a_opt = _base_fields()
        self.a_fixings = make_spin(1, 365, 12, 1, 0)
        self.a_style   = make_combo(["Arithmetic (MC)", "Geometric (exact)"])
        self.a_avg     = make_combo(["Fixed strike", "Floating strike"])
        self.a_sims    = make_spin(1000, 500000, 50000, 5000, 0)
        af.add_group("Asian Option", [
            FieldRow("Spot",      self.a_spot),
            FieldRow("Strike",    self.a_strike),
            FieldRow("Expiry",    self.a_expiry),
            FieldRow("Rate",      self.a_rate),
            FieldRow("Vol",       self.a_sigma),
            FieldRow("Dividend",  self.a_div),
            FieldRow("Type",      self.a_opt),
            FieldRow("Fixings",   self.a_fixings),
            FieldRow("Averaging", self.a_style),
            FieldRow("Strike type",self.a_avg),
            FieldRow("Simulations",self.a_sims),
        ])
        avl = QVBoxLayout(aw); avl.setContentsMargins(0,0,0,0); avl.addWidget(af)
        self.tabs.addTab(aw, "Asian")

        # ── Digital ───────────────────────────────────────
        dw = QWidget(); df = ParamForm()
        self.d_spot, self.d_strike, self.d_expiry, self.d_rate, self.d_sigma, self.d_div, self.d_opt = _base_fields()
        self.d_type    = make_combo(["Cash-or-Nothing", "Asset-or-Nothing",
                                     "One-Touch", "No-Touch", "Double No-Touch"])
        self.d_cash    = make_spin(0, 1e9, 1.0, 0.1, 4)
        self.d_barrier = make_spin(0.01, 1e7, 110.0, 1, 4)
        self.d_lower   = make_spin(0.01, 1e7,  90.0, 1, 4)
        self.d_upper   = make_spin(0.01, 1e7, 110.0, 1, 4)
        self.d_dir     = make_combo(["Up", "Down"])
        df.add_group("Digital Option", [
            FieldRow("Spot",           self.d_spot),
            FieldRow("Strike / Level", self.d_strike),
            FieldRow("Expiry",         self.d_expiry),
            FieldRow("Rate",           self.d_rate),
            FieldRow("Vol",            self.d_sigma),
            FieldRow("Type",           self.d_opt),
            FieldRow("Digital type",   self.d_type),
            FieldRow("Cash amount",    self.d_cash),
            FieldRow("Barrier",        self.d_barrier),
            FieldRow("Lower",          self.d_lower, "For double no-touch"),
            FieldRow("Upper",          self.d_upper, "For double no-touch"),
            FieldRow("Direction",      self.d_dir,   "For one-touch/no-touch"),
        ])
        dvl = QVBoxLayout(dw); dvl.setContentsMargins(0,0,0,0); dvl.addWidget(df)
        self.tabs.addTab(dw, "Digital")

        # ── Lookback ──────────────────────────────────────
        lw = QWidget(); lf = ParamForm()
        self.l_spot, self.l_strike, self.l_expiry, self.l_rate, self.l_sigma, self.l_div, self.l_opt = _base_fields()
        self.l_style = make_combo(["Floating strike", "Fixed strike"])
        lf.add_group("Lookback Option", [
            FieldRow("Spot",      self.l_spot),
            FieldRow("Strike",    self.l_strike, "Used for fixed-strike only"),
            FieldRow("Expiry",    self.l_expiry),
            FieldRow("Rate",      self.l_rate),
            FieldRow("Vol",       self.l_sigma),
            FieldRow("Dividend",  self.l_div),
            FieldRow("Type",      self.l_opt),
            FieldRow("Style",     self.l_style),
        ])
        lvl = QVBoxLayout(lw); lvl.setContentsMargins(0,0,0,0); lvl.addWidget(lf)
        self.tabs.addTab(lw, "Lookback")

        # ── Chooser / Cliquet / Compound ──────────────────
        ew = QWidget(); ef = ParamForm()
        self.e_spot, self.e_strike, self.e_expiry, self.e_rate, self.e_sigma, self.e_div, self.e_opt = _base_fields()
        self.e_type     = make_combo(["Simple Chooser", "Cliquet", "Forward-Start",
                                      "Compound (call-on-call)", "Variance Swap"])
        self.e_t_choose = make_spin(0.001, 50, 0.25, 0.01, 4, " yr")
        self.e_alpha    = make_pct(1.0, 0.01, 3.0)
        self.e_k_outer  = make_spin(0.01, 1e6, 3.0, 0.1, 4)
        ef.add_group("Exotic Option", [
            FieldRow("Spot",         self.e_spot),
            FieldRow("Strike",       self.e_strike),
            FieldRow("Expiry",       self.e_expiry),
            FieldRow("Rate",         self.e_rate),
            FieldRow("Vol",          self.e_sigma),
            FieldRow("Type",         self.e_type),
            FieldRow("Choose time",  self.e_t_choose, "Chooser: time to choose"),
            FieldRow("α (Fwd-start)",self.e_alpha,    "Forward-start moneyness"),
            FieldRow("K outer (comp)",self.e_k_outer, "Compound: outer strike"),
        ])
        evl = QVBoxLayout(ew); evl.setContentsMargins(0,0,0,0); evl.addWidget(ef)
        self.tabs.addTab(ew, "Chooser / Exotic")

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
            ["Price", "Std Error", "Vanilla (BSM)", "Discount", "Fixings / Periods", "Model"], cols=3)
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        splitter.addWidget(left); splitter.addWidget(right)
        splitter.setStretchFactor(0,0); splitter.setStretchFactor(1,1)
        root.addWidget(splitter)

    def _vanilla(self, S, K, T, r, sigma, q, opt):
        from models.black_scholes import bsm
        return bsm(S, K, T, r, sigma, q, opt).price

    def calculate(self):
        self.banner.clear(); self.grid.clear_all()
        tab = self.tabs.currentIndex()
        try:
            if tab == 0:   self._calc_asian()
            elif tab == 1: self._calc_digital()
            elif tab == 2: self._calc_lookback()
            elif tab == 3: self._calc_exotic()
        except Exception as e:
            self.banner.show_error(str(e))

    def _calc_asian(self):
        S=self.a_spot.value(); K=self.a_strike.value(); T=self.a_expiry.value()
        r=self.a_rate.value()/100; sig=self.a_sigma.value()/100
        q=self.a_div.value()/100; opt=self.a_opt.currentText().lower()
        avg = "fixed" if "Fixed" in self.a_avg.currentText() else "floating"
        n_sims = int(self.a_sims.value())
        n = int(self.a_fixings.value())

        if "Geometric" in self.a_style.currentText():
            from instruments.asian import geometric_asian_discrete
            res = geometric_asian_discrete(S, K, T, r, sig, q, n, opt)
        else:
            from instruments.asian import arithmetic_asian
            res = arithmetic_asian(S, K, T, r, sig, q, n, opt, n_sims=n_sims, averaging=avg)

        self.grid.set("Price",     res["price"],  color="#d97757")
        self.grid.set("Std Error", res.get("stderr", 0))
        self.grid.set("Vanilla (BSM)", self._vanilla(S,K,T,r,sig,q,opt))
        self.grid.set("Fixings / Periods", n)
        self.grid.set("Model", res.get("model","—"))

        # payoff chart
        spots = np.linspace(S*0.6, S*1.4, 200)
        payoffs = [max(s-K,0) if opt=="call" else max(K-s,0) for s in spots]
        self.chart.plot_payoff(spots, payoffs, "Asian payoff (avg≈S_T)", S)

    def _calc_digital(self):
        S=self.d_spot.value(); K=self.d_strike.value(); T=self.d_expiry.value()
        r=self.d_rate.value()/100; sig=self.d_sigma.value()/100
        q=self.d_div.value()/100; opt=self.d_opt.currentText().lower()
        dt = self.d_type.currentText()

        if dt == "Cash-or-Nothing":
            from instruments.digital import cash_or_nothing
            res = cash_or_nothing(S, K, T, r, sig, q, opt, self.d_cash.value())
        elif dt == "Asset-or-Nothing":
            from instruments.digital import asset_or_nothing
            res = asset_or_nothing(S, K, T, r, sig, q, opt)
        elif dt == "One-Touch":
            from instruments.digital import one_touch
            res = one_touch(S, self.d_barrier.value(), T, r, sig, q,
                            self.d_dir.currentText().lower(), "expiry", self.d_cash.value())
        elif dt == "No-Touch":
            from instruments.digital import no_touch
            res = no_touch(S, self.d_barrier.value(), T, r, sig, q,
                           self.d_dir.currentText().lower(), self.d_cash.value())
        else:
            from instruments.digital import double_no_touch
            res = double_no_touch(S, self.d_lower.value(), self.d_upper.value(),
                                  T, r, sig, q, self.d_cash.value())
        self.grid.set("Price", res["price"], color="#d97757")

        # payoff chart
        spots = np.linspace(S*0.6, S*1.4, 300)
        if "Cash" in dt:
            payoffs = [self.d_cash.value() if (s>K if opt=="call" else s<K) else 0 for s in spots]
        elif "Asset" in dt:
            payoffs = [s if (s>K if opt=="call" else s<K) else 0 for s in spots]
        else:
            payoffs = [self.d_cash.value() if self.d_lower.value()<s<self.d_upper.value() else 0 for s in spots]
        bars = [self.d_barrier.value()] if "Touch" in dt and "Double" not in dt else []
        self.chart.plot_payoff(spots, payoffs, dt, S, bars)

    def _calc_lookback(self):
        S=self.l_spot.value(); K=self.l_strike.value(); T=self.l_expiry.value()
        r=self.l_rate.value()/100; sig=self.l_sigma.value()/100
        q=self.l_div.value()/100; opt=self.l_opt.currentText().lower()
        style = "floating" if "Float" in self.l_style.currentText() else "fixed"

        if style == "floating":
            from instruments.lookback import floating_lookback
            res = floating_lookback(S, T, r, sig, q, opt)
        else:
            from instruments.lookback import fixed_lookback
            res = fixed_lookback(S, K, T, r, sig, q, opt)

        self.grid.set("Price",         res["price"], color="#d97757")
        self.grid.set("Vanilla (BSM)", self._vanilla(S,K,T,r,sig,q,opt))

        spots = np.linspace(S*0.6, S*1.4, 200)
        if style=="floating":
            # Floating call pays S_T - S_min → lower bound is S_T - S_min ≥ 0
            payoffs = [max(s-S*0.8, 0) for s in spots]  # illustrative
        else:
            payoffs = [max(s-K,0) if opt=="call" else max(K-s,0) for s in spots]
        self.chart.plot_payoff(spots, payoffs, f"Lookback {style}", S)

    def _calc_exotic(self):
        S=self.e_spot.value(); K=self.e_strike.value(); T=self.e_expiry.value()
        r=self.e_rate.value()/100; sig=self.e_sigma.value()/100
        etype = self.e_type.currentText()

        if etype == "Simple Chooser":
            from instruments.exotic import simple_chooser
            res = simple_chooser(S, K, self.e_t_choose.value(), T, r, sig)
        elif etype == "Cliquet":
            from instruments.exotic import cliquet
            res = cliquet(S, T, r, sig, n_sims=30_000)
        elif etype == "Forward-Start":
            from instruments.exotic import forward_start
            alpha = self.e_alpha.value() / 100
            res = forward_start(S, alpha, self.e_t_choose.value(), T, r, sig)
        elif "Compound" in etype:
            from instruments.exotic import compound_option
            res = compound_option(S, self.e_k_outer.value(), K, self.e_t_choose.value(), T, r, sig)
        else:  # Variance Swap
            from instruments.variance_swaps import vol_swap_mc
            res = vol_swap_mc(S, r, 0, sig, T, n_sims=30_000)

        self.grid.set("Price", res.get("price") or res.get("vol_strike"), color="#d97757")
        if "stderr" in res:
            self.grid.set("Std Error", res["stderr"])
        self.chart.clear()

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
