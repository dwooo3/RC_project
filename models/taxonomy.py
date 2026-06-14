"""
Model taxonomy (Master-plan M0).

Three independent classification axes for every pricer, replacing the flat
`domain` field which conflated layer / asset class / instrument:

    asset_class  — what underlying market   (rates, credit, equity, fx, ...)
    model_family — the modelling approach    (analytic, stoch_vol, jump, ...)
    method       — the numerical method      (closed_form, lattice, pde, mc, fourier)

Plus an `ENGINES` matrix: which engines may price a given instrument, so one
instrument (e.g. a barrier) can be valued by several selectable engines. Risk
and portfolio models are tagged `kind="risk"`/`"portfolio"` (not pricers) and
sit outside the asset×instrument×engine grid.

Pure data + lookups; imported by the registry and the pricing catalogue. No
behavioural change to existing engines — this only classifies them.
"""

from __future__ import annotations

from enum import Enum


class AssetClass(str, Enum):
    RATES = "rates"
    CREDIT = "credit"
    EQUITY = "equity"
    FX = "fx"
    INFLATION = "inflation"
    COMMODITY = "commodity"
    HYBRID = "hybrid"        # multi-asset / convertibles
    RISK = "risk"            # VaR / capital (not a pricer)
    PORTFOLIO = "portfolio"
    MARKET = "market"        # surfaces / curves infrastructure


class ModelFamily(str, Enum):
    ANALYTIC = "analytic"
    LOCAL_VOL = "local_vol"
    STOCH_VOL = "stoch_vol"
    JUMP = "jump"
    LEVY = "levy"
    SHORT_RATE = "short_rate"
    MARKET_MODEL = "market_model"
    COPULA = "copula"
    STRUCTURAL = "structural"
    REDUCED_FORM = "reduced_form"
    REPLICATION = "replication"
    STATISTICAL = "statistical"   # GARCH / VaR


class Method(str, Enum):
    CLOSED_FORM = "closed_form"
    LATTICE = "lattice"
    PDE = "pde"
    MONTE_CARLO = "monte_carlo"
    FOURIER = "fourier"
    SIMULATION = "simulation"     # historical / scenario


# model_id -> (asset_class, model_family, method, kind)
# kind: "pricer" (default) | "risk" | "portfolio" | "market"
_A, _MF, _M = AssetClass, ModelFamily, Method

CLASSIFICATION: dict[str, tuple] = {
    # ── Vanilla closed forms ──────────────────────────────
    "black_scholes": (_A.EQUITY, _MF.ANALYTIC, _M.CLOSED_FORM),
    "black76": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "garman_kohlhagen": (_A.FX, _MF.ANALYTIC, _M.CLOSED_FORM),
    "bachelier": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    # ── Lattice / PDE / MC engines (equity) ───────────────
    "binomial_crr": (_A.EQUITY, _MF.ANALYTIC, _M.LATTICE),
    "binomial_lr": (_A.EQUITY, _MF.ANALYTIC, _M.LATTICE),
    "trinomial": (_A.EQUITY, _MF.ANALYTIC, _M.LATTICE),
    "pde_cn": (_A.EQUITY, _MF.LOCAL_VOL, _M.PDE),
    "mc_gbm": (_A.EQUITY, _MF.ANALYTIC, _M.MONTE_CARLO),
    "mc_lsm": (_A.EQUITY, _MF.ANALYTIC, _M.MONTE_CARLO),
    # ── Stochastic vol / jumps / local vol ────────────────
    "heston_cf": (_A.EQUITY, _MF.STOCH_VOL, _M.FOURIER),
    "mc_heston": (_A.EQUITY, _MF.STOCH_VOL, _M.MONTE_CARLO),
    "mc_heston_qe": (_A.EQUITY, _MF.STOCH_VOL, _M.MONTE_CARLO),
    "sabr": (_A.RATES, _MF.STOCH_VOL, _M.CLOSED_FORM),
    "bates": (_A.EQUITY, _MF.JUMP, _M.FOURIER),
    "merton_jump": (_A.EQUITY, _MF.JUMP, _M.CLOSED_FORM),
    "local_vol_mc": (_A.EQUITY, _MF.LOCAL_VOL, _M.MONTE_CARLO),
    "garch": (_A.EQUITY, _MF.STATISTICAL, _M.CLOSED_FORM),
    # ── Short rate ────────────────────────────────────────
    "short_rate": (_A.RATES, _MF.SHORT_RATE, _M.LATTICE),
    "bermudan_swaption": (_A.RATES, _MF.SHORT_RATE, _M.LATTICE),
    "callable_bond": (_A.RATES, _MF.SHORT_RATE, _M.LATTICE),
    # ── Fixed income (discounting) ────────────────────────
    "fixed_bond": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "custom_bond": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "amortizing_bond": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "step_bond": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "perpetual_bond": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "bond_future": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "stir_future": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "repo": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "mm_deposit": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "treasury_bill": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "commercial_paper": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "frn": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "irs": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "fra": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "basis_swap": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "capfloor": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "swaption": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "cms_swap": (_A.RATES, _MF.ANALYTIC, _M.CLOSED_FORM),
    "swaption_cube": (_A.RATES, _MF.STOCH_VOL, _M.CLOSED_FORM),
    # ── Inflation ─────────────────────────────────────────
    "inflation_linked_bond": (_A.INFLATION, _MF.ANALYTIC, _M.CLOSED_FORM),
    "inflation_swap": (_A.INFLATION, _MF.ANALYTIC, _M.CLOSED_FORM),
    # ── FX ────────────────────────────────────────────────
    "fx_forward": (_A.FX, _MF.ANALYTIC, _M.CLOSED_FORM),
    "ndf": (_A.FX, _MF.ANALYTIC, _M.CLOSED_FORM),
    "xccy_swap": (_A.FX, _MF.ANALYTIC, _M.CLOSED_FORM),
    "fx_smile": (_A.FX, _MF.STOCH_VOL, _M.CLOSED_FORM),
    # ── Equity exotics ────────────────────────────────────
    "barrier": (_A.EQUITY, _MF.ANALYTIC, _M.CLOSED_FORM),
    "digital": (_A.EQUITY, _MF.ANALYTIC, _M.CLOSED_FORM),
    "lookback": (_A.EQUITY, _MF.ANALYTIC, _M.CLOSED_FORM),
    "asian": (_A.EQUITY, _MF.ANALYTIC, _M.MONTE_CARLO),
    "variance_swap": (_A.EQUITY, _MF.REPLICATION, _M.CLOSED_FORM),
    "multi_asset": (_A.HYBRID, _MF.ANALYTIC, _M.MONTE_CARLO),
    # ── Credit ────────────────────────────────────────────
    "cds": (_A.CREDIT, _MF.REDUCED_FORM, _M.CLOSED_FORM),
    "cds_curve": (_A.CREDIT, _MF.REDUCED_FORM, _M.CLOSED_FORM),
    "risky_bond": (_A.CREDIT, _MF.REDUCED_FORM, _M.CLOSED_FORM),
    "cva_dva": (_A.CREDIT, _MF.REDUCED_FORM, _M.CLOSED_FORM),
    "cva_exposure": (_A.CREDIT, _MF.REDUCED_FORM, _M.MONTE_CARLO),
    # ── Structured / hybrid ───────────────────────────────
    "structured_autocall": (_A.HYBRID, _MF.STOCH_VOL, _M.MONTE_CARLO),
    "cln_ftd": (_A.CREDIT, _MF.COPULA, _M.MONTE_CARLO),
    "convertible_bond": (_A.HYBRID, _MF.ANALYTIC, _M.LATTICE),
    # ── Risk / portfolio / market (kind != pricer) ────────
    "var_parametric": (_A.RISK, _MF.STATISTICAL, _M.CLOSED_FORM),
    "var_historical": (_A.RISK, _MF.STATISTICAL, _M.SIMULATION),
    "var_mc": (_A.RISK, _MF.STATISTICAL, _M.MONTE_CARLO),
    "evt_var": (_A.RISK, _MF.STATISTICAL, _M.CLOSED_FORM),
    "var_full_reprice": (_A.RISK, _MF.STATISTICAL, _M.SIMULATION),
    "cva_exposure_risk": (_A.RISK, _MF.REDUCED_FORM, _M.MONTE_CARLO),
    "portfolio_aggregation": (_A.PORTFOLIO, _MF.ANALYTIC, _M.CLOSED_FORM),
}

_RISK_FAMILIES = {AssetClass.RISK, AssetClass.PORTFOLIO, AssetClass.MARKET}


def classify(model_id: str) -> dict:
    """Return {asset_class, model_family, method, kind} for a model id."""
    entry = CLASSIFICATION.get(model_id)
    if entry is None:
        return {"asset_class": None, "model_family": None,
                "method": None, "kind": "unknown"}
    ac, mf, m = entry
    kind = "risk" if ac == AssetClass.RISK else (
        "portfolio" if ac == AssetClass.PORTFOLIO else (
            "market" if ac == AssetClass.MARKET else "pricer"))
    return {"asset_class": ac.value, "model_family": mf.value,
            "method": m.value, "kind": kind}


def models_by_asset_class(asset_class: str) -> list[str]:
    return [mid for mid, (ac, _, _) in CLASSIFICATION.items()
            if ac.value == asset_class]


def models_by_family(family: str) -> list[str]:
    return [mid for mid, (_, mf, _) in CLASSIFICATION.items()
            if mf.value == family]


def pricer_asset_classes() -> list[str]:
    """Asset classes that carry actual pricers (excludes risk/portfolio/market)."""
    seen = []
    for ac, _, _ in CLASSIFICATION.values():
        if ac not in _RISK_FAMILIES and ac.value not in seen:
            seen.append(ac.value)
    return seen


# ── Instrument → applicable engines (one instrument, many engines) ───────
# Each entry: instrument key -> [engine model_ids], first is the default.
ENGINES: dict[str, list[str]] = {
    "european_option": ["black_scholes", "binomial_crr", "binomial_lr",
                        "trinomial", "pde_cn", "mc_gbm", "heston_cf",
                        "mc_heston_qe", "merton_jump", "bates", "local_vol_mc"],
    "american_option": ["pde_cn", "binomial_crr", "binomial_lr", "trinomial", "mc_lsm"],
    "barrier_option": ["barrier", "pde_cn"],
    "asian_option": ["asian"],
    "digital_option": ["digital"],
    "lookback_option": ["lookback"],
    "fx_option": ["garman_kohlhagen", "fx_smile"],
    "swaption": ["swaption", "bermudan_swaption"],
    "cap_floor": ["capfloor"],
    "callable_bond": ["callable_bond"],
    "fixed_bond": ["fixed_bond"],
    "cds": ["cds", "cds_curve"],
}


def engines_for(instrument: str) -> list[str]:
    return ENGINES.get(instrument, [])


def default_engine(instrument: str) -> str | None:
    engines = ENGINES.get(instrument)
    return engines[0] if engines else None
