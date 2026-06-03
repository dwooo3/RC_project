"""Risk factor exposure contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskFactorExposure:
    """Sensitivity to one named risk factor and bump convention."""

    factor_name: str
    factor_type: str
    currency: str
    bump_size: float
    sensitivity: float
    unit: str
