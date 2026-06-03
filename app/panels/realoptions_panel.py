"""Real Options panel (Hull Ch. 36): Expand, Abandon, Defer, Switch, Staged investment."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from scipy.stats import norm
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSplitter, QTabWidget
)
from PySide6.QtCore import Qt
from app.widgets import (ParamForm, FieldRow, ResultsGrid, SectionHeader,
                         Banner, make_spin, make_pct, make_combo)
from app.chart import ChartWidget


def _bs_call(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return max(S-K, 0)
    d1 = (np.log(S/K) + (r+0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)

def _bs_put(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return max(K-S, 0)
    d1 = (np.log(S/K) + (r+0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)


class RealOptionsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp = QSplitter(Qt.Horizontal); sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(340); left.setMaximumWidth(430)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Real Options",
            "Defer · Expand · Abandon · Switch · Staged · Growth"))
        self.banner = Banner(); ll.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane{border:none;}")

        # ── Option to Defer ─────────────────────────────────
        df_w = QWidget(); df_f = ParamForm()
        self.df_V    = make_spin(0, 1e12, 100e6, 1e6, 0)
        self.df_I    = make_spin(0, 1e12, 110e6, 1e6, 0)
        self.df_r    = make_pct(0.10)
        self.df_sigma = make_pct(0.25, 0.01, 3)
        self.df_T    = make_spin(0.01, 20, 3, 0.5, 2, "yr")
        self.df_q    = make_pct(0.05, 0, 1)
        df_f.add_group("Option to Defer (=Call Option)", [
            FieldRow("Project NPV V",      self.df_V),
            FieldRow("Investment cost I",  self.df_I),
            FieldRow("Risk-free r",        self.df_r),
            FieldRow("Project vol σ",      self.df_sigma),
            FieldRow("Deferral period T",  self.df_T),
            FieldRow("Dividend yield q",   self.df_q),
        ])
        dfvl = QVBoxLayout(df_w); dfvl.setContentsMargins(0,0,0,0); dfvl.addWidget(df_f)
        self.tabs.addTab(df_w, "Defer")

        # ── Option to Expand ────────────────────────────────
        ex_w = QWidget(); exf = ParamForm()
        self.ex_V    = make_spin(0, 1e12, 100e6, 1e6, 0)
        self.ex_CE   = make_spin(0, 1e12, 30e6, 1e6, 0)
        self.ex_x    = make_pct(0.30, 0, 5)
        self.ex_r    = make_pct(0.10)
        self.ex_sigma = make_pct(0.25, 0.01, 3)
        self.ex_T    = make_spin(0.01, 20, 3, 0.5, 2, "yr")
        exf.add_group("Option to Expand (=Call on V*x)", [
            FieldRow("Base NPV V",          self.ex_V),
            FieldRow("Expansion cost C_E",  self.ex_CE),
            FieldRow("Expansion factor x",  self.ex_x),
            FieldRow("Risk-free r",         self.ex_r),
            FieldRow("Project vol σ",       self.ex_sigma),
            FieldRow("Decision horizon T",  self.ex_T),
        ])
        exvl = QVBoxLayout(ex_w); exvl.setContentsMargins(0,0,0,0); exvl.addWidget(exf)
        self.tabs.addTab(ex_w, "Expand")

        # ── Option to Abandon ───────────────────────────────
        ab_w = QWidget(); abf = ParamForm()
        self.ab_V    = make_spin(0, 1e12, 100e6, 1e6, 0)
        self.ab_SA   = make_spin(0, 1e12, 60e6, 1e6, 0)
        self.ab_r    = make_pct(0.10)
        self.ab_sigma = make_pct(0.25, 0.01, 3)
        self.ab_T    = make_spin(0.01, 20, 5, 0.5, 2, "yr")
        abf.add_group("Option to Abandon (=Put Option)", [
            FieldRow("Project NPV V",      self.ab_V),
            FieldRow("Salvage value S_A",  self.ab_SA),
            FieldRow("Risk-free r",        self.ab_r),
            FieldRow("Project vol σ",      self.ab_sigma),
            FieldRow("Time to abandon T",  self.ab_T),
        ])
        abvl = QVBoxLayout(ab_w); abvl.setContentsMargins(0,0,0,0); abvl.addWidget(abf)
        self.tabs.addTab(ab_w, "Abandon")

        # ── Staged Investment ────────────────────────────────
        st_w = QWidget(); stf = ParamForm()
        self.st_V    = make_spin(0, 1e12, 100e6, 1e6, 0)
        self.st_I1   = make_spin(0, 1e12, 20e6, 1e6, 0)
        self.st_I2   = make_spin(0, 1e12, 90e6, 1e6, 0)
        self.st_T1   = make_spin(0.01, 20, 1, 0.5, 2, "yr")
        self.st_T2   = make_spin(0.01, 20, 3, 0.5, 2, "yr")
        self.st_r    = make_pct(0.10)
        self.st_sigma = make_pct(0.30, 0.01, 3)
        stf.add_group("Staged Investment (Compound Option)", [
            FieldRow("Final project NPV V",   self.st_V),
            FieldRow("Phase 1 invest. I₁",    self.st_I1),
            FieldRow("Phase 2 invest. I₂",    self.st_I2),
            FieldRow("Decision T₁ (phase 1)", self.st_T1),
            FieldRow("Launch T₂ (phase 2)",   self.st_T2),
            FieldRow("Risk-free r",            self.st_r),
            FieldRow("Project vol σ",          self.st_sigma),
        ])
        stvl = QVBoxLayout(st_w); stvl.setContentsMargins(0,0,0,0); stvl.addWidget(stf)
        self.tabs.addTab(st_w, "Staged/Compound")

        # ── Switch Option ────────────────────────────────────
        sw_w = QWidget(); swf = ParamForm()
        self.sw_V1    = make_spin(0, 1e12, 100e6, 1e6, 0)
        self.sw_V2    = make_spin(0, 1e12, 90e6, 1e6, 0)
        self.sw_SC    = make_spin(0, 1e12, 5e6, 1e6, 0)
        self.sw_r     = make_pct(0.10)
        self.sw_sigma = make_pct(0.25, 0.01, 3)
        self.sw_T     = make_spin(0.01, 20, 5, 0.5, 2, "yr")
        swf.add_group("Option to Switch (= Exchange Option)", [
            FieldRow("Asset V₁ (current mode)", self.sw_V1),
            FieldRow("Asset V₂ (alt mode)",     self.sw_V2),
            FieldRow("Switch cost C_S",          self.sw_SC),
            FieldRow("Risk-free r",              self.sw_r),
            FieldRow("Vol σ",                    self.sw_sigma),
            FieldRow("Horizon T",                self.sw_T),
        ])
        swvl = QVBoxLayout(sw_w); swvl.setContentsMargins(0,0,0,0); swvl.addWidget(swf)
        self.tabs.addTab(sw_w, "Switch")

        ll.addWidget(self.tabs, 1)
        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Value Real Option"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr = QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn, 1); bb.addWidget(self.clr)
        ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate)
        self.clr.clicked.connect(self.clear)

        # Right
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl2 = QHBoxLayout(hdr)
        hl2.setContentsMargins(18,10,18,10)
        lb = QLabel("REAL OPTION VALUE"); lb.setObjectName("results_title_lbl")
        hl2.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["Option Value", "Static NPV", "Strategic NPV", "Option Premium",
             "Delta", "d1", "d2", "Exercise Prob",
             "Break-even V", "Time Value", "Intrinsic Value", "ROV/NPV ratio"],
            cols=4, highlight="Strategic NPV")
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            tab = self.tabs.tabText(self.tabs.currentIndex())
            if tab == "Defer":
                self._defer()
            elif tab == "Expand":
                self._expand()
            elif tab == "Abandon":
                self._abandon()
            elif "Staged" in tab:
                self._staged()
            elif tab == "Switch":
                self._switch()
        except Exception as e:
            self.banner.show_error(str(e))

    def _defer(self):
        V = self.df_V.value(); I = self.df_I.value()
        r = self.df_r.value()/100; sigma = self.df_sigma.value()/100
        T = self.df_T.value(); q = self.df_q.value()/100

        static_npv = V - I
        # Real option = BS call with S=V, K=I, drift r, div yield q
        S_eff = V * np.exp(-q*T)  # present value of costs (dividends)
        opt_val = _bs_call(V, I, T, r-q, sigma)  # call on V with continuous cost yield q

        d1 = (np.log(V/I) + (r - q + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
        d2 = d1 - sigma*np.sqrt(T)
        delta = norm.cdf(d1) * np.exp(-q*T)
        ex_prob = norm.cdf(d2)

        strategic_npv = max(static_npv, 0) + opt_val  # NPV of flexibility

        self.grid.set("Option Value",    f"{opt_val:,.0f}", color="#d97757")
        self.grid.set("Static NPV",      f"{static_npv:,.0f}")
        self.grid.set("Strategic NPV",   f"{max(static_npv, 0) + opt_val:,.0f}", color="#30d158")
        self.grid.set("Option Premium",  f"{opt_val:,.0f}")
        self.grid.set("Delta",           f"{delta:.4f}")
        self.grid.set("d1",              f"{d1:.4f}")
        self.grid.set("d2",              f"{d2:.4f}")
        self.grid.set("Exercise Prob",   f"{ex_prob*100:.1f}%")
        self.grid.set("Time Value",      f"{opt_val - max(V-I, 0):,.0f}")
        self.grid.set("Intrinsic Value", f"{max(V-I, 0):,.0f}")
        rov_ratio = opt_val / abs(V) if V != 0 else float("nan")
        self.grid.set("ROV/NPV ratio",   f"{rov_ratio*100:.2f}%")

        Vs = np.linspace(I*0.3, I*2.5, 150)
        opt_vals = [_bs_call(v, I, T, r-q, sigma) for v in Vs]
        snpv = [v - I for v in Vs]

        ax = self.chart.ax; ax.clear()
        ax.plot(Vs/1e6, opt_vals/np.array(Vs)*100, color="#d97757", linewidth=2, label="Option Value / V (%)")
        ax.axvline(V/1e6, color="#ff9f0a", linestyle="--", linewidth=1.5, label=f"V={V/1e6:.0f}MM")
        ax.axhline(0, color="#636366", linewidth=0.8)
        ax2 = ax.twinx()
        ax2.plot(Vs/1e6, np.array(opt_vals)/1e6, color="#30d158", linewidth=1.5, alpha=0.7, label="Option Value (MM)")
        ax2.plot(Vs/1e6, np.maximum(np.array(snpv), 0)/1e6, color="#ff453a", linewidth=1, linestyle=":", label="Max(NPV,0)")
        ax.set_xlabel("Project Value V (MM)"); ax.set_ylabel("ROV/V (%)")
        ax.set_title("Real Option to Defer — Value vs Project NPV")
        ax.legend(loc="upper left", fontsize=8); ax2.legend(loc="lower right", fontsize=8)
        ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _expand(self):
        V = self.ex_V.value(); CE = self.ex_CE.value()
        x = self.ex_x.value()/100; r = self.ex_r.value()/100
        sigma = self.ex_sigma.value()/100; T = self.ex_T.value()

        # Option to expand = call on x*V with strike CE
        expand_V = x * V
        opt_val = _bs_call(expand_V, CE, T, r, sigma)
        static_npv = V - 0  # base project value
        strat_npv  = V + opt_val

        self.grid.set("Option Value",    f"{opt_val:,.0f}", color="#d97757")
        self.grid.set("Static NPV",      f"{V:,.0f}")
        self.grid.set("Strategic NPV",   f"{strat_npv:,.0f}", color="#30d158")
        self.grid.set("Option Premium",  f"{opt_val:,.0f}")

        Vs = np.linspace(V*0.2, V*3, 150)
        opt_vals = [_bs_call(x*v, CE, T, r, sigma) for v in Vs]

        ax = self.chart.ax; ax.clear()
        ax.plot(Vs/1e6, np.array(opt_vals)/1e6, color="#d97757", linewidth=2, label="Expansion option")
        ax.axvline(V/1e6, color="#ff9f0a", linestyle="--", linewidth=1.5, label=f"V={V/1e6:.0f}MM")
        ax.set_xlabel("Project Value V (MM)"); ax.set_ylabel("Option Value (MM)")
        ax.set_title("Option to Expand")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _abandon(self):
        V = self.ab_V.value(); SA = self.ab_SA.value()
        r = self.ab_r.value()/100; sigma = self.ab_sigma.value()/100
        T = self.ab_T.value()

        opt_val = _bs_put(V, SA, T, r, sigma)
        strat_npv = V + opt_val

        self.grid.set("Option Value",    f"{opt_val:,.0f}", color="#d97757")
        self.grid.set("Static NPV",      f"{V:,.0f}")
        self.grid.set("Strategic NPV",   f"{strat_npv:,.0f}", color="#30d158")

        Vs = np.linspace(SA*0.2, SA*3, 150)
        opt_vals = [_bs_put(v, SA, T, r, sigma) for v in Vs]

        ax = self.chart.ax; ax.clear()
        ax.plot(Vs/1e6, np.array(opt_vals)/1e6, color="#ff453a", linewidth=2, label="Abandon option (Put)")
        ax.axvline(V/1e6, color="#ff9f0a", linestyle="--", linewidth=1.5)
        ax.axvline(SA/1e6, color="#636366", linestyle=":", linewidth=1.5, label=f"Salvage={SA/1e6:.0f}MM")
        ax.set_xlabel("Project Value V (MM)"); ax.set_ylabel("Option Value (MM)")
        ax.set_title("Option to Abandon")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _staged(self):
        V = self.st_V.value(); I1 = self.st_I1.value(); I2 = self.st_I2.value()
        T1 = self.st_T1.value(); T2 = self.st_T2.value()
        r = self.st_r.value()/100; sigma = self.st_sigma.value()/100

        # Compound option: call-on-call
        # Value of stage 2 option at T1: BS call on V with K=I2, T=T2-T1
        opt2 = lambda v: _bs_call(v, I2, T2 - T1, r, sigma)
        # Stage 1: pay I1 at T1 if opt2(V_T1) > I1, else abandon
        from models.monte_carlo import gbm_paths
        paths = gbm_paths(V, r, 0, sigma, T1, 50, 20000, antithetic=True, seed=42)
        V_T1 = paths[:, -1]
        payoffs = np.maximum(np.array([opt2(v) for v in V_T1]) - I1, 0)
        compound_opt = np.exp(-r * T1) * payoffs.mean()

        static_npv = V - I1 - I2 * np.exp(-r * T2)
        strat_npv  = compound_opt - 0  # Stage 1 ROV

        self.grid.set("Option Value",    f"{compound_opt:,.0f}", color="#d97757")
        self.grid.set("Static NPV",      f"{static_npv:,.0f}")
        self.grid.set("Strategic NPV",   f"{V + compound_opt:,.0f}", color="#30d158")

        # Plot: option value vs project value at T1
        V_range = np.linspace(I2*0.3, I2*3, 100)
        opt2_vals = [opt2(v) for v in V_range]
        intrinsics = [max(v - I2, 0) for v in V_range]

        ax = self.chart.ax; ax.clear()
        ax.plot(V_range/1e6, np.array(opt2_vals)/1e6, color="#d97757", linewidth=2, label="Stage 2 Option at T₁")
        ax.plot(V_range/1e6, np.array(intrinsics)/1e6, color="#636366", linewidth=1, linestyle="--", label="Intrinsic")
        ax.axvline(V/1e6, color="#ff9f0a", linestyle=":", linewidth=1.5, label=f"V={V/1e6:.0f}MM")
        ax.axhline(I1/1e6, color="#ff453a", linestyle="--", linewidth=1, label=f"I₁={I1/1e6:.0f}MM")
        ax.set_xlabel("V at T₁ (MM)"); ax.set_ylabel("Value (MM)")
        ax.set_title("Staged Investment — Compound Option Analysis")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _switch(self):
        V1 = self.sw_V1.value(); V2 = self.sw_V2.value()
        SC = self.sw_SC.value(); r = self.sw_r.value()/100
        sigma = self.sw_sigma.value()/100; T = self.sw_T.value()

        # Exchange option (Margrabe): max(V2 - V1 - SC, 0)
        sigma_eff = sigma * np.sqrt(2)  # simplified: assume same vol and corr=0
        F = V2 / (V1 + SC)
        d1 = (np.log(F) + 0.5*sigma_eff**2*T) / (sigma_eff*np.sqrt(T))
        d2 = d1 - sigma_eff*np.sqrt(T)
        opt_val = (V1+SC) * (F*norm.cdf(d1) - norm.cdf(d2)) * np.exp(-r*T)
        opt_val = max(opt_val, 0)

        self.grid.set("Option Value",    f"{opt_val:,.0f}", color="#d97757")
        self.grid.set("Static NPV",      f"{V1:,.0f}")
        self.grid.set("Strategic NPV",   f"{V1 + opt_val:,.0f}", color="#30d158")

        ax = self.chart.ax; ax.clear()
        ax.bar(["Mode 1 (current)", "Mode 2 (alternative)", "Switch Cost", "Option Value"],
               [V1/1e6, V2/1e6, SC/1e6, opt_val/1e6],
               color=["#d97757","#30d158","#ff453a","#ff9f0a"])
        ax.set_ylabel("Value (MM)"); ax.set_title("Option to Switch — Value Decomposition")
        ax.grid(True, alpha=0.2, axis="y")
        self.chart.canvas.draw()

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
