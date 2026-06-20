"""Shared application context for the bridge.

Builds the same runtime the desktop app uses — the live MOEX market service +
active snapshot — plus a seeded demo portfolio and the governance/risk services.
Cached so every request shares one DB connection and one snapshot.
"""

from __future__ import annotations

import math

from domain.portfolio import Position
from services.governance_service import GovernanceService
from services.portfolio_service import PortfolioService
from services.risk_service import RiskService


# The desktop's demo book (Main Portfolio · Trading) — real market snapshot,
# representative positions across equity / rates / FX.
_DEMO_POSITIONS = [
    dict(id="pos_option_001", instrument="call", description="ATM equity call",
         quantity=2500, currency="RUB", book="Trading",
         params={"S": 100.0, "K": 100.0, "T": 0.5, "r": 0.05, "sigma": 0.20, "q": 0.0, "opt": "call"}),
    dict(id="pos_bond_001", instrument="bond", description="5Y fixed-rate bond",
         quantity=1_000_000, currency="RUB", book="Trading",
         params={"face": 100.0, "coupon": 0.075, "T": 5.0, "freq": 2, "r": 0.08}),
    dict(id="pos_irs_001", instrument="irs", description="RUB IRS pay fixed 5Y",
         quantity=1.0, currency="RUB", book="Trading",
         params={"notional": 50_000_000.0, "fixed_rate": 0.075, "T": 5.0, "freq": 4, "r": 0.08, "pay_fixed": True}),
    dict(id="pos_fx_001", instrument="fx_forward", description="USD/RUB forward",
         quantity=1_000_000, currency="RUB", book="Trading", ccy_pair="USD/RUB",
         params={"S": 90.0, "K": 91.0, "r_d": 0.10, "r_f": 0.045, "T": 0.25, "ccy_pair": "USD/RUB"}),
]


class AppContext:
    """Process-wide services + data, lazily built and cached."""

    def __init__(self) -> None:
        self._market = None
        self._snapshot = None
        self._portfolio: PortfolioService | None = None
        self.governance = GovernanceService()
        self.risk = RiskService()

    # ── market ───────────────────────────────────────────
    @property
    def market(self):
        if self._market is None:
            from app import runtime
            self._market = runtime.market_service()
        return self._market

    @property
    def snapshot(self):
        if self._snapshot is None:
            from app import runtime
            self._snapshot = runtime.active_snapshot(self.market)
        return self._snapshot

    @property
    def market_db(self):
        return getattr(self.market, "market_db", None)

    def is_live(self) -> bool:
        from app import runtime
        return runtime.is_live()

    def reload(self) -> None:
        """Drop caches and rebind to the freshest snapshot (after an ingest)."""
        from app import runtime
        self._market = None
        self._snapshot = None
        self._portfolio = None
        runtime.market_service(refresh=True)

    # ── portfolio ────────────────────────────────────────
    @property
    def portfolio(self) -> PortfolioService:
        if self._portfolio is None:
            ps = PortfolioService()
            for spec in _DEMO_POSITIONS:
                ps.add(Position(**spec))
            self._portfolio = ps
        return self._portfolio

    # ── parametric VaR/ES (normal) on the portfolio MV ───
    def parametric_var(self, confidence: float = 0.99, horizon: int = 1) -> dict:
        """Closed-form normal VaR/ES on |market value|, σ from the live RTS vol
        when available. Clearly a parametric approximation — labelled as such."""
        from scipy.stats import norm

        from services import market_views as mv

        val = self.portfolio.value()
        mvz = abs(float(val.total_market_value))
        sigma_annual = 0.20
        live_vol = False
        try:
            ov = mv.market_overview(self.market_db, self.snapshot)
            raw = float(ov.get("key_vols", {}).get("RTS", 0.0))
            if raw > 0:
                # market_overview reports implied vols in percent (e.g. 26.5)
                sigma_annual = raw / 100.0 if raw > 1.5 else raw
                live_vol = True
        except Exception:
            pass
        z = float(norm.ppf(confidence))
        scale = sigma_annual * math.sqrt(horizon / 252.0)
        var = z * scale * mvz
        es = (norm.pdf(z) / (1.0 - confidence)) * scale * mvz
        return {
            "market_value": float(val.total_market_value),
            "confidence": confidence,
            "horizon_days": horizon,
            "sigma_annual": sigma_annual,
            "var": var,
            "expected_shortfall": es,
            "method": "Parametric (normal)",
            "vol_source": "live RTS implied vol" if live_vol else "assumed 20%",
        }


# Single shared context for the server process.
CONTEXT = AppContext()
