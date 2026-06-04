"""Domain contracts for RiskCalc architecture migration."""

from domain.audit import AuditRecord, CalculationRecord
from domain.market_data import MarketDataSnapshot, MarketDataSource, MarketDataStore
from domain.model_governance import ModelDefinition
from domain.portfolio import (
    Portfolio,
    PortfolioRiskResult,
    PortfolioValuationResult,
    Position,
    PositionType,
)
from domain.reporting import ReportDocument, ReportMetric, ReportSection, ReportTable
from domain.results import PnLExplainResult, PricingResult
from domain.risk_factors import RiskFactor, RiskFactorBucket, RiskFactorExposure, RiskFactorGroup, RiskFactorHierarchy
from domain.scenario import Scenario, ScenarioResult, ScenarioShock, ScenarioShockType, ScenarioType

__all__ = [
    "MarketDataSnapshot",
    "AuditRecord",
    "CalculationRecord",
    "MarketDataSource",
    "MarketDataStore",
    "ModelDefinition",
    "Portfolio",
    "PortfolioRiskResult",
    "PortfolioValuationResult",
    "Position",
    "PositionType",
    "ReportDocument",
    "ReportMetric",
    "ReportSection",
    "ReportTable",
    "PricingResult",
    "PnLExplainResult",
    "RiskFactorBucket",
    "RiskFactor",
    "RiskFactorExposure",
    "RiskFactorGroup",
    "RiskFactorHierarchy",
    "Scenario",
    "ScenarioResult",
    "ScenarioShock",
    "ScenarioShockType",
    "ScenarioType",
]
