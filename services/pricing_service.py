"""Pricing service entry points.

The service keeps existing pricing engines intact and wraps them with governance,
market-data metadata, warnings, and structured errors.
"""

from typing import Any

from domain.market_data import MarketDataSnapshot
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
        return {
            "value": value,
            "model_id": model_id,
            "model_status": model.status,
            "warnings": all_warnings,
            "errors": errors or [],
            "market_data_snapshot_id": snapshot.snapshot_id if snapshot else "",
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
            raw = european(S, K, T, r, sigma, q, opt, model)
            return self._result(value=raw.get("price"), model_id=model_id, raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id=model_id, error=exc, snapshot=snapshot)

    def price_bond(
        self,
        face: float,
        coupon: float,
        T: float,
        freq: int,
        curve=None,
        snapshot: MarketDataSnapshot | None = None,
        curve_id: str = "flat_rub",
    ) -> dict:
        """Price a fixed-rate bond through the existing fixed income engine."""
        from instruments.fixed_income import fixed_bond

        try:
            if curve is None:
                snapshot = snapshot or self.market_data.demo_snapshot()
                curve = self.market_data.get_curve(curve_id, snapshot)
            raw = fixed_bond(face, coupon, T, freq, curve)
            return self._result(value=raw.get("price"), model_id="fixed_bond", raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id="fixed_bond", error=exc, snapshot=snapshot)

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
            raw = fx_option(S, K, T, r_d, r_f, sigma, notional, opt, quote)
            return self._result(value=raw.get("price"), model_id="garman_kohlhagen", raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id="garman_kohlhagen", error=exc, snapshot=snapshot)
