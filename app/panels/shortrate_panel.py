"""Short rate models panel (Hull Ch. 31, 32): Vasicek, CIR, Hull-White, BDT, BK, Ho-Lee."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt
from app.widgets import (ModelStatus, ParamForm, FieldRow, ResultsGrid, SectionHeader,
                         Banner, make_spin, make_pct, make_combo)
from app.chart import ChartWidget


class ShortRatePanel(QWidget):
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
        ll.addWidget(SectionHeader("Short Rate Models",
                 "Vasicek · CIR · Hull-White · Ho-Lee · BDT · BK",
                 status=ModelStatus.PROTOTYPE))
        self.banner = Banner(); ll.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane{border:none;}")

        # ── Vasicek ────────────────────────────────────────
        vas_w = QWidget(); vf = ParamForm()
        self.v_r0    = make_pct(0.05, -0.1, 2)
        self.v_kappa = make_spin(0.001, 10, 0.3, 0.05, 3)
        self.v_theta = make_pct(0.06, 0, 1)
        self.v_sigma = make_pct(0.02, 0.001, 1)
        self.v_T     = make_spin(0.1, 30, 10, 0.5, 2, "yr")
        self.v_K_bond = make_spin(0, 2, 0.80, 0.01, 4)
        self.v_T_opt = make_spin(0.01, 20, 2, 0.5, 2, "yr")
        self.v_T_bond = make_spin(0.01, 30, 5, 0.5, 2, "yr")
        vf.add_group("Vasicek Model  dr = κ(θ-r)dt + σdW", [
            FieldRow("r₀  (current rate)", self.v_r0),
            FieldRow("κ  (mean reversion)", self.v_kappa),
            FieldRow("θ  (long-run mean)",  self.v_theta),
            FieldRow("σ  (volatility)",     self.v_sigma),
            FieldRow("Curve maturity T",    self.v_T),
        ])
        vf.add_group("Bond Option (Jamshidian)", [
            FieldRow("Option expiry T_opt",  self.v_T_opt),
            FieldRow("Bond maturity T_bond", self.v_T_bond),
            FieldRow("Strike K",             self.v_K_bond),
        ])
        vvl = QVBoxLayout(vas_w); vvl.setContentsMargins(0,0,0,0); vvl.addWidget(vf)
        self.tabs.addTab(vas_w, "Vasicek")

        # ── CIR ────────────────────────────────────────────
        cir_w = QWidget(); cf_f = ParamForm()
        self.c_r0    = make_pct(0.05, 0, 2)
        self.c_kappa = make_spin(0.001, 10, 0.3, 0.05, 3)
        self.c_theta = make_pct(0.06, 0, 1)
        self.c_sigma = make_pct(0.10, 0.001, 1)
        self.c_T     = make_spin(0.1, 30, 10, 0.5, 2, "yr")
        cf_f.add_group("CIR Model  dr = κ(θ-r)dt + σ√r dW", [
            FieldRow("r₀  (current rate)", self.c_r0),
            FieldRow("κ  (mean reversion)", self.c_kappa),
            FieldRow("θ  (long-run mean)",  self.c_theta),
            FieldRow("σ  (volatility)",     self.c_sigma),
            FieldRow("Curve maturity T",    self.c_T),
        ])
        cvl = QVBoxLayout(cir_w); cvl.setContentsMargins(0,0,0,0); cvl.addWidget(cf_f)
        self.tabs.addTab(cir_w, "CIR")

        # ── Hull-White ─────────────────────────────────────
        hw_w = QWidget(); hwf = ParamForm()
        self.hw_r0     = make_pct(0.15, -0.1, 2)
        self.hw_a      = make_spin(0.001, 5, 0.10, 0.01, 4)
        self.hw_sigma  = make_pct(0.015, 0.001, 1)
        self.hw_T      = make_spin(0.1, 30, 10, 0.5, 2, "yr")
        self.hw_swaption_T = make_spin(0.1, 20, 2, 0.5, 2, "yr")
        self.hw_swap_T     = make_spin(0.1, 30, 5, 0.5, 2, "yr")
        self.hw_K_swap     = make_pct(0.05)
        hwf.add_group("Hull-White  dr = [θ(t)-ar]dt + σdW", [
            FieldRow("r₀  (current rate)", self.hw_r0),
            FieldRow("a  (mean reversion)", self.hw_a),
            FieldRow("σ  (volatility)",     self.hw_sigma),
            FieldRow("Curve maturity T",    self.hw_T),
        ])
        hwf.add_group("Swaption Pricing", [
            FieldRow("Option expiry T",     self.hw_swaption_T),
            FieldRow("Swap maturity T",     self.hw_swap_T),
            FieldRow("Swap fixed rate K",   self.hw_K_swap),
        ])
        hwvl = QVBoxLayout(hw_w); hwvl.setContentsMargins(0,0,0,0); hwvl.addWidget(hwf)
        self.tabs.addTab(hw_w, "Hull-White")

        # ── Ho-Lee ─────────────────────────────────────────
        hl_w = QWidget(); hlf = ParamForm()
        self.hl_r0    = make_pct(0.05, -0.1, 2)
        self.hl_sigma = make_pct(0.015, 0.001, 1)
        self.hl_T     = make_spin(0.1, 30, 10, 0.5, 2, "yr")
        hlf.add_group("Ho-Lee  dr = θ(t)dt + σdW", [
            FieldRow("r₀", self.hl_r0),
            FieldRow("σ",  self.hl_sigma),
            FieldRow("T",  self.hl_T),
        ])
        hlvl = QVBoxLayout(hl_w); hlvl.setContentsMargins(0,0,0,0); hlvl.addWidget(hlf)
        self.tabs.addTab(hl_w, "Ho-Lee")

        ll.addWidget(self.tabs, 1)
        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Calculate"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.btn_sim = QPushButton("Simulate"); self.btn_sim.setObjectName("clear_btn"); self.btn_sim.setFixedHeight(38)
        bb.addWidget(self.btn, 1); bb.addWidget(self.btn_sim)
        ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate)
        self.btn_sim.clicked.connect(self.simulate)

        # Right
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl2 = QHBoxLayout(hdr)
        hl2.setContentsMargins(18,10,18,10)
        lb = QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl2.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["P(0,1)", "P(0,2)", "P(0,5)", "P(0,10)",
             "R(0,1)", "R(0,5)", "R(0,10)", "R(∞)",
             "Bond Opt Call", "Bond Opt Put", "Swaption", "2F Check"],
            cols=4, highlight="P(0,5)")
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            from models.short_rate import Vasicek, CIR
            tab = self.tabs.tabText(self.tabs.currentIndex())
            Ts = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30])

            if tab == "Vasicek":
                model = Vasicek(
                    r0    = self.v_r0.value() / 100,
                    kappa = self.v_kappa.value(),
                    theta = self.v_theta.value() / 100,
                    sigma = self.v_sigma.value() / 100,
                )
                self._plot_term_structure(model, Ts, "Vasicek")
                for t, key in [(1,"P(0,1)"), (2,"P(0,2)"), (5,"P(0,5)"), (10,"P(0,10)")]:
                    self.grid.set(key, f"{model.bond_price(model.r0, t):.6f}")
                for t, key in [(1,"R(0,1)"), (5,"R(0,5)"), (10,"R(0,10)")]:
                    self.grid.set(key, f"{model.zero_rate(t)*100:.3f}%")
                rinfty = model.theta
                self.grid.set("R(∞)", f"{rinfty*100:.3f}%")

                # Bond option
                call = model.bond_option(self.v_T_opt.value(), self.v_T_bond.value(), self.v_K_bond.value(), "call")
                put  = model.bond_option(self.v_T_opt.value(), self.v_T_bond.value(), self.v_K_bond.value(), "put")
                self.grid.set("Bond Opt Call", f"{call:.6f}")
                self.grid.set("Bond Opt Put",  f"{put:.6f}")

            elif tab == "CIR":
                model = CIR(
                    r0    = self.c_r0.value() / 100,
                    kappa = self.c_kappa.value(),
                    theta = self.c_theta.value() / 100,
                    sigma = self.c_sigma.value() / 100,
                )
                self._plot_term_structure(model, Ts, "CIR")
                for t, key in [(1,"P(0,1)"), (2,"P(0,2)"), (5,"P(0,5)"), (10,"P(0,10)")]:
                    self.grid.set(key, f"{model.bond_price(model.r0, t):.6f}")
                for t, key in [(1,"R(0,1)"), (5,"R(0,5)"), (10,"R(0,10)")]:
                    self.grid.set(key, f"{model.zero_rate(t)*100:.3f}%")

            elif tab == "Hull-White":
                from models.short_rate import HullWhite
                from services.market_data_service import MarketDataService
                r0 = self.hw_r0.value() / 100
                flat_curve = MarketDataService().flat_curve(r0)
                model = HullWhite(
                    kappa = self.hw_a.value(),
                    sigma = self.hw_sigma.value() / 100,
                    curve = flat_curve,
                )
                self._plot_term_structure(model, Ts, "Hull-White")
                for t, key in [(1,"P(0,1)"), (2,"P(0,2)"), (5,"P(0,5)"), (10,"P(0,10)")]:
                    self.grid.set(key, f"{model.bond_price(r0, 0, t):.6f}")
                for t, key in [(1,"R(0,1)"), (5,"R(0,5)"), (10,"R(0,10)")]:
                    self.grid.set(key, f"{model.zero_rate(t)*100:.3f}%")

                # Swaption via Jamshidian
                try:
                    sw = model.swaption(
                        notional = 1e7,
                        K        = self.hw_K_swap.value() / 100,
                        T_opt    = self.hw_swaption_T.value(),
                        T_swap   = self.hw_swap_T.value(),
                        freq     = 2,
                    )
                    self.grid.set("Swaption", f"{sw['payer']:,.2f}")
                except Exception:
                    pass

            elif tab == "Ho-Lee":
                from models.short_rate import HoLee
                from services.market_data_service import MarketDataService
                r0 = self.hl_r0.value() / 100
                flat_curve = MarketDataService().flat_curve(r0)
                model = HoLee(sigma=self.hl_sigma.value()/100, curve=flat_curve)
                self._plot_term_structure(model, Ts, "Ho-Lee")
                for t, key in [(1,"P(0,1)"), (2,"P(0,2)"), (5,"P(0,5)"), (10,"P(0,10)")]:
                    self.grid.set(key, f"{model.bond_price(r0, 0, t):.6f}")

        except Exception as e:
            self.banner.show_error(str(e))

    def _plot_term_structure(self, model, Ts, label):
        rates = [model.zero_rate(T)*100 for T in Ts]
        ax = self.chart.ax; ax.clear()
        ax.plot(Ts, rates, color="#d97757", linewidth=2.5, marker="o", markersize=4, label=label)
        ax.fill_between(Ts, rates, alpha=0.1, color="#d97757")
        ax.axhline(rates[-1], color="#636366", linestyle=":", linewidth=1)
        ax.set_xlabel("Maturity (yr)"); ax.set_ylabel("Zero Rate (%)")
        ax.set_title(f"{label} — Term Structure of Interest Rates")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def simulate(self):
        self.banner.clear()
        try:
            tab = self.tabs.tabText(self.tabs.currentIndex())
            from models.short_rate import Vasicek, CIR
            n_paths = 20
            if tab == "Vasicek":
                model = Vasicek(self.v_r0.value()/100, self.v_kappa.value(),
                                self.v_theta.value()/100, self.v_sigma.value()/100)
                paths = model.simulate(self.v_T.value(), steps=252, n_sims=n_paths, seed=42)
                title = "Vasicek Short Rate Paths"
            elif tab == "CIR":
                model = CIR(self.c_r0.value()/100, self.c_kappa.value(),
                            self.c_theta.value()/100, self.c_sigma.value()/100)
                paths = model.simulate(self.c_T.value(), steps=252, n_sims=n_paths, seed=42)
                title = "CIR Short Rate Paths"
            elif tab == "Hull-White":
                from models.short_rate import HullWhite
                from services.market_data_service import MarketDataService
                r0 = self.hw_r0.value()/100
                model = HullWhite(kappa=self.hw_a.value(), sigma=self.hw_sigma.value()/100, curve=MarketDataService().flat_curve(r0))
                paths = model.simulate(self.hw_T.value(), steps=252, n_sims=n_paths, seed=42)
                title = "Hull-White Short Rate Paths"
            else:
                from models.short_rate import HoLee
                from services.market_data_service import MarketDataService
                r0 = self.hl_r0.value()/100
                model = HoLee(sigma=self.hl_sigma.value()/100, curve=MarketDataService().flat_curve(r0))
                paths = model.simulate(self.hl_T.value(), steps=252, n_sims=n_paths, seed=42)
                title = "Ho-Lee Short Rate Paths"

            T_val = paths.shape[1] - 1
            t_axis = np.linspace(0, T_val/252, paths.shape[1])
            ax = self.chart.ax; ax.clear()
            for i in range(min(n_paths, paths.shape[0])):
                ax.plot(t_axis, paths[i]*100, linewidth=0.8, alpha=0.5, color="#d97757")
            mean_path = paths.mean(axis=0)*100
            ax.plot(t_axis, mean_path, color="#ff9f0a", linewidth=2, label="Mean")
            ax.set_xlabel("Time (yr)"); ax.set_ylabel("Short Rate (%)")
            ax.set_title(title); ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
            self.chart.canvas.draw()

        except Exception as e:
            self.banner.show_error(str(e))
