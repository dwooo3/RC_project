"""QW1 authoritative model/solver definitions and publication ledger.

The legacy :mod:`models.registry` remains the canonical inventory of callable
implementation components.  This module separates economic dynamics from
numerical algorithms and records where every component is published.  It is
pure metadata: pricing dispatch remains in the application/service layers.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from domain.model_governance import (
    ComponentPublication,
    DefinitionRef,
    ModelDefinition,
    SolverDefinition,
    SolverEvidenceRecord,
)
from models import registry
from models.parameters import ENGINE_PARAMS, PARAMETER_SCHEMA_VERSION
from models.taxonomy import COMPONENT_GROUPS, ComponentKind, Method, classify


DEFINITION_VERSION = "1.0.0"
VALID_Q_LEVELS = {f"Q{i}" for i in range(7)}


def _parameter_schema_ref(component_id: str) -> str:
    return (
        f"models.parameters:ENGINE_PARAMS:{component_id}"
        f"@{PARAMETER_SCHEMA_VERSION}"
    )


# One economic model may have several implementation components/solvers.  This
# map deliberately does not make ``heston_cf`` and ``heston_adi`` two models.
MODEL_COMPONENT_TO_DEFINITION: dict[str, str] = {
    component_id: component_id
    for kind in (ComponentKind.STOCHASTIC_MODEL, ComponentKind.MARKET_MODEL)
    for component_id in COMPONENT_GROUPS[kind]
}
MODEL_COMPONENT_TO_DEFINITION.update({
    "black_scholes": "black_scholes_merton",
    "heston_cf": "heston",
    "merton_jump": "merton_jump_diffusion",
    "garch": "garch_family",
    "short_rate": "short_rate_family",
})


_MODEL_IMPLEMENTATIONS: dict[str, tuple[str, ...]] = {}
for _component_id, _definition_id in MODEL_COMPONENT_TO_DEFINITION.items():
    _MODEL_IMPLEMENTATIONS.setdefault(_definition_id, ())
    _MODEL_IMPLEMENTATIONS[_definition_id] = tuple(sorted({
        *_MODEL_IMPLEMENTATIONS[_definition_id], _component_id,
    }))

_MODEL_IMPLEMENTATIONS.update({
    "black_scholes_merton": tuple(sorted({
        *_MODEL_IMPLEMENTATIONS["black_scholes_merton"],
        "binomial_crr", "binomial_jr", "binomial_lr", "binomial_tian",
        "mc_gbm", "mc_lsm", "pde_cn", "qmc", "trinomial",
    })),
    "heston": tuple(sorted({
        *_MODEL_IMPLEMENTATIONS["heston"],
        "heston_adi", "mc_heston", "mc_heston_qe",
    })),
    "merton_jump_diffusion": tuple(sorted({
        *_MODEL_IMPLEMENTATIONS["merton_jump_diffusion"], "merton_cos",
    })),
    "short_rate_family": tuple(sorted({
        *_MODEL_IMPLEMENTATIONS["short_rate_family"], "amc",
    })),
    # Dynamics which were previously hidden inside a solver/pricer component.
    "dupire_local_vol": ("local_vol_mc",),
    "two_asset_lognormal": ("two_asset_adi",),
    "deterministic_cashflow": tuple(sorted({
        "bermudan_swaption", "bond_future", "capfloor", "cms_swap", "fra",
        "irs", "stir_future", "swaption", "term_deposit",
    })),
    "deterministic_fx_carry": ("fx_forward", "ndf", "xccy_swap"),
    "reduced_form_credit": tuple(sorted({
        "asset_swap", "cds", "cds_curve", "cds_index", "cds_index_option",
        "cds_isda", "risky_bond",
    })),
    "deterministic_inflation_carry": ("inflation_swap", "jarrow_yildirim"),
    "correlated_gbm": tuple(sorted({
        "accumulator", "asian", "multi_asset", "structured_autocall",
        "structured_basket_note", "tarn", "two_asset_adi",
    })),
    "equity_credit_hybrid": ("afv_convertible", "convertible_bond"),
})


_MODEL_PRIMARY_COMPONENT: dict[str, str] = {
    definition_id: implementation_ids[0]
    for definition_id, implementation_ids in _MODEL_IMPLEMENTATIONS.items()
}
_MODEL_PRIMARY_COMPONENT.update({
    "black_scholes_merton": "black_scholes",
    "heston": "heston_cf",
    "merton_jump_diffusion": "merton_jump",
    "short_rate_family": "short_rate",
    "dupire_local_vol": "local_vol_mc",
    "two_asset_lognormal": "two_asset_adi",
    "deterministic_cashflow": "irs",
    "deterministic_fx_carry": "fx_forward",
    "reduced_form_credit": "cds",
    "deterministic_inflation_carry": "jarrow_yildirim",
    "correlated_gbm": "multi_asset",
    "equity_credit_hybrid": "convertible_bond",
})


_MODEL_NAMES = {
    "black_scholes_merton": "Black-Scholes-Merton lognormal dynamics",
    "heston": "Heston stochastic-variance dynamics",
    "merton_jump_diffusion": "Merton jump-diffusion dynamics",
    "garch_family": "GARCH/GJR/EWMA physical-volatility family",
    "short_rate_family": "Legacy short-rate family facade",
    "dupire_local_vol": "Dupire local-volatility dynamics",
    "two_asset_lognormal": "Correlated two-asset lognormal dynamics",
    "deterministic_cashflow": "Deterministic cash-flow/curve model",
    "deterministic_fx_carry": "Deterministic FX carry model",
    "reduced_form_credit": "Deterministic reduced-form credit model",
    "deterministic_inflation_carry": "Deterministic nominal/real CPI carry",
    "correlated_gbm": "Correlated geometric-Brownian basket dynamics",
    "equity_credit_hybrid": "Equity-credit hybrid dynamics",
}

_STATE_FACTORS = {
    "black_scholes_merton": ("spot",),
    "heston": ("spot", "variance"),
    "merton_jump_diffusion": ("spot", "poisson_jump_count"),
    "garch_family": ("return", "conditional_variance"),
    "short_rate_family": ("short_rate",),
    "dupire_local_vol": ("spot", "local_vol_surface"),
    "two_asset_lognormal": ("spot_1", "spot_2"),
    "deterministic_cashflow": ("discount_curve", "projection_curve"),
    "deterministic_fx_carry": ("fx_spot", "domestic_curve", "foreign_curve"),
    "reduced_form_credit": ("discount_curve", "hazard_curve", "recovery"),
    "deterministic_inflation_carry": ("nominal_curve", "real_curve", "cpi"),
    "correlated_gbm": ("asset_spots", "correlation_matrix"),
    "equity_credit_hybrid": ("equity_spot", "credit_state"),
}

# Q1 is a formal model contract, not a copy of an implementation note.  These
# compact specifications are intentionally solver-independent.  Longer model
# documents and calibrated parameter artefacts remain QW2/QW3 deliverables.
_MODEL_CONTRACTS: dict[str, dict[str, object]] = {
    "bachelier": {
        "dynamics": "dF_t = sigma_N dW_t under the expiry-forward measure",
        "parameter_domain": "T >= 0; sigma_N >= 0; F and K are real-valued",
        "assumptions": ("deterministic discounting", "constant normal volatility"),
        "measure": "expiry_forward", "numeraire": "discount_bond_to_expiry",
    },
    "bates": {
        "dynamics": "Heston spot/variance diffusion plus independent compound-Poisson lognormal jumps",
        "parameter_domain": "S>0; v0,kappa,theta,xi,lambda>=0; rho in [-1,1]; jump variance>=0",
        "assumptions": ("finite compensator", "non-negative variance process"),
    },
    "bk": {
        "dynamics": "d log(r_t) = (theta(t)-a log(r_t))dt + sigma dW_t",
        "parameter_domain": "r0>0; a>=0; sigma>=0; finite theta(t)",
        "assumptions": ("strictly positive short rate", "deterministic model coefficients"),
    },
    "black76": {
        "dynamics": "dF_t = sigma F_t dW_t under the expiry-forward measure",
        "parameter_domain": "F>0; K>=0; T>=0; sigma>=0",
        "assumptions": ("deterministic discounting", "constant lognormal volatility"),
        "measure": "expiry_forward", "numeraire": "discount_bond_to_expiry",
    },
    "black_cox": {
        "dynamics": "dV_t/V_t=(r-q_V)dt+sigma_V dW_t; default is first passage through a debt barrier",
        "parameter_domain": "V0>0; barrier>0; sigma_V>=0; recovery in [0,1]",
        "assumptions": ("continuous barrier monitoring", "deterministic rates and liability barrier"),
    },
    "black_scholes_merton": {
        "dynamics": "dS_t/S_t=(r-q)dt+sigma dW_t",
        "parameter_domain": "S>0; K>=0; T>=0; sigma>=0; finite r and q",
        "assumptions": ("continuous trading", "deterministic r, q and sigma", "no discrete dividends"),
    },
    "cev": {
        "dynamics": "dS_t=(r-q)S_t dt + sigma S_t^beta dW_t",
        "parameter_domain": "S>=0; sigma>=0; beta>=0; boundary convention specified by engine",
        "assumptions": ("deterministic coefficients", "absorbing/non-negative spot boundary"),
    },
    "cgmy": {
        "dynamics": "log spot is a risk-neutral CGMY pure-jump Levy process with martingale compensator",
        "parameter_domain": "C>0; G>0; M>1 for finite positive exponential moment; Y<2",
        "assumptions": ("independent stationary increments", "martingale correction exists"),
    },
    "cheyette": {
        "dynamics": "Markovian HJM state (x_t,y_t) with mean-reverting x and variance accumulator y",
        "parameter_domain": "mean reversion>=0; local volatility finite and non-negative",
        "assumptions": ("deterministic initial curve", "Markovian separability of HJM volatility"),
    },
    "clayton_copula": {
        "dynamics": "joint default uniforms follow an Archimedean Clayton copula",
        "parameter_domain": "theta>0; marginal default probabilities in [0,1]",
        "assumptions": ("calibrated marginal distributions", "exchangeable lower-tail dependence"),
        "measure": "pricing_probability", "numeraire": "not_applicable_probability_model",
    },
    "correlated_gbm": {
        "dynamics": "dS_i/S_i=(r-q_i)dt+sigma_i dW_i with d<W_i,W_j>=rho_ij dt",
        "parameter_domain": "S_i>0; sigma_i>=0; correlation matrix symmetric positive semidefinite",
        "assumptions": ("constant vols/correlation", "deterministic carry inputs"),
    },
    "deterministic_cashflow": {
        "dynamics": "value is the sum of contractual cashflows discounted/projected by deterministic curves",
        "parameter_domain": "valid ordered schedules; positive accrual fractions; finite discount factors",
        "assumptions": ("deterministic curves", "explicit day-count and payment conventions"),
    },
    "deterministic_fx_carry": {
        "dynamics": "F(t,T)=S_t D_f(t,T)/D_d(t,T) with deterministic domestic and foreign curves",
        "parameter_domain": "S>0; positive discount factors; T>=0",
        "assumptions": ("covered-interest parity", "deterministic rates and basis inputs"),
    },
    "deterministic_inflation_carry": {
        "dynamics": "forward CPI is implied by deterministic nominal and real discount curves",
        "parameter_domain": "CPI base>0; positive nominal/real discount factors; ordered observation dates",
        "assumptions": ("deterministic CPI carry", "explicit lag/interpolation convention"),
    },
    "displaced_diffusion": {
        "dynamics": "d(F_t+shift)=sigma(F_t+shift)dW_t under a forward measure",
        "parameter_domain": "F+shift>0; K+shift>=0; sigma>=0",
        "assumptions": ("constant displacement and volatility", "deterministic discounting"),
        "measure": "expiry_forward", "numeraire": "discount_bond_to_expiry",
    },
    "dupire_local_vol": {
        "dynamics": "dS_t/S_t=(r-q)dt+sigma_loc(t,S_t)dW_t",
        "parameter_domain": "S>0; sigma_loc finite/non-negative on the simulated domain",
        "assumptions": ("arbitrage-consistent input surface", "specified surface extrapolation"),
    },
    "equity_credit_hybrid": {
        "dynamics": "equity diffusion is coupled to a state-dependent default intensity and recovery payoff",
        "parameter_domain": "S>0; sigma>=0; intensity>=0; recovery in [0,1]",
        "assumptions": ("compensated default jump", "explicit equity-at-default convention"),
    },
    "g2pp": {
        "dynamics": "r_t=phi(t)+x_t+y_t with correlated Ornstein-Uhlenbeck factors x and y",
        "parameter_domain": "a,b>0; sigma,eta>=0; rho in [-1,1]",
        "assumptions": ("deterministic initial curve fit", "Gaussian factors"),
    },
    "garch_family": {
        "dynamics": "conditional variance follows configured EWMA/GARCH/GJR recursion under the physical measure",
        "parameter_domain": "omega>=0; alpha,beta>=0; stationarity constraints are variant-specific",
        "assumptions": ("ordered return observations", "finite innovation variance"),
        "measure": "physical", "numeraire": "not_applicable_physical_measure",
    },
    "garman_kohlhagen": {
        "dynamics": "dS_t/S_t=(r_d-r_f)dt+sigma dW_t",
        "parameter_domain": "S>0; K>=0; T>=0; sigma>=0; finite domestic/foreign rates",
        "assumptions": ("deterministic domestic and foreign curves", "constant volatility"),
    },
    "gaussian_copula": {
        "dynamics": "latent standard normals with correlation matrix map marginal default probabilities to joint defaults",
        "parameter_domain": "marginal probabilities in [0,1]; correlation matrix positive semidefinite",
        "assumptions": ("calibrated marginals", "static dependence over the horizon"),
        "measure": "pricing_probability", "numeraire": "not_applicable_probability_model",
    },
    "gibson_schwartz": {
        "dynamics": "commodity log spot and convenience yield follow correlated diffusions with mean-reverting yield",
        "parameter_domain": "volatilities>=0; mean reversion>0; rho in [-1,1]",
        "assumptions": ("constant coefficients", "deterministic interest rate"),
    },
    "heston": {
        "dynamics": "dS/S=(r-q)dt+sqrt(v)dW_S; dv=kappa(theta-v)dt+xi sqrt(v)dW_v",
        "parameter_domain": "S>0; v0,kappa,theta,xi>=0; rho in [-1,1]",
        "assumptions": ("non-negative variance convention", "finite required moments for selected solver"),
    },
    "kmv": {
        "dynamics": "firm asset value follows GBM; distance-to-default maps the debt point to default probability",
        "parameter_domain": "asset value>0; debt point>0; asset volatility>=0; horizon>0",
        "assumptions": ("structural default at horizon", "equity-to-asset inversion is well conditioned"),
    },
    "kou": {
        "dynamics": "log spot diffusion plus compound-Poisson double-exponential jumps with martingale compensator",
        "parameter_domain": "lambda>=0; p in [0,1]; eta_up>1; eta_down>0; sigma>=0",
        "assumptions": ("independent jump/diffusion drivers", "finite exponential moment"),
    },
    "lmm": {
        "dynamics": "tenor forward rates are correlated lognormal diffusions under their associated forward measures",
        "parameter_domain": "positive accruals/forwards; volatilities>=0; correlation matrix positive semidefinite",
        "assumptions": ("arbitrage-consistent drift construction", "fixed tenor structure"),
    },
    "lognormal_mixture": {
        "dynamics": "terminal forward distribution is a finite weighted mixture of lognormal components",
        "parameter_domain": "weights>=0 sum to one; component vols>=0; common positive forward",
        "assumptions": ("deterministic discounting", "martingale mean constraint"),
        "measure": "expiry_forward", "numeraire": "discount_bond_to_expiry",
    },
    "merton_jump_diffusion": {
        "dynamics": "log spot diffusion plus compound-Poisson lognormal jumps with risk-neutral compensator",
        "parameter_domain": "sigma,lambda,jump_std>=0; finite jump mean; S>0",
        "assumptions": ("independent Brownian and jump drivers", "finite exponential jump moment"),
    },
    "merton_structural": {
        "dynamics": "firm asset value follows GBM and defaults at maturity when assets fall below debt",
        "parameter_domain": "asset value>0; debt>0; asset volatility>=0; maturity>0",
        "assumptions": ("single maturity debt boundary", "deterministic rates"),
    },
    "nig": {
        "dynamics": "log spot is a risk-neutral Normal-Inverse-Gaussian Levy process with martingale correction",
        "parameter_domain": "alpha>|beta|; delta>0; finite exponential moment requires alpha>|beta+1|",
        "assumptions": ("independent stationary increments", "martingale correction exists"),
    },
    "pilipovic": {
        "dynamics": "commodity spot is the sum/product of mean-reverting short and persistent long factors",
        "parameter_domain": "mean reversion>0; factor volatilities>=0; rho in [-1,1]",
        "assumptions": ("constant coefficients", "specified additive/lognormal variant"),
    },
    "reduced_form_credit": {
        "dynamics": "survival Q(t,T)=exp(-integral_t^T lambda(u)du) with recovery applied at default/payment convention",
        "parameter_domain": "hazard intensity>=0; recovery in [0,1]; positive discount factors",
        "assumptions": ("deterministic hazard and recovery", "explicit accrual-on-default convention"),
    },
    "rough_bergomi": {
        "dynamics": "forward variance is lognormal Volterra-driven with Hurst H and correlated spot driver",
        "parameter_domain": "H in (0,0.5); eta>=0; rho in [-1,1]; xi0(t)>0",
        "assumptions": ("integrable forward-variance curve", "declared Volterra discretization"),
    },
    "schwartz_smith": {
        "dynamics": "log spot is the sum of a mean-reverting short factor and a Brownian long equilibrium factor",
        "parameter_domain": "mean reversion>0; factor volatilities>=0; rho in [-1,1]",
        "assumptions": ("constant coefficients", "deterministic interest rate"),
    },
    "short_rate_family": {
        "dynamics": "runtime-selected Vasicek, CIR or Hull-White one-factor short-rate dynamics",
        "parameter_domain": "variant explicitly selected; variant-specific mean reversion/volatility domains apply",
        "assumptions": ("no silent variant fallback", "deterministic coefficients within selected variant"),
    },
    "swap_market_model": {
        "dynamics": "co-terminal swap rates follow correlated lognormal diffusions under annuity measures",
        "parameter_domain": "positive annuities/rates; volatilities>=0; correlation matrix positive semidefinite",
        "assumptions": ("fixed co-terminal tenor set", "declared measure/drift approximation"),
    },
    "t_copula": {
        "dynamics": "latent multivariate Student-t variables map calibrated marginal default probabilities to joint defaults",
        "parameter_domain": "degrees of freedom>0; marginals in [0,1]; correlation matrix positive semidefinite",
        "assumptions": ("calibrated marginals", "static dependence over the horizon"),
        "measure": "pricing_probability", "numeraire": "not_applicable_probability_model",
    },
    "two_asset_lognormal": {
        "dynamics": "two GBM assets with constant vols and instantaneous correlation rho",
        "parameter_domain": "S1,S2>0; sigma1,sigma2>=0; rho in [-1,1]",
        "assumptions": ("constant carry/vol/correlation", "positive-semidefinite covariance"),
    },
    "variance_gamma": {
        "dynamics": "log spot is Brownian motion with drift evaluated at an independent gamma clock",
        "parameter_domain": "sigma>=0; nu>0; martingale logarithm argument positive",
        "assumptions": ("independent gamma clock", "risk-neutral martingale correction exists"),
    },
}

_LEGACY_EMBEDDED_MODEL_DEFINITIONS = {
    "deterministic_cashflow", "deterministic_fx_carry",
    "reduced_form_credit", "deterministic_inflation_carry",
    "correlated_gbm", "equity_credit_hybrid",
}

_MODEL_EVIDENCE_COMPONENT_OVERRIDES = {
    # These tests exercise model properties (flat-surface/limiting identities),
    # while convergence/reproducibility remain in SolverEvidenceRecord.
    "dupire_local_vol": {"local_vol_mc"},
    "two_asset_lognormal": {"two_asset_adi"},
}


def _status_value(entry: dict) -> str:
    status = entry.get("status")
    return (status.value if hasattr(status, "value") else str(status)).lower()


def _executable_test_refs(component_id: str) -> tuple[str, ...]:
    """Resolve the exact executable evidence catalogue used by validation.

    QW1 keeps the historical map in ``scripts.validation_program``; unlike the
    free-form registry ``tests`` labels, these entries are runnable pytest
    selectors/files and are exercised by ``validation_program.py --run``.
    """
    from scripts.validation_program import TEST_MAP

    return tuple(TEST_MAP.get(component_id, ()))


def _evidence_ref_exists(selector: str) -> bool:
    path = selector.split("::", 1)[0]
    return (Path(__file__).resolve().parents[1] / path).is_file()


def _model_evidence_component_ids(
    definition_id: str, implementation_ids: tuple[str, ...]
) -> set[str]:
    component_ids = {
        component_id
        for component_id in implementation_ids
        if classify(component_id)["component_kind"] in {
            ComponentKind.STOCHASTIC_MODEL.value,
            ComponentKind.MARKET_MODEL.value,
        }
    }
    if definition_id in _LEGACY_EMBEDDED_MODEL_DEFINITIONS:
        component_ids.update(
            component_id
            for component_id in implementation_ids
            if classify(component_id)["component_kind"]
            == ComponentKind.PRODUCT_PRICER.value
        )
    component_ids.update(_MODEL_EVIDENCE_COMPONENT_OVERRIDES.get(definition_id, set()))
    return component_ids


def _model_q_level(definition_id: str, primary: dict,
                   implementation_ids: tuple[str, ...]) -> str:
    """Conservative Q assignment based on explicit specification/evidence.

    ``Validated`` in the legacy component ledger is intentionally *not* mapped
    to Q6.  Q3+ requires a governed calibration/parameter artefact which is not
    yet present, so implemented models stop at Q2 in this QW1 increment.
    """
    if definition_id not in _MODEL_CONTRACTS:
        return "Q0"
    if definition_id in {"short_rate_family", "pilipovic"}:
        return "Q1"
    evidence_components = _model_evidence_component_ids(
        definition_id, implementation_ids
    )
    evidence = [
        selector
        for component_id in implementation_ids
        if component_id in evidence_components
        for selector in _executable_test_refs(component_id)
    ]
    has_versioned_schema = _MODEL_PRIMARY_COMPONENT[definition_id] in ENGINE_PARAMS
    return "Q2" if evidence and has_versioned_schema else "Q1"


def _build_model_definition(definition_id: str,
                            implementation_ids: tuple[str, ...]) -> ModelDefinition:
    primary_id = _MODEL_PRIMARY_COMPONENT[definition_id]
    primary = registry.get(primary_id)
    taxonomy = classify(primary_id)
    evidence_components = _model_evidence_component_ids(
        definition_id, implementation_ids
    )
    evidence = tuple(sorted({
        selector
        for component_id in implementation_ids
        if component_id in evidence_components
        for selector in _executable_test_refs(component_id)
    }))
    references = tuple(sorted({
        ref
        for component_id in implementation_ids
        if component_id in evidence_components
        for ref in registry.get(component_id).get("references", [])
    }))
    research = primary_id in registry.ANALYTICS_LAB_MODELS
    contract = _MODEL_CONTRACTS[definition_id]
    return ModelDefinition(
        ref=DefinitionRef(definition_id, DEFINITION_VERSION),
        name=_MODEL_NAMES.get(definition_id, primary.get("name", definition_id)),
        asset_class=taxonomy.get("asset_class") or "hybrid",
        model_family=taxonomy.get("model_family") or "analytic",
        specification_ref=(
            f"models.quant_definitions:_MODEL_CONTRACTS:{definition_id}"
            f"@{DEFINITION_VERSION}"
        ),
        state_factors=_STATE_FACTORS.get(definition_id, ("market_state",)),
        dynamics=str(contract["dynamics"]),
        measure=str(contract.get("measure", "risk_neutral")),
        numeraire=str(contract.get("numeraire", "money_market_account")),
        parameter_domain=str(contract["parameter_domain"]),
        well_posedness_assumptions=tuple(contract["assumptions"]),
        parameter_schema_ref=(
            _parameter_schema_ref(primary_id) if primary_id in ENGINE_PARAMS
            else f"not_versioned_qw1_gap:{primary_id}"
        ),
        parameter_resolution_policy=(
            "manual_or_market_snapshot; governed calibration artifact not yet available"
        ),
        calibration_policy="not_governed_qw1_gap",
        q_level=_model_q_level(definition_id, primary, implementation_ids),
        governance_status=_status_value(primary),
        workflow_layer="Research" if research else "Production",
        implementation_component_ids=implementation_ids,
        evidence_refs=evidence,
        benchmark_refs=references,
        limitations=(primary.get("notes", ""),) if primary.get("notes") else (),
        implementation_owner=primary.get("owner", primary.get("module_path", "quant-platform")),
        validation_owner=primary.get("validation_owner", "unassigned"),
    )


MODEL_DEFINITIONS: dict[str, ModelDefinition] = {
    definition_id: _build_model_definition(definition_id, implementation_ids)
    for definition_id, implementation_ids in sorted(_MODEL_IMPLEMENTATIONS.items())
}


_SOLVER_ALGORITHMS = {
    "amc": "American Monte Carlo / least-squares continuation",
    "binomial_crr": "Cox-Ross-Rubinstein recombining lattice",
    "binomial_jr": "Jarrow-Rudd equal-probability lattice",
    "binomial_lr": "Leisen-Reimer inversion lattice",
    "binomial_tian": "Tian moment-matched lattice",
    "carr_madan": "Carr-Madan damped FFT inversion",
    "heston_adi": "Douglas ADI finite differences in spot/variance",
    "local_vol_mc": "Log-Euler Monte Carlo with tabulated local volatility",
    "mc_gbm": "Antithetic log-Euler Monte Carlo",
    "mc_heston": "Heston Euler-Maruyama with reflected variance",
    "mc_heston_qe": "Andersen quadratic-exponential Heston Monte Carlo",
    "mc_lsm": "Longstaff-Schwartz least-squares Monte Carlo",
    "merton_cos": "Fang-Oosterlee COS Fourier expansion",
    "pde_cn": "Crank-Nicolson finite differences with Rannacher startup",
    "qmc": "Scrambled Sobol quasi-Monte Carlo",
    "trinomial": "Recombining trinomial lattice",
    "two_asset_adi": "Douglas ADI finite differences in two spot dimensions",
}

_ENGINE_COMPONENT_KINDS = {
    ComponentKind.STOCHASTIC_MODEL.value,
    ComponentKind.MARKET_MODEL.value,
    ComponentKind.SMILE_PARAMETERIZATION.value,
    ComponentKind.PRODUCT_PRICER.value,
}


def _embedded_solver_id(component_id: str, method: str) -> str:
    """Stable implementation-qualified solver id for a non-solver component."""
    return f"{component_id}__{method}"


def _solver_evidence(component_id: str, solver_ref: DefinitionRef,
                     method: str) -> SolverEvidenceRecord:
    entry = registry.get(component_id)
    tests = _executable_test_refs(component_id)
    is_mc = method == Method.MONTE_CARLO.value
    convergence_terms = ("converg", "matches", "bias", "faster", "cross_check")
    registered_claims = tuple(str(item).lower() for item in entry.get("tests", []))
    evidence_text = (*registered_claims, *(item.lower() for item in tests))
    convergence = tuple(t for t in tests if any(term in t.lower()
                                                 for term in convergence_terms))
    reproducibility = any(
        term in claim
        for claim in evidence_text
        for term in ("fixed_seed", "reproduc", "deterministic_seed")
    )
    confidence_interval = any(
        term in claim
        for claim in evidence_text
        for term in ("stderr", "standard_error", "confidence_interval")
    )
    greeks_validation = any(
        term in claim
        for claim in evidence_text
        for term in ("greek", "delta", "gamma", "vega", "rho_bump")
    )
    return SolverEvidenceRecord(
        evidence_id=f"solver-evidence:{solver_ref.definition_id}:{solver_ref.version}",
        solver_ref=solver_ref,
        status=_status_value(entry),
        test_refs=tests,
        benchmark_refs=tuple(entry.get("references", [])),
        convergence_evidence=(
            ",".join(convergence) if convergence else "not_documented_qw1_gap"
        ),
        reproducibility_evidence=(
            "explicit_executable_evidence" if is_mc and reproducibility
            else "not_documented_qw1_gap" if is_mc
            else "not_applicable_deterministic_algorithm"
        ),
        confidence_interval_evidence=(
            "explicit_executable_evidence" if is_mc and confidence_interval
            else "not_documented_qw1_gap" if is_mc
            else "not_applicable_deterministic_algorithm"
        ),
        greeks_validation_evidence=(
            "explicit_executable_evidence" if greeks_validation
            else "not_documented_qw1_gap"
        ),
        performance_envelope="not_documented_qw1_gap",
        validation_owner=entry.get("validation_owner", "unassigned"),
        limitations=(entry.get("notes", ""),) if entry.get("notes") else (),
    )


SOLVER_DEFINITIONS: dict[str, SolverDefinition] = {}
SOLVER_EVIDENCE: dict[str, SolverEvidenceRecord] = {}
EMBEDDED_SOLVER_BY_COMPONENT: dict[str, str] = {}
for _solver_id in sorted(COMPONENT_GROUPS[ComponentKind.NUMERICAL_SOLVER]):
    _entry = registry.get(_solver_id)
    _taxonomy = classify(_solver_id)
    _ref = DefinitionRef(_solver_id, DEFINITION_VERSION)
    _method = _taxonomy["method"]
    _evidence = _solver_evidence(_solver_id, _ref, _method)
    SOLVER_EVIDENCE[_evidence.evidence_id] = _evidence
    _is_mc = _method == Method.MONTE_CARLO.value
    SOLVER_DEFINITIONS[_solver_id] = SolverDefinition(
        ref=_ref,
        name=_entry.get("name", _solver_id),
        method=_method,
        algorithm=_SOLVER_ALGORITHMS[_solver_id],
        numerical_parameter_schema_ref=(
            _parameter_schema_ref(_solver_id) if _solver_id in ENGINE_PARAMS
            else f"embedded_schema:{_solver_id}@{DEFINITION_VERSION}"
        ),
        supported_dimensions=("implementation_specific",),
        supported_features=("see_engine_eligibility",),
        deterministic=not _is_mc,
        random_source_policy="numpy_generator" if _is_mc else "not_applicable",
        seed_policy="explicit_seed" if _is_mc else "not_applicable",
        implementation_component_ids=(_solver_id,),
        evidence_ref=_evidence.evidence_id,
        governance_status=_status_value(_entry),
        workflow_layer=(
            "Research" if _solver_id in registry.ANALYTICS_LAB_MODELS else "Production"
        ),
        limitations=(_entry.get("notes", ""),) if _entry.get("notes") else (),
        owner=_entry.get("owner", _entry.get("module_path", "quant-platform")),
    )

# Legacy product/model components often embed their analytic, lattice or Monte
# Carlo algorithm.  A handful of method-wide placeholder solvers would erase
# which code and tests support a concrete engine, so QW1 materialises one
# implementation-qualified solver/evidence record per eligible component.
for _component_id in sorted(registry.MODEL_REGISTRY):
    _taxonomy = classify(_component_id)
    if _taxonomy["component_kind"] not in _ENGINE_COMPONENT_KINDS:
        continue
    _method = _taxonomy["method"]
    _solver_id = _embedded_solver_id(_component_id, _method)
    EMBEDDED_SOLVER_BY_COMPONENT[_component_id] = _solver_id
    _entry = registry.get(_component_id)
    _ref = DefinitionRef(_solver_id, DEFINITION_VERSION)
    _evidence = _solver_evidence(_component_id, _ref, _method)
    SOLVER_EVIDENCE[_evidence.evidence_id] = _evidence
    _is_mc = _method == Method.MONTE_CARLO.value
    SOLVER_DEFINITIONS[_solver_id] = SolverDefinition(
        ref=_ref,
        name=f"{_entry.get('name', _component_id)} — embedded {_method}",
        method=_method,
        algorithm=(
            f"Implementation-specific {_method} route in canonical component "
            f"{_component_id}"
        ),
        numerical_parameter_schema_ref=(
            _parameter_schema_ref(_component_id)
            if _component_id in ENGINE_PARAMS
            else f"embedded_schema:{_component_id}@{DEFINITION_VERSION}"
        ),
        supported_dimensions=("see_engine_eligibility",),
        supported_features=("see_engine_eligibility",),
        deterministic=not _is_mc,
        random_source_policy=(
            "implementation_specific" if _is_mc
            else "not_applicable"
        ),
        seed_policy=(
            "explicit_or_component_fixed_seed" if _is_mc
            else "not_applicable"
        ),
        implementation_component_ids=(_component_id,),
        evidence_ref=_evidence.evidence_id,
        governance_status=_status_value(_entry),
        workflow_layer=(
            "Research" if _component_id in registry.ANALYTICS_LAB_MODELS
            else "Production"
        ),
        limitations=(_entry.get("notes", ""),) if _entry.get("notes") else (),
        owner=_entry.get("owner", _entry.get("module_path", "quant-platform")),
    )


_BOND_CATALOGUE_COMPONENTS = {
    "amortizing_bond", "callable_bond", "commercial_paper", "custom_bond",
    "fixed_bond", "frn", "inflation_linked_bond", "mbs", "mm_deposit",
    "perpetual_bond", "repo", "step_bond", "treasury_bill",
}


def _publication_for(component_id: str) -> ComponentPublication:
    entry = registry.get(component_id)
    kind = entry["component_kind"]
    targets: tuple[str, ...]
    if kind in {ComponentKind.STOCHASTIC_MODEL.value, ComponentKind.MARKET_MODEL.value}:
        targets = ("model_catalogue",)
    elif kind == ComponentKind.SMILE_PARAMETERIZATION.value:
        targets = ("volatility_calibration_catalogue",)
    elif kind == ComponentKind.NUMERICAL_SOLVER.value:
        targets = ("solver_catalogue",)
    elif kind == ComponentKind.PRODUCT_PRICER.value:
        targets = (("bond_catalogue", "product_catalogue")
                   if component_id in _BOND_CATALOGUE_COMPONENTS
                   else ("product_catalogue",))
    elif kind == ComponentKind.RISK_METHODOLOGY.value:
        targets = ("risk_method_catalogue",)
    elif kind == ComponentKind.MARKET_INFRASTRUCTURE.value:
        targets = ("market_data_catalogue",)
    else:
        targets = ("calibration_method_catalogue",)

    status = entry["status"]
    if component_id == "cln_ftd":
        publication_status = "deprecated"
        reason = "Ambiguous combined CLN/FTD prototype; split contracts before publication."
    elif component_id in registry.ANALYTICS_LAB_MODELS or status == registry.ModelStatus.PROTOTYPE:
        publication_status = "research-only"
        targets = tuple(dict.fromkeys((*targets, "analytics_lab")))
        reason = "Research publication; no production engine approval."
    elif status in {registry.ModelStatus.BROKEN, registry.ModelStatus.PLACEHOLDER}:
        publication_status = "out-of-scope"
        reason = f"Blocked component status: {status.value}."
    elif component_id in _BOND_CATALOGUE_COMPONENTS:
        publication_status = "published"
        reason = "Integrated in the existing bond catalogue."
    else:
        publication_status = "routed"
        reason = (
            "Semantic publication target assigned; concrete UI/API binding "
            "must be confirmed by the application layer."
        )
    return ComponentPublication(
        component_id=component_id,
        component_kind=kind,
        publication_targets=targets,
        publication_status=publication_status,
        reason=reason,
        owner=entry.get("owner", entry.get("module_path", "quant-platform")),
    )


COMPONENT_PUBLICATIONS: dict[str, ComponentPublication] = {
    component_id: _publication_for(component_id)
    for component_id in sorted(registry.MODEL_REGISTRY)
}


def definition_consistency_errors() -> list[str]:
    """Return deterministic QW1 definition/publication violations."""
    errors: list[str] = []
    component_ids = set(registry.MODEL_REGISTRY)

    model_component_ids = (
        set(COMPONENT_GROUPS[ComponentKind.STOCHASTIC_MODEL])
        | set(COMPONENT_GROUPS[ComponentKind.MARKET_MODEL])
    )
    covered_model_components = {
        component_id
        for definition in MODEL_DEFINITIONS.values()
        for component_id in definition.implementation_component_ids
        if component_id in model_component_ids
    }
    if covered_model_components != model_component_ids:
        errors.append(
            "model-definition component coverage mismatch: "
            f"missing={sorted(model_component_ids - covered_model_components)}, "
            f"extra={sorted(covered_model_components - model_component_ids)}"
        )

    for definition_id, definition in sorted(MODEL_DEFINITIONS.items()):
        if definition.definition_id != definition_id:
            errors.append(f"model definition key/ref mismatch: {definition_id}")
        if definition.q_level not in VALID_Q_LEVELS:
            errors.append(f"{definition_id}: invalid q_level {definition.q_level!r}")
        unknown = set(definition.implementation_component_ids) - component_ids
        if unknown:
            errors.append(f"{definition_id}: unknown implementation components {sorted(unknown)}")
        if (not definition.state_factors or not definition.dynamics
                or not definition.parameter_domain
                or not definition.well_posedness_assumptions):
            errors.append(f"{definition_id}: incomplete Q1 specification")
        if definition.q_level in {"Q2", "Q3", "Q4", "Q5", "Q6"} and not definition.evidence_refs:
            errors.append(f"{definition_id}: Q2+ requires executable evidence")
        if definition.q_level in {"Q2", "Q3", "Q4", "Q5", "Q6"}:
            if (not definition.parameter_schema_ref.startswith("models.parameters:")
                    or not definition.parameter_schema_ref.endswith(
                        f"@{PARAMETER_SCHEMA_VERSION}"
                    )):
                errors.append(f"{definition_id}: Q2+ requires versioned parameter schema")
            missing_evidence = [
                ref for ref in definition.evidence_refs
                if not _evidence_ref_exists(ref)
            ]
            if missing_evidence:
                errors.append(
                    f"{definition_id}: unresolved executable evidence "
                    f"{missing_evidence}"
                )

    canonical_solver_ids = set(COMPONENT_GROUPS[ComponentKind.NUMERICAL_SOLVER])
    if not canonical_solver_ids <= set(SOLVER_DEFINITIONS):
        errors.append(
            "missing solver definitions: "
            f"{sorted(canonical_solver_ids - set(SOLVER_DEFINITIONS))}"
        )
    for solver_id, solver in sorted(SOLVER_DEFINITIONS.items()):
        if solver.definition_id != solver_id:
            errors.append(f"solver definition key/ref mismatch: {solver_id}")
        evidence = SOLVER_EVIDENCE.get(solver.evidence_ref)
        if evidence is None:
            errors.append(f"{solver_id}: missing solver evidence {solver.evidence_ref!r}")
        elif evidence.solver_ref != solver.ref:
            errors.append(f"{solver_id}: solver/evidence version mismatch")
        elif solver.governance_status == "validated" and not evidence.test_refs:
            errors.append(f"{solver_id}: validated solver has no executable evidence")
        elif evidence is not None:
            missing_evidence = [
                ref for ref in evidence.test_refs
                if not _evidence_ref_exists(ref)
            ]
            if missing_evidence:
                errors.append(
                    f"{solver_id}: unresolved executable evidence {missing_evidence}"
                )
        unknown = set(solver.implementation_component_ids) - component_ids
        if unknown:
            errors.append(f"{solver_id}: unknown implementation components {sorted(unknown)}")

    if set(COMPONENT_PUBLICATIONS) != component_ids:
        errors.append(
            "component-publication coverage mismatch: "
            f"missing={sorted(component_ids - set(COMPONENT_PUBLICATIONS))}, "
            f"extra={sorted(set(COMPONENT_PUBLICATIONS) - component_ids)}"
        )
    allowed_publication_statuses = {
        "routed", "published", "research-only", "out-of-scope", "deprecated",
    }
    for component_id, publication in sorted(COMPONENT_PUBLICATIONS.items()):
        if publication.publication_status not in allowed_publication_statuses:
            errors.append(
                f"{component_id}: invalid publication status "
                f"{publication.publication_status!r}"
            )
        if not publication.publication_targets:
            errors.append(f"{component_id}: publication target is empty")
    return errors


def assert_definitions_consistent() -> None:
    errors = definition_consistency_errors()
    if errors:
        raise RuntimeError("Quant definitions are inconsistent: " + "; ".join(errors))


def coverage_summary() -> dict[str, object]:
    publication_counts: dict[str, int] = {}
    for publication in COMPONENT_PUBLICATIONS.values():
        publication_counts[publication.publication_status] = (
            publication_counts.get(publication.publication_status, 0) + 1
        )
    q_counts: dict[str, int] = {}
    for definition in MODEL_DEFINITIONS.values():
        q_counts[definition.q_level] = q_counts.get(definition.q_level, 0) + 1
    return {
        "schema_version": DEFINITION_VERSION,
        "component_count": len(COMPONENT_PUBLICATIONS),
        "model_definition_count": len(MODEL_DEFINITIONS),
        "canonical_solver_count": len(COMPONENT_GROUPS[ComponentKind.NUMERICAL_SOLVER]),
        "solver_definition_count": len(SOLVER_DEFINITIONS),
        "solver_evidence_count": len(SOLVER_EVIDENCE),
        "publication_counts": publication_counts,
        "model_q_counts": q_counts,
        "generated_on": date.today().isoformat(),
    }
