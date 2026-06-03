"""Monte Carlo simulation panel (Hull Ch. 21, 27)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSplitter, QTabWidget, QSpinBox
)
from PySide6.QtCore import Qt
from app.widgets import (ModelStatus, ParamForm, FieldRow, ResultsGrid, SectionHeader,
                         Banner, make_spin, make_pct, make_combo)
from app.chart import ChartWidget


class MonteCarloPanel(QWidget):
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
        ll.addWidget(SectionHeader("Monte Carlo Simulation",
            "GBM · Heston · LSM American · Multi-asset · Variance Reduction"))
        self.banner = Banner(); ll.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane{border:none;}")

        # ── GBM / Vanilla MC ───────────────────────────────
        gbm_w = QWidget(); gf = ParamForm()
        self.g_S     = make_spin(0.01, 1e9, 100, 1, 2)
        self.g_K     = make_spin(0.01, 1e9, 100, 1, 2)
        self.g_r     = make_pct(0.15)
        self.g_q     = make_pct(0, 0, 1)
        self.g_sigma = make_pct(0.25, 0.01, 5)
        self.g_T     = make_spin(0.01, 10, 1, 0.25, 3, "yr")
        self.g_steps = make_spin(10, 2000, 252, 10, 0, "steps")
        self.g_sims  = make_spin(1000, 500000, 50000, 1000, 0, "paths")
        self.g_type  = make_combo(["European Call","European Put","Asian Call (arith)",
                                    "Asian Put (arith)","Lookback Call","Lookback Put",
                                    "Barrier Up-and-out Call","Digital Call"])
        self.g_barrier = make_spin(0, 1e9, 120, 1, 2)
        self.g_antith  = make_combo(["Yes","No"])
        self.g_mm      = make_combo(["Yes","No"])
        self.g_cv      = make_combo(["None","Black-Scholes CV"])
        gf.add_group("Underlying", [
            FieldRow("Spot S",       self.g_S),
            FieldRow("Strike K",     self.g_K),
            FieldRow("Rate r",       self.g_r),
            FieldRow("Div yield q",  self.g_q),
            FieldRow("Vol σ",        self.g_sigma),
            FieldRow("Maturity T",   self.g_T),
        ])
        gf.add_group("Simulation", [
            FieldRow("Time steps",       self.g_steps),
            FieldRow("Paths",            self.g_sims),
            FieldRow("Instrument",       self.g_type),
            FieldRow("Barrier level",    self.g_barrier),
            FieldRow("Antithetic",       self.g_antith),
            FieldRow("Moment matching",  self.g_mm),
            FieldRow("Control variate",  self.g_cv),
        ])
        gvl = QVBoxLayout(gbm_w); gvl.setContentsMargins(0,0,0,0); gvl.addWidget(gf)
        self.tabs.addTab(gbm_w, "GBM / Vanilla")

        # ── Heston MC ──────────────────────────────────────
        hes_w = QWidget(); hf = ParamForm()
        self.h_S     = make_spin(0.01, 1e9, 100, 1, 2)
        self.h_K     = make_spin(0.01, 1e9, 100, 1, 2)
        self.h_r     = make_pct(0.05)
        self.h_q     = make_pct(0, 0, 1)
        self.h_v0    = make_spin(0.001, 4, 0.04, 0.01, 4)
        self.h_kappa = make_spin(0.001, 20, 2.0, 0.1, 3)
        self.h_theta = make_spin(0.001, 4, 0.04, 0.01, 4)
        self.h_xi    = make_spin(0.001, 5, 0.30, 0.05, 3)
        self.h_rho   = make_spin(-1, 1, -0.70, 0.05, 3)
        self.h_T     = make_spin(0.01, 10, 1, 0.25, 3, "yr")
        self.h_steps = make_spin(10, 2000, 100, 10, 0, "steps")
        self.h_sims  = make_spin(1000, 200000, 20000, 1000, 0, "paths")
        hf.add_group("Heston Parameters", [
            FieldRow("Spot S",          self.h_S),
            FieldRow("Strike K",        self.h_K),
            FieldRow("Rate r",          self.h_r),
            FieldRow("Div yield q",     self.h_q),
            FieldRow("Var v₀",          self.h_v0),
            FieldRow("κ (mean rev)",    self.h_kappa),
            FieldRow("θ (long-run var)",self.h_theta),
            FieldRow("ξ (vol of vol)",  self.h_xi),
            FieldRow("ρ (corr)",        self.h_rho),
            FieldRow("Maturity T",      self.h_T),
            FieldRow("Time steps",      self.h_steps),
            FieldRow("Paths",           self.h_sims),
        ])
        hvl = QVBoxLayout(hes_w); hvl.setContentsMargins(0,0,0,0); hvl.addWidget(hf)
        self.tabs.addTab(hes_w, "Heston")

        # ── LSM American ───────────────────────────────────
        lsm_w = QWidget(); lf = ParamForm()
        self.l_S     = make_spin(0.01, 1e9, 100, 1, 2)
        self.l_K     = make_spin(0.01, 1e9, 100, 1, 2)
        self.l_r     = make_pct(0.06)
        self.l_q     = make_pct(0, 0, 1)
        self.l_sigma = make_pct(0.20, 0.01, 5)
        self.l_T     = make_spin(0.01, 10, 1, 0.25, 3, "yr")
        self.l_steps = make_spin(10, 1000, 50, 5, 0, "steps")
        self.l_sims  = make_spin(1000, 100000, 20000, 1000, 0, "paths")
        self.l_type  = make_combo(["American Put","American Call","Bermudan Put"])
        lf.add_group("LSM — Longstaff-Schwartz (Hull Ch. 27)", [
            FieldRow("Spot S",       self.l_S),
            FieldRow("Strike K",     self.l_K),
            FieldRow("Rate r",       self.l_r),
            FieldRow("Div yield q",  self.l_q),
            FieldRow("Vol σ",        self.l_sigma),
            FieldRow("Maturity T",   self.l_T),
            FieldRow("Exercise steps", self.l_steps),
            FieldRow("Paths",        self.l_sims),
            FieldRow("Type",         self.l_type),
        ])
        lvl = QVBoxLayout(lsm_w); lvl.setContentsMargins(0,0,0,0); lvl.addWidget(lf)
        self.tabs.addTab(lsm_w, "LSM American")

        # ── VaR via MC ─────────────────────────────────────
        var_w = QWidget(); vrf = ParamForm()
        self.mv_S     = make_spin(0.01, 1e9, 1e6, 1, 0)
        self.mv_sigma = make_pct(0.20, 0.01, 5)
        self.mv_T     = make_spin(0.001, 5, 0.04, 0.005, 4, "yr")
        self.mv_conf  = make_pct(0.99, 0.90, 0.9999)
        self.mv_sims  = make_spin(10000, 1000000, 100000, 10000, 0, "paths")
        vrf.add_group("MC VaR & ES (Hull Ch. 22)", [
            FieldRow("Portfolio value", self.mv_S),
            FieldRow("Vol σ (annual)",  self.mv_sigma),
            FieldRow("Horizon T",       self.mv_T),
            FieldRow("Confidence",      self.mv_conf),
            FieldRow("Paths",           self.mv_sims),
        ])
        mvl = QVBoxLayout(var_w); mvl.setContentsMargins(0,0,0,0); mvl.addWidget(vrf)
        self.tabs.addTab(var_w, "MC VaR")

        ll.addWidget(self.tabs, 1)
        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Run Simulation"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.btn_paths = QPushButton("Show Paths"); self.btn_paths.setObjectName("clear_btn"); self.btn_paths.setFixedHeight(38)
        bb.addWidget(self.btn, 1); bb.addWidget(self.btn_paths)
        ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate)
        self.btn_paths.clicked.connect(self.show_paths)

        # Right
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl2 = QHBoxLayout(hdr)
        hl2.setContentsMargins(18,10,18,10)
        lb = QLabel("SIMULATION RESULTS"); lb.setObjectName("results_title_lbl")
        hl2.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["MC Price", "BS Analytical", "Diff (MC-BS)", "Std Error",
             "95% CI Low", "95% CI High", "N Paths", "Time (s)",
             "Early Exer. Premium", "VaR", "CVaR/ES", "Paths/sec"],
            cols=4, highlight="MC Price")
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        import time
        try:
            tab = self.tabs.tabText(self.tabs.currentIndex())

            if "GBM" in tab or "Vanilla" in tab:
                self._run_gbm()
            elif "Heston" in tab:
                self._run_heston()
            elif "LSM" in tab:
                self._run_lsm()
            elif "VaR" in tab:
                self._run_mc_var()

        except Exception as e:
            self.banner.show_error(str(e))

    def _run_gbm(self):
        import time
        from models.monte_carlo import gbm_paths
        from models.black_scholes import black_scholes
        S = self.g_S.value(); K = self.g_K.value()
        r = self.g_r.value()/100; q = self.g_q.value()/100
        sigma = self.g_sigma.value()/100
        T = self.g_T.value(); steps = int(self.g_steps.value())
        n_sims = int(self.g_sims.value())
        antith = self.g_antith.currentText() == "Yes"
        mm     = self.g_mm.currentText() == "Yes"
        inst   = self.g_type.currentText()
        barrier = self.g_barrier.value()

        t0 = time.time()
        paths = gbm_paths(S, r, q, sigma, T, steps, n_sims, antithetic=antith, moment_match=mm, seed=42)
        elapsed = time.time() - t0

        if "Asian" in inst:
            avg = paths[:, 1:].mean(axis=1)
            if "Call" in inst:
                payoffs = np.maximum(avg - K, 0)
            else:
                payoffs = np.maximum(K - avg, 0)
        elif "Lookback" in inst:
            if "Call" in inst:
                payoffs = np.maximum(paths.max(axis=1) - K, 0)
            else:
                payoffs = np.maximum(K - paths.min(axis=1), 0)
        elif "Barrier" in inst:
            breached = (paths.max(axis=1) >= barrier)
            payoffs = np.maximum(paths[:, -1] - K, 0) * (~breached).astype(float)
        elif "Digital" in inst:
            payoffs = (paths[:, -1] > K).astype(float)
        elif "Call" in inst:
            payoffs = np.maximum(paths[:, -1] - K, 0)
        else:
            payoffs = np.maximum(K - paths[:, -1], 0)

        disc_payoffs = np.exp(-r * T) * payoffs
        price = disc_payoffs.mean()
        se = disc_payoffs.std() / np.sqrt(n_sims)

        # BS for comparison
        try:
            flag = "c" if "Call" in inst else "p"
            bs_res = black_scholes(S, K, T, r, sigma, flag, q=q)
            bs_price = bs_res["price"]
        except Exception:
            bs_price = float("nan")

        self.grid.set("MC Price",      f"{price:.4f}", color="#d97757")
        self.grid.set("BS Analytical", f"{bs_price:.4f}" if not np.isnan(bs_price) else "N/A")
        diff = price - bs_price if not np.isnan(bs_price) else float("nan")
        self.grid.set("Diff (MC-BS)",  f"{diff:.4f}" if not np.isnan(diff) else "N/A")
        self.grid.set("Std Error",     f"{se:.5f}")
        self.grid.set("95% CI Low",    f"{price - 1.96*se:.4f}")
        self.grid.set("95% CI High",   f"{price + 1.96*se:.4f}")
        self.grid.set("N Paths",       f"{n_sims:,}")
        self.grid.set("Time (s)",      f"{elapsed:.2f}s")
        self.grid.set("Paths/sec",     f"{n_sims/elapsed:,.0f}")

        # Plot payoff distribution
        ax = self.chart.ax; ax.clear()
        ax.hist(disc_payoffs, bins=80, color="#d97757", alpha=0.7, edgecolor="none", density=True)
        ax.axvline(price, color="#ff9f0a", linewidth=2, label=f"Mean={price:.3f}")
        ax.axvline(price+1.96*se, color="#ff453a", linewidth=1, linestyle="--")
        ax.axvline(price-1.96*se, color="#ff453a", linewidth=1, linestyle="--", label="95% CI")
        ax.set_xlabel("Discounted Payoff"); ax.set_ylabel("Density")
        ax.set_title(f"MC Payoff Distribution — {inst}")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _run_heston(self):
        import time
        from models.monte_carlo import heston_paths
        from models.heston import heston_price
        S = self.h_S.value(); K = self.h_K.value()
        r = self.h_r.value()/100; q = self.h_q.value()/100
        v0 = self.h_v0.value(); kappa = self.h_kappa.value()
        theta = self.h_theta.value(); xi = self.h_xi.value()
        rho = self.h_rho.value(); T = self.h_T.value()
        steps = int(self.h_steps.value()); n_sims = int(self.h_sims.value())

        t0 = time.time()
        S_paths, v_paths = heston_paths(S, v0, r, q, kappa, theta, xi, rho,
                                         T, steps, n_sims, seed=42)
        elapsed = time.time() - t0

        payoffs = np.maximum(S_paths[:, -1] - K, 0)
        disc = np.exp(-r*T) * payoffs
        price = disc.mean()
        se = disc.std() / np.sqrt(n_sims)

        try:
            bs_ref = heston_price(S, K, T, r, v0, kappa, theta, xi, rho)
        except Exception:
            bs_ref = float("nan")

        self.grid.set("MC Price",      f"{price:.4f}", color="#d97757")
        self.grid.set("BS Analytical", f"{bs_ref:.4f}" if not np.isnan(bs_ref) else "N/A")
        self.grid.set("Std Error",     f"{se:.5f}")
        self.grid.set("95% CI Low",    f"{price - 1.96*se:.4f}")
        self.grid.set("95% CI High",   f"{price + 1.96*se:.4f}")
        self.grid.set("N Paths",       f"{n_sims:,}")
        self.grid.set("Time (s)",      f"{elapsed:.2f}s")

        ax = self.chart.ax; ax.clear()
        ax.hist(disc, bins=80, color="#30d158", alpha=0.7, density=True)
        ax.axvline(price, color="#ff9f0a", linewidth=2, label=f"Mean={price:.3f}")
        ax.set_xlabel("Discounted Payoff"); ax.set_ylabel("Density")
        ax.set_title("Heston MC — Call Payoff Distribution")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _run_lsm(self):
        import time
        from models.monte_carlo import gbm_paths
        from models.black_scholes import black_scholes
        S = self.l_S.value(); K = self.l_K.value()
        r = self.l_r.value()/100; q = self.l_q.value()/100
        sigma = self.l_sigma.value()/100; T = self.l_T.value()
        steps = int(self.l_steps.value()); n_sims = int(self.l_sims.value())
        opt_type = self.l_type.currentText()
        is_call = "Call" in opt_type

        t0 = time.time()
        paths = gbm_paths(S, r, q, sigma, T, steps, n_sims, antithetic=True, seed=42)
        dt = T / steps

        # LSM algorithm
        if is_call:
            intrinsic = lambda path_col: np.maximum(path_col - K, 0)
        else:
            intrinsic = lambda path_col: np.maximum(K - path_col, 0)

        cash_flows = intrinsic(paths[:, -1])

        for t_idx in range(steps - 1, 0, -1):
            itm = intrinsic(paths[:, t_idx]) > 0
            if itm.sum() < 2:
                cash_flows *= np.exp(-r * dt)
                continue
            X = paths[itm, t_idx]
            Y = cash_flows[itm] * np.exp(-r * dt)
            coeffs = np.polyfit(X, Y, 3)
            continuation = np.polyval(coeffs, X)
            imm_val = intrinsic(X)
            exercise = imm_val > continuation
            cash_flows[itm] = np.where(exercise, imm_val, Y)

        elapsed = time.time() - t0
        disc_cf = cash_flows * np.exp(-r * T)
        lsm_price = disc_cf.mean()
        se = disc_cf.std() / np.sqrt(n_sims)

        flag = "c" if is_call else "p"
        try:
            eu_price = black_scholes(S, K, T, r, sigma, flag, q=q)["price"]
        except Exception:
            eu_price = float("nan")

        early_prem = lsm_price - eu_price if not np.isnan(eu_price) else float("nan")

        self.grid.set("MC Price",      f"{lsm_price:.4f}", color="#d97757")
        self.grid.set("BS Analytical", f"{eu_price:.4f}" if not np.isnan(eu_price) else "N/A")
        self.grid.set("Early Exer. Premium", f"{early_prem:.4f}" if not np.isnan(early_prem) else "N/A")
        self.grid.set("Std Error",     f"{se:.5f}")
        self.grid.set("95% CI Low",    f"{lsm_price - 1.96*se:.4f}")
        self.grid.set("95% CI High",   f"{lsm_price + 1.96*se:.4f}")
        self.grid.set("N Paths",       f"{n_sims:,}")
        self.grid.set("Time (s)",      f"{elapsed:.2f}s")

        ax = self.chart.ax; ax.clear()
        ax.hist(disc_cf, bins=80, color="#ff9f0a", alpha=0.7, density=True)
        ax.axvline(lsm_price, color="#d97757", linewidth=2, label=f"LSM={lsm_price:.3f}")
        if not np.isnan(eu_price):
            ax.axvline(eu_price, color="#30d158", linewidth=1.5, linestyle="--", label=f"EU={eu_price:.3f}")
        ax.set_xlabel("Discounted Payoff"); ax.set_ylabel("Density")
        ax.set_title(f"LSM — {opt_type} Payoff Distribution")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _run_mc_var(self):
        V = self.mv_S.value(); sigma = self.mv_sigma.value()/100
        T = self.mv_T.value(); conf = self.mv_conf.value()/100
        n_sims = int(self.mv_sims.value())

        rng = np.random.default_rng(42)
        returns = rng.normal(0, sigma * np.sqrt(T), n_sims)
        port_values = V * np.exp(returns - 0.5 * sigma**2 * T)
        pnl = port_values - V

        var_idx = int(np.ceil((1-conf) * n_sims))
        sorted_pnl = np.sort(pnl)
        var = -sorted_pnl[var_idx]
        es  = -sorted_pnl[:var_idx].mean()

        self.grid.set("VaR",    f"{var:,.0f}", color="#ff453a")
        self.grid.set("CVaR/ES",f"{es:,.0f}",  color="#ff9f0a")
        self.grid.set("N Paths",f"{n_sims:,}")

        ax = self.chart.ax; ax.clear()
        ax.hist(pnl/1e6, bins=100, color="#d97757", alpha=0.6, density=True, label="P&L")
        ax.axvline(-var/1e6, color="#ff453a", linewidth=2, label=f"VaR {conf*100:.0f}%")
        ax.axvline(-es/1e6,  color="#ff9f0a", linewidth=2, linestyle="--", label=f"ES")
        ax.fill_betweenx([0, ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 0.1],
                          pnl.min()/1e6, -var/1e6, alpha=0.2, color="#ff453a")
        ax.set_xlabel("P&L (MM)"); ax.set_ylabel("Density")
        ax.set_title(f"MC P&L Distribution — {conf*100:.0f}% VaR = {var:,.0f}")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def show_paths(self):
        self.banner.clear()
        try:
            from models.monte_carlo import gbm_paths
            S = self.g_S.value(); r = self.g_r.value()/100
            q = self.g_q.value()/100; sigma = self.g_sigma.value()/100
            T = self.g_T.value(); steps = int(self.g_steps.value())

            paths = gbm_paths(S, r, q, sigma, T, steps, 200, seed=42)
            t_axis = np.linspace(0, T, steps+1)

            ax = self.chart.ax; ax.clear()
            for i in range(min(50, paths.shape[0])):
                ax.plot(t_axis, paths[i], linewidth=0.5, alpha=0.4, color="#d97757")
            mean_p = paths.mean(axis=0)
            p5  = np.percentile(paths, 5, axis=0)
            p95 = np.percentile(paths, 95, axis=0)
            ax.plot(t_axis, mean_p, color="#ff9f0a", linewidth=2, label="Mean")
            ax.fill_between(t_axis, p5, p95, alpha=0.2, color="#d97757", label="5-95%")
            ax.axhline(self.g_K.value(), color="#ff453a", linestyle="--", linewidth=1.5, label=f"K={self.g_K.value()}")
            ax.set_xlabel("Time (yr)"); ax.set_ylabel("Asset Price")
            ax.set_title(f"GBM Sample Paths (S₀={S}, σ={sigma*100:.1f}%)")
            ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
            self.chart.canvas.draw()
        except Exception as e:
            self.banner.show_error(str(e))
