"""
M0 foundation — taxonomy (3 axes + engine matrix) and the ParameterSpec system.
Pure, headless. Guards that every registered model is classified and that the
parameter library is coherent.
"""
import pytest

from models import registry as R
from models import taxonomy as tax
from models import parameters as P


# ── Taxonomy ─────────────────────────────────────────────

def test_every_registered_model_is_classified():
    """No model may be left out of the taxonomy (or the UI can't place it)."""
    unclassified = [m for m in R.MODEL_REGISTRY if m not in tax.CLASSIFICATION]
    assert unclassified == [], f"unclassified models: {unclassified}"


def test_canonical_inventory_and_component_kind_partition_are_exact():
    component_ids = {
        model_id
        for ids in tax.COMPONENT_GROUPS.values()
        for model_id in ids
    }
    assert set(R.MODEL_REGISTRY) == set(tax.CLASSIFICATION) == component_ids
    assert sum(len(ids) for ids in tax.COMPONENT_GROUPS.values()) == len(component_ids)
    assert R.consistency_errors() == []


def test_classify_axes_valid():
    for mid in R.MODEL_REGISTRY:
        c = tax.classify(mid)
        assert c["asset_class"] in {a.value for a in tax.AssetClass}
        assert c["model_family"] in {f.value for f in tax.ModelFamily}
        assert c["method"] in {m.value for m in tax.Method}
        assert c["kind"] in {"pricer", "risk", "portfolio", "market"}
        assert c["component_kind"] in {kind.value for kind in tax.ComponentKind}


def test_classify_examples():
    assert tax.classify("black_scholes") == {
        "asset_class": "equity", "model_family": "analytic",
        "method": "closed_form", "kind": "pricer",
        "component_kind": "stochastic_model"}
    assert tax.classify("heston_cf")["method"] == "fourier"
    assert tax.classify("var_historical")["kind"] == "risk"
    assert tax.classify("cds_curve")["asset_class"] == "credit"
    assert tax.classify("unknown_model")["kind"] == "unknown"


def test_grouping_helpers():
    rates = tax.models_by_asset_class("rates")
    assert "irs" in rates and "swaption" in rates
    sv = tax.models_by_family("stoch_vol")
    assert "heston_cf" in sv and "sabr" in sv
    classes = tax.pricer_asset_classes()
    assert "risk" not in classes and "equity" in classes and "fx" in classes


def test_engine_matrix():
    eng = tax.engines_for("european_option")
    assert "black_scholes" in eng and "heston_cf" in eng and "merton_jump" in eng
    assert "merton_cos" in eng
    assert tax.default_engine("european_option") == "black_scholes"
    assert tax.default_engine("american_option") == "pde_cn"
    assert tax.engines_for("nonexistent") == []


def test_engine_ids_are_registered():
    """Every engine in the matrix must be a real registered model."""
    for instrument, engines in tax.ENGINES.items():
        for e in engines:
            assert R.is_registered(e), f"{instrument} -> unregistered engine {e}"


def test_legacy_aliases_resolve_without_polluting_canonical_inventory():
    assert tax.canonical_component_id("adi") == "two_asset_adi"
    assert tax.canonical_component_id("adi", "heston_adi_pricing") == "heston_adi"
    assert tax.classify("adi") == tax.classify("two_asset_adi")
    assert R.get("adi")["canonical_component_id"] == "two_asset_adi"
    assert R.get("adi")["deprecated_alias"] is True
    assert R.get("adi", "heston_adi_pricing")["canonical_component_id"] == "heston_adi"
    assert R.get("cva_exposure_risk")["canonical_component_id"] == "cva_exposure"
    assert not (set(tax.ID_ALIASES) & set(R.MODEL_REGISTRY))

    from services.governance_service import GovernanceService
    listed = {model.model_id for model in GovernanceService().list_models()}
    assert not (set(tax.ID_ALIASES) & listed)


def test_consistency_diagnostics_are_fail_closed_and_taxonomy_authoritative(monkeypatch):
    monkeypatch.setitem(
        R.MODEL_REGISTRY["black_scholes"], "component_kind", "product_pricer")
    assert R.get("black_scholes")["component_kind"] == "stochastic_model"

    monkeypatch.delitem(tax.CLASSIFICATION, "heston_adi")
    errors = R.consistency_errors()
    assert any("heston_adi" in error and "classification" in error
               for error in errors)


def test_governance_startup_rejects_unclassified_registry_entry(monkeypatch):
    from services.governance_service import GovernanceService

    monkeypatch.setitem(R.MODEL_REGISTRY, "unclassified_test_component", {
        "name": "Test", "status": R.ModelStatus.PROTOTYPE, "domain": "Test",
        "tests": [], "notes": "test-only malformed entry",
    })
    with pytest.raises(RuntimeError, match="unclassified_test_component"):
        GovernanceService()


# ── Registry enrichment ──────────────────────────────────

def test_registry_get_carries_taxonomy():
    e = R.get("black_scholes")
    assert e["asset_class"] == "equity" and e["model_family"] == "analytic"
    assert e["method"] == "closed_form" and e["kind"] == "pricer"
    assert e["component_kind"] == "stochastic_model"


def test_legacy_scope_metadata_is_explicit_and_honest():
    afv = R.get("afv_convertible")
    jy = R.get("jarrow_yildirim")
    assert afv["implementation_scope"] == "equity_linked_hazard_crr_tree"
    assert "not the Ayache-Forsyth-Vetzal" in afv["notes"]
    assert jy["implementation_scope"] == "deterministic_flat_nominal_real_carry"
    assert jy["q_level"] == "Q1"
    assert "not the full stochastic Jarrow-Yildirim" in jy["notes"]


def test_by_asset_class_and_family():
    assert any(m == "irs" for m, _ in R.by_asset_class("rates"))
    assert any(m == "bates" for m, _ in R.by_model_family("jump"))


def test_promotion_rule():
    # barrier/lookback are Validated since batch-1 (2026-07) — still "eligible"
    assert R.can_promote_to_validated("barrier")
    # a Prototype is not eligible
    assert not R.can_promote_to_validated("cln_ftd")
    cands = R.validation_candidates()          # NOT-yet-promoted candidates only
    assert "barrier" not in cands and "lookback" not in cands
    assert "tarn" not in cands        # batch-4 (2026-07) закрыл последних кандидатов
    assert "cln_ftd" not in cands


# ── ParameterSpec ────────────────────────────────────────

def test_parameter_spec_validation():
    s = P.P("kappa", "κ", 1.5, "model", minimum=0.0, maximum=20.0)
    assert s.advanced is True                       # model params -> advanced
    assert s.validate_value(2.0) == (True, "")
    assert s.validate_value(-1)[0] is False         # below min
    assert s.validate_value("x")[0] is False        # not a number
    assert s.validate_value(99)[0] is False         # above max


def test_parameter_spec_groups_and_choice():
    with pytest.raises(ValueError):
        P.P("x", "x", 1, "badgroup")
    with pytest.raises(ValueError):
        P.P("x", "x", "a", "contract", dtype="choice")     # choice needs choices
    c = P.P("scheme", "scheme", "qe", "numerical", dtype="choice", choices=["qe", "euler"])
    assert c.validate_value("euler") == (True, "")          # choices bypass numeric


def test_engine_params_library():
    heston = P.engine_params("heston_cf")
    keys = {s.key for s in heston}
    assert {"v0", "kappa", "theta", "xi", "rho"} <= keys
    assert all(s.group == "model" for s in heston)
    # plain analytic engine has no extra params
    assert P.engine_params("black_scholes") == []
    # MC engine carries numerical specs
    assert any(s.key == "n_sims" for s in P.engine_params("mc_gbm"))
    assert {s.key for s in P.engine_params("adi")} == {
        s.key for s in P.engine_params("two_asset_adi")}
    assert {"lam", "mu_j", "delta_j", "N"} <= {
        s.key for s in P.engine_params("merton_cos")}


def test_specs_by_group():
    specs = [P.P("K", "Strike", 100, "contract"),
             P.P("r", "Rate", 0.05, "market"),
             P.P("kappa", "κ", 1.5, "model"),
             P.P("n_sims", "paths", 50000, "numerical", dtype="int")]
    grouped = P.specs_by_group(specs)
    assert len(grouped["contract"]) == 1 and len(grouped["model"]) == 1
    assert set(grouped) == set(P.GROUPS)


def test_engine_param_models_are_registered():
    for engine_id in P.ENGINE_PARAMS:
        assert engine_id in R.MODEL_REGISTRY, f"params for unregistered {engine_id}"


def test_legacy_field_conversion():
    from app.panels.pricing_catalogue import Field
    fields = [Field("S", "Spot", 100.0), Field("opt", "Type", "call", ["call", "put"]),
              Field("cashflows", "CF", "1:35,2:1035", wide=True),
              Field("K", "Strike", 105.0)]
    specs = P.from_legacy_fields(fields)
    by_key = {s.key: s for s in specs}
    assert by_key["S"].group == "market"            # spot -> market
    assert by_key["opt"].dtype == "choice"
    assert by_key["cashflows"].dtype == "schedule"  # wide text
    assert by_key["K"].group == "contract"


# ── M0 engine-aware pricing (UI dispatch) ────────────────

def test_vanilla_product_is_engine_aware():
    from app.panels.pricing_catalogue import products_by_category
    prod = next(p for p in products_by_category("Option") if p.id == "vanilla")
    engines = prod.engines()
    assert "black_scholes" in engines and "merton_jump" in engines
    assert {"mc_heston", "mc_heston_qe"} <= set(engines)


def test_vanilla_engine_dispatch_agrees_and_differs():
    from app.panels.pricing_catalogue import products_by_category
    from models.parameters import engine_params
    from services.pricing_service import PricingService
    svc = PricingService(allow_analytics_lab=True)
    prod = next(p for p in products_by_category("Option") if p.id == "vanilla")
    base = {"S": 100, "K": 100, "T": 1.0, "r": 0.05, "sigma": 0.20, "q": 0.0, "opt": "call"}

    def price(eng):
        v = dict(base, __engine=eng)
        for s in engine_params(eng):
            v.setdefault(s.key, s.default)
        return prod.price(svc, v)["value"]

    bsm = price("black_scholes")
    # lattice/PDE/MC engines agree with BSM within numerical tolerance
    for eng in ("binomial_lr", "pde_cn", "trinomial"):
        assert abs(price(eng) - bsm) < 0.05, eng
    # jump engine adds value (negative-mean jumps richen the option)
    assert price("merton_jump") > bsm
