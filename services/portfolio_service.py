"""Portfolio workflow service."""

from collections import defaultdict

from domain.portfolio import Portfolio, PortfolioRiskResult, PortfolioValuationResult, Position
from domain.risk_factors import RiskFactor, RiskFactorExposure, RiskFactorBucket, RiskFactorGroup
from domain.results import PnLExplainResult
from domain.scenario import Scenario, ScenarioResult, ScenarioShock, ScenarioShockType, ScenarioType
from services.audit_service import AuditService
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService


EXPOSURE_BUCKETS: tuple[RiskFactorBucket, ...] = (
    "Rates",
    "FX",
    "Equity",
    "Credit",
    "Volatility",
)


CANONICAL_RISK_FACTORS: dict[str, RiskFactor] = {
    "rates.yield_curve": RiskFactor(
        factor_id="rates.yield_curve",
        name="Yield Curve",
        bucket="Rates",
        factor_type="yield_curve",
        currency="RUB",
        unit="DV01",
        bump_size=0.0001,
    ),
    "rates.swap_curve": RiskFactor(
        factor_id="rates.swap_curve",
        name="Swap Curve",
        bucket="Rates",
        factor_type="swap_curve",
        currency="RUB",
        unit="DV01",
        bump_size=0.0001,
    ),
    "rates.risk_free_rate": RiskFactor(
        factor_id="rates.risk_free_rate",
        name="Risk-Free Rate",
        bucket="Rates",
        factor_type="rate",
        currency="RUB",
        unit="Rho",
        bump_size=0.01,
    ),
    "fx.spot": RiskFactor(
        factor_id="fx.spot",
        name="FX Spot",
        bucket="FX",
        factor_type="fx_spot",
        unit="FX Delta",
        bump_size=1.0,
    ),
    "equity.spot": RiskFactor(
        factor_id="equity.spot",
        name="Equity Spot",
        bucket="Equity",
        factor_type="spot",
        unit="Delta",
        bump_size=1.0,
    ),
    "equity.spot_gamma": RiskFactor(
        factor_id="equity.spot_gamma",
        name="Equity Spot Gamma",
        bucket="Equity",
        factor_type="spot_gamma",
        unit="Gamma",
        bump_size=1.0,
    ),
    "credit.spread": RiskFactor(
        factor_id="credit.spread",
        name="Credit Spread",
        bucket="Credit",
        factor_type="credit_spread",
        unit="CS01",
        bump_size=0.0001,
    ),
    "vol.implied": RiskFactor(
        factor_id="vol.implied",
        name="Implied Volatility",
        bucket="Volatility",
        factor_type="implied_vol",
        unit="Vega",
        bump_size=0.01,
    ),
}


class PortfolioService:
    """Owns portfolio pricing, risk-factor exposure aggregation, and scenario P&L."""

    def __init__(
        self,
        portfolio: Portfolio | str | None = None,
        market_data: MarketDataService | None = None,
        pricing: PricingService | None = None,
        audit: AuditService | None = None,
    ):
        if isinstance(portfolio, Portfolio):
            self.portfolio = portfolio
        elif isinstance(portfolio, str):
            self.portfolio = Portfolio(portfolio)
        else:
            self.portfolio = Portfolio()
        self.market_data = market_data or MarketDataService()
        self.audit = audit or getattr(pricing, "audit", None) or AuditService()
        self.pricing = pricing or PricingService(market_data=self.market_data, audit=self.audit)

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
        record = self.audit.record_calculation(
            user_action="Value portfolio",
            calculation_type="portfolio_valuation",
            model_id="portfolio_service",
            model_version="1.0",
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            inputs=self._portfolio_inputs(),
            result_id=f"portfolio_valuation:{self.portfolio.portfolio_id}",
            details={"positions": len(self.positions), "errors": errors},
        )
        return PortfolioValuationResult(
            portfolio_id=self.portfolio.portfolio_id,
            valuation_date=self.portfolio.valuation_date,
            base_currency=self.portfolio.base_currency,
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            total_market_value=sum(p.market_value for p in self.positions),
            positions=list(self.positions),
            warnings=warnings,
            errors=errors,
            calculation_record=record,
            calculation_id=record.record_id,
            inputs_hash=record.inputs_hash,
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
        factor_id: str | None = None,
    ):
        if sensitivity == 0:
            return
        resolved_factor_id = factor_id or self._factor_id(bucket, factor_name)
        pos.exposures.append(
            RiskFactorExposure(
                factor_name=factor_name,
                factor_type=factor_type or bucket.lower(),
                currency=pos.currency,
                bump_size=bump_size,
                sensitivity=sensitivity,
                unit=unit,
                bucket=bucket,
                factor_id=resolved_factor_id,
                position_id=pos.id,
            )
        )

    def _factor_id(self, bucket: RiskFactorBucket | str, factor_name: str) -> str:
        normalized_name = factor_name.lower().replace(" ", "_")
        candidates = {
            ("Rates", "yield_curve"): "rates.yield_curve",
            ("Rates", "swap_curve"): "rates.swap_curve",
            ("Rates", "risk_free_rate"): "rates.risk_free_rate",
            ("FX", "fx_spot"): "fx.spot",
            ("FX", normalized_name): f"fx.{normalized_name}",
            ("Equity", "spot"): "equity.spot",
            ("Equity", "spot_gamma"): "equity.spot_gamma",
            ("Equity", "future_underlying"): "equity.spot",
            ("Credit", "credit_spread"): "credit.spread",
            ("Volatility", "implied_vol"): "vol.implied",
        }
        return candidates.get((bucket, factor_name), f"{str(bucket).lower()}.{normalized_name}")

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
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0, factor_id="equity.spot")
            self._add_exposure(pos, "Equity", "spot_gamma", pos.gamma, "Gamma", 1.0, factor_id="equity.spot_gamma")
            self._add_exposure(pos, "Volatility", "implied_vol", pos.vega, "Vega", 0.01, factor_id="vol.implied")
            self._add_exposure(pos, "Rates", "risk_free_rate", pos.rho, "Rho", 0.01, factor_id="rates.risk_free_rate")

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
            self._add_exposure(pos, "Rates", "yield_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.yield_curve")

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
            self._add_exposure(pos, "Credit", "credit_spread", pos.cs01, "CS01", 0.0001, factor_id="credit.spread")

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
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")

        elif inst == "equity":
            S = p["S"]
            pos.price = S
            pos.market_value = S * qt
            pos.delta = qt
            pos.model_id = "equity_spot"
            pos.model_status = "Manual"
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0, factor_id="equity.spot")

        elif inst == "fx_forward":
            res = self.pricing.price_fx_forward(p["S"], p["r_d"], p["r_f"], p["T"])
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = raw.get("forward", res["value"])
            pos.market_value = (pos.price - p.get("K", pos.price)) * qt
            pos.fx_delta = qt
            self._add_exposure(
                pos,
                "FX",
                p.get("ccy_pair", pos.ccy_pair or "fx_spot"),
                pos.fx_delta,
                "FX Delta",
                1.0,
                factor_id=f"fx.{p.get('ccy_pair', pos.ccy_pair or 'spot').lower()}",
            )

        elif inst == "future":
            F = p.get("F", p.get("S", 0))
            multiplier = p.get("multiplier", 1)
            pos.price = F
            pos.market_value = F * qt * multiplier
            pos.delta = qt * multiplier
            pos.model_id = "future_mark"
            pos.model_status = "Manual"
            self._add_exposure(pos, "Equity", "future_underlying", pos.delta, "Delta", 1.0, factor_id="equity.spot")

        elif inst == "digital":
            res = self.pricing.price_digital_option(
                p["S"], p["K"], p["T"], p["r"], p["sigma"], p.get("q", 0),
                p.get("opt", "call"), p.get("style", "cash"), p.get("cash", 1.0))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.delta = raw.get("delta", 0.0) * qt
            pos.gamma = raw.get("gamma", 0.0) * qt
            pos.vega = raw.get("vega", 0.0) * qt
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0, factor_id="equity.spot")
            self._add_exposure(pos, "Equity", "spot_gamma", pos.gamma, "Gamma", 1.0, factor_id="equity.spot_gamma")
            self._add_exposure(pos, "Volatility", "implied_vol", pos.vega, "Vega", 0.01, factor_id="vol.implied")

        elif inst in ("barrier", "asian", "lookback", "spread", "basket", "autocall"):
            # Engines return price only (or MC) -> sensitivities via finite difference.
            base, S0, vol0 = self._equity_exotic_pricer(inst, p)
            res = base(S0, vol0)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            p0, delta, gamma, vega = self._fd_equity_greeks(lambda S, v: base(S, v)["value"], S0, vol0)
            pos.price = p0
            pos.market_value = p0 * qt
            pos.delta = delta * qt
            pos.gamma = gamma * qt
            pos.vega = vega * qt
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0, factor_id="equity.spot")
            self._add_exposure(pos, "Equity", "spot_gamma", pos.gamma, "Gamma", 1.0, factor_id="equity.spot_gamma")
            self._add_exposure(pos, "Volatility", "implied_vol", pos.vega, "Vega", 0.01, factor_id="vol.implied")

        elif inst == "frn":
            curve = p.get("curve") or self.market_data.flat_curve(p["r"])
            res = self.pricing.price_frn(p["face"], p["spread"], p["T"], p.get("freq", 2), curve=curve)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt / p["face"]
            pos.dv01 = self._fd_rates_dv01(lambda r: self.pricing.price_frn(
                p["face"], p["spread"], p["T"], p.get("freq", 2),
                curve=self.market_data.flat_curve(r))["value"], p["r"]) * qt / p["face"]
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")

        elif inst == "fra":
            curve = p.get("curve") or self.market_data.flat_curve(p["r"])
            res = self.pricing.price_fra(p["notional"], p["K"], p["T1"], p["T2"], curve=curve)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = self._fd_rates_dv01(lambda r: self.pricing.price_fra(
                p["notional"], p["K"], p["T1"], p["T2"],
                curve=self.market_data.flat_curve(r))["value"], p["r"]) * qt
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")

        elif inst in ("cap", "floor", "cap_floor"):
            curve = p.get("curve") or self.market_data.flat_curve(p["r"])
            opt = p.get("opt", "cap")
            res = self.pricing.price_cap_floor(
                p["notional"], p["K"], p["T"], p.get("freq", 2), p["vol"], opt, curve=curve)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = self._fd_rates_dv01(lambda r: self.pricing.price_cap_floor(
                p["notional"], p["K"], p["T"], p.get("freq", 2), p["vol"], opt,
                curve=self.market_data.flat_curve(r))["value"], p["r"]) * qt
            pos.vega = self._fd_vol_vega(lambda v: self.pricing.price_cap_floor(
                p["notional"], p["K"], p["T"], p.get("freq", 2), v, opt, curve=curve)["value"],
                p["vol"]) * qt
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")
            self._add_exposure(pos, "Volatility", "rate_vol", pos.vega, "Vega", 0.01, factor_id="vol.rate")

        elif inst == "swaption":
            curve = p.get("curve") or self.market_data.flat_curve(p["r"])
            opt = p.get("opt", "payer")
            res = self.pricing.price_swaption(
                p["notional"], p["K"], p["T_option"], p["T_swap"], p.get("freq", 2),
                p["sigma"], opt, curve=curve)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = self._fd_rates_dv01(lambda r: self.pricing.price_swaption(
                p["notional"], p["K"], p["T_option"], p["T_swap"], p.get("freq", 2),
                p["sigma"], opt, curve=self.market_data.flat_curve(r))["value"], p["r"]) * qt
            pos.vega = self._fd_vol_vega(lambda v: self.pricing.price_swaption(
                p["notional"], p["K"], p["T_option"], p["T_swap"], p.get("freq", 2),
                v, opt, curve=curve)["value"], p["sigma"]) * qt
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")
            self._add_exposure(pos, "Volatility", "rate_vol", pos.vega, "Vega", 0.01, factor_id="vol.rate")

    def _equity_exotic_pricer(self, inst: str, p: dict):
        """Return (value_fn(S, sigma) -> governed result, base_spot, base_vol) for an exotic."""
        if inst == "barrier":
            return (lambda S, v: self.pricing.price_barrier_option(
                S, p["K"], p["H"], p["T"], p["r"], v, p.get("q", 0),
                p.get("opt", "call"), p.get("barrier_type", "down-out"))), p["S"], p["sigma"]
        if inst == "asian":
            return (lambda S, v: self.pricing.price_asian_option(
                S, p["K"], p["T"], p["r"], v, p.get("q", 0), p.get("opt", "call"),
                p.get("averaging", "arithmetic"), p.get("n", 12),
                p.get("n_sims", 20_000))), p["S"], p["sigma"]
        if inst == "lookback":
            return (lambda S, v: self.pricing.price_lookback_option(
                S, p["T"], p["r"], v, p.get("q", 0), p.get("opt", "call"),
                p.get("strike_type", "floating"), p.get("K"))), p["S"], p["sigma"]
        if inst == "spread":
            return (lambda S, v: self.pricing.price_spread_option(
                S, p["S2"], p["K"], p["T"], p["r"], v, p["sigma2"], p["rho"],
                p.get("q1", 0), p.get("q2", 0))), p["S1"], p["sigma1"]
        if inst == "basket":
            return (lambda S, v: self.pricing.price_basket_option(
                [S] + list(p["assets"][1:]), p["weights"], p["K"], p["T"], p["r"],
                [v] + list(p["sigmas"][1:]), p["corr"], p.get("opt", "call"))), \
                p["assets"][0], p["sigmas"][0]
        # autocall / phoenix
        return (lambda S, v: self.pricing.price_autocall_phoenix(
            S, p["r"], p.get("q", 0), v, p["T"], p["obs_dates"], p["autocall_barrier"],
            p["coupon_barrier"], p["ki_barrier"], p["coupon_rate"],
            p.get("memory_coupon", True), p.get("n_sims", 20_000),
            p.get("steps", 100))), p["S0"], p["sigma"]

    @staticmethod
    def _fd_equity_greeks(value_fn, S: float, sigma: float):
        """Central-difference (price, delta, gamma, vega-per-1%) for an equity pricer."""
        dS = max(abs(S) * 0.01, 1e-4)
        dV = 0.01
        p0 = value_fn(S, sigma)
        pu, pd = value_fn(S + dS, sigma), value_fn(S - dS, sigma)
        vu, vd = value_fn(S, sigma + dV), value_fn(S, sigma - dV)
        delta = (pu - pd) / (2 * dS)
        gamma = (pu - 2 * p0 + pd) / (dS * dS)
        vega = (vu - vd) / (2 * dV) * 0.01
        return p0, delta, gamma, vega

    @staticmethod
    def _fd_rates_dv01(value_fn, r: float):
        """DV01 via a 1bp parallel curve bump: price change for a 1bp fall in rates."""
        dr = 1e-4
        return (value_fn(r - dr) - value_fn(r + dr)) / 2.0

    @staticmethod
    def _fd_vol_vega(value_fn, sigma: float, dV: float = 0.01):
        """Vega per 1% vol via central difference."""
        return (value_fn(sigma + dV) - value_fn(sigma - dV)) / (2 * dV) * 0.01

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
            risk_factors=self.risk_factor_totals(),
            risk_factor_groups=risk.risk_factor_groups,
            factor_contributions=risk.factor_contributions,
            **totals,
        )

    def risk(self) -> PortfolioRiskResult:
        """Canonical portfolio risk aggregation entry point."""
        valuation = self.value()
        scenario = self._scenario_pnl_from_exposures(dS=0, dVol=0, dr=0, dSpread=0)
        record = self.audit.record_calculation(
            user_action="Aggregate portfolio risk",
            calculation_type="portfolio_risk",
            model_id="portfolio_service",
            model_version="1.0",
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            inputs=self._portfolio_inputs(),
            result_id=f"portfolio_risk:{self.portfolio.portfolio_id}",
            details={"valuation_calculation_id": valuation.calculation_id},
        )
        return PortfolioRiskResult(
            portfolio_id=self.portfolio.portfolio_id,
            base_currency=self.portfolio.base_currency,
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            market_value=valuation.total_market_value,
            exposure_buckets=self.exposure_buckets(),
            risk_factor_exposures=self.risk_factor_exposures(),
            risk_factor_groups=self.risk_factor_groups(),
            factor_contributions=self.factor_contributions(),
            scenario_pnl=scenario,
            warnings=valuation.warnings,
            errors=valuation.errors,
            calculation_record=record,
            calculation_id=record.record_id,
            inputs_hash=record.inputs_hash,
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

    def risk_factor_totals(self) -> dict[str, dict[str, float | str]]:
        """Aggregate exposures by canonical factor ID."""
        factors: dict[str, dict[str, float | str]] = {}
        for exp in self.risk_factor_exposures():
            factor_id = exp.factor_id or self._factor_id(exp.bucket, exp.factor_name)
            factor = factors.setdefault(
                factor_id,
                {
                    "factor_id": factor_id,
                    "factor_name": exp.factor_name,
                    "bucket": exp.bucket,
                    "factor_type": exp.factor_type,
                    "currency": exp.currency,
                    "unit": exp.unit,
                    "sensitivity": 0.0,
                    "contribution": 0.0,
                },
            )
            factor["sensitivity"] = float(factor["sensitivity"]) + exp.sensitivity
            factor["contribution"] = float(factor["contribution"]) + exp.contribution
        return factors

    def risk_factor_groups(self) -> list[RiskFactorGroup]:
        groups: dict[str, list[RiskFactorExposure]] = {bucket: [] for bucket in EXPOSURE_BUCKETS}
        for exp in self.risk_factor_exposures():
            groups.setdefault(exp.bucket, []).append(exp)
        return [
            RiskFactorGroup.from_exposures(bucket, exposures)
            for bucket, exposures in groups.items()
        ]

    def factor_contributions(
        self,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
    ) -> dict[str, float]:
        contributions: defaultdict[str, float] = defaultdict(float)
        for exp in self.risk_factor_exposures():
            factor_id = exp.factor_id or self._factor_id(exp.bucket, exp.factor_name)
            contributions[factor_id] += self._exposure_pnl(exp, dS, dVol, dr, dSpread)
        return dict(contributions)

    def run_scenario(self, scenario: Scenario | dict) -> ScenarioResult:
        """Run a unified scenario against current portfolio factor exposures."""
        scenario = self._coerce_scenario(scenario)
        valuation = self.value()
        raw, warnings = self._scenario_pnl_from_scenario(scenario)
        pnl = raw["pnl"]
        record = self.audit.record_calculation(
            user_action="Run portfolio scenario",
            calculation_type="portfolio_scenario",
            model_id="portfolio_service",
            model_version="1.0",
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            inputs={"portfolio": self._portfolio_inputs(), "scenario": scenario},
            result_id=f"portfolio_scenario:{self.portfolio.portfolio_id}:{scenario.scenario_id}",
            details={"valuation_calculation_id": valuation.calculation_id},
        )
        return ScenarioResult(
            scenario=scenario,
            base_value=valuation.total_market_value,
            stressed_value=valuation.total_market_value + pnl,
            pnl=pnl,
            bucket_pnl=raw.get("bucket_pnl", {}),
            factor_pnl=raw.get("factor_pnl", {}),
            position_pnl=raw.get("position_pnl", {}),
            warnings=warnings + valuation.warnings,
            errors=valuation.errors,
            raw=raw,
            calculation_record=record,
            calculation_id=record.record_id,
            inputs_hash=record.inputs_hash,
        )

    def _coerce_scenario(self, scenario: Scenario | dict) -> Scenario:
        if isinstance(scenario, Scenario):
            return scenario
        shocks = [
            shock if isinstance(shock, ScenarioShock) else ScenarioShock(**shock)
            for shock in scenario.get("shocks", [])
        ]
        return Scenario(
            scenario_id=scenario.get("scenario_id", scenario.get("name", "custom").lower().replace(" ", "-")),
            name=scenario.get("name", "Custom Scenario"),
            scenario_type=scenario.get("scenario_type", ScenarioType.CUSTOM),
            shocks=shocks,
            source=scenario.get("source", ""),
            description=scenario.get("description", ""),
            metadata=scenario.get("metadata", {}),
        )

    def _bps_to_rate(self, shock: ScenarioShock) -> float:
        return shock.value / 10000 if shock.unit.lower() in {"bp", "bps", "basis_points"} else shock.value

    def _scenario_pnl_from_scenario(self, scenario: Scenario) -> tuple[dict, list[str]]:
        bucket_pnl: defaultdict[str, float] = defaultdict(float)
        factor_pnl: defaultdict[str, float] = defaultdict(float)
        position_pnl: defaultdict[str, float] = defaultdict(float)
        warnings: list[str] = []

        for exp in self.risk_factor_exposures():
            factor_id = exp.factor_id or self._factor_id(exp.bucket, exp.factor_name)
            for shock in scenario.shocks:
                contribution, warning = self._shock_exposure_pnl(exp, shock)
                if warning and warning not in warnings:
                    warnings.append(warning)
                if contribution == 0.0:
                    continue
                bucket_pnl[exp.bucket] += contribution
                factor_pnl[factor_id] += contribution
                position_pnl[exp.position_id] += contribution

        pnl = sum(bucket_pnl.values())
        return (
            dict(
                pnl=pnl,
                scenario_id=scenario.scenario_id,
                scenario_name=scenario.name,
                scenario_type=scenario.type_value,
                bucket_pnl={bucket: bucket_pnl.get(bucket, 0.0) for bucket in EXPOSURE_BUCKETS},
                factor_pnl=dict(factor_pnl),
                position_pnl=dict(position_pnl),
            ),
            warnings,
        )

    def _shock_exposure_pnl(self, exp: RiskFactorExposure, shock: ScenarioShock) -> tuple[float, str]:
        shock_type = shock.type_value
        if shock.factor_id and exp.factor_id and shock.factor_id != exp.factor_id:
            return 0.0, ""
        if shock.bucket and shock.bucket != exp.bucket:
            return 0.0, ""

        if shock_type == ScenarioShockType.EQUITY_SHOCK.value:
            if exp.bucket != "Equity":
                return 0.0, ""
            if exp.unit == "Delta":
                return exp.sensitivity * shock.value, ""
            if exp.unit == "Gamma":
                return exp.sensitivity * shock.value**2 / 2, ""
            return 0.0, ""

        if shock_type == ScenarioShockType.FX_SHOCK.value:
            if exp.bucket != "FX" or exp.unit != "FX Delta":
                return 0.0, ""
            return exp.sensitivity * shock.value, ""

        if shock_type == ScenarioShockType.VOLATILITY_SHOCK.value:
            if exp.bucket != "Volatility" or exp.unit != "Vega":
                return 0.0, ""
            return exp.sensitivity * shock.value * 100, ""

        if shock_type == ScenarioShockType.PARALLEL_CURVE_SHIFT.value:
            if exp.bucket != "Rates":
                return 0.0, ""
            return self._rate_exposure_pnl(exp, self._bps_to_rate(shock)), ""

        if shock_type == ScenarioShockType.STEEPENER.value:
            if exp.bucket != "Rates":
                return 0.0, ""
            warning = "Steepener scenario is approximated through aggregate rate DV01 until tenor-level exposures are available."
            return self._rate_exposure_pnl(exp, self._bps_to_rate(shock)), warning

        if shock_type == ScenarioShockType.FLATTENER.value:
            if exp.bucket != "Rates":
                return 0.0, ""
            warning = "Flattener scenario is approximated through aggregate rate DV01 until tenor-level exposures are available."
            return self._rate_exposure_pnl(exp, -self._bps_to_rate(shock)), warning

        if exp.bucket == "Credit" and exp.unit == "CS01":
            return -exp.sensitivity * self._bps_to_rate(shock) * 10000, ""
        return 0.0, ""

    def _rate_exposure_pnl(self, exp: RiskFactorExposure, dr: float) -> float:
        if exp.unit == "DV01":
            return -exp.sensitivity * dr * 10000
        if exp.unit == "Rho":
            return exp.sensitivity * dr * 100
        return 0.0

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
        return self._scenario_pnl_from_exposures(dS, dVol, dr, dSpread)

    def explain_pnl(
        self,
        total_pnl: float | None = None,
        *,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
        theta_days: float = 0,
        scenario: Scenario | dict | None = None,
    ) -> PnLExplainResult:
        """Explain portfolio P&L using risk-factor exposures."""
        self.value()
        if scenario is not None:
            scenario_result = self.run_scenario(scenario)
            components = self._pnl_components_from_scenario(scenario_result.raw, theta_days=theta_days)
            factor_pnl = scenario_result.factor_pnl
            position_pnl = scenario_result.position_pnl
            estimated_total = scenario_result.pnl + components["theta_pnl"]
            warnings = list(scenario_result.warnings)
            errors = list(scenario_result.errors)
        else:
            raw = self._scenario_pnl_from_exposures(dS, dVol, dr, dSpread, theta_days=theta_days)
            components = self._pnl_components_from_legacy(raw)
            factor_pnl = raw.get("factor_pnl", {})
            position_pnl = raw.get("position_pnl", {})
            estimated_total = raw["pnl"]
            warnings = []
            errors = []

        reported_total = estimated_total if total_pnl is None else float(total_pnl)
        explained = sum(components.values())
        residual = reported_total - explained
        record = self.audit.record_calculation(
            user_action="Explain portfolio PnL",
            calculation_type="pnl_explain",
            model_id="portfolio_service",
            model_version="1.0",
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            inputs={
                "portfolio": self._portfolio_inputs(),
                "total_pnl": total_pnl,
                "dS": dS,
                "dVol": dVol,
                "dr": dr,
                "dSpread": dSpread,
                "theta_days": theta_days,
                "scenario": scenario,
            },
            result_id=f"pnl_explain:{self.portfolio.portfolio_id}",
            details={"reported_total": reported_total, "explained": explained, "residual": residual},
        )
        return PnLExplainResult(
            portfolio_id=self.portfolio.portfolio_id,
            total_pnl=reported_total,
            explained_pnl=explained,
            residual=residual,
            delta_pnl=components["delta_pnl"],
            gamma_pnl=components["gamma_pnl"],
            vega_pnl=components["vega_pnl"],
            theta_pnl=components["theta_pnl"],
            rate_pnl=components["rate_pnl"],
            fx_pnl=components["fx_pnl"],
            components=components,
            factor_pnl=factor_pnl,
            position_pnl=position_pnl,
            warnings=warnings,
            errors=errors,
            calculation_record=record,
            calculation_id=record.record_id,
            inputs_hash=record.inputs_hash,
        )

    def _portfolio_inputs(self) -> dict:
        return {
            "portfolio_id": self.portfolio.portfolio_id,
            "base_currency": self.portfolio.base_currency,
            "valuation_date": self.portfolio.valuation_date,
            "market_data_snapshot_id": self.portfolio.market_data_snapshot_id,
            "positions": [
                {
                    "id": position.id,
                    "instrument": position.instrument,
                    "description": position.description,
                    "quantity": position.quantity,
                    "params": position.params,
                    "currency": position.currency,
                    "book": position.book,
                    "ccy_pair": position.ccy_pair,
                }
                for position in self.positions
            ],
        }

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

    def _scenario_pnl_from_exposures(
        self,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
        theta_days: float = 0,
    ) -> dict:
        bucket_pnl: defaultdict[str, float] = defaultdict(float)
        factor_pnl: defaultdict[str, float] = defaultdict(float)
        position_pnl: defaultdict[str, float] = defaultdict(float)
        legacy_components: defaultdict[str, float] = defaultdict(float)

        for exp in self.risk_factor_exposures():
            contribution = self._exposure_pnl(exp, dS, dVol, dr, dSpread)
            factor_id = exp.factor_id or self._factor_id(exp.bucket, exp.factor_name)
            bucket_pnl[exp.bucket] += contribution
            factor_pnl[factor_id] += contribution
            position_pnl[exp.position_id] += contribution
            legacy_components[self._legacy_component_name(exp)] += contribution

        theta_pnl = sum(p.theta for p in self.positions) * theta_days
        if theta_pnl:
            bucket_pnl["Theta"] += theta_pnl
            legacy_components["theta"] += theta_pnl

        pnl = sum(bucket_pnl.values())
        return dict(
            pnl=pnl,
            dS=dS,
            dVol=dVol,
            dr=dr,
            dSpread=dSpread,
            bucket_pnl={bucket: bucket_pnl.get(bucket, 0.0) for bucket in EXPOSURE_BUCKETS},
            factor_pnl=dict(factor_pnl),
            position_pnl=dict(position_pnl),
            components=dict(legacy_components),
        )

    def _exposure_pnl(
        self,
        exp: RiskFactorExposure,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
    ) -> float:
        if exp.unit == "Delta":
            return exp.sensitivity * dS
        if exp.unit == "Gamma":
            return exp.sensitivity * dS**2 / 2
        if exp.unit == "Vega":
            return exp.sensitivity * dVol * 100
        if exp.unit == "Rho":
            return exp.sensitivity * dr * 100
        if exp.unit == "DV01":
            return -exp.sensitivity * dr * 10000
        if exp.unit == "CS01":
            return -exp.sensitivity * dSpread * 10000
        if exp.unit == "FX Delta":
            return exp.sensitivity * dS
        return 0.0

    def _legacy_component_name(self, exp: RiskFactorExposure) -> str:
        return {
            "Delta": "delta",
            "Gamma": "gamma",
            "Vega": "vega",
            "Rho": "rho",
            "DV01": "ir_01",
            "CS01": "cs_01",
            "FX Delta": "fx",
        }.get(exp.unit, exp.unit.lower().replace(" ", "_"))

    def _pnl_components_from_legacy(self, raw: dict) -> dict[str, float]:
        raw_components = raw.get("components", {})
        return {
            "delta_pnl": raw_components.get("delta", 0.0),
            "gamma_pnl": raw_components.get("gamma", 0.0),
            "vega_pnl": raw_components.get("vega", 0.0),
            "theta_pnl": raw_components.get("theta", 0.0),
            "rate_pnl": raw_components.get("rho", 0.0) + raw_components.get("ir_01", 0.0),
            "fx_pnl": raw_components.get("fx", 0.0),
        }

    def _pnl_components_from_scenario(self, raw: dict, theta_days: float = 0) -> dict[str, float]:
        factor_pnl = raw.get("factor_pnl", {})
        theta_pnl = sum(p.theta for p in self.positions) * theta_days
        return {
            "delta_pnl": factor_pnl.get("equity.spot", 0.0),
            "gamma_pnl": factor_pnl.get("equity.spot_gamma", 0.0),
            "vega_pnl": factor_pnl.get("vol.implied", 0.0),
            "theta_pnl": theta_pnl,
            "rate_pnl": sum(value for factor, value in factor_pnl.items() if factor.startswith("rates.")),
            "fx_pnl": sum(value for factor, value in factor_pnl.items() if factor.startswith("fx.")),
        }

    def __len__(self):
        return len(self.portfolio)

    def __repr__(self):
        return repr(self.portfolio)
