"""Pricing service skeleton.

Phase 1 intentionally keeps pricing engines untouched. Concrete pricing
methods will be introduced in later phases.
"""

from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService


class PricingService:
    def __init__(
        self,
        market_data: MarketDataService | None = None,
        governance: GovernanceService | None = None,
    ):
        self.market_data = market_data or MarketDataService()
        self.governance = governance or GovernanceService()
