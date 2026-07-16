"""Risk service entry points."""

from typing import Any

import numpy as np

from domain.market_data import MarketDataSnapshot
from domain.scenario import Scenario
from services.audit_service import AuditService
from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService


def _validated_reprice_pnl(result, *, context: str) -> float:
    """Fail closed on a partial/invalid full-reprice observation."""
    if not isinstance(result, dict) or not result:
        raise ValueError(f"{context}: empty or invalid reprice result")
    raw_errors = result.get("errors") or []
    if isinstance(raw_errors, str):
        raw_errors = [raw_errors]
    errors = [str(error) for error in raw_errors if error not in (None, "")]
    if errors:
        raise ValueError(f"{context}: " + "; ".join(errors))
    if result.get("valid") is False:
        raise ValueError(f"{context}: reprice result is marked invalid")
    if "pnl" not in result:
        raise ValueError(f"{context}: reprice result has no P&L")

    def finite_scalar(value, label: str) -> float:
        try:
            array = np.asarray(value)
            if array.ndim != 0:
                raise TypeError
            number = float(array)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{context}: {label} is not a scalar") from exc
        if not np.isfinite(number):
            raise ValueError(f"{context}: {label} is non-finite")
        return number

    pnl = finite_scalar(result["pnl"], "P&L")
    for key, label in (("base_value", "base value"),
                       ("shocked_value", "shocked value")):
        if key in result:
            finite_scalar(result[key], label)
    return pnl


class RiskService:
    def __init__(
        self,
        market_data: MarketDataService | None = None,
        governance: GovernanceService | None = None,
        audit: AuditService | None = None,
        allow_analytics_lab: bool = False,
        allow_non_production_models: bool = False,
    ):
        self.market_data = market_data or MarketDataService()
        self.governance = governance or GovernanceService()
        self.audit = audit or AuditService()
        self.allow_analytics_lab = allow_analytics_lab
        self.allow_non_production_models = allow_non_production_models

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
        canonical_model_id = model.model_id
        all_warnings = self.governance.warnings_for_model(canonical_model_id)
        all_warnings.extend(self._market_data_warnings(snapshot))
        all_warnings.extend(warnings or [])
        model_metadata = self.governance.metadata_for_model(model_id)
        snapshot_id = snapshot.snapshot_id if snapshot else ""
        audit_record = self.audit.record_calculation(
            user_action=user_action,
            calculation_type=calculation_type,
            model_id=canonical_model_id,
            model_version=model.version,
            market_data_snapshot_id=snapshot_id,
            inputs=inputs,
            result_id=f"{calculation_type}:{canonical_model_id}",
            details={
                "model_status": model.status,
                "errors": errors or [],
                "requested_model_id": model.requested_component_id,
                "canonical_component_id": canonical_model_id,
                "deprecated_alias": model.deprecated_alias,
            },
        )
        return {
            "value": value,
            "model_id": canonical_model_id,
            "requested_model_id": model.requested_component_id,
            "deprecated_model_alias": model.deprecated_alias,
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
            "calculation_timestamp": audit_record.timestamp.isoformat(),
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
            allow_non_production=self.allow_non_production_models,
        )

    # ── Full-reprice VaR (Phase 4) ────────────────────────

    def full_reprice_var(
        self,
        portfolio_service,
        eq_returns,
        rate_changes,
        vol_changes=None,
        fx_returns=None,
        confidence: float = 0.99,
        snapshot: MarketDataSnapshot | None = None,
        spot_return_convention: str = "simple",
        curve_changes_by_id: dict | None = None,
        surface_changes_by_position: dict | None = None,
    ) -> dict:
        """
        Historical full-reprice portfolio VaR: every joint historical scenario
        (equity return, absolute rate change, vol change, FX return) is applied
        to position parameters and the whole book is REPRICED through its
        actual pricers — no delta-gamma approximation, so option convexity and
        exotic nonlinearity enter the P&L distribution exactly.
        ``spot_return_convention`` is explicit because callers may supply
        either ordinary relative returns or log-returns. Rates and volatility
        remain absolute changes in both cases. Named curve/surface positions
        require their exact historical maps; the generic rate/vol arrays are
        retained only for legacy scalar dependencies.
        """
        model_id = "var_full_reprice"
        try:
            input_scenarios = len(eq_returns)
        except TypeError:
            input_scenarios = None

        def input_keys(values) -> list[str]:
            if not isinstance(values, dict):
                return []
            return sorted(str(key) for key in values)

        inputs = {
            "n_scenarios": input_scenarios,
            "confidence": confidence,
            "positions": len(portfolio_service.positions),
            "spot_return_convention": spot_return_convention,
            "named_curve_histories": input_keys(curve_changes_by_id),
            "named_surface_histories": input_keys(surface_changes_by_position),
        }
        try:
            self._enforce_model(model_id)
            if spot_return_convention not in {"simple", "log"}:
                raise ValueError(
                    "spot_return_convention must be 'simple' or 'log'")
            if (not isinstance(confidence, (int, float))
                    or isinstance(confidence, bool)
                    or not np.isfinite(float(confidence))
                    or not 0.0 < float(confidence) < 1.0):
                raise ValueError("confidence must be finite and between 0 and 1")
            if (curve_changes_by_id is not None
                    and not isinstance(curve_changes_by_id, dict)):
                raise ValueError("named curve histories must be a mapping")
            if (surface_changes_by_position is not None
                    and not isinstance(surface_changes_by_position, dict)):
                raise ValueError("named surface histories must be a mapping")

            def scenario_array(values, label: str) -> np.ndarray:
                try:
                    array = np.asarray(values, dtype=float)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(f"{label} history must be numeric") from exc
                if array.ndim != 1:
                    raise ValueError(f"{label} history must be one-dimensional")
                if not np.all(np.isfinite(array)):
                    raise ValueError(f"{label} history contains non-finite values")
                return array

            eq = scenario_array(eq_returns, "equity")
            ir = scenario_array(rate_changes, "rate")
            vol = (np.zeros_like(eq) if vol_changes is None
                   else scenario_array(vol_changes, "volatility"))
            fx = (np.zeros_like(eq) if fx_returns is None
                  else scenario_array(fx_returns, "FX"))
            lengths = {
                "equity": len(eq), "rate": len(ir),
                "volatility": len(vol), "FX": len(fx),
            }
            if len(set(lengths.values())) != 1:
                detail = ", ".join(
                    f"{label}={length}" for label, length in lengths.items())
                raise ValueError(
                    "joint factor histories must have exactly equal lengths: "
                    + detail)
            n = len(eq)
            if n < 30:
                raise ValueError("full_reprice_var needs at least 30 joint scenarios")
            named_curve_ids = {
                str(curve_id)
                for position in portfolio_service.positions
                for key in ("curve_id", "proj_curve_id")
                if (curve_id := (position.params or {}).get(key))
            }
            named_surface_positions = {
                position.id for position in portfolio_service.positions
                if (position.params or {}).get("vol_surface_id")
            }
            if named_curve_ids - set((curve_changes_by_id or {}).keys()):
                missing = sorted(
                    named_curve_ids - set((curve_changes_by_id or {}).keys()))
                raise ValueError(
                    "named curve histories are required: " + ", ".join(missing))
            if named_surface_positions - set((surface_changes_by_position or {}).keys()):
                missing = sorted(
                    named_surface_positions
                    - set((surface_changes_by_position or {}).keys()))
                raise ValueError(
                    "named surface histories are required for positions: "
                    + ", ".join(missing))

            curve_arrays = {}
            for curve_id, nodes in (curve_changes_by_id or {}).items():
                normalised_curve_id = str(curve_id)
                if normalised_curve_id in curve_arrays:
                    raise ValueError(
                        f"duplicate named curve identity '{normalised_curve_id}'")
                if not isinstance(nodes, dict) or not nodes:
                    raise ValueError(
                        f"named curve '{curve_id}' history has no nodes")
                curve_arrays[normalised_curve_id] = {}
                for tenor, values in nodes.items():
                    try:
                        node_tenor = float(tenor)
                    except (TypeError, ValueError, OverflowError) as exc:
                        raise ValueError(
                            f"named curve '{curve_id}' has an invalid node {tenor}") from exc
                    if not np.isfinite(node_tenor) or node_tenor <= 0:
                        raise ValueError(
                            f"named curve '{curve_id}' has an invalid node {tenor}")
                    if node_tenor in curve_arrays[normalised_curve_id]:
                        raise ValueError(
                            f"named curve '{curve_id}' has duplicate node {node_tenor}")
                    array = scenario_array(
                        values, f"named curve '{curve_id}' node {tenor}")
                    if len(array) != n:
                        raise ValueError(
                            f"named curve '{curve_id}' node {tenor} history is "
                            f"incomplete or misaligned: expected exactly {n} scenarios, "
                            f"got {len(array)}")
                    curve_arrays[normalised_curve_id][node_tenor] = array
            surface_arrays = {}
            for position_id, values in (surface_changes_by_position or {}).items():
                normalised_position_id = str(position_id)
                if normalised_position_id in surface_arrays:
                    raise ValueError(
                        f"duplicate named surface position '{normalised_position_id}'")
                array = scenario_array(
                    values, f"named surface history for '{position_id}'")
                if len(array) != n:
                    raise ValueError(
                        f"named surface history for '{position_id}' is incomplete "
                        f"or misaligned: expected exactly {n} scenarios, got {len(array)}")
                surface_arrays[normalised_position_id] = array
            pnl = np.empty(n)
            for i in range(n):
                context = f"full_reprice_var scenario {i}"
                try:
                    res = portfolio_service.full_reprice_pnl(
                        dS=eq[i], dr=ir[i], dvol=vol[i], dfx=fx[i],
                        dr_curves={
                            curve_id: [(tenor, float(values[i]))
                                       for tenor, values in nodes.items()]
                            for curve_id, nodes in curve_arrays.items()
                        } if curve_arrays else None,
                        dvol_by_position={
                            position_id: float(values[i])
                            for position_id, values in surface_arrays.items()
                        } if surface_arrays else None,
                        spot_shock_convention=spot_return_convention)
                except Exception as exc:
                    raise ValueError(f"{context}: {exc}") from exc
                pnl[i] = _validated_reprice_pnl(res, context=context)
            if not np.all(np.isfinite(pnl)):
                raise ValueError("full_reprice_var P&L series contains non-finite values")
            losses = -pnl
            var = float(np.quantile(losses, confidence))
            tail = losses[losses >= var]
            es = float(tail.mean()) if tail.size else var
            raw = dict(var=var, expected_shortfall=es, confidence=confidence,
                       n_scenarios=n, pnl_mean=float(pnl.mean()),
                       pnl_std=float(pnl.std()), worst=float(pnl.min()),
                       best=float(pnl.max()),
                       spot_return_convention=spot_return_convention,
                       reprice_errors=[])
            return self._result(
                value=var, model_id=model_id, raw=raw, snapshot=snapshot,
                warnings=[], calculation_type="full_reprice_var",
                inputs=inputs, user_action="Full-reprice portfolio VaR")
        except Exception as exc:
            return self._error_result(model_id=model_id, error=exc,
                                      snapshot=snapshot,
                                      calculation_type="full_reprice_var",
                                      inputs=inputs)

    # ── Counterparty exposure / CVA (Phase 4) ─────────────

    def cva_irs(
        self,
        notional: float,
        fixed_rate: float,
        T: float,
        freq: int,
        hazard_id: str = "hazard_1t_demo",
        curve_id: str = "ofz_demo",
        kappa: float = 0.1,
        sigma_r: float = 0.012,
        pay_fixed: bool = True,
        recovery: float | None = None,
        n_sims: int = 4000,
        n_grid: int = 24,
        snapshot: MarketDataSnapshot | None = None,
    ) -> dict:
        """
        IRS CVA from a simulated Hull-White exposure profile and a Phase-1
        hazard curve: EPE/PFE grid plus CVA = (1-R)·∫EPE·df·dPD.
        """
        from risk.exposure import cva_from_profile, irs_exposure_profile

        model_id = "cva_exposure"
        inputs = {"notional": notional, "fixed_rate": fixed_rate, "T": T,
                  "freq": freq, "hazard_id": hazard_id, "curve_id": curve_id,
                  "kappa": kappa, "sigma_r": sigma_r, "pay_fixed": pay_fixed,
                  "n_sims": n_sims, "n_grid": n_grid}
        try:
            self._enforce_model(model_id)
            snapshot = snapshot or self.market_data.demo_snapshot()
            curve = self.market_data.get_curve(curve_id, snapshot)
            hazard = self.market_data.get_hazard_curve(hazard_id, snapshot)
            profile = irs_exposure_profile(notional, fixed_rate, T, freq, curve,
                                           kappa, sigma_r, pay_fixed,
                                           n_sims, n_grid)
            xva = cva_from_profile(profile["times"], profile["epe"], hazard,
                                   curve, recovery, ene=profile["ene"],
                                   own_hazard_curve=hazard)
            raw = {**profile, **xva}
            return self._result(
                value=xva["cva"], model_id=model_id, raw=raw, snapshot=snapshot,
                calculation_type="cva_exposure", inputs=inputs,
                user_action="IRS CVA from simulated exposure")
        except Exception as exc:
            return self._error_result(model_id=model_id, error=exc,
                                      snapshot=snapshot,
                                      calculation_type="cva_exposure",
                                      inputs=inputs)

    def xva_netting_set(
        self,
        trades: list,
        cpty_hazard_id: str = "hazard_1t_demo",
        own_hazard_id: str | None = None,
        curve_id: str = "ofz_demo",
        kappa: float = 0.1,
        sigma_r: float = 0.012,
        funding_spread: float = 0.0,
        cost_of_capital: float = 0.0,
        risk_weight: float = 1.0,
        csa: dict | None = None,
        n_sims: int = 4000,
        n_grid: int = 24,
        snapshot: MarketDataSnapshot | None = None,
        curve=None,
        cpty_hazard=None,
        own_hazard=None,
    ) -> dict:
        """Full XVA on an IRS netting set (M4): CVA/DVA/FVA/MVA/KVA on a shared
        Hull-White MtM cube, with optional two-way CSA collateral. Curve and
        hazard OBJECTS override the snapshot ids — live snapshots carry no demo
        credit curves, so the bridge passes issuer-implied hazards directly."""
        from risk.xva import simulate_irs_portfolio, xva_suite

        model_id = "xva_suite"
        inputs = {"n_trades": len(trades), "cpty_hazard_id": cpty_hazard_id,
                  "own_hazard_id": own_hazard_id, "curve_id": curve_id,
                  "funding_spread": funding_spread, "cost_of_capital": cost_of_capital,
                  "csa": csa, "n_sims": n_sims, "n_grid": n_grid}
        try:
            self._enforce_model(model_id)
            snapshot = snapshot or self.market_data.demo_snapshot()
            if curve is None:
                curve = self.market_data.get_curve(curve_id, snapshot)
            cpty = cpty_hazard if cpty_hazard is not None else \
                self.market_data.get_hazard_curve(cpty_hazard_id, snapshot)
            own = own_hazard if own_hazard is not None else (
                self.market_data.get_hazard_curve(own_hazard_id, snapshot)
                if own_hazard_id else None)
            sim = simulate_irs_portfolio(list(trades), curve, kappa, sigma_r,
                                         n_sims, n_grid)
            res = xva_suite(sim, curve, cpty, own, funding_spread=funding_spread,
                            cost_of_capital=cost_of_capital, risk_weight=risk_weight,
                            csa=csa)
            return self._result(
                value=res["total_xva"], model_id=model_id, raw=res, snapshot=snapshot,
                calculation_type="xva_suite", inputs=inputs,
                user_action="XVA on IRS netting set")
        except Exception as exc:
            return self._error_result(model_id=model_id, error=exc, snapshot=snapshot,
                                      calculation_type="xva_suite", inputs=inputs)

    def frtb_capital(self, factors=None, rho=0.5, gamma=0.25, vega_factors=None,
                     curvature_factors=None, drc_factors=None, snapshot=None) -> dict:
        """FRTB Standardised Approach capital (M8 + task-3 extensions). With only
        `factors` it returns the SBM delta charge; supplying vega/curvature/drc
        factors returns the full SBM (delta+vega+curvature) + DRC total."""
        from models.frtb import frtb_delta_charge, frtb_capital as frtb_total
        model_id = "frtb_sba"
        inputs = {"n_delta": len(factors or []), "n_vega": len(vega_factors or []),
                  "n_curv": len(curvature_factors or []), "n_drc": len(drc_factors or []),
                  "rho": rho, "gamma": gamma}
        try:
            self._enforce_model(model_id)
            snapshot = snapshot or self.market_data.demo_snapshot()
            if vega_factors or curvature_factors or drc_factors:
                res = frtb_total(factors, vega_factors, curvature_factors,
                                 drc_factors, rho, gamma)
                value = res["total"]
            else:
                res = frtb_delta_charge(list(factors or []), rho, gamma)
                value = res["charge"]
            return self._result(
                value=value, model_id=model_id, raw=res, snapshot=snapshot,
                calculation_type="frtb_sba", inputs=inputs,
                user_action="FRTB-SA capital")
        except Exception as exc:
            return self._error_result(model_id=model_id, error=exc, snapshot=snapshot,
                                      calculation_type="frtb_sba", inputs=inputs)

    def frtb_ima(self, pnl_scenarios, alpha=0.975, liquidity_scale=1.0,
                 snapshot=None) -> dict:
        """FRTB-IMA expected-shortfall capital (gap batch 4)."""
        from models.frtb import frtb_ima_es
        try:
            self._enforce_model("frtb_ima")
            snapshot = snapshot or self.market_data.demo_snapshot()
            res = frtb_ima_es(list(pnl_scenarios), alpha, liquidity_scale)
            return self._result(value=res["es"], model_id="frtb_ima", raw=res,
                                snapshot=snapshot, calculation_type="frtb_ima",
                                inputs={"alpha": alpha, "n": len(pnl_scenarios)},
                                user_action="FRTB-IMA expected shortfall")
        except Exception as exc:
            return self._error_result(model_id="frtb_ima", error=exc, snapshot=snapshot,
                                      calculation_type="frtb_ima", inputs={})

    def copula_var(self, weights, vols, corr, alpha=0.99, marginal="normal",
                   df=5, n_sims=100_000, snapshot=None) -> dict:
        """Portfolio VaR under a Gaussian copula of normal/t marginals (batch 4)."""
        from risk.var import copula_var
        try:
            self._enforce_model("copula_var")
            snapshot = snapshot or self.market_data.demo_snapshot()
            res = copula_var(list(weights), list(vols), corr, alpha, marginal,
                             int(df), int(n_sims))
            return self._result(value=res["var"], model_id="copula_var", raw=res,
                                snapshot=snapshot, calculation_type="copula_var",
                                inputs={"alpha": alpha, "marginal": marginal},
                                user_action="Copula VaR")
        except Exception as exc:
            return self._error_result(model_id="copula_var", error=exc, snapshot=snapshot,
                                      calculation_type="copula_var", inputs={})

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
