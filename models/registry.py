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


MODEL_REGISTRY: dict[str, dict] = {
    # ── Equity / FX options ───────────────────────────────
    "black_scholes": {
        "name": "Black-Scholes / Merton",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["put_call_parity", "atm_call_known_value"],
        "notes": "European vanilla only. No discrete dividends. Edge-cases (T→0, σ→0) need hardening.",
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
        "notes": "Antithetic + moment matching + control variate. Greeks via common random numbers.",
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
        "notes": "CF integration via scipy quad. Feller condition not enforced. No benchmark test.",
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
        "tests": [],
        "notes": "No settlement date / day count / accrued interest. Schedule from T*freq. DV01 via duration.",
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
        "tests": [],
        "notes": "Single-curve. No dual-curve OIS discounting. No fixing lag / schedule / day count.",
    },
    "capfloor": {
        "name": "Cap / Floor / Swaption",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Black-76. No vol surface by tenor/strike. T1=0 caplet degenerates.",
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
        "name": "FX Vol Smile",
        "status": ModelStatus.PLACEHOLDER,
        "domain": "Market",
        "tests": [],
        "notes": "Smile is a linear placeholder. Replace with ATM/RR/BF inputs.",
    },

    # ── Exotics ───────────────────────────────────────────
    "barrier": {
        "name": "Barrier Options",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": [],
        "notes": "Analytical formulas for continuous monitoring. Discrete not supported.",
    },
    "asian": {
        "name": "Asian Options",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": [],
        "notes": "Arithmetic approximation + MC. No geometric exact formula comparison.",
    },
    "digital": {
        "name": "Digital / Cash-or-Nothing",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "European cash/asset digital analytically. Touch: hit probability only.",
    },
    "lookback": {
        "name": "Lookback Options",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": [],
        "notes": "Analytical formulas require validation against MC.",
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
        "tests": [],
        "notes": "Replication via log-contract. No discrete monitoring adjustment.",
    },

    # ── Credit ────────────────────────────────────────────
    "cds": {
        "name": "Credit Default Swap",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Flat hazard rate from spread/(1-R). No bootstrap from term structure.",
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
    return MODEL_REGISTRY.get(model_id, {
        "name": model_id,
        "status": ModelStatus.PLACEHOLDER,
        "domain": "Unknown",
        "tests": [],
        "notes": "Not registered.",
    })


def by_domain(domain: str) -> list[tuple[str, dict]]:
    return [(k, v) for k, v in MODEL_REGISTRY.items() if v["domain"] == domain]


def summary() -> dict:
    counts = {s: 0 for s in ModelStatus}
    for v in MODEL_REGISTRY.values():
        counts[v["status"]] += 1
    return counts
