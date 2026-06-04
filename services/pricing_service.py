"""Pricing service entry points.

The service keeps existing pricing engines intact and wraps them with governance,
market-data metadata, warnings, and structured errors.
"""

from typing import Any

from domain.market_data import MarketDataSnapshot
from domain.results import BondPricingRequest, BondPricingResult
from domain.scenario import ScenarioShock, ScenarioShockType
from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService


_BOND_APPROXIMATION_WARNINGS = [
    "Fixed bond pricing supports regular coupon schedules, settlement handling, ACT/365F, ACT/360, 30/360, clean price, dirty price, and accrued interest.",
    "Limitations remain: no holiday-calendar source, no irregular stub policy, no ex-coupon logic, no callable/putable features, and no inflation-linked bond mechanics.",
    "Duration, convexity, and DV01 are deterministic curve analytics and require benchmark validation before production use.",
]


class PricingService:
    def __init__(
        self,
        market_data: MarketDataService | None = None,
        governance: GovernanceService | None = None,
        allow_analytics_lab: bool = False,
    ):
        self.market_data = market_data or MarketDataService()
        self.governance = governance or GovernanceService()
        self.allow_analytics_lab = allow_analytics_lab

    def _market_data_warnings(self, snapshot: MarketDataSnapshot | None) -> list[str]:
        if snapshot is None:
            return []
        warnings = []
        if snapshot.is_demo:
            warnings.append("Market data snapshot is DEMO/MANUAL and not production quality.")
        warning = snapshot.metadata.get("warning")
        if warning:
            warnings.append(str(warning))
        return warnings

    def _market_data_source(self, snapshot: MarketDataSnapshot | None) -> str:
        if snapshot is None:
            return ""
        source = snapshot.source
        return source.value if hasattr(source, "value") else str(source)

    def _result(
        self,
        *,
        value: Any,
        model_id: str,
        raw: Any = None,
        snapshot: MarketDataSnapshot | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> dict:
        model = self.governance.get_model(model_id)
        all_warnings = self.governance.warnings_for_model(model_id)
        all_warnings.extend(self._market_data_warnings(snapshot))
        all_warnings.extend(warnings or [])
        model_metadata = self.governance.metadata_for_model(model_id)
        return {
            "value": value,
            "model_id": model_id,
            "model_status": model.status,
            "model_metadata": model_metadata,
            "model_version": model.version,
            "model_owner": model.owner,
            "model_validation_date": model_metadata["model_validation_date"],
            "model_limitations": model_metadata["model_limitations"],
            "model_documentation_link": model.documentation_link,
            "model_production_allowed": model.production_allowed,
            "model_workflow_layer": model.workflow_layer,
            "model_analytics_lab_only": model.analytics_lab_only,
            "warnings": all_warnings,
            "errors": errors or [],
            "market_data_snapshot_id": snapshot.snapshot_id if snapshot else "",
            "market_data_source": self._market_data_source(snapshot),
            "market_data_quality": snapshot.quality if snapshot else "",
            "raw": raw,
        }

    def _error_result(
        self,
        *,
        model_id: str,
        error: Exception,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        return self._result(
            value=None,
            model_id=model_id,
            raw=None,
            snapshot=snapshot,
            errors=[str(error)],
        )

    def _enforce_model(self, model_id: str):
        return self.governance.enforce_model(
            model_id,
            allow_analytics_lab=self.allow_analytics_lab,
        )

    def price_vanilla_option(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        q: float = 0.0,
        opt: str = "call",
        model: str = "bsm",
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Price a vanilla option through the existing engine."""
        from instruments.vanilla import european

        model_id = {
            "bsm": "black_scholes",
            "black76": "black76",
            "gk": "garman_kohlhagen",
            "bachelier": "bachelier",
            "binomial": "binomial_crr",
            "binomial_lr": "binomial_lr",
            "trinomial": "trinomial",
            "mc": "mc_gbm",
        }.get(model, model)
        try:
            self._enforce_model(model_id)
            raw = european(S, K, T, r, sigma, q, opt, model)
            return self._result(value=raw.get("price"), model_id=model_id, raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id=model_id, error=exc, snapshot=snapshot)

    def price_bond(
        self,
        face: float | BondPricingRequest,
        coupon: float | None = None,
        T: float | None = None,
        freq: int | None = None,
        curve=None,
        snapshot: MarketDataSnapshot | None = None,
        curve_id: str = "flat_rub",
    ) -> dict:
        """Price a fixed-rate bond through the existing fixed income engine."""
        from instruments.fixed_income import fixed_bond

        resolved_snapshot = snapshot
        try:
            self._enforce_model("fixed_bond")
            request = self._bond_request(face, coupon, T, freq, curve_id)
            warnings = list(_BOND_APPROXIMATION_WARNINGS)
            if curve is None:
                resolved_snapshot = resolved_snapshot or self.market_data.demo_snapshot()
                curve = self.market_data.get_curve(request.curve_id, resolved_snapshot)
            else:
                warnings.append(
                    "External curve supplied directly for backward compatibility; prefer MarketDataService snapshot curve ownership."
                )
            raw = fixed_bond(
                request.face,
                request.coupon,
                request.maturity,
                request.frequency,
                curve,
                settlement_date=request.settlement_date,
                maturity_date=request.maturity_date,
                issue_date=request.issue_date,
                valuation_date=request.valuation_date,
                settlement_days=request.settlement_days,
                day_count=request.day_count,
                business_day_convention=request.business_day_convention,
            )
            result = self._result(
                value=raw.get("price"),
                model_id="fixed_bond",
                raw=raw,
                snapshot=resolved_snapshot,
                warnings=warnings,
            )
            result.update(
                {
                    "request": request,
                    "dirty_price": raw.get("dirty_price"),
                    "clean_price": raw.get("clean_price"),
                    "accrued_interest": raw.get("accrued_interest", 0.0),
                    "settlement_date": raw.get("settlement_date"),
                    "previous_coupon_date": raw.get("previous_coupon_date"),
                    "next_coupon_date": raw.get("next_coupon_date"),
                    "day_count": raw.get("day_count", request.day_count),
                    "business_day_convention": raw.get(
                        "business_day_convention", request.business_day_convention
                    ),
                    "bond_result": BondPricingResult(
                        value=raw.get("price"),
                        dirty_price=raw.get("dirty_price"),
                        clean_price=raw.get("clean_price"),
                        accrued_interest=raw.get("accrued_interest", 0.0),
                        currency=request.currency,
                        model_id=result["model_id"],
                        model_status=result["model_status"],
                        settlement_date=raw.get("settlement_date"),
                        previous_coupon_date=raw.get("previous_coupon_date"),
                        next_coupon_date=raw.get("next_coupon_date"),
                        day_count=raw.get("day_count", request.day_count),
                        business_day_convention=raw.get(
                            "business_day_convention", request.business_day_convention
                        ),
                        market_data_snapshot_id=result["market_data_snapshot_id"],
                        market_data_source=result["market_data_source"],
                        market_data_quality=result["market_data_quality"],
                        warnings=result["warnings"],
                        errors=result["errors"],
                        raw=raw,
                    ),
                }
            )
            return result
        except Exception as exc:
            return self._error_result(model_id="fixed_bond", error=exc, snapshot=resolved_snapshot)

    def _bond_request(
        self,
        face: float | BondPricingRequest,
        coupon: float | None,
        T: float | None,
        freq: int | None,
        curve_id: str,
    ) -> BondPricingRequest:
        if isinstance(face, BondPricingRequest):
            return face
        missing = [
            name
            for name, value in {"coupon": coupon, "T": T, "freq": freq}.items()
            if value is None
        ]
        if missing:
            raise ValueError(f"Missing bond pricing inputs: {', '.join(missing)}")
        return BondPricingRequest(
            face=float(face),
            coupon=float(coupon),
            maturity=float(T),
            frequency=int(freq),
            curve_id=curve_id,
        )

    def price_irs(
        self,
        notional: float,
        fixed_rate: float,
        T: float,
        freq: int,
        curve=None,
        pay_fixed: bool = True,
        snapshot: MarketDataSnapshot | None = None,
        curve_id: str = "flat_rub",
    ) -> dict:
        """Price an IRS through the existing single-curve engine."""
        from instruments.fixed_income import irs

        try:
            self._enforce_model("irs")
            if curve is None:
                snapshot = snapshot or self.market_data.demo_snapshot()
                curve = self.market_data.get_curve(curve_id, snapshot)
            raw = irs(notional, fixed_rate, T, freq, curve, pay_fixed)
            return self._result(value=raw.get("npv"), model_id="irs", raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id="irs", error=exc, snapshot=snapshot)

    def price_fx_forward(
        self,
        S: float,
        r_d: float,
        r_f: float,
        T: float,
        notional: float = 1_000_000,
        forward_agreed: float | None = None,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Price an FX forward through the existing engine."""
        from instruments.fx import fx_forward

        try:
            self._enforce_model("fx_forward")
            raw = fx_forward(S, r_d, r_f, T, notional, forward_agreed)
            value = raw.get("npv") if forward_agreed is not None else raw.get("forward")
            return self._result(value=value, model_id="fx_forward", raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id="fx_forward", error=exc, snapshot=snapshot)

    def price_fx_option(
        self,
        S: float,
        K: float,
        T: float,
        r_d: float,
        r_f: float,
        sigma: float,
        notional: float = 1_000_000,
        opt: str = "call",
        quote: str = "domestic_pips",
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Price an FX option through the existing Garman-Kohlhagen engine."""
        from instruments.fx import fx_option

        try:
            self._enforce_model("garman_kohlhagen")
            raw = fx_option(S, K, T, r_d, r_f, sigma, notional, opt, quote)
            return self._result(value=raw.get("price"), model_id="garman_kohlhagen", raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id="garman_kohlhagen", error=exc, snapshot=snapshot)

    def shock_curve(self, curve, shock: ScenarioShock):
        """Apply supported scenario curve shocks to a yield curve."""
        from curves.yield_curve import YieldCurve

        shock_type = shock.type_value
        if shock_type == ScenarioShockType.PARALLEL_CURVE_SHIFT.value:
            return curve.parallel_shift(self._shock_bps(shock))

        if shock_type not in {ScenarioShockType.STEEPENER.value, ScenarioShockType.FLATTENER.value}:
            raise ValueError(f"Unsupported curve shock type: {shock_type}")

        bps = self._shock_bps(shock)
        if shock_type == ScenarioShockType.FLATTENER.value:
            bps = -bps
        tenors = curve.tenors
        pivot = 5.0
        max_distance = max(abs(float(t) - pivot) for t in tenors) or 1.0
        slope = (tenors - pivot) / max_distance
        shocked_rates = curve.zero_rates + (bps / 10000) * slope
        return YieldCurve(
            tenors,
            shocked_rates,
            label=f"{curve.label}:{shock_type}",
            interp=curve._interp,
            source=curve.source,
            valuation_date=curve.valuation_date,
            rate_type=curve.rate_type,
            compounding=curve.compounding,
            day_count=curve.day_count,
            metadata={**curve.metadata, "scenario_shock": shock_type},
        )

    def _shock_bps(self, shock: ScenarioShock) -> float:
        return shock.value if shock.unit.lower() in {"bp", "bps", "basis_points"} else shock.value * 10000
