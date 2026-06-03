"""Volatility surface panel (Hull Ch. 20, 27): SVI, SABR, Dupire local vol."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox
)
from PySide6.QtCore import Qt
from app.widgets import (ParamForm, FieldRow, ResultsGrid, SectionHeader,
                         Banner, make_spin, make_pct, make_combo)
from app.chart import ChartWidget


class VolSurfacePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._surface = None
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp = QSplitter(Qt.Horizontal); sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(340); left.setMaximumWidth(430)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Volatility Surface",
            "SVI · SABR · Dupire Local Vol · Term Structure"))
        self.banner = Banner(); ll.addWidget(self.banner)

        tabs = QTabWidget()

        # ── Market Quotes ──────────────────────────────────
        quotes_w = QWidget(); ql = QVBoxLayout(quotes_w); ql.setContentsMargins(8,8,8,8)
        self.model_cb = make_combo(["Market quotes","SVI parametric","SABR","Flat"])
        ql.addWidget(FieldRow("Model", self.model_cb))
        self.S0 = make_spin(0.01, 1e9, 100, 1, 2)
        self.r  = make_pct(0.15)
        ql.addWidget(FieldRow("Spot S₀", self.S0))
        ql.addWidget(FieldRow("Rate r",  self.r))

        ql.addWidget(QLabel("  Implied vols matrix (Strikes vs Maturities):"))
        STRIKES = [80, 90, 95, 100, 105, 110, 120]
        MATS    = [0.25, 0.5, 1.0, 2.0]
        VOLS = [
            [0.35, 0.32, 0.30, 0.29],
            [0.28, 0.26, 0.25, 0.24],
            [0.24, 0.23, 0.22, 0.22],
            [0.22, 0.22, 0.21, 0.21],
            [0.22, 0.22, 0.22, 0.22],
            [0.24, 0.23, 0.23, 0.23],
            [0.30, 0.28, 0.27, 0.26],
        ]
        self.vol_tbl = QTableWidget(len(STRIKES), len(MATS)+1)
        headers = ["Strike"] + [f"T={t}" for t in MATS]
        self.vol_tbl.setHorizontalHeaderLabels(headers)
        self.vol_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i, (K, vrow) in enumerate(zip(STRIKES, VOLS)):
            self.vol_tbl.setItem(i, 0, QTableWidgetItem(str(K)))
            for j, v in enumerate(vrow):
                self.vol_tbl.setItem(i, j+1, QTableWidgetItem(f"{v*100:.1f}"))
        ql.addWidget(self.vol_tbl, 1)
        tabs.addTab(quotes_w, "Market Data")

        # ── SVI params ─────────────────────────────────────
        svi_w = QWidget(); sf = ParamForm()
        self.svi_a = make_spin(-1, 1, 0.04, 0.01, 4)
        self.svi_b = make_spin(0, 2, 0.40, 0.01, 4)
        self.svi_rho = make_spin(-1, 1, -0.30, 0.05, 3)
        self.svi_m = make_spin(-2, 2, 0.0, 0.05, 3)
        self.svi_sigma = make_spin(0.001, 2, 0.30, 0.01, 3)
        sf.add_group("SVI Parameters (Jim Gatheral)", [
            FieldRow("a  (level)",      self.svi_a),
            FieldRow("b  (slope)",      self.svi_b),
            FieldRow("ρ  (skew corr)",  self.svi_rho),
            FieldRow("m  (ATM shift)",  self.svi_m),
            FieldRow("σ  (ATM width)",  self.svi_sigma),
        ])
        svl = QVBoxLayout(svi_w); svl.setContentsMargins(0,0,0,0); svl.addWidget(sf)
        tabs.addTab(svi_w, "SVI")

        # ── SABR params ─────────────────────────────────────
        sabr_w = QWidget(); sbf = ParamForm()
        self.sabr_alpha = make_pct(0.30, 0.001, 5)
        self.sabr_beta  = make_spin(0, 1, 0.5, 0.05, 2)
        self.sabr_rho   = make_spin(-1, 1, -0.3, 0.05, 2)
        self.sabr_nu    = make_pct(0.40, 0, 5)
        self.sabr_F     = make_spin(0.001, 1e6, 100, 1, 2)
        sbf.add_group("SABR Parameters", [
            FieldRow("α  (vol of vol init)", self.sabr_alpha),
            FieldRow("β  (backbone)",        self.sabr_beta),
            FieldRow("ρ  (corr)",            self.sabr_rho),
            FieldRow("ν  (vol of vol)",      self.sabr_nu),
            FieldRow("F  (forward)",         self.sabr_F),
        ])
        svl2 = QVBoxLayout(sabr_w); svl2.setContentsMargins(0,0,0,0); svl2.addWidget(sbf)
        tabs.addTab(sabr_w, "SABR")

        ll.addWidget(tabs, 1)
        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn_build = QPushButton("Build Surface"); self.btn_build.setObjectName("calc_btn"); self.btn_build.setFixedHeight(38)
        self.btn_smile = QPushButton("Smile Slice");   self.btn_smile.setObjectName("clear_btn"); self.btn_smile.setFixedHeight(38)
        bb.addWidget(self.btn_build, 1); bb.addWidget(self.btn_smile)
        ll.addLayout(bb)
        self.btn_build.clicked.connect(self._build_surface)
        self.btn_smile.clicked.connect(self._show_smile)

        # Right side
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10)
        lb = QLabel("VOLATILITY SURFACE"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["ATM Vol T=0.25", "ATM Vol T=0.5", "ATM Vol T=1", "ATM Vol T=2",
             "Skew 25Δ T=0.5", "RR 25Δ T=0.5", "Fly 25Δ T=0.5", "ATMF Vol"],
            cols=4, highlight="ATM Vol T=0.5")
        rl.addWidget(self.grid)

        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0, 0); sp.setStretchFactor(1, 1); sp.setSizes([380, 900])
        root.addWidget(sp)

    def _read_market_vols(self):
        rows = self.vol_tbl.rowCount()
        cols = self.vol_tbl.columnCount() - 1
        strikes, mats, vols = [], [0.25, 0.5, 1.0, 2.0][:cols], []
        for i in range(rows):
            try:
                K = float(self.vol_tbl.item(i, 0).text())
                strikes.append(K)
                row_vols = []
                for j in range(cols):
                    v = float(self.vol_tbl.item(i, j+1).text()) / 100
                    row_vols.append(v)
                vols.append(row_vols)
            except Exception:
                pass
        return np.array(strikes), np.array(mats), np.array(vols)

    def _build_surface(self):
        self.banner.clear()
        try:
            from risk.vol_surface import VolSurface
            K_arr, T_arr, vol_arr = self._read_market_vols()
            if len(K_arr) < 2:
                self.banner.show_error("Need at least 2 strikes in the table")
                return

            S0 = self.S0.value()
            surf = VolSurface(K_arr, T_arr, vol_arr, S0=S0, label="market")
            self._surface = surf

            # Fill metric grid
            for Ti, key in zip(T_arr, ["ATM Vol T=0.25", "ATM Vol T=0.5", "ATM Vol T=1", "ATM Vol T=2"]):
                atm_v = surf.get_vol(S0, Ti)
                self.grid.set(key, f"{atm_v*100:.2f}%")

            # 25-delta risk reversal and fly for T=0.5
            T05 = 0.5
            from scipy.stats import norm
            r = self.r.value() / 100
            def delta_to_K(delta, T, v):
                d1 = norm.ppf(delta) + v * np.sqrt(T) / 2
                return S0 * np.exp(-d1 * v * np.sqrt(T) + (r - 0.5*v**2)*T)

            v_atm = surf.get_vol(S0, T05)
            K25c = delta_to_K(0.25, T05, v_atm)
            K25p = delta_to_K(0.75, T05, v_atm)
            v25c = surf.get_vol(K25c, T05)
            v25p = surf.get_vol(K25p, T05)
            rr25 = v25c - v25p
            fly25 = 0.5*(v25c + v25p) - v_atm

            self.grid.set("Skew 25Δ T=0.5", f"{(v25c - v25p)*100:.2f}%")
            self.grid.set("RR 25Δ T=0.5",   f"{rr25*100:.2f}%")
            self.grid.set("Fly 25Δ T=0.5",  f"{fly25*100:.4f}%")
            self.grid.set("ATMF Vol",        f"{v_atm*100:.2f}%")

            # Plot surface as a 2D heatmap (strikes vs maturities)
            ax = self.chart.ax
            ax.clear()
            import matplotlib.pyplot as plt
            import matplotlib
            matplotlib.use("Agg")
            K_plot = np.linspace(K_arr.min(), K_arr.max(), 50)
            T_plot = np.linspace(T_arr.min(), T_arr.max(), 40)
            KG, TG = np.meshgrid(K_plot, T_plot)
            VG = np.array([[surf.get_vol(k, t)*100 for k in K_plot] for t in T_plot])
            c = ax.contourf(KG, TG, VG, levels=20, cmap="RdYlGn_r")
            try:
                self.chart.figure.colorbar(c, ax=ax, label="Implied Vol (%)")
            except Exception:
                pass
            ax.set_xlabel("Strike"); ax.set_ylabel("Maturity (yr)")
            ax.set_title("Implied Volatility Surface")
            ax.axvline(S0, color="#d97757", linestyle="--", linewidth=1, label=f"S₀={S0}")
            ax.legend(fontsize=8)
            self.chart.canvas.draw()

        except Exception as e:
            self.banner.show_error(str(e))

    def _show_smile(self):
        self.banner.clear()
        try:
            K_arr, T_arr, vol_arr = self._read_market_vols()
            if len(K_arr) < 2:
                self.banner.show_error("Need at least 2 strikes")
                return
            from risk.vol_surface import VolSurface
            surf = VolSurface(K_arr, T_arr, vol_arr, S0=self.S0.value())
            ax = self.chart.ax; ax.clear()
            colors = ["#d97757","#30d158","#ff9f0a","#ff453a"]
            for idx, T in enumerate(T_arr):
                K_plot = np.linspace(K_arr.min(), K_arr.max(), 200)
                vols   = [surf.get_vol(k, T)*100 for k in K_plot]
                c = colors[idx % len(colors)]
                ax.plot(K_plot, vols, color=c, linewidth=2, label=f"T={T}")
                ax.scatter(K_arr, vol_arr[:, idx]*100, color=c, s=30, zorder=5)
            ax.axvline(self.S0.value(), color="#636366", linestyle="--", linewidth=1)
            ax.set_xlabel("Strike"); ax.set_ylabel("Implied Vol (%)"); ax.set_title("Volatility Smiles")
            ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
            self.chart.canvas.draw()
        except Exception as e:
            self.banner.show_error(str(e))
