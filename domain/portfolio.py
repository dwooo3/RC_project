"""Portfolio domain contracts."""

from dataclasses import dataclass, field

from domain.risk_factors import RiskFactorExposure


@dataclass
class Position:
    """Single portfolio position with computed valuation state."""

    id: str
    instrument: str
    description: str
    quantity: float
    params: dict

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


@dataclass
class Portfolio:
    """Portfolio as an owned collection of positions."""

    name: str = "Main Portfolio"
    positions: list[Position] = field(default_factory=list)

    def add(self, pos: Position):
        self.positions.append(pos)

    def remove(self, position_id: str):
        self.positions = [p for p in self.positions if p.id != position_id]

    def __len__(self):
        return len(self.positions)

    def __repr__(self):
        return f"Portfolio('{self.name}', {len(self)} positions)"
