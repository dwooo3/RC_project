"""VaR & CVaR panel — Historical · Parametric · Monte Carlo · EVT + comparison chart."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView, QFrame
)
from PySide6.QtCore import Qt

from app.widgets import (ModelStatus, 
    ParamForm, FieldRow, ResultsGrid, SectionHeader,
    Banner, make_spin, make_pct, make_combo
)
from app.chart import ChartWidget


class VarPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sp = QSplitter(Qt.Horizontal)
        sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        # ── Left ──────────────────────────────────────────
        left = QWidget()
        left.setObjectName("center_panel")
        left.setMinimumWidth(320)
        left.setMaximumWidth(400)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        ll.addWidget(SectionHeader("VaR & CVaR",
            "Historical · Parametric · Monte Carlo · EVT",
                 status=ModelStatus.APPROXIMATION))
        self.banner = Banner()
        ll.addWidget(self.banner)

        # Synthetic data warning
        demo_warn = QLabel(
            "⚠  DEMO MODE — Returns are synthetically generated from Normal(μ, σ). "
            "Load real CSV/P&L data for production VaR.")
        demo_warn.setWordWrap(True)
        demo_warn.setStyleSheet(
            "background:#2a2518;color:#ffd60a;border:1px solid #604820;"
            "border-radius:6px;padding:7px 12px;font-size:11px;margin:0 14px 4px 14px;")
        ll.addWidget(demo_warn)

        form = ParamForm()
        self.position  = make_spin(1e3, 1e12, 1_000_000, 1e4, 0)
        self.conf      = make_pct(0.95, 0.5, 0.9999)
        self.horizon   = make_spin(1, 365, 1, 1, 0, "d")
        self.mu        = make_pct(0.05 / 100 * 100, -5, 5)
        self.sigma_ret = make_pct(1.5, 0.01, 50.0)
        self.n_obs     = make_spin(100, 10000, 1000, 50, 0)

        self.spot   = make_spin(0.01, 1e7, 100.0, 1.0, 4)
        self.strike = make_spin(0.01, 1e7, 100.0, 1.0, 4)
        self.expiry = make_spin(0.001, 50, 0.5, 0.01, 4, "yr")
        self.rate   = make_pct(0.05)
        self.sigma  = make_pct(0.20, 0.001, 10.0)
        self.opt    = make_combo(["Call", "Put"])

        form.add_group("VaR Parameters", [
            FieldRow("Position value",  self.position),
            FieldRow("Confidence",      self.conf),
            FieldRow("Horizon",         self.horizon),
            FieldRow("Daily mean ret.", self.mu,        "Expected daily return (%)"),
            FieldRow("Daily vol",       self.sigma_ret, "Daily return volatility (%)"),
            FieldRow("Observations",    self.n_obs),
        ])
        form.add_group("Option (Stress Test)", [
            FieldRow("Spot",    self.spot),
            FieldRow("Strike",  self.strike),
            FieldRow("Expiry",  self.expiry),
            FieldRow("Rate",    self.rate),
            FieldRow("Vol (σ)", self.sigma),
            FieldRow("Type",    self.opt),
        ])
        ll.addWidget(form, 1)

        bb_w = QWidget()
        bb_w.setStyleSheet("background:#1a1a1e; border-top:1px solid #2e2e33;")
        bb = QHBoxLayout(bb_w)
        bb.setContentsMargins(14, 10, 14, 12)
        bb.setSpacing(8)
        self.btn_var    = QPushButton("Run VaR")
        self.btn_var.setObjectName("calc_btn")
        self.btn_var.setFixedHeight(36)
        self.btn_stress = QPushButton("Stress Test")
        self.btn_stress.setObjectName("sec_btn")
        self.btn_stress.setFixedHeight(36)
        bb.addWidget(self.btn_var, 1)
        bb.addWidget(self.btn_stress, 1)
        ll.addWidget(bb_w)

        self.btn_var.clicked.connect(self.calc_var)
        self.btn_stress.clicked.connect(self.calc_stress)

        # ── Right ─────────────────────────────────────────
        right = QWidget()
        right.setObjectName("results_panel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        hdr = QWidget()
        hdr.setObjectName("results_header")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 9, 16, 9)
        lb = QLabel("RESULTS")
        lb.setObjectName("results_title_lbl")
        hl.addWidget(lb)
        rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["VaR (Historical)", "CVaR (Historical)",
             "VaR (Parametric)", "CVaR (Parametric)",
             "VaR (Monte Carlo)", "VaR (EVT)"],
            cols=2,
        )
        rl.addWidget(self.grid)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Scenario", "Spot Δ", "Vol Δ", "Price", "P&L"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMaximumHeight(220)
        self.table.setAlternatingRowColors(True)
        rl.addWidget(self.table)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2e2e33; max-height:1px;")
        rl.addWidget(sep)

        self.chart = ChartWidget()
        self.chart.clear()
        rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0, 0); sp.setStretchFactor(1, 1)
        sp.setSizes([360, 900])
        root.addWidget(sp)

    def _make_returns(self):
        rng = np.random.default_rng(42)
        mu  = self.mu.value() / 100 / 100
        sig = self.sigma_ret.value() / 100
        return rng.normal(mu, sig, int(self.n_obs.value()))

    def calc_var(self):
        self.banner.clear()
        returns = self._make_returns()
        pos  = self.position.value()
        conf = self.conf.value() / 100
        h    = int(self.horizon.value())
        try:
            from risk.var import historical_var, parametric_var, montecarlo_var, evt_var
            kw = dict(position_value=pos, confidence=conf, horizon=h)
            h_res = historical_var(returns, **kw)
            p_res = parametric_var(returns, **kw)
            m_res = montecarlo_var(returns, **kw, n_sims=200_000)
            e_res = evt_var(returns, pos, conf)

            self.grid.set("VaR (Historical)",  h_res["VaR"],  color="#ff453a")
            self.grid.set("CVaR (Historical)", h_res["CVaR"], color="#ff453a")
            self.grid.set("VaR (Parametric)",  p_res["VaR"],  color="#ffd60a")
            self.grid.set("CVaR (Parametric)", p_res["CVaR"], color="#ffd60a")
            self.grid.set("VaR (Monte Carlo)", m_res["VaR"],  color="#5ac8fa")
            if "VaR" in e_res:
                self.grid.set("VaR (EVT)", e_res["VaR"], color="#bf5af2")

            results = {"Historical": h_res, "Parametric": p_res, "Monte Carlo": m_res}
            if "VaR" in e_res:
                results["EVT"] = e_res
            self.chart.plot_var_comparison(returns, results, pos)
        except Exception as e:
            self.banner.show_error(str(e))

    def calc_stress(self):
        self.banner.clear()
        try:
            from risk.stress import stress_option
            results = stress_option(
                self.spot.value(), self.strike.value(),
                self.expiry.value(), self.rate.value() / 100,
                self.sigma.value() / 100, 0.0,
                self.opt.currentText().lower(),
            )
            self.table.setRowCount(len(results))
            scenarios = []; pnls = []
            for i, r in enumerate(results):
                self.table.setItem(i, 0, QTableWidgetItem(r["scenario"][:28]))
                self.table.setItem(i, 1, QTableWidgetItem(r["spot_shock"]))
                self.table.setItem(i, 2, QTableWidgetItem(r["vol_shock"]))
                self.table.setItem(i, 3, QTableWidgetItem(str(r["stressed_price"])))
                self.table.setItem(i, 4, QTableWidgetItem(str(r["pnl"])))
                scenarios.append(r["scenario"][:22])
                pnls.append(r["pnl"])
            self.chart.plot_stress(scenarios, pnls)
        except Exception as e:
            self.banner.show_error(str(e))
