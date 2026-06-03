"""Commodity derivatives panel (Hull Ch. 35): oil, gas, metals, electricity, commodity options."""
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


class CommodityPanel(QWidget):
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
        ll.addWidget(SectionHeader("Commodity Derivatives",
            "Forwards · Options · Convenience Yield · Mean-Reversion · Seasonality"))
        self.banner = Banner(); ll.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane{border:none;}")

        # ── Forward Curve ───────────────────────────────────
        fwd_w = QWidget(); ff = ParamForm()
        self.fwd_S     = make_spin(0.001, 1e6, 80.0, 1, 2)
        self.fwd_r     = make_pct(0.05)
        self.fwd_u     = make_pct(0.03, 0, 1)
        self.fwd_y     = make_pct(0.05, 0, 1)
        self.fwd_T     = make_spin(0.01, 10, 1, 0.25, 3, "yr")
        self.fwd_comm  = make_combo(["Oil (Brent/WTI)","Natural Gas","Gold","Silver",
                                      "Copper","Wheat","Corn","Coal","Custom"])
        self.fwd_curr  = make_combo(["USD","RUB","EUR"])
        ff.add_group("Commodity Forward", [
            FieldRow("Commodity",          self.fwd_comm),
            FieldRow("Spot price S",       self.fwd_S),
            FieldRow("Risk-free r",        self.fwd_r),
            FieldRow("Storage cost u",     self.fwd_u),
            FieldRow("Convenience yield y",self.fwd_y),
            FieldRow("Maturity T",         self.fwd_T),
            FieldRow("Currency",           self.fwd_curr),
        ])
        fvl = QVBoxLayout(fwd_w); fvl.setContentsMargins(0,0,0,0); fvl.addWidget(ff)
        self.tabs.addTab(fwd_w, "Forward")

        # ── Commodity Option ───────────────────────────────
        opt_w = QWidget(); of = ParamForm()
        self.opt_S     = make_spin(0.001, 1e6, 80.0, 1, 2)
        self.opt_K     = make_spin(0.001, 1e6, 80.0, 1, 2)
        self.opt_r     = make_pct(0.05)
        self.opt_u     = make_pct(0.03, 0, 1)
        self.opt_y     = make_pct(0.05, 0, 1)
        self.opt_sigma = make_pct(0.30, 0.01, 5)
        self.opt_T     = make_spin(0.01, 10, 1, 0.25, 3, "yr")
        self.opt_type  = make_combo(["Call","Put","Asian Call (arith)","Spread Call"])
        self.opt_S2    = make_spin(0, 1e6, 75.0, 1, 2)
        of.add_group("Commodity Option — Black's Model", [
            FieldRow("Spot S₁",            self.opt_S),
            FieldRow("Spot S₂ (spread)",   self.opt_S2),
            FieldRow("Strike K",           self.opt_K),
            FieldRow("Rate r",             self.opt_r),
            FieldRow("Storage cost u",     self.opt_u),
            FieldRow("Conv. yield y",      self.opt_y),
            FieldRow("Vol σ",              self.opt_sigma),
            FieldRow("Maturity T",         self.opt_T),
            FieldRow("Type",               self.opt_type),
        ])
        ovl = QVBoxLayout(opt_w); ovl.setContentsMargins(0,0,0,0); ovl.addWidget(of)
        self.tabs.addTab(opt_w, "Option")

        # ── Schwartz Mean-Reversion ────────────────────────
        mr_w = QWidget(); mrf = ParamForm()
        self.mr_S     = make_spin(0.001, 1e6, 80.0, 1, 2)
        self.mr_kappa = make_spin(0.001, 20, 1.0, 0.1, 3)
        self.mr_mu    = make_spin(0.001, 1e6, 80.0, 1, 2)
        self.mr_sigma = make_pct(0.30, 0.01, 5)
        self.mr_T     = make_spin(0.01, 10, 3, 0.25, 3, "yr")
        self.mr_r     = make_pct(0.05)
        self.mr_lam   = make_pct(0.10, -1, 1)
        mrf.add_group("Schwartz 1-Factor Mean-Reversion (Ch. 35)", [
            FieldRow("Spot S",           self.mr_S),
            FieldRow("κ (mean reversion)", self.mr_kappa),
            FieldRow("μ (long-run mean)", self.mr_mu),
            FieldRow("σ (vol)",          self.mr_sigma),
            FieldRow("Maturity T",       self.mr_T),
            FieldRow("Risk-free r",      self.mr_r),
            FieldRow("λ (risk premium)", self.mr_lam),
        ])
        mvl = QVBoxLayout(mr_w); mvl.setContentsMargins(0,0,0,0); mvl.addWidget(mrf)
        self.tabs.addTab(mr_w, "Mean Reversion")

        # ── Energy Swap ─────────────────────────────────────
        esw_w = QWidget(); esf = ParamForm()
        self.esw_N    = make_spin(1, 1e9, 100000, 1000, 0, "bbl/gas")
        self.esw_K    = make_spin(0.001, 1e6, 80.0, 1, 2)
        self.esw_fwd  = make_spin(0.001, 1e6, 82.0, 1, 2)
        self.esw_r    = make_pct(0.05)
        self.esw_T    = make_spin(0.01, 10, 1, 0.25, 3, "yr")
        self.esw_freq = make_combo(["Monthly","Quarterly","Annual"])
        esf.add_group("Commodity Swap / TRS", [
            FieldRow("Quantity",        self.esw_N),
            FieldRow("Fixed price K",   self.esw_K),
            FieldRow("Forward price F", self.esw_fwd),
            FieldRow("Risk-free r",     self.esw_r),
            FieldRow("Maturity T",      self.esw_T),
            FieldRow("Settlement",      self.esw_freq),
        ])
        esvl = QVBoxLayout(esw_w); esvl.setContentsMargins(0,0,0,0); esvl.addWidget(esf)
        self.tabs.addTab(esw_w, "Energy Swap")

        ll.addWidget(self.tabs, 1)
        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Calculate"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
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
        lb = QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl2.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["Forward Price", "Option Price", "Delta", "Vega",
             "Cost of Carry", "Conv. Yield", "LR Mean Fwd", "Swap Value",
             "d1", "d2", "Gamma", "Theta"],
            cols=4, highlight="Forward Price")
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            tab = self.tabs.tabText(self.tabs.currentIndex())
            if "Forward" in tab:
                self._calc_forward()
            elif "Option" in tab:
                self._calc_option()
            elif "Mean" in tab:
                self._calc_mean_reversion()
            elif "Swap" in tab:
                self._calc_energy_swap()
        except Exception as e:
            self.banner.show_error(str(e))

    def _calc_forward(self):
        S = self.fwd_S.value(); r = self.fwd_r.value()/100
        u = self.fwd_u.value()/100; y = self.fwd_y.value()/100
        T = self.fwd_T.value()

        Ts = np.linspace(0.01, max(T*2, 2), 100)
        Fs = S * np.exp((r + u - y) * Ts)
        F_T = S * np.exp((r + u - y) * T)

        self.grid.set("Forward Price", f"{F_T:.2f}", color="#d97757")
        self.grid.set("Cost of Carry", f"{(r+u-y)*100:.2f}%/yr")
        self.grid.set("Conv. Yield",   f"{y*100:.2f}%")

        ax = self.chart.ax; ax.clear()
        ax.plot(Ts, Fs, color="#d97757", linewidth=2, label=self.fwd_comm.currentText())
        ax.axhline(S, color="#636366", linestyle="--", linewidth=1, label=f"Spot={S:.2f}")
        ax.scatter([T], [F_T], color="#ff9f0a", s=80, zorder=5, label=f"F({T}yr)={F_T:.2f}")
        ax.set_xlabel("Maturity (yr)"); ax.set_ylabel("Forward Price")
        ax.set_title("Commodity Forward Curve (Cost of Carry)")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _calc_option(self):
        S = self.opt_S.value(); K = self.opt_K.value()
        r = self.opt_r.value()/100; u = self.opt_u.value()/100
        y = self.opt_y.value()/100; sigma = self.opt_sigma.value()/100
        T = self.opt_T.value(); opt = self.opt_type.currentText()

        # Forward price for Black's model
        F = S * np.exp((r + u - y) * T)
        d1 = (np.log(F/K) + 0.5*sigma**2*T) / (sigma*np.sqrt(T))
        d2 = d1 - sigma*np.sqrt(T)
        df = np.exp(-r*T)

        if "Call" in opt and "Spread" not in opt and "Asian" not in opt:
            price = df * (F*norm.cdf(d1) - K*norm.cdf(d2))
            delta = df * norm.cdf(d1)
        elif "Put" in opt:
            price = df * (K*norm.cdf(-d2) - F*norm.cdf(-d1))
            delta = -df * norm.cdf(-d1)
        elif "Spread" in opt:
            S2 = self.opt_S2.value()
            F2 = S2 * np.exp((r + u - y) * T)
            price = max(F - F2 - K, 0) * df  # intrinsic approximation
            delta = 0
        else:  # Asian approximation
            F_adj = F * np.exp(-0.5 * sigma**2 * T / 6)
            sig_adj = sigma / np.sqrt(3)
            d1a = (np.log(F_adj/K) + 0.5*sig_adj**2*T) / (sig_adj*np.sqrt(T))
            d2a = d1a - sig_adj*np.sqrt(T)
            price = df * (F_adj*norm.cdf(d1a) - K*norm.cdf(d2a))
            delta = 0

        vega  = df * F * norm.pdf(d1) * np.sqrt(T)
        gamma = df * norm.pdf(d1) / (F * sigma * np.sqrt(T))

        self.grid.set("Forward Price", f"{F:.4f}")
        self.grid.set("Option Price",  f"{price:.4f}", color="#d97757")
        self.grid.set("Delta",         f"{delta:.4f}")
        self.grid.set("Vega",          f"{vega:.4f}")
        self.grid.set("Gamma",         f"{gamma:.6f}")
        self.grid.set("d1",            f"{d1:.4f}")
        self.grid.set("d2",            f"{d2:.4f}")

        Ks = np.linspace(K*0.6, K*1.4, 100)
        prices = []
        for k in Ks:
            d1k = (np.log(F/k) + 0.5*sigma**2*T) / (sigma*np.sqrt(T))
            d2k = d1k - sigma*np.sqrt(T)
            if "Call" in opt:
                prices.append(df * (F*norm.cdf(d1k) - k*norm.cdf(d2k)))
            else:
                prices.append(df * (k*norm.cdf(-d2k) - F*norm.cdf(-d1k)))

        ax = self.chart.ax; ax.clear()
        ax.plot(Ks, prices, color="#d97757", linewidth=2, label=f"{opt}")
        ax.axvline(K, color="#ff9f0a", linestyle="--", linewidth=1.5, label=f"K={K}")
        ax.axvline(F, color="#30d158", linestyle=":", linewidth=1.5, label=f"F={F:.2f}")
        ax.set_xlabel("Strike"); ax.set_ylabel("Option Price")
        ax.set_title(f"Commodity {opt} vs Strike")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _calc_mean_reversion(self):
        S = self.mr_S.value(); kappa = self.mr_kappa.value()
        mu = self.mr_mu.value(); sigma = self.mr_sigma.value()/100
        T = self.mr_T.value(); r = self.mr_r.value()/100
        lam = self.mr_lam.value()/100

        # Schwartz forward price
        Ts = np.linspace(0.01, max(T*2, 3), 100)
        alpha = (mu - lam/kappa - 0.5*sigma**2/kappa**2) * kappa
        Fs = np.exp(np.log(S)*np.exp(-kappa*Ts) +
                    (1-np.exp(-kappa*Ts)) * alpha/kappa +
                    sigma**2/(4*kappa) * (1-np.exp(-2*kappa*Ts)))
        F_T = float(np.interp(T, Ts, Fs))

        lr_mean = np.exp(alpha/kappa + sigma**2/(4*kappa**2))
        self.grid.set("Forward Price", f"{F_T:.4f}", color="#d97757")
        self.grid.set("LR Mean Fwd",   f"{lr_mean:.4f}")
        self.grid.set("Cost of Carry", f"{kappa:.3f} (kappa)")

        ax = self.chart.ax; ax.clear()
        ax.plot(Ts, Fs, color="#d97757", linewidth=2, label="Schwartz forward curve")
        ax.axhline(lr_mean, color="#636366", linestyle="--", linewidth=1.5, label=f"LR mean={lr_mean:.2f}")
        ax.axhline(S, color="#ff9f0a", linestyle=":", linewidth=1.5, label=f"Spot={S}")
        ax.scatter([T], [F_T], color="#ff453a", s=80, zorder=5)
        ax.set_xlabel("Maturity (yr)"); ax.set_ylabel("Forward Price")
        ax.set_title(f"Schwartz Mean-Reverting Commodity (κ={kappa:.2f})")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _calc_energy_swap(self):
        N = self.esw_N.value(); K = self.esw_K.value()
        F = self.esw_fwd.value(); r = self.esw_r.value()/100
        T = self.esw_T.value(); freq_s = self.esw_freq.currentText()

        freq_map = {"Monthly": 12, "Quarterly": 4, "Annual": 1}
        freq = freq_map[freq_s]
        dt = 1 / freq
        times = np.arange(dt, T+dt, dt)

        swap_value = N * sum((F - K) * np.exp(-r*t) for t in times)

        self.grid.set("Swap Value", f"{swap_value:,.2f}", color="#d97757")
        self.grid.set("Forward Price", f"{F:.2f}")

        cashflows = [(F - K) * N for _ in times]
        pv_cashflows = [cf * np.exp(-r*t) for cf, t in zip(cashflows, times)]

        ax = self.chart.ax; ax.clear()
        ax.bar(times, pv_cashflows, width=dt*0.8, color="#d97757", alpha=0.8, label="PV Cash Flows")
        ax.axhline(0, color="#636366", linewidth=0.8)
        ax.set_xlabel("Settlement Date (yr)"); ax.set_ylabel("PV Cash Flow")
        ax.set_title(f"Energy Swap Cash Flows (Total NPV={swap_value:,.0f})")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
