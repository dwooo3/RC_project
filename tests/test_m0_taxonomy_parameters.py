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


def test_classify_axes_valid():
    for mid in R.MODEL_REGISTRY:
        c = tax.classify(mid)
        assert c["asset_class"] in {a.value for a in tax.AssetClass}
        assert c["model_family"] in {f.value for f in tax.ModelFamily}
        assert c["method"] in {m.value for m in tax.Method}
        assert c["kind"] in {"pricer", "risk", "portfolio", "market"}


def test_classify_examples():
    assert tax.classify("black_scholes") == {
        "asset_class": "equity", "model_family": "analytic",
        "method": "closed_form", "kind": "pricer"}
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
    assert tax.default_engine("european_option") == "black_scholes"
    assert tax.default_engine("american_option") == "pde_cn"
    assert tax.engines_for("nonexistent") == []


def test_engine_ids_are_registered():
    """Every engine in the matrix must be a real registered model."""
    for instrument, engines in tax.ENGINES.items():
        for e in engines:
            assert e in R.MODEL_REGISTRY, f"{instrument} -> unregistered engine {e}"


# ── Registry enrichment ──────────────────────────────────

def test_registry_get_carries_taxonomy():
    e = R.get("black_scholes")
    assert e["asset_class"] == "equity" and e["model_family"] == "analytic"
    assert e["method"] == "closed_form" and e["kind"] == "pricer"


def test_by_asset_class_and_family():
    assert any(m == "irs" for m, _ in R.by_asset_class("rates"))
    assert any(m == "bates" for m, _ in R.by_model_family("jump"))


def test_promotion_rule():
    # barrier has tests + Approximation -> eligible
    assert R.can_promote_to_validated("barrier")
    # a Prototype is not eligible
    assert not R.can_promote_to_validated("cln_ftd")
    cands = R.validation_candidates()
    assert "barrier" in cands and "lookback" in cands
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
    assert "mc_heston_qe" not in engines           # no service route yet


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
