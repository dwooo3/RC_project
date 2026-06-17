"""Backward-compatible portfolio facade.

Portfolio ownership lives in domain.portfolio and services.portfolio_service.
This module preserves the legacy import path used by existing UI and scripts.
"""

from services.portfolio_service import PortfolioService


class Portfolio(PortfolioService):
    """Compatibility wrapper for the former risk.portfolio.Portfolio API."""

    pass
