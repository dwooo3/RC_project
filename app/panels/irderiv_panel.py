"""Interest Rate Derivatives panel (Hull Ch. 6, 7, 18, 29, 30): caps, floors, swaptions, bond options, convexity/timing/quanto."""
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


def _blacks_formula(F, K, T, sigma, r, flag="call"):
    if T <= 0 or sigma <= 0:
        return max(F - K, 0) if flag == "call" else max(K - F, 0)
    d1 = (np.log(F / K) + 0.5 * sigma**2 * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    df = np.exp(-r * T)
    if flag == "call":
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


class IRDerivPanel(QWidget):
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
        ll.addWidget(SectionHeader("IR Derivatives",
            "Bond Options · Floor/Cap · Swaptions · Convexity · Quanto"))
        self.banner = Banner(); ll.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane{border:none;}")

        # ── Bond Option ────────────────────────────────────
        bo_w = QWidget(); bof = ParamForm()
        self.bo_F   = make_spin(50, 200, 98.0, 0.1, 4)
        self.bo_K   = make_spin(50, 200, 98.0, 0.1, 4)
        self.bo_r   = make_pct(0.05)
        self.bo_T   = make_spin(0.01, 20, 1.0, 0.25, 3, "yr")
        self.bo_sig = make_pct(0.10, 0.001, 3)
        self.bo_type = make_combo(["Call (Bond)","Put (Bond)"])
        bof.add_group("Bond Option — Black's Model (Hull Ch. 29)", [
            FieldRow("Bond Forward F",  self.bo_F),
            FieldRow("Strike K",        self.bo_K),
            FieldRow("Rate r",          self.bo_r),
            FieldRow("Expiry T",        self.bo_T),
            FieldRow("Bond vol σ",      self.bo_sig),
            FieldRow("Type",            self.bo_type),
        ])
        bvl = QVBoxLayout(bo_w); bvl.setContentsMargins(0,0,0,0); bvl.addWidget(bof)
        self.tabs.addTab(bo_w, "Bond Option")

        # ── Cap / Floor ────────────────────────────────────
        cap_w = QWidget(); cf_f = ParamForm()
        self.cap_N    = make_spin(1e3, 1e12, 1e7, 1e5, 0)
        self.cap_K    = make_pct(0.05)
        self.cap_r    = make_pct(0.15)
        self.cap_sig  = make_pct(0.20, 0.001, 3)
        self.cap_T    = make_spin(0.01, 30, 3, 0.5, 2, "yr")
        self.cap_freq = make_combo(["1","2","4"])
        self.cap_type = make_combo(["Cap","Floor","Collar"])
        cf_f.add_group("Cap / Floor — Black's Model (Hull Ch. 29)", [
            FieldRow("Notional",          self.cap_N),
            FieldRow("Cap/Floor rate K",  self.cap_K),
            FieldRow("Flat rate curve",   self.cap_r),
            FieldRow("Flat caplet vol σ", self.cap_sig),
            FieldRow("Maturity T",        self.cap_T),
            FieldRow("Reset freq / yr",   self.cap_freq),
            FieldRow("Instrument",        self.cap_type),
        ])
        cvl = QVBoxLayout(cap_w); cvl.setContentsMargins(0,0,0,0); cvl.addWidget(cf_f)
        self.tabs.addTab(cap_w, "Cap / Floor")

        # ── Swaption ───────────────────────────────────────
        sw_w = QWidget(); swf = ParamForm()
        self.sw_N    = make_spin(1e3, 1e12, 1e7, 1e5, 0)
        self.sw_K    = make_pct(0.05)
        self.sw_r    = make_pct(0.15)
        self.sw_sig  = make_pct(0.20, 0.001, 3)
        self.sw_Topt = make_spin(0.01, 20, 1.0, 0.25, 3, "yr")
        self.sw_Tswap = make_spin(0.01, 30, 5.0, 0.5, 2, "yr")
        self.sw_freq  = make_combo(["1","2","4"])
        self.sw_type  = make_combo(["Payer","Receiver"])
        swf.add_group("Swaption — Black's Model (Hull Ch. 29)", [
            FieldRow("Notional",           self.sw_N),
            FieldRow("Strike swap rate K", self.sw_K),
            FieldRow("Flat zero curve",    self.sw_r),
            FieldRow("Swaption vol σ",     self.sw_sig),
            FieldRow("Option expiry T",    self.sw_Topt),
            FieldRow("Swap maturity T",    self.sw_Tswap),
            FieldRow("Swap freq / yr",     self.sw_freq),
            FieldRow("Type",               self.sw_type),
        ])
        svl = QVBoxLayout(sw_w); svl.setContentsMargins(0,0,0,0); svl.addWidget(swf)
        self.tabs.addTab(sw_w, "Swaption")

        # ── Convexity / Timing ─────────────────────────────
        ct_w = QWidget(); ctf = ParamForm()
        self.ct_F    = make_pct(0.05)
        self.ct_sig  = make_pct(0.15)
        self.ct_T    = make_spin(0.01, 20, 2.0, 0.25, 3, "yr")
        self.ct_r    = make_pct(0.04)
        self.ct_alpha = make_spin(-5, 5, -0.5, 0.05, 3)
        self.ct_type  = make_combo(["CMS Convexity Adj","Timing Adj","Quanto Adj"])
        ctf.add_group("Convexity / Timing / Quanto (Hull Ch. 30)", [
            FieldRow("Forward rate F",  self.ct_F),
            FieldRow("Vol σ_F",         self.ct_sig),
            FieldRow("Settlement T",    self.ct_T),
            FieldRow("Risk-free r",     self.ct_r),
            FieldRow("α = dF/F·dR/R",  self.ct_alpha),
            FieldRow("Adjustment type", self.ct_type),
        ])
        ctvl = QVBoxLayout(ct_w); ctvl.setContentsMargins(0,0,0,0); ctvl.addWidget(ctf)
        self.tabs.addTab(ct_w, "Convexity/Quanto")

        # ── LIBOR/SOFR Market Model ─────────────────────────
        lmm_w = QWidget(); lf = ParamForm()
        self.lmm_n_fwd = make_spin(1, 20, 6, 1, 0)
        self.lmm_dt    = make_spin(0.01, 2, 0.5, 0.25, 3, "yr")
        self.lmm_f0    = make_pct(0.15)
        self.lmm_vol   = make_pct(0.20)
        self.lmm_corr  = make_spin(0, 1, 0.90, 0.05, 2)
        lf.add_group("LIBOR Market Model (BGM)", [
            FieldRow("# Forward rates",    self.lmm_n_fwd),
            FieldRow("Tenor spacing Δ",    self.lmm_dt),
            FieldRow("Initial flat rate",  self.lmm_f0),
            FieldRow("Flat vol σ",         self.lmm_vol),
            FieldRow("Corr ρ (adjacent)",  self.lmm_corr),
        ])
        lvl = QVBoxLayout(lmm_w); lvl.setContentsMargins(0,0,0,0); lvl.addWidget(lf)
        self.tabs.addTab(lmm_w, "LMM/BGM")

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
            ["Price", "DV01", "Delta", "Vega",
             "Fwd Rate", "Annuity", "d1", "d2",
             "Put-Call Par.", "Intrinsic", "Theta", "Convexity Adj"],
            cols=4, highlight="Price")
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            tab = self.tabs.tabText(self.tabs.currentIndex())
            if "Bond" in tab:
                self._price_bond_option()
            elif "Cap" in tab:
                self._price_cap_floor()
            elif "Swaption" in tab:
                self._price_swaption()
            elif "Convex" in tab:
                self._calc_convexity()
            elif "LMM" in tab:
                self._price_lmm()
        except Exception as e:
            self.banner.show_error(str(e))

    def _price_bond_option(self):
        F = self.bo_F.value(); K = self.bo_K.value()
        r = self.bo_r.value()/100; T = self.bo_T.value()
        sigma = self.bo_sig.value()/100
        flag = "call" if "Call" in self.bo_type.currentText() else "put"

        price = _blacks_formula(F, K, T, sigma, r, flag)
        d1 = (np.log(F/K) + 0.5*sigma**2*T) / (sigma*np.sqrt(T))
        d2 = d1 - sigma*np.sqrt(T)
        df = np.exp(-r*T)

        # Greeks
        delta = df * norm.cdf(d1) if flag=="call" else -df * norm.cdf(-d1)
        vega  = df * F * norm.pdf(d1) * np.sqrt(T)
        dv01  = delta * 100 / 10000

        self.grid.set("Price",  f"{price:.4f}", color="#d97757")
        self.grid.set("DV01",   f"{dv01:.4f}")
        self.grid.set("Delta",  f"{delta:.4f}")
        self.grid.set("Vega",   f"{vega:.4f}")
        self.grid.set("d1",     f"{d1:.4f}")
        self.grid.set("d2",     f"{d2:.4f}")
        self.grid.set("Fwd Rate", f"{F:.4f}")

        # PCP
        pcp = F * df - K * df - price if flag=="call" else price - F*df + K*df
        self.grid.set("Put-Call Par.", f"{pcp:.4f}")

        # Vol surface: price vs vol
        vols = np.linspace(0.01, 0.50, 100)
        prices_v = [_blacks_formula(F, K, T, v, r, flag) for v in vols]
        ax = self.chart.ax; ax.clear()
        ax.plot(vols*100, prices_v, color="#d97757", linewidth=2)
        ax.axvline(sigma*100, color="#ff9f0a", linewidth=1.5, linestyle="--", label=f"σ={sigma*100:.1f}%")
        ax.set_xlabel("Vol (%)"); ax.set_ylabel("Option Price")
        ax.set_title(f"Bond Option Price vs Volatility")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _price_cap_floor(self):
        N = self.cap_N.value(); K = self.cap_K.value()/100
        r = self.cap_r.value()/100; sigma = self.cap_sig.value()/100
        T = self.cap_T.value(); freq = int(self.cap_freq.currentText())
        cap_type = self.cap_type.currentText()

        dt = 1.0 / freq
        times = np.arange(dt, T+dt, dt)
        total_cap = 0.0; total_floor = 0.0
        caplet_prices = []

        for t in times:
            t_prev = t - dt
            F_t  = r  # flat curve: forward = flat rate
            df   = np.exp(-r * t)
            d1   = (np.log(F_t/K) + 0.5*sigma**2*t_prev) / (sigma*np.sqrt(max(t_prev, 1e-10)))
            d2   = d1 - sigma*np.sqrt(max(t_prev, 1e-10))
            # Caplet value
            cap_v  = N * dt * df * (F_t*norm.cdf(d1) - K*norm.cdf(d2))
            floor_v = N * dt * df * (K*norm.cdf(-d2) - F_t*norm.cdf(-d1))
            total_cap   += cap_v
            total_floor += floor_v
            caplet_prices.append((t, cap_v, floor_v))

        dv01 = N * T / 10000

        if "Cap" in cap_type:
            price = total_cap
        elif "Floor" in cap_type:
            price = total_floor
        else:  # Collar
            collar_K_floor = K * 0.8
            price = total_cap - total_floor

        self.grid.set("Price",    f"{price:,.2f}", color="#d97757")
        self.grid.set("DV01",     f"{dv01:,.0f}")
        self.grid.set("Fwd Rate", f"{r*100:.2f}%")

        times_arr = np.array([t for t,_,_ in caplet_prices])
        cap_arr   = np.array([c for _,c,_ in caplet_prices])
        floor_arr = np.array([f for _,_,f in caplet_prices])

        ax = self.chart.ax; ax.clear()
        ax.bar(times_arr, cap_arr, width=dt*0.4, color="#d97757", alpha=0.8, label="Caplet", align="center")
        ax.bar(times_arr+dt*0.4, floor_arr, width=dt*0.4, color="#ff453a", alpha=0.8, label="Floorlet")
        ax.set_xlabel("Maturity"); ax.set_ylabel("Value")
        ax.set_title(f"Caplet/Floorlet Values — Total Cap={total_cap:,.0f}")
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _price_swaption(self):
        N = self.sw_N.value(); K = self.sw_K.value()/100
        r = self.sw_r.value()/100; sigma = self.sw_sig.value()/100
        T_opt = self.sw_Topt.value(); T_swap = self.sw_Tswap.value()
        freq = int(self.sw_freq.currentText())
        sw_type = self.sw_type.currentText()

        dt = 1.0 / freq
        times = np.arange(dt, T_swap+dt, dt)
        annuity = sum(dt * np.exp(-r*(T_opt+t)) for t in times)
        par_swap = (1 - np.exp(-r*(T_opt+T_swap))) / (sum(dt * np.exp(-r*(T_opt+t)) for t in times))

        if T_opt <= 0 or sigma <= 0:
            price = max(par_swap - K, 0) * N * annuity
        else:
            d1 = (np.log(par_swap/K) + 0.5*sigma**2*T_opt) / (sigma*np.sqrt(T_opt))
            d2 = d1 - sigma*np.sqrt(T_opt)
            if sw_type == "Payer":
                price = N * annuity * (par_swap*norm.cdf(d1) - K*norm.cdf(d2))
            else:
                price = N * annuity * (K*norm.cdf(-d2) - par_swap*norm.cdf(-d1))

        self.grid.set("Price",    f"{price:,.2f}", color="#d97757")
        self.grid.set("Fwd Rate", f"{par_swap*100:.3f}%")
        self.grid.set("Annuity",  f"{annuity:.4f}")

        if T_opt > 0 and sigma > 0:
            d1 = (np.log(par_swap/K) + 0.5*sigma**2*T_opt) / (sigma*np.sqrt(T_opt))
            d2 = d1 - sigma*np.sqrt(T_opt)
            self.grid.set("d1", f"{d1:.4f}")
            self.grid.set("d2", f"{d2:.4f}")

        vols = np.linspace(0.01, 0.80, 100)
        prices_v = []
        for v in vols:
            if T_opt <= 0:
                prices_v.append(max(par_swap-K,0)*N*annuity)
                continue
            d1 = (np.log(par_swap/K) + 0.5*v**2*T_opt) / (v*np.sqrt(T_opt))
            d2 = d1 - v*np.sqrt(T_opt)
            if sw_type == "Payer":
                p = N * annuity * (par_swap*norm.cdf(d1) - K*norm.cdf(d2))
            else:
                p = N * annuity * (K*norm.cdf(-d2) - par_swap*norm.cdf(-d1))
            prices_v.append(p)

        ax = self.chart.ax; ax.clear()
        ax.plot(vols*100, prices_v, color="#d97757", linewidth=2)
        ax.axvline(sigma*100, color="#ff9f0a", linewidth=1.5, linestyle="--")
        ax.set_xlabel("Swaption Vol (%)"); ax.set_ylabel("Swaption Price")
        ax.set_title(f"{sw_type} Swaption Price vs Vol")
        ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _calc_convexity(self):
        F = self.ct_F.value()/100; sigma = self.ct_sig.value()/100
        T = self.ct_T.value(); r = self.ct_r.value()/100
        alpha = self.ct_alpha.value()
        adj_type = self.ct_type.currentText()

        if "CMS" in adj_type:
            # CMS convexity adjustment: E[R_T] = F + F^2 * sigma^2 * T * α / (1+F)
            # Simplified: hull ch 30 formula
            adj = F**2 * sigma**2 * T / (1 + F)
            adjusted = F + adj
            label = "CMS Adjusted Rate"
        elif "Timing" in adj_type:
            # Timing adjustment
            adj = -F * sigma**2 * T * alpha
            adjusted = F + adj
            label = "Timing Adjusted Rate"
        else:
            # Quanto adjustment
            rho = alpha  # reuse as correlation
            sigma_q = 0.15  # FX vol placeholder
            adj = rho * sigma * sigma_q * T * F
            adjusted = F - adj
            label = "Quanto Adjusted Rate"

        self.grid.set("Price",          f"{adjusted*100:.4f}%", color="#d97757")
        self.grid.set("Convexity Adj",  f"{adj*100:.4f}%")
        self.grid.set("Fwd Rate",       f"{F*100:.4f}%")

        Ts = np.linspace(0.01, 10, 100)
        if "CMS" in adj_type:
            adjs = F**2 * sigma**2 * Ts / (1 + F)
        elif "Timing" in adj_type:
            adjs = -F * sigma**2 * Ts * alpha
        else:
            adjs = -alpha * sigma * 0.15 * Ts * F

        ax = self.chart.ax; ax.clear()
        ax.plot(Ts, adjs*10000, color="#d97757", linewidth=2)
        ax.axhline(0, color="#636366", linewidth=0.8)
        ax.axvline(T, color="#ff9f0a", linestyle="--", linewidth=1.5, label=f"T={T}")
        ax.set_xlabel("Settlement T (yr)"); ax.set_ylabel("Adjustment (bps)")
        ax.set_title(adj_type)
        ax.legend(fontsize=9); ax.grid(True, alpha=0.2)
        self.chart.canvas.draw()

    def _price_lmm(self):
        n = int(self.lmm_n_fwd.value())
        dt = self.lmm_dt.value()
        f0 = self.lmm_f0.value() / 100
        vol = self.lmm_vol.value() / 100
        rho = self.lmm_corr.value()

        # Calibrate caplet prices from LMM
        cap_price = 0
        for k in range(1, n+1):
            t = k * dt; t_prev = (k-1) * dt
            r_k = f0
            df_k = np.exp(-f0 * t)
            d1 = (np.log(r_k / f0) + 0.5 * vol**2 * t_prev) / (vol * np.sqrt(max(t_prev, 1e-10)))
            d2 = d1 - vol * np.sqrt(max(t_prev, 1e-10))
            cap_price += dt * df_k * (r_k * norm.cdf(d1) - f0 * norm.cdf(d2))

        self.grid.set("Price",    f"{cap_price:.6f}", color="#d97757")
        self.grid.set("Fwd Rate", f"{f0*100:.2f}%")
        self.grid.set("Annuity",  f"{dt*sum(np.exp(-f0*k*dt) for k in range(1,n+1)):.4f}")

        fwd_names = [f"L({(k-1)*dt:.1f},{k*dt:.1f})" for k in range(1, n+1)]
        fwd_vals  = [f0] * n

        ax = self.chart.ax; ax.clear()
        ax.bar(range(n), [v*100 for v in fwd_vals], color="#d97757", alpha=0.8)
        ax.set_xticks(range(n)); ax.set_xticklabels(fwd_names, rotation=45, fontsize=8)
        ax.set_ylabel("Forward Rate (%)"); ax.set_title("LMM — Forward Rate Curve")
        ax.grid(True, alpha=0.2, axis="y")
        self.chart.canvas.draw()

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
