"""Portfolio Workspace v1 backed exclusively by PortfolioService."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QTabWidget

from domain.portfolio import Position
from services.portfolio_service import PortfolioService
from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class PortfolioPanel(WorkstationWorkspace):
    """Institutional portfolio workstation using PortfolioService as the UI boundary."""

    def __init__(self, parent=None):
        self.portfolio_service = PortfolioService("Main Portfolio")
        self._seed_demo_portfolio()
        self.valuation = self.portfolio_service.value()
        self.aggregate = self.portfolio_service.aggregate()
        self.scenario = self.portfolio_service.scenario_pnl(
            dS=-5.0,
            dVol=0.05,
            dr=0.01,
            dSpread=0.0025,
        )
        self.pnl_explain = self.portfolio_service.explain_pnl(
            scenario=None,
            dS=-5.0,
            dVol=0.05,
            dr=0.01,
            dSpread=0.0025,
        )

        super().__init__(
            "Portfolio",
            "Positions, exposures, P&L, scenario analysis, and valuation",
            chips=self._status_chips(),
            actions=[
                make_action("Add Position"),
                make_action("Import"),
                make_action("Value", primary=True),
                make_action("Scenario"),
                make_action("Export"),
            ],
            kpi_strip=self._summary_kpis(),
            left=self._portfolio_summary_panel(),
            center=self._workspace_tabs(),
            right=self._position_context_panel(),
            bottom=self._valuation_panel(),
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

    def _status_chips(self):
        status = "Approximation" if self.valuation.warnings else "Validated"
        text = "PortfolioService boundary"
        return [DataSourceChip("DEMO"), StatusChip(status, text=text)]

    def _summary_kpis(self):
        return KpiStrip(
            [
                ("Market Value", self._money(self.valuation.total_market_value), self.valuation.base_currency),
                ("Positions", str(len(self.portfolio_service.positions)), "Active"),
                ("Rates DV01", self._number(self.aggregate.get("dv01", 0.0)), "DV01"),
                ("FX Delta", self._number(self.aggregate.get("fx_delta", 0.0)), "FX"),
                ("Vol Vega", self._number(self.aggregate.get("vega", 0.0)), "Vega"),
                ("Scenario P&L", self._money(self.scenario.get("pnl", 0.0)), "Service scenario"),
                ("Residual", self._money(self.pnl_explain.residual), "PnL explain"),
            ]
        )

    def _portfolio_summary_panel(self):
        panel = WorkstationPanel("Portfolio Summary")
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
                    ["Snapshot", portfolio.market_data_snapshot_id or "DEMO / service-created"],
                    ["Service", "PortfolioService"],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Action", "Shortcut"],
                [
                    ["Value Portfolio", "V"],
                    ["Scenario Analysis", "S"],
                    ["PnL Explain", "A"],
                    ["Run Risk", "Shift+V"],
                    ["Export Report", "Ctrl+E"],
                ],
            )
        )
        return panel

    def _workspace_tabs(self):
        tabs = QTabWidget()
        tabs.addTab(self._positions_section(), "Positions")
        tabs.addTab(self._exposures_section(), "Exposures")
        tabs.addTab(self._pnl_section(), "PnL")
        tabs.addTab(self._scenario_section(), "Scenario Analysis")
        tabs.addTab(self._valuation_section(), "Valuation")
        return tabs

    def _positions_section(self):
        panel = WorkstationPanel("Positions")
        rows = []
        for row in self.portfolio_service.positions_table():
            rows.append(
                [
                    row["id"],
                    row["instrument"],
                    row["description"],
                    row["quantity"],
                    row["price"],
                    row["market_value"],
                    row["dv01"],
                    row["currency"],
                    row["book"],
                ]
            )
        panel.layout.addWidget(
            DenseTable(
                ["ID", "Product", "Description", "Qty", "Price", "MV", "DV01", "Ccy", "Book"],
                rows,
            )
        )
        return panel

    def _exposures_section(self):
        panel = WorkstationPanel("Risk Factor Exposure Grid")
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
                ["Factor", "Bucket", "Unit", "Exposure", "Contribution", "Ccy"],
                exposure_rows,
            )
        )
        bucket_rows = [
            [bucket, ", ".join(f"{unit}: {self._number(value)}" for unit, value in values.items()) or "0"]
            for bucket, values in self.aggregate.get("exposure_buckets", {}).items()
        ]
        panel.layout.addWidget(DenseTable(["Bucket", "Aggregated Exposure"], bucket_rows))
        return panel

    def _pnl_section(self):
        panel = WorkstationPanel("PnL Summary")
        panel.layout.addWidget(
            DenseTable(
                ["Component", "Amount"],
                [
                    ["Delta P&L", self._money(self.pnl_explain.delta_pnl)],
                    ["Gamma P&L", self._money(self.pnl_explain.gamma_pnl)],
                    ["Vega P&L", self._money(self.pnl_explain.vega_pnl)],
                    ["Theta P&L", self._money(self.pnl_explain.theta_pnl)],
                    ["Rate P&L", self._money(self.pnl_explain.rate_pnl)],
                    ["FX P&L", self._money(self.pnl_explain.fx_pnl)],
                    ["Explained P&L", self._money(self.pnl_explain.explained_pnl)],
                    ["Residual", self._money(self.pnl_explain.residual)],
                ],
            )
        )
        factor_rows = [[factor, self._money(value)] for factor, value in sorted(self.pnl_explain.factor_pnl.items())]
        panel.layout.addWidget(DenseTable(["Factor", "PnL"], factor_rows or [["No factor PnL", "0"]]))
        return panel

    def _scenario_section(self):
        panel = WorkstationPanel("Scenario Summary")
        bucket_pnl = self.scenario.get("bucket_pnl", {})
        panel.layout.addWidget(
            DenseTable(
                ["Scenario Input", "Value"],
                [
                    ["Equity / FX shock", "-5.0"],
                    ["Volatility shock", "+5 vol pts"],
                    ["Rates shock", "+100bp"],
                    ["Credit shock", "+25bp"],
                    ["Total P&L", self._money(self.scenario.get("pnl", 0.0))],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Bucket", "P&L"],
                [[bucket, self._money(value)] for bucket, value in bucket_pnl.items()],
            )
        )
        return panel

    def _valuation_section(self):
        panel = WorkstationPanel("Valuation")
        panel.layout.addWidget(
            DenseTable(
                ["Field", "Value"],
                [
                    ["Portfolio ID", self.valuation.portfolio_id],
                    ["Base Currency", self.valuation.base_currency],
                    ["Total Market Value", self._money(self.valuation.total_market_value)],
                    ["Positions Valued", str(len(self.valuation.positions))],
                    ["Warnings", str(len(self.valuation.warnings))],
                    ["Errors", str(len(self.valuation.errors))],
                ],
            )
        )
        warning_rows = [[warning] for warning in self.valuation.warnings] or [["No warnings"]]
        error_rows = [[error] for error in self.valuation.errors] or [["No errors"]]
        panel.layout.addWidget(DenseTable(["Warnings"], warning_rows))
        panel.layout.addWidget(DenseTable(["Errors"], error_rows))
        return panel

    def _position_context_panel(self):
        panel = WorkstationPanel("Position Context")
        position = self.valuation.positions[0] if self.valuation.positions else None
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
        return panel

    def _valuation_panel(self):
        panel = WorkstationPanel("Valuation / Service Notes")
        panel.layout.addWidget(
            DenseTable(
                ["Contract", "State"],
                [
                    ["UI boundary", "PortfolioService only"],
                    ["Direct model calls", "None in PortfolioPanel"],
                    ["Valuation", "PortfolioService.value()"],
                    ["Exposure aggregation", "PortfolioService.aggregate()"],
                    ["Scenario analysis", "PortfolioService.scenario_pnl()"],
                    ["PnL explain", "PortfolioService.explain_pnl()"],
                ],
            )
        )
        return panel

    def _context_items(self):
        return [
            ("Layer", "Portfolio"),
            ("Service", "PortfolioService"),
            ("Portfolio", self.portfolio_service.portfolio.name),
            ("Base Currency", self.valuation.base_currency),
            ("Positions", str(len(self.valuation.positions))),
            ("Warnings", str(len(self.valuation.warnings))),
            ("Errors", str(len(self.valuation.errors))),
        ]

    def _money(self, value: float) -> str:
        return f"{value:,.2f}"

    def _number(self, value: float) -> str:
        return f"{value:,.4f}"
