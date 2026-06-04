"""Portfolio domain contracts."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from domain.risk_factors import RiskFactorExposure


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PositionType(str, Enum):
    OPTION = "option"
    BOND = "bond"
    IRS = "irs"
    CDS = "cds"
    EQUITY = "equity"
    FX_FORWARD = "fx_forward"
    FUTURE = "future"
    UNKNOWN = "unknown"

    @classmethod
    def from_instrument(cls, instrument: str) -> "PositionType":
        key = instrument.lower()
        if key in {"call", "put", "option"}:
            return cls.OPTION
        if key in {"irs", "swap"}:
            return cls.IRS
        try:
            return cls(key)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class Position:
    """Single portfolio position with computed valuation state."""

    id: str
    instrument: str
    description: str
    quantity: float
    params: dict
    position_type: PositionType | str | None = None

    price: float = 0.0
    market_value: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    rho: float = 0.0
    dv01: float = 0.0
    cs01: float = 0.0
    fx_delta: float = 0.0
    pnl_1d: float = 0.0
    exposures: list[RiskFactorExposure] = field(default_factory=list)

    currency: str = "RUB"
    book: str = "Trading"
    trader: str = ""
    ccy_pair: str = ""
    market_data_snapshot_id: str = ""
    model_id: str = ""
    model_status: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.position_type is None:
            self.position_type = PositionType.from_instrument(self.instrument)
        elif not isinstance(self.position_type, PositionType):
            self.position_type = PositionType.from_instrument(str(self.position_type))

    @property
    def type(self) -> PositionType:
        return self.position_type if isinstance(self.position_type, PositionType) else PositionType.UNKNOWN


@dataclass
class Portfolio:
    """Portfolio as an owned collection of positions."""

    name: str = "Main Portfolio"
    positions: list[Position] = field(default_factory=list)
    portfolio_id: str = ""
    base_currency: str = "RUB"
    valuation_date: date | None = None
    market_data_snapshot_id: str = ""
    owner: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self):
        if not self.portfolio_id:
            self.portfolio_id = self.name.lower().replace(" ", "-")

    def add(self, pos: Position):
        self.positions.append(pos)
        self.updated_at = _utc_now()

    def remove(self, position_id: str):
        self.positions = [p for p in self.positions if p.id != position_id]
        self.updated_at = _utc_now()

    def by_type(self, position_type: PositionType | str) -> list[Position]:
        target = position_type if isinstance(position_type, PositionType) else PositionType.from_instrument(str(position_type))
        return [position for position in self.positions if position.type == target]

    def __len__(self):
        return len(self.positions)

    def __repr__(self):
        return f"Portfolio('{self.name}', {len(self)} positions)"


@dataclass(frozen=True)
class PortfolioValuationResult:
    """Portfolio-level valuation output owned by PortfolioService."""

    portfolio_id: str
    valuation_date: date | None
    base_currency: str
    market_data_snapshot_id: str
    total_market_value: float
    positions: list[Position]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PortfolioRiskResult:
    """Portfolio-level risk aggregation output owned by PortfolioService."""

    portfolio_id: str
    base_currency: str
    market_data_snapshot_id: str
    market_value: float
    exposure_buckets: dict[str, dict[str, float]]
    risk_factor_exposures: list[RiskFactorExposure]
    scenario_pnl: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
