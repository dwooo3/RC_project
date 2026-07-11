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
        self._audit = None
        self._governance = None
        self._risk = None

    # ── audit / governance (durable: A2 отчёта валидации) ─
    @property
    def audit(self):
        """Shared AuditService persisting every CalculationRecord to AppDB."""
        if self._audit is None:
            from services.audit_service import AuditService
            self._audit = AuditService(db=self.app_db)
        return self._audit

    @property
    def governance(self) -> GovernanceService:
        if self._governance is None:
            self._governance = GovernanceService(audit=self.audit)
        return self._governance

    @property
    def risk(self) -> RiskService:
        if self._risk is None:
            self._risk = RiskService(audit=self.audit)
        return self._risk

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
    _BOOK_ID = "bridge_book"

    @property
    def app_db(self):
        """Application persistence (portfolio book) — data/app.sqlite."""
        if getattr(self, "_app_db", None) is None:
            import os

            from infra.db.app_db import AppDB
            path = os.path.join(os.path.dirname(__file__), "..", "data", "app.sqlite")
            self._app_db = AppDB(os.path.abspath(path))
        return self._app_db

    @property
    def portfolio(self) -> PortfolioService:
        if self._portfolio is None:
            try:
                self._portfolio = PortfolioService.load_from_db(
                    self.app_db, self._BOOK_ID, audit=self.audit)
                if not self._portfolio.positions:
                    raise KeyError("empty book")
            except Exception:
                self._portfolio = self._demo_book()
        return self._portfolio

    def _demo_book(self) -> PortfolioService:
        ps = PortfolioService(audit=self.audit)
        ps.portfolio.portfolio_id = self._BOOK_ID
        ps.portfolio.name = "Bridge book"
        for spec in _DEMO_POSITIONS:
            ps.add(Position(**spec))
        return ps

    # ── books / trade filters (A4) ───────────────────────
    def filtered_portfolio(self, book: str | None = None,
                           instrument: str | None = None,
                           currency: str | None = None) -> PortfolioService:
        """Срез книги по book/инструменту/валюте — отдельный PortfolioService
        на подмножестве позиций (те же pricing/market/audit), для оценок и
        VaR по срезу. Пустые фильтры возвращают основную книгу как есть."""
        ps = self.portfolio
        if not any((book, instrument, currency)):
            return ps
        subset = [p for p in ps.positions
                  if (not book or p.book == book)
                  and (not instrument or p.instrument == instrument)
                  and (not currency or p.currency == currency)]
        import copy
        filtered = PortfolioService(market_data=ps.market_data,
                                    pricing=ps.pricing, audit=self.audit)
        filtered.portfolio.portfolio_id = (
            f"{self._BOOK_ID}:{book or '*'}/{instrument or '*'}/{currency or '*'}")
        filtered.portfolio.name = f"Срез книги ({len(subset)} позиций)"
        for pos in subset:
            filtered.add(copy.deepcopy(pos))
        return filtered

    def books(self) -> list[dict]:
        counts: dict[str, int] = {}
        for p in self.portfolio.positions:
            counts[p.book or "—"] = counts.get(p.book or "—", 0) + 1
        return [{"book": b, "positions": n} for b, n in sorted(counts.items())]

    # ── pricing environments (A1) ────────────────────────
    def environment(self, env_id: str | None = None):
        """Resolve a PricingEnvironment (seeded on first access; default FO)."""
        from domain.pricing_environment import PricingEnvironment, default_environments
        db = self.app_db
        if not db.list_environments():
            for env in default_environments():
                db.save_environment(env)
        payload = db.load_environment((env_id or "FO").upper())
        if payload is None:
            raise KeyError(f"unknown pricing environment '{env_id}'")
        return PricingEnvironment.from_dict(payload)

    def env_snapshot(self, env):
        """Snapshot контура: закреплённый env.snapshot_id или активный."""
        if getattr(env, "snapshot_id", None):
            return self.market.get_snapshot(env.snapshot_id)
        return self.snapshot

    def save_environment(self, env) -> None:
        self.app_db.save_environment(env)
        try:
            from api import marketrisk
            marketrisk.invalidate_cache()          # контур влияет на переоценку
        except Exception:
            pass

    def _portfolio_changed(self) -> None:
        """Persist the book and drop every valuation cache built on it."""
        self.portfolio.save_to_db(self.app_db)
        try:
            from api import marketrisk
            marketrisk.invalidate_cache()
        except Exception:
            pass

    def add_position(self, instrument: str, params: dict, description: str,
                     quantity: float = 1.0) -> Position:
        ps = self.portfolio
        existing = {p.id for p in ps.positions}
        n = 1
        while f"ws_{instrument}_{n:03d}" in existing:
            n += 1
        pos = Position(id=f"ws_{instrument}_{n:03d}", instrument=instrument,
                       description=description, quantity=quantity,
                       currency="RUB", book="Trading", params=params)
        ps.add(pos)
        self._portfolio_changed()
        return pos

    def remove_position(self, position_id: str) -> None:
        self.portfolio.remove(position_id)
        self._portfolio_changed()

    def reset_portfolio(self) -> None:
        """Back to the seeded demo book (and persist that state)."""
        self._portfolio = self._demo_book()
        self._portfolio_changed()

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
