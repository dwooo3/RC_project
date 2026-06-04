"""Calculation result contracts."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from domain.audit import CalculationRecord
from domain.risk_factors import RiskFactorExposure


@dataclass(frozen=True)
class PricingResult:
    """Structured output for future pricing services."""

    price: float
    currency: str
    market_value: float
    model_id: str
    model_version: str = "0.1"
    market_data_snapshot_id: str = ""
    cashflows: list[Any] = field(default_factory=list)
    sensitivities: list[RiskFactorExposure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BondPricingRequest:
    """Service-level request for fixed-rate bond pricing."""

    face: float
    coupon: float
    maturity: float
    frequency: int
    curve_id: str = "flat_rub"
    currency: str = "RUB"
    valuation_date: date | None = None
    settlement_date: date | None = None
    settlement_days: int = 0
    issue_date: date | None = None
    maturity_date: date | None = None
    day_count: str = "act365"
    business_day_convention: str = "following"


@dataclass(frozen=True)
class BondPricingResult:
    """Structured fixed-income result with clean/dirty price separation."""

    value: float | None
    dirty_price: float | None
    clean_price: float | None
    accrued_interest: float
    currency: str
    model_id: str
    model_status: str
    settlement_date: date | None = None
    previous_coupon_date: date | None = None
    next_coupon_date: date | None = None
    day_count: str = "act365"
    business_day_convention: str = "following"
    market_data_snapshot_id: str = ""
    market_data_source: str = ""
    market_data_quality: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PnLExplainResult:
    """Portfolio P&L attribution result."""

    portfolio_id: str
    total_pnl: float
    explained_pnl: float
    residual: float
    delta_pnl: float = 0.0
    gamma_pnl: float = 0.0
    vega_pnl: float = 0.0
    theta_pnl: float = 0.0
    rate_pnl: float = 0.0
    fx_pnl: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    factor_pnl: dict[str, float] = field(default_factory=dict)
    position_pnl: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    calculation_record: CalculationRecord | None = None
    calculation_id: str = ""
    inputs_hash: str = ""

    @property
    def reconciles(self) -> bool:
        return abs(self.total_pnl - self.explained_pnl - self.residual) < 1e-9

    def as_dict(self) -> dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "total_pnl": self.total_pnl,
            "explained_pnl": self.explained_pnl,
            "residual": self.residual,
            "delta_pnl": self.delta_pnl,
            "gamma_pnl": self.gamma_pnl,
            "vega_pnl": self.vega_pnl,
            "theta_pnl": self.theta_pnl,
            "rate_pnl": self.rate_pnl,
            "fx_pnl": self.fx_pnl,
            "components": self.components,
            "factor_pnl": self.factor_pnl,
            "position_pnl": self.position_pnl,
            "warnings": self.warnings,
            "errors": self.errors,
            "reconciles": self.reconciles,
            "calculation_id": self.calculation_id,
            "inputs_hash": self.inputs_hash,
            "audit_record": self.calculation_record.as_dict() if self.calculation_record else None,
        }
