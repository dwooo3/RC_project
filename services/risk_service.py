"""Risk service entry points."""

from typing import Any

import numpy as np

from domain.market_data import MarketDataSnapshot
from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService


class RiskService:
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

    def historical_var(
        self,
        returns: np.ndarray,
        position_value: float,
        confidence: float = 0.95,
        horizon: int = 1,
        weights: np.ndarray | None = None,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Calculate historical VaR through the existing return-based engine."""
        from risk.var import historical_var

        try:
            raw = historical_var(returns, position_value, confidence, horizon, weights)
            return self._result(value=raw.get("VaR"), model_id="var_historical", raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id="var_historical", error=exc, snapshot=snapshot)

    def parametric_var(
        self,
        returns: np.ndarray,
        position_value: float,
        confidence: float = 0.95,
        horizon: int = 1,
        distribution: str = "normal",
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Calculate parametric VaR through the existing engine."""
        from risk.var import parametric_var

        try:
            raw = parametric_var(returns, position_value, confidence, horizon, distribution)
            return self._result(value=raw.get("VaR"), model_id="var_parametric", raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id="var_parametric", error=exc, snapshot=snapshot)

    def expected_shortfall(
        self,
        returns: np.ndarray,
        position_value: float,
        confidence: float = 0.95,
        horizon: int = 1,
        method: str = "historical",
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Return ES/CVaR using an existing VaR engine."""
        if method == "parametric":
            result = self.parametric_var(returns, position_value, confidence, horizon, snapshot=snapshot)
        else:
            result = self.historical_var(returns, position_value, confidence, horizon, snapshot=snapshot)
        raw = result.get("raw") or {}
        result["value"] = raw.get("CVaR", raw.get("ES"))
        return result

    def stress_option(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        q: float = 0.0,
        opt: str = "call",
        scenarios: dict | None = None,
        position: float = 1.0,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Run option stress scenarios through the existing stress engine."""
        from risk.stress import stress_option

        try:
            raw = stress_option(S, K, T, r, sigma, q, opt, scenarios, position)
            worst = min((row["pnl"] for row in raw), default=0.0)
            return self._result(value=worst, model_id="var_parametric", raw=raw, snapshot=snapshot)
        except Exception as exc:
            return self._error_result(model_id="var_parametric", error=exc, snapshot=snapshot)
