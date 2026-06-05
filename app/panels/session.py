"""Shared in-session portfolio so 'Add to portfolio' from Pricing lands in Portfolio."""
from services.portfolio_service import PortfolioService

_PORTFOLIO: PortfolioService | None = None


def shared_portfolio() -> PortfolioService:
    global _PORTFOLIO
    if _PORTFOLIO is None:
        _PORTFOLIO = PortfolioService("Main Portfolio")
    return _PORTFOLIO
