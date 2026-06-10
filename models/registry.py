"""
Model registry — central source of truth for validation status.
Every pricing / risk module must reference this registry.
"""

from enum import Enum


class ModelStatus(str, Enum):
    VALIDATED    = "Validated"
    APPROXIMATION = "Approximation"
    PROTOTYPE    = "Prototype"
    PLACEHOLDER  = "Placeholder"
    BROKEN       = "Broken"


PRODUCTION_MODELS = {
    "fixed_bond",
    "irs",
    "fx_forward",
    "garman_kohlhagen",
    "var_historical",
    "var_parametric",
    "var_mc",
    "evt_var",
}

ANALYTICS_LAB_MODELS = {
    "mc_gbm",
    "mc_lsm",
    "mc_heston",
    "heston_cf",
    "sabr",
    "garch",
    "short_rate",
}


MODEL_REGISTRY: dict[str, dict] = {
    # ── Equity / FX options ───────────────────────────────
    "black_scholes": {
        "name": "Black-Scholes / Merton",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["put_call_parity", "atm_call_known_value"],
        "notes": "European vanilla only. No discrete dividends. Expiry put delta now -1 when ITM; volga/ultima rescaled to per-1% convention.",
    },
    "black76": {
        "name": "Black-76 (Futures/Rates)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["put_call_parity"],
        "notes": "Forward-price model. No vol surface by tenor/strike.",
    },
    "garman_kohlhagen": {
        "name": "Garman-Kohlhagen (FX Options)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["put_call_parity"],
        "notes": "Continuous dividend = foreign rate. No FX smile.",
    },
    "bachelier": {
        "name": "Bachelier (Normal Vol)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Supports negative rates. Vega per 1% normal vol.",
    },

    # ── Lattice models ────────────────────────────────────
    "binomial_crr": {
        "name": "Binomial CRR",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["no_recursion", "european_converges_to_bsm", "american_put_ge_european"],
        "notes": "Recursion bug fixed. Greeks via bump-and-reprice. Convergence tests pending.",
    },
    "binomial_lr": {
        "name": "Binomial Leisen-Reimer",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["no_recursion"],
        "notes": "Better convergence than CRR for same N.",
    },
    "trinomial": {
        "name": "Trinomial Tree",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["no_recursion"],
        "notes": "Useful for barrier options. Barrier placement not optimised.",
    },

    # ── Monte Carlo ───────────────────────────────────────
    "mc_gbm": {
        "name": "Monte Carlo GBM",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["mc_european_vs_bsm"],
        "notes": "Antithetic + moment matching + control variate (CV expectation corrected to E[disc*S_T]=S0 e^{-qT}). Greeks via common random numbers.",
    },
    "mc_lsm": {
        "name": "Longstaff-Schwartz LSM",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Analytics",
        "tests": [],
        "notes": "Recursion bug fixed. No out-of-sample exercise policy validation. Use CRR for benchmarks.",
    },
    "mc_heston": {
        "name": "Heston Monte Carlo",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Analytics",
        "tests": [],
        "notes": "Euler-Maruyama with reflection. Slow convergence for deep OTM.",
    },

    # ── Stochastic vol ────────────────────────────────────
    "heston_cf": {
        "name": "Heston (Characteristic Function)",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Analytics",
        "tests": [],
        "notes": "CF integration via scipy quad (stable Little-Heston-Trap form). Delta now dividend-adjusted (e^{-qT} P1). Feller condition not enforced. No benchmark test.",
    },
    "sabr": {
        "name": "SABR",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Analytics",
        "tests": [],
        "notes": "Hagan-Kumar-Lesnieweski-Woodward. No ATM limit test. No positive vol guarantee.",
    },
    "garch": {
        "name": "GARCH / EWMA",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": [],
        "notes": "GARCH(1,1) + EWMA. Stationarity (α+β<1) checked. No NaN/inf guard on inputs.",
    },

    # ── Fixed income ──────────────────────────────────────
    "fixed_bond": {
        "name": "Fixed-Rate Bond",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [
            "day_count_act365f",
            "day_count_act360",
            "day_count_30360",
            "coupon_schedule_regular",
            "clean_dirty_accrued_consistency",
            "flat_curve_bond_baseline",
        ],
        "notes": (
            "Regular fixed-rate bond engine with ACT/365F, ACT/360, 30/360, "
            "business-day adjustment, settlement handling, accrued interest, clean/dirty price, "
            "duration (modified duration now uses YTM, not the zero rate at maturity), "
            "convexity, and finite-difference DV01. Limitations: no external holiday "
            "calendar source, no irregular stub policy, no ex-coupon logic, no amortization, "
            "no callable/putable features, and no inflation-linked bond mechanics."
        ),
    },
    "custom_bond": {
        "name": "Custom Cashflow Bond",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Prices an arbitrary user-supplied cashflow schedule on the discount curve.",
    },
    "callable_bond": {
        "name": "Callable / Putable Bond (OAS)",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": [],
        "notes": "BDT short-rate tree with optimal exercise; option value and OAS. Flat rate vol; no vol term structure calibration.",
    },
    "bond_future": {
        "name": "Bond Future (CTD)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Cheapest-to-deliver via min net basis; theoretical futures, invoice, futures DV01, hedge ratio. Conversion factors supplied externally.",
    },
    "stir_future": {
        "name": "STIR Future",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Price = 100 - rate; linear DV01 on notional and tenor.",
    },
    "repo": {
        "name": "Repo / Reverse Repo",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Cash-and-carry forward price, net carry and funding DV01. Simple repo rate; no haircut/margin schedule.",
    },
    "mm_deposit": {
        "name": "Money Market Deposit",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Simple-interest term deposit; PV on the discount curve.",
    },
    "treasury_bill": {
        "name": "Treasury Bill",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Discount instrument; discount yield, money-market yield, bond-equivalent yield.",
    },
    "commercial_paper": {
        "name": "Commercial Paper",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Discount instrument; discount yield and money-market yield.",
    },
    "amortizing_bond": {
        "name": "Amortizing Bond",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Linear or level-annuity principal amortization; DCF on the curve. No prepayment model.",
    },
    "step_bond": {
        "name": "Step-Up / Step-Down Bond",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Scheduled coupon changes; DCF on the curve.",
    },
    "perpetual_bond": {
        "name": "Perpetual / Consol",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Level perpetual coupon valued as C/y at a long-run par yield. No call feature.",
    },
    "inflation_linked_bond": {
        "name": "Inflation-Linked Bond",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["curve_pair_matches_flat_when_breakeven_flat", "breakeven_round_trip"],
        "notes": (
            "Phase 1: priced off a (nominal, real) curve pair with curve-implied "
            "breakeven index projection (OFZ-IN real curve); the legacy flat "
            "assumed-inflation mode remains for back-compat. No seasonality, "
            "no indexation lag."
        ),
    },
    "frn": {
        "name": "Floating Rate Note",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": [],
        "notes": "No par-reset logic. No forward coupon. No projection curve. Replace before production use.",
    },
    "irs": {
        "name": "Interest Rate Swap",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["npv_zero_at_fair_rate", "single_curve_telescope"],
        "notes": (
            "Float leg = simple projected forwards discounted on the discount curve "
            "(2026-06: replaced the P(0.001)-P(T) telescope hack); dual-curve via "
            "proj_curve. No fixing lag / schedule / day count."
        ),
    },
    "capfloor": {
        "name": "Cap / Floor / Swaption",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["cap_floor_swap_parity"],
        "notes": (
            "Black-76 on the SIMPLE forward with vol at caplet expiry T1 (2026-06: was "
            "continuous forward + vol at T2, which broke cap-floor=swap parity). "
            "No vol surface by tenor/strike. First caplet (T1=0) prices at intrinsic."
        ),
    },
    "basis_swap": {
        "name": "Basis Swap",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["fair_spread_matches_curve_basis", "npv_zero_at_fair_spread"],
        "notes": (
            "Float vs float + spread from simple projected forwards on each index curve, "
            "common discount curve (2026-06: previous FRN-par construction made "
            "fair_spread identically zero). No reset schedule / day count."
        ),
    },
    "swaption": {
        "name": "European Swaption (Black-76)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Black-76 on the forward swap rate. Single-curve; no swaption vol cube; no smile.",
    },
    "fra": {
        "name": "Forward Rate Agreement",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Simple forward rate from the discount curve. Single-curve; no convexity adjustment.",
    },
    "short_rate": {
        "name": "Short Rate Models (Hull-White / Vasicek / CIR)",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Analytics",
        "tests": [],
        "notes": "Calibration to term structure not validated.",
    },

    # ── FX ────────────────────────────────────────────────
    "fx_forward": {
        "name": "FX Forward",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Interest rate parity. No bid/ask / settlement conventions.",
    },
    "fx_smile": {
        "name": "FX Vol Smile (Malz ATM/RR/BF)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["malz_quote_anchors", "atm_strike_recovers_atm_vol"],
        "notes": (
            "Malz quadratic smile in forward delta from ATM/RR/BF quotes with "
            "fixed-point strike-vol resolution (Phase 1: replaced the linear "
            "placeholder). Single-tenor quotes; no arbitrage-free constraint check."
        ),
    },

    # ── Exotics ───────────────────────────────────────────
    "barrier": {
        "name": "Barrier Options",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["in_out_parity_all_branches", "haug_reference_value", "mc_bgk_cross_check"],
        "notes": (
            "Reiner-Rubinstein/Haug closed form, continuous monitoring. 2026-06 audit: "
            "up-branch table and put-side C/D blocks were wrong and were rewritten; all 16 "
            "type/strike branches now validated against BGK-adjusted MC and in-out parity. "
            "Rebate paid at touch (out) / at expiry (in). Discrete monitoring not supported."
        ),
    },
    "asian": {
        "name": "Asian Options",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": ["geometric_n1_equals_bsm"],
        "notes": "Arithmetic approximation + MC. No geometric exact formula comparison.",
    },
    "digital": {
        "name": "Digital / Cash-or-Nothing",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "European cash/asset digital analytically. Cash digital put gamma sign corrected. Touch: hit probability only.",
    },
    "lookback": {
        "name": "Lookback Options",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["mc_richardson_all_variants", "float_put_fixed_call_identity"],
        "notes": (
            "Goldman-Sosin-Gatto (floating) / Conze-Viswanathan (fixed), continuous "
            "monitoring. 2026-06 audit: floating put and both fixed-strike OTM branches "
            "were mistranscribed and rewritten; all variants incl. seasoned contracts now "
            "validated vs Richardson-extrapolated MC. b=0 handled by epsilon guard."
        ),
    },
    "multi_asset": {
        "name": "Multi-Asset / Rainbow",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": [],
        "notes": "MC with Cholesky. No nearest-PD fallback for correlation matrix.",
    },
    "variance_swap": {
        "name": "Variance Swap",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["flat_smile_recovers_sigma_squared"],
        "notes": (
            "Replication via log-contract (Demeterfi). 2026-06 audit: option strip now "
            "entered at forward value (e^{rT} growth factor was missing, understating "
            "K_var). Recovers sigma^2 exactly on a flat smile incl. dividends. "
            "No discrete monitoring adjustment."
        ),
    },

    # ── Credit ────────────────────────────────────────────
    "cds": {
        "name": "Credit Default Swap (flat hazard)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["npv_zero_at_fair_spread", "implied_hazard_round_trip"],
        "notes": "Flat hazard rate, flat discount rate. For term-structure pricing use cds_curve.",
    },
    "cds_curve": {
        "name": "CDS on Hazard Curve",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["bootstrap_round_trip", "flat_curve_matches_flat_cds"],
        "notes": (
            "Phase 1: piecewise-constant hazard curve bootstrapped from CDS par "
            "spreads (curves.hazard); premium leg with half-period accrual-on-default, "
            "weekly protection-leg integration. Quoted CDS reprice to zero NPV exactly. "
            "No ISDA standard-model conventions (IMM dates, fixed coupon + upfront)."
        ),
    },
    "risky_bond": {
        "name": "Credit-Risky Bond",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["zero_hazard_equals_riskless", "monotone_in_hazard"],
        "notes": (
            "Phase 1: survival-weighted coupons/principal + recovery on default "
            "off the hazard curve; reports credit z-spread, CS01, expected loss. "
            "Links the bond stack to the credit stack. Recovery on face only "
            "(no accrued recovery), no settlement conventions."
        ),
    },
    "cva_dva": {
        "name": "CVA / DVA",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Risk",
        "tests": [],
        "notes": "No exposure simulation. No wrong-way risk. No collateral/netting.",
    },

    # ── Structured ────────────────────────────────────────
    "structured_autocall": {
        "name": "Autocall / Phoenix",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": [],
        "notes": "Path MC. No observation schedule / barrier convention / coupon memory.",
    },
    "cln_ftd": {
        "name": "CLN / FTD",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": [],
        "notes": "Gaussian copula simulation. No calibration to market tranche spreads.",
    },

    # ── Risk ──────────────────────────────────────────────
    "var_parametric": {
        "name": "Parametric VaR (Normal / t)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Risk",
        "tests": ["known_quantile"],
        "notes": "Normal and Student-t. sqrt(h) horizon scaling.",
    },
    "var_historical": {
        "name": "Historical VaR",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Risk",
        "tests": ["known_array_quantile", "es_gte_var"],
        "notes": "Age-weighted quantile fixed. Synthetic data must be marked as Demo.",
    },
    "var_mc": {
        "name": "Monte Carlo VaR",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Risk",
        "tests": [],
        "notes": "GBM returns. Full repricing not implemented.",
    },
    "evt_var": {
        "name": "EVT VaR (GPD tail)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Risk",
        "tests": [],
        "notes": "POT / GPD fit. Requires sufficient tail observations.",
    },
    "portfolio_aggregation": {
        "name": "Portfolio Aggregation",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Portfolio",
        "tests": [],
        "notes": "Greeks mixed units (equity delta ≠ bond DV01 ≠ option delta). No risk-factor mapping.",
    },
}


def get(model_id: str) -> dict:
    entry = dict(MODEL_REGISTRY.get(model_id, {
        "name": model_id,
        "status": ModelStatus.PLACEHOLDER,
        "domain": "Unknown",
        "tests": [],
        "notes": "Not registered.",
    }))
    workflow_layer = "Research" if model_id in ANALYTICS_LAB_MODELS else "Production"
    analytics_lab_only = model_id in ANALYTICS_LAB_MODELS
    entry.setdefault("workflow_layer", workflow_layer)
    entry.setdefault("analytics_lab_only", analytics_lab_only)
    if model_id in PRODUCTION_MODELS:
        entry.setdefault("production_allowed", entry.get("status") in {ModelStatus.VALIDATED, ModelStatus.APPROXIMATION})
    elif analytics_lab_only:
        entry.setdefault("production_allowed", False)
    return entry


def by_domain(domain: str) -> list[tuple[str, dict]]:
    return [(k, v) for k, v in MODEL_REGISTRY.items() if v["domain"] == domain]


def summary() -> dict:
    counts = {s: 0 for s in ModelStatus}
    for v in MODEL_REGISTRY.values():
        counts[v["status"]] += 1
    return counts
