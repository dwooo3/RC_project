"""Risk factor exposure contracts."""

from dataclasses import dataclass
from typing import Literal


RiskFactorBucket = Literal["Rates", "FX", "Equity", "Credit", "Volatility"]


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
