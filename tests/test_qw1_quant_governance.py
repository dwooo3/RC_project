"""QW1: separated model/solver definitions, publication and engine eligibility."""

from collections import Counter
from dataclasses import fields
from datetime import date

import pytest

from api.pricing_workstation import (
    PRODUCTS,
    build_ws_catalogue,
    find_product,
    payoff_ws,
    price_ws,
    validate_ws,
)
from domain.model_governance import EngineEligibility, ModelDefinition
from domain.pricing_environment import PricingEnvironment
from models import registry
from models.engine_eligibility import (
    build_engine_eligibility,
    eligibility_consistency_errors,
    eligibility_policy_issues,
)
from models.quant_definitions import (
    COMPONENT_PUBLICATIONS,
    MODEL_DEFINITIONS,
    SOLVER_DEFINITIONS,
    SOLVER_EVIDENCE,
    definition_consistency_errors,
)
from models.taxonomy import COMPONENT_GROUPS, ComponentKind
from services.governance_service import GovernanceService
from services.pricing_service import PricingService


def _bindings():
    rows = []
    for product in PRODUCTS:
        for engine in product.engines:
            defaults = {
                spec.key: spec.default
                for spec in product.params_for(engine, [], [])
            }
            rows.append((product.id, engine.id, engine.model_id, defaults))
    return rows


def _vanilla_params():
    return {
        "S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05,
        "q": 0.0, "sigma": 0.2, "opt": "call",
    }


def test_qw1_definition_and_publication_ledgers_are_complete():
    assert definition_consistency_errors() == []
    assert set(COMPONENT_PUBLICATIONS) == set(registry.MODEL_REGISTRY)
    assert len(MODEL_DEFINITIONS) == 39
    assert len(SOLVER_DEFINITIONS) == 107
    assert len(SOLVER_EVIDENCE) == 107
    assert Counter(item.q_level for item in MODEL_DEFINITIONS.values()) == {
        "Q1": 21, "Q2": 18,
    }
    assert "production_allowed" not in {field.name for field in fields(ModelDefinition)}
    assert all(item.parameter_domain for item in MODEL_DEFINITIONS.values())
    assert all(item.well_posedness_assumptions for item in MODEL_DEFINITIONS.values())
    assert all(
        item.parameter_schema_ref.startswith("models.parameters:")
        for item in MODEL_DEFINITIONS.values()
        if item.q_level == "Q2"
    )


def test_model_and_solver_roles_are_physically_separate():
    heston = MODEL_DEFINITIONS["heston"]
    assert {"heston_cf", "heston_adi", "mc_heston", "mc_heston_qe"} <= set(
        heston.implementation_component_ids
    )
    assert heston.q_level == "Q2"
    assert SOLVER_DEFINITIONS["heston_adi"].method == "pde"
    assert SOLVER_DEFINITIONS["mc_heston_qe"].method == "monte_carlo"
    qe_evidence = SOLVER_EVIDENCE[
        SOLVER_DEFINITIONS["mc_heston_qe"].evidence_ref
    ]
    assert qe_evidence.reproducibility_evidence == "not_documented_qw1_gap"
    assert qe_evidence.confidence_interval_evidence == "not_documented_qw1_gap"

    # A Monte-Carlo taxonomy label is not itself evidence for deterministic
    # replay or confidence intervals. QW1 stays conservative until an exact
    # executable evidence artifact explicitly proves each capability.
    mc_evidence = [
        SOLVER_EVIDENCE[solver.evidence_ref]
        for solver in SOLVER_DEFINITIONS.values()
        if not solver.deterministic
    ]
    assert mc_evidence
    assert {
        item.reproducibility_evidence for item in mc_evidence
    } == {"not_documented_qw1_gap"}
    assert {
        item.confidence_interval_evidence for item in mc_evidence
    } == {"not_documented_qw1_gap"}


def test_workstation_pairs_have_unique_versioned_eligibility():
    bindings = _bindings()
    assert len(bindings) == 105
    assert len({(product, selector) for product, selector, _, _ in bindings}) == 105
    assert eligibility_consistency_errors(bindings) == []

    eligibilities = GovernanceService().list_engine_eligibilities()
    assert len(eligibilities) == 106  # Carr-Madan variants + custom AST binding
    assert len({item.engine_id for item in eligibilities}) == len(eligibilities)
    assert all(isinstance(item, EngineEligibility) for item in eligibilities)


def test_legacy_transition_keeps_validated_production_verticals_available():
    governance = GovernanceService()
    for product_id, selector_id in (
        ("european_option", "black_scholes"),
        ("fra", "fra"),
        ("irs", "irs"),
        ("fx_forward", "fx_forward"),
        ("cds", "cds"),
        ("autocall", "structured_autocall"),
        ("basket_option", "multi_asset"),
        ("convertible", "convertible_bond"),
    ):
        eligibility = governance.get_engine_eligibility(product_id, selector_id)
        assert eligibility.production_allowed, eligibility.engine_id
        assert eligibility.eligibility_status == "legacy-transition"
        assert eligibility.approval_basis == "legacy_transition"
        assert eligibility.approval_ref
        assert eligibility.approval_expires_on is not None


def test_pricing_dropdown_excludes_wrong_component_contours():
    model_ids = {engine.model_id for product in PRODUCTS for engine in product.engines}
    assert not (model_ids & COMPONENT_GROUPS[ComponentKind.RISK_METHODOLOGY])
    assert not (model_ids & COMPONENT_GROUPS[ComponentKind.MARKET_INFRASTRUCTURE])
    assert {"garch", "sabr", "short_rate"}.isdisjoint(model_ids)
    # Existing Heston solvers are now explicit Analytics-Lab engines.
    assert {"mc_heston", "mc_heston_qe"} <= model_ids


def test_carr_madan_runtime_variant_resolves_actual_model():
    bsm = build_engine_eligibility(
        product_id="european_option", selector_id="carr_madan",
        implementation_component_id="carr_madan", params={"cf_model": "bsm"},
    )
    heston = build_engine_eligibility(
        product_id="european_option", selector_id="carr_madan",
        implementation_component_id="carr_madan", params={"cf_model": "heston"},
    )
    assert bsm.engine_id != heston.engine_id
    assert bsm.model_ref.definition_id == "black_scholes_merton"
    assert bsm.production_allowed is True
    assert heston.model_ref.definition_id == "heston"
    assert heston.is_research_only and heston.production_allowed is False


def test_transition_approval_expiry_is_inclusive_and_fail_closed_afterwards():
    eligibility = build_engine_eligibility(
        product_id="european_option", selector_id="black_scholes",
        implementation_component_id="black_scholes",
    )
    assert eligibility_policy_issues(
        eligibility, as_of=date(2027, 1, 31)
    ) == []
    issues = eligibility_policy_issues(
        eligibility, as_of=date(2027, 2, 1)
    )
    assert [code for code, _ in issues] == ["ENGINE_APPROVAL_EXPIRED"]
    assert eligibility_consistency_errors(
        _bindings(), as_of=date(2027, 1, 31)
    ) == []
    assert any(
        "transition approval expired" in issue
        for issue in eligibility_consistency_errors(
            _bindings(), as_of=date(2027, 2, 1)
        )
    )

    governance = GovernanceService()
    active = governance.quant_coverage_summary(as_of=date(2027, 1, 31))
    expired = governance.quant_coverage_summary(as_of=date(2027, 2, 1))
    assert active["production_engine_count"] == 86
    assert active["declared_production_engine_count"] == 86
    assert active["expired_transition_engine_count"] == 0
    assert expired["production_engine_count"] == 0
    assert expired["declared_production_engine_count"] == 86
    assert expired["legacy_transition_engine_count"] == 0
    assert expired["expired_transition_engine_count"] == 86


def test_validate_and_price_share_research_policy_gate():
    params = _vanilla_params()
    blocked = validate_ws("european_option", "heston_cf", params)
    assert blocked["valid"] is False
    assert any(issue["code"] == "ENGINE_RESEARCH_ONLY"
               for issue in blocked["issues"])

    allowed = validate_ws(
        "european_option", "heston_cf", params,
        allow_analytics_lab=True,
    )
    assert allowed["valid"] is True
    assert allowed["eligibility"]["model_definition_id"] == "heston"

    with pytest.raises(ValueError, match="ENGINE_RESEARCH_ONLY"):
        price_ws(PricingService(), None, "european_option", "heston_cf", params)
    result = price_ws(
        PricingService(allow_analytics_lab=True), None,
        "european_option", "heston_cf", params,
    )
    assert result["errors"] == []
    assert result["provenance"]["model_definition_id"] == "heston"


def test_engine_provenance_is_written_to_result_and_audit():
    result = price_ws(
        PricingService(), None, "european_option", "black_scholes",
        _vanilla_params(),
    )
    assert result["eligibility_id"] == "european_option:black_scholes"
    assert result["model_definition_id"] == "black_scholes_merton"
    assert result["solver_definition_id"] == "black_scholes__closed_form"
    assert result["provenance"]["production_allowed"] is True

    svc = PricingService()
    product = find_product("european_option")
    priced = price_ws(svc, None, product.id, "black_scholes", _vanilla_params())
    audit = svc.audit.records[0]
    assert audit.details["engine_eligibility_id"] == priced["eligibility_id"]
    assert audit.details["model_definition_id"] == "black_scholes_merton"
    assert audit.details["solver_definition_id"] == "black_scholes__closed_form"


def test_publication_backlog_is_routed_not_dumped_into_dropdown():
    used = {engine.model_id for product in PRODUCTS for engine in product.engines}
    backlog = set(registry.MODEL_REGISTRY) - used
    assert len(backlog) == 38
    publications = {row.component_id: row
                    for row in GovernanceService().list_component_publications()}
    assert Counter(row.publication_status for row in publications.values()) == {
        "published": 85,
        "routed": 18,
        "research-only": 20,
        "deprecated": 1,
    }
    assert all(publications[item].publication_targets for item in backlog)
    assert publications["var_historical"].publication_targets == (
        "risk_method_catalogue",
    )
    assert publications["var_historical"].publication_status == "routed"
    assert "bond_catalogue" in publications["fixed_bond"].publication_targets
    assert publications["fixed_bond"].publication_status == "published"
    assert publications["cln_ftd"].publication_status == "deprecated"


def test_catalogue_and_swift_contract_metadata_are_additive():
    catalogue = build_ws_catalogue([], [])
    engine = catalogue["products"][0]["engines"][0]
    assert engine["model_id"] == "black_scholes"
    assert engine["eligibility"]["eligibility_id"] == (
        "european_option:black_scholes"
    )
    assert engine["eligibility"]["fallback_policy"] == "error"
    carr = next(
        item for item in catalogue["products"][0]["engines"]
        if item["id"] == "carr_madan"
    )
    variants = {row["runtime_variant"]: row
                for row in carr["eligibility_variants"]}
    assert set(variants) == {"bsm", "heston"}
    assert variants["bsm"]["production_allowed"] is True
    assert variants["heston"]["status"] == "research-only"


def test_server_workstation_permissions_are_environment_scoped():
    from api import server

    assert server._workstation_permissions(None) == (False, False)
    normal = PricingEnvironment("FO2", "FO", "fo")
    assert server._workstation_permissions(normal) == (False, False)
    untrusted = PricingEnvironment(
        "CUSTOM", "Untrusted", "research",
        metadata={
            "allow_analytics_lab": "true",
            "allow_non_production": "true",
        },
    )
    assert server._workstation_permissions(untrusted) == (False, False)
    lab = PricingEnvironment("LAB", "Analytics Lab", "research")
    assert server._workstation_permissions(lab) == (True, True)
    service = server._workstation_service(lab)
    assert service.allow_analytics_lab is True
    assert service.allow_non_production_models is True


def test_server_validate_and_price_block_research_without_lab_environment():
    from api import server

    request = server.WsPriceRequest(
        product="european_option", engine="heston_cf", params=_vanilla_params()
    )
    validation = server.ws_validate(request)
    assert validation["valid"] is False
    assert any(issue["code"] == "ENGINE_RESEARCH_ONLY"
               for issue in validation["issues"])
    with pytest.raises(server.HTTPException) as exc_info:
        server.ws_price(request)
    assert exc_info.value.status_code == 400
    assert "ENGINE_RESEARCH_ONLY" in exc_info.value.detail


def test_all_derived_pricing_routes_share_fail_closed_policy():
    from api import server

    params = _vanilla_params()
    calls = [
        lambda: server.ws_ladder(server.WsLadderRequest(
            product="european_option", engine="heston_cf", params=params,
            bump_key="S", lo=90, hi=110, steps=3,
        )),
        lambda: server.ws_grid2d(server.WsGrid2DRequest(
            product="european_option", engine="heston_cf", params=params,
            x_key="S", y_key="sigma", x_lo=90, x_hi=110,
            y_lo=.15, y_hi=.25, nx=3, ny=3,
        )),
        lambda: server.ws_payoff(server.WsPriceRequest(
            product="european_option", engine="heston_cf", params=params,
        )),
        lambda: server.ws_scenarios(server.WsPriceRequest(
            product="european_option", engine="heston_cf", params=params,
        )),
    ]
    for call in calls:
        with pytest.raises(server.HTTPException) as exc_info:
            call()
        assert exc_info.value.status_code == 400
        assert "ENGINE_RESEARCH_ONLY" in exc_info.value.detail


def test_payoff_uses_a_schema_valid_near_expiry_horizon():
    result = payoff_ws(
        PricingService(), None, "european_option", "black_scholes",
        _vanilla_params(), steps=3,
    )
    assert len(result["value"]) == 3
    assert len(result["payoff"]) == 3


def test_payoff_materializes_environment_engine_and_parameter_defaults():
    env = PricingEnvironment(
        "FO-DEFAULTS", "FO defaults", "fo",
        pricer_overrides={"european_option": "black_scholes"},
        default_params={**_vanilla_params(), "S": 120.0},
    )
    result = payoff_ws(
        PricingService(), None, "european_option", None, {}, steps=3, env=env,
    )
    assert result["engine"] == "black_scholes"
    assert result["spot"] == 120.0
    assert len(result["value"]) == 3
    assert len(result["payoff"]) == 3


def test_quant_governance_api_exposes_all_separated_ledgers():
    from api import server

    payload = server.quant_governance()
    assert payload["summary"]["component_count"] == 124
    assert payload["summary"]["model_q_counts"] == {"Q1": 21, "Q2": 18}
    assert payload["summary"]["publication_counts"] == {
        "deprecated": 1,
        "published": 85,
        "research-only": 20,
        "routed": 18,
    }
    assert payload["summary"]["production_engine_count"] == 86
    assert payload["summary"]["declared_production_engine_count"] == 86
    assert len(payload["model_definitions"]) == 39
    assert len(payload["solver_definitions"]) == 107
    assert len(payload["engine_eligibilities"]) == 106
    assert len(payload["component_publications"]) == 124


@pytest.mark.parametrize("engine_id", ["mc_heston", "mc_heston_qe"])
def test_heston_mc_engines_are_callable_and_research_only(engine_id):
    product = find_product("european_option")
    engine = next(item for item in product.engines if item.id == engine_id)
    params = {spec.key: spec.default for spec in product.params_for(engine, [], [])}
    params.update(n_sims=1000, steps=8, seed=7)
    result = price_ws(
        PricingService(allow_analytics_lab=True), None,
        product.id, engine_id, params,
    )
    assert result["errors"] == []
    assert result["value"] is not None
    assert result["model_id"] == engine_id
    assert result["model_definition_id"] == "heston"
    assert result["solver_definition_id"] == engine_id
    assert result["provenance"]["production_allowed"] is False


def test_carr_madan_heston_executes_with_variant_provenance():
    params = {
        **_vanilla_params(), "cf_model": "heston", "v0": .04,
        "kappa": 1.5, "theta": .04, "xi": .3, "rho": -.6,
    }
    result = price_ws(
        PricingService(allow_analytics_lab=True), None,
        "european_option", "carr_madan", params,
    )
    assert result["errors"] == []
    assert result["value"] is not None
    assert result["eligibility_id"] == "european_option:carr_madan:heston"
    assert result["model_definition_id"] == "heston"
    assert result["provenance"]["runtime_variant"] == "heston"


def test_direct_carr_madan_service_enforces_runtime_variant_governance():
    params = {
        **_vanilla_params(), "v0": .04, "kappa": 1.5,
        "theta": .04, "xi": .3, "rho": -.6,
    }

    blocked = PricingService().price_carr_madan(
        "heston", **{key: value for key, value in params.items() if key != "cf_model"}
    )
    assert blocked["value"] is None
    assert any("ENGINE_RESEARCH_ONLY" in error for error in blocked["errors"])
    assert blocked["model_definition_id"] == "heston"
    assert blocked["engine_runtime_variant"] == "heston"

    typo = PricingService().price_carr_madan(
        "hestonn", **{key: value for key, value in params.items() if key != "cf_model"}
    )
    assert typo["value"] is None
    assert any("unsupported Carr-Madan model 'hestonn'" in error
               for error in typo["errors"])
    assert typo.get("model_definition_id") is None

    allowed = PricingService(allow_analytics_lab=True).price_carr_madan(
        "heston", **{key: value for key, value in params.items() if key != "cf_model"}
    )
    assert allowed["errors"] == []
    assert allowed["value"] is not None
    assert allowed["engine_eligibility_id"] == (
        "european_option:carr_madan:heston"
    )
    assert allowed["model_definition_id"] == "heston"
    assert allowed["solver_definition_id"] == "carr_madan"
    assert allowed["engine_runtime_variant"] == "heston"
