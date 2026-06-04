"""Portfolio workflow service."""

from collections import defaultdict

from domain.portfolio import Portfolio, PortfolioRiskResult, PortfolioValuationResult, Position
from domain.risk_factors import RiskFactorExposure, RiskFactorBucket
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService


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
        pricing: PricingService | None = None,
    ):
        if isinstance(portfolio, Portfolio):
            self.portfolio = portfolio
        elif isinstance(portfolio, str):
            self.portfolio = Portfolio(portfolio)
        else:
            self.portfolio = Portfolio()
        self.market_data = market_data or MarketDataService()
        self.pricing = pricing or PricingService(market_data=self.market_data)

    @property
    def positions(self) -> list[Position]:
        return self.portfolio.positions

    def add(self, pos: Position):
        self.portfolio.add(pos)

    def remove(self, position_id: str):
        self.portfolio.remove(position_id)

    def price_all(self):
        """Reprice all positions using their params."""
        errors = []
        warnings = []
        for pos in self.positions:
            try:
                self._price_position(pos)
                warnings.extend(pos.warnings)
                errors.extend(pos.errors)
            except Exception as exc:
                pos.price = float("nan")
                pos.market_value = float("nan")
                pos.exposures = []
                pos.errors = [f"Pricing failed for {pos.id}: {exc}"]
                errors.extend(pos.errors)
        return PortfolioValuationResult(
            portfolio_id=self.portfolio.portfolio_id,
            valuation_date=self.portfolio.valuation_date,
            base_currency=self.portfolio.base_currency,
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            total_market_value=sum(p.market_value for p in self.positions),
            positions=list(self.positions),
            warnings=warnings,
            errors=errors,
        )

    def value(self) -> PortfolioValuationResult:
        """Canonical portfolio valuation entry point."""
        return self.price_all()

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
        pos.warnings = []
        pos.errors = []

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
            res = self.pricing.price_vanilla_option(
                p["S"], p["K"], p["T"], p["r"], p["sigma"], p.get("q", 0), p.get("opt", inst)
            )
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.delta = raw.get("delta", 0.0) * qt
            pos.gamma = raw.get("gamma", 0.0) * qt
            pos.vega = raw.get("vega", 0.0) * qt
            pos.theta = raw.get("theta", 0.0) * qt
            pos.rho = raw.get("rho", 0.0) * qt
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0)
            self._add_exposure(pos, "Equity", "spot_gamma", pos.gamma, "Gamma", 1.0)
            self._add_exposure(pos, "Volatility", "implied_vol", pos.vega, "Vega", 0.01)
            self._add_exposure(pos, "Rates", "risk_free_rate", pos.rho, "Rho", 0.01)

        elif inst == "bond":
            curve = p.get("curve") or self.market_data.flat_curve(p["r"])
            res = self.pricing.price_bond(p["face"], p["coupon"], p["T"], p.get("freq", 2), curve=curve)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt / p["face"]
            pos.dv01 = raw.get("dv01", 0.0) * qt / p["face"]
            pos.delta = raw.get("mod_duration", 0.0) * pos.market_value / 100
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
            pos.model_id = "cds"
            pos.model_status = "Approximation"
            self._add_exposure(pos, "Credit", "credit_spread", pos.cs01, "CS01", 0.0001)

        elif inst in ("irs", "swap"):
            curve = p.get("curve") or self.market_data.flat_curve(p["r"])
            res = self.pricing.price_irs(
                p["notional"], p["fixed_rate"], p["T"], p.get("freq", 4), curve=curve, pay_fixed=p.get("pay_fixed", True)
            )
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = raw.get("dv01", 0.0) * qt
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001)

        elif inst == "equity":
            S = p["S"]
            pos.price = S
            pos.market_value = S * qt
            pos.delta = qt
            pos.model_id = "equity_spot"
            pos.model_status = "Manual"
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0)

        elif inst == "fx_forward":
            res = self.pricing.price_fx_forward(p["S"], p["r_d"], p["r_f"], p["T"])
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = raw.get("forward", res["value"])
            pos.market_value = (pos.price - p.get("K", pos.price)) * qt
            pos.fx_delta = qt
            self._add_exposure(pos, "FX", p.get("ccy_pair", pos.ccy_pair or "fx_spot"), pos.fx_delta, "FX Delta", 1.0)

        elif inst == "future":
            F = p.get("F", p.get("S", 0))
            multiplier = p.get("multiplier", 1)
            pos.price = F
            pos.market_value = F * qt * multiplier
            pos.delta = qt * multiplier
            pos.model_id = "future_mark"
            pos.model_status = "Manual"
            self._add_exposure(pos, "Equity", "future_underlying", pos.delta, "Delta", 1.0)

    def _attach_service_metadata(self, pos: Position, result: dict):
        pos.model_id = result.get("model_id", "")
        pos.model_status = result.get("model_status", "")
        pos.market_data_snapshot_id = result.get("market_data_snapshot_id", "")
        pos.warnings = list(result.get("warnings", []))
        pos.errors = list(result.get("errors", []))

    def aggregate(self) -> dict:
        risk = self.risk()

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
            market_value=risk.market_value,
            exposure_buckets=risk.exposure_buckets,
            risk_factor_exposures=risk.risk_factor_exposures,
            **totals,
        )

    def risk(self) -> PortfolioRiskResult:
        """Canonical portfolio risk aggregation entry point."""
        valuation = self.value()
        scenario = self._scenario_pnl_from_aggregate(
            self._legacy_totals(),
            dS=0,
            dVol=0,
            dr=0,
            dSpread=0,
        )
        return PortfolioRiskResult(
            portfolio_id=self.portfolio.portfolio_id,
            base_currency=self.portfolio.base_currency,
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            market_value=valuation.total_market_value,
            exposure_buckets=self.exposure_buckets(),
            risk_factor_exposures=self.risk_factor_exposures(),
            scenario_pnl=scenario,
            warnings=valuation.warnings,
            errors=valuation.errors,
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
        self.value()
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
        self.value()
        agg = self._legacy_totals()
        return self._scenario_pnl_from_aggregate(agg, dS, dVol, dr, dSpread)

    def _legacy_totals(self) -> dict:
        return {
            "delta": self._sum_unit("Delta"),
            "gamma": self._sum_unit("Gamma"),
            "vega": self._sum_unit("Vega"),
            "rho": self._sum_unit("Rho"),
            "dv01": self._sum_unit("DV01"),
            "cs01": self._sum_unit("CS01"),
            "fx_delta": self._sum_unit("FX Delta"),
            "theta": sum(p.theta for p in self.positions),
        }

    def _scenario_pnl_from_aggregate(
        self,
        agg: dict,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
    ) -> dict:
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
