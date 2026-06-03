"""Binomial tree panel (Hull Ch. 13, 21)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt
from app.widgets import (ParamForm, FieldRow, ResultsGrid, SectionHeader,
                         Banner, make_spin, make_pct, make_combo)
from app.chart import ChartWidget


class BinomialPanel(QWidget):
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
        ll.addWidget(SectionHeader("Binomial Trees",
            "CRR · Equal Prob · Leisen-Reimer · American · Bermudan"))
        self.banner = Banner(); ll.addWidget(self.banner)

        f = ParamForm()
        self.S      = make_spin(0.01, 1e9, 100, 1, 2)
        self.K      = make_spin(0.01, 1e9, 100, 1, 2)
        self.r      = make_pct(0.15)
        self.q      = make_pct(0, 0, 1)
        self.sigma  = make_pct(0.25, 0.01, 5)
        self.T      = make_spin(0.01, 30, 1, 0.25, 3, "yr")
        self.N      = make_spin(1, 1000, 50, 5, 0, "steps")
        self.opt    = make_combo(["European Call","European Put",
                                   "American Call","American Put",
                                   "Bermudan Put"])
        self.method = make_combo(["CRR (Cox-Ross-Rubinstein)",
                                   "Equal Probability",
                                   "Leisen-Reimer"])
        self.show_tree = make_combo(["Yes","No"])

        f.add_group("Option Parameters", [
            FieldRow("Spot S",          self.S),
            FieldRow("Strike K",        self.K),
            FieldRow("Rate r",          self.r),
            FieldRow("Div yield q",     self.q),
            FieldRow("Vol σ",           self.sigma),
            FieldRow("Maturity T",      self.T),
            FieldRow("Steps N",         self.N),
            FieldRow("Type",            self.opt),
            FieldRow("Tree method",     self.method),
            FieldRow("Show tree grid",  self.show_tree),
        ])
        ll.addWidget(f, 1)

        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Price Option"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.btn_conv = QPushButton("Convergence"); self.btn_conv.setObjectName("clear_btn"); self.btn_conv.setFixedHeight(38)
        bb.addWidget(self.btn, 1); bb.addWidget(self.btn_conv)
        ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate)
        self.btn_conv.clicked.connect(self.show_convergence)

        # Right
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl2 = QHBoxLayout(hdr)
        hl2.setContentsMargins(18,10,18,10)
        lb = QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl2.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["Price", "BS Analytical", "Diff", "u factor",
             "d factor", "p (risk-neutral)", "Delta", "Gamma",
             "Theta", "Early Exer. Nodes", "Intrinsic Value", "Time Value"],
            cols=4, highlight="Price")
        rl.addWidget(self.grid)

        self.tree_tbl = QTableWidget(0, 0)
        self.tree_tbl.setMaximumHeight(160)
        self.tree_tbl.setAlternatingRowColors(True)
        rl.addWidget(self.tree_tbl)

        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,900])
        root.addWidget(sp)

    def _crr_params(self, sigma, r, q, dt):
        u = np.exp(sigma * np.sqrt(dt))
        d = 1 / u
        p = (np.exp((r-q)*dt) - d) / (u - d)
        return u, d, p

    def _lr_params(self, sigma, r, q, dt, n, K, S):
        # Leisen-Reimer (odd n required)
        if n % 2 == 0: n += 1
        h = lambda x: 0.5 + np.sign(x) * np.sqrt(0.25 - 0.25 * np.exp(-(x/(n+1.0/3+0.1/(n+1)))**2 * (n+1.0/6)))
        d2 = (np.log(S/K) + (r-q-0.5*sigma**2)*n*dt) / (sigma*np.sqrt(n*dt))
        d1 = d2 + sigma*np.sqrt(n*dt)
        pp = h(d2)
        p  = h(d1)
        u  = np.exp((r-q)*dt) * p / pp
        d  = (np.exp((r-q)*dt) - pp*u) / (1-pp)
        return u, d, pp

    def _price_tree(self, S, K, r, q, sigma, T, N, is_call, is_american, method):
        dt = T / N
        if method == "Leisen-Reimer":
            u, d, p = self._lr_params(sigma, r, q, dt, N, K, S)
        elif method == "Equal Probability":
            M = np.exp((r-q)*dt)
            u = M * np.exp(sigma * np.sqrt(dt))
            d = M / np.exp(sigma * np.sqrt(dt))
            p = 0.5
        else:
            u, d, p = self._crr_params(sigma, r, q, dt)

        disc = np.exp(-r * dt)
        p = np.clip(p, 0.001, 0.999)

        # Terminal stock prices
        S_T = S * u**np.arange(N, -1, -1) * d**np.arange(0, N+1, 1)
        if is_call:
            V = np.maximum(S_T - K, 0)
        else:
            V = np.maximum(K - S_T, 0)

        early_nodes = 0
        # Backward induction
        for i in range(N-1, -1, -1):
            S_i = S * u**np.arange(i, -1, -1) * d**np.arange(0, i+1, 1)
            V_cont = disc * (p * V[:i+1] + (1-p) * V[1:i+2])
            if is_american:
                if is_call:
                    intrinsic = np.maximum(S_i - K, 0)
                else:
                    intrinsic = np.maximum(K - S_i, 0)
                exercised = intrinsic > V_cont
                early_nodes += int(exercised.sum())
                V = np.maximum(V_cont, intrinsic)
            else:
                V = V_cont

        return V[0], u, d, p, early_nodes

    def calculate(self):
        self.banner.clear()
        try:
            from models.black_scholes import black_scholes
            S = self.S.value(); K = self.K.value()
            r = self.r.value()/100; q = self.q.value()/100
            sigma = self.sigma.value()/100; T = self.T.value()
            N = int(self.N.value())
            opt_type = self.opt.currentText()
            method_str = self.method.currentText().split(" ")[0]

            is_call = "Call" in opt_type
            is_american = "American" in opt_type or "Bermudan" in opt_type

            price, u, d, p, early_n = self._price_tree(S, K, r, q, sigma, T, N,
                                                         is_call, is_american, method_str)

            try:
                flag = "c" if is_call else "p"
                bs = black_scholes(S, K, T, r, sigma, flag, q=q)
                bs_price = bs["price"]
                delta_bs = bs["delta"]
                gamma_bs = bs["gamma"]
                theta_bs = bs["theta"]
            except Exception:
                bs_price = delta_bs = gamma_bs = theta_bs = float("nan")

            intrinsic = max(S - K, 0) if is_call else max(K - S, 0)
            time_val  = price - intrinsic

            self.grid.set("Price",        f"{price:.4f}", color="#d97757")
            self.grid.set("BS Analytical",f"{bs_price:.4f}" if not np.isnan(bs_price) else "N/A")
            diff = price - bs_price if not np.isnan(bs_price) else float("nan")
            self.grid.set("Diff",         f"{diff:.5f}" if not np.isnan(diff) else "N/A")
            self.grid.set("u factor",     f"{u:.5f}")
            self.grid.set("d factor",     f"{d:.5f}")
            self.grid.set("p (risk-neutral)", f"{p:.5f}")
            self.grid.set("Delta",        f"{delta_bs:.4f}" if not np.isnan(delta_bs) else "—")
            self.grid.set("Gamma",        f"{gamma_bs:.4f}" if not np.isnan(gamma_bs) else "—")
            self.grid.set("Theta",        f"{theta_bs:.4f}" if not np.isnan(theta_bs) else "—")
            self.grid.set("Early Exer. Nodes", str(early_n))
            self.grid.set("Intrinsic Value", f"{intrinsic:.4f}")
            self.grid.set("Time Value",   f"{time_val:.4f}")

            # Show small tree
            if self.show_tree.currentText() == "Yes" and N <= 20:
                n_small = min(N, 8)
                self.tree_tbl.setRowCount(n_small+1)
                self.tree_tbl.setColumnCount(n_small+1)
                self.tree_tbl.setHorizontalHeaderLabels([f"t={i}" for i in range(n_small+1)])
                dt = T / N
                for j in range(n_small+1):
                    for i in range(j+1):
                        val = S * u**(j-i) * d**i
                        item = QTableWidgetItem(f"{val:.2f}")
                        item.setTextAlignment(Qt.AlignCenter)
                        self.tree_tbl.setItem(i, j, item)
                self.tree_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            else:
                self.tree_tbl.setRowCount(0); self.tree_tbl.setColumnCount(0)

            # Plot delta vs S
            S_range = np.linspace(S*0.6, S*1.4, 100)
            prices_range = []
            for s in S_range:
                p_s, *_ = self._price_tree(s, K, r, q, sigma, T, N, is_call, is_american, method_str)
                prices_range.append(p_s)
            prices_range = np.array(prices_range)

            ax = self.chart.ax; ax.clear()
            ax.plot(S_range, prices_range, color="#d97757", linewidth=2, label=f"Binomial ({N} steps)")
            try:
                bs_prices = [black_scholes(s, K, T, r, sigma, flag, q=q)["price"] for s in S_range]
                ax.plot(S_range, bs_prices, color="#ff9f0a", linewidth=1.5, linestyle="--", label="BS")
            except Exception:
                pass
            ax.axvline(S, color="#636366", linestyle=":", linewidth=1)
            ax.set_xlabel("Spot Price"); ax.set_ylabel("Option Price")
            ax.set_title(f"Binomial vs BS — {opt_type}")
            ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
            self.chart.canvas.draw()

        except Exception as e:
            self.banner.show_error(str(e))

    def show_convergence(self):
        self.banner.clear()
        try:
            from models.black_scholes import black_scholes
            S = self.S.value(); K = self.K.value()
            r = self.r.value()/100; q = self.q.value()/100
            sigma = self.sigma.value()/100; T = self.T.value()
            opt_type = self.opt.currentText()
            is_call = "Call" in opt_type; is_amer = "American" in opt_type
            flag = "c" if is_call else "p"

            steps_list = list(range(5, 200, 5)) + list(range(200, 501, 25))
            prices = []
            for n in steps_list:
                p, *_ = self._price_tree(S, K, r, q, sigma, T, n, is_call, is_amer, "CRR")
                prices.append(p)

            try:
                bs_p = black_scholes(S, K, T, r, sigma, flag, q=q)["price"]
            except Exception:
                bs_p = None

            ax = self.chart.ax; ax.clear()
            ax.plot(steps_list, prices, color="#d97757", linewidth=1.5, label="CRR")
            if bs_p is not None:
                ax.axhline(bs_p, color="#ff9f0a", linewidth=2, linestyle="--", label=f"BS={bs_p:.4f}")
            ax.set_xlabel("Number of Steps"); ax.set_ylabel("Option Price")
            ax.set_title(f"Binomial Tree Convergence — {opt_type}")
            ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
            self.chart.canvas.draw()

        except Exception as e:
            self.banner.show_error(str(e))
