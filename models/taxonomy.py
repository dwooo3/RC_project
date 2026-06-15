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
    # ── Lévy / jump (Fourier COS) — M1 ────────────────────
    "merton_cos": (_A.EQUITY, _MF.JUMP, _M.FOURIER),
    "kou": (_A.EQUITY, _MF.JUMP, _M.FOURIER),
    "variance_gamma": (_A.EQUITY, _MF.LEVY, _M.FOURIER),
    "nig": (_A.EQUITY, _MF.LEVY, _M.FOURIER),
    "cgmy": (_A.EQUITY, _MF.LEVY, _M.FOURIER),
    "local_vol_mc": (_A.EQUITY, _MF.LOCAL_VOL, _M.MONTE_CARLO),
    "rough_bergomi": (_A.EQUITY, _MF.STOCH_VOL, _M.MONTE_CARLO),
    # ── Numerical methods (M6) ────────────────────────────
    "baw": (_A.EQUITY, _MF.ANALYTIC, _M.CLOSED_FORM),        # American approx
    "bjerksund_stensland": (_A.EQUITY, _MF.ANALYTIC, _M.CLOSED_FORM),
    "qmc": (_A.EQUITY, _MF.ANALYTIC, _M.MONTE_CARLO),        # Sobol quasi-MC
    "adi": (_A.HYBRID, _MF.ANALYTIC, _M.PDE),                # 2-asset ADI PDE
    "garch": (_A.EQUITY, _MF.STATISTICAL, _M.CLOSED_FORM),
    # ── Short rate ────────────────────────────────────────
    "short_rate": (_A.RATES, _MF.SHORT_RATE, _M.LATTICE),
    "bermudan_swaption": (_A.RATES, _MF.SHORT_RATE, _M.LATTICE),
    "amc": (_A.RATES, _MF.SHORT_RATE, _M.MONTE_CARLO),     # M4c: Longstaff-Schwartz
    "callable_bond": (_A.RATES, _MF.SHORT_RATE, _M.LATTICE),
    "g2pp": (_A.RATES, _MF.SHORT_RATE, _M.MONTE_CARLO),    # M3a: 2-factor Gaussian
    "lmm": (_A.RATES, _MF.MARKET_MODEL, _M.MONTE_CARLO),   # M3b: LIBOR market model
    "bk": (_A.RATES, _MF.SHORT_RATE, _M.LATTICE),          # M3c: Black-Karasinski
    "cheyette": (_A.RATES, _MF.SHORT_RATE, _M.MONTE_CARLO),  # M3c: quasi-Gaussian HJM
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
    "xccy_curve": (_A.FX, _MF.ANALYTIC, _M.CLOSED_FORM),   # M3c: basis bootstrap
    "fx_smile": (_A.FX, _MF.STOCH_VOL, _M.CLOSED_FORM),
    # ── Commodity (M5) ────────────────────────────────────
    "schwartz_smith": (_A.COMMODITY, _MF.ANALYTIC, _M.CLOSED_FORM),
    "gibson_schwartz": (_A.COMMODITY, _MF.ANALYTIC, _M.CLOSED_FORM),
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
    "structured_basket_note": (_A.HYBRID, _MF.ANALYTIC, _M.MONTE_CARLO),
    "cln_ftd": (_A.CREDIT, _MF.COPULA, _M.MONTE_CARLO),
    # ── Credit models (M7) ────────────────────────────────
    "cds_isda": (_A.CREDIT, _MF.REDUCED_FORM, _M.CLOSED_FORM),
    "merton_structural": (_A.CREDIT, _MF.STRUCTURAL, _M.CLOSED_FORM),
    "black_cox": (_A.CREDIT, _MF.STRUCTURAL, _M.CLOSED_FORM),
    "kmv": (_A.CREDIT, _MF.STRUCTURAL, _M.CLOSED_FORM),
    "gaussian_copula": (_A.CREDIT, _MF.COPULA, _M.CLOSED_FORM),
    "convertible_bond": (_A.HYBRID, _MF.ANALYTIC, _M.LATTICE),
    "afv_convertible": (_A.HYBRID, _MF.REDUCED_FORM, _M.LATTICE),   # M8: equity-credit
    "mbs": (_A.RATES, _MF.REDUCED_FORM, _M.CLOSED_FORM),            # M8: prepayment
    "frtb_sba": (_A.RISK, _MF.STATISTICAL, _M.CLOSED_FORM),         # M8: FRTB-SA capital
    # ── Risk / portfolio / market (kind != pricer) ────────
    "var_parametric": (_A.RISK, _MF.STATISTICAL, _M.CLOSED_FORM),
    "var_historical": (_A.RISK, _MF.STATISTICAL, _M.SIMULATION),
    "var_mc": (_A.RISK, _MF.STATISTICAL, _M.MONTE_CARLO),
    "evt_var": (_A.RISK, _MF.STATISTICAL, _M.CLOSED_FORM),
    "var_full_reprice": (_A.RISK, _MF.STATISTICAL, _M.SIMULATION),
    "cva_exposure_risk": (_A.RISK, _MF.REDUCED_FORM, _M.MONTE_CARLO),
    "xva_suite": (_A.RISK, _MF.REDUCED_FORM, _M.MONTE_CARLO),   # M4: full XVA
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
    # european_option: engines with a live service route (M0). mc_heston_qe /
    # local_vol_mc rejoin once their option wrappers land (M1/M2).
    "european_option": ["black_scholes", "binomial_crr", "binomial_lr",
                        "trinomial", "pde_cn", "mc_gbm", "heston_cf",
                        "merton_jump", "bates", "rough_bergomi",
                        "kou", "variance_gamma", "nig", "cgmy", "qmc"],
    "american_option": ["pde_cn", "binomial_crr", "binomial_lr", "trinomial",
                        "mc_lsm", "baw", "bjerksund_stensland"],
    "multi_asset_option": ["adi"],
    "barrier_option": ["barrier", "pde_cn"],
    "asian_option": ["asian"],
    "digital_option": ["digital"],
    "lookback_option": ["lookback"],
    "fx_option": ["garman_kohlhagen", "fx_smile"],
    "swaption": ["swaption", "g2pp", "lmm", "bk", "cheyette"],  # Black-76 / G2++ / LMM / BK / Cheyette
    "cap_floor": ["capfloor", "lmm"],          # Black strip or LMM (M3b)
    "commodity_option": ["schwartz_smith", "gibson_schwartz"],   # M5: futures option
    "commodity_future": ["schwartz_smith", "gibson_schwartz"],   # M5: futures curve
    "callable_bond": ["callable_bond"],
    "fixed_bond": ["fixed_bond"],
    "convertible_bond": ["convertible_bond", "afv_convertible"],   # TF or AFV (M8)
    "mbs": ["mbs"],
    "cds": ["cds", "cds_curve", "cds_isda"],
    "structural_default": ["merton_structural", "black_cox", "kmv"],
    "cdo_tranche": ["gaussian_copula"],
    "kth_to_default": ["gaussian_copula"],
}


def engines_for(instrument: str) -> list[str]:
    return ENGINES.get(instrument, [])


def default_engine(instrument: str) -> str | None:
    engines = ENGINES.get(instrument)
    return engines[0] if engines else None
