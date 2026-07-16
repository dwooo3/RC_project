"""QW1 product-qualified engine eligibility.

Workstation selectors such as ``pde_cn`` and ``adi`` are not globally unique.
This module resolves each ``(product, selector, runtime variant)`` into exact
model/solver definitions and owns the production/research publication decision.
It does not import the workstation catalogue, avoiding a models -> API cycle.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Mapping

from domain.model_governance import DefinitionRef, EngineEligibility
from models import registry
from models.quant_definitions import (
    COMPONENT_PUBLICATIONS,
    DEFINITION_VERSION,
    EMBEDDED_SOLVER_BY_COMPONENT,
    MODEL_COMPONENT_TO_DEFINITION,
    MODEL_DEFINITIONS,
    SOLVER_DEFINITIONS,
    SOLVER_EVIDENCE,
)
from models.taxonomy import ComponentKind, classify


ENGINE_ELIGIBILITY_VERSION = "1.0.0"
WORKSTATION_PARAMETER_SCHEMA_VERSION = "1.0.0"
LEGACY_TRANSITION_POLICY_REF = "QW1-LEGACY-TRANSITION-2026-07-15"
LEGACY_TRANSITION_EXPIRES_ON = date(2027, 1, 31)


_NUMERICAL_MODEL_BINDINGS = {
    "amc": "short_rate_family",
    "binomial_crr": "black_scholes_merton",
    "binomial_jr": "black_scholes_merton",
    "binomial_lr": "black_scholes_merton",
    "binomial_tian": "black_scholes_merton",
    "heston_adi": "heston",
    "local_vol_mc": "dupire_local_vol",
    "mc_gbm": "black_scholes_merton",
    "mc_heston": "heston",
    "mc_heston_qe": "heston",
    "mc_lsm": "black_scholes_merton",
    "merton_cos": "merton_jump_diffusion",
    "pde_cn": "black_scholes_merton",
    "qmc": "black_scholes_merton",
    "trinomial": "black_scholes_merton",
    "two_asset_adi": "two_asset_lognormal",
}


_PRODUCT_MODEL_BINDINGS = {
    # Equity and FX option primitives.
    "european_option": "black_scholes_merton",
    "american_option": "black_scholes_merton",
    "barrier_option": "black_scholes_merton",
    "asian_option": "black_scholes_merton",
    "digital_option": "black_scholes_merton",
    "lookback_option": "black_scholes_merton",
    "variance_swap": "black_scholes_merton",
    "equity_forward": "black_scholes_merton",
    "equity_swap": "black_scholes_merton",
    "dividend_swap": "black_scholes_merton",
    "equity_future": "black_scholes_merton",
    "warrant": "black_scholes_merton",
    # Deterministic curve/cash-flow products.
    "term_deposit": "deterministic_cashflow",
    "fra": "deterministic_cashflow",
    "irs": "deterministic_cashflow",
    "cap_floor": "deterministic_cashflow",
    "swaption": "deterministic_cashflow",
    "bermudan_swaption": "deterministic_cashflow",
    "cms_swap": "deterministic_cashflow",
    "stir_future": "deterministic_cashflow",
    "bond_future": "deterministic_cashflow",
    # FX carry / smile.
    "fx_forward": "deterministic_fx_carry",
    "ndf": "deterministic_fx_carry",
    "fx_option": "garman_kohlhagen",
    "fx_barrier": "garman_kohlhagen",
    "fx_digital": "garman_kohlhagen",
    "fx_asian": "garman_kohlhagen",
    "fx_lookback": "garman_kohlhagen",
    "xccy_swap": "deterministic_fx_carry",
    # Credit and inflation.
    "cds_index": "reduced_form_credit",
    "cds_index_option": "reduced_form_credit",
    "asset_swap": "reduced_form_credit",
    "cds": "reduced_form_credit",
    "risky_bond": "reduced_form_credit",
    "zciis": "deterministic_inflation_carry",
    "yoyiis": "deterministic_inflation_carry",
    # Hybrid/basket payoffs.
    "spread_option": "correlated_gbm",
    "two_asset_option": "two_asset_lognormal",
    "basket_option": "correlated_gbm",
    "rainbow_option": "correlated_gbm",
    "autocall": "correlated_gbm",
    "multi_asset_autocall": "correlated_gbm",
    "basket_note": "correlated_gbm",
    "tarn": "correlated_gbm",
    "accumulator": "correlated_gbm",
    "convertible": "equity_credit_hybrid",
}


def _model_definition_id(product_id: str, component_id: str,
                         params: Mapping[str, object]) -> tuple[str, str]:
    if component_id == "carr_madan":
        variant = str(params.get("cf_model") or "bsm").lower()
        if variant not in {"bsm", "heston"}:
            raise ValueError(f"unsupported Carr-Madan cf_model {variant!r}")
        return ("heston" if variant == "heston" else "black_scholes_merton", variant)

    taxonomy = classify(component_id)
    kind = taxonomy["component_kind"]
    if kind in {ComponentKind.STOCHASTIC_MODEL.value, ComponentKind.MARKET_MODEL.value}:
        return MODEL_COMPONENT_TO_DEFINITION[component_id], "default"
    if kind == ComponentKind.SMILE_PARAMETERIZATION.value:
        return "garman_kohlhagen", "default"
    if kind == ComponentKind.NUMERICAL_SOLVER.value:
        model_id = _NUMERICAL_MODEL_BINDINGS.get(component_id)
        if model_id is None:
            raise ValueError(f"solver {component_id!r} has no model binding")
        return model_id, "default"
    model_id = _PRODUCT_MODEL_BINDINGS.get(product_id)
    if model_id is None:
        raise ValueError(
            f"product {product_id!r} has no explicit model definition binding"
        )
    return model_id, "default"


def _solver_definition_id(component_id: str) -> str:
    taxonomy = classify(component_id)
    if taxonomy["component_kind"] == ComponentKind.NUMERICAL_SOLVER.value:
        return component_id
    try:
        return EMBEDDED_SOLVER_BY_COMPONENT[component_id]
    except KeyError as exc:
        raise ValueError(
            f"component {component_id!r} has no implementation-qualified "
            f"solver binding for method {taxonomy['method']!r}"
        ) from exc


def _engine_ref_id(product_id: str, selector_id: str, runtime_variant: str) -> str:
    base = f"{product_id}:{selector_id}"
    return f"{base}:{runtime_variant}" if selector_id == "carr_madan" else base


def build_engine_eligibility(
    *,
    product_id: str,
    selector_id: str,
    implementation_component_id: str,
    params: Mapping[str, object] | None = None,
    required_market_dependencies: Iterable[str] = (),
    supported_product_features: Iterable[str] = (),
) -> EngineEligibility:
    """Resolve one workstation engine to exact model/solver definitions."""
    params = params or {}
    component = registry.get(implementation_component_id)
    if component["status"] == registry.ModelStatus.PLACEHOLDER:
        raise ValueError(f"unknown implementation component {implementation_component_id!r}")
    component_id = component["canonical_component_id"]
    taxonomy = classify(component_id)
    kind = taxonomy["component_kind"]
    if kind in {
        ComponentKind.RISK_METHODOLOGY.value,
        ComponentKind.MARKET_INFRASTRUCTURE.value,
        ComponentKind.CALIBRATION_METHOD.value,
    }:
        raise ValueError(
            f"component {component_id!r} of kind {kind!r} cannot be a pricing engine"
        )

    model_id, runtime_variant = _model_definition_id(product_id, component_id, params)
    solver_id = _solver_definition_id(component_id)
    model = MODEL_DEFINITIONS.get(model_id)
    solver = SOLVER_DEFINITIONS.get(solver_id)
    if model is None:
        raise ValueError(f"engine references unknown model definition {model_id!r}")
    if solver is None:
        raise ValueError(f"engine references unknown solver definition {solver_id!r}")

    publication = COMPONENT_PUBLICATIONS[component_id]
    solver_evidence = SOLVER_EVIDENCE.get(solver.evidence_ref)
    status = component["status"]
    component_research = bool(component.get("analytics_lab_only"))
    research = component_research or model.is_research_only or solver.is_research_only
    deprecated = publication.publication_status in {"deprecated", "out-of-scope"}
    transition_allowed = (
        status == registry.ModelStatus.VALIDATED
        # Temporary grandfathering intentionally does not imply model Q2/Q6;
        # it requires exact executable evidence and expires independently.
        and bool(model.evidence_refs)
        and solver.governance_status == "validated"
        and solver_evidence is not None
        and bool(solver_evidence.test_refs)
        and not research
        and not deprecated
    )
    if deprecated:
        eligibility_status = publication.publication_status
    elif research:
        eligibility_status = "research-only"
    elif transition_allowed:
        # This preserves explicitly grandfathered workstation behaviour while
        # distinguishing it from an independently validated QW5 approval.
        eligibility_status = "legacy-transition"
    else:
        eligibility_status = "non-production"

    evidence_refs = tuple(sorted({
        *model.evidence_refs,
        solver.evidence_ref,
        *(solver_evidence.test_refs if solver_evidence else ()),
        *(solver_evidence.benchmark_refs if solver_evidence else ()),
    }))
    pricer_id = component_id if kind == ComponentKind.PRODUCT_PRICER.value else None
    parameterization_id = (
        component_id if kind == ComponentKind.SMILE_PARAMETERIZATION.value else None
    )
    return EngineEligibility(
        ref=DefinitionRef(
            _engine_ref_id(product_id, selector_id, runtime_variant),
            ENGINE_ELIGIBILITY_VERSION,
        ),
        product_definition_id=product_id,
        selector_id=selector_id,
        implementation_component_id=component_id,
        model_ref=model.ref,
        solver_ref=solver.ref,
        pricer_component_id=pricer_id,
        parameterization_component_id=parameterization_id,
        calculation_type=f"{product_id}_pricing",
        parameter_schema_ref=(
            f"api.pricing_workstation:{product_id}:{selector_id}"
            f"@{WORKSTATION_PARAMETER_SCHEMA_VERSION}"
        ),
        required_market_dependencies=tuple(sorted(set(required_market_dependencies))),
        supported_product_features=tuple(sorted(set(supported_product_features))),
        unsupported_regions=tuple(component.get("limitations", [])) or (
            component.get("notes", ""),
        ),
        supported_measures=("value", "engine_reported_measures"),
        publication_targets=("pricing_workstation",),
        eligibility_status=eligibility_status,
        production_allowed=transition_allowed,
        approval_basis="legacy_transition" if transition_allowed else "none",
        approval_ref=LEGACY_TRANSITION_POLICY_REF if transition_allowed else "",
        approval_expires_on=(
            LEGACY_TRANSITION_EXPIRES_ON if transition_allowed else None
        ),
        fallback_policy="error",
        evidence_refs=evidence_refs,
        owner=component.get("owner", component.get("module_path", "quant-platform")),
        workflow_layer="Research" if research else "Production",
        runtime_variant=runtime_variant,
    )


def eligibility_policy_issues(
    eligibility: EngineEligibility,
    *,
    allow_analytics_lab: bool = False,
    allow_non_production: bool = False,
    as_of: date | None = None,
) -> list[tuple[str, str]]:
    """Return fail-closed policy issues shared by validate and price paths."""
    issues: list[tuple[str, str]] = []
    effective_date = as_of or date.today()
    if eligibility.eligibility_status in {"deprecated", "out-of-scope"}:
        issues.append((
            "ENGINE_NOT_PUBLISHED",
            f"engine {eligibility.engine_id!r} is {eligibility.eligibility_status}",
        ))
    if eligibility.is_research_only and not allow_analytics_lab:
        issues.append((
            "ENGINE_RESEARCH_ONLY",
            f"engine {eligibility.engine_id!r} requires explicit Analytics Lab context",
        ))
    if eligibility.production_allowed and eligibility.approval_basis == "legacy_transition":
        if not eligibility.approval_ref or eligibility.approval_expires_on is None:
            issues.append((
                "ENGINE_APPROVAL_INVALID",
                f"engine {eligibility.engine_id!r} has incomplete transition approval",
            ))
        elif effective_date > eligibility.approval_expires_on:
            issues.append((
                "ENGINE_APPROVAL_EXPIRED",
                f"engine {eligibility.engine_id!r} transition approval expired on "
                f"{eligibility.approval_expires_on.isoformat()}",
            ))
    if (not eligibility.production_allowed
            and not eligibility.is_research_only
            and eligibility.eligibility_status == "non-production"
            and not allow_non_production):
        issues.append((
            "ENGINE_NOT_PRODUCTION_ALLOWED",
            f"engine {eligibility.engine_id!r} is not production allowed",
        ))
    return issues


def approval_is_active(
    eligibility: EngineEligibility, *, as_of: date | None = None
) -> bool:
    """Return the time-qualified state of an engine approval decision."""
    if not eligibility.production_allowed:
        return False
    if eligibility.approval_basis != "legacy_transition":
        return True
    effective_date = as_of or date.today()
    return bool(
        eligibility.approval_ref
        and eligibility.approval_expires_on is not None
        and effective_date <= eligibility.approval_expires_on
    )


def effective_production_allowed(
    eligibility: EngineEligibility, *, as_of: date | None = None
) -> bool:
    """Execution-facing production flag; unlike the decision, honors expiry."""
    return eligibility.production_allowed and approval_is_active(
        eligibility, as_of=as_of
    )


def eligibility_consistency_errors(
    bindings: Iterable[tuple[str, str, str, Mapping[str, object]]],
    *,
    as_of: date | None = None,
) -> list[str]:
    """Validate workstation bindings without importing the API catalogue."""
    errors: list[str] = []
    # Structural consistency is time-stable by default. Callers may supply an
    # as-of to audit active approvals; runtime execution always goes through
    # eligibility_policy_issues(), which defaults to today's date.
    effective_date = as_of
    seen_pairs: set[tuple[str, str]] = set()
    seen_refs: set[str] = set()
    for product_id, selector_id, component_id, params in bindings:
        pair = (product_id, selector_id)
        if pair in seen_pairs:
            errors.append(f"duplicate workstation selector pair {pair!r}")
            continue
        seen_pairs.add(pair)
        variants = [params]
        if component_id == "carr_madan":
            variants = [{**params, "cf_model": "bsm"}, {**params, "cf_model": "heston"}]
        for variant_params in variants:
            try:
                eligibility = build_engine_eligibility(
                    product_id=product_id,
                    selector_id=selector_id,
                    implementation_component_id=component_id,
                    params=variant_params,
                )
            except (KeyError, ValueError) as exc:
                errors.append(f"{pair!r}: {exc}")
                continue
            if eligibility.engine_id in seen_refs:
                errors.append(f"duplicate engine eligibility id {eligibility.engine_id!r}")
            seen_refs.add(eligibility.engine_id)
            if eligibility.model_ref.definition_id not in MODEL_DEFINITIONS:
                errors.append(f"{eligibility.engine_id}: unknown model ref")
            if eligibility.solver_ref.definition_id not in SOLVER_DEFINITIONS:
                errors.append(f"{eligibility.engine_id}: unknown solver ref")
            if eligibility.fallback_policy != "error":
                errors.append(f"{eligibility.engine_id}: silent fallback is forbidden")
            if eligibility.production_allowed:
                if eligibility.approval_basis != "legacy_transition":
                    errors.append(f"{eligibility.engine_id}: missing transition approval basis")
                if not eligibility.approval_ref or eligibility.approval_expires_on is None:
                    errors.append(f"{eligibility.engine_id}: incomplete transition approval")
                elif (effective_date is not None
                      and effective_date > eligibility.approval_expires_on):
                    errors.append(f"{eligibility.engine_id}: transition approval expired")
                evidence = SOLVER_EVIDENCE.get(
                    SOLVER_DEFINITIONS[eligibility.solver_ref.definition_id].evidence_ref
                )
                if evidence is None:
                    errors.append(f"{eligibility.engine_id}: missing solver evidence")
    return errors
