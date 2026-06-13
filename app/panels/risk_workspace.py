"""Risk Workspace v1 backed by RiskService."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from datetime import UTC, datetime

import numpy as np
from PySide6.QtWidgets import QTabWidget

from services.market_data_service import MarketDataService
from services.risk_service import RiskService
from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class RiskWorkspace(WorkstationWorkspace):
    """Unified risk workstation for VaR, stress, backtesting, and capital."""

    def __init__(self, parent=None):
        from app.runtime import active_snapshot, market_service
        self.calculation_timestamp = datetime.now(UTC).replace(microsecond=0)
        self.market_data = market_service()
        self._db = getattr(self.market_data, "market_db", None)
        self.snapshot = active_snapshot(self.market_data)
        self.risk_service = RiskService(market_data=self.market_data)
        self.returns = self._demo_returns()
        self.position_value = 1_000_000.0
        self.confidence = 0.99
        self.horizon = 10
        self.var_results = self._calculate_var_results()
        self.stress_result = self._calculate_stress()

        super().__init__(
            "Risk",
            "Unified risk workstation for VaR, stress, backtesting, and capital",
            chips=self._chips(),
            actions=[
                make_action("Run VaR", primary=True),
                make_action("Run Stress"),
                make_action("Backtest"),
                make_action("Export"),
            ],
            kpi_strip=self._summary_kpis(),
            left=self._risk_controls_panel(),
            center=self._risk_tabs(),
            right=self._metadata_panel(),
            bottom=self._calculation_log_panel(),
            context_items=self._context_items(),
            parent=parent,
        )

    def _demo_returns(self):
        rng = np.random.default_rng(42)
        return rng.normal(0.0001, 0.0125, 1000)

    def _calculate_var_results(self):
        kwargs = dict(
            returns=self.returns,
            position_value=self.position_value,
            confidence=self.confidence,
            horizon=self.horizon,
            snapshot=self.snapshot,
        )
        return {
            "Historical": self.risk_service.historical_var(**kwargs),
            "Parametric": self.risk_service.parametric_var(**kwargs),
            "Monte Carlo": self.risk_service.monte_carlo_var(**kwargs, n_sims=20_000),
        }

    def _calculate_stress(self):
        return self.risk_service.stress_option(
            100.0,
            100.0,
            1.0,
            0.05,
            0.20,
            opt="call",
            position=1000.0,
            snapshot=self.snapshot,
        )

    def _chips(self):
        worst_status = self._worst_model_status()
        return [
            DataSourceChip(self.snapshot.source.value),
            StatusChip(worst_status, text=f"Model: {worst_status}"),
        ]

    def _worst_model_status(self):
        order = ["Validated", "Approximation", "Prototype", "Placeholder", "Broken"]
        statuses = [result.get("model_status", "Validated") for result in self.var_results.values()]
        statuses.append(self.stress_result.get("model_status", "Validated"))
        return max(statuses, key=lambda status: order.index(status) if status in order else 0)

    def _summary_kpis(self):
        historical = self.var_results["Historical"].get("raw") or {}
        parametric = self.var_results["Parametric"].get("raw") or {}
        monte_carlo = self.var_results["Monte Carlo"].get("raw") or {}
        stress_value = self.stress_result.get("value") or 0.0
        exceptions = self._backtest_exceptions(historical.get("VaR_pct", 0.0))
        return KpiStrip(
            [
                ("Historical VaR", self._money(historical.get("VaR", 0.0)), "99% / 10d"),
                ("Parametric VaR", self._money(parametric.get("VaR", 0.0)), "normal"),
                ("Monte Carlo VaR", self._money(monte_carlo.get("VaR", 0.0)), "20k sims"),
                ("Historical ES", self._money(historical.get("CVaR", 0.0)), "tail loss"),
                ("Worst Stress", self._money(stress_value), "option stress"),
                ("Exceptions", str(exceptions), "demo backtest"),
            ]
        )

    def _risk_controls_panel(self):
        panel = WorkstationPanel("Risk Controls")
        panel.layout.addWidget(
            DenseTable(
                ["Control", "Value"],
                [
                    ["Scope", "Main Portfolio proxy"],
                    ["Position Value", self._money(self.position_value)],
                    ["Confidence", f"{self.confidence:.2%}"],
                    ["Horizon", f"{self.horizon}d"],
                    ["Observations", str(len(self.returns))],
                    ["Returns Source", "DEMO generated returns"],
                    ["Calculation Time", self._timestamp()],
                ],
            )
        )
        return panel

    def _risk_tabs(self):
        tabs = QTabWidget()
        tabs.addTab(self._var_tab(), "VaR")
        tabs.addTab(self._decomposition_tab(), "Decomposition")
        tabs.addTab(self._scenarios_tab(), "Scenarios")
        tabs.addTab(self._stress_tab(), "Stress")
        tabs.addTab(self._xva_tab(), "XVA")
        tabs.addTab(self._backtesting_tab(), "Backtesting")
        tabs.addTab(self._capital_tab(), "Capital")
        tabs.addTab(self._factors_tab(), "Factors")
        return tabs

    def _analytics_portfolio(self):
        """A representative demo book for the institutional analytics views."""
        if getattr(self, "_an_ps", None) is not None:
            return self._an_ps
        from domain.portfolio import Portfolio, Position
        from services.portfolio_service import PortfolioService
        book = Portfolio(name="Risk demo", positions=[
            Position(id="opt_sber", instrument="call", description="SBER call",
                     quantity=500, params=dict(S=322.0, K=340.0, T=0.5, r=0.14, sigma=0.30)),
            Position(id="ofz_5y", instrument="bond", description="OFZ 5Y",
                     quantity=2000, params=dict(face=1000, coupon=0.12, T=5, freq=2, r=0.14)),
            Position(id="eq_gazp", instrument="equity", description="GAZP",
                     quantity=20000, params=dict(S=113.0)),
            Position(id="eq_lkoh", instrument="equity", description="LUKOIL",
                     quantity=1000, params=dict(S=4734.0)),
        ])
        self._an_ps = PortfolioService(book, market_data=self.market_data)
        return self._an_ps

    def _decomposition_tab(self):
        """Risk decomposition by factor / bucket / position (Aladdin-style)."""
        from services import analytics_views as av
        panel = WorkstationPanel("Risk Decomposition")
        try:
            d = av.risk_decomposition(self._analytics_portfolio())
        except Exception as exc:
            panel.layout.addWidget(DenseTable(["Error"], [[str(exc)[:120]]]))
            return panel
        panel.layout.addWidget(DenseTable(
            ["Bucket", "|Contribution|"],
            [[b, self._money(v)] for b, v in sorted(d["by_bucket"].items(),
                                                    key=lambda x: -x[1])]))
        panel.layout.addWidget(DenseTable(
            ["Factor", "Bucket", "Sensitivity", "Contribution"],
            [[r["factor"], r["bucket"], f"{r['sensitivity']:,.2f}",
              self._money(r["contribution"])] for r in d["by_factor"][:15]]))
        panel.layout.addWidget(DenseTable(
            ["Position", "Instrument", "Market Value", "DV01", "Delta", "Vega"],
            [[r["id"], r["instrument"], self._money(r["mv"]),
              f"{r['dv01']:,.1f}", f"{r['delta']:,.1f}", f"{r['vega']:,.1f}"]
             for r in d["by_position"]]))
        try:
            from app.chart import ChartWidget
            if d["by_bucket"]:
                chart = ChartWidget()
                chart.setMinimumHeight(240)
                items = sorted(d["by_bucket"].items(), key=lambda x: -x[1])
                chart.plot_curves([("contribution", list(range(len(items))),
                                    [v for _, v in items])],
                                  title="Risk by bucket", xlabel="bucket", ylabel="|contribution|")
                panel.layout.addWidget(chart)
        except Exception:
            pass
        return panel

    def _scenarios_tab(self):
        """Named stress library via full-reprice P&L."""
        from services import analytics_views as av
        panel = WorkstationPanel("Scenario Library (full-reprice)")
        try:
            lib = av.scenario_library(self._analytics_portfolio())
        except Exception as exc:
            panel.layout.addWidget(DenseTable(["Error"], [[str(exc)[:120]]]))
            return panel
        panel.layout.addWidget(DenseTable(
            ["Scenario", "P&L", "Shocks"],
            [[s["name"], self._money(s["pnl"]),
              ", ".join(f"{k}={v:+g}" for k, v in s["shocks"].items())]
             for s in lib["scenarios"]]))
        try:
            from app.chart import ChartWidget
            chart = ChartWidget()
            chart.setMinimumHeight(240)
            names = [s["name"] for s in lib["scenarios"]]
            chart.plot_series(names, [("P&L", [s["pnl"] for s in lib["scenarios"]])],
                              title="Scenario P&L", ylabel="P&L")
            panel.layout.addWidget(chart)
        except Exception:
            pass
        return panel

    def _xva_tab(self):
        """XVA dashboard: EPE/ENE/PFE profiles + CVA/DVA from exposure simulation."""
        from services import analytics_views as av
        panel = WorkstationPanel("XVA — IRS counterparty exposure")
        try:
            x = av.xva_profile(self.risk_service, n_sims=2000, n_grid=20)
        except Exception as exc:
            panel.layout.addWidget(DenseTable(["Error"], [[str(exc)[:120]]]))
            return panel
        if x.get("errors"):
            panel.layout.addWidget(DenseTable(["Error"], [["; ".join(x["errors"])[:120]]]))
            return panel
        panel.layout.addWidget(DenseTable(
            ["Metric", "Value"],
            [["CVA", self._money(x["cva"])], ["DVA", self._money(x.get("dva") or 0)],
             ["BCVA", self._money(x.get("bcva") or 0)],
             ["Peak PFE (95%)", self._money(x["peak_pfe"])]]))
        try:
            from app.chart import ChartWidget
            chart = ChartWidget()
            chart.setMinimumHeight(260)
            t = [f"{v:.1f}" for v in x["times"]]
            chart.plot_series(t, [("EPE", x["epe"]), ("PFE 95%", x["pfe95"]),
                                  ("PFE 99%", x["pfe99"])],
                              title="Exposure profile", xlabel="years", ylabel="exposure")
            panel.layout.addWidget(chart)
        except Exception:
            pass
        return panel

    def _factors_tab(self):
        """Risk-factor annualised vols + correlation matrix from real history."""
        panel = WorkstationPanel("Risk Factors (return history)")
        if self._db is None:
            panel.layout.addWidget(DenseTable(
                ["Status"], [["Demo mode — connect a market-data DB for factor history"]]))
            return panel
        from services import market_views as mv
        candidates = ["IMOEX:price", "SBER:price", "GAZP:price", "LKOH:price",
                      "ROSN:price", "GMKN:price", "PLZL:price", "VTBR:price"]
        have = {r["factor_id"] for r in self._db._query(
            "SELECT DISTINCT factor_id FROM time_series WHERE kind='price'")}
        factors = [f for f in candidates if f in have]
        if not factors:
            panel.layout.addWidget(DenseTable(["Status"], [["No factor history ingested yet"]]))
            return panel
        fs = mv.factor_series(self.market_data, factors)
        panel.layout.addWidget(DenseTable(
            ["Factor", "Ann. vol", "Observations"],
            [[f, f"{fs['ann_vol'][f]:.1f}%", fs["n_obs"]] for f in fs["factors"]]))
        # factor model: beta to benchmark, systematic vs idiosyncratic (P2)
        try:
            from services import analytics_views as av
            fm = av.factor_model(self.market_data,
                                 [f for f in factors if f != "IMOEX:price"],
                                 "IMOEX:price")
            if fm["factors"]:
                panel.layout.addWidget(DenseTable(
                    ["Factor", "Beta (IMOEX)", "Systematic %", "Idio vol", "Total vol"],
                    [[r["factor"].replace(":price", ""), f"{r['beta']:.2f}",
                      f"{r['systematic_pct']:.0f}%", f"{r['idio_vol']:.1f}%",
                      f"{r['total_vol']:.1f}%"] for r in fm["factors"]]))
        except Exception:
            pass
        # correlation matrix (table + heatmap)
        names = [f.replace(":price", "") for f in fs["factors"]]
        header = ["Corr"] + names
        corr_rows = [[names[i]] + [f"{fs['correlation'][i][j]:.2f}"
                                   for j in range(len(names))]
                     for i in range(len(names))]
        panel.layout.addWidget(DenseTable(header, corr_rows))
        try:
            from app.chart import ChartWidget
            if len(names) > 1:
                chart = ChartWidget()
                chart.setMinimumHeight(280)
                chart.plot_heatmap(fs["correlation"], names,
                                   title="Factor correlation")
                panel.layout.addWidget(chart)
        except Exception:
            pass
        return panel

    def _var_tab(self):
        panel = WorkstationPanel("VaR")
        rows = []
        for method, result in self.var_results.items():
            raw = result.get("raw") or {}
            rows.append(
                [
                    method,
                    self._money(raw.get("VaR", 0.0)),
                    self._money(raw.get("CVaR", raw.get("ES", 0.0))),
                    result.get("model_id", ""),
                    result.get("model_status", ""),
                    result.get("market_data_source", ""),
                    self._timestamp(),
                    len(result.get("warnings", [])),
                    "; ".join(result.get("errors", [])),
                ]
            )
        panel.layout.addWidget(
            DenseTable(
                [
                    "Method",
                    "VaR",
                    "ES",
                    "Model ID",
                    "Model Status",
                    "Market Source",
                    "Timestamp",
                    "Warnings",
                    "Errors",
                ],
                rows,
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Convention", "Value"],
                [
                    ["Loss sign", "Positive losses"],
                    ["Confidence interpretation", "Positive loss quantile"],
                    ["Horizon scaling", f"{self.horizon} day"],
                    ["ES consistency", "ES >= VaR enforced in engines"],
                ],
            )
        )
        return panel

    def _stress_tab(self):
        panel = WorkstationPanel("Stress")
        raw = self.stress_result.get("raw") or []
        rows = []
        for scenario in raw[:20]:
            rows.append(
                [
                    scenario.get("scenario", ""),
                    scenario.get("dS", scenario.get("spot_shift", "")),
                    scenario.get("dVol", scenario.get("vol_shift", "")),
                    self._money(scenario.get("price", 0.0)),
                    self._money(scenario.get("pnl", 0.0)),
                ]
            )
        panel.layout.addWidget(DenseTable(["Scenario", "Spot Shock", "Vol Shock", "Price", "P&L"], rows))
        panel.layout.addWidget(
            DenseTable(
                ["Metadata", "Value"],
                [
                    ["Model ID", self.stress_result.get("model_id", "")],
                    ["Model Status", self.stress_result.get("model_status", "")],
                    ["Market Source", self.stress_result.get("market_data_source", "")],
                    ["Timestamp", self._timestamp()],
                    ["Warnings", str(len(self.stress_result.get("warnings", [])))],
                ],
            )
        )
        return panel

    def _backtesting_tab(self):
        panel = WorkstationPanel("Backtesting")
        hist_raw = self.var_results["Historical"].get("raw") or {}
        var_pct = hist_raw.get("VaR_pct", 0.0)
        exceptions = self._backtest_exceptions(var_pct)
        expected = max((1 - self.confidence) * len(self.returns), 0.0)
        zone = "Green" if exceptions <= max(expected * 2, 1) else "Amber"
        panel.layout.addWidget(
            DenseTable(
                ["Metric", "Value"],
                [
                    ["VaR Run", "Historical"],
                    ["Observed Exceptions", str(exceptions)],
                    ["Expected Exceptions", f"{expected:.2f}"],
                    ["Traffic Light", zone],
                    ["Observation Count", str(len(self.returns))],
                    ["Timestamp", self._timestamp()],
                ],
            )
        )
        exception_rows = []
        losses = np.maximum(-self.returns, 0.0)
        for idx, loss_pct in enumerate(losses):
            if loss_pct > var_pct:
                exception_rows.append([idx, f"{loss_pct:.4%}", f"{var_pct:.4%}", "Breach"])
        panel.layout.addWidget(
            DenseTable(["Observation", "Loss", "VaR Threshold", "Status"], exception_rows[:25] or [["-", "-", "-", "No breaches"]])
        )
        return panel

    def _capital_tab(self):
        panel = WorkstationPanel("Capital")
        panel.layout.addWidget(
            DenseTable(
                ["Capital Area", "Status", "Next Action"],
                [
                    ["Market risk capital", "Not implemented", "Define methodology"],
                    ["Expected shortfall capital", "Design-ready", "Route through RiskService"],
                    ["Limit utilization", "Prototype", "Connect limits store"],
                    ["Regulatory scenarios", "Prepared", "Use Scenario framework"],
                ],
            )
        )
        return panel

    def _metadata_panel(self):
        panel = WorkstationPanel("Calculation Metadata")
        rows = []
        for method, result in self.var_results.items():
            rows.append([method, result.get("model_status", ""), result.get("market_data_source", ""), self._timestamp()])
        rows.append(["Stress", self.stress_result.get("model_status", ""), self.stress_result.get("market_data_source", ""), self._timestamp()])
        panel.layout.addWidget(DenseTable(["Calculation", "Model Status", "Market Source", "Timestamp"], rows))
        return panel

    def _calculation_log_panel(self):
        panel = WorkstationPanel("Calculation Log")
        rows = []
        for method, result in self.var_results.items():
            rows.append(
                [
                    self._timestamp(),
                    f"{method} VaR",
                    result.get("model_id", ""),
                    result.get("model_status", ""),
                    result.get("market_data_snapshot_id", ""),
                    len(result.get("warnings", [])),
                ]
            )
        rows.append(
            [
                self._timestamp(),
                "Stress",
                self.stress_result.get("model_id", ""),
                self.stress_result.get("model_status", ""),
                self.stress_result.get("market_data_snapshot_id", ""),
                len(self.stress_result.get("warnings", [])),
            ]
        )
        panel.layout.addWidget(DenseTable(["Timestamp", "Calculation", "Model", "Status", "Snapshot", "Warnings"], rows))
        return panel

    def _context_items(self):
        return [
            ("Layer", "Risk"),
            ("Service", "RiskService"),
            ("Snapshot", self.snapshot.snapshot_id),
            ("Market Source", self.snapshot.source.value),
            ("Timestamp", self._timestamp()),
            ("VaR Methods", "Historical / Parametric / Monte Carlo"),
            ("Duplicate Panels", "Removed from workspace"),
        ]

    def _backtest_exceptions(self, var_pct: float) -> int:
        losses = np.maximum(-self.returns, 0.0)
        return int(np.sum(losses > var_pct))

    def _timestamp(self) -> str:
        return self.calculation_timestamp.isoformat().replace("+00:00", "Z")

    def _money(self, value) -> str:
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return "0.00"
