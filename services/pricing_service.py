"""Pricing service entry points.

The service keeps existing pricing engines intact and wraps them with governance,
market-data metadata, warnings, and structured errors.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from typing import Any, Iterator

from domain.market_data import MarketDataSnapshot
from domain.results import BondPricingRequest, BondPricingResult
from domain.scenario import ScenarioShock, ScenarioShockType
from services.audit_service import AuditService
from services.governance_service import GovernanceService
from services.market_data_service import MarketDataService


_BOND_APPROXIMATION_WARNINGS = [
    "Fixed bond pricing supports regular coupon schedules, settlement handling, ACT/365F, ACT/360, 30/360, clean price, dirty price, and accrued interest.",
    "Limitations remain: no holiday-calendar source, no irregular stub policy, no ex-coupon logic, no callable/putable features, and no inflation-linked bond mechanics.",
    "Duration, convexity, and DV01 are deterministic curve analytics and require benchmark validation before production use.",
]


# Request-local workstation composition.  ContextVar keeps concurrent FastAPI
# requests isolated while allowing the existing 50 product adapters to reuse
# the same PricingService entry points without threading engine metadata through
# every signature.
_ENGINE_EXECUTION_CONTEXT: ContextVar[dict | None] = ContextVar(
    "pricing_engine_execution_context", default=None
)


class PricingService:
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

    @contextmanager
    def engine_context(self, metadata: dict) -> Iterator[None]:
        """Attach exact engine/model/solver provenance to one calculation."""
        # Engine wrappers may add a more specific eligibility variant inside
        # the workstation's outer exact-request context (Carr-Madan is one
        # example).  Replacing the ContextVar here silently discarded the
        # outer resolved request and made environment/snapshot changes hash to
        # the same run.  Merge scopes instead; the innermost metadata wins for
        # overlapping provenance keys while private outer identity survives.
        merged = dict(_ENGINE_EXECUTION_CONTEXT.get() or {})
        merged.update(metadata)
        token = _ENGINE_EXECUTION_CONTEXT.set(merged)
        try:
            yield
        finally:
            _ENGINE_EXECUTION_CONTEXT.reset(token)

    @staticmethod
    def _eligibility_metadata(eligibility) -> dict:
        from models.engine_eligibility import effective_production_allowed

        return {
            "engine_eligibility_id": eligibility.engine_id,
            "engine_eligibility_version": eligibility.version,
            "model_definition_id": eligibility.model_ref.definition_id,
            "model_definition_version": eligibility.model_ref.version,
            "solver_definition_id": eligibility.solver_ref.definition_id,
            "solver_definition_version": eligibility.solver_ref.version,
            "pricer_component_id": eligibility.pricer_component_id,
            "parameterization_component_id": eligibility.parameterization_component_id,
            "implementation_component_id": eligibility.implementation_component_id,
            "requested_engine_selector": eligibility.selector_id,
            "engine_runtime_variant": eligibility.runtime_variant,
            "engine_production_allowed": eligibility.production_allowed,
            "engine_effective_production_allowed": effective_production_allowed(
                eligibility
            ),
            "engine_approval_basis": eligibility.approval_basis,
            "engine_approval_ref": eligibility.approval_ref,
            "engine_approval_expires_on": (
                eligibility.approval_expires_on.isoformat()
                if eligibility.approval_expires_on else ""
            ),
        }

    def _market_data_warnings(self, snapshot: MarketDataSnapshot | None) -> list[str]:
        if snapshot is None:
            return []
        warnings = []
        if bool(getattr(snapshot, "is_demo", False)):
            warnings.append("Market data snapshot is DEMO/MANUAL and not production quality.")
        metadata = getattr(snapshot, "metadata", {}) or {}
        warning = metadata.get("warning") if isinstance(metadata, dict) else None
        if warning:
            warnings.append(str(warning))
        return warnings

    def _market_data_source(self, snapshot: MarketDataSnapshot | None) -> str:
        if snapshot is None:
            return ""
        source = getattr(snapshot, "source", "")
        return source.value if hasattr(source, "value") else str(source)

    @staticmethod
    def _canonical_basket_inputs(
        constituents, correlation, *, resolved_snapshot_id: str = "",
        reference_spots=None, reference_fixing_dates=None,
    ) -> dict:
        """JSON-safe market state used by replay, Greeks and transient risk."""
        supplied_references = reference_spots is not None
        references = (
            list(reference_spots) if supplied_references
            else [float(item.spot) for item in constituents]
        )
        return {
            "resolved_snapshot_id": str(resolved_snapshot_id),
            "component_secids": [str(item.name) for item in constituents],
            "component_kinds": [str(item.kind) for item in constituents],
            "assets": [float(item.spot) for item in constituents],
            # Initial reference levels are contractual state for relative
            # barriers.  Scenario spots may move; these levels must not.
            "reference_spots": [float(value) for value in references],
            "reference_spot_source": (
                "contract_fixing" if supplied_references
                else "current_snapshot_spot_inception_assumption"
            ),
            "reference_fixing_dates": [
                str(value) for value in (reference_fixing_dates or [])
            ],
            "sigmas": [float(item.vol) for item in constituents],
            "incomes": [float(item.income) for item in constituents],
            "weights": [float(item.weight) for item in constituents],
            "correlation": [
                [float(value) for value in row]
                for row in correlation
            ],
        }

    @staticmethod
    def _basket_fallback_warnings(evidence: dict) -> list[str]:
        """Compact, user-visible warning while retaining full resolver evidence."""
        flags = list(evidence.get("fallback_flags") or [])
        if not flags:
            return []
        visible = "; ".join(str(flag) for flag in flags[:5])
        suffix = f"; +{len(flags) - 5} more" if len(flags) > 5 else ""
        return [
            f"Basket market-data fallback(s) used ({len(flags)}): "
            f"{visible}{suffix}. Inspect market_data_evidence before relying "
            "on the result."
        ]

    def _result(
        self,
        *,
        value: Any,
        model_id: str,
        raw: Any = None,
        snapshot: MarketDataSnapshot | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        calculation_type: str = "pricing",
        inputs: Any = None,
        user_action: str = "PricingService calculation",
    ) -> dict:
        model = self.governance.get_model(model_id)
        canonical_model_id = model.model_id
        all_warnings = self.governance.warnings_for_model(canonical_model_id)
        all_warnings.extend(self._market_data_warnings(snapshot))
        all_warnings.extend(warnings or [])
        model_metadata = self.governance.metadata_for_model(model_id)
        snapshot_id = snapshot.snapshot_id if snapshot else ""
        engine_context = dict(_ENGINE_EXECUTION_CONTEXT.get() or {})
        # Workstation composition supplies the complete resolved request.  It
        # is private execution context (not response metadata) and replaces
        # wrapper-specific partial inputs for audit/hash purposes.
        resolved_request = engine_context.pop("_resolved_pricing_request", None)
        audit_inputs = resolved_request if resolved_request is not None else inputs
        # Products whose tradable inputs are resolved from the market store
        # (basket spots, realised vols, carry and correlation) must bind that
        # resolution into the authoritative calculation hash.  The workstation
        # request alone only contains SECIDs and would otherwise replay against
        # whatever happens to be latest in the database.  Wrappers add the
        # deterministic resolver evidence to their mutable ``inputs`` mapping
        # after the engine has resolved it; merge the reserved field into the
        # complete workstation request instead of replacing that request.
        if (resolved_request is not None and isinstance(inputs, dict)
                and inputs.get("market_data_resolution") is not None):
            audit_inputs = {
                **resolved_request,
                "market_data_resolution": inputs["market_data_resolution"],
            }
        audit_record = self.audit.record_calculation(
            user_action=user_action,
            calculation_type=calculation_type,
            model_id=canonical_model_id,
            model_version=model.version,
            market_data_snapshot_id=snapshot_id,
            inputs=audit_inputs,
            result_id=f"{calculation_type}:{canonical_model_id}",
            details={
                "model_status": model.status,
                "errors": errors or [],
                "requested_model_id": model.requested_component_id,
                "canonical_component_id": canonical_model_id,
                "deprecated_alias": model.deprecated_alias,
                **engine_context,
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
            **engine_context,
            "warnings": all_warnings,
            "errors": errors or [],
            "market_data_snapshot_id": snapshot_id,
            "market_data_source": self._market_data_source(snapshot),
            "market_data_quality": getattr(snapshot, "quality", "") if snapshot else "",
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
        calculation_type: str = "pricing",
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

    def workflow_status(
        self,
        model_id: str,
        *,
        snapshot: MarketDataSnapshot | None = None,
        reason: str = "Pricing workflow is not yet service-routed.",
    ) -> dict:
        """Return governed workflow readiness without calling a pricing engine."""
        try:
            self._enforce_model(model_id)
            return self._result(
                value=None,
                model_id=model_id,
                raw={"workflow_available": False, "reason": reason},
                snapshot=snapshot,
                warnings=[reason],
                calculation_type="pricing_workflow_status",
                inputs={"model_id": model_id, "reason": reason},
                user_action="Pricing workflow status",
            )
        except Exception as exc:
            return self._error_result(
                model_id=model_id,
                error=exc,
                snapshot=snapshot,
                calculation_type="pricing_workflow_status",
                inputs={"model_id": model_id, "reason": reason},
            )

    def _enforce_model(self, model_id: str):
        return self.governance.enforce_model(
            model_id,
            allow_analytics_lab=self.allow_analytics_lab,
            allow_non_production=self.allow_non_production_models,
        )

    def price_vanilla_option(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float | None = None,
        q: float = 0.0,
        opt: str = "call",
        model: str = "bsm",
        snapshot: MarketDataSnapshot | None = None,
        vol_surface_id: str | None = None,
        n: int | None = None,
        n_sims: int | None = None,
        steps: int | None = None,
        seed: int | None = None,
        ns: int | None = None,
        nt: int | None = None,
    ) -> dict:
        """
        Price a vanilla option. sigma may be omitted when vol_surface_id names a
        surface in the market snapshot — the strike/tenor vol is then resolved
        from the surface (Phase 1: surface-aware pricing).
        n / n_sims / steps / seed: numerical overrides for lattice/MC engines.
        """
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
            "pde": "pde_cn",
        }.get(model, model)
        try:
            self._enforce_model(model_id)
            vol_warnings = []
            if sigma is None:
                if vol_surface_id is None:
                    raise ValueError("Provide sigma or vol_surface_id")
                snapshot = snapshot or self.market_data.demo_snapshot()
                surface = self.market_data.get_vol_surface(vol_surface_id, snapshot)
                sigma, vol_warning = self._vol_from_surface(surface, K, T, S=S)
                if vol_warning:
                    vol_warnings.append(vol_warning)
                note = f"σ={sigma:.2%} from surface '{vol_surface_id}'"
                rmse = getattr(surface, "rmse_at", lambda _t: None)(T)
                if rmse is not None:
                    note += f" · SABR fit RMSE {rmse:.2%}"
                vol_warnings.append(note)
            raw = european(S, K, T, r, sigma, q, opt, model,
                           n=n, n_sims=n_sims, steps=steps, seed=seed,
                           ns=ns, nt=nt)
            if vol_surface_id is not None and isinstance(raw, dict):
                raw["vol_surface_id"] = vol_surface_id
                raw["sigma_used"] = sigma
            inputs = {"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt,
                      "model": model, "vol_surface_id": vol_surface_id}
            for key, val in (("n", n), ("n_sims", n_sims),
                             ("steps", steps), ("seed", seed),
                             ("ns", ns), ("nt", nt)):
                if val is not None:      # numericals are part of the evidence
                    inputs[key] = val
            return self._result(
                value=raw.get("price"),
                model_id=model_id,
                raw=raw,
                snapshot=snapshot,
                warnings=vol_warnings,
                calculation_type="vanilla_option_pricing",
                inputs=inputs,
                user_action="Price vanilla option",
            )
        except Exception as exc:
            return self._error_result(
                model_id=model_id,
                error=exc,
                snapshot=snapshot,
                calculation_type="vanilla_option_pricing",
                inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt, "model": model},
            )

    def _priced(self, *, model_id, calculation_type, engine, inputs, snapshot,
                user_action, value_key="price", warnings=None):
        """Uniform governed wrapper: enforce -> call engine -> structured result."""
        try:
            self._enforce_model(model_id)
            raw = engine()
            value = raw.get(value_key) if isinstance(raw, dict) else raw
            return self._result(value=value, model_id=model_id, raw=raw, snapshot=snapshot,
                                calculation_type=calculation_type, inputs=inputs,
                                user_action=user_action, warnings=warnings)
        except Exception as exc:
            return self._error_result(model_id=model_id, error=exc, snapshot=snapshot,
                                      calculation_type=calculation_type, inputs=inputs)

    # ── Этап 5: линейный equity / asset swap / CDS index / FXO ────────
    def price_equity_forward(self, S, K, T, r, q=0.0, notional=1.0,
                             position="long", snapshot=None) -> dict:
        """Equity forward/future (exact cost-of-carry)."""
        from instruments.equity_linear import equity_forward
        return self._priced(
            model_id="equity_forward", calculation_type="equity_forward_pricing",
            engine=lambda: equity_forward(S, K, T, r, q, notional, position),
            inputs={"S": S, "K": K, "T": T, "r": r, "q": q, "notional": notional,
                    "position": position},
            snapshot=snapshot, user_action="Price equity forward", value_key="npv")

    def price_equity_swap(self, S, notional, T, r, q=0.0, spread=0.0, freq=4,
                          receive_equity=True, snapshot=None) -> dict:
        """Equity total-return swap (continuous-reset closed form)."""
        from instruments.equity_linear import equity_swap
        return self._priced(
            model_id="equity_swap", calculation_type="equity_swap_pricing",
            engine=lambda: equity_swap(S, notional, T, r, q, spread, freq,
                                       receive_equity),
            inputs={"S": S, "notional": notional, "T": T, "r": r, "q": q,
                    "spread": spread, "freq": freq, "receive_equity": receive_equity},
            snapshot=snapshot, user_action="Price equity swap", value_key="npv")

    def price_dividend_swap(self, S, T, r, q, div_strike=None, notional=1.0,
                            position="long", snapshot=None) -> dict:
        """Dividend swap (expected dividend strip vs fixed strike)."""
        from instruments.equity_linear import dividend_swap
        return self._priced(
            model_id="dividend_swap", calculation_type="dividend_swap_pricing",
            engine=lambda: dividend_swap(S, T, r, q, div_strike, notional, position),
            inputs={"S": S, "T": T, "r": r, "q": q, "div_strike": div_strike,
                    "notional": notional, "position": position},
            snapshot=snapshot, user_action="Price dividend swap", value_key="npv")

    def price_asset_swap(self, face, coupon, T, freq, market_price, r,
                         snapshot=None) -> dict:
        """Par-par asset swap spread (bond vs risk-free curve)."""
        from instruments.credit import asset_swap_parpar
        return self._priced(
            model_id="asset_swap", calculation_type="asset_swap_pricing",
            engine=lambda: asset_swap_parpar(face, coupon, T, freq, market_price, r),
            inputs={"face": face, "coupon": coupon, "T": T, "freq": freq,
                    "market_price": market_price, "r": r},
            snapshot=snapshot, user_action="Price asset swap",
            value_key="asset_swap_spread_bp")

    def price_cds_index(self, notional, index_spread, coupon, T, freq, r,
                        recovery=0.4, n_names=125, buy_protection=True,
                        snapshot=None) -> dict:
        """CDS index on a homogeneous pool (ISDA-style flat hazard, upfront)."""
        from instruments.credit import cds_index
        return self._priced(
            model_id="cds_index", calculation_type="cds_index_pricing",
            engine=lambda: cds_index(notional, index_spread, coupon, T, freq, r,
                                     recovery, n_names, buy_protection),
            inputs={"notional": notional, "index_spread": index_spread,
                    "coupon": coupon, "T": T, "freq": freq, "r": r,
                    "recovery": recovery, "n_names": n_names,
                    "buy_protection": buy_protection},
            snapshot=snapshot, user_action="Price CDS index", value_key="upfront")

    def price_fx_barrier(self, S, K, H, T, r_d, r_f, sigma, opt="call",
                         barrier_type="down-out", rebate=0.0,
                         notional=1_000_000, snapshot=None) -> dict:
        """FX barrier option (Garman-Kohlhagen carry, continuous monitoring)."""
        from instruments.fx import fx_barrier
        return self._priced(
            model_id="barrier", calculation_type="fx_barrier_pricing",
            engine=lambda: fx_barrier(S, K, H, T, r_d, r_f, sigma, opt,
                                      barrier_type, rebate, notional),
            inputs={"S": S, "K": K, "H": H, "T": T, "r_d": r_d, "r_f": r_f,
                    "sigma": sigma, "opt": opt, "barrier_type": barrier_type,
                    "rebate": rebate, "notional": notional},
            snapshot=snapshot, user_action="Price FX barrier")

    def price_fx_digital(self, S, K, T, r_d, r_f, sigma, opt="call",
                         style="cash", cash=1.0, notional=1_000_000,
                         snapshot=None) -> dict:
        """FX digital (cash/asset-or-nothing, GK carry)."""
        from instruments.fx import fx_digital
        return self._priced(
            model_id="digital", calculation_type="fx_digital_pricing",
            engine=lambda: fx_digital(S, K, T, r_d, r_f, sigma, opt, style,
                                      cash, notional),
            inputs={"S": S, "K": K, "T": T, "r_d": r_d, "r_f": r_f,
                    "sigma": sigma, "opt": opt, "style": style, "cash": cash,
                    "notional": notional},
            snapshot=snapshot, user_action="Price FX digital")

    def price_fx_asian(self, S, K, T, r_d, r_f, sigma, opt="call",
                       averaging="arithmetic", n=12, n_sims=50_000,
                       notional=1_000_000, snapshot=None) -> dict:
        """FX Asian (arithmetic MC / geometric closed form, GK carry)."""
        from instruments.fx import fx_asian
        return self._priced(
            model_id="asian", calculation_type="fx_asian_pricing",
            engine=lambda: fx_asian(S, K, T, r_d, r_f, sigma, opt, averaging,
                                    n, n_sims, notional),
            inputs={"S": S, "K": K, "T": T, "r_d": r_d, "r_f": r_f,
                    "sigma": sigma, "opt": opt, "averaging": averaging, "n": n,
                    "notional": notional},
            snapshot=snapshot, user_action="Price FX asian")

    def price_fx_lookback(self, S, T, r_d, r_f, sigma, opt="call",
                          strike_type="floating", K=None, notional=1_000_000,
                          snapshot=None) -> dict:
        """FX lookback (floating/fixed strike, GK carry)."""
        from instruments.fx import fx_lookback
        return self._priced(
            model_id="lookback", calculation_type="fx_lookback_pricing",
            engine=lambda: fx_lookback(S, T, r_d, r_f, sigma, opt, strike_type,
                                       K, notional),
            inputs={"S": S, "T": T, "r_d": r_d, "r_f": r_f, "sigma": sigma,
                    "opt": opt, "strike_type": strike_type, "K": K,
                    "notional": notional},
            snapshot=snapshot, user_action="Price FX lookback")

    def price_equity_future(self, S, K, T, r, q=0.0, notional=1.0,
                            position="long", snapshot=None) -> dict:
        """Equity future (futures convention: undiscounted MtM)."""
        from instruments.equity_linear import equity_future
        return self._priced(
            model_id="equity_future", calculation_type="equity_future_pricing",
            engine=lambda: equity_future(S, K, T, r, q, notional, position),
            inputs={"S": S, "K": K, "T": T, "r": r, "q": q, "notional": notional,
                    "position": position},
            snapshot=snapshot, user_action="Price equity future", value_key="npv")

    def price_warrant(self, S, K, T, r, sigma, q=0.0, n_shares=100.0,
                      n_warrants=10.0, opt="call", notional=1.0,
                      snapshot=None) -> dict:
        """Warrant (dilution-adjusted BSM)."""
        from instruments.equity_linear import warrant
        return self._priced(
            model_id="warrant", calculation_type="warrant_pricing",
            engine=lambda: warrant(S, K, T, r, sigma, q, n_shares, n_warrants,
                                   opt, notional),
            inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q,
                    "n_shares": n_shares, "n_warrants": n_warrants, "opt": opt,
                    "notional": notional},
            snapshot=snapshot, user_action="Price warrant")

    def price_cds_index_option(self, notional, strike_spread, current_spread,
                               sigma, T_opt, T_index, freq, r, recovery=0.4,
                               option="payer", snapshot=None) -> dict:
        """CDS index option (Black on index spread, RPV01 numeraire)."""
        from instruments.credit import cds_index_option
        return self._priced(
            model_id="cds_index_option", calculation_type="cds_index_option_pricing",
            engine=lambda: cds_index_option(notional, strike_spread, current_spread,
                                            sigma, T_opt, T_index, freq, r,
                                            recovery, option),
            inputs={"notional": notional, "strike_spread": strike_spread,
                    "current_spread": current_spread, "sigma": sigma,
                    "T_opt": T_opt, "T_index": T_index, "freq": freq, "r": r,
                    "recovery": recovery, "option": option},
            snapshot=snapshot, user_action="Price CDS index option", value_key="price")

    def price_term_deposit(self, notional, deposit_rate, T, r, basis="simple",
                           deposit=True, snapshot=None) -> dict:
        """Money-market term deposit / loan (simple/continuous accrual)."""
        from instruments.money_market import term_deposit
        return self._priced(
            model_id="term_deposit", calculation_type="term_deposit_pricing",
            engine=lambda: term_deposit(notional, deposit_rate, T, r, basis,
                                        deposit),
            inputs={"notional": notional, "deposit_rate": deposit_rate, "T": T,
                    "r": r, "basis": basis, "deposit": deposit},
            snapshot=snapshot, user_action="Price term deposit", value_key="npv")

    # ── Equity exotics ────────────────────────────────────────────────
    def price_barrier_option(self, S, K, H, T, r, sigma, q=0.0, opt="call",
                             barrier_type="down-out", rebate=0.0, snapshot=None) -> dict:
        """Single-barrier European option (closed form)."""
        from instruments.barrier import single_barrier
        return self._priced(
            model_id="barrier", calculation_type="barrier_option_pricing",
            engine=lambda: single_barrier(S, K, H, T, r, sigma, q, opt, barrier_type, rebate),
            inputs={"S": S, "K": K, "H": H, "T": T, "r": r, "sigma": sigma, "q": q,
                    "opt": opt, "barrier_type": barrier_type, "rebate": rebate},
            snapshot=snapshot, user_action="Price barrier option")

    def price_asian_option(self, S, K, T, r, sigma, q=0.0, opt="call",
                           averaging="arithmetic", n=12, n_sims=50_000, snapshot=None) -> dict:
        """Asian option (arithmetic via MC+control variate, or geometric closed form)."""
        from instruments.asian import arithmetic_asian, geometric_asian_discrete
        if averaging == "geometric":
            engine = lambda: geometric_asian_discrete(S, K, T, r, sigma, q, n, opt)
        else:
            engine = lambda: arithmetic_asian(S, K, T, r, sigma, q, n, opt, n_sims)
        return self._priced(
            model_id="asian", calculation_type="asian_option_pricing", engine=engine,
            inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt,
                    "averaging": averaging, "n": n},
            snapshot=snapshot, user_action="Price asian option")

    def price_digital_option(self, S, K, T, r, sigma, q=0.0, opt="call",
                             style="cash", cash=1.0, snapshot=None) -> dict:
        """Digital option: cash-or-nothing or asset-or-nothing."""
        from instruments.digital import asset_or_nothing, cash_or_nothing
        if style == "asset":
            engine = lambda: asset_or_nothing(S, K, T, r, sigma, q, opt)
        else:
            engine = lambda: cash_or_nothing(S, K, T, r, sigma, q, opt, cash)
        return self._priced(
            model_id="digital", calculation_type="digital_option_pricing", engine=engine,
            inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt,
                    "style": style, "cash": cash},
            snapshot=snapshot, user_action="Price digital option")

    def price_lookback_option(self, S, T, r, sigma, q=0.0, opt="call",
                              strike_type="floating", K=None, snapshot=None) -> dict:
        """Lookback option: floating- or fixed-strike (closed form)."""
        from instruments.lookback import fixed_lookback, floating_lookback
        if strike_type == "fixed":
            engine = lambda: fixed_lookback(S, K, T, r, sigma, q, opt)
        else:
            engine = lambda: floating_lookback(S, T, r, sigma, q, opt)
        return self._priced(
            model_id="lookback", calculation_type="lookback_option_pricing", engine=engine,
            inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt,
                    "strike_type": strike_type},
            snapshot=snapshot, user_action="Price lookback option")

    def _resolve_curve(self, curve, snapshot, curve_id):
        """Resolve a pricing curve from an explicit curve or a market snapshot."""
        if curve is not None:
            return curve, snapshot
        snapshot = snapshot or self.market_data.demo_snapshot()
        return self.market_data.get_curve(curve_id, snapshot), snapshot

    def _resolve_proj_curve(self, proj_curve, proj_curve_id, snapshot):
        """Resolve an optional projection curve (dual-curve pricing)."""
        if proj_curve is not None or proj_curve_id is None:
            return proj_curve, snapshot
        snapshot = snapshot or self.market_data.demo_snapshot()
        return self.market_data.get_curve(proj_curve_id, snapshot), snapshot

    @staticmethod
    def _vol_from_surface(surface, K: float, T: float, S: float | None = None):
        """Resolve a vol from a snapshot surface object.

        Interpolated surfaces (``VolSurface`` / ``CalibratedSurface``) return a
        strike- and tenor-aware vol — a real smile + term structure. ``rr_bf``
        quote sets are expanded into a smile surface. A bare ``median_vol`` grid
        is only used as a last resort (and flagged with a warning).
        """
        if hasattr(surface, "get_vol"):                       # VolSurface | CalibratedSurface
            return float(surface.get_vol(K, T)), None
        if isinstance(surface, dict):
            if surface.get("type") == "flat":
                return float(surface["vol"]), None
            if surface.get("type") == "rr_bf":
                vs = PricingService._surface_from_rr_bf(surface, S or K)
                return float(vs.get_vol(K, T)), None
            if surface.get("median_vol") is not None:
                return (float(surface["median_vol"]),
                        "Vol surface too thin to calibrate a smile; using median vol.")
        raise ValueError(f"Unsupported vol surface object: {type(surface).__name__}")

    def resolve_vol_surface(
        self,
        surface_id: str,
        K: float,
        T: float,
        *,
        S: float | None = None,
        snapshot: MarketDataSnapshot | None = None,
    ) -> tuple[float, str | None]:
        """Resolve one governed strike/expiry node without a DEMO fallback.

        Portfolio valuation uses this strict entry point because a captured
        surface ID is an executable market-data dependency, not an optional
        display label.  Scenario code may then apply a parallel vol move to the
        resolved current node; historical surface-node dynamics remain a
        separate methodology/data requirement.
        """
        if snapshot is None:
            raise ValueError(
                f"vol surface '{surface_id}' requires a bound market-data snapshot")
        surface = self.market_data.get_vol_surface(surface_id, snapshot)
        self._require_surface_support(surface_id, surface, K=float(K), T=float(T))
        sigma, warning = self._vol_from_surface(surface, K, T, S=S)
        sigma = float(sigma)
        if not 0.0 < sigma < 5.0:
            raise ValueError(
                f"vol surface '{surface_id}' resolved invalid sigma {sigma}")
        return sigma, warning

    @staticmethod
    def _require_surface_support(surface_id: str, surface, *, K: float, T: float) -> None:
        """Reject implicit strike/tenor clipping or extrapolation.

        Captured surface IDs are governed market-data dependencies.  The
        underlying interpolators intentionally support display-friendly flat
        extrapolation, but portfolio valuation must stay inside the calibrated
        native strike/expiry support unless the object is explicitly declared
        flat.
        """
        if K <= 0 or T <= 0:
            raise ValueError(
                f"vol surface '{surface_id}' requires positive K and T")
        if isinstance(surface, dict):
            surface_type = surface.get("type")
            if surface_type in {"flat", "rr_bf"}:
                return
            # A listed-option grid reaches this branch only when calibration
            # could not build even one usable smile slice.  Median fallback is
            # suitable for display, not for governed K/T valuation.
            raise ValueError(
                f"vol surface '{surface_id}' has no calibrated strike/tenor support")

        slices = getattr(surface, "slices", None)
        if slices is not None:
            if not slices:
                raise ValueError(f"vol surface '{surface_id}' has no calibrated slices")
            ordered = sorted(slices, key=lambda item: float(item["T"]))
            lo_t, hi_t = float(ordered[0]["T"]), float(ordered[-1]["T"])
            if T < lo_t - 1e-12 or T > hi_t + 1e-12:
                raise ValueError(
                    f"vol surface '{surface_id}' tenor support is "
                    f"[{lo_t:.6g}, {hi_t:.6g}]Y; requested {T:.6g}Y")
            relevant = [item for item in ordered
                        if abs(float(item["T"]) - T) <= 1e-12]
            if not relevant:
                lower = [item for item in ordered if float(item["T"]) < T]
                upper = [item for item in ordered if float(item["T"]) > T]
                relevant = [max(lower, key=lambda item: float(item["T"])),
                            min(upper, key=lambda item: float(item["T"]))]
            k_lo = max(float(item["kmin"]) for item in relevant)
            k_hi = min(float(item["kmax"]) for item in relevant)
            if k_lo > k_hi or K < k_lo - 1e-12 or K > k_hi + 1e-12:
                raise ValueError(
                    f"vol surface '{surface_id}' strike support at {T:.6g}Y is "
                    f"[{k_lo:.6g}, {k_hi:.6g}]; requested {K:.6g}")
            return

        strikes = getattr(surface, "K", None)
        tenors = getattr(surface, "T", None)
        if strikes is None or tenors is None or not len(strikes) or not len(tenors):
            raise ValueError(
                f"vol surface '{surface_id}' does not expose native K/T support")
        k_lo, k_hi = min(map(float, strikes)), max(map(float, strikes))
        t_lo, t_hi = min(map(float, tenors)), max(map(float, tenors))
        if K < k_lo - 1e-12 or K > k_hi + 1e-12:
            raise ValueError(
                f"vol surface '{surface_id}' strike support is "
                f"[{k_lo:.6g}, {k_hi:.6g}]; requested {K:.6g}")
        if T < t_lo - 1e-12 or T > t_hi + 1e-12:
            raise ValueError(
                f"vol surface '{surface_id}' tenor support is "
                f"[{t_lo:.6g}, {t_hi:.6g}]Y; requested {T:.6g}Y")

    @staticmethod
    def _surface_from_rr_bf(surface: dict, S0: float):
        """Expand an ATM / 25Δ risk-reversal / butterfly quote set into a smile
        surface: butterfly → curvature, risk-reversal → skew, on a moneyness grid
        with a flat term structure. Robust placement (no delta root-finding)."""
        import numpy as np
        from risk.vol_surface import VolSurface
        atm = float(surface["atm"])
        rr = float(surface.get("rr", 0.0))
        bf = float(surface.get("bf", 0.0))
        m = np.array([0.90, 0.95, 1.0, 1.05, 1.10])      # K / S0
        x = np.log(m) / np.log(1.10)                     # normalised log-moneyness
        smile = np.clip(atm + bf * x**2 + 0.5 * rr * x, 0.01, None)
        tenors = np.array([0.1, 0.25, 0.5, 1.0, 2.0])
        V = np.tile(smile.reshape(-1, 1), (1, len(tenors)))
        return VolSurface(S0 * m, tenors, V, S0=S0, label="rr_bf")

    @staticmethod
    def _vol_term_structure(vol):
        """Normalize a vol input: scalar stays scalar, [(T, vol), ...] -> callable."""
        if isinstance(vol, (int, float)) or callable(vol):
            return vol
        from risk.vol_surface import vol_term_structure
        pairs = sorted((float(t), float(v)) for t, v in vol)
        return vol_term_structure([t for t, _ in pairs], [v for _, v in pairs])

    # ── Rates (curve-based) ───────────────────────────────────────────
    def price_frn(self, face, spread, T, freq, curve=None, snapshot=None,
                  curve_id="flat_rub", proj_curve=None, proj_curve_id=None) -> dict:
        """Floating-rate note: forward-projected coupons (dual-curve when a
        projection curve is given), discounted on the discount curve."""
        from instruments.fixed_income import frn
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        proj_curve, snapshot = self._resolve_proj_curve(proj_curve, proj_curve_id, snapshot)
        return self._priced(
            model_id="frn", calculation_type="frn_pricing",
            engine=lambda: frn(face, spread, T, freq, curve, proj_curve),
            inputs={"face": face, "spread": spread, "T": T, "freq": freq,
                    "curve_id": curve_id, "proj_curve_id": proj_curve_id},
            snapshot=snapshot, user_action="Price FRN")

    def price_callable_bond(self, face, coupon, T, freq, sigma=0.15, call_price=None,
                            call_start=0.0, put_price=None, put_start=0.0, option="callable",
                            market_price=None, curve=None, snapshot=None, curve_id="flat_rub") -> dict:
        from instruments.fixed_income import callable_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="callable_bond", calculation_type="callable_bond_pricing",
            engine=lambda: callable_bond(face, coupon, T, int(freq), curve, sigma, call_price,
                                         call_start, put_price, put_start, option,
                                         market_price=market_price),
            inputs={"face": face, "coupon": coupon, "T": T, "freq": int(freq), "sigma": sigma,
                    "call_price": call_price, "call_start": call_start, "put_price": put_price,
                    "put_start": put_start, "option": option, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price callable/putable bond")

    def price_bond_future(self, deliverables, futures_price, repo_rate, T_delivery,
                          target_bpv=None, snapshot=None) -> dict:
        from instruments.fixed_income import bond_future
        return self._priced(
            model_id="bond_future", calculation_type="bond_future_pricing",
            engine=lambda: bond_future(deliverables, futures_price, repo_rate, T_delivery, target_bpv),
            inputs={"deliverables": deliverables, "futures_price": futures_price,
                    "repo_rate": repo_rate, "T_delivery": T_delivery, "target_bpv": target_bpv},
            snapshot=snapshot, user_action="Price bond future")

    def price_stir_future(self, forward_rate, notional=1_000_000, tenor=0.25, snapshot=None) -> dict:
        from instruments.fixed_income import stir_future
        return self._priced(
            model_id="stir_future", calculation_type="stir_future_pricing",
            engine=lambda: stir_future(forward_rate, notional, tenor),
            inputs={"forward_rate": forward_rate, "notional": notional, "tenor": tenor},
            snapshot=snapshot, user_action="Price STIR future")

    def price_repo(self, spot, repo_rate, T, coupon_income=0.0, direction="repo",
                   snapshot=None) -> dict:
        from instruments.fixed_income import repo
        return self._priced(
            model_id="repo", calculation_type="repo_pricing", value_key="forward_price",
            engine=lambda: repo(spot, repo_rate, T, coupon_income, direction),
            inputs={"spot": spot, "repo_rate": repo_rate, "T": T,
                    "coupon_income": coupon_income, "direction": direction},
            snapshot=snapshot, user_action="Price repo")

    def price_deposit(self, notional, rate, T, curve=None, snapshot=None,
                      curve_id="flat_rub") -> dict:
        from instruments.fixed_income import mm_deposit
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="mm_deposit", calculation_type="deposit_pricing", value_key="npv",
            engine=lambda: mm_deposit(notional, rate, T, curve),
            inputs={"notional": notional, "rate": rate, "T": T, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price deposit")

    def price_treasury_bill(self, face, discount_rate, T, snapshot=None) -> dict:
        from instruments.fixed_income import treasury_bill
        return self._priced(
            model_id="treasury_bill", calculation_type="treasury_bill_pricing",
            engine=lambda: treasury_bill(face, discount_rate, T),
            inputs={"face": face, "discount_rate": discount_rate, "T": T},
            snapshot=snapshot, user_action="Price treasury bill")

    def price_commercial_paper(self, face, discount_rate, T, snapshot=None) -> dict:
        from instruments.fixed_income import commercial_paper
        return self._priced(
            model_id="commercial_paper", calculation_type="commercial_paper_pricing",
            engine=lambda: commercial_paper(face, discount_rate, T),
            inputs={"face": face, "discount_rate": discount_rate, "T": T},
            snapshot=snapshot, user_action="Price commercial paper")

    def price_custom_bond(self, cashflows, freq=2, curve=None, snapshot=None,
                          curve_id="flat_rub") -> dict:
        """Price a manual cashflow schedule [(t_years, amount), ...]."""
        from instruments.fixed_income import custom_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="custom_bond", calculation_type="custom_bond_pricing",
            engine=lambda: custom_bond(cashflows, curve, int(freq)),
            inputs={"cashflows": list(cashflows), "freq": int(freq), "curve_id": curve_id},
            snapshot=snapshot, user_action="Price custom bond")

    def price_amortizing_bond(self, face, coupon, T, freq, amort_type="linear",
                              day_count="act365", curve=None, snapshot=None,
                              curve_id="flat_rub") -> dict:
        from instruments.fixed_income import amortizing_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="amortizing_bond", calculation_type="amortizing_bond_pricing",
            engine=lambda: amortizing_bond(face, coupon, T, int(freq), curve, amort_type, day_count),
            inputs={"face": face, "coupon": coupon, "T": T, "freq": int(freq),
                    "amort_type": amort_type, "day_count": day_count, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price amortizing bond")

    def price_step_bond(self, face, coupon1, coupon2, switch_year, T, freq,
                        day_count="act365", curve=None, snapshot=None, curve_id="flat_rub") -> dict:
        from instruments.fixed_income import step_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        steps = [(0.0, coupon1), (switch_year, coupon2)]
        return self._priced(
            model_id="step_bond", calculation_type="step_bond_pricing",
            engine=lambda: step_bond(face, steps, T, int(freq), curve, day_count),
            inputs={"face": face, "coupon1": coupon1, "coupon2": coupon2,
                    "switch_year": switch_year, "T": T, "freq": int(freq),
                    "day_count": day_count, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price step bond")

    def price_perpetual_bond(self, face, coupon, freq=1, curve=None, snapshot=None,
                             curve_id="flat_rub") -> dict:
        from instruments.fixed_income import perpetual_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="perpetual_bond", calculation_type="perpetual_bond_pricing",
            engine=lambda: perpetual_bond(face, coupon, curve, int(freq)),
            inputs={"face": face, "coupon": coupon, "freq": int(freq), "curve_id": curve_id},
            snapshot=snapshot, user_action="Price perpetual bond")

    def price_inflation_linked_bond(self, face, real_coupon, T, freq, base_cpi=100.0,
                                    current_cpi=100.0, inflation_rate=0.04, day_count="act365",
                                    curve=None, snapshot=None, curve_id="flat_rub") -> dict:
        from instruments.fixed_income import inflation_linked_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="inflation_linked_bond", calculation_type="inflation_linked_bond_pricing",
            engine=lambda: inflation_linked_bond(face, real_coupon, T, int(freq), curve,
                                                 base_cpi, current_cpi, inflation_rate, day_count),
            inputs={"face": face, "real_coupon": real_coupon, "T": T, "freq": int(freq),
                    "base_cpi": base_cpi, "current_cpi": current_cpi,
                    "inflation_rate": inflation_rate, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price inflation-linked bond")

    def price_fra(self, notional, K, T1, T2, curve=None, proj_curve=None, snapshot=None,
                  curve_id="flat_rub", proj_curve_id=None) -> dict:
        """Forward Rate Agreement: forward on proj_curve, discount on the curve."""
        from instruments.fixed_income import fra
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        proj_curve, snapshot = self._resolve_proj_curve(proj_curve, proj_curve_id, snapshot)
        return self._priced(
            model_id="fra", calculation_type="fra_pricing", value_key="npv",
            engine=lambda: fra(notional, K, T1, T2, curve, proj_curve),
            inputs={"notional": notional, "K": K, "T1": T1, "T2": T2, "curve_id": curve_id,
                    "proj_curve_id": proj_curve_id, "dual_curve": proj_curve is not None},
            snapshot=snapshot, user_action="Price FRA")

    def price_cap_floor(self, notional, K, T, freq, vol=None, opt="cap", curve=None,
                        proj_curve=None, snapshot=None, curve_id="flat_rub",
                        proj_curve_id=None, vol_strip_id=None) -> dict:
        """
        Cap/Floor as a strip of Black-76 caplets/floorlets.
        vol: scalar, callable sigma(T), or [(tenor, vol), ...] term structure
        (variance-flat interpolation). With vol omitted and vol_strip_id set,
        per-caplet strike-aware vols come from the CapletVolStrip (Stage A).
        Dual-curve via proj_curve / proj_curve_id.
        """
        from instruments.fixed_income import cap_floor
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        proj_curve, snapshot = self._resolve_proj_curve(proj_curve, proj_curve_id, snapshot)
        try:
            if vol is None:
                if vol_strip_id is None:
                    raise ValueError("Provide vol or vol_strip_id")
                snapshot = snapshot or self.market_data.demo_snapshot()
                strip = self.market_data.get_vol_surface(vol_strip_id, snapshot)
                if not hasattr(strip, "vol"):
                    raise TypeError(f"{vol_strip_id} is not a CapletVolStrip")
                vol = lambda T1, _s=strip, _K=K: _s.vol(T1, _K)
        except Exception as exc:
            return self._error_result(model_id="capfloor", error=exc, snapshot=snapshot,
                                      calculation_type="cap_floor_pricing",
                                      inputs={"K": K, "vol_strip_id": vol_strip_id})
        vol_input = self._vol_term_structure(vol)
        return self._priced(
            model_id="capfloor", calculation_type="cap_floor_pricing",
            engine=lambda: cap_floor(notional, K, T, freq, curve, vol_input, opt,
                                     proj_curve=proj_curve),
            inputs={"notional": notional, "K": K, "T": T, "freq": freq,
                    "vol": vol if isinstance(vol, (int, float)) else f"strip:{vol_strip_id}" if vol_strip_id else "callable" if callable(vol) else list(map(tuple, vol)),
                    "opt": opt, "curve_id": curve_id, "proj_curve_id": proj_curve_id,
                    "dual_curve": proj_curve is not None},
            snapshot=snapshot, user_action="Price cap/floor")

    def price_swaption(self, notional, K, T_option, T_swap, freq, sigma=None, opt="payer",
                       curve=None, snapshot=None, curve_id="flat_rub",
                       cube_id=None) -> dict:
        """
        European swaption via Black-76 on the forward swap rate. sigma may be
        omitted when cube_id names a SwaptionCube — the strike-aware node vol
        (SABR smile recentred on the ATM matrix) is then used (Stage A).
        """
        from instruments.fixed_income import swaption
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        try:
            if sigma is None:
                if cube_id is None:
                    raise ValueError("Provide sigma or cube_id")
                snapshot = snapshot or self.market_data.demo_snapshot()
                cube = self.market_data.get_swaption_cube(cube_id, snapshot)
                from models.short_rate import _forward_swap_rate
                F = _forward_swap_rate(curve, T_option, T_swap, int(freq))[0]
                sigma = cube.vol(T_option, T_swap, K, F)
        except Exception as exc:
            return self._error_result(model_id="swaption", error=exc, snapshot=snapshot,
                                      calculation_type="swaption_pricing",
                                      inputs={"K": K, "cube_id": cube_id})
        return self._priced(
            model_id="swaption", calculation_type="swaption_pricing",
            engine=lambda: swaption(notional, K, T_option, T_swap, freq, curve, sigma, opt),
            inputs={"notional": notional, "K": K, "T_option": T_option, "T_swap": T_swap,
                    "freq": freq, "sigma": sigma, "opt": opt, "curve_id": curve_id,
                    "cube_id": cube_id},
            snapshot=snapshot, user_action="Price swaption")

    # ── Credit ────────────────────────────────────────────────────────
    def price_cds(self, notional, spread, T, freq, hazard, r, recovery=0.4,
                  buy_protection=True, snapshot=None) -> dict:
        """Credit default swap NPV / fair spread (flat hazard, flat rate)."""
        from instruments.credit import cds
        return self._priced(
            model_id="cds", calculation_type="cds_pricing", value_key="npv",
            engine=lambda: cds(notional, spread, T, freq, hazard, r, recovery, buy_protection),
            inputs={"notional": notional, "spread": spread, "T": T, "freq": freq,
                    "hazard": hazard, "r": r, "recovery": recovery,
                    "buy_protection": buy_protection},
            snapshot=snapshot, user_action="Price CDS")

    def price_cds_curve(self, notional, spread, T, freq, hazard_curve=None,
                        hazard_id="hazard_1t_demo", curve=None, curve_id="ofz_demo",
                        recovery=None, buy_protection=True, snapshot=None) -> dict:
        """CDS off a bootstrapped hazard curve + discount curve (Phase 1)."""
        from instruments.credit import cds_curve
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        if hazard_curve is None:
            snapshot = snapshot or self.market_data.demo_snapshot()
            hazard_curve = self.market_data.get_hazard_curve(hazard_id, snapshot)
        return self._priced(
            model_id="cds_curve", calculation_type="cds_curve_pricing", value_key="npv",
            engine=lambda: cds_curve(notional, spread, T, freq, hazard_curve, curve,
                                     recovery, buy_protection),
            inputs={"notional": notional, "spread": spread, "T": T, "freq": freq,
                    "hazard_id": hazard_id, "curve_id": curve_id, "recovery": recovery,
                    "buy_protection": buy_protection},
            snapshot=snapshot, user_action="Price CDS on hazard curve")

    def price_risky_bond(self, face, coupon, T, freq, hazard_curve=None,
                         hazard_id="hazard_1t_demo", curve=None, curve_id="ofz_demo",
                         recovery=None, snapshot=None) -> dict:
        """Credit-risky bond: survival-weighted cashflows + recovery (Phase 1)."""
        from instruments.credit import risky_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        if hazard_curve is None:
            snapshot = snapshot or self.market_data.demo_snapshot()
            hazard_curve = self.market_data.get_hazard_curve(hazard_id, snapshot)
        return self._priced(
            model_id="risky_bond", calculation_type="risky_bond_pricing",
            engine=lambda: risky_bond(face, coupon, T, freq, curve, hazard_curve, recovery),
            inputs={"face": face, "coupon": coupon, "T": T, "freq": freq,
                    "hazard_id": hazard_id, "curve_id": curve_id, "recovery": recovery},
            snapshot=snapshot, user_action="Price risky bond")

    def price_inflation_linked_bond_real(self, face, real_coupon, T, freq,
                                         base_cpi=100.0, current_cpi=100.0,
                                         nominal_curve=None, real_curve=None,
                                         nominal_curve_id="ofz_demo",
                                         real_curve_id="ofzin_real_demo",
                                         day_count="act365", snapshot=None) -> dict:
        """Linker off the (nominal, real) curve pair — curve-implied breakeven (Phase 1)."""
        from curves.inflation import inflation_linked_bond_curve
        nominal_curve, snapshot = self._resolve_curve(nominal_curve, snapshot, nominal_curve_id)
        real_curve, snapshot = self._resolve_curve(real_curve, snapshot, real_curve_id)
        return self._priced(
            model_id="inflation_linked_bond", calculation_type="inflation_linked_bond_pricing",
            engine=lambda: inflation_linked_bond_curve(face, real_coupon, T, int(freq),
                                                       nominal_curve, real_curve,
                                                       base_cpi, current_cpi, day_count),
            inputs={"face": face, "real_coupon": real_coupon, "T": T, "freq": int(freq),
                    "base_cpi": base_cpi, "current_cpi": current_cpi,
                    "nominal_curve_id": nominal_curve_id, "real_curve_id": real_curve_id,
                    "projection": "curve_pair"},
            snapshot=snapshot, user_action="Price inflation-linked bond (real curve)")

    # ── Multi-asset ───────────────────────────────────────────────────
    def price_spread_option(self, S1, S2, K, T, r, sigma1, sigma2, rho,
                            q1=0.0, q2=0.0, snapshot=None) -> dict:
        """Spread option via the Kirk approximation."""
        from instruments.multi_asset import spread_option_kirk
        return self._priced(
            model_id="multi_asset", calculation_type="spread_option_pricing",
            engine=lambda: spread_option_kirk(S1, S2, K, T, r, sigma1, sigma2, rho, q1, q2),
            inputs={"S1": S1, "S2": S2, "K": K, "T": T, "r": r, "sigma1": sigma1,
                    "sigma2": sigma2, "rho": rho, "q1": q1, "q2": q2},
            snapshot=snapshot, user_action="Price spread option")

    def price_basket_option(self, assets, weights, K, T, r, sigmas, corr,
                            opt="call", snapshot=None) -> dict:
        """Basket option via Monte Carlo (correlation matrix)."""
        import numpy as np
        from instruments.multi_asset import basket_option
        corr_matrix = np.array(corr, dtype=float)
        return self._priced(
            model_id="multi_asset", calculation_type="basket_option_pricing",
            engine=lambda: basket_option(list(assets), list(weights), K, T, r,
                                         list(sigmas), corr_matrix, opt=opt),
            inputs={"assets": list(assets), "weights": list(weights), "K": K, "T": T,
                    "r": r, "sigmas": list(sigmas), "opt": opt},
            snapshot=snapshot, user_action="Price basket option")

    # ── Structured ────────────────────────────────────────────────────
    def price_autocall_phoenix(self, S0, r, q, sigma, T, obs_dates, autocall_barrier,
                               coupon_barrier, ki_barrier, coupon_rate,
                               memory_coupon=True, n_sims=50_000, steps=252,
                               snapshot=None) -> dict:
        """Phoenix / autocallable structured note via Monte Carlo."""
        from instruments.structured.phoenix import phoenix
        return self._priced(
            model_id="structured_autocall", calculation_type="autocall_phoenix_pricing",
            engine=lambda: phoenix(S0, r, q, sigma, T, list(obs_dates), autocall_barrier,
                                   coupon_barrier, ki_barrier, coupon_rate,
                                   memory_coupon=memory_coupon, n_sims=n_sims, steps=steps),
            inputs={"S0": S0, "r": r, "q": q, "sigma": sigma, "T": T,
                    "obs_dates": list(obs_dates), "autocall_barrier": autocall_barrier,
                    "coupon_barrier": coupon_barrier, "ki_barrier": ki_barrier,
                    "coupon_rate": coupon_rate, "memory_coupon": memory_coupon},
            snapshot=snapshot, user_action="Price autocall/phoenix note")

    def price_basket_note(self, specs, r, T, *, principal_protection=1.0,
                          guaranteed_coupon=0.0, coupon_freq=1, participation=1.0,
                          cap=None, basket_type="average", face=1000.0,
                          n_sims=40_000, steps=52, snapshot=None) -> dict:
        """Structured note on a basket of real underlyings (equities/bonds/indices).

        ``specs`` is a list of ``{"secid", "kind", "weight"}``. Spot, vol, income and
        the correlation matrix are resolved from market data; principal protection,
        guaranteed coupon, participation and cap configure the wrapper.
        """
        from instruments.structured.basket_note import basket_note
        specs = [dict(s) for s in specs]

        inputs = {"specs": specs, "r": r, "T": T,
                  "principal_protection": principal_protection,
                  "guaranteed_coupon": guaranteed_coupon,
                  "coupon_freq": int(coupon_freq),
                  "participation": participation, "cap": cap,
                  "basket_type": basket_type, "face": face,
                  "n_sims": int(n_sims), "steps": int(steps)}
        resolution_warnings = []

        def _engine():
            constituents, corr, evidence = self.market_data.basket_market_inputs(
                specs, T, snapshot=snapshot, include_evidence=True)
            inputs["market_data_resolution"] = evidence
            resolution_warnings.extend(self._basket_fallback_warnings(evidence))
            raw = basket_note(
                constituents, r, T, corr,
                principal_protection=principal_protection,
                guaranteed_coupon=guaranteed_coupon, coupon_freq=int(coupon_freq),
                participation=participation, cap=cap, basket_type=basket_type,
                face=face, n_sims=int(n_sims), steps=int(steps))
            raw["resolved_inputs"] = self._canonical_basket_inputs(
                constituents, corr,
                resolved_snapshot_id=evidence["snapshot"]["snapshot_id"])
            raw["market_data_evidence"] = evidence
            return raw

        return self._priced(
            model_id="structured_basket_note", calculation_type="basket_note_pricing",
            engine=_engine,
            inputs=inputs,
            snapshot=snapshot,
            warnings=resolution_warnings,
            user_action="Price basket structured note")

    def price_multi_asset_autocall(
        self,
        specs,
        r,
        T,
        *,
        reference_spots=None,
        reference_fixing_dates=None,
        observation_dates=None,
        autocall_barrier=1.20,
        autocall_aggregation="best_of",
        protection_barrier=0.65,
        protection_aggregation="worst_of",
        protection_monitoring="maturity",
        coupon_barrier=0.65,
        coupon_aggregation="worst_of",
        coupon_rate=0.0,
        guaranteed_coupon=0.05,
        memory_coupon=True,
        notional=1_000.0,
        n_sims=20_000,
        steps=100,
        seed=42,
        snapshot=None,
    ) -> dict:
        """Autocall/Phoenix on 1--5 real equities, indices or bonds.

        ``specs`` contains ``secid``, ``kind`` and ``weight``.  The market-data
        service resolves current spot, historical volatility, income/carry and
        the full empirical correlation matrix before the path engine runs.
        Trigger aggregations are independent, allowing e.g. best-of autocall
        with worst-of coupon/protection tests.
        """
        from instruments.structured.multi_asset_autocall import (
            multi_asset_autocall_component_greeks,
        )

        specs = [dict(spec) for spec in specs]
        resolved_observations = list(observation_dates or [])
        contractual_references = (
            None if reference_spots is None else list(reference_spots)
        )
        contractual_fixing_dates = list(reference_fixing_dates or [])

        inputs = {
            "specs": specs,
            "r": r,
            "T": T,
            "reference_spots": contractual_references,
            "reference_fixing_dates": contractual_fixing_dates,
            "observation_dates": resolved_observations,
            "autocall_barrier": autocall_barrier,
            "autocall_aggregation": autocall_aggregation,
            "protection_barrier": protection_barrier,
            "protection_aggregation": protection_aggregation,
            "protection_monitoring": protection_monitoring,
            "coupon_barrier": coupon_barrier,
            "coupon_aggregation": coupon_aggregation,
            "coupon_rate": coupon_rate,
            "guaranteed_coupon": guaranteed_coupon,
            "memory_coupon": memory_coupon,
            "notional": notional,
            "n_sims": int(n_sims),
            "steps": int(steps),
            "seed": int(seed),
        }

        def _engine():
            constituents, correlation, evidence = self.market_data.basket_market_inputs(
                specs, T, snapshot=snapshot, include_evidence=True)
            count = len(constituents)
            if (contractual_references is not None
                    and len(contractual_references) != count):
                raise ValueError(
                    "reference_spots must contain one contractual fixing per "
                    f"underlying ({count} required)"
                )
            if contractual_fixing_dates and len(contractual_fixing_dates) != count:
                raise ValueError(
                    "reference_fixing_dates must contain one date per "
                    f"underlying ({count} required)"
                )
            for index, raw_date in enumerate(contractual_fixing_dates):
                try:
                    fixing_date = date.fromisoformat(str(raw_date))
                except ValueError as exc:
                    raise ValueError(
                        "reference_fixing_dates must use YYYY-MM-DD"
                    ) from exc
                valuation_date = getattr(snapshot, "valuation_date", None)
                if valuation_date is not None and fixing_date > valuation_date:
                    raise ValueError(
                        "reference fixing date cannot be after the snapshot "
                        f"valuation date (index {index})"
                    )
            effective_references = (
                contractual_references
                if contractual_references is not None
                else [item.spot for item in constituents]
            )
            inputs["market_data_resolution"] = evidence
            limitations.extend(self._basket_fallback_warnings(evidence))
            if contractual_references is None:
                limitations.append(
                    "Contract reference spots were not supplied; current snapshot "
                    "spots are used as an inception-only fixing assumption. "
                    "Seasoned trades require explicit immutable reference_spots."
                )
            raw = multi_asset_autocall_component_greeks(
                constituents,
                r,
                T,
                correlation,
                reference_spots=effective_references,
                observation_dates=resolved_observations,
                autocall_barrier=autocall_barrier,
                autocall_aggregation=autocall_aggregation,
                protection_barrier=protection_barrier,
                protection_aggregation=protection_aggregation,
                protection_monitoring=protection_monitoring,
                coupon_barrier=coupon_barrier,
                coupon_aggregation=coupon_aggregation,
                coupon_rate=coupon_rate,
                guaranteed_coupon=guaranteed_coupon,
                memory_coupon=memory_coupon,
                notional=notional,
                n_sims=int(n_sims),
                steps=int(steps),
                seed=int(seed),
            )
            raw["resolved_inputs"] = self._canonical_basket_inputs(
                constituents, correlation,
                resolved_snapshot_id=evidence["snapshot"]["snapshot_id"],
                reference_spots=contractual_references,
                reference_fixing_dates=contractual_fixing_dates)
            evidence["contract_reference"] = {
                "source": raw["resolved_inputs"]["reference_spot_source"],
                "reference_spots": list(effective_references),
                "reference_fixing_dates": contractual_fixing_dates,
            }
            raw["market_data_evidence"] = evidence
            return raw

        limitations = [
            "Multi-asset autocall uses correlated GBM with constant volatility, "
            "correlation, carry and discount rate over the full maturity.",
        ]
        if any(str(spec.get("kind", "")).lower() == "bond" for spec in specs):
            limitations.append(
                "Bond underlyings are simulated as price-index GBMs using "
                "historical volatility and YTM carry; coupon cashflows, "
                "duration/convexity and issuer default are not modelled."
            )
        return self._priced(
            model_id="structured_autocall",
            calculation_type="multi_asset_autocall_pricing",
            engine=_engine,
            inputs=inputs,
            snapshot=snapshot,
            user_action="Price multi-asset autocall / Phoenix",
            warnings=limitations,
        )

    def price_bond(
        self,
        face: float | BondPricingRequest,
        coupon: float | None = None,
        T: float | None = None,
        freq: int | None = None,
        curve=None,
        snapshot: MarketDataSnapshot | None = None,
        curve_id: str = "flat_rub",
        day_count: str | None = None,
    ) -> dict:
        """Price a fixed-rate bond through the existing fixed income engine."""
        from instruments.fixed_income import fixed_bond

        resolved_snapshot = snapshot
        try:
            self._enforce_model("fixed_bond")
            request = self._bond_request(face, coupon, T, freq, curve_id)
            effective_day_count = day_count or request.day_count
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
                day_count=effective_day_count,
                business_day_convention=request.business_day_convention,
            )
            result = self._result(
                value=raw.get("price"),
                model_id="fixed_bond",
                raw=raw,
                snapshot=resolved_snapshot,
                warnings=warnings,
                calculation_type="bond_pricing",
                inputs={"request": request, "curve_id": request.curve_id, "direct_curve": curve is not None and snapshot is None},
                user_action="Price fixed-rate bond",
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
            return self._error_result(
                model_id="fixed_bond",
                error=exc,
                snapshot=resolved_snapshot,
                calculation_type="bond_pricing",
                inputs={"face": face, "coupon": coupon, "T": T, "freq": freq, "curve_id": curve_id},
            )

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
        proj_curve=None,
        proj_curve_id: str | None = None,
    ) -> dict:
        """
        Price an IRS: floating leg projected on proj_curve (or the snapshot curve
        named by proj_curve_id, e.g. 'ruonia_demo'), both legs discounted on the
        discount curve.
        """
        from instruments.fixed_income import irs

        try:
            self._enforce_model("irs")
            curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
            proj_curve, snapshot = self._resolve_proj_curve(proj_curve, proj_curve_id, snapshot)
            raw = irs(notional, fixed_rate, T, freq, curve, pay_fixed, proj_curve)
            return self._result(
                value=raw.get("npv"),
                model_id="irs",
                raw=raw,
                snapshot=snapshot,
                calculation_type="irs_pricing",
                inputs={
                    "notional": notional,
                    "fixed_rate": fixed_rate,
                    "T": T,
                    "freq": freq,
                    "pay_fixed": pay_fixed,
                    "curve_id": curve_id,
                    "proj_curve_id": proj_curve_id,
                    "dual_curve": proj_curve is not None,
                },
                user_action="Price IRS",
            )
        except Exception as exc:
            return self._error_result(
                model_id="irs",
                error=exc,
                snapshot=snapshot,
                calculation_type="irs_pricing",
                inputs={"notional": notional, "fixed_rate": fixed_rate, "T": T, "freq": freq, "pay_fixed": pay_fixed, "curve_id": curve_id},
            )

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
            return self._result(
                value=value,
                model_id="fx_forward",
                raw=raw,
                snapshot=snapshot,
                calculation_type="fx_forward_pricing",
                inputs={"S": S, "r_d": r_d, "r_f": r_f, "T": T, "notional": notional, "forward_agreed": forward_agreed},
                user_action="Price FX forward",
            )
        except Exception as exc:
            return self._error_result(
                model_id="fx_forward",
                error=exc,
                snapshot=snapshot,
                calculation_type="fx_forward_pricing",
                inputs={"S": S, "r_d": r_d, "r_f": r_f, "T": T, "notional": notional, "forward_agreed": forward_agreed},
            )

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
            return self._result(
                value=raw.get("price"),
                model_id="garman_kohlhagen",
                raw=raw,
                snapshot=snapshot,
                calculation_type="fx_option_pricing",
                inputs={"S": S, "K": K, "T": T, "r_d": r_d, "r_f": r_f, "sigma": sigma, "notional": notional, "opt": opt, "quote": quote},
                user_action="Price FX option",
            )
        except Exception as exc:
            return self._error_result(
                model_id="garman_kohlhagen",
                error=exc,
                snapshot=snapshot,
                calculation_type="fx_option_pricing",
                inputs={"S": S, "K": K, "T": T, "r_d": r_d, "r_f": r_f, "sigma": sigma, "notional": notional, "opt": opt, "quote": quote},
            )

    def price_g2pp_swaption(self, notional, K, T_option, T_swap, freq=2,
                            a=0.1, sigma=0.01, b=0.3, eta=0.012, rho=-0.7,
                            opt="payer", n_sims=50_000, curve=None,
                            snapshot=None, curve_id="flat_rub", method="analytic") -> dict:
        """European swaption under G2++ (two-factor Gaussian). method=analytic
        (Brigo-Mercurio closed form, M-calib) | mc (forward-measure, M3a)."""
        from models.g2pp import g2pp_swaption
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="g2pp", calculation_type="g2pp_swaption_pricing",
            engine=lambda: g2pp_swaption(curve, notional, K, T_option, T_swap,
                                         int(freq), a, sigma, b, eta, rho, opt,
                                         int(n_sims), method=method),
            inputs={"notional": notional, "K": K, "T_option": T_option,
                    "T_swap": T_swap, "freq": int(freq), "a": a, "sigma": sigma,
                    "b": b, "eta": eta, "rho": rho, "opt": opt, "curve_id": curve_id,
                    "method": method},
            snapshot=snapshot, user_action="Price G2++ swaption")

    def price_afv_convertible(self, S, sigma, q, face, coupon, freq, T, conv_ratio,
                              r=0.05, lam0=0.02, alpha=1.2, recovery=0.4, N=400,
                              snapshot=None) -> dict:
        """Andersen-Buffum convertible bond (equity-linked default), M8."""
        from models.convertible_afv import afv_convertible
        return self._priced(
            model_id="afv_convertible", calculation_type="afv_convertible_pricing",
            engine=lambda: afv_convertible(S, sigma, q, face, coupon, int(freq), T,
                                           conv_ratio, r, lam0, alpha, recovery, int(N)),
            inputs={"S": S, "sigma": sigma, "q": q, "face": face, "coupon": coupon,
                    "freq": int(freq), "T": T, "conv_ratio": conv_ratio, "r": r,
                    "lam0": lam0, "alpha": alpha, "recovery": recovery},
            snapshot=snapshot, user_action="Price AFV convertible")

    def price_mbs(self, balance, wac, net_coupon, wam_months, psa=100.0,
                  disc_rate=None, oas=0.0, snapshot=None) -> dict:
        """MBS pass-through price + WAL with PSA prepayment (M8)."""
        from models.mbs import mbs_price
        return self._priced(
            model_id="mbs", calculation_type="mbs_pricing",
            engine=lambda: mbs_price(balance, wac, net_coupon, int(wam_months),
                                     psa, disc_rate, None, oas),
            inputs={"balance": balance, "wac": wac, "net_coupon": net_coupon,
                    "wam_months": int(wam_months), "psa": psa,
                    "disc_rate": disc_rate, "oas": oas},
            snapshot=snapshot, user_action="Price MBS pass-through")

    def price_isda_cds(self, notional, coupon, quoted_spread, T, freq=4, r=0.03,
                       recovery=0.4, snapshot=None) -> dict:
        """ISDA standard-model CDS: upfront from a quoted spread (M7)."""
        from instruments.credit import cds_upfront
        return self._priced(
            model_id="cds_isda", calculation_type="isda_cds_pricing", value_key="upfront",
            engine=lambda: cds_upfront(notional, coupon, quoted_spread, T, int(freq), r, recovery),
            inputs={"notional": notional, "coupon": coupon, "quoted_spread": quoted_spread,
                    "T": T, "freq": int(freq), "r": r, "recovery": recovery},
            snapshot=snapshot, user_action="Price ISDA CDS")

    def price_structural_credit(self, model, V0, D, T, r, sigma_V, barrier=None,
                                snapshot=None) -> dict:
        """Structural default model (M7).

        ``model`` accepts canonical IDs. For KMV the legacy argument names
        ``V0`` and ``sigma_V`` carry observable equity value and equity vol.
        """
        from models.structural_credit import black_cox, kmv_calibrate, merton
        aliases = {"merton": "merton_structural"}
        mid = aliases.get(model, model)
        if mid not in {"merton_structural", "black_cox", "kmv"}:
            return self._error_result(
                model_id=mid,
                error=ValueError(f"Unknown structural credit model {model}"),
                snapshot=snapshot,
                calculation_type="structural_credit_pricing",
                inputs={"model": model},
            )

        def engine():
            if mid == "black_cox":
                res = black_cox(V0, D, T, r, sigma_V, barrier)
                return {"price": res["pd"], **res}
            if mid == "kmv":
                res = kmv_calibrate(V0, sigma_V, D, T, r)
                return {"price": res["edf"], **res}
            res = merton(V0, D, T, r, sigma_V)
            return {"price": res["credit_spread"], **res}
        return self._priced(
            model_id=mid, calculation_type="structural_credit_pricing", value_key="price",
            engine=engine,
            inputs={"model": model, "V0": V0, "D": D, "T": T, "r": r, "sigma_V": sigma_V},
            snapshot=snapshot, user_action="Price structural credit")

    def price_cdo_tranche(self, pds, rho, K1, K2, recovery=0.4, snapshot=None) -> dict:
        """CDO tranche expected loss via the one-factor Gaussian copula (M7)."""
        from models.credit_portfolio import cdo_tranche
        return self._priced(
            model_id="gaussian_copula", calculation_type="cdo_tranche_pricing",
            value_key="expected_tranche_loss",
            engine=lambda: cdo_tranche(list(pds), rho, K1, K2, recovery),
            inputs={"n_names": len(pds), "rho": rho, "K1": K1, "K2": K2, "recovery": recovery},
            snapshot=snapshot, user_action="Price CDO tranche")

    def price_kth_to_default(self, pds, rho, k=1, snapshot=None) -> dict:
        """kth-to-default probability via the one-factor Gaussian copula (M7)."""
        from models.credit_portfolio import kth_to_default_prob
        return self._priced(
            model_id="gaussian_copula", calculation_type="kth_to_default_pricing",
            value_key="prob",
            engine=lambda: {"prob": kth_to_default_prob(list(pds), rho, int(k))},
            inputs={"n_names": len(pds), "rho": rho, "k": int(k)},
            snapshot=snapshot, user_action="Price kth-to-default basket")

    def price_commodity_option(self, model, spot, K, T_option, T_future, opt="call",
                               r=0.05, kappa=1.0, rho=0.3, snapshot=None,
                               **params) -> dict:
        """Option on a commodity future under Schwartz-Smith / Gibson-Schwartz (M5).
        model: 'schwartz_smith' | 'gibson_schwartz'."""
        from models.commodity import SchwartzSmith, GibsonSchwartz
        if model == "gibson_schwartz":
            m = GibsonSchwartz(spot=spot, delta0=params.get("delta0", 0.05), kappa=kappa,
                               sigma_S=params.get("sigma_S", 0.30),
                               alpha_tilde=params.get("alpha_tilde", 0.05),
                               sigma_delta=params.get("sigma_delta", 0.30), rho=rho, r=r)
            mid = "gibson_schwartz"
        else:
            import numpy as _np
            m = SchwartzSmith(chi0=params.get("chi0", 0.0),
                              xi0=_np.log(spot) - params.get("chi0", 0.0), kappa=kappa,
                              sigma_chi=params.get("sigma_chi", 0.30),
                              mu_xi=params.get("mu_xi", 0.0),
                              sigma_xi=params.get("sigma_xi", 0.15), rho=rho, r=r)
            mid = "schwartz_smith"
        return self._priced(
            model_id=mid, calculation_type="commodity_option_pricing",
            engine=lambda: {"price": m.futures_option(T_option, T_future, K, opt)},
            inputs={"model": model, "spot": spot, "K": K, "T_option": T_option,
                    "T_future": T_future, "opt": opt, "r": r, "kappa": kappa, "rho": rho},
            snapshot=snapshot, user_action="Price commodity futures option")

    def commodity_futures_curve(self, model, spot, tenors, r=0.05, kappa=1.0,
                                rho=0.3, snapshot=None, **params) -> dict:
        """Futures term structure F(0,T) under SS/GS (M5)."""
        from models.commodity import SchwartzSmith, GibsonSchwartz, commodity_futures_curve
        inputs = {
            "model": model, "spot": spot, "tenors": list(tenors), "r": r,
            "kappa": kappa, "rho": rho, **params,
        }
        try:
            self._enforce_model(model)
            if model == "gibson_schwartz":
                m = GibsonSchwartz(spot=spot, delta0=params.get("delta0", 0.05), kappa=kappa,
                                   sigma_S=params.get("sigma_S", 0.30),
                                   alpha_tilde=params.get("alpha_tilde", 0.05),
                                   sigma_delta=params.get("sigma_delta", 0.30), rho=rho, r=r)
            else:
                import numpy as _np
                m = SchwartzSmith(chi0=params.get("chi0", 0.0),
                                  xi0=_np.log(spot) - params.get("chi0", 0.0), kappa=kappa,
                                  sigma_chi=params.get("sigma_chi", 0.30),
                                  mu_xi=params.get("mu_xi", 0.0),
                                  sigma_xi=params.get("sigma_xi", 0.15), rho=rho, r=r)
            curve = commodity_futures_curve(m, tenors)
            governed = self._result(
                value=None, model_id=model, raw={"curve": curve},
                snapshot=snapshot,
                calculation_type="commodity_futures_curve",
                inputs=inputs, user_action="Build commodity futures curve",
            )
            # Preserve the established direct-service convenience key while
            # also returning the governed raw/provenance envelope.
            governed["curve"] = curve
            return governed
        except Exception as exc:                       # noqa: BLE001
            return self._error_result(
                model_id=model, error=exc, snapshot=snapshot,
                calculation_type="commodity_futures_curve", inputs=inputs,
            )

    def price_amc_bermudan_swaption(self, notional, K, exercise_dates, T_end,
                                    freq=2, kappa=0.1, sigma_r=0.012, opt="payer",
                                    n_sims=20_000, curve=None, snapshot=None,
                                    curve_id="flat_rub") -> dict:
        """Bermudan swaption via American Monte Carlo (Longstaff-Schwartz), M4c."""
        from risk.xva import amc_bermudan_swaption
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="amc", calculation_type="amc_bermudan_swaption_pricing",
            engine=lambda: amc_bermudan_swaption(notional, K, list(exercise_dates),
                                                 T_end, int(freq), curve, kappa,
                                                 sigma_r, opt, int(n_sims)),
            inputs={"notional": notional, "K": K, "exercise_dates": list(exercise_dates),
                    "T_end": T_end, "freq": int(freq), "kappa": kappa,
                    "sigma_r": sigma_r, "opt": opt, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price AMC Bermudan swaption")

    def calibrate_rate_model(self, model_id, instruments, freq=2, curve=None,
                             cube=None, snapshot=None, curve_id="flat_rub") -> dict:
        """Calibrate a rate model (g2pp/lmm/bk/cheyette/hw) to a swaption cube
        (M-calib). Returns the fitted params + per-instrument repricing table."""
        from models.rate_calibration import calibrate_rate_model
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        if cube is None:
            return {"errors": ["no swaption cube supplied"], "model_id": model_id}
        try:
            res = calibrate_rate_model(model_id, curve, cube, list(instruments),
                                       int(freq), 1.0)
            res.update(errors=[], model_id=model_id)
            return res
        except Exception as exc:                       # noqa: BLE001
            return {"errors": [str(exc)], "model_id": model_id}

    def price_lmm_swaption(self, notional, K, T_option, T_swap, freq=2,
                           vol=0.20, corr_beta=0.1, opt="payer", n_sims=50_000,
                           steps=24, curve=None, snapshot=None,
                           curve_id="flat_rub") -> dict:
        """European swaption under the LIBOR market model, MC (M3b)."""
        from models.lmm import lmm_swaption
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="lmm", calculation_type="lmm_swaption_pricing",
            engine=lambda: lmm_swaption(curve, notional, K, T_option, T_swap,
                                        int(freq), vol, corr_beta, opt,
                                        int(n_sims), int(steps)),
            inputs={"notional": notional, "K": K, "T_option": T_option,
                    "T_swap": T_swap, "freq": int(freq), "vol": vol,
                    "corr_beta": corr_beta, "opt": opt, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price LMM swaption")

    def price_lmm_cap(self, notional, K, T, freq=2, vol=0.20, opt="cap",
                      curve=None, snapshot=None, curve_id="flat_rub") -> dict:
        """Cap/floor as an LMM Black caplet strip (M3b)."""
        from models.lmm import LMM
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)

        def engine():
            m = LMM(curve, start=0.0, end=T, freq=int(freq), vol=vol)
            return {"price": m.cap_black(K, opt, start=1, notional=notional)}

        return self._priced(
            model_id="lmm", calculation_type="lmm_cap_pricing", engine=engine,
            inputs={"notional": notional, "K": K, "T": T, "freq": int(freq),
                    "vol": vol, "opt": opt, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price LMM cap/floor")

    def price_bk_swaption(self, notional, K, T_option, T_swap, freq=2, a=0.1,
                          sigma=0.20, opt="payer", steps_per_year=24, curve=None,
                          snapshot=None, curve_id="flat_rub") -> dict:
        """European swaption under Black-Karasinski (lognormal short rate), tree (M3c)."""
        from models.black_karasinski import bk_swaption
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="bk", calculation_type="bk_swaption_pricing",
            engine=lambda: bk_swaption(curve, notional, K, T_option, T_swap,
                                       int(freq), a, sigma, opt, int(steps_per_year)),
            inputs={"notional": notional, "K": K, "T_option": T_option,
                    "T_swap": T_swap, "freq": int(freq), "a": a, "sigma": sigma,
                    "opt": opt, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price Black-Karasinski swaption")

    def price_cheyette_swaption(self, notional, K, T_option, T_swap, freq=2, a=0.1,
                                sigma=0.01, skew=0.0, opt="payer", n_sims=50_000,
                                steps=100, curve=None, snapshot=None,
                                curve_id="flat_rub") -> dict:
        """European swaption under Cheyette (quasi-Gaussian HJM), MC (M3c)."""
        from models.cheyette import cheyette_swaption
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="cheyette", calculation_type="cheyette_swaption_pricing",
            engine=lambda: cheyette_swaption(curve, notional, K, T_option, T_swap,
                                             int(freq), a, sigma, skew, opt,
                                             int(n_sims), int(steps)),
            inputs={"notional": notional, "K": K, "T_option": T_option,
                    "T_swap": T_swap, "freq": int(freq), "a": a, "sigma": sigma,
                    "skew": skew, "opt": opt, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price Cheyette swaption")

    def build_xccy_curve(self, fx_spot, tenors, basis_bps, freq=4,
                         dom_curve=None, for_curve=None, dom_curve_id="flat_rub",
                         for_curve_id="flat_usd", snapshot=None) -> dict:
        """Bootstrap a cross-currency basis discount curve and return its zero
        rates + CIP-implied FX forwards (M3c)."""
        from curves.xccy_curve import bootstrap_xccy_curve, implied_fx_forwards
        dom_curve, snapshot = self._resolve_curve(dom_curve, snapshot, dom_curve_id)
        if for_curve is None:
            from curves.yield_curve import YieldCurve
            for_curve = YieldCurve.flat(0.04, label=for_curve_id)
        try:
            xc = bootstrap_xccy_curve(dom_curve, for_curve, fx_spot, list(tenors),
                                      list(basis_bps), int(freq))
            fwds = implied_fx_forwards(dom_curve, xc, fx_spot, list(tenors))
            return {"errors": [], "model_id": "xccy_curve",
                    "tenors": list(tenors),
                    "discounts": [xc.discount(T) for T in tenors],
                    "zero_rates": [xc.rate(T) for T in tenors],
                    "fx_forwards": fwds}
        except Exception as exc:                       # noqa: BLE001
            return {"errors": [str(exc)], "model_id": "xccy_curve"}

    # ── Phase 3: numerical engines ────────────────────────────────────
    def price_american_option(self, S, K, T, r, sigma, q=0.0, opt="put",
                              model="pde", snapshot=None, *, N=None,
                              ns=None, nt=None, n_sims=None, steps=None,
                              seed=None) -> dict:
        """American option. model: pde | binomial | binomial_lr | trinomial | lsm
        | baw (Barone-Adesi-Whaley) | bjerksund_stensland (M6 analytic approx)."""
        if model in ("baw", "bjerksund_stensland"):
            from models.american_approx import baw, bjerksund_stensland
            fn = baw if model == "baw" else bjerksund_stensland
            return self._priced(
                model_id=model, calculation_type="american_option_pricing",
                engine=lambda: {"price": fn(S, K, T, r, sigma, q, opt)},
                inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q,
                        "opt": opt, "model": model},
                snapshot=snapshot, user_action="Price American option (analytic)")
        from instruments.vanilla import american
        model_id = {"pde": "pde_cn", "binomial": "binomial_crr",
                    "binomial_lr": "binomial_lr", "trinomial": "trinomial",
                    "lsm": "mc_lsm"}.get(model, model)
        return self._priced(
            model_id=model_id, calculation_type="american_option_pricing",
            engine=lambda: american(
                S, K, T, r, sigma, q, opt, model,
                N=N, ns=ns, nt=nt, n_sims=n_sims, steps=steps, seed=seed),
            inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q,
                    "opt": opt, "model": model, "N": N, "Ns": ns, "Nt": nt,
                    "n_sims": n_sims, "steps": steps, "seed": seed},
            snapshot=snapshot, user_action="Price American option")

    def price_vanilla_extra(self, model, S, K, T, r, sigma, q=0.0, opt="call",
                            snapshot=None, **kw) -> dict:
        """Vanilla/vol analytic extensions (gap batch 1). model: displaced_diffusion
        | cev | discrete_div_bsm | binomial_jr | binomial_tian | lognormal_mixture."""
        from models import vanilla_extra as VE
        engines = {
            "displaced_diffusion": lambda: VE.displaced_diffusion(S, K, T, r, sigma, kw.get("shift", 0.0), opt),
            "cev": lambda: VE.cev_price(S, K, T, r, sigma, kw.get("beta", 1.0), q, opt),
            "discrete_div_bsm": lambda: VE.discrete_dividend_bsm(S, K, T, r, sigma, kw.get("dividends", []), opt),
            "binomial_jr": lambda: VE.binomial_jarrow_rudd(S, K, T, r, sigma, q, opt, int(kw.get("N", 500)), kw.get("exercise", "european")),
            "binomial_tian": lambda: VE.binomial_tian(S, K, T, r, sigma, q, opt, int(kw.get("N", 500)), kw.get("exercise", "european")),
            "lognormal_mixture": lambda: VE.mixture_price(S, K, T, r, kw.get("sigma_list", [sigma]), kw.get("weights", [1.0]), q, opt),
        }
        if model not in engines:
            return {"errors": [f"unknown vanilla-extra model {model!r}"], "model_id": model}
        return self._priced(
            model_id=model, calculation_type="vanilla_extra_pricing",
            engine=lambda: {"price": engines[model]()},
            inputs={"model": model, "S": S, "K": K, "T": T, "r": r, "sigma": sigma,
                    "q": q, "opt": opt, **kw},
            snapshot=snapshot, user_action=f"Price {model}")

    def price_smm_swaption(self, notional, K, T_option, T_swap, freq=2, sigma=0.2,
                           shift=0.0, opt="payer", curve=None, snapshot=None,
                           curve_id="flat_rub") -> dict:
        """European swaption under the Swap Market Model (batch 4)."""
        from models.rates_market import smm_swaption
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="swap_market_model", calculation_type="smm_swaption_pricing",
            engine=lambda: smm_swaption(curve, notional, K, T_option, T_swap,
                                        int(freq), sigma, shift, opt),
            inputs={"notional": notional, "K": K, "T_option": T_option,
                    "T_swap": T_swap, "freq": int(freq), "sigma": sigma,
                    "shift": shift, "opt": opt},
            snapshot=snapshot, user_action="Price SMM swaption")

    def price_tarn(self, S0, K, T, freq, r, sigma, target, q=0.0, n_sims=100_000,
                   snapshot=None) -> dict:
        """Target accrual redemption note (batch 4)."""
        from models.exotics_extra import tarn
        return self._priced(
            model_id="tarn", calculation_type="tarn_pricing",
            engine=lambda: tarn(S0, K, T, int(freq), r, sigma, target, q, int(n_sims)),
            inputs={"S0": S0, "K": K, "T": T, "freq": int(freq), "r": r,
                    "sigma": sigma, "target": target},
            snapshot=snapshot, user_action="Price TARN")

    def price_accumulator(self, S0, K, barrier, T, freq, r, sigma, q=0.0, qty=1.0,
                          n_sims=100_000, snapshot=None) -> dict:
        """Up-and-out accumulator (batch 4)."""
        from models.exotics_extra import accumulator
        return self._priced(
            model_id="accumulator", calculation_type="accumulator_pricing",
            engine=lambda: accumulator(S0, K, barrier, T, int(freq), r, sigma, q, qty, int(n_sims)),
            inputs={"S0": S0, "K": K, "barrier": barrier, "T": T, "freq": int(freq),
                    "r": r, "sigma": sigma},
            snapshot=snapshot, user_action="Price accumulator")

    def price_vanna_volga(self, S, K, T, r_d, r_f, K_atm, sig_atm, K_put, sig_put,
                          K_call, sig_call, opt="call", snapshot=None) -> dict:
        """FX option at the Vanna-Volga implied vol from the 25Δ pillars (batch 3)."""
        from models.vanna_volga import vv_price
        return self._priced(
            model_id="vanna_volga", calculation_type="vanna_volga_pricing",
            engine=lambda: vv_price(S, K, T, r_d, r_f, K_atm, sig_atm, K_put, sig_put,
                                    K_call, sig_call, opt),
            inputs={"S": S, "K": K, "T": T, "r_d": r_d, "r_f": r_f, "opt": opt},
            snapshot=snapshot, user_action="Price FX option (Vanna-Volga)")

    def price_basket_copula(self, copula, pds, k=1, recovery=0.4, rho=0.3, df=5,
                            theta=1.0, n_sims=100_000, snapshot=None) -> dict:
        """kth-to-default basket under a t / Clayton copula (batch 3)."""
        from models.credit_portfolio import basket_mc_t, basket_mc_clayton
        mid = "t_copula" if copula == "t" else "clayton_copula"
        if copula == "t":
            engine = lambda: {"price": basket_mc_t(list(pds), rho, int(df), int(k),
                                                   recovery, int(n_sims))["kth_prob"]}
        else:
            engine = lambda: {"price": basket_mc_clayton(list(pds), theta, int(k),
                                                         recovery, int(n_sims))["kth_prob"]}
        return self._priced(
            model_id=mid, calculation_type="basket_copula_pricing", engine=engine,
            inputs={"copula": copula, "n_names": len(pds), "k": int(k), "rho": rho,
                    "df": df, "theta": theta},
            snapshot=snapshot, user_action=f"Price {copula}-copula basket")

    def price_carr_madan(self, model, S, K, T, r, sigma=0.2, q=0.0, opt="call",
                         snapshot=None, **kw) -> dict:
        """Carr-Madan FFT pricer (gap batch 2). model: bsm | heston."""
        from models.fourier import carr_madan_bsm, carr_madan_heston
        model = str(model).lower()
        inputs = {
            "model": model, "S": S, "K": K, "T": T, "r": r,
            "sigma": sigma, "q": q, "opt": opt, **kw,
        }
        if model not in {"bsm", "heston"}:
            return self._error_result(
                model_id="carr_madan",
                error=ValueError(f"unsupported Carr-Madan model {model!r}"),
                snapshot=snapshot,
                calculation_type="carr_madan_pricing",
                inputs=inputs,
            )
        eligibility = self.governance.get_engine_eligibility(
            "european_option", "carr_madan", {"cf_model": model}
        )
        metadata = self._eligibility_metadata(eligibility)
        try:
            self.governance.enforce_engine(
                "european_option", "carr_madan", {"cf_model": model},
                allow_analytics_lab=self.allow_analytics_lab,
                allow_non_production=self.allow_non_production_models,
            )
        except Exception as exc:
            with self.engine_context(metadata):
                return self._error_result(
                    model_id="carr_madan", error=exc, snapshot=snapshot,
                    calculation_type="carr_madan_pricing", inputs=inputs,
                )
        if model == "heston":
            engine = lambda: {"price": carr_madan_heston(
                S, K, T, r, q, kw.get("v0", 0.04), kw.get("kappa", 1.5),
                kw.get("theta", 0.04), kw.get("xi", 0.3),
                kw.get("rho", -0.6), opt)}
        else:
            engine = lambda: {"price": carr_madan_bsm(S, K, T, r, sigma, q, opt)}
        with self.engine_context(metadata):
            return self._priced(
                model_id="carr_madan", calculation_type="carr_madan_pricing",
                engine=engine, inputs=inputs, snapshot=snapshot,
                user_action="Price option (Carr-Madan FFT)")

    def price_qmc_option(self, S, K, T, r, sigma, q=0.0, opt="call",
                         kind="european", n=16384, m=12, snapshot=None) -> dict:
        """European or geometric-Asian option via Sobol QMC (M6)."""
        from models import qmc as Q
        if kind == "geometric_asian":
            engine = lambda: {"price": Q.geometric_asian_qmc(S, K, T, r, sigma, q, opt, m, int(n))}
        else:
            engine = lambda: {"price": Q.qmc_european(S, K, T, r, sigma, q, opt, int(n))}
        return self._priced(
            model_id="qmc", calculation_type="qmc_option_pricing", engine=engine,
            inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q,
                    "opt": opt, "kind": kind, "n": int(n)},
            snapshot=snapshot, user_action="Price option (QMC)")

    def price_heston_adi(self, S, K, T, r, q, v0, kappa, theta, sigma, rho,
                         opt="call", NS=160, Nv=80, Nt=120, snapshot=None) -> dict:
        """European Heston option via Douglas ADI with the Hout-Foulon v=0
        boundary (task-3; cross-check to the Heston CF)."""
        from models.adi import heston_adi
        return self._priced(
            model_id="heston_adi", calculation_type="heston_adi_pricing",
            engine=lambda: {"price": heston_adi(S, K, T, r, q, v0, kappa, theta,
                                                sigma, rho, opt, int(NS), int(Nv), int(Nt))},
            inputs={"S": S, "K": K, "T": T, "r": r, "q": q, "v0": v0, "kappa": kappa,
                    "theta": theta, "sigma": sigma, "rho": rho, "opt": opt},
            snapshot=snapshot, user_action="Price Heston option (ADI)")

    def calibrate_sabr_from_market(self, underlying, expiry=None, beta=0.5) -> dict:
        """Calibrate SABR (α,ρ,ν) to the LIVE FORTS option smile for `underlying`
        (real-data path: equity/index/commodity option chains from MOEX)."""
        from app.runtime import market_service, active_snapshot
        from models.heston import sabr_calibrate
        ms = market_service()
        sm = ms.get_option_smile(underlying, expiry, active_snapshot(ms))
        if not sm:
            return {"errors": [f"no live FORTS smile for {underlying!r}"], "model_id": "sabr"}
        cal = sabr_calibrate(sm["ivs"], sm["forward"], sm["strikes"], sm["T"], beta)
        return {**cal, "errors": [], "model_id": "sabr", "underlying": underlying,
                "expiry": sm["expiry"], "forward": sm["forward"], "n_strikes": len(sm["strikes"])}

    def fx_vanna_volga_from_market(self, asset, K, opt="call", expiry=None,
                                   r_d=0.0, r_f=0.0) -> dict:
        """Vanna-Volga FX vol/price at strike K from the LIVE 25Δ RR/BF smile
        (asset = Si/CNY). Real-data path closing the VV data gap."""
        from app.runtime import market_service, active_snapshot
        from models.vanna_volga import vv_implied_vol
        ms = market_service()
        rb = ms.get_fx_rr_bf(asset, expiry, active_snapshot(ms))
        if not rb:
            return {"errors": [f"no live FX smile for {asset!r}"], "model_id": "vanna_volga"}
        F, T = rb["forward"], rb["T"]
        iv = vv_implied_vol(F, K, T, r_d, r_f, F, rb["atm_vol"],
                            rb["k_25p"], rb["sig_25p"], rb["k_25c"], rb["sig_25c"])
        return {"errors": [], "model_id": "vanna_volga", "asset": asset,
                "forward": F, "atm_vol": rb["atm_vol"], "rr_25": rb["rr_25"],
                "bf_25": rb["bf_25"], "implied_vol": iv, "expiry": rb["expiry"]}

    def calibrate_commodity_from_market(self, asset, vol_proxy=0.25, r=0.05) -> dict:
        """Calibrate Schwartz-Smith to the LIVE MOEX-FORTS futures strip for
        `asset` (BR/GOLD/NG/...). Real-data path: pulls commodity_quotes via the
        market service. Commodity option vols are a documented data gap, so the
        vol term structure is fitted to a flat proxy (see
        MODEL_MARKET_DATA_REQUIREMENTS.md)."""
        from app.runtime import market_service, active_snapshot
        ms = market_service()
        curve = ms.get_commodity_curve(asset, active_snapshot(ms))
        if len(curve) < 3:
            return {"errors": [f"no live futures strip for {asset!r}"], "model_id": "schwartz_smith"}
        tenors = list(curve.keys())
        futures = list(curve.values())
        vt = tenors
        vm = [vol_proxy] * len(tenors)
        res = self.calibrate_commodity("schwartz_smith", tenors, futures, vt, vm,
                                       r=r, spot=futures[0])
        res["asset"] = asset
        res["n_futures"] = len(curve)
        return res

    def calibrate_commodity(self, model, tenors, futures, vol_tenors, vol_mkt,
                            r=0.05, spot=None) -> dict:
        """Calibrate a commodity model to a futures strip + ATM vols (task-3).
        model: 'schwartz_smith'."""
        from models.market_calibration import calibrate_schwartz_smith
        try:
            res = calibrate_schwartz_smith(tenors, futures, vol_tenors, vol_mkt, r, spot)
            res.pop("model", None)
            return {**res, "errors": [], "model_id": "schwartz_smith"}
        except Exception as exc:                       # noqa: BLE001
            return {"errors": [str(exc)], "model_id": "schwartz_smith"}

    def calibrate_base_correlation(self, pds, detachments, target_els,
                                   recovery=0.4) -> dict:
        """Bootstrap the CDO base-correlation curve from base-tranche ELs (task-3)."""
        from models.market_calibration import calibrate_base_correlation
        try:
            curve = calibrate_base_correlation(list(pds), list(detachments),
                                               list(target_els), recovery)
            return {"errors": [], "model_id": "gaussian_copula", "base_correlation": curve}
        except Exception as exc:                       # noqa: BLE001
            return {"errors": [str(exc)], "model_id": "gaussian_copula"}

    def calibrate_cheyette_skew(self, T_opt, T_swap, strikes, market_vols, a=0.1,
                                sigma=0.01, freq=2, curve=None, snapshot=None,
                                curve_id="flat_rub") -> dict:
        """Calibrate the Cheyette local-vol skew to a swaption smile (task-3)."""
        from models.rate_calibration import calibrate_cheyette_skew
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        try:
            res = calibrate_cheyette_skew(curve, a, sigma, T_opt, T_swap, list(strikes),
                                          list(market_vols), int(freq))
            return {**res, "errors": [], "model_id": "cheyette"}
        except Exception as exc:                       # noqa: BLE001
            return {"errors": [str(exc)], "model_id": "cheyette"}

    def price_two_asset_option(self, S1, S2, T, r, q1, q2, sigma1, sigma2, rho,
                               kind="exchange", strike=0.0, N1=80, N2=80, Nt=100,
                               snapshot=None) -> dict:
        """Two-asset European option via Douglas ADI (M6). kind: exchange | spread."""
        import numpy as _np
        from models.adi import two_asset_adi
        K = strike
        payoffs = {"exchange": lambda a, b: _np.maximum(a - b, 0.0),
                   "spread": lambda a, b: _np.maximum(a - b - K, 0.0)}
        payoff = payoffs.get(kind, payoffs["exchange"])
        return self._priced(
            model_id="two_asset_adi", calculation_type="two_asset_option_pricing",
            engine=lambda: {"price": two_asset_adi(payoff, S1, S2, T, r, q1, q2,
                                                   sigma1, sigma2, rho,
                                                   int(N1), int(N2), int(Nt))},
            inputs={"S1": S1, "S2": S2, "T": T, "r": r, "q1": q1, "q2": q2,
                    "sigma1": sigma1, "sigma2": sigma2, "rho": rho, "kind": kind,
                    "strike": strike},
            snapshot=snapshot, user_action="Price two-asset option (ADI)")

    def price_barrier_option_pde(self, S, K, H, T, r, sigma, q=0.0, opt="call",
                                 barrier_type="down-out", rebate=0.0,
                                 ns=None, nt=None, snapshot=None) -> dict:
        """Barrier option via the Crank-Nicolson PDE (cross-check to closed form)."""
        from models.pde import cn_barrier
        return self._priced(
            model_id="pde_cn", calculation_type="barrier_option_pde_pricing",
            engine=lambda: cn_barrier(S, K, H, T, r, sigma, q, opt, barrier_type,
                                      rebate, Ns=int(ns or 400), Nt=int(nt or 400)),
            inputs={"S": S, "K": K, "H": H, "T": T, "r": r, "sigma": sigma, "q": q,
                    "opt": opt, "barrier_type": barrier_type, "rebate": rebate,
                    "ns": ns, "nt": nt},
            snapshot=snapshot, user_action="Price barrier option (PDE)")

    def price_merton_option(self, S, K, T, r, sigma, q=0.0, lam=0.1, mu_j=-0.1,
                            delta_j=0.15, opt="call", snapshot=None) -> dict:
        """European option under Merton lognormal jump-diffusion."""
        from models.jump_diffusion import merton_price
        return self._priced(
            model_id="merton_jump", calculation_type="merton_option_pricing",
            engine=lambda: merton_price(S, K, T, r, sigma, q, lam, mu_j, delta_j, opt),
            inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q,
                    "lam": lam, "mu_j": mu_j, "delta_j": delta_j, "opt": opt},
            snapshot=snapshot, user_action="Price Merton jump option")

    def price_levy_option(self, model, S, K, T, r, sigma=0.0, q=0.0, opt="call",
                          snapshot=None, **params) -> dict:
        """
        European option under a Lévy/jump model via the Fourier COS method
        (M1): model ∈ {kou, variance_gamma, nig, cgmy, merton_cos}. Analytics Lab.
        """
        from models import levy as L
        engines = {
            "kou": lambda: L.kou_price(S, K, T, r, sigma, q,
                                       params.get("lam", 0.5), params.get("p", 0.4),
                                       params.get("eta1", 10.0), params.get("eta2", 5.0),
                                       opt, int(params.get("N", 256))),
            "variance_gamma": lambda: L.vg_price(S, K, T, r, sigma, q,
                                                 params.get("nu", 0.2), params.get("theta", -0.1),
                                                 opt, int(params.get("N", 256))),
            "nig": lambda: L.nig_price(S, K, T, r, params.get("alpha", 15.0),
                                       params.get("beta", -5.0), params.get("delta", 0.5),
                                       q, opt, int(params.get("N", 256))),
            "cgmy": lambda: L.cgmy_price(S, K, T, r, params.get("C", 0.1),
                                         params.get("G", 5.0), params.get("M", 5.0),
                                         params.get("Y", 0.8), q, opt, int(params.get("N", 512))),
            "merton_cos": lambda: L.merton_cos(S, K, T, r, sigma, q,
                                               params.get("lam", 0.3), params.get("mu_j", -0.1),
                                               params.get("delta_j", 0.15), opt,
                                               int(params.get("N", 256))),
        }
        if model not in engines:
            return self._error_result(model_id=model, error=ValueError(f"Unknown Lévy model {model}"),
                                      snapshot=snapshot, calculation_type="levy_option_pricing",
                                      inputs={"model": model})
        return self._priced(
            model_id=model, calculation_type="levy_option_pricing",
            engine=engines[model],
            inputs={"model": model, "S": S, "K": K, "T": T, "r": r, "sigma": sigma,
                    "q": q, "opt": opt, **params},
            snapshot=snapshot, user_action=f"Price {model} option (COS)")

    def price_rough_bergomi_option(self, S, K, T, r, q=0.0, H=0.1, eta=1.5,
                                   rho=-0.7, xi0=0.04, opt="call",
                                   n_paths=40_000, steps=100, snapshot=None) -> dict:
        """European option under rough Bergomi (MC); Analytics Lab (M2)."""
        from models.rough_vol import rough_bergomi_price
        return self._priced(
            model_id="rough_bergomi", calculation_type="rough_bergomi_pricing",
            engine=lambda: rough_bergomi_price(S, K, T, r, q, H, eta, rho, xi0,
                                               opt, int(n_paths), int(steps)),
            inputs={"S": S, "K": K, "T": T, "r": r, "q": q, "H": H, "eta": eta,
                    "rho": rho, "xi0": xi0, "opt": opt},
            snapshot=snapshot, user_action="Price rough Bergomi option")

    def price_heston_option(self, S, K, T, r, q, v0, kappa, theta, xi, rho,
                            opt="call", snapshot=None) -> dict:
        """European option under Heston (characteristic-function); Analytics Lab."""
        from models.heston import heston_price
        return self._priced(
            model_id="heston_cf", calculation_type="heston_option_pricing",
            engine=lambda: heston_price(S, K, T, r, q, v0, kappa, theta, xi, rho, opt),
            inputs={"S": S, "K": K, "T": T, "r": r, "q": q, "v0": v0,
                    "kappa": kappa, "theta": theta, "xi": xi, "rho": rho, "opt": opt},
            snapshot=snapshot, user_action="Price Heston option")

    def price_heston_mc_option(self, S, K, T, r, q, v0, kappa, theta, xi, rho,
                               opt="call", scheme="qe", n_sims=100_000,
                               steps=100, seed=42, snapshot=None) -> dict:
        """European Heston MC via explicit Euler or Andersen-QE solver."""
        import numpy as np

        from models.monte_carlo import heston_mc_price

        scheme = str(scheme).lower()
        if scheme not in {"euler", "qe"}:
            return self._error_result(
                model_id="mc_heston_qe",
                error=ValueError(f"Unknown Heston MC scheme {scheme!r}"),
                snapshot=snapshot,
                calculation_type="heston_mc_option_pricing",
                inputs={"scheme": scheme},
            )
        model_id = "mc_heston_qe" if scheme == "qe" else "mc_heston"
        n_sims = int(n_sims)
        if scheme == "euler" and n_sims % 2:
            n_sims += 1
        payoff = (
            (lambda paths: np.maximum(paths[:, -1] - K, 0.0))
            if opt == "call"
            else (lambda paths: np.maximum(K - paths[:, -1], 0.0))
        )
        return self._priced(
            model_id=model_id,
            calculation_type="heston_mc_option_pricing",
            engine=lambda: heston_mc_price(
                payoff, S, v0, r, q, kappa, theta, xi, rho, T,
                int(steps), n_sims, int(seed), scheme,
            ),
            inputs={
                "S": S, "K": K, "T": T, "r": r, "q": q, "v0": v0,
                "kappa": kappa, "theta": theta, "xi": xi, "rho": rho,
                "opt": opt, "scheme": scheme, "n_sims": n_sims,
                "steps": int(steps), "seed": int(seed),
            },
            snapshot=snapshot,
            user_action=f"Price Heston option ({scheme.upper()} Monte Carlo)",
        )

    def price_bates_option(self, S, K, T, r, q, v0, kappa, theta, xi, rho,
                           lam=0.1, mu_j=-0.1, delta_j=0.15, opt="call",
                           snapshot=None) -> dict:
        """European option under Bates (Heston + jumps); Analytics Lab model."""
        from models.jump_diffusion import bates_price
        return self._priced(
            model_id="bates", calculation_type="bates_option_pricing",
            engine=lambda: bates_price(S, K, T, r, q, v0, kappa, theta, xi, rho,
                                       lam, mu_j, delta_j, opt),
            inputs={"S": S, "K": K, "T": T, "r": r, "q": q, "v0": v0,
                    "kappa": kappa, "theta": theta, "xi": xi, "rho": rho,
                    "lam": lam, "mu_j": mu_j, "delta_j": delta_j, "opt": opt},
            snapshot=snapshot, user_action="Price Bates option")

    # ── Phase 2: new instrument classes ───────────────────────────────
    def price_ndf(self, S, K, T, r_d, r_f, notional_fgn=1_000_000,
                  settle="foreign", position="long", snapshot=None) -> dict:
        """Non-deliverable forward (cash-settled FX forward)."""
        from instruments.fx import ndf
        return self._priced(
            model_id="ndf", calculation_type="ndf_pricing", value_key="npv",
            engine=lambda: ndf(S, K, T, r_d, r_f, notional_fgn, settle, position),
            inputs={"S": S, "K": K, "T": T, "r_d": r_d, "r_f": r_f,
                    "notional_fgn": notional_fgn, "settle": settle, "position": position},
            snapshot=snapshot, user_action="Price NDF")

    def price_xccy_swap(self, notional_dom, S, T, freq, basis_spread=0.0,
                        leg_dom="float", leg_fgn="float",
                        fixed_rate_dom=0.0, fixed_rate_fgn=0.0,
                        disc_dom=None, disc_fgn=None, proj_dom=None, proj_fgn=None,
                        dom_curve_id="cbr_key_demo", fgn_rate=0.05,
                        exchange_notionals=True, receive_domestic=True,
                        snapshot=None) -> dict:
        """Cross-currency swap; foreign curve defaults to a flat curve at fgn_rate."""
        from instruments.xccy import xccy_swap
        disc_dom, snapshot = self._resolve_curve(disc_dom, snapshot, dom_curve_id)
        if disc_fgn is None:
            disc_fgn = self.market_data.flat_curve(fgn_rate, label="Foreign flat")
        return self._priced(
            model_id="xccy_swap", calculation_type="xccy_swap_pricing", value_key="npv",
            engine=lambda: xccy_swap(notional_dom, S, T, freq, disc_dom, disc_fgn,
                                     proj_dom, proj_fgn, basis_spread,
                                     leg_dom, leg_fgn, fixed_rate_dom, fixed_rate_fgn,
                                     exchange_notionals, receive_domestic),
            inputs={"notional_dom": notional_dom, "S": S, "T": T, "freq": freq,
                    "basis_spread": basis_spread, "leg_dom": leg_dom, "leg_fgn": leg_fgn,
                    "fixed_rate_dom": fixed_rate_dom, "fixed_rate_fgn": fixed_rate_fgn,
                    "dom_curve_id": dom_curve_id, "fgn_rate": fgn_rate,
                    "exchange_notionals": exchange_notionals,
                    "receive_domestic": receive_domestic},
            snapshot=snapshot, user_action="Price XCCY swap")

    def price_zc_inflation_swap(self, notional, K, T, pay_fixed=True,
                                nominal_curve=None, real_curve=None,
                                nominal_curve_id="ofz_demo",
                                real_curve_id="ofzin_real_demo", snapshot=None) -> dict:
        """Zero-coupon inflation swap off the (nominal, real) curve pair."""
        from instruments.inflation_swaps import zc_inflation_swap
        nominal_curve, snapshot = self._resolve_curve(nominal_curve, snapshot, nominal_curve_id)
        real_curve, snapshot = self._resolve_curve(real_curve, snapshot, real_curve_id)
        return self._priced(
            model_id="inflation_swap", calculation_type="zciis_pricing", value_key="npv",
            engine=lambda: zc_inflation_swap(notional, K, T, nominal_curve, real_curve, pay_fixed),
            inputs={"notional": notional, "K": K, "T": T, "pay_fixed": pay_fixed,
                    "nominal_curve_id": nominal_curve_id, "real_curve_id": real_curve_id},
            snapshot=snapshot, user_action="Price ZC inflation swap")

    def price_yoy_inflation_swap(self, notional, K, T, freq=1, pay_fixed=True,
                                 nominal_curve=None, real_curve=None,
                                 nominal_curve_id="ofz_demo",
                                 real_curve_id="ofzin_real_demo", snapshot=None) -> dict:
        """Year-on-year inflation swap (no YoY convexity adjustment)."""
        from instruments.inflation_swaps import yoy_inflation_swap
        nominal_curve, snapshot = self._resolve_curve(nominal_curve, snapshot, nominal_curve_id)
        real_curve, snapshot = self._resolve_curve(real_curve, snapshot, real_curve_id)
        return self._priced(
            model_id="inflation_swap", calculation_type="yoyiis_pricing", value_key="npv",
            engine=lambda: yoy_inflation_swap(notional, K, T, int(freq),
                                              nominal_curve, real_curve, pay_fixed),
            inputs={"notional": notional, "K": K, "T": T, "freq": int(freq),
                    "pay_fixed": pay_fixed, "nominal_curve_id": nominal_curve_id,
                    "real_curve_id": real_curve_id},
            snapshot=snapshot, user_action="Price YoY inflation swap")

    def price_bermudan_swaption(self, notional, K, exercise_dates, T_end, freq=2,
                                kappa=0.1, sigma=0.012, opt="payer", steps=200,
                                curve=None, snapshot=None, curve_id="flat_rub",
                                calibrate_to_cube=False,
                                cube_id="swaption_cube_demo") -> dict:
        """
        Bermudan swaption on the Hull-White trinomial tree. With
        calibrate_to_cube=True, (kappa, sigma) are first calibrated to the
        cube's co-terminal ATM swaptions (Stage A) and the manual kappa/sigma
        inputs are ignored.
        """
        from models.short_rate import bermudan_swaption_calibrated, bermudan_swaption_hw
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        if calibrate_to_cube:
            snapshot = snapshot or self.market_data.demo_snapshot()
            cube = self.market_data.get_swaption_cube(cube_id, snapshot)
            engine = lambda: bermudan_swaption_calibrated(
                notional, K, list(exercise_dates), T_end, int(freq), curve, cube,
                opt, steps)
        else:
            engine = lambda: bermudan_swaption_hw(
                notional, K, list(exercise_dates), T_end, int(freq), curve,
                kappa, sigma, opt, steps)
        return self._priced(
            model_id="bermudan_swaption", calculation_type="bermudan_swaption_pricing",
            engine=engine,
            inputs={"notional": notional, "K": K, "exercise_dates": list(exercise_dates),
                    "T_end": T_end, "freq": int(freq), "kappa": kappa, "sigma": sigma,
                    "opt": opt, "steps": steps, "curve_id": curve_id,
                    "calibrate_to_cube": calibrate_to_cube,
                    "cube_id": cube_id if calibrate_to_cube else None},
            snapshot=snapshot, user_action="Price Bermudan swaption")

    def price_cms_swap(self, notional, K, T, freq, swap_tenor, sigma=None,
                       pay_fixed=True, curve=None, snapshot=None,
                       curve_id="flat_rub", cube_id=None) -> dict:
        """
        CMS swap with per-fixing convexity + timing adjustments. sigma may be
        omitted when cube_id names a SwaptionCube: each fixing then reads its
        own (expiry, tenor) ATM node vol (Stage A).
        """
        from instruments.fixed_income import cms_swap
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        try:
            if sigma is None:
                if cube_id is None:
                    raise ValueError("Provide sigma or cube_id")
                snapshot = snapshot or self.market_data.demo_snapshot()
                cube = self.market_data.get_swaption_cube(cube_id, snapshot)
                sigma_input = cube.atm_vol
            else:
                sigma_input = sigma
        except Exception as exc:
            return self._error_result(model_id="cms_swap", error=exc, snapshot=snapshot,
                                      calculation_type="cms_swap_pricing",
                                      inputs={"cube_id": cube_id})
        return self._priced(
            model_id="cms_swap", calculation_type="cms_swap_pricing", value_key="npv",
            engine=lambda: cms_swap(notional, K, T, int(freq), swap_tenor, curve,
                                    sigma_input, pay_fixed),
            inputs={"notional": notional, "K": K, "T": T, "freq": int(freq),
                    "swap_tenor": swap_tenor,
                    "sigma": sigma if sigma is not None else f"cube:{cube_id}",
                    "pay_fixed": pay_fixed, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price CMS swap")

    def price_convertible_bond(self, S, sigma, q, face, coupon, freq, T, conv_ratio,
                               credit_spread=0.02, call_price=None, call_start=0.0,
                               put_price=None, put_start=0.0, N=400,
                               curve=None, snapshot=None, curve_id="flat_rub") -> dict:
        """Convertible bond via Tsiveriotis-Fernandes on a CRR tree."""
        from instruments.convertible import convertible_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="convertible_bond", calculation_type="convertible_bond_pricing",
            engine=lambda: convertible_bond(S, sigma, q, face, coupon, int(freq), T,
                                            conv_ratio, curve, credit_spread,
                                            call_price, call_start, put_price, put_start,
                                            int(N)),
            inputs={"S": S, "sigma": sigma, "q": q, "face": face, "coupon": coupon,
                    "freq": int(freq), "T": T, "conv_ratio": conv_ratio,
                    "credit_spread": credit_spread, "call_price": call_price,
                    "call_start": call_start, "put_price": put_price,
                    "put_start": put_start, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price convertible bond")

    def price_fx_option_smile(
        self,
        S: float,
        K: float,
        T: float,
        r_d: float,
        r_f: float,
        atm: float | None = None,
        rr: float | None = None,
        bf: float | None = None,
        notional: float = 1_000_000,
        opt: str = "call",
        snapshot: MarketDataSnapshot | None = None,
        vol_surface_id: str | None = None,
    ) -> dict:
        """
        FX option with a Malz smile-consistent vol. Quotes (atm, rr, bf) may be
        passed directly or resolved from a snapshot surface of type 'rr_bf'
        (e.g. 'fx_usdrub_demo').
        """
        from instruments.fx import fx_option_smile

        def engine():
            nonlocal atm, rr, bf
            if atm is None:
                if vol_surface_id is None:
                    raise ValueError("Provide (atm, rr, bf) or vol_surface_id")
                surface = self.market_data.get_vol_surface(
                    vol_surface_id, snapshot or self.market_data.demo_snapshot())
                if not (isinstance(surface, dict) and surface.get("type") == "rr_bf"):
                    raise ValueError(f"Surface {vol_surface_id} is not an rr_bf quote set")
                atm, rr, bf = surface["atm"], surface["rr"], surface["bf"]
            return fx_option_smile(S, K, T, r_d, r_f, atm, rr, bf, notional, opt)

        return self._priced(
            model_id="fx_smile", calculation_type="fx_option_smile_pricing",
            engine=engine,
            inputs={"S": S, "K": K, "T": T, "r_d": r_d, "r_f": r_f, "atm": atm,
                    "rr": rr, "bf": bf, "notional": notional, "opt": opt,
                    "vol_surface_id": vol_surface_id},
            snapshot=snapshot, user_action="Price FX option with smile")

    def price_variance_swap(self, S, T, r, sigma, q=0.0, skew=0.0,
                            vega_notional=100_000, n_strikes=25, width=0.5,
                            snapshot=None) -> dict:
        """Variance swap fair strike via Demeterfi log-contract replication.

        The OTM option strip is synthesized from a quadratic smile
        σ(K) = σ·(1 + skew·ln(K/F)) so a flat smile (skew=0) recovers σ²
        exactly; skew≠0 shows the replication picking up the smile premium.
        """
        import numpy as np
        from instruments.variance_swaps import variance_swap_fair_strike
        from models.black_scholes import bsm

        def engine():
            F = S * np.exp((r - q) * T)
            Ks = np.linspace(F * (1 - width), F * (1 + width), int(n_strikes) * 2 + 1)
            puts, calls = [], []
            for K in Ks:
                sig_k = max(sigma * (1.0 + skew * np.log(K / F)), 1e-4)
                if K < F:
                    puts.append((float(K), float(bsm(S, K, T, r, sig_k, q, "put").price)))
                elif K > F:
                    calls.append((float(K), float(bsm(S, K, T, r, sig_k, q, "call").price)))
            raw = variance_swap_fair_strike(r, q, T, puts, calls, S, F)
            raw["price"] = raw["vol_strike"] * 100          # headline in vol points
            raw["vega_notional"] = vega_notional
            raw["strip_strikes"] = len(puts) + len(calls)
            return raw

        return self._priced(
            model_id="variance_swap", calculation_type="variance_swap_pricing",
            engine=engine,
            inputs={"S": S, "T": T, "r": r, "sigma": sigma, "q": q, "skew": skew,
                    "n_strikes": n_strikes, "width": width},
            snapshot=snapshot, user_action="Price variance swap")

    def price_rainbow_option(self, assets, T, r, sigmas, corr, style="best_of_cash",
                             cash=0.0, q_list=None, snapshot=None) -> dict:
        """Rainbow (best-of / worst-of) option: Stulz exact for 2 assets, MC for n>2."""
        import numpy as np
        from instruments.multi_asset import best_of_assets_cash, worst_of_assets
        corr_m = np.array(corr, dtype=float)
        if style == "worst_of":
            engine = lambda: worst_of_assets(list(assets), T, r, list(sigmas), corr_m, q_list)
        else:
            engine = lambda: best_of_assets_cash(list(assets), cash, T, r, list(sigmas),
                                                 corr_m, q_list)
        return self._priced(
            model_id="multi_asset", calculation_type="rainbow_option_pricing",
            engine=engine,
            inputs={"assets": assets, "T": T, "r": r, "sigmas": sigmas,
                    "style": style, "cash": cash},
            snapshot=snapshot, user_action="Price rainbow option")

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
