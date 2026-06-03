"""Historical VaR panel (Hull Ch. 22, 23)."""
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


def _gen_sample_pnl(n=500, seed=42):
    rng = np.random.default_rng(seed)
    base = rng.normal(0.001, 0.012, n)
    # Fat tails: add occasional jumps
    shocks = rng.choice([0, 1], size=n, p=[0.97, 0.03])
    base += shocks * rng.normal(-0.04, 0.02, n)
    return base


class HistVarPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pnl = None
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp = QSplitter(Qt.Horizontal); sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(340); left.setMaximumWidth(430)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Historical VaR",
            "Historical Sim · Age-weighted · Filtered · Backtest · GARCH VaR",
                 status=ModelStatus.APPROXIMATION))
        self.banner = Banner(); ll.addWidget(self.banner)

        demo_warn = QLabel(
            "⚠  DEMO MODE — P&L series is synthetically generated. "
            "Replace with real historical P&L for production use.")
        demo_warn.setWordWrap(True)
        demo_warn.setStyleSheet(
            "background:#2a2518;color:#ffd60a;border:1px solid #604820;"
            "border-radius:6px;padding:7px 12px;font-size:11px;margin:0 14px 4px 14px;")
        ll.addWidget(demo_warn)

        f = ParamForm()
        self.port_val   = make_spin(1e3, 1e12, 1e8, 1e5, 0)
        self.n_hist     = make_spin(100, 5000, 500, 50, 0, "days")
        self.horizon    = make_spin(1, 250, 10, 1, 0, "days")
        self.conf       = make_pct(0.99, 0.90, 0.9999)
        self.method     = make_combo(["Historical Simulation",
                                       "Age-weighted (BRW)",
                                       "Filtered HS (Hull-White)",
                                       "GARCH VaR",
                                       "Parametric Normal",
                                       "Parametric t-dist"])
        self.decay      = make_spin(0.90, 0.9999, 0.98, 0.005, 4)
        self.garch_lam  = make_spin(0.80, 0.999, 0.94, 0.01, 4)
        self.backtest_n = make_spin(100, 5000, 500, 50, 0, "days")
        self.vol_seed   = make_pct(0.15, 0.01, 2)
        self.corr_pairs = make_spin(1, 50, 5, 1, 0)

        f.add_group("Portfolio", [
            FieldRow("Portfolio value",   self.port_val),
            FieldRow("Annual vol σ",      self.vol_seed),
        ])
        f.add_group("VaR Parameters", [
            FieldRow("History window",    self.n_hist),
            FieldRow("Horizon",           self.horizon),
            FieldRow("Confidence level",  self.conf),
            FieldRow("Method",            self.method),
            FieldRow("Decay (age-wt)",    self.decay),
            FieldRow("GARCH λ",           self.garch_lam),
        ])
        f.add_group("Backtest", [
            FieldRow("Backtest window",   self.backtest_n),
        ])
        ll.addWidget(f, 1)

        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Calculate VaR"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.btn_bt = QPushButton("Backtest"); self.btn_bt.setObjectName("clear_btn"); self.btn_bt.setFixedHeight(38)
        bb.addWidget(self.btn, 1); bb.addWidget(self.btn_bt)
        ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate)
        self.btn_bt.clicked.connect(self.backtest)

        # Right
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl2 = QHBoxLayout(hdr)
        hl2.setContentsMargins(18,10,18,10)
        lb = QLabel("RISK METRICS"); lb.setObjectName("results_title_lbl")
        hl2.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["VaR (1-day)", "CVaR/ES (1-day)", "VaR (horizon)", "CVaR (horizon)",
             "VaR % Port", "CVaR % Port", "Max Loss", "Skewness",
             "Kurtosis", "Exceptions", "Kupiec p-val", "GARCH Vol"],
            cols=4, highlight="VaR (1-day)")
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            from risk.historical_var import hs_var, hs_age_weighted
            V      = self.port_val.value()
            n_hist = int(self.n_hist.value())
            horizon = int(self.horizon.value())
            conf   = self.conf.value() / 100
            method = self.method.currentText()
            sigma_ann = self.vol_seed.value() / 100

            # Generate synthetic P&L series scaled to portfolio
            daily_vol = sigma_ann / np.sqrt(252)
            pnl_pct = _gen_sample_pnl(n=n_hist)
            # scale vol to match input
            pnl_pct = pnl_pct / pnl_pct.std() * daily_vol
            pnl = pnl_pct * V
            self._pnl = pnl

            if method == "Historical Simulation":
                result = hs_var(pnl, conf, 1)
            elif method == "Age-weighted (BRW)":
                result = hs_age_weighted(pnl, conf, self.decay.value(), 1)
            elif "Filtered" in method:
                result = self._filtered_hs(pnl, conf)
            elif "GARCH" in method:
                result = self._garch_var(pnl, conf)
            elif "t-dist" in method:
                result = self._tvar(pnl, conf)
            else:
                result = self._parametric_normal(pnl, conf)

            var_1d = result["VaR"]
            es_1d  = result.get("CVaR", result.get("ES", var_1d * 1.2))
            var_h  = var_1d * np.sqrt(horizon)
            es_h   = es_1d * np.sqrt(horizon)

            losses = -pnl
            skew = float(np.mean(((pnl - pnl.mean())/pnl.std())**3))
            kurt = float(np.mean(((pnl - pnl.mean())/pnl.std())**4))
            max_loss = losses.max()

            # Quick backtest: count exceptions in last 250 days
            n_bt = min(250, len(pnl))
            bt_pnl = pnl[-n_bt:]
            var_bt = hs_var(bt_pnl, conf, 1)["VaR"]
            exceptions = int((bt_pnl < -var_bt).sum())
            # Kupiec test p-value
            p_exc = 1 - conf
            from scipy.stats import binom
            kupiec_pval = 2 * binom.pmf(exceptions, n_bt, p_exc)

            self.grid.set("VaR (1-day)",    f"{var_1d:,.0f}", color="#ff453a")
            self.grid.set("CVaR/ES (1-day)",f"{es_1d:,.0f}",  color="#ff9f0a")
            self.grid.set("VaR (horizon)",  f"{var_h:,.0f}")
            self.grid.set("CVaR (horizon)", f"{es_h:,.0f}")
            self.grid.set("VaR % Port",     f"{var_1d/V*100:.3f}%")
            self.grid.set("CVaR % Port",    f"{es_1d/V*100:.3f}%")
            self.grid.set("Max Loss",       f"{max_loss:,.0f}")
            self.grid.set("Skewness",       f"{skew:.3f}")
            self.grid.set("Kurtosis",       f"{kurt:.3f}")
            self.grid.set("Exceptions",     f"{exceptions} / {n_bt}")
            self.grid.set("Kupiec p-val",   f"{kupiec_pval:.4f}")

            garch_vol = self._garch_vol(pnl)
            self.grid.set("GARCH Vol",      f"{garch_vol*100*np.sqrt(252):.2f}% ann")

            # Plot P&L distribution
            ax = self.chart.ax; ax.clear()
            ax.hist(pnl/1e6, bins=60, color="#d97757", alpha=0.6, density=True, label="Daily P&L")
            ax.axvline(-var_1d/1e6, color="#ff453a", linewidth=2, label=f"VaR {conf*100:.0f}%")
            ax.axvline(-es_1d/1e6,  color="#ff9f0a", linewidth=2, linestyle="--", label="ES/CVaR")
            from scipy.stats import norm, kurtosis as kurt_fn
            mu = pnl.mean() / 1e6
            sd = pnl.std() / 1e6
            xs = np.linspace(pnl.min()/1e6, pnl.max()/1e6, 200)
            ax.plot(xs, norm.pdf(xs, mu, sd), color="#636366", linewidth=1.5, linestyle="--", label="Normal fit")
            ax.set_xlabel("P&L (MM)"); ax.set_ylabel("Density")
            ax.set_title(f"P&L Distribution — {method}")
            ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
            self.chart.canvas.draw()

        except Exception as e:
            self.banner.show_error(str(e))

    def backtest(self):
        self.banner.clear()
        try:
            if self._pnl is None:
                self.calculate()
                return
            from risk.historical_var import hs_var
            pnl = self._pnl
            conf = self.conf.value() / 100
            n_bt = min(int(self.backtest_n.value()), len(pnl) - 50)
            window = 50

            var_series = []
            pnl_actual = []
            for i in range(window, n_bt):
                hist = pnl[i-window:i]
                v = hs_var(hist, conf, 1)["VaR"]
                var_series.append(v)
                pnl_actual.append(pnl[i])

            var_arr  = np.array(var_series)
            pnl_arr  = np.array(pnl_actual)
            breaches = pnl_arr < -var_arr

            ax = self.chart.ax; ax.clear()
            days = np.arange(len(var_arr))
            ax.plot(days, pnl_arr / 1e6, color="#d97757", linewidth=0.8, alpha=0.8, label="P&L")
            ax.plot(days, -var_arr / 1e6, color="#ff453a", linewidth=1.5, label=f"VaR {conf*100:.0f}%")
            breach_days = days[breaches]
            ax.scatter(breach_days, pnl_arr[breaches]/1e6, color="#ff453a", s=40, zorder=5, label=f"Exceptions ({breaches.sum()})")
            ax.axhline(0, color="#636366", linewidth=0.5)
            ax.set_xlabel("Day"); ax.set_ylabel("P&L / VaR (MM)")
            ax.set_title(f"VaR Backtest — {breaches.sum()} exceptions / {len(var_arr)} days")
            ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
            self.chart.canvas.draw()

        except Exception as e:
            self.banner.show_error(str(e))

    def _filtered_hs(self, pnl, conf):
        lam = self.garch_lam.value()
        n = len(pnl)
        var2 = np.zeros(n)
        var2[0] = pnl[0]**2
        for i in range(1, n):
            var2[i] = lam * var2[i-1] + (1-lam) * pnl[i-1]**2
        current_vol = np.sqrt(var2[-1])
        hist_vols   = np.sqrt(var2)
        standardized = pnl / (hist_vols + 1e-12)
        scaled_pnl = standardized * current_vol
        losses = -np.sort(scaled_pnl)
        idx = int(np.ceil(conf * n)) - 1
        return dict(VaR=losses[idx], CVaR=losses[idx:].mean())

    def _garch_var(self, pnl, conf):
        from risk.historical_var import hs_var
        return hs_var(pnl, conf, 1)

    def _tvar(self, pnl, conf):
        from scipy.stats import t as t_dist
        n = len(pnl)
        df, loc, scale = t_dist.fit(pnl)
        var = -t_dist.ppf(1-conf, df, loc, scale)
        es  = -loc + scale * t_dist.pdf(t_dist.ppf(1-conf, df), df) / (1-conf) * (df + t_dist.ppf(1-conf,df)**2) / (df - 1)
        return dict(VaR=var, CVaR=max(es, var))

    def _parametric_normal(self, pnl, conf):
        from scipy.stats import norm
        mu = pnl.mean(); sigma = pnl.std()
        var = -(mu + sigma * norm.ppf(1-conf))
        es  = -(mu - sigma * norm.pdf(norm.ppf(1-conf)) / (1-conf))
        return dict(VaR=var, CVaR=max(es, var))

    def _garch_vol(self, pnl):
        lam = self.garch_lam.value()
        v2 = pnl[0]**2
        for r in pnl[1:]:
            v2 = lam * v2 + (1-lam) * r**2
        return np.sqrt(v2)
