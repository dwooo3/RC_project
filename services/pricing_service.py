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
        sigma: float | None = None,
        q: float = 0.0,
        opt: str = "call",
        model: str = "bsm",
        snapshot: MarketDataSnapshot | None = None,
        vol_surface_id: str | None = None,
    ) -> dict:
        """
        Price a vanilla option. sigma may be omitted when vol_surface_id names a
        surface in the market snapshot — the strike/tenor vol is then resolved
        from the surface (Phase 1: surface-aware pricing).
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
                sigma, vol_warning = self._vol_from_surface(surface, K, T)
                if vol_warning:
                    vol_warnings.append(vol_warning)
            raw = european(S, K, T, r, sigma, q, opt, model)
            if vol_surface_id is not None and isinstance(raw, dict):
                raw["vol_surface_id"] = vol_surface_id
                raw["sigma_used"] = sigma
            inputs = {"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q, "opt": opt,
                      "model": model, "vol_surface_id": vol_surface_id}
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
    def _vol_from_surface(surface, K: float, T: float):
        """Resolve a vol from a snapshot surface object (VolSurface | dict)."""
        from risk.vol_surface import VolSurface
        if isinstance(surface, VolSurface):
            return surface.get_vol(K, T), None
        if isinstance(surface, dict):
            if surface.get("type") == "flat":
                return float(surface["vol"]), None
            if surface.get("median_vol") is not None:
                return (float(surface["median_vol"]),
                        "Vol surface has no strike/tenor interpolation; using median vol.")
        raise ValueError(f"Unsupported vol surface object: {type(surface).__name__}")

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

        def _engine():
            constituents, corr = self.market_data.basket_market_inputs(specs, T)
            return basket_note(
                constituents, r, T, corr,
                principal_protection=principal_protection,
                guaranteed_coupon=guaranteed_coupon, coupon_freq=int(coupon_freq),
                participation=participation, cap=cap, basket_type=basket_type,
                face=face, n_sims=int(n_sims), steps=int(steps))

        return self._priced(
            model_id="structured_basket_note", calculation_type="basket_note_pricing",
            engine=_engine,
            inputs={"specs": specs, "r": r, "T": T,
                    "principal_protection": principal_protection,
                    "guaranteed_coupon": guaranteed_coupon, "coupon_freq": int(coupon_freq),
                    "participation": participation, "cap": cap,
                    "basket_type": basket_type, "face": face, "n_sims": int(n_sims)},
            snapshot=snapshot, user_action="Price basket structured note")

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
        """Structural default model (M7). model: merton | black_cox."""
        from models.structural_credit import merton, black_cox
        mid = "merton_structural" if model == "merton" else "black_cox"

        def engine():
            if model == "black_cox":
                res = black_cox(V0, D, T, r, sigma_V, barrier)
                return {"price": res["pd"], **res}
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
                                rho=0.3, **params) -> dict:
        """Futures term structure F(0,T) under SS/GS (M5)."""
        from models.commodity import SchwartzSmith, GibsonSchwartz, commodity_futures_curve
        try:
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
            return {"errors": [], "model_id": model,
                    "curve": commodity_futures_curve(m, tenors)}
        except Exception as exc:                       # noqa: BLE001
            return {"errors": [str(exc)], "model_id": model}

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
                              model="pde", snapshot=None) -> dict:
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
            engine=lambda: american(S, K, T, r, sigma, q, opt, model),
            inputs={"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "q": q,
                    "opt": opt, "model": model},
            snapshot=snapshot, user_action="Price American option")

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
            model_id="adi", calculation_type="two_asset_option_pricing",
            engine=lambda: {"price": two_asset_adi(payoff, S1, S2, T, r, q1, q2,
                                                   sigma1, sigma2, rho,
                                                   int(N1), int(N2), int(Nt))},
            inputs={"S1": S1, "S2": S2, "T": T, "r": r, "q1": q1, "q2": q2,
                    "sigma1": sigma1, "sigma2": sigma2, "rho": rho, "kind": kind,
                    "strike": strike},
            snapshot=snapshot, user_action="Price two-asset option (ADI)")

    def price_barrier_option_pde(self, S, K, H, T, r, sigma, q=0.0, opt="call",
                                 barrier_type="down-out", rebate=0.0,
                                 snapshot=None) -> dict:
        """Barrier option via the Crank-Nicolson PDE (cross-check to closed form)."""
        from models.pde import cn_barrier
        return self._priced(
            model_id="pde_cn", calculation_type="barrier_option_pde_pricing",
            engine=lambda: cn_barrier(S, K, H, T, r, sigma, q, opt, barrier_type, rebate),
            inputs={"S": S, "K": K, "H": H, "T": T, "r": r, "sigma": sigma, "q": q,
                    "opt": opt, "barrier_type": barrier_type, "rebate": rebate},
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
