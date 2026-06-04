"""Reporting foundation built on service-layer results."""

from typing import Any

import numpy as np

from domain.reporting import ReportDocument, ReportMetric, ReportSection, ReportTable
from services.governance_service import GovernanceService
from services.portfolio_service import PortfolioService
from services.risk_service import RiskService


class ReportingService:
    """Create renderer-neutral, PDF-ready report structures."""

    def __init__(
        self,
        portfolio: PortfolioService | None = None,
        risk: RiskService | None = None,
        governance: GovernanceService | None = None,
    ):
        self.portfolio = portfolio or PortfolioService("Reporting Portfolio")
        self.risk = risk or RiskService()
        self.governance = governance or GovernanceService()

    def portfolio_report(self) -> ReportDocument:
        valuation = self.portfolio.value()
        risk = self.portfolio.risk()
        positions = [
            [
                position.id,
                position.instrument,
                position.description,
                position.quantity,
                round(position.price, 6),
                round(position.market_value, 2),
                position.model_id,
                position.model_status,
            ]
            for position in valuation.positions
        ]
        exposure_rows = [
            [bucket, unit, round(value, 6)]
            for bucket, values in risk.exposure_buckets.items()
            for unit, value in values.items()
        ]
        return ReportDocument(
            report_type="portfolio",
            title="Portfolio Report",
            source_services=["PortfolioService"],
            metadata=self._common_metadata(
                portfolio_id=valuation.portfolio_id,
                market_data_snapshot_id=valuation.market_data_snapshot_id,
                calculation_id=valuation.calculation_id,
                inputs_hash=valuation.inputs_hash,
            ),
            sections=[
                ReportSection(
                    "Portfolio Summary",
                    metrics=[
                        ReportMetric("Portfolio ID", valuation.portfolio_id),
                        ReportMetric("Base Currency", valuation.base_currency),
                        ReportMetric("Total Market Value", round(valuation.total_market_value, 2)),
                        ReportMetric("Positions", len(valuation.positions)),
                        ReportMetric("Market Snapshot", valuation.market_data_snapshot_id),
                    ],
                    warnings=valuation.warnings,
                    errors=valuation.errors,
                ),
                ReportSection(
                    "Positions",
                    tables=[
                        ReportTable(
                            "Positions",
                            ["ID", "Instrument", "Description", "Quantity", "Price", "Market Value", "Model", "Status"],
                            positions,
                        )
                    ],
                ),
                ReportSection(
                    "Risk Factor Exposure",
                    tables=[ReportTable("Exposure Buckets", ["Bucket", "Unit", "Exposure"], exposure_rows)],
                    warnings=risk.warnings,
                    errors=risk.errors,
                ),
            ],
        )

    def risk_report(self) -> ReportDocument:
        risk = self.portfolio.risk()
        bucket_rows = [
            [bucket, unit, round(value, 6)]
            for bucket, values in risk.exposure_buckets.items()
            for unit, value in values.items()
        ]
        contribution_rows = [
            [factor_id, round(value, 6)]
            for factor_id, value in sorted(risk.factor_contributions.items())
        ]
        return ReportDocument(
            report_type="risk",
            title="Risk Report",
            source_services=["PortfolioService", "RiskService"],
            metadata=self._common_metadata(
                portfolio_id=risk.portfolio_id,
                market_data_snapshot_id=risk.market_data_snapshot_id,
                calculation_id=risk.calculation_id,
                inputs_hash=risk.inputs_hash,
            ),
            sections=[
                ReportSection(
                    "Risk Summary",
                    metrics=[
                        ReportMetric("Portfolio ID", risk.portfolio_id),
                        ReportMetric("Market Value", round(risk.market_value, 2)),
                        ReportMetric("Base Currency", risk.base_currency),
                        ReportMetric("Market Snapshot", risk.market_data_snapshot_id),
                    ],
                    warnings=risk.warnings,
                    errors=risk.errors,
                ),
                ReportSection(
                    "Exposure Buckets",
                    tables=[ReportTable("Exposure Buckets", ["Bucket", "Unit", "Exposure"], bucket_rows)],
                ),
                ReportSection(
                    "Factor Contributions",
                    tables=[ReportTable("Factor Contributions", ["Risk Factor", "Contribution"], contribution_rows)],
                ),
            ],
        )

    def var_report(
        self,
        returns: np.ndarray,
        position_value: float,
        confidence: float = 0.95,
        horizon: int = 1,
    ) -> ReportDocument:
        historical = self.risk.historical_var(returns, position_value, confidence, horizon)
        parametric = self.risk.parametric_var(returns, position_value, confidence, horizon)
        monte_carlo = self.risk.monte_carlo_var(returns, position_value, confidence, horizon, n_sims=10_000)
        expected_shortfall = self.risk.expected_shortfall(returns, position_value, confidence, horizon)
        results = [historical, parametric, monte_carlo, expected_shortfall]
        rows = [
            [
                result.get("audit_record").calculation_type if result.get("audit_record") else "",
                result.get("value"),
                result.get("model_id"),
                result.get("model_version"),
                result.get("model_status"),
                result.get("calculation_id"),
                result.get("inputs_hash"),
                "; ".join(result.get("warnings", [])[:2]),
                "; ".join(result.get("errors", [])),
            ]
            for result in results
        ]
        return ReportDocument(
            report_type="var",
            title="VaR Report",
            source_services=["RiskService", "GovernanceService"],
            metadata=self._common_metadata(
                confidence=confidence,
                horizon=horizon,
                position_value=position_value,
                observations=len(returns),
            ),
            sections=[
                ReportSection(
                    "VaR Summary",
                    metrics=[
                        ReportMetric("Confidence", confidence),
                        ReportMetric("Horizon", horizon, "days"),
                        ReportMetric("Position Value", position_value),
                        ReportMetric("Observations", len(returns)),
                    ],
                ),
                ReportSection(
                    "VaR Results",
                    tables=[
                        ReportTable(
                            "VaR Methods",
                            [
                                "Calculation",
                                "Value",
                                "Model",
                                "Version",
                                "Status",
                                "Audit ID",
                                "Inputs Hash",
                                "Warnings",
                                "Errors",
                            ],
                            rows,
                        )
                    ],
                    warnings=self._collect_messages(results, "warnings"),
                    errors=self._collect_messages(results, "errors"),
                ),
            ],
        )

    def scenario_report(self, scenario: dict | Any) -> ReportDocument:
        scenario_result = self.portfolio.run_scenario(scenario)
        pnl_explain = self.portfolio.explain_pnl(scenario=scenario_result.scenario)
        bucket_rows = [[bucket, round(value, 6)] for bucket, value in scenario_result.bucket_pnl.items()]
        factor_rows = [[factor, round(value, 6)] for factor, value in sorted(scenario_result.factor_pnl.items())]
        return ReportDocument(
            report_type="scenario",
            title="Scenario Report",
            source_services=["PortfolioService", "RiskService"],
            metadata=self._common_metadata(
                scenario_id=scenario_result.scenario.scenario_id,
                scenario_name=scenario_result.scenario.name,
                calculation_id=scenario_result.calculation_id,
                inputs_hash=scenario_result.inputs_hash,
            ),
            sections=[
                ReportSection(
                    "Scenario Summary",
                    metrics=[
                        ReportMetric("Scenario ID", scenario_result.scenario.scenario_id),
                        ReportMetric("Scenario Type", scenario_result.scenario.type_value),
                        ReportMetric("Base Value", round(scenario_result.base_value, 2)),
                        ReportMetric("Stressed Value", round(scenario_result.stressed_value, 2)),
                        ReportMetric("Scenario P&L", round(scenario_result.pnl, 2)),
                    ],
                    warnings=scenario_result.warnings,
                    errors=scenario_result.errors,
                ),
                ReportSection(
                    "Scenario P&L",
                    tables=[
                        ReportTable("Bucket P&L", ["Bucket", "P&L"], bucket_rows),
                        ReportTable("Factor P&L", ["Factor", "P&L"], factor_rows),
                    ],
                ),
                ReportSection(
                    "PnL Explain",
                    metrics=[
                        ReportMetric("Explained P&L", round(pnl_explain.explained_pnl, 2)),
                        ReportMetric("Residual", round(pnl_explain.residual, 2)),
                        ReportMetric("Reconciles", pnl_explain.reconciles),
                    ],
                    warnings=pnl_explain.warnings,
                    errors=pnl_explain.errors,
                ),
            ],
        )

    def model_governance_report(self) -> ReportDocument:
        models = self.governance.list_models()
        rows = [
            [
                model.model_id,
                model.status,
                model.owner,
                model.validation_date.isoformat() if model.validation_date else "",
                "Yes" if model.production_allowed else "No",
                model.quant_review_status,
                model.version,
            ]
            for model in models
        ]
        status_rows = [[status, count] for status, count in sorted(self.governance.status_counts().items())]
        quant_counts: dict[str, int] = {}
        for model in models:
            quant_counts[model.quant_review_status] = quant_counts.get(model.quant_review_status, 0) + 1
        quant_rows = [[status, quant_counts.get(status, 0)] for status in ("Fixed", "False Positive", "Partially Validated", "Open")]
        return ReportDocument(
            report_type="model_governance",
            title="Model Governance Report",
            source_services=["GovernanceService"],
            metadata=self._common_metadata(model_count=len(models)),
            sections=[
                ReportSection(
                    "Model Registry",
                    tables=[
                        ReportTable(
                            "Model Registry",
                            ["Model ID", "Status", "Owner", "Validation Date", "Production Allowed", "Quant Review", "Version"],
                            rows,
                        )
                    ],
                ),
                ReportSection(
                    "Status Summary",
                    tables=[
                        ReportTable("Registry Status", ["Status", "Count"], status_rows),
                        ReportTable("Quant Review Status", ["Quant Review", "Count"], quant_rows),
                    ],
                ),
                ReportSection(
                    "Limitations",
                    tables=[
                        ReportTable(
                            "Limitations",
                            ["Model ID", "Status", "Production Allowed", "Quant Review", "Limitation"],
                            [
                                [
                                    item["model_id"],
                                    item["status"],
                                    "Yes" if item["production_allowed"] else "No",
                                    item["quant_review_status"],
                                    item["limitation"],
                                ]
                                for item in self.governance.limitations_report()
                            ],
                        )
                    ],
                ),
            ],
        )

    def _common_metadata(self, **kwargs) -> dict[str, Any]:
        metadata = {
            "format": "pdf_ready_structure",
            "renderer": "not_implemented",
            "final_pdf_styling": "pending",
        }
        metadata.update(kwargs)
        return metadata

    def _collect_messages(self, results: list[dict], key: str) -> list[str]:
        messages: list[str] = []
        for result in results:
            for message in result.get(key, []):
                if message and message not in messages:
                    messages.append(message)
        return messages
