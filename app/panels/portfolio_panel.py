"""Portfolio Workspace v1 backed exclusively by PortfolioService."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QTabWidget

from app.panels.session import shared_portfolio
from domain.portfolio import Position
from services.portfolio_service import PortfolioService  # noqa: F401  (service-boundary marker)
from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WarningBanner, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class PortfolioPanel(WorkstationWorkspace):
    """Institutional portfolio workstation using PortfolioService as the UI boundary."""

    def __init__(self, parent=None):
        # Shared session portfolio: instruments priced and added on the Pricing
        # tab appear here. Demo seed only when the portfolio is still empty.
        self.portfolio_service = shared_portfolio()
        self._seed_demo_portfolio()
        self.valuation = self.portfolio_service.value()
        self.aggregate = self.portfolio_service.aggregate()
        self.scenario_definition = self._scenario_definition()
        self.scenario_result = self.portfolio_service.run_scenario(self.scenario_definition)
        self.scenario = self.scenario_result.as_dict()
        self.pnl_explain = self.portfolio_service.explain_pnl(
            scenario=self.scenario_definition,
            theta_days=1.0,
        )
        self.service_warnings = self._collect_warnings()

        super().__init__(
            "Portfolio",
            "Primary portfolio workstation: overview, positions, exposures, scenario P&L, and attribution",
            chips=self._status_chips(),
            actions=[
                make_action("Add Position"),
                make_action("Import"),
                make_action("Value", primary=True),
                make_action("Scenario"),
                make_action("Export"),
            ],
            kpi_strip=self._summary_kpis(),
            left=self._portfolio_control_panel(),
            center=self._workspace_tabs(),
            right=self._portfolio_context_panel(),
            bottom=self._service_notes_panel(),
            context_items=self._context_items(),
            parent=parent,
        )

    def _seed_demo_portfolio(self):
        if self.portfolio_service.positions:
            return
        positions = [
            Position(
                id="pos_option_001",
                instrument="call",
                description="ATM equity call",
                quantity=2500,
                params={"S": 100.0, "K": 100.0, "T": 0.5, "r": 0.05, "sigma": 0.20, "q": 0.0, "opt": "call"},
                currency="RUB",
                book="Trading",
            ),
            Position(
                id="pos_bond_001",
                instrument="bond",
                description="5Y fixed-rate bond",
                quantity=1_000_000,
                params={"face": 100.0, "coupon": 0.075, "T": 5.0, "freq": 2, "r": 0.08},
                currency="RUB",
                book="Trading",
            ),
            Position(
                id="pos_irs_001",
                instrument="irs",
                description="RUB IRS pay fixed 5Y",
                quantity=1.0,
                params={"notional": 50_000_000.0, "fixed_rate": 0.075, "T": 5.0, "freq": 4, "r": 0.08, "pay_fixed": True},
                currency="RUB",
                book="Trading",
            ),
            Position(
                id="pos_fx_001",
                instrument="fx_forward",
                description="USD/RUB forward",
                quantity=1_000_000,
                params={"S": 90.0, "K": 91.0, "r_d": 0.10, "r_f": 0.045, "T": 0.25, "ccy_pair": "USD/RUB"},
                currency="RUB",
                book="Trading",
                ccy_pair="USD/RUB",
            ),
        ]
        for position in positions:
            self.portfolio_service.add(position)

    def _scenario_definition(self) -> dict:
        return {
            "scenario_id": "portfolio-workstation-risk-off",
            "name": "Risk-Off Shock",
            "scenario_type": "Hypothetical",
            "source": "PortfolioService",
            "description": "Desk-level scenario routed through PortfolioService scenario engine.",
            "shocks": [
                {
                    "shock_type": "equity_shock",
                    "value": -5.0,
                    "unit": "absolute",
                    "bucket": "Equity",
                    "description": "Equity spot down 5 points",
                },
                {
                    "shock_type": "fx_shock",
                    "value": -5.0,
                    "unit": "absolute",
                    "bucket": "FX",
                    "description": "FX spot down 5 points",
                },
                {
                    "shock_type": "volatility_shock",
                    "value": 0.05,
                    "unit": "absolute",
                    "bucket": "Volatility",
                    "description": "Implied volatility up 5 vol points",
                },
                {
                    "shock_type": "parallel_curve_shift",
                    "value": 100.0,
                    "unit": "bps",
                    "bucket": "Rates",
                    "description": "Parallel rates up 100bp",
                },
            ],
        }

    def _collect_warnings(self) -> list[str]:
        warnings = []
        for warning in (
            list(self.valuation.warnings)
            + list(self.scenario_result.warnings)
            + list(self.pnl_explain.warnings)
        ):
            if warning and warning not in warnings:
                warnings.append(warning)
        return warnings

    def _status_chips(self):
        status = "Approximation" if self.service_warnings else "Validated"
        text = "PortfolioService boundary"
        return [DataSourceChip("DEMO"), StatusChip(status, text=text)]

    def _summary_kpis(self):
        top_factor = self._largest_factor_exposure()
        return KpiStrip(
            [
                ("Portfolio Value", self._money(self.valuation.total_market_value), self.valuation.base_currency),
                ("Positions", str(len(self.portfolio_service.positions)), "Active"),
                ("Top Factor", top_factor[0], self._number(top_factor[1])),
                ("Scenario Impact", self._money(self.scenario_result.pnl), self.scenario_result.scenario.name),
                ("Explained P&L", self._money(self.pnl_explain.explained_pnl), "PnL explain"),
                ("Residual", self._money(self.pnl_explain.residual), "Reconciliation"),
                ("Warnings", str(len(self.service_warnings)), "Service surfaced"),
            ]
        )

    def _portfolio_control_panel(self):
        panel = WorkstationPanel("Portfolio Control")
        portfolio = self.portfolio_service.portfolio
        panel.layout.addWidget(
            DenseTable(
                ["Field", "Value"],
                [
                    ["Portfolio", portfolio.name],
                    ["Portfolio ID", portfolio.portfolio_id],
                    ["Book", "Trading"],
                    ["Base Currency", portfolio.base_currency],
                    ["Valuation Date", str(portfolio.valuation_date or "Current session")],
                    ["Snapshot", self.valuation.market_data_snapshot_id or "DEMO / service-created"],
                    ["Service", "PortfolioService"],
                    ["Scenario", self.scenario_result.scenario.name],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Action", "Shortcut"],
                [
                    ["Value Portfolio", "V"],
                    ["Run Scenario", "S"],
                    ["PnL Explain", "A"],
                    ["Run Risk", "Shift+V"],
                    ["Export Report", "Ctrl+E"],
                ],
            )
        )
        return panel

    def _workspace_tabs(self):
        tabs = QTabWidget()
        tabs.addTab(self._portfolio_overview_section(), "Portfolio Overview")
        tabs.addTab(self._positions_grid_section(), "Positions Grid")
        tabs.addTab(self._exposure_dashboard_section(), "Exposure Dashboard")
        tabs.addTab(self._scenario_dashboard_section(), "Scenario Dashboard")
        tabs.addTab(self._pnl_explain_dashboard_section(), "PnL Explain Dashboard")
        return tabs

    def _portfolio_overview_section(self):
        panel = WorkstationPanel("Portfolio Overview")
        panel.layout.addWidget(self._warning_banner())
        panel.layout.addWidget(
            DenseTable(
                ["Metric", "Value", "Source"],
                [
                    ["Portfolio value", self._money(self.valuation.total_market_value), "PortfolioService.value()"],
                    ["Active positions", str(len(self.valuation.positions)), "Portfolio.positions"],
                    ["Risk-factor exposures", str(len(self.aggregate.get("risk_factor_exposures", []))), "RiskFactorExposure"],
                    ["Scenario impact", self._money(self.scenario_result.pnl), "Scenario Engine"],
                    ["Attribution residual", self._money(self.pnl_explain.residual), "PnL Explain"],
                    ["Service warnings", str(len(self.service_warnings)), "PortfolioService"],
                ],
            )
        )
        top_rows = [
            [
                position.id,
                position.instrument,
                position.description,
                self._money(position.market_value),
                position.model_id or "PortfolioService",
                position.model_status or "Manual",
            ]
            for position in self._top_positions()
        ]
        panel.layout.addWidget(
            DenseTable(
                ["Top Position", "Product", "Description", "Market Value", "Model", "Status"],
                top_rows or [["No positions", "", "", "0.00", "", ""]],
            )
        )
        return panel

    def _positions_grid_section(self):
        panel = WorkstationPanel("Positions Grid")
        rows = []
        for row in self.portfolio_service.positions_table():
            rows.append(
                [
                    row["id"],
                    row["instrument"],
                    row["description"],
                    row["quantity"],
                    row["price"],
                    self._money(row["market_value"]),
                    row["delta"],
                    row["vega"],
                    row["dv01"],
                    row["currency"],
                    row["book"],
                ]
            )
        panel.layout.addWidget(
            DenseTable(
                ["ID", "Product", "Description", "Qty", "Price", "Market Value", "Delta", "Vega", "DV01", "Ccy", "Book"],
                rows,
            )
        )
        return panel

    def _exposure_dashboard_section(self):
        panel = WorkstationPanel("Exposure Dashboard")
        exposure_rows = []
        for factor_id, factor in sorted(self.aggregate.get("risk_factors", {}).items()):
            exposure_rows.append(
                [
                    factor_id,
                    factor.get("bucket", ""),
                    factor.get("unit", ""),
                    self._number(float(factor.get("sensitivity", 0.0))),
                    self._money(float(factor.get("contribution", 0.0))),
                    factor.get("currency", ""),
                ]
            )
        panel.layout.addWidget(
            DenseTable(
                ["Risk Factor", "Bucket", "Unit", "Exposure", "Contribution", "Ccy"],
                exposure_rows,
            )
        )
        bucket_rows = [
            [bucket, ", ".join(f"{unit}: {self._number(value)}" for unit, value in values.items()) or "0"]
            for bucket, values in self.aggregate.get("exposure_buckets", {}).items()
        ]
        panel.layout.addWidget(DenseTable(["Bucket", "Aggregated Exposure"], bucket_rows))
        return panel

    def _scenario_dashboard_section(self):
        panel = WorkstationPanel("Scenario Dashboard")
        scenario = self.scenario_result.scenario
        panel.layout.addWidget(
            DenseTable(
                ["Scenario", "Value"],
                [
                    ["Name", scenario.name],
                    ["Type", scenario.type_value],
                    ["Source", scenario.source or "PortfolioService"],
                    ["Base value", self._money(self.scenario_result.base_value)],
                    ["Stressed value", self._money(self.scenario_result.stressed_value)],
                    ["Total impact", self._money(self.scenario_result.pnl)],
                    ["Warnings", str(len(self.scenario_result.warnings))],
                ],
            )
        )
        shock_rows = [
            [shock.type_value, shock.bucket or shock.factor_id or "Portfolio", shock.value, shock.unit, shock.description]
            for shock in scenario.shocks
        ]
        panel.layout.addWidget(
            DenseTable(
                ["Shock", "Target", "Value", "Unit", "Description"],
                shock_rows,
            )
        )
        bucket_rows = [
            [bucket, self._money(value)]
            for bucket, value in self.scenario_result.bucket_pnl.items()
        ]
        position_rows = [
            [position_id, self._money(value)]
            for position_id, value in sorted(
                self.scenario_result.position_pnl.items(),
                key=lambda item: abs(item[1]),
                reverse=True,
            )
        ]
        panel.layout.addWidget(DenseTable(["Bucket", "Scenario P&L"], bucket_rows))
        panel.layout.addWidget(DenseTable(["Position", "Scenario P&L"], position_rows or [["No position impact", "0.00"]]))
        return panel

    def _pnl_explain_dashboard_section(self):
        panel = WorkstationPanel("PnL Explain Dashboard")
        panel.layout.addWidget(self._warning_banner())
        panel.layout.addWidget(
            DenseTable(
                ["Component", "Amount", "Purpose"],
                [
                    ["Delta P&L", self._money(self.pnl_explain.delta_pnl), "Equity factor move"],
                    ["Gamma P&L", self._money(self.pnl_explain.gamma_pnl), "Second-order equity move"],
                    ["Vega P&L", self._money(self.pnl_explain.vega_pnl), "Volatility factor move"],
                    ["Theta P&L", self._money(self.pnl_explain.theta_pnl), "One-day carry"],
                    ["Rate P&L", self._money(self.pnl_explain.rate_pnl), "Rates factor move"],
                    ["FX P&L", self._money(self.pnl_explain.fx_pnl), "FX factor move"],
                    ["Explained P&L", self._money(self.pnl_explain.explained_pnl), "Attributed total"],
                    ["Residual", self._money(self.pnl_explain.residual), "Unexplained amount"],
                    ["Reconciles", "Yes" if self.pnl_explain.reconciles else "No", "Tolerance check"],
                ],
            )
        )
        factor_rows = [[factor, self._money(value)] for factor, value in sorted(self.pnl_explain.factor_pnl.items())]
        panel.layout.addWidget(DenseTable(["Factor", "PnL"], factor_rows or [["No factor PnL", "0"]]))
        return panel

    def _portfolio_context_panel(self):
        panel = WorkstationPanel("Portfolio Context")
        position = self._top_positions(1)[0] if self.valuation.positions else None
        if position is None:
            rows = [["Selected", "No positions"]]
        else:
            rows = [
                ["Selected", position.id],
                ["Product", position.instrument],
                ["Description", position.description],
                ["Market Value", self._money(position.market_value)],
                ["Model", position.model_id or "PortfolioService"],
                ["Model Status", position.model_status or "Manual"],
                ["Warnings", str(len(position.warnings))],
                ["Errors", str(len(position.errors))],
            ]
        panel.layout.addWidget(DenseTable(["Field", "Value"], rows))
        panel.layout.addWidget(
            DenseTable(
                ["Workflow", "Boundary"],
                [
                    ["Valuation", "PortfolioService.value()"],
                    ["Exposures", "RiskFactorExposure"],
                    ["Scenario", "PortfolioService.run_scenario()"],
                    ["PnL Explain", "PortfolioService.explain_pnl()"],
                    ["Direct model calls", "None"],
                ],
            )
        )
        return panel

    def _service_notes_panel(self):
        panel = WorkstationPanel("Service Notes")
        panel.layout.addWidget(
            DenseTable(
                ["Contract", "State"],
                [
                    ["UI boundary", "PortfolioService only"],
                    ["Direct model calls", "None in PortfolioPanel"],
                    ["Valuation", "PortfolioService.value()"],
                    ["Exposure aggregation", "PortfolioService.aggregate()"],
                    ["Scenario analysis", "PortfolioService.run_scenario()"],
                    ["PnL explain", "PortfolioService.explain_pnl()"],
                    ["Warnings surfaced", str(len(self.service_warnings))],
                ],
            )
        )
        warning_rows = [[warning] for warning in self.service_warnings] or [["No warnings"]]
        panel.layout.addWidget(DenseTable(["Warnings"], warning_rows))
        return panel

    def _context_items(self):
        return [
            ("Layer", "Portfolio"),
            ("Service", "PortfolioService"),
            ("Portfolio", self.portfolio_service.portfolio.name),
            ("Base Currency", self.valuation.base_currency),
            ("Positions", str(len(self.valuation.positions))),
            ("Scenario", self.scenario_result.scenario.name),
            ("Warnings", str(len(self.service_warnings))),
            ("Errors", str(len(self.valuation.errors))),
        ]

    def _top_positions(self, limit: int = 5) -> list[Position]:
        return sorted(
            self.valuation.positions,
            key=lambda position: abs(position.market_value),
            reverse=True,
        )[:limit]

    def _largest_factor_exposure(self) -> tuple[str, float]:
        factors = self.aggregate.get("risk_factors", {})
        if not factors:
            return ("None", 0.0)
        factor_id, factor = max(
            factors.items(),
            key=lambda item: abs(float(item[1].get("sensitivity", 0.0))),
        )
        return factor_id, float(factor.get("sensitivity", 0.0))

    def _warning_banner(self) -> WarningBanner:
        banner = WarningBanner()
        if self.service_warnings:
            banner.show_error("; ".join(self.service_warnings[:3]))
        else:
            banner.show_ok("Portfolio workflow is routed through PortfolioService.")
        return banner

    def _money(self, value: float) -> str:
        return f"{value:,.2f}"

    def _number(self, value: float) -> str:
        return f"{value:,.4f}"
