"""Scenario domain contracts."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ScenarioType(str, Enum):
    HISTORICAL = "Historical"
    HYPOTHETICAL = "Hypothetical"
    REGULATORY = "Regulatory"
    CUSTOM = "Custom"


class ScenarioShockType(str, Enum):
    PARALLEL_CURVE_SHIFT = "parallel_curve_shift"
    STEEPENER = "steepener"
    FLATTENER = "flattener"
    FX_SHOCK = "fx_shock"
    EQUITY_SHOCK = "equity_shock"
    VOLATILITY_SHOCK = "volatility_shock"


@dataclass(frozen=True)
class ScenarioShock:
    """Single market shock in a scenario."""

    shock_type: ScenarioShockType | str
    value: float
    unit: str
    bucket: str = ""
    factor_id: str = ""
    tenor: str = ""
    description: str = ""

    @property
    def type_value(self) -> str:
        return self.shock_type.value if hasattr(self.shock_type, "value") else str(self.shock_type)


@dataclass(frozen=True)
class Scenario:
    """Unified scenario definition for market-risk workflows."""

    scenario_id: str
    name: str
    scenario_type: ScenarioType | str
    shocks: list[ScenarioShock] = field(default_factory=list)
    source: str = ""
    as_of: datetime = field(default_factory=_utc_now)
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def type_value(self) -> str:
        return self.scenario_type.value if hasattr(self.scenario_type, "value") else str(self.scenario_type)


@dataclass(frozen=True)
class ScenarioResult:
    """Structured result for a scenario run."""

    scenario: Scenario
    base_value: float
    stressed_value: float
    pnl: float
    bucket_pnl: dict[str, float] = field(default_factory=dict)
    factor_pnl: dict[str, float] = field(default_factory=dict)
    position_pnl: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario.scenario_id,
            "scenario_name": self.scenario.name,
            "scenario_type": self.scenario.type_value,
            "base_value": self.base_value,
            "stressed_value": self.stressed_value,
            "pnl": self.pnl,
            "bucket_pnl": self.bucket_pnl,
            "factor_pnl": self.factor_pnl,
            "position_pnl": self.position_pnl,
            "warnings": self.warnings,
            "errors": self.errors,
            "raw": self.raw,
        }
