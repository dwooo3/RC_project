"""Embedded matplotlib charts — dark Claude-style theme."""

import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import matplotlib as mpl
import matplotlib.ticker as mtick

# ── Dark palette ──────────────────────────────────────────────────────────
_BG0  = "#0f0f11"   # figure background
_BG1  = "#1a1a1e"   # axes background
_BG2  = "#242428"   # card / elevated
_GRID = "#2e2e33"   # grid lines
_EDGE = "#38383d"   # spine / border
_TXT  = "#a0a0a8"   # labels, ticks
_TXT0 = "#f0f0f2"   # titles
_LEG  = "#1e1e22"   # legend bg

# ── Color palette ─────────────────────────────────────────────────────────
C_ACCENT = "#d97757"   # Claude orange — main accent
C_BLUE   = "#5ac8fa"   # teal-blue — secondary
C_GREEN  = "#30d158"   # green — positive
C_RED    = "#ff453a"   # red — negative / risk
C_PURPLE = "#bf5af2"   # purple — model
C_AMBER  = "#ffd60a"   # yellow — highlight
C_TEAL   = "#34aadc"   # teal — curves
C_GREY   = "#48484a"   # neutral lines
C_SLATE  = "#606068"   # muted references

# ── Global rcParams ───────────────────────────────────────────────────────
mpl.rcParams.update({
    "font.family":        "DejaVu Sans",
    "font.size":          9.0,
    "axes.facecolor":     _BG1,
    "figure.facecolor":   _BG0,
    "axes.edgecolor":     _EDGE,
    "axes.linewidth":     0.7,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.grid":          True,
    "axes.grid.axis":     "y",
    "grid.alpha":         0.30,
    "grid.linestyle":     ":",
    "grid.linewidth":     0.6,
    "grid.color":         _GRID,
    "xtick.color":        _TXT,
    "ytick.color":        _TXT,
    "xtick.labelsize":    8,
    "ytick.labelsize":    8,
    "axes.labelcolor":    _TXT,
    "axes.labelsize":     8.5,
    "axes.titlesize":     10,
    "axes.titleweight":   "bold",
    "axes.titlecolor":    _TXT0,
    "axes.titlelocation": "left",
    "text.color":         _TXT,
    "legend.fontsize":    8,
    "legend.framealpha":  0.90,
    "legend.facecolor":   _LEG,
    "legend.edgecolor":   _EDGE,
    "legend.labelcolor":  _TXT,
    "legend.borderpad":   0.5,
    "legend.handlelength": 1.4,
    "figure.dpi":         110,
    "lines.linewidth":    1.9,
    "lines.antialiased":  True,
    "patch.antialiased":  True,
})


class ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.fig = Figure(figsize=(5, 3.5))
        self.fig.patch.set_facecolor(_BG0)
        self.ax  = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.12, right=0.95, top=0.88, bottom=0.13)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setStyleSheet(f"background: {_BG0}; border: none;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _reset(self, nrows=1, ncols=1, shared_x=False, ratios=None):
        self.fig.clear()
        self.fig.patch.set_facecolor(_BG0)
        kw = {}
        if ratios:
            kw["height_ratios" if nrows > 1 else "width_ratios"] = ratios
        if nrows == 1 and ncols == 1:
            self.ax = self.fig.add_subplot(111)
            self.ax.set_facecolor(_BG1)
            self.fig.subplots_adjust(left=0.12, right=0.95, top=0.88, bottom=0.13)
            return self.ax
        axes = self.fig.subplots(nrows, ncols, sharex=shared_x,
                                 gridspec_kw=kw if kw else None)
        self.fig.subplots_adjust(left=0.09, right=0.97, top=0.88, bottom=0.14,
                                 wspace=0.36, hspace=0.42)
        for ax in np.array(axes).flatten():
            ax.set_facecolor(_BG1)
        self.ax = np.array(axes).flatten()[0]
        return axes

    def _vline(self, ax, x, color, label="", ls="--", alpha=0.70):
        ax.axvline(x, color=color, lw=0.9, ls=ls, alpha=alpha, label=label)

    def _hline(self, ax, y, color, label="", ls="--"):
        ax.axhline(y, color=color, lw=0.8, ls=ls, alpha=0.65, label=label)

    def _style_ax(self, ax, title="", xlabel="", ylabel=""):
        ax.set_title(title, pad=7, color=_TXT0, fontsize=10, fontweight="bold")
        ax.set_xlabel(xlabel, labelpad=3, color=_TXT, fontsize=8.5)
        ax.set_ylabel(ylabel, labelpad=3, color=_TXT, fontsize=8.5)
        ax.tick_params(length=2.5, colors=_TXT, which="both")
        for sp in ["left", "bottom"]:
            ax.spines[sp].set_color(_EDGE)

    def _finish(self, ax=None, title="", xlabel="", ylabel=""):
        ax = ax or self.ax
        self._style_ax(ax, title, xlabel, ylabel)
        self.canvas.draw()

    # ── Option: Price · Delta profile ─────────────────────────────────────

    def plot_option(self, S, K, T, r, sigma, q, opt, model_fn):
        axes = self._reset(2, 2)
        ax_price, ax_delta, ax_gamma, ax_theta = axes.flatten()

        spots = np.linspace(S * 0.50, S * 1.50, 300)
        prices = []; deltas = []; gammas = []; thetas = []; intrs = []
        for s in spots:
            try:
                g = model_fn(s, K, T, r, sigma, q, opt)
                prices.append(g.price); deltas.append(g.delta)
                gammas.append(g.gamma); thetas.append(g.theta * 365)
            except Exception:
                prices.append(np.nan); deltas.append(np.nan)
                gammas.append(np.nan); thetas.append(np.nan)
            intrs.append(max(s-K,0) if opt=="call" else max(K-s,0))

        # Price
        ax_price.fill_between(spots, prices, alpha=0.13, color=C_ACCENT)
        ax_price.plot(spots, prices,  color=C_ACCENT, lw=2.0, label="Price")
        ax_price.plot(spots, intrs,   color=C_GREY,   lw=1.0, ls="--", label="Intrinsic")
        self._vline(ax_price, S, C_AMBER, f"S={S:.0f}")
        self._vline(ax_price, K, C_RED,   f"K={K:.0f}", ls=":")
        ax_price.legend(loc="upper left", fontsize=7.5)
        self._style_ax(ax_price, "Price", "Spot", "Value")

        # Delta
        ax_delta.fill_between(spots, deltas, alpha=0.13, color=C_BLUE)
        ax_delta.plot(spots, deltas, color=C_BLUE, lw=2.0)
        self._hline(ax_delta, 0.5, C_SLATE, ls=":")
        self._vline(ax_delta, S, C_AMBER); self._vline(ax_delta, K, C_RED, ls=":")
        self._style_ax(ax_delta, "Delta", "Spot", "Δ")

        # Gamma
        ax_gamma.fill_between(spots, gammas, alpha=0.13, color=C_GREEN)
        ax_gamma.plot(spots, gammas, color=C_GREEN, lw=2.0)
        self._vline(ax_gamma, S, C_AMBER); self._vline(ax_gamma, K, C_RED, ls=":")
        self._style_ax(ax_gamma, "Gamma", "Spot", "Γ")

        # Theta (annualised → daily shown)
        ax_theta.fill_between(spots, thetas, alpha=0.13, color=C_PURPLE)
        ax_theta.plot(spots, thetas, color=C_PURPLE, lw=2.0)
        self._hline(ax_theta, 0, C_SLATE)
        self._vline(ax_theta, S, C_AMBER); self._vline(ax_theta, K, C_RED, ls=":")
        self._style_ax(ax_theta, "Annual Theta", "Spot", "θ/yr")

        self.fig.suptitle(f"Greeks Profile  {'Call' if opt=='call' else 'Put'}  K={K:.0f}  T={T:.2f}y  σ={sigma:.0%}",
                          fontsize=9, color=_TXT, x=0.5, y=0.995, ha="center")
        self.canvas.draw()

    # ── Greeks ladder subplots ─────────────────────────────────────────────

    def plot_greeks_ladder(self, spots, prices, deltas, gammas, S, K):
        axes = self._reset(1, 3)
        data = [(prices,"Price",C_ACCENT), (deltas,"Delta",C_BLUE), (gammas,"Gamma",C_GREEN)]
        for ax, (y, lbl, col) in zip(axes, data):
            ax.fill_between(spots, y, alpha=0.12, color=col)
            ax.plot(spots, y, color=col, lw=1.9)
            self._vline(ax, S, C_AMBER); self._vline(ax, K, C_RED, ls=":")
            self._style_ax(ax, lbl, "Spot")
        self.fig.suptitle("Greeks Ladder", fontsize=9.5, fontweight="bold",
                          color=_TXT0, x=0.03, ha="left", y=0.98)
        self.canvas.draw()

    # ── Bond analysis ─────────────────────────────────────────────────────
    # Shows: Price-Yield curve, Duration sensitivity, Cash-flow bar

    def plot_bond_analysis(self, yields_pct, prices, dur_yields, durations,
                           cf_times, cf_vals, coupon_pct, rate_pct,
                           mac_dur, mod_dur, dv01):
        axes = self._reset(1, 3)
        ax_py, ax_dur, ax_cf = axes

        # 1. Price vs Yield
        ax_py.plot(yields_pct, prices, color=C_ACCENT, lw=2.0)
        ax_py.fill_between(yields_pct, prices, alpha=0.10, color=C_ACCENT)
        self._vline(ax_py, rate_pct, C_BLUE, f"r={rate_pct:.1f}%")
        if coupon_pct is not None:
            self._vline(ax_py, coupon_pct, C_AMBER, f"c={coupon_pct:.1f}%", ls=":")
        self._style_ax(ax_py, "Price vs Yield", "Yield (%)", "Price")

        # 2. Duration sensitivity
        ax_dur.plot(dur_yields, durations, color=C_BLUE, lw=2.0, label="Mod Duration")
        ax_dur.fill_between(dur_yields, durations, alpha=0.10, color=C_BLUE)
        ax_dur.axvline(rate_pct, color=C_AMBER, lw=0.9, ls="--", alpha=0.7)
        ax_dur.legend(fontsize=7.5)
        self._style_ax(ax_dur, "Duration Profile", "Yield (%)", "Years")

        # 3. Cash-flow bar
        if cf_times and cf_vals:
            colors = [C_AMBER if i < len(cf_times)-1 else C_ACCENT for i in range(len(cf_times))]
            ax_cf.bar(cf_times, cf_vals, color=colors, alpha=0.85, width=0.15, edgecolor="none")
            self._style_ax(ax_cf, "Cash Flows", "Time (yr)", "CF")
            ax_cf.set_xticks(cf_times)
            ax_cf.xaxis.set_major_formatter(mtick.FormatStrFormatter("%.1f"))

        self.fig.suptitle(
            f"Bond  MacD={mac_dur:.2f}y  ModD={mod_dur:.2f}y  DV01={dv01:.4f}",
            fontsize=9, color=_TXT, x=0.5, y=0.995, ha="center")
        self.canvas.draw()

    # ── Payoff diagram ────────────────────────────────────────────────────

    def plot_payoff(self, spots, payoffs, label="Payoff",
                    S=None, barriers=None, prices=None):
        ax = self._reset()
        ax.fill_between(spots, payoffs, alpha=0.12, color=C_ACCENT)
        ax.plot(spots, payoffs, color=C_ACCENT, lw=2.0, label=label)
        if prices is not None:
            ax.plot(spots, prices, color=C_BLUE, lw=1.8, ls="--", label="Price")
        if S:
            self._vline(ax, S, C_AMBER, f"S={S:.2f}")
        if barriers:
            for b in barriers:
                self._vline(ax, b, C_RED, f"H={b:.2f}", ls=":")
        ax.legend(loc="upper left")
        self._finish(ax, "Payoff at Expiry", "Spot", "Payoff")

    # ── Stress scenarios ──────────────────────────────────────────────────

    def plot_stress(self, scenarios, pnls):
        ax = self._reset()
        colors = [C_GREEN if p >= 0 else C_RED for p in pnls]
        y_pos  = list(range(len(scenarios)))
        bars = ax.barh(y_pos, pnls, color=colors, alpha=0.80,
                       edgecolor="none", height=0.60)
        ax.set_yticks(y_pos)
        ax.set_yticklabels([s[:26] for s in scenarios], fontsize=7.5, color=_TXT)
        ax.axvline(0, color=_EDGE, lw=0.8)
        ax.set_xlabel("P&L", color=_TXT)
        ax.grid(axis="x", alpha=0.25)
        ax.grid(axis="y", alpha=0)
        span = max(abs(v) for v in pnls) if pnls else 1
        for bar, v in zip(bars, pnls):
            x = bar.get_width()
            ax.text(x + span * 0.02, bar.get_y() + bar.get_height() / 2,
                    f"{v:+.4f}", va="center", ha="left", fontsize=7, color=_TXT)
        self._finish(ax, "Stress Test — P&L by Scenario")

    # ── VaR comparison: all methods on one plot ───────────────────────────

    def plot_var_comparison(self, returns, results_dict, position):
        """Show P&L histogram + VaR/CVaR lines for all methods."""
        ax = self._reset()
        pnl = np.sort(returns * position)

        ax.hist(pnl, bins=60, color=C_ACCENT, alpha=0.35,
                edgecolor="none", label="P&L dist.", zorder=1)
        # Tail fill
        colors_m = {"Historical": C_RED, "Parametric": C_AMBER,
                    "Monte Carlo": C_BLUE, "EVT": C_PURPLE}
        ls_map   = {"Historical": "-", "Parametric": "--",
                    "Monte Carlo": (0,(4,2)), "EVT": ":"}
        for name, res in results_dict.items():
            if "VaR" not in res: continue
            col = colors_m.get(name, C_GREY)
            ls  = ls_map.get(name, "--")
            ax.axvline(-res["VaR"],  color=col, lw=1.6, ls=ls, alpha=0.85,
                       label=f"{name} VaR {res['VaR']:,.0f}", zorder=3)
            if "CVaR" in res:
                ax.axvline(-res["CVaR"], color=col, lw=0.9, ls=":",
                           alpha=0.55, zorder=2)
        ax.legend(loc="upper left", fontsize=7.5)
        self._finish(ax, "P&L Distribution + VaR/CVaR Comparison", "P&L", "Frequency")

    def plot_var_distribution(self, returns, var_val, cvar_val, position):
        ax = self._reset()
        pnl = np.sort(returns * position)
        ax.hist(pnl, bins=55, color=C_ACCENT, alpha=0.40,
                edgecolor="none", label="P&L distribution")
        tail_mask = pnl <= -var_val
        if tail_mask.any():
            ax.hist(pnl[tail_mask], bins=30, color=C_RED, alpha=0.65,
                    edgecolor="none", label="Tail loss")
        ax.axvline(-var_val,  color=C_RED,   lw=2.0, ls="--",
                   label=f"VaR  {var_val:,.0f}", zorder=4)
        ax.axvline(-cvar_val, color=C_AMBER, lw=2.0, ls=":",
                   label=f"CVaR {cvar_val:,.0f}", zorder=4)
        ax.legend(loc="upper left")
        self._finish(ax, "P&L Distribution", "P&L", "Frequency")

    # ── Yield curve ───────────────────────────────────────────────────────

    def plot_yield_curve(self, tenors, rates, label="Flat curve",
                         tenors2=None, rates2=None, label2=None):
        ax = self._reset()
        ax.plot(tenors, [r*100 for r in rates],
                color=C_ACCENT, lw=2.0, marker="o", ms=4.5,
                markerfacecolor=_BG1, markeredgewidth=1.4,
                markeredgecolor=C_ACCENT, label=label)
        ax.fill_between(tenors, [r*100 for r in rates], alpha=0.10, color=C_ACCENT)
        if tenors2 is not None and rates2 is not None:
            ax.plot(tenors2, [r*100 for r in rates2],
                    color=C_BLUE, lw=1.8, marker="s", ms=4,
                    markerfacecolor=_BG1, markeredgewidth=1.2,
                    markeredgecolor=C_BLUE, label=label2 or "Curve 2", ls="--")
        ax.legend()
        self._finish(ax, "Yield Curve", "Maturity (years)", "Rate (%)")

    # ── Vol smile ─────────────────────────────────────────────────────────

    def plot_vol_smile(self, strikes, vols, F=None,
                       strikes2=None, vols2=None, label2=None):
        ax = self._reset()
        ax.plot(strikes, [v*100 for v in vols],
                color=C_PURPLE, lw=2.0, marker="o", ms=4,
                markerfacecolor=_BG1, markeredgewidth=1.3,
                markeredgecolor=C_PURPLE, label="IV Smile")
        ax.fill_between(strikes, [v*100 for v in vols], alpha=0.10, color=C_PURPLE)
        if strikes2 is not None:
            ax.plot(strikes2, [v*100 for v in vols2],
                    color=C_ACCENT, lw=1.8, ls="--", label=label2 or "Model")
        if F:
            self._vline(ax, F, C_AMBER, f"Fwd={F:.4f}")
        ax.legend()
        self._finish(ax, "Implied Volatility Smile", "Strike", "IV (%)")

    # ── Time decay ────────────────────────────────────────────────────────

    def plot_time_decay(self, days, prices, current_price=None, prices2=None, label2=None):
        ax = self._reset()
        ax.fill_between(days, prices, alpha=0.12, color=C_ACCENT)
        ax.plot(days, prices, color=C_ACCENT, lw=2.0, label="Price")
        if prices2 is not None:
            ax.plot(days, prices2, color=C_BLUE, lw=1.8, ls="--",
                    label=label2 or "Scenario 2")
        if current_price is not None:
            self._hline(ax, current_price, C_GREY, "Current")
        ax.legend()
        self._finish(ax, "Time Decay (Theta)", "Days to Expiry", "Option Price")

    # ── CDS / credit ──────────────────────────────────────────────────────

    def plot_survival_curve(self, tenors, surv_probs, tenors2=None, surv2=None):
        ax = self._reset()
        ax.fill_between(tenors, surv_probs, 1, alpha=0.10, color=C_RED, label="Default")
        ax.fill_between(tenors, 0, surv_probs, alpha=0.12, color=C_GREEN, label="Survival")
        ax.plot(tenors, surv_probs, color=C_GREEN, lw=2.0)
        if tenors2 is not None and surv2 is not None:
            ax.plot(tenors2, surv2, color=C_ACCENT, lw=1.8, ls="--", label="Scenario 2")
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1))
        ax.legend()
        self._finish(ax, "Survival Probability Curve", "Maturity (years)", "Q(τ > T)")

    # ── Monte Carlo paths ─────────────────────────────────────────────────

    def plot_mc_paths(self, times, paths, percentiles=None, final_dist=None):
        """Plot simulated paths + percentile bands + final distribution."""
        if final_dist is not None:
            axes = self._reset(1, 2, ratios=[3, 1])
            ax_paths, ax_hist = axes
        else:
            ax_paths = self._reset()
            ax_hist  = None

        n_show = min(80, paths.shape[0])
        for i in range(n_show):
            ax_paths.plot(times, paths[i], color=C_ACCENT, alpha=0.06, lw=0.6)

        if percentiles is not None:
            p5, p50, p95 = percentiles
            ax_paths.fill_between(times, p5, p95, color=C_ACCENT, alpha=0.18, label="5–95%")
            ax_paths.plot(times, p50, color=C_ACCENT, lw=2.0, label="Median")
            ax_paths.plot(times, p5,  color=C_RED,    lw=1.2, ls="--", alpha=0.7)
            ax_paths.plot(times, p95, color=C_GREEN,  lw=1.2, ls="--", alpha=0.7)

        ax_paths.legend(fontsize=7.5)
        self._style_ax(ax_paths, "Monte Carlo Paths", "Time", "Value")

        if ax_hist is not None and final_dist is not None:
            ax_hist.hist(final_dist, bins=40, orientation="horizontal",
                         color=C_ACCENT, alpha=0.55, edgecolor="none")
            ax_hist.axhline(np.percentile(final_dist, 5),  color=C_RED,   lw=1.2, ls="--")
            ax_hist.axhline(np.percentile(final_dist, 95), color=C_GREEN, lw=1.2, ls="--")
            ax_hist.set_yticks([])
            ax_hist.set_xlabel("Freq", color=_TXT, fontsize=8)
            self._style_ax(ax_hist, "Final Dist.", "")

        self.canvas.draw()

    # ── Short-rate / yield evolution ──────────────────────────────────────

    def plot_rate_paths(self, times, paths, label="Rate"):
        ax = self._reset()
        n_show = min(60, paths.shape[0])
        for i in range(n_show):
            ax.plot(times, paths[i] * 100, color=C_ACCENT, alpha=0.07, lw=0.6)
        p5  = np.percentile(paths, 5, axis=0) * 100
        p50 = np.percentile(paths, 50, axis=0) * 100
        p95 = np.percentile(paths, 95, axis=0) * 100
        ax.fill_between(times, p5, p95, color=C_ACCENT, alpha=0.20, label="5–95%")
        ax.plot(times, p50, color=C_ACCENT, lw=2.0, label="Median")
        ax.plot(times, p5,  color=C_RED,    lw=1.1, ls="--", alpha=0.70)
        ax.plot(times, p95, color=C_GREEN,  lw=1.1, ls="--", alpha=0.70)
        ax.legend()
        self._finish(ax, f"{label} Simulated Paths", "Time (years)", "Rate (%)")

    # ── Portfolio / multi-asset ────────────────────────────────────────────

    def plot_portfolio(self, labels, weights, returns_ann, vols_ann):
        """Pie (weights) + scatter (risk-return) side by side."""
        axes = self._reset(1, 2)
        ax_pie, ax_rr = axes

        colors_p = [C_ACCENT, C_BLUE, C_GREEN, C_PURPLE,
                    C_AMBER, C_TEAL, C_RED, C_GREY][:len(labels)]
        wedges, texts, autotexts = ax_pie.pie(
            weights, labels=labels, autopct="%1.1f%%",
            colors=colors_p, startangle=90,
            textprops={"color": _TXT, "fontsize": 7.5},
            wedgeprops={"linewidth": 0.5, "edgecolor": _BG0})
        for at in autotexts:
            at.set_color(_TXT0); at.set_fontsize(7)
        ax_pie.set_facecolor(_BG1)
        self._style_ax(ax_pie, "Portfolio Weights")

        # Risk-return scatter
        for i, lbl in enumerate(labels):
            col = colors_p[i % len(colors_p)]
            ax_rr.scatter(vols_ann[i]*100, returns_ann[i]*100,
                          color=col, s=60, zorder=3, edgecolors="none")
            ax_rr.annotate(lbl, (vols_ann[i]*100, returns_ann[i]*100),
                           textcoords="offset points", xytext=(5, 4),
                           fontsize=7, color=_TXT)
        self._hline(ax_rr, 0, C_SLATE)
        ax_rr.set_xlabel("Vol (% ann.)", color=_TXT, fontsize=8)
        ax_rr.set_ylabel("Return (% ann.)", color=_TXT, fontsize=8)
        self._style_ax(ax_rr, "Risk–Return")

        self.canvas.draw()

    # ── Clear placeholder ─────────────────────────────────────────────────

    # ── Market-data views (Stage V) ───────────────────────────────────────

    _SERIES_COLORS = (C_ACCENT, C_BLUE, C_GREEN, C_PURPLE, C_AMBER, C_TEAL, C_RED)

    def plot_curves(self, series, title="Yield Curves",
                    xlabel="Maturity (years)", ylabel="Rate (%)"):
        """Overlay N curves. series = [(label, xs, ys), ...] (ys already in %)."""
        ax = self._reset()
        for i, (label, xs, ys) in enumerate(series):
            col = self._SERIES_COLORS[i % len(self._SERIES_COLORS)]
            ax.plot(xs, ys, color=col, lw=1.9, marker="o", ms=3.5,
                    markerfacecolor=_BG1, markeredgecolor=col, label=label)
        if series:
            ax.legend(loc="best", fontsize=7.5)
        self._finish(ax, title, xlabel, ylabel)

    def plot_series(self, x, ys, title="History", xlabel="Date", ylabel="Value",
                    max_xticks=8):
        """
        Time/sequence series. x = labels (e.g. dates), ys = [(label, values), ...].
        x ticks are thinned to max_xticks for readability.
        """
        ax = self._reset()
        idx = list(range(len(x)))
        for i, (label, values) in enumerate(ys):
            col = self._SERIES_COLORS[i % len(self._SERIES_COLORS)]
            ax.plot(idx, values, color=col, lw=1.8, label=label)
            if len(ys) == 1:
                ax.fill_between(idx, values, alpha=0.10, color=col)
        if len(x) > max_xticks:
            step = max(1, len(x) // max_xticks)
            ax.set_xticks(idx[::step])
            ax.set_xticklabels([str(x[i])[:10] for i in idx[::step]],
                               rotation=30, ha="right", fontsize=7)
        else:
            ax.set_xticks(idx)
            ax.set_xticklabels([str(v)[:10] for v in x], rotation=30,
                               ha="right", fontsize=7)
        if len(ys) > 1:
            ax.legend(loc="best", fontsize=7.5)
        self._finish(ax, title, xlabel, ylabel)

    def plot_heatmap(self, matrix, labels, title="Correlation"):
        """Correlation/heatmap with annotated cells. matrix = list[list[float]]."""
        ax = self._reset()
        m = np.array(matrix, dtype=float)
        im = ax.imshow(m, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7, color=_TXT)
        ax.set_yticklabels(labels, fontsize=7, color=_TXT)
        n = len(labels)
        if n <= 12:
            for i in range(n):
                for j in range(n):
                    ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center",
                            fontsize=6.5,
                            color="#ffffff" if abs(m[i, j]) > 0.55 else _TXT0)
        cbar = self.fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.ax.tick_params(colors=_TXT, labelsize=7)
        ax.set_title(title, pad=7, color=_TXT0, fontsize=10, fontweight="bold")
        self.canvas.draw()

    def clear(self):
        ax = self._reset()
        ax.text(0.5, 0.5, "Press Calculate to see chart",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color="#3a3a42", style="italic")
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.grid(False)
        self.canvas.draw()
