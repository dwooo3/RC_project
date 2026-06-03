"""Portfolio workflow service."""

from collections import defaultdict

from domain.portfolio import Portfolio, Position
from domain.risk_factors import RiskFactorExposure, RiskFactorBucket
from services.market_data_service import MarketDataService


EXPOSURE_BUCKETS: tuple[RiskFactorBucket, ...] = (
    "Rates",
    "FX",
    "Equity",
    "Credit",
    "Volatility",
)


class PortfolioService:
    """Owns portfolio pricing, risk-factor exposure aggregation, and scenario P&L."""

    def __init__(
        self,
        portfolio: Portfolio | str | None = None,
        market_data: MarketDataService | None = None,
    ):
        if isinstance(portfolio, Portfolio):
            self.portfolio = portfolio
        elif isinstance(portfolio, str):
            self.portfolio = Portfolio(portfolio)
        else:
            self.portfolio = Portfolio()
        self.market_data = market_data or MarketDataService()

    @property
    def positions(self) -> list[Position]:
        return self.portfolio.positions

    def add(self, pos: Position):
        self.portfolio.add(pos)

    def remove(self, position_id: str):
        self.portfolio.remove(position_id)

    def price_all(self):
        """Reprice all positions using their params."""
        for pos in self.positions:
            try:
                self._price_position(pos)
            except Exception:
                pos.price = float("nan")
                pos.market_value = float("nan")
                pos.exposures = []

    def _reset_position_risk(self, pos: Position):
        pos.delta = 0.0
        pos.gamma = 0.0
        pos.vega = 0.0
        pos.theta = 0.0
        pos.rho = 0.0
        pos.dv01 = 0.0
        pos.cs01 = 0.0
        pos.fx_delta = 0.0
        pos.exposures = []

    def _add_exposure(
        self,
        pos: Position,
        bucket: RiskFactorBucket,
        factor_name: str,
        sensitivity: float,
        unit: str,
        bump_size: float,
        factor_type: str | None = None,
    ):
        if sensitivity == 0:
            return
        pos.exposures.append(
            RiskFactorExposure(
                factor_name=factor_name,
                factor_type=factor_type or bucket.lower(),
                currency=pos.currency,
                bump_size=bump_size,
                sensitivity=sensitivity,
                unit=unit,
                bucket=bucket,
            )
        )

    def _price_position(self, pos: Position):
        self._reset_position_risk(pos)
        p = pos.params
        qt = pos.quantity
        inst = pos.instrument

        if inst in ("call", "put", "option"):
            from models.black_scholes import bsm

            g = bsm(p["S"], p["K"], p["T"], p["r"], p["sigma"], p.get("q", 0), p.get("opt", inst))
            pos.price = g.price
            pos.market_value = g.price * qt
            pos.delta = g.delta * qt
            pos.gamma = g.gamma * qt
            pos.vega = g.vega * qt
            pos.theta = g.theta * qt
            pos.rho = g.rho * qt
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0)
            self._add_exposure(pos, "Equity", "spot_gamma", pos.gamma, "Gamma", 1.0)
            self._add_exposure(pos, "Volatility", "implied_vol", pos.vega, "Vega", 0.01)
            self._add_exposure(pos, "Rates", "risk_free_rate", pos.rho, "Rho", 0.01)

        elif inst == "bond":
            from instruments.fixed_income import fixed_bond

            curve = p.get("curve") or self.market_data.flat_curve(p["r"])
            res = fixed_bond(p["face"], p["coupon"], p["T"], p.get("freq", 2), curve)
            pos.price = res["price"]
            pos.market_value = res["price"] * qt / p["face"]
            pos.dv01 = res["dv01"] * qt / p["face"]
            pos.delta = res["mod_duration"] * pos.market_value / 100
            self._add_exposure(pos, "Rates", "yield_curve", pos.dv01, "DV01", 0.0001)

        elif inst == "cds":
            from instruments.credit import cds, cds_implied_hazard

            hazard = cds_implied_hazard(
                p["spread"], p["T"], p.get("freq", 4), p["r"], p.get("recovery", 0.4)
            )
            res = cds(
                p["notional"], p["spread"], p["T"], p.get("freq", 4),
                hazard, p["r"], p.get("recovery", 0.4), p.get("buy", True)
            )
            pos.price = res["npv"]
            pos.market_value = res["npv"] * qt
            pos.cs01 = res["dv01"] * qt
            self._add_exposure(pos, "Credit", "credit_spread", pos.cs01, "CS01", 0.0001)

        elif inst in ("irs", "swap"):
            from instruments.fixed_income import irs

            curve = p.get("curve") or self.market_data.flat_curve(p["r"])
            res = irs(p["notional"], p["fixed_rate"], p["T"], p.get("freq", 4), curve, p.get("pay_fixed", True))
            pos.price = res["npv"]
            pos.market_value = res["npv"] * qt
            pos.dv01 = res["dv01"] * qt
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001)

        elif inst == "equity":
            S = p["S"]
            pos.price = S
            pos.market_value = S * qt
            pos.delta = qt
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0)

        elif inst == "fx_forward":
            from instruments.fx import fx_forward

            res = fx_forward(p["S"], p["r_d"], p["r_f"], p["T"])
            pos.price = res["forward"]
            pos.market_value = (res["forward"] - p.get("K", res["forward"])) * qt
            pos.fx_delta = qt
            self._add_exposure(pos, "FX", p.get("ccy_pair", pos.ccy_pair or "fx_spot"), pos.fx_delta, "FX Delta", 1.0)

        elif inst == "future":
            F = p.get("F", p.get("S", 0))
            multiplier = p.get("multiplier", 1)
            pos.price = F
            pos.market_value = F * qt * multiplier
            pos.delta = qt * multiplier
            self._add_exposure(pos, "Equity", "future_underlying", pos.delta, "Delta", 1.0)

    def aggregate(self) -> dict:
        self.price_all()
        exposure_buckets = self.exposure_buckets()
        total_mv = sum(p.market_value for p in self.positions)

        totals = {
            "delta": self._sum_unit("Delta"),
            "gamma": self._sum_unit("Gamma"),
            "vega": self._sum_unit("Vega"),
            "rho": self._sum_unit("Rho"),
            "dv01": self._sum_unit("DV01"),
            "cs01": self._sum_unit("CS01"),
            "fx_delta": self._sum_unit("FX Delta"),
            "theta": sum(p.theta for p in self.positions),
        }

        return dict(
            n_positions=len(self.positions),
            market_value=total_mv,
            exposure_buckets=exposure_buckets,
            risk_factor_exposures=self.risk_factor_exposures(),
            **totals,
        )

    def _sum_unit(self, unit: str) -> float:
        return sum(exp.sensitivity for exp in self.risk_factor_exposures() if exp.unit == unit)

    def risk_factor_exposures(self) -> list[RiskFactorExposure]:
        exposures: list[RiskFactorExposure] = []
        for pos in self.positions:
            exposures.extend(pos.exposures)
        return exposures

    def exposure_buckets(self) -> dict[str, dict[str, float]]:
        buckets = {bucket: {} for bucket in EXPOSURE_BUCKETS}
        for exp in self.risk_factor_exposures():
            bucket = buckets.setdefault(exp.bucket, {})
            bucket.setdefault(exp.unit, 0.0)
            bucket[exp.unit] += exp.sensitivity
        return buckets

    def positions_table(self) -> list[dict]:
        self.price_all()
        return [
            dict(
                id=p.id,
                instrument=p.instrument,
                description=p.description,
                quantity=p.quantity,
                price=round(p.price, 4),
                market_value=round(p.market_value, 2),
                delta=round(p.delta, 4),
                gamma=round(p.gamma, 6),
                vega=round(p.vega, 4),
                theta=round(p.theta, 4),
                dv01=round(p.dv01, 2),
                cs01=round(p.cs01, 2),
                currency=p.currency,
                book=p.book,
            )
            for p in self.positions
        ]

    def scenario_pnl(self, dS: float = 0, dVol: float = 0, dr: float = 0, dSpread: float = 0) -> dict:
        """First-order scenario P&L by risk-factor bucket."""
        agg = self.aggregate()
        components = {
            "Equity": agg["delta"] * dS + agg["gamma"] * dS**2 / 2,
            "Volatility": agg["vega"] * dVol * 100,
            "Rates": agg["rho"] * dr * 100 - agg["dv01"] * dr * 10000,
            "Credit": -agg["cs01"] * dSpread * 10000,
            "FX": agg["fx_delta"] * dS,
            "Theta": agg["theta"],
        }
        pnl = sum(components.values())
        legacy_components = defaultdict(float)
        legacy_components.update(
            delta=agg["delta"] * dS,
            gamma=agg["gamma"] * dS**2 / 2,
            vega=agg["vega"] * dVol * 100,
            theta=agg["theta"],
            rho=agg["rho"] * dr * 100,
            ir_01=agg["dv01"] * dr * 10000,
            cs_01=agg["cs01"] * dSpread * 10000,
            fx=agg["fx_delta"] * dS,
        )
        return dict(
            pnl=pnl,
            dS=dS,
            dVol=dVol,
            dr=dr,
            dSpread=dSpread,
            bucket_pnl=components,
            components=dict(legacy_components),
        )

    def __len__(self):
        return len(self.portfolio)

    def __repr__(self):
        return repr(self.portfolio)
