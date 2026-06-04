"""Calculation result contracts."""

from dataclasses import dataclass, field
from typing import Any

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
    """Service-level request for the legacy fixed-rate bond engine."""

    face: float
    coupon: float
    maturity: float
    frequency: int
    curve_id: str = "flat_rub"
    currency: str = "RUB"


@dataclass(frozen=True)
class BondPricingResult:
    """Structured fixed-income result with explicit approximation metadata."""

    value: float | None
    dirty_price: float | None
    clean_price: float | None
    accrued_interest: float
    currency: str
    model_id: str
    model_status: str
    market_data_snapshot_id: str = ""
    market_data_source: str = ""
    market_data_quality: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
