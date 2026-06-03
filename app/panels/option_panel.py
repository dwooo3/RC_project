"""Vanilla / American / Bermudan option panel — refined."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QSplitter, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer

from app.widgets import (ModelStatus, 
    ParamForm, FieldRow, ResultsGrid, SectionHeader,
    Banner, make_spin, make_pct, make_combo
)
from app.chart import ChartWidget


class OptionPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._auto_calculate)
        self._build_ui()
        # Show default chart immediately
        self.chart.clear()

    # ── Build ─────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #2e2e33; }")

        # ── Left: param form ─────────────────────────────
        left = QWidget()
        left.setObjectName("center_panel")
        left.setMinimumWidth(330)
        left.setMaximumWidth(400)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        ll.addWidget(SectionHeader("Options",
                 "European  ·  American  ·  Bermudan",
                 status=ModelStatus.APPROXIMATION))

        self.banner = Banner()
        ll.addWidget(self.banner)

        form = ParamForm()

        # Spinboxes — no button arrows, period separator
        self.spot   = make_spin(0.01, 1e9, 100.0,  1.0,  2)
        self.strike = make_spin(0.01, 1e9, 100.0,  1.0,  2)
        self.expiry = make_spin(0.001, 50,  0.25, 0.01,  3, "yr")
        self.rate   = make_pct(0.05, -0.5,  0.5)
        self.sigma  = make_pct(0.20,  0.01, 5.0)
        self.div    = make_pct(0.00, -0.5,  1.0)
        self.opt    = make_combo(["Call", "Put"])
        self.extype = make_combo(["European", "American", "Bermudan"])
        self.model  = make_combo([
            "BSM", "Black-76", "Garman-Kohlhagen", "Bachelier",
            "Binomial CRR", "Binomial LR", "Trinomial",
            "Monte Carlo", "LSM",
        ])

        form.add_group("Market Parameters", [
            FieldRow("Spot (S)",          self.spot,   "Current price of the underlying"),
            FieldRow("Strike (K)",        self.strike, "Strike price of the option"),
            FieldRow("Expiry (T)",        self.expiry, "Time to expiration in years"),
            FieldRow("Risk-free rate (r)",self.rate,   "Annual continuously-compounded rate"),
            FieldRow("Volatility (σ)",    self.sigma,  "Annual implied volatility"),
            FieldRow("Dividend yield (q)",self.div,    "Continuous dividend yield"),
        ])
        form.add_group("Option Settings", [
            FieldRow("Type",     self.opt,    "Call or Put"),
            FieldRow("Exercise", self.extype, "European / American / Bermudan"),
            FieldRow("Model",    self.model,  "Pricing model"),
        ])
        ll.addWidget(form, 1)

        # Buttons
        btn_bar = QWidget()
        btn_bar.setStyleSheet("background: #1c1c1e; border-top: 1px solid #2c2c2e;")
        br = QHBoxLayout(btn_bar)
        br.setContentsMargins(16, 12, 16, 14)
        br.setSpacing(8)

        self.btn_calc = QPushButton("Calculate")
        self.btn_calc.setObjectName("calc_btn")
        self.btn_calc.setFixedHeight(38)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("clear_btn")
        self.btn_clear.setFixedHeight(38)
        self.btn_clear.setFixedWidth(90)

        br.addWidget(self.btn_calc, 1)
        br.addWidget(self.btn_clear)
        ll.addWidget(btn_bar)

        self.btn_calc.clicked.connect(self.calculate)
        self.btn_clear.clicked.connect(self.clear)

        # Auto-calculate on change (debounced 400ms)
        for w in [self.spot, self.strike, self.expiry,
                  self.rate, self.sigma, self.div]:
            w.valueChanged.connect(self._schedule_auto)
        for w in [self.opt, self.extype, self.model]:
            w.currentIndexChanged.connect(self._schedule_auto)

        # ── Right: results ───────────────────────────────
        right = QWidget()
        right.setObjectName("results_panel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        # Results header
        hdr = QWidget()
        hdr.setObjectName("results_header")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 10, 18, 10)
        hl.setSpacing(0)
        res_lbl = QLabel("RESULTS")
        res_lbl.setObjectName("results_title_lbl")
        hl.addWidget(res_lbl)
        hl.addStretch()
        self._model_badge = QLabel("")
        self._model_badge.setStyleSheet(
            "background:#3a2518; color:#d97757; border-radius:5px;"
            "padding:2px 8px; font-size:10px; font-weight:600;")
        hl.addWidget(self._model_badge)
        rl.addWidget(hdr)

        # Metric grid — price highlighted
        self.grid = ResultsGrid(
            ["Price", "Delta", "Gamma",
             "Vega",  "Theta", "Rho",
             "Vanna", "Volga", "IV (BSM)",
             "Intrinsic", "Time Value", "Leverage"],
            cols=3, highlight="Price",
        )
        rl.addWidget(self.grid)

        # Thin separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2c2c2e; margin: 0;")
        rl.addWidget(sep)

        self.chart = ChartWidget()
        rl.addWidget(self.chart, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([370, 900])
        root.addWidget(splitter)

    # ── Auto-calc debounce ────────────────────────────────

    def _schedule_auto(self):
        # Only auto-calc for fast models
        fast = self.model.currentText() in (
            "BSM", "Black-76", "Garman-Kohlhagen", "Bachelier",
            "Binomial CRR", "Binomial LR", "Trinomial",
        )
        if fast:
            self._debounce.start(350)

    def _auto_calculate(self):
        try:
            self.calculate(silent=True)
        except Exception:
            pass

    # ── Main calculation ──────────────────────────────────

    def calculate(self, silent=False):
        self.banner.clear()
        p = self._params()
        model_key = {
            "BSM":              "bsm",
            "Black-76":         "black76",
            "Garman-Kohlhagen": "gk",
            "Bachelier":        "bachelier",
            "Binomial CRR":     "binomial",
            "Binomial LR":      "binomial_lr",
            "Trinomial":        "trinomial",
            "Monte Carlo":      "mc",
            "LSM":              "lsm",
        }[self.model.currentText()]
        extype = self.extype.currentText().lower()

        try:
            from instruments.vanilla import european, american, bermudan

            _safe_model = model_key
            if extype != "european" and model_key in ("bsm","gk","bachelier","black76"):
                _safe_model = "binomial"

            if extype == "european":
                res = european(**p, model=model_key)
            elif extype == "american":
                res = american(**p, model=_safe_model)
            else:
                dates = [p["T"] * i / 4 for i in range(1, 5)]
                res = bermudan(**p, exercise_dates=dates, model=_safe_model)

            price    = res.get("price", 0)
            delta    = res.get("delta", 0)
            gamma    = res.get("gamma", 0)
            vega     = res.get("vega",  0)
            theta    = res.get("theta", 0)
            rho      = res.get("rho",   0)
            vanna    = res.get("vanna", 0)
            volga    = res.get("volga", 0)

            intrinsic = max(p["S"]-p["K"], 0) if p["opt"]=="call" else max(p["K"]-p["S"], 0)
            time_val  = max(price - intrinsic, 0)
            leverage  = delta * p["S"] / price if price > 1e-8 else 0

            self.grid.set("Price",      price,     color="#d97757")
            self.grid.set("Delta",      delta)
            self.grid.set("Gamma",      gamma)
            self.grid.set("Vega",       vega,      sub="per 1% vol move")
            self.grid.set("Theta",      theta,     sub="per calendar day")
            self.grid.set("Rho",        rho,       sub="per 1% rate move")
            self.grid.set("Vanna",      vanna)
            self.grid.set("Volga",      volga)
            self.grid.set("Intrinsic",  intrinsic)
            self.grid.set("Time Value", time_val)
            self.grid.set("Leverage",   leverage,  sub="delta × S / price")

            # Implied vol
            try:
                from models.implied_vol import implied_vol_bsm
                iv = implied_vol_bsm(price, p["S"], p["K"], p["T"],
                                     p["r"], p["q"], p["opt"])
                if iv == iv:
                    self.grid.set("IV (BSM)", iv, sub=f"{iv*100:.2f}%")
            except Exception:
                pass

            self._model_badge.setText(self.model.currentText())

            # Chart: BSM profile regardless of selected model (fast)
            from models.black_scholes import bsm as _bsm
            self.chart.plot_option(
                p["S"], p["K"], p["T"], p["r"], p["sigma"], p["q"], p["opt"], _bsm
            )

        except Exception as e:
            if not silent:
                self.banner.show_error(str(e))

    def _params(self):
        return dict(
            S=self.spot.value(),
            K=self.strike.value(),
            T=self.expiry.value(),
            r=self.rate.value() / 100,
            sigma=self.sigma.value() / 100,
            q=self.div.value() / 100,
            opt=self.opt.currentText().lower(),
        )

    def clear(self):
        self.grid.clear_all()
        self.chart.clear()
        self.banner.clear()
        self._model_badge.setText("")
