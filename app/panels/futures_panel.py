"""Futures & Forwards pricing panel (Hull Ch. 2, 3, 5, 6)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSplitter, QTabWidget
)
from PySide6.QtCore import Qt
from app.widgets import (ParamForm, FieldRow, ResultsGrid, SectionHeader,
                         Banner, make_spin, make_pct, make_combo)
from app.chart import ChartWidget


class FuturesPanel(QWidget):
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
        ll.addWidget(SectionHeader("Futures & Forwards",
            "Equity · Index · FX · Commodity · Bond · Interest Rate Futures"))
        self.banner = Banner(); ll.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane{border:none;}")

        # ── Equity/Index Futures ───────────────────────────
        eq_w = QWidget(); ef = ParamForm()
        self.eq_S      = make_spin(0.01, 1e9, 100, 1, 2)
        self.eq_r      = make_pct(0.15)
        self.eq_q      = make_pct(0, 0, 1)
        self.eq_T      = make_spin(0.01, 10, 0.5, 0.25, 3, "yr")
        self.eq_F      = make_spin(0, 1e9, 0, 1, 4)
        ef.add_group("Equity / Index Forward", [
            FieldRow("Spot S",          self.eq_S),
            FieldRow("Risk-free r",     self.eq_r),
            FieldRow("Dividend yield q",self.eq_q),
            FieldRow("Maturity T",      self.eq_T),
            FieldRow("Quoted futures F",self.eq_F, "0 = compute"),
        ])
        evl = QVBoxLayout(eq_w); evl.setContentsMargins(0,0,0,0); evl.addWidget(ef)
        self.tabs.addTab(eq_w, "Equity/Index")

        # ── FX Forward ────────────────────────────────────
        fx_w = QWidget(); ff = ParamForm()
        self.fx_S   = make_spin(0.001, 1e9, 90.0, 0.1, 4)
        self.fx_rd  = make_pct(0.15)
        self.fx_rf  = make_pct(0.05)
        self.fx_T   = make_spin(0.01, 10, 0.5, 0.25, 3, "yr")
        ff.add_group("FX Forward (Interest Rate Parity)", [
            FieldRow("Spot S (base/quote)",    self.fx_S),
            FieldRow("Domestic rate r_d",      self.fx_rd),
            FieldRow("Foreign rate r_f",       self.fx_rf),
            FieldRow("Maturity T",             self.fx_T),
        ])
        fvl = QVBoxLayout(fx_w); fvl.setContentsMargins(0,0,0,0); fvl.addWidget(ff)
        self.tabs.addTab(fx_w, "FX Forward")

        # ── Commodity Forward ──────────────────────────────
        cm_w = QWidget(); cmf = ParamForm()
        self.cm_S    = make_spin(0.001, 1e9, 60.0, 1, 2)
        self.cm_r    = make_pct(0.05)
        self.cm_u    = make_pct(0.03, 0, 1)   # storage cost
        self.cm_y    = make_pct(0.02, 0, 1)   # convenience yield
        self.cm_T    = make_spin(0.01, 10, 1, 0.25, 3, "yr")
        cmf.add_group("Commodity Forward", [
            FieldRow("Spot S",             self.cm_S),
            FieldRow("Risk-free r",        self.cm_r),
            FieldRow("Storage cost u",     self.cm_u),
            FieldRow("Convenience yield y",self.cm_y),
            FieldRow("Maturity T",         self.cm_T),
        ])
        cvl = QVBoxLayout(cm_w); cvl.setContentsMargins(0,0,0,0); cvl.addWidget(cmf)
        self.tabs.addTab(cm_w, "Commodity")

        # ── Bond Futures ───────────────────────────────────
        bf_w = QWidget(); bff = ParamForm()
        self.bf_price    = make_spin(0, 200, 98.0, 0.1, 4)
        self.bf_coupon   = make_pct(0.07)
        self.bf_r        = make_pct(0.05)
        self.bf_T        = make_spin(0.01, 10, 1.0, 0.25, 3, "yr")
        self.bf_ai       = make_spin(0, 10, 0.5, 0.01, 4)  # accrued interest
        self.bf_cf       = make_spin(0.5, 2, 1.0, 0.01, 4) # conversion factor
        bff.add_group("Bond Futures (Hull Ch. 6)", [
            FieldRow("Quoted bond price",   self.bf_price),
            FieldRow("Coupon rate",         self.bf_coupon),
            FieldRow("Risk-free r",         self.bf_r),
            FieldRow("Delivery T",          self.bf_T),
            FieldRow("Accrued interest",    self.bf_ai),
            FieldRow("Conversion factor",   self.bf_cf),
        ])
        bvl = QVBoxLayout(bf_w); bvl.setContentsMargins(0,0,0,0); bvl.addWidget(bff)
        self.tabs.addTab(bf_w, "Bond Futures")

        # ── Eurodollar / SOFR ──────────────────────────────
        ed_w = QWidget(); edf = ParamForm()
        self.ed_price  = make_spin(90, 100, 96.5, 0.01, 4)
        self.ed_T      = make_spin(0.01, 5, 0.5, 0.25, 3, "yr")
        self.ed_convex = make_spin(-0.1, 0.1, 0.001, 0.0005, 5)
        edf.add_group("IR Futures (Eurodollar / SOFR)", [
            FieldRow("Futures price",      self.ed_price),
            FieldRow("Maturity T",         self.ed_T),
            FieldRow("Convexity adj.",     self.ed_convex),
        ])
        evl2 = QVBoxLayout(ed_w); evl2.setContentsMargins(0,0,0,0); evl2.addWidget(edf)
        self.tabs.addTab(ed_w, "IR Futures")

        ll.addWidget(self.tabs, 1)
        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Calculate"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr = QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn, 1); bb.addWidget(self.clr)
        ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate)
        self.clr.clicked.connect(self.clear)

        # Right side
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10)
        lb = QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)

        self.grid = ResultsGrid(
            ["Forward Price", "Futures Price", "Basis", "Cost of Carry",
             "Implied Rate", "DV01 (IR fut)", "Hedge Ratio", "Value"],
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

            if "Equity" in tab or "Index" in tab:
                S = self.eq_S.value()
                r = self.eq_r.value() / 100
                q = self.eq_q.value() / 100
                T = self.eq_T.value()
                F_quoted = self.eq_F.value()

                F_theoretical = S * np.exp((r - q) * T)
                basis = F_quoted - F_theoretical if F_quoted > 0 else 0
                cost_of_carry = (r - q) * S * T

                self.grid.set("Forward Price",   f"{F_theoretical:.4f}", color="#d97757")
                self.grid.set("Futures Price",   f"{F_theoretical:.4f}")
                self.grid.set("Basis",           f"{basis:.4f}")
                self.grid.set("Cost of Carry",   f"{cost_of_carry:.4f}")
                self.grid.set("Implied Rate",    f"{r*100:.2f}%")
                self.grid.set("Hedge Ratio",     "1.00")
                self.grid.set("Value",           f"0.00")

                # Term structure chart
                Ts = np.linspace(0.01, 3, 100)
                Fs = S * np.exp((r - q) * Ts)
                ax = self.chart.ax; ax.clear()
                ax.plot(Ts, Fs, color="#d97757", linewidth=2, label="Forward Curve")
                ax.axhline(S, color="#636366", linestyle="--", linewidth=1, label=f"Spot={S}")
                ax.axvline(T, color="#ff9f0a", linestyle=":", linewidth=1.5, label=f"T={T}")
                ax.scatter([T], [F_theoretical], color="#ff9f0a", s=80, zorder=5)
                ax.set_xlabel("Maturity (yr)"); ax.set_ylabel("Forward Price")
                ax.set_title("Forward Curve — Cost of Carry Model")
                ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
                self.chart.canvas.draw()

            elif "FX" in tab:
                S = self.fx_S.value()
                rd = self.fx_rd.value() / 100
                rf = self.fx_rf.value() / 100
                T  = self.fx_T.value()

                F = S * np.exp((rd - rf) * T)
                self.grid.set("Forward Price", f"{F:.4f}", color="#d97757")
                self.grid.set("Implied Rate",  f"{(rd-rf)*100:.2f}%")
                self.grid.set("Cost of Carry", f"{(F-S):.4f}")

                Ts = np.linspace(0.01, 3, 100)
                Fs = S * np.exp((rd - rf) * Ts)
                ax = self.chart.ax; ax.clear()
                ax.plot(Ts, Fs, color="#30d158", linewidth=2)
                ax.axhline(S, color="#636366", linestyle="--", linewidth=1, label=f"Spot={S}")
                ax.set_xlabel("Maturity (yr)"); ax.set_ylabel("Forward Rate")
                ax.set_title("FX Forward Curve (Interest Rate Parity)"); ax.grid(True, alpha=0.2)
                self.chart.canvas.draw()

            elif "Commodity" in tab:
                S = self.cm_S.value()
                r = self.cm_r.value() / 100
                u = self.cm_u.value() / 100
                y = self.cm_y.value() / 100
                T = self.cm_T.value()

                F = S * np.exp((r + u - y) * T)
                self.grid.set("Forward Price",   f"{F:.4f}", color="#d97757")
                self.grid.set("Cost of Carry",   f"{(r+u-y)*100:.2f}%/yr")
                self.grid.set("Basis",           f"{F-S:.4f}")

                Ts = np.linspace(0.01, 3, 100)
                Fs = S * np.exp((r + u - y) * Ts)
                ax = self.chart.ax; ax.clear()
                ax.plot(Ts, Fs, color="#ff9f0a", linewidth=2)
                ax.axhline(S, color="#636366", linestyle="--", linewidth=1)
                ax.set_xlabel("Maturity (yr)"); ax.set_ylabel("Forward Price")
                ax.set_title("Commodity Forward Curve"); ax.grid(True, alpha=0.2)
                self.chart.canvas.draw()

            elif "Bond" in tab:
                P = self.bf_price.value()
                c = self.bf_coupon.value() / 100
                r = self.bf_r.value() / 100
                T = self.bf_T.value()
                ai = self.bf_ai.value()
                cf = self.bf_cf.value()

                cash_price = P + ai
                # Futures = (cash_price - accrued_at_delivery) * e^(rT) - coupon * e^(r*(T-t_c))
                # Simplified:
                F_cash = (cash_price - 0) * np.exp(r * T) - c * (np.exp(r*T) - 1) / r if r > 0 else cash_price + c*T
                F_quoted = F_cash / cf

                self.grid.set("Forward Price",  f"{F_cash:.4f}", color="#d97757")
                self.grid.set("Futures Price",  f"{F_quoted:.4f}")
                self.grid.set("Hedge Ratio",    f"{cf:.4f}")

            elif "IR" in tab:
                price = self.ed_price.value()
                T     = self.ed_T.value()
                conv  = self.ed_convex.value()

                implied_rate = (100 - price) / 100
                adjusted_rate = implied_rate - conv
                dv01 = 25.0  # $25 per basis point for Eurodollar

                self.grid.set("Implied Rate", f"{implied_rate*100:.4f}%", color="#d97757")
                self.grid.set("DV01 (IR fut)", f"{dv01:.2f}")
                self.grid.set("Futures Price", f"{price:.4f}")
                self.grid.set("Forward Price", f"{adjusted_rate*100:.4f}%")

        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
