"""Risk service entry points."""

from typing import Any

import numpy as np

from domain.market_data import MarketDataSnapshot
from domain.scenario import Scenario
from services.audit_service import AuditService
from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService


class RiskService:
    def __init__(
        self,
        market_data: MarketDataService | None = None,
        governance: GovernanceService | None = None,
        audit: AuditService | None = None,
        allow_analytics_lab: bool = False,
    ):
        self.market_data = market_data or MarketDataService()
        self.governance = governance or GovernanceService()
        self.audit = audit or AuditService()
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
        calculation_type: str = "risk",
        inputs: Any = None,
        user_action: str = "RiskService calculation",
    ) -> dict:
        model = self.governance.get_model(model_id)
        all_warnings = self.governance.warnings_for_model(model_id)
        all_warnings.extend(self._market_data_warnings(snapshot))
        all_warnings.extend(warnings or [])
        model_metadata = self.governance.metadata_for_model(model_id)
        snapshot_id = snapshot.snapshot_id if snapshot else ""
        audit_record = self.audit.record_calculation(
            user_action=user_action,
            calculation_type=calculation_type,
            model_id=model_id,
            model_version=model.version,
            market_data_snapshot_id=snapshot_id,
            inputs=inputs,
            result_id=f"{calculation_type}:{model_id}",
            details={"model_status": model.status, "errors": errors or []},
        )
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
            "market_data_snapshot_id": snapshot_id,
            "market_data_source": self._market_data_source(snapshot),
            "market_data_quality": snapshot.quality if snapshot else "",
            "calculation_id": audit_record.record_id,
            "inputs_hash": audit_record.inputs_hash,
            "audit_record": audit_record,
            "calculation_record": audit_record,
            "raw": raw,
        }

    def _error_result(
        self,
        *,
        model_id: str,
        error: Exception,
        snapshot: MarketDataSnapshot | None = None,
        calculation_type: str = "risk",
        inputs: Any = None,
    ) -> dict:
        return self._result(
            value=None,
            model_id=model_id,
            raw=None,
            snapshot=snapshot,
            errors=[str(error)],
            calculation_type=calculation_type,
            inputs=inputs,
        )

    def _enforce_model(self, model_id: str):
        return self.governance.enforce_model(
            model_id,
            allow_analytics_lab=self.allow_analytics_lab,
        )

    def var(
        self,
        returns: np.ndarray,
        position_value: float,
        confidence: float = 0.95,
        horizon: int = 1,
        method: str = "historical",
        snapshot: MarketDataSnapshot | None = None,
        **kwargs,
    ) -> dict:
        """
        Unified VaR entry point with method as a parameter.

        Historical VaR is one method among several here, not a separate
        top-level workflow. Pure dispatch over the existing per-method engines;
        no quantitative behaviour changes.
        """
        m = method.lower().replace("-", "_").replace(" ", "_")
        if m in ("historical", "hist", "historical_simulation", "hs"):
            return self.historical_var(returns, position_value, confidence, horizon,
                                       weights=kwargs.get("weights"), snapshot=snapshot)
        if m in ("parametric", "normal", "delta_normal", "t", "student_t"):
            distribution = kwargs.get("distribution", "t" if m in ("t", "student_t") else "normal")
            return self.parametric_var(returns, position_value, confidence, horizon,
                                       distribution=distribution, snapshot=snapshot)
        if m in ("monte_carlo", "mc", "montecarlo"):
            return self.monte_carlo_var(returns, position_value, confidence, horizon,
                                        n_sims=kwargs.get("n_sims", 100_000),
                                        seed=kwargs.get("seed", 42), snapshot=snapshot)
        if m in ("evt", "pot", "evt_pot"):
            return self.evt_var(returns, position_value, confidence,
                                threshold_pct=kwargs.get("threshold_pct", 0.10),
                                horizon=horizon, snapshot=snapshot)
        return self._error_result(
            model_id="var_historical",
            error=ValueError(f"Unknown VaR method: {method!r}"),
            snapshot=snapshot,
            calculation_type="var_dispatch",
            inputs={
                "returns": returns,
                "position_value": position_value,
                "confidence": confidence,
                "horizon": horizon,
                "method": method,
                "kwargs": kwargs,
            },
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
            self._enforce_model("var_historical")
            raw = historical_var(returns, position_value, confidence, horizon, weights)
            inputs = {
                "returns": returns,
                "position_value": position_value,
                "confidence": confidence,
                "horizon": horizon,
                "weights": weights,
            }
            return self._result(
                value=raw.get("VaR"),
                model_id="var_historical",
                raw=raw,
                snapshot=snapshot,
                calculation_type="historical_var",
                inputs=inputs,
                user_action="Calculate historical VaR",
            )
        except Exception as exc:
            return self._error_result(
                model_id="var_historical",
                error=exc,
                snapshot=snapshot,
                calculation_type="historical_var",
                inputs={"returns": returns, "position_value": position_value, "confidence": confidence, "horizon": horizon, "weights": weights},
            )

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
            self._enforce_model("var_parametric")
            raw = parametric_var(returns, position_value, confidence, horizon, distribution)
            return self._result(
                value=raw.get("VaR"),
                model_id="var_parametric",
                raw=raw,
                snapshot=snapshot,
                calculation_type="parametric_var",
                inputs={
                    "returns": returns,
                    "position_value": position_value,
                    "confidence": confidence,
                    "horizon": horizon,
                    "distribution": distribution,
                },
                user_action="Calculate parametric VaR",
            )
        except Exception as exc:
            return self._error_result(
                model_id="var_parametric",
                error=exc,
                snapshot=snapshot,
                calculation_type="parametric_var",
                inputs={"returns": returns, "position_value": position_value, "confidence": confidence, "horizon": horizon, "distribution": distribution},
            )

    def monte_carlo_var(
        self,
        returns: np.ndarray,
        position_value: float,
        confidence: float = 0.95,
        horizon: int = 1,
        n_sims: int = 100_000,
        seed: int = 42,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Calculate Monte Carlo VaR through the existing return-based engine."""
        from risk.var import montecarlo_var

        try:
            self._enforce_model("var_mc")
            raw = montecarlo_var(returns, position_value, confidence, horizon, n_sims, seed)
            return self._result(
                value=raw.get("VaR"),
                model_id="var_mc",
                raw=raw,
                snapshot=snapshot,
                calculation_type="monte_carlo_var",
                inputs={
                    "returns": returns,
                    "position_value": position_value,
                    "confidence": confidence,
                    "horizon": horizon,
                    "n_sims": n_sims,
                    "seed": seed,
                },
                user_action="Calculate Monte Carlo VaR",
            )
        except Exception as exc:
            return self._error_result(
                model_id="var_mc",
                error=exc,
                snapshot=snapshot,
                calculation_type="monte_carlo_var",
                inputs={"returns": returns, "position_value": position_value, "confidence": confidence, "horizon": horizon, "n_sims": n_sims, "seed": seed},
            )

    def evt_var(
        self,
        returns: np.ndarray,
        position_value: float,
        confidence: float = 0.99,
        threshold_pct: float = 0.10,
        horizon: int = 1,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Calculate EVT VaR through the existing POT/GPD engine."""
        from risk.var import evt_var

        try:
            self._enforce_model("evt_var")
            raw = evt_var(returns, position_value, confidence, threshold_pct, horizon)
            errors = [raw["error"]] if isinstance(raw, dict) and "error" in raw else []
            return self._result(
                value=raw.get("VaR") if isinstance(raw, dict) else None,
                model_id="evt_var",
                raw=raw,
                snapshot=snapshot,
                errors=errors,
                calculation_type="evt_var",
                inputs={
                    "returns": returns,
                    "position_value": position_value,
                    "confidence": confidence,
                    "threshold_pct": threshold_pct,
                    "horizon": horizon,
                },
                user_action="Calculate EVT VaR",
            )
        except Exception as exc:
            return self._error_result(
                model_id="evt_var",
                error=exc,
                snapshot=snapshot,
                calculation_type="evt_var",
                inputs={"returns": returns, "position_value": position_value, "confidence": confidence, "threshold_pct": threshold_pct, "horizon": horizon},
            )

    def historical_pnl_var(
        self,
        pnl: np.ndarray,
        confidence: float = 0.95,
        horizon: int = 1,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Calculate historical VaR from a P&L series."""
        from risk.historical_var import hs_var

        try:
            self._enforce_model("var_historical")
            raw = hs_var(pnl, confidence, horizon)
            return self._result(
                value=raw.get("VaR"),
                model_id="var_historical",
                raw=raw,
                snapshot=snapshot,
                calculation_type="historical_pnl_var",
                inputs={"pnl": pnl, "confidence": confidence, "horizon": horizon},
                user_action="Calculate historical PnL VaR",
            )
        except Exception as exc:
            return self._error_result(
                model_id="var_historical",
                error=exc,
                snapshot=snapshot,
                calculation_type="historical_pnl_var",
                inputs={"pnl": pnl, "confidence": confidence, "horizon": horizon},
            )

    def age_weighted_pnl_var(
        self,
        pnl: np.ndarray,
        confidence: float = 0.95,
        decay: float = 0.98,
        horizon: int = 1,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Calculate age-weighted historical VaR from a P&L series."""
        from risk.historical_var import hs_age_weighted

        try:
            self._enforce_model("var_historical")
            raw = hs_age_weighted(pnl, confidence, decay, horizon)
            return self._result(
                value=raw.get("VaR"),
                model_id="var_historical",
                raw=raw,
                snapshot=snapshot,
                calculation_type="age_weighted_pnl_var",
                inputs={"pnl": pnl, "confidence": confidence, "decay": decay, "horizon": horizon},
                user_action="Calculate age-weighted historical VaR",
            )
        except Exception as exc:
            return self._error_result(
                model_id="var_historical",
                error=exc,
                snapshot=snapshot,
                calculation_type="age_weighted_pnl_var",
                inputs={"pnl": pnl, "confidence": confidence, "decay": decay, "horizon": horizon},
            )

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
        record = self.audit.record_calculation(
            user_action="Calculate expected shortfall",
            calculation_type="expected_shortfall",
            model_id=result["model_id"],
            model_version=result["model_version"],
            market_data_snapshot_id=result.get("market_data_snapshot_id", ""),
            inputs={
                "returns": returns,
                "position_value": position_value,
                "confidence": confidence,
                "horizon": horizon,
                "method": method,
            },
            result_id=f"expected_shortfall:{result['model_id']}",
            details={"source_calculation_id": result.get("calculation_id", "")},
        )
        result["calculation_id"] = record.record_id
        result["inputs_hash"] = record.inputs_hash
        result["audit_record"] = record
        result["calculation_record"] = record
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
            self._enforce_model("var_parametric")
            raw = stress_option(S, K, T, r, sigma, q, opt, scenarios, position)
            worst = min((row["pnl"] for row in raw), default=0.0)
            return self._result(
                value=worst,
                model_id="var_parametric",
                raw=raw,
                snapshot=snapshot,
                calculation_type="stress_option",
                inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt, "scenarios": scenarios, "position": position},
                user_action="Run option stress",
            )
        except Exception as exc:
            return self._error_result(
                model_id="var_parametric",
                error=exc,
                snapshot=snapshot,
                calculation_type="stress_option",
                inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt, "scenarios": scenarios, "position": position},
            )

    def reverse_stress_option(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        q: float = 0.0,
        opt: str = "call",
        target_loss: float | None = None,
        target_loss_pct: float | None = None,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Run option reverse stress through the existing stress engine."""
        from risk.stress import reverse_stress

        try:
            self._enforce_model("var_parametric")
            raw = reverse_stress(S, K, T, r, sigma, q, opt, target_loss, target_loss_pct)
            return self._result(
                value=raw.get("actual_loss"),
                model_id="var_parametric",
                raw=raw,
                snapshot=snapshot,
                calculation_type="reverse_stress_option",
                inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt, "target_loss": target_loss, "target_loss_pct": target_loss_pct},
                user_action="Run reverse stress",
            )
        except Exception as exc:
            return self._error_result(
                model_id="var_parametric",
                error=exc,
                snapshot=snapshot,
                calculation_type="reverse_stress_option",
                inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt, "target_loss": target_loss, "target_loss_pct": target_loss_pct},
            )

    def run_portfolio_scenario(
        self,
        portfolio_service,
        scenario: Scenario | dict,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """Run a unified portfolio scenario through the portfolio service."""
        try:
            self._enforce_model("var_parametric")
            scenario_result = portfolio_service.run_scenario(scenario)
            result = self._result(
                value=scenario_result.pnl,
                model_id="var_parametric",
                raw=scenario_result.as_dict(),
                snapshot=snapshot,
                warnings=scenario_result.warnings,
                errors=scenario_result.errors,
                calculation_type="portfolio_scenario",
                inputs={"portfolio_id": portfolio_service.portfolio.portfolio_id, "scenario": scenario},
                user_action="Run portfolio scenario",
            )
            result["scenario_result"] = scenario_result
            return result
        except Exception as exc:
            return self._error_result(
                model_id="var_parametric",
                error=exc,
                snapshot=snapshot,
                calculation_type="portfolio_scenario",
                inputs={"scenario": scenario},
            )
