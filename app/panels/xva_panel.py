"""XVA panel: CVA, DVA, FVA, MVA, KVA (Hull Ch. 9, 24)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSplitter, QTabWidget
)
from PySide6.QtCore import Qt
from app.widgets import (ModelStatus, ParamForm, FieldRow, ResultsGrid, SectionHeader,
                         Banner, make_spin, make_pct, make_combo)
from app.chart import ChartWidget


class XVAPanel(QWidget):
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
        ll.addWidget(SectionHeader("XVA — Valuation Adjustments",
            "CVA · DVA · FVA · MVA · KVA"))
        self.banner = Banner(); ll.addWidget(self.banner)

        f = ParamForm()

        # Counterparty
        self.cp_pd     = make_pct(0.02, 0, 1)
        self.cp_lgd    = make_pct(0.60, 0, 1)
        self.cp_spread = make_spin(0, 5000, 200, 10, 0)
        self.cp_recov  = make_pct(0.40, 0, 1)

        # Own
        self.own_pd    = make_pct(0.01, 0, 1)
        self.own_lgd   = make_pct(0.60, 0, 1)
        self.own_spread = make_spin(0, 5000, 100, 10, 0)

        # Instrument
        self.notional  = make_spin(1e3, 1e12, 1e7, 1e5, 0)
        self.mtm       = make_spin(-1e9, 1e9, 500000, 10000, 0)
        self.T         = make_spin(0.01, 30, 5, 0.5, 2, "yr")
        self.r         = make_pct(0.15)
        self.vol_mtm   = make_pct(0.30, 0.01, 3)
        self.collateral = make_combo(["None","Full collateral","Partial (CSA)"])
        self.inst_type  = make_combo(["Vanilla IRS","CDS","FX Forward","Option","Custom"])

        # Funding
        self.fund_spread = make_spin(0, 1000, 50, 5, 0)
        self.margin_rate = make_pct(0.05)

        f.add_group("Counterparty Credit", [
            FieldRow("PD (annual)",        self.cp_pd),
            FieldRow("LGD",                self.cp_lgd),
            FieldRow("CDS spread (bps)",   self.cp_spread),
            FieldRow("Recovery",           self.cp_recov),
        ])
        f.add_group("Own Credit (DVA)", [
            FieldRow("Own PD (annual)",    self.own_pd),
            FieldRow("Own LGD",            self.own_lgd),
            FieldRow("Own CDS spread",     self.own_spread),
        ])
        f.add_group("Trade Parameters", [
            FieldRow("Notional",           self.notional),
            FieldRow("Current MtM",        self.mtm),
            FieldRow("Maturity T",         self.T),
            FieldRow("Discount rate",      self.r),
            FieldRow("MtM vol σ",          self.vol_mtm),
            FieldRow("Instrument",         self.inst_type),
            FieldRow("Collateral",         self.collateral),
        ])
        f.add_group("Funding (FVA)", [
            FieldRow("Funding spread (bps)",self.fund_spread),
            FieldRow("Initial margin rate", self.margin_rate),
        ])
        ll.addWidget(f, 1)

        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Calculate XVA"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr = QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn, 1); bb.addWidget(self.clr)
        ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate)
        self.clr.clicked.connect(self.clear)

        # Right
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10)
        lb = QLabel("XVA RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["CVA", "DVA", "FVA", "MVA", "KVA",
             "Total XVA", "Clean MtM", "Adj. MtM",
             "EPE", "ENE", "EffPD", "EffLGD"],
            cols=4, highlight="Total XVA")
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            N   = self.notional.value()
            mtm = self.mtm.value()
            T   = self.T.value()
            r   = self.r.value() / 100
            vol = self.vol_mtm.value() / 100

            pd_cp   = self.cp_pd.value() / 100
            lgd_cp  = self.cp_lgd.value() / 100
            pd_own  = self.own_pd.value() / 100
            lgd_own = self.own_lgd.value() / 100
            fs      = self.fund_spread.value() / 10000

            collateral = self.collateral.currentText()
            coll_factor = 1.0 if "None" in collateral else (0.0 if "Full" in collateral else 0.5)

            # Exposure profiles (simplified Black-Scholes expected exposure)
            dt = 0.25
            times = np.arange(dt, T + dt, dt)

            # EPE / ENE via analytical approximation (lognormal MtM)
            epe_profile = []
            ene_profile = []
            for t in times:
                sig_t = vol * np.sqrt(t)
                from scipy.stats import norm
                d = sig_t / 2
                if mtm >= 0:
                    epe = mtm * norm.cdf(d) + mtm * sig_t * norm.pdf(d)
                    ene = -mtm * norm.cdf(-d) + mtm * sig_t * norm.pdf(-d)
                else:
                    epe = abs(mtm) * sig_t * norm.pdf(d)
                    ene = abs(mtm) * norm.cdf(d)
                epe_profile.append(epe * coll_factor)
                ene_profile.append(ene * coll_factor)

            epe_profile = np.array(epe_profile)
            ene_profile = np.array(ene_profile)

            # CVA = sum over time steps: PD(t) * LGD * EPE(t) * DF(t)
            survival_cp  = np.exp(-pd_cp * times)
            dfs          = np.exp(-r * times)
            marginal_pd_cp = -np.diff(np.concatenate([[1], survival_cp]))

            cva = lgd_cp * np.sum(epe_profile * marginal_pd_cp * dfs) * coll_factor
            cva = max(cva, 0)

            survival_own = np.exp(-pd_own * times)
            marginal_pd_own = -np.diff(np.concatenate([[1], survival_own]))
            dva = lgd_own * np.sum(ene_profile * marginal_pd_own * dfs) * coll_factor
            dva = max(dva, 0)

            # FVA (simplified)
            avg_exposure = np.mean(epe_profile) * coll_factor
            fva = fs * avg_exposure * T * np.exp(-r * T/2)

            # MVA (initial margin cost)
            im = 0.1 * abs(mtm)
            mva = self.margin_rate.value() / 100 * im * T * 0.5

            # KVA (simplified capital cost ~8% RWA)
            rwa = 0.5 * abs(mtm)
            kva = 0.08 * rwa * 0.12 * T * 0.5

            total_xva = -cva + dva - fva - mva - kva
            adj_mtm   = mtm + total_xva

            self.grid.set("CVA",       f"-{cva:,.0f}", color="#ff453a")
            self.grid.set("DVA",       f"+{dva:,.0f}", color="#30d158")
            self.grid.set("FVA",       f"-{fva:,.0f}", color="#ff9f0a")
            self.grid.set("MVA",       f"-{mva:,.0f}")
            self.grid.set("KVA",       f"-{kva:,.0f}")
            self.grid.set("Total XVA", f"{total_xva:,.0f}", color="#d97757")
            self.grid.set("Clean MtM", f"{mtm:,.0f}")
            self.grid.set("Adj. MtM",  f"{adj_mtm:,.0f}")
            self.grid.set("EPE",       f"{np.mean(epe_profile):,.0f}")
            self.grid.set("ENE",       f"{np.mean(ene_profile):,.0f}")
            self.grid.set("EffPD",     f"{pd_cp*100:.2f}%")
            self.grid.set("EffLGD",    f"{lgd_cp*100:.0f}%")

            # Chart: exposure profiles
            ax = self.chart.ax; ax.clear()
            ax.fill_between(times, epe_profile/1e6, alpha=0.3, color="#d97757", label="EPE")
            ax.fill_between(times, -ene_profile/1e6, alpha=0.3, color="#ff453a", label="-ENE")
            ax.plot(times, epe_profile/1e6, color="#d97757", linewidth=2)
            ax.plot(times, -ene_profile/1e6, color="#ff453a", linewidth=2)
            ax.axhline(0, color="#636366", linewidth=0.8)
            ax.set_xlabel("Time (yr)"); ax.set_ylabel("Exposure (MM)")
            ax.set_title("Expected Positive/Negative Exposure Profile")
            ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
            self.chart.canvas.draw()

        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
