"""Risk service skeleton.

Phase 1 introduces the boundary only; existing risk functions remain callable.
"""

from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService


class RiskService:
    def __init__(
        self,
        market_data: MarketDataService | None = None,
        governance: GovernanceService | None = None,
    ):
        self.market_data = market_data or MarketDataService()
        self.governance = governance or GovernanceService()
