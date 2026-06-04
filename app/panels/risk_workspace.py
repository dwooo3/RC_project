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
        self.calculation_timestamp = datetime.now(UTC).replace(microsecond=0)
        self.market_data = MarketDataService()
        self.snapshot = self.market_data.demo_snapshot()
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
        tabs.addTab(self._stress_tab(), "Stress")
        tabs.addTab(self._backtesting_tab(), "Backtesting")
        tabs.addTab(self._capital_tab(), "Capital")
        return tabs

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
