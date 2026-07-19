"""Risk factor exposure contracts."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


RiskFactorBucket = Literal[
    "Rates", "FX", "Equity", "Credit", "Commodity", "Volatility"
]


class RiskFactorHierarchy(str, Enum):
    RATES = "Rates"
    FX = "FX"
    EQUITY = "Equity"
    CREDIT = "Credit"
    COMMODITY = "Commodity"
    VOLATILITY = "Volatility"


@dataclass(frozen=True)
class RiskFactor:
    """Canonical market-risk factor."""

    factor_id: str
    name: str
    bucket: RiskFactorBucket | str
    factor_type: str
    currency: str = ""
    unit: str = ""
    bump_size: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RiskFactorExposure:
    """Sensitivity to one named risk factor and bump convention."""

    factor_name: str
    factor_type: str
    currency: str
    bump_size: float
    sensitivity: float
    unit: str
    bucket: RiskFactorBucket | str = "Unclassified"
    factor_id: str = ""
    position_id: str = ""
    contribution: float = 0.0


@dataclass(frozen=True)
class RiskFactorGroup:
    """Aggregated exposures and contribution for one factor hierarchy bucket."""

    bucket: RiskFactorBucket | str
    exposures: list[RiskFactorExposure] = field(default_factory=list)
    totals_by_unit: dict[str, float] = field(default_factory=dict)
    contribution: float = 0.0

    @classmethod
    def from_exposures(
        cls,
        bucket: RiskFactorBucket | str,
        exposures: list[RiskFactorExposure],
    ) -> "RiskFactorGroup":
        totals: dict[str, float] = {}
        contribution = 0.0
        for exposure in exposures:
            totals[exposure.unit] = totals.get(exposure.unit, 0.0) + exposure.sensitivity
            contribution += exposure.contribution
        return cls(bucket=bucket, exposures=list(exposures), totals_by_unit=totals, contribution=contribution)
