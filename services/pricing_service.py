"""Pricing service entry points.

The service keeps existing pricing engines intact and wraps them with governance,
market-data metadata, warnings, and structured errors.
"""

from typing import Any

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


class PricingService:
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
        calculation_type: str = "pricing",
        inputs: Any = None,
        user_action: str = "PricingService calculation",
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
            inputs = {"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt, "model": model}
            return self._result(
                value=raw.get("price"),
                model_id=model_id,
                raw=raw,
                snapshot=snapshot,
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

    # ── Rates (curve-based) ───────────────────────────────────────────
    def price_frn(self, face, spread, T, freq, curve=None, snapshot=None,
                  curve_id="flat_rub") -> dict:
        """Floating-rate note through the FRN engine (curve from snapshot if not given)."""
        from instruments.fixed_income import frn
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="frn", calculation_type="frn_pricing",
            engine=lambda: frn(face, spread, T, freq, curve),
            inputs={"face": face, "spread": spread, "T": T, "freq": freq, "curve_id": curve_id},
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

    def price_amortizing_bond(self, face, coupon, T, freq, amort_type="linear",
                              curve=None, snapshot=None, curve_id="flat_rub") -> dict:
        from instruments.fixed_income import amortizing_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="amortizing_bond", calculation_type="amortizing_bond_pricing",
            engine=lambda: amortizing_bond(face, coupon, T, int(freq), curve, amort_type),
            inputs={"face": face, "coupon": coupon, "T": T, "freq": int(freq),
                    "amort_type": amort_type, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price amortizing bond")

    def price_step_bond(self, face, coupon1, coupon2, switch_year, T, freq,
                        curve=None, snapshot=None, curve_id="flat_rub") -> dict:
        from instruments.fixed_income import step_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        steps = [(0.0, coupon1), (switch_year, coupon2)]
        return self._priced(
            model_id="step_bond", calculation_type="step_bond_pricing",
            engine=lambda: step_bond(face, steps, T, int(freq), curve),
            inputs={"face": face, "coupon1": coupon1, "coupon2": coupon2,
                    "switch_year": switch_year, "T": T, "freq": int(freq), "curve_id": curve_id},
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
                                    current_cpi=100.0, inflation_rate=0.04, curve=None,
                                    snapshot=None, curve_id="flat_rub") -> dict:
        from instruments.fixed_income import inflation_linked_bond
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="inflation_linked_bond", calculation_type="inflation_linked_bond_pricing",
            engine=lambda: inflation_linked_bond(face, real_coupon, T, int(freq), curve,
                                                 base_cpi, current_cpi, inflation_rate),
            inputs={"face": face, "real_coupon": real_coupon, "T": T, "freq": int(freq),
                    "base_cpi": base_cpi, "current_cpi": current_cpi,
                    "inflation_rate": inflation_rate, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price inflation-linked bond")

    def price_fra(self, notional, K, T1, T2, curve=None, snapshot=None,
                  curve_id="flat_rub") -> dict:
        """Forward Rate Agreement NPV from the discount curve."""
        from instruments.fixed_income import fra
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="fra", calculation_type="fra_pricing", value_key="npv",
            engine=lambda: fra(notional, K, T1, T2, curve),
            inputs={"notional": notional, "K": K, "T1": T1, "T2": T2, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price FRA")

    def price_cap_floor(self, notional, K, T, freq, vol, opt="cap", curve=None,
                        snapshot=None, curve_id="flat_rub") -> dict:
        """Cap/Floor as a strip of Black-76 caplets/floorlets."""
        from instruments.fixed_income import cap_floor
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="capfloor", calculation_type="cap_floor_pricing",
            engine=lambda: cap_floor(notional, K, T, freq, curve, vol, opt),
            inputs={"notional": notional, "K": K, "T": T, "freq": freq, "vol": vol,
                    "opt": opt, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price cap/floor")

    def price_swaption(self, notional, K, T_option, T_swap, freq, sigma, opt="payer",
                       curve=None, snapshot=None, curve_id="flat_rub") -> dict:
        """European swaption via Black-76 on the forward swap rate."""
        from instruments.fixed_income import swaption
        curve, snapshot = self._resolve_curve(curve, snapshot, curve_id)
        return self._priced(
            model_id="swaption", calculation_type="swaption_pricing",
            engine=lambda: swaption(notional, K, T_option, T_swap, freq, curve, sigma, opt),
            inputs={"notional": notional, "K": K, "T_option": T_option, "T_swap": T_swap,
                    "freq": freq, "sigma": sigma, "opt": opt, "curve_id": curve_id},
            snapshot=snapshot, user_action="Price swaption")

    # ── Credit ────────────────────────────────────────────────────────
    def price_cds(self, notional, spread, T, freq, hazard, r, recovery=0.4,
                  buy_protection=True, snapshot=None) -> dict:
        """Credit default swap NPV / fair spread."""
        from instruments.credit import cds
        return self._priced(
            model_id="cds", calculation_type="cds_pricing", value_key="npv",
            engine=lambda: cds(notional, spread, T, freq, hazard, r, recovery, buy_protection),
            inputs={"notional": notional, "spread": spread, "T": T, "freq": freq,
                    "hazard": hazard, "r": r, "recovery": recovery,
                    "buy_protection": buy_protection},
            snapshot=snapshot, user_action="Price CDS")

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
    ) -> dict:
        """Price an IRS through the existing single-curve engine."""
        from instruments.fixed_income import irs

        try:
            self._enforce_model("irs")
            if curve is None:
                snapshot = snapshot or self.market_data.demo_snapshot()
                curve = self.market_data.get_curve(curve_id, snapshot)
            raw = irs(notional, fixed_rate, T, freq, curve, pay_fixed)
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
