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
    "mc_heston_qe",
    "heston_cf",
    "sabr",
    "garch",
    "short_rate",
    "bates",
    "local_vol_mc",
    "kou",
    "variance_gamma",
    "nig",
    "cgmy",
    "merton_cos",
    "rough_bergomi",
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

    # ── PDE ───────────────────────────────────────────────
    "pde_cn": {
        "name": "Crank-Nicolson PDE",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["european_matches_bsm", "american_matches_crr",
                  "barrier_matches_closed_form", "greeks_from_grid"],
        "notes": (
            "Phase 3: log-spot CN with Rannacher startup, barrier-aligned grids, "
            "projection step for American exercise. European to ~1e-4 of BSM, "
            "American put to ~5e-3 of CRR(2000), KO barriers to <2e-2 of closed "
            "form. Uniform grid; no nonuniform refinement at strike/barrier."
        ),
    },

    # ── Jump diffusion ────────────────────────────────────
    "merton_jump": {
        "name": "Merton Jump-Diffusion",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["lambda_zero_is_bsm", "put_call_parity", "series_matches_mc"],
        "notes": (
            "Phase 3: exact Poisson-mixture series of BSM prices (lognormal "
            "jumps); Greeks as the weighted mixture. Series truncated at 60 "
            "terms with mass check. Jump params are inputs — no calibration."
        ),
    },
    "bates": {
        "name": "Bates (Heston + Jumps)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["lambda_zero_is_heston", "xi_zero_is_merton", "put_call_parity"],
        "notes": (
            "M2 promotion (was Prototype): Gil-Pelaez inversion of the Heston CF "
            "times the compensated jump factor. Validated — degenerates exactly "
            "to Heston (λ=0) and Merton (ξ→0), parity holds. No market "
            "calibration; Analytics Lab only."
        ),
    },

    # ── Monte Carlo ───────────────────────────────────────
    "mc_heston_qe": {
        "name": "Heston Monte Carlo (Andersen QE)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["qe_bias_vs_cf_coarse_steps"],
        "notes": (
            "Phase 3: Andersen (2008) Quadratic-Exponential scheme; exact "
            "conditional moments of v. ~6x smaller bias than Euler-reflection "
            "at 32 steps in validation. No martingale correction term."
        ),
    },
    # ── Lévy / jump (Fourier COS) — M1 ────────────────────
    "kou": {
        "name": "Kou Double-Exponential Jump (COS)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["lambda_zero_is_bsm", "put_call_parity", "cos_vs_mc"],
        "notes": (
            "M1: Kou double-exponential jump-diffusion via the Fourier COS "
            "method. λ=0 recovers BSM; put-call parity to 1e-6. η1>1 enforced "
            "for a finite jump mean. No calibration helper yet."
        ),
    },
    "variance_gamma": {
        "name": "Variance Gamma (COS)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["nu_to_zero_is_bsm", "put_call_parity"],
        "notes": (
            "M1: Variance Gamma via COS. ν→0 recovers BSM; parity to 1e-11. "
            "Pure-jump (no diffusion floor in the standard parametrisation)."
        ),
    },
    "nig": {
        "name": "Normal Inverse Gaussian (COS)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["put_call_parity", "cos_vs_ig_subordinator_mc"],
        "notes": (
            "M1: NIG via COS with the exact martingale drift; parity to 1e-10, "
            "agrees with an IG-subordinator MC. Requires |β|<α."
        ),
    },
    "cgmy": {
        "name": "CGMY / KoBoL (COS)",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Analytics",
        "tests": ["put_call_parity_loose"],
        "notes": (
            "M1: CGMY tempered-stable via COS. Heavy tails — parity ~1e-4 at "
            "N=512/1024 (truncation interval needs c4 widening for Y near 1). "
            "Use VG/NIG for production until the interval is tightened."
        ),
    },
    "local_vol_mc": {
        "name": "Local Vol MC (Dupire)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["flat_surface_is_bsm", "smile_repricing"],
        "notes": (
            "Phase 3: Dupire local vol tabulated on a (spot, time) grid, "
            "vectorized log-Euler MC. Reprices the input smile within MC noise "
            "in validation. Quality depends on the implied-surface smoothness."
        ),
    },
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
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["heston_parity", "xi_to_zero_is_bsm", "heston_mc_vs_cf",
                  "cos_engine_cross_check"],
        "notes": (
            "M2 promotion (was Prototype): Gil-Pelaez inversion (stable form), "
            "dividend-adjusted delta. Validated — put-call parity, ξ→0 ⇒ BSM, "
            "MC(QE) vs CF agree, COS-engine cross-check. Feller not enforced."
        ),
    },
    "sabr": {
        "name": "SABR (Hagan, Obłój z)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["beta1_nu0_is_alpha", "smile_continuity"],
        "notes": (
            "M2 promotion (was Prototype): Hagan implied-vol with the Obłój-style "
            "log-moneyness z. ATM/ν→0 limits validated, smile continuous. No "
            "guaranteed arbitrage-free wings at extreme strikes."
        ),
    },
    "rough_bergomi": {
        "name": "Rough Bergomi (rough vol)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Analytics",
        "tests": ["eta_zero_is_bsm", "put_call_parity_martingale",
                  "rough_skew_steeper_than_smooth"],
        "notes": (
            "M2: rough Bergomi (Bayer-Friz-Gatheral) MC. Volterra integral with "
            "exact per-step kernel integration; terminal-spot martingale "
            "correction (McCrickerd-Pakkanen) restores parity. η→0 ⇒ BSM; rough "
            "(small H) gives a steeper short-dated skew than smooth. Euler spot "
            "with martingale fix — not a full turbocharged scheme."
        ),
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
    "bermudan_swaption": {
        "name": "Bermudan Swaption (Hull-White tree)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["tree_reprices_curve", "single_exercise_matches_jamshidian",
                  "bermudan_geq_european", "cube_calibration_round_trip"],
        "notes": (
            "Phase 2: Hull-White trinomial tree (exact curve fit via Arrow-Debreu), "
            "analytic bond reconstitution at nodes. Single exercise matches "
            "Jamshidian to <0.3%. Stage A: (kappa, sigma) calibrate to the "
            "swaption cube's co-terminal ATM quotes (least squares on Jamshidian "
            "vs Black prices; exact round-trip when quotes are HW-generated)."
        ),
    },
    "g2pp": {
        "name": "G2++ (two-factor Gaussian short rate)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["curve_reprice", "zcb_option_parity", "eta_zero_is_hw1f",
                  "swaption_mc_vs_hw1f", "analytic_vs_mc", "swaption_surface_calibration"],
        "notes": (
            "M3a: two-factor Gaussian short rate (Brigo-Mercurio). Analytic "
            "curve-fitted bond, closed-form ZCB option. M-calib: closed-form "
            "European swaption (BM 4.31, 1D integral with exercise boundary) and "
            "a forward-measure MC (exact terminal (x,y) sampling). Validated: "
            "curve reprice, ZCB parity, η→0 = one-factor Hull-White, analytic == "
            "MC within noise across expiries/strikes, swaption-surface "
            "calibration round-trips (rmse~1e-12, recovers a/σ/b/η/ρ). NOTE the "
            "M3a MC omitted the forward-measure drift means (μx,μy) — small at "
            "short expiries, fixed in M-calib (simulate_factors fwd_measure)."
        ),
    },
    "lmm": {
        "name": "LMM / BGM (LIBOR market model)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["curve_reprice", "caplet_mc_vs_black", "caplet_parity",
                  "swaption_mc_vs_rebonato", "swaption_parity",
                  "decorrelation_lowers_swaption_vol"],
        "notes": (
            "M3b: forward LIBOR market model. Flat per-rate lognormal vol + "
            "exp(-β|ΔT|) correlation; analytic Black caplets by construction. "
            "Terminal T_N-measure Monte Carlo with log-Euler predictor-corrector "
            "drift; swaptions cross-checked vs the Rebonato vol approximation. "
            "Validated: reprices the curve (1e-16), caplet MC == Black within "
            "noise (non-zero drift + numeraire reconstruction), caplet/swaption "
            "parity, swaption MC == Rebonato within noise, decorrelation lowers "
            "the swaption vol below the cap vol. No cap/swaption-surface "
            "calibration yet (flat vol input); time-dependent vol deferred."
        ),
    },
    "bk": {
        "name": "Black-Karasinski (lognormal short rate)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["curve_reprice", "positive_rates", "payer_receiver_parity",
                  "sigma_zero_is_intrinsic", "monotone_in_vol"],
        "notes": (
            "M3c: lognormal short rate r=exp(x), x mean-reverting Gaussian on a "
            "clamped trinomial lattice; time shift fitted per step by root search "
            "(transcendental) so the tree reprices the curve. Rates strictly "
            "positive. European swaption by backward induction (fixed-coupon "
            "bond rollback). Validated: curve reprice 1e-16, positivity, "
            "payer/receiver parity (σ-free), σ→0 = discounted intrinsic, "
            "monotone in vol. No cap/swaption-surface calibration yet."
        ),
    },
    "cheyette": {
        "name": "Cheyette (quasi-Gaussian HJM)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["bond_reconstruction", "const_vol_is_hull_white",
                  "payer_receiver_parity", "monotone_skew"],
        "notes": (
            "M3c: one-factor Markovian (quasi-Gaussian) HJM in state (x,y) with "
            "bond reconstruction off the initial curve. Constant local vol "
            "collapses exactly to one-factor Hull-White; a linear local vol "
            "σ_r=σ(1+skew·x) adds an implied-vol skew the Gaussian models cannot. "
            "MC under the risk-neutral measure (MMA from ∫x dt). Validated: bond "
            "reconstruction at t=0, const-vol swaption MC == HW Jamshidian (z≈0), "
            "payer/receiver parity, monotone skew in the swaption smile. "
            "Skew calibration deferred."
        ),
    },
    "xccy_curve": {
        "name": "Cross-currency basis curve (bootstrap)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["par_reprice", "zero_basis_is_foreign", "basis_sign",
                  "cip_forwards_monotone"],
        "notes": (
            "M3c: bootstraps the foreign basis-adjusted discount curve P_x from "
            "par constant-notional XCCY basis swaps (foreign-OIS-float + basis vs "
            "domestic-OIS-float, principals exchanged). Each tenor's zero rate "
            "solved so the par swap prices to zero; intermediate coupons "
            "interpolated. Validated: input swaps reprice to par (1e-15), zero "
            "basis ⇒ P_x ≡ P_f, basis sign moves P_x correctly, CIP forwards "
            "F=S0·P_x/P_dom monotone. Single-curve float projection; turn-of-year "
            "and tenor-basis effects not modelled."
        ),
    },
    "amc": {
        "name": "AMC (Longstaff-Schwartz) Bermudan swaption",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["single_exercise_matches_jamshidian", "amc_vs_hw_tree",
                  "bermudan_geq_european"],
        "notes": (
            "M4c: American Monte Carlo for Bermudan swaptions — Longstaff-Schwartz "
            "regression (quadratic basis in the co-terminal swap value) on a "
            "Hull-White state carrying the money-market numeraire B=exp(∫r). "
            "Validated: single exercise == Jamshidian within MC noise, multi-date "
            "Bermudan within <0.5% of the HW trinomial tree, Bermudan ≥ European. "
            "Foundation for callable-trade exposure (regression exercise boundary "
            "applied to the XVA cube); callable-exposure wiring not yet shipped."
        ),
    },
    "schwartz_smith": {
        "name": "Schwartz-Smith (two-factor commodity)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["futures_at_zero_is_spot", "gs_ss_equivalence", "mc_matches_futures",
                  "futures_option_parity", "samuelson_vol_decay"],
        "notes": (
            "M5: log spot = short-term mean-reverting χ + equilibrium ABM ξ. "
            "Closed-form log-normal futures ln F=e^{-κτ}χ+ξ+A(τ) and futures "
            "options (Black with the model's term-structure variance). Validated: "
            "F(0,0)=spot, equivalence to Gibson-Schwartz to machine precision, "
            "option MC == closed form, put-call parity, Samuelson vol decay (near "
            "futures more volatile) with long-end vol → σ_ξ. Curve calibration to "
            "an observed futures strip not yet wired (parametric curve only)."
        ),
    },
    "gibson_schwartz": {
        "name": "Gibson-Schwartz (stochastic convenience yield)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["futures_at_zero_is_spot", "gs_ss_equivalence", "mc_matches_futures"],
        "notes": (
            "M5: spot S with mean-reverting stochastic convenience yield δ; "
            "closed-form futures F=S·exp(C(τ)-δB(τ)). Mathematically equivalent "
            "to Schwartz-Smith (to_schwartz_smith mapping). Validated: F(0,0)=spot, "
            "GS futures/options == SS to machine precision, Euler MC E^Q[S_T] == "
            "closed-form futures. Convenience-yield/curve calibration deferred."
        ),
    },
    "baw": {
        "name": "Barone-Adesi-Whaley (American approx)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["geq_european", "no_dividend_call_is_european", "matches_binomial"],
        "notes": (
            "M6: quadratic American approximation — European value plus an "
            "early-exercise premium A·(S/S*)^q from the critical price S* (solved "
            "by Brent). Validated: ≥ European, a no-dividend call == European, "
            "within ~0.2% of the binomial American reference. Closed-form, no "
            "lattice/PDE solve."
        ),
    },
    "bjerksund_stensland": {
        "name": "Bjerksund-Stensland 1993 (American approx)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["geq_european", "no_dividend_call_is_european", "matches_binomial"],
        "notes": (
            "M6: flat-exercise-boundary American approximation (φ/ψ functions); "
            "put via the McDonald-Schroder put-call transformation. Validated: ≥ "
            "European, no-dividend call == European, within ~0.5% of the binomial "
            "American reference."
        ),
    },
    "qmc": {
        "name": "Quasi-Monte-Carlo (Sobol)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["european_matches_bs", "geometric_asian_matches_cf",
                  "faster_convergence_than_pseudo"],
        "notes": (
            "M6: scrambled Sobol low-discrepancy QMC. Validated: 1-D European == "
            "Black-Scholes, multi-date geometric Asian == log-normal closed form, "
            "RMSE 1-2 orders of magnitude below pseudo-MC at equal path count. "
            "Randomised (scrambled) for an unbiased estimator + error bar."
        ),
    },
    "adi": {
        "name": "ADI 2-D PDE (two-asset, Douglas)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["exchange_matches_margrabe", "spread_equals_exchange_at_zero"],
        "notes": (
            "M6: Douglas ADI for the two-asset Black-Scholes PDE in log-space — "
            "explicit predictor carrying the cross-derivative ρσ1σ2·U_xy, then two "
            "implicit tridiagonal sweeps. Validated: exchange option == Margrabe "
            "within ~0.07% across moneyness and ρ∈{-0.5,0,0.5}. Prices general "
            "two-asset payoffs (spread/basket/best-of). Heston (S,v) ADI deferred "
            "(degenerate v=0 boundary needs Hout-Foulon; Heston CF is the "
            "production stoch-vol pricer)."
        ),
    },
    "cds_isda": {
        "name": "ISDA CDS Standard Model (upfront)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["par_coupon_zero_upfront", "upfront_spread_roundtrip",
                  "calibrated_par_matches_quote"],
        "notes": (
            "M7: standardised fixed-coupon CDS. Flat hazard calibrated so the "
            "model par spread equals the quote; upfront = (par-coupon)·RPV01 with "
            "accrual-on-default in RPV01. Validated: coupon=par ⇒ zero upfront, "
            "upfront↔spread round-trip, calibrated par reproduces the quote, "
            "credit-triangle limit. Flat-hazard ISDA convention (single quote); "
            "full ISDA date roll/holiday calendar not modelled."
        ),
    },
    "merton_structural": {
        "name": "Merton structural model",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["equity_is_bs_call", "spread_rises_with_leverage_vol",
                  "low_leverage_zero_spread"],
        "notes": (
            "M7: firm asset value GBM; equity = call on assets struck at debt D. "
            "Risk-neutral PD=N(-d2), distance-to-default, credit spread, implied "
            "recovery. Validated: equity == BS call on assets, spread → 0 at low "
            "leverage and rises with leverage/vol."
        ),
    },
    "black_cox": {
        "name": "Black-Cox (first-passage default)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["pd_geq_merton", "barrier_zero_zero_pd"],
        "notes": (
            "M7: first-passage structural default — defaults the first time assets "
            "touch the barrier; PD via the reflection principle. Validated: PD ≥ "
            "Merton terminal-only PD, barrier → 0 ⇒ PD → 0."
        ),
    },
    "kmv": {
        "name": "KMV (distance-to-default / EDF)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["calibration_roundtrip"],
        "notes": (
            "M7: inverts observable equity value/vol to latent (V,σ_V) via the "
            "Merton equations, then distance-to-default and EDF=N(-DD). Validated: "
            "V,σ_V → E,σ_E → V,σ_V round-trips. Empirical EDF mapping not included "
            "(model EDF = N(-DD))."
        ),
    },
    "gaussian_copula": {
        "name": "One-factor Gaussian copula (basket / CDO)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["el_correlation_independent", "tranches_sum_to_el",
                  "recursion_matches_mc", "correlation_skew"],
        "notes": (
            "M7: one-factor Gaussian copula; conditional-independence recursion "
            "for the number-of-defaults distribution integrated over the factor. "
            "kth-to-default and CDO-tranche expected loss. Validated: portfolio EL "
            "correlation-independent (=mean PD·LGD), tranche losses partition back "
            "to it, recursion == MC copula, FTD falls / senior-tranche rises with "
            "ρ (correlation skew). Single factor, homogeneous LGD; base-correlation "
            "calibration and stochastic recovery deferred."
        ),
    },
    "afv_convertible": {
        "name": "AFV (Andersen-Buffum) convertible bond",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["conv_zero_is_defaultable_bond", "lambda_zero_is_convertible",
                  "deep_itm_parity", "price_falls_with_hazard"],
        "notes": (
            "M8: defaultable-equity convertible on a CRR tree — stock jumps to "
            "zero at hazard λ(S)=λ0·(S0/S)^α, holder recovers R·face; risk-neutral "
            "drift compensated for the jump (growth e^{(r-q+λ)Δt}). Validated: "
            "conv_ratio→0 == defaultable straight bond, λ0→0 == no-default "
            "convertible (matches Tsiveriotis-Fernandes), deep ITM → parity, price "
            "falls as the hazard rises. Hazard capped at 10 for S→0. Equity-credit "
            "link unlike the constant-spread TF model."
        ),
    },
    "mbs": {
        "name": "MBS pass-through (PSA prepayment)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["principal_returned", "zero_psa_par", "faster_psa_shorter_wal",
                  "oas_roundtrip"],
        "notes": (
            "M8: amortising mortgage pass-through with a PSA-scaled CPR/SMM "
            "prepayment model; investor cashflows on the net coupon, scheduled + "
            "prepaid principal. Price + WAL; OAS solve. Validated: all principal "
            "returned, 0 PSA prices to par at the net coupon, faster PSA shortens "
            "WAL, price falls with the discount rate, OAS↔price round-trips. "
            "Deterministic prepayment (no rate-path option model / refi burnout)."
        ),
    },
    "frtb_sba": {
        "name": "FRTB Standardised Approach (SBM delta)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Risk",
        "tests": ["single_factor_rw_times_s", "homogeneous_degree_one",
                  "correlation_diversifies", "scenario_max"],
        "notes": (
            "M8: FRTB sensitivities-based method delta charge — WS=RW·s, "
            "intra-bucket ρ and inter-bucket γ aggregation, evaluated under the "
            "three regulatory correlation scenarios (medium/high/low) with the max "
            "taken. Validated: single factor = RW·|s|, homogeneous degree 1, "
            "imperfect correlation diversifies and ρ=1 recovers the sum, scenario "
            "max ≥ medium. Delta only (vega/curvature and DRC/RRAO deferred)."
        ),
    },
    "cms_swap": {
        "name": "CMS Swap (convexity-adjusted)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["zero_vol_no_adjustment", "adjustment_positive_increasing",
                  "timing_adjustment_sign"],
        "notes": (
            "Phase 2: CMS coupons = forward swap rate + Hull bond-yield convexity "
            "adjustment. Stage A: payment-lag timing adjustment "
            "(-S·σ_S·σ_F·ρ·T·τF/(1+τF), forward vol proxied by swap vol) and "
            "per-fixing ATM vols from the swaption cube. Smile in CMS coupons "
            "not yet used (ATM only)."
        ),
    },
    "swaption_cube": {
        "name": "Swaption Cube / Caplet Strip (SABR)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Market",
        "tests": ["sabr_recalibration_round_trip", "atm_interpolation",
                  "strike_query_matches_quotes"],
        "notes": (
            "Stage A: ATM matrix with bilinear (expiry, tenor) interpolation + "
            "per-node SABR smiles (beta=0.5) recentred on the ATM level for "
            "strike queries; caplet strip variance-flat in expiry. Demo quotes "
            "manual — no market IRVOL source yet (roadmap D1)."
        ),
    },
    "inflation_swap": {
        "name": "Inflation Swaps (ZCIIS / YoYIIS)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["zciis_fair_equals_breakeven", "npv_zero_at_fair"],
        "notes": (
            "Phase 2: priced off the (nominal, real) curve pair; ZCIIS fair rate "
            "equals the curve breakeven by construction. YoY legs from forward "
            "breakevens WITHOUT the YoY convexity adjustment (needs inflation vol)."
        ),
    },
    "convertible_bond": {
        "name": "Convertible Bond (Tsiveriotis-Fernandes)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["otm_equals_risky_floor", "itm_equals_parity",
                  "riskless_limit", "call_put_bounds"],
        "notes": (
            "Phase 2: TF equity/debt split on a CRR tree with curve-consistent "
            "step discounting; voluntary conversion, issuer call with forced "
            "conversion, holder put, discrete coupons. Bond floor matches the "
            "straight bond at r+cs exactly. No soft-call triggers, no stock "
            "borrow cost, flat credit spread."
        ),
    },

    # ── FX ────────────────────────────────────────────────
    "fx_forward": {
        "name": "FX Forward",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": [],
        "notes": "Interest rate parity. No bid/ask / settlement conventions.",
    },
    "ndf": {
        "name": "Non-Deliverable Forward",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["domestic_settle_equals_deliverable", "npv_zero_at_forward"],
        "notes": (
            "Phase 2: cash-settled FX forward. Foreign settlement uses the exact "
            "change-of-numeraire result E_f[1/S_T] = 1/F (no convexity, no vol "
            "input). No fixing-source / settlement-lag conventions."
        ),
    },
    "xccy_swap": {
        "name": "Cross-Currency Swap",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Pricing",
        "tests": ["flat_same_curves_fair_basis_zero", "fair_basis_zeroes_npv"],
        "notes": (
            "Phase 2: constant-notional XCCY (float-float basis / fixed-fixed), "
            "simple projected forwards per leg, notional exchange, basis spread on "
            "the domestic leg. No mark-to-market notional resets, no XCCY basis "
            "curve bootstrap (spread is an input)."
        ),
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
    "structured_basket_note": {
        "name": "Basket Structured Note (real underlyings)",
        "status": ModelStatus.PROTOTYPE,
        "domain": "Pricing",
        "tests": ["par_at_fair_participation", "protection_floors_capital"],
        "notes": (
            "Correlated GBM on real equities/bonds/indices resolved from the market "
            "store (spot, historical vol, dividend/carry income, empirical correlation). "
            "Wrapper: principal protection, guaranteed coupon, participation, cap, "
            "worst-of/average basket. No vol skew/term structure, flat rates, bonds "
            "proxied as low-vol carry assets (no full cashflow model)."
        ),
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
        "notes": "GBM returns. For full repricing use var_full_reprice.",
    },
    "var_full_reprice": {
        "name": "Full-Reprice Historical VaR",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Risk",
        "tests": ["linear_position_matches_historical", "option_convexity_sign"],
        "notes": (
            "Phase 4: joint historical factor scenarios (equity, rates, vol, FX) "
            "applied to position params with FULL repricing through the actual "
            "pricers — option convexity enters the P&L distribution exactly. "
            "4-factor parameter map; no per-name factor granularity yet."
        ),
    },
    "cva_exposure": {
        "name": "CVA from Simulated Exposure",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Risk",
        "tests": ["par_swap_epe_hump", "cva_increasing_in_hazard"],
        "notes": (
            "Phase 4: Hull-White exposure simulation for IRS (analytic node "
            "revaluation), GBM for FX forwards; EPE/ENE/PFE95/99 profiles; "
            "CVA/DVA integrate the profile against Phase-1 hazard curves. "
            "No netting sets, no collateral/CSA, no wrong-way risk."
        ),
    },
    "xva_suite": {
        "name": "XVA suite (netting / CSA / CVA-DVA-FVA-MVA-KVA)",
        "status": ModelStatus.APPROXIMATION,
        "domain": "Risk",
        "tests": ["netting_benefit", "collateral_reduces_exposure",
                  "zero_spread_zero_xva", "xva_linear_in_spread",
                  "single_trade_matches_exposure_profile"],
        "notes": (
            "M4: path-wise Hull-White MtM cube for an IRS netting set (shared "
            "rate path -> correct netting), two-way CSA variation margin "
            "(threshold/MTA/margin-period-of-risk with time-interpolated lag), "
            "dynamic initial margin (q99 of the MPoR value change). Suite: CVA/"
            "DVA (vs Phase-1 hazard), FVA (FCA-FBA), MVA (IM funding), KVA "
            "(CCR capital = RW·8%·α·EffectiveEPE). Validated: offsetting trades "
            "net to ~0, zero threshold+MPoR collateralises to ~0, each "
            "adjustment is 0 at zero spread and linear in it, single-trade EPE "
            "matches risk/exposure.py. Single rate factor (no FX/equity in the "
            "netting set yet), no wrong-way risk, IM is a model proxy not SIMM."
        ),
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
    # M0: enrich with taxonomy axes (asset_class / model_family / method / kind)
    try:
        from models.taxonomy import classify
        for k, v in classify(model_id).items():
            entry.setdefault(k, v)
    except Exception:
        pass
    return entry


def by_domain(domain: str) -> list[tuple[str, dict]]:
    return [(k, v) for k, v in MODEL_REGISTRY.items() if v["domain"] == domain]


def by_asset_class(asset_class: str) -> list[tuple[str, dict]]:
    """M0: group models by taxonomy asset class (rates/credit/equity/...)."""
    from models.taxonomy import classify
    return [(k, get(k)) for k in MODEL_REGISTRY
            if classify(k)["asset_class"] == asset_class]


def by_model_family(family: str) -> list[tuple[str, dict]]:
    from models.taxonomy import classify
    return [(k, get(k)) for k in MODEL_REGISTRY
            if classify(k)["model_family"] == family]


def summary() -> dict:
    counts = {s: 0 for s in ModelStatus}
    for v in MODEL_REGISTRY.values():
        counts[v["status"]] += 1
    return counts


# ── M0: status promotion rule (STATE_AUDIT F1) ───────────
def can_promote_to_validated(model_id: str) -> bool:
    """
    A model is eligible for Validated when it (a) is at least Approximation and
    (b) carries registered tests (identity/benchmark). Eligibility only —
    promotion stays an explicit registry edit so it is reviewable.
    """
    entry = MODEL_REGISTRY.get(model_id)
    if not entry:
        return False
    return (entry["status"] in {ModelStatus.APPROXIMATION, ModelStatus.VALIDATED}
            and len(entry.get("tests", [])) > 0)


def validation_candidates() -> list[str]:
    """Approximation models with tests — ready for a Validated review."""
    return [m for m, e in MODEL_REGISTRY.items()
            if e["status"] == ModelStatus.APPROXIMATION and len(e.get("tests", [])) > 0]
