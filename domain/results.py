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
