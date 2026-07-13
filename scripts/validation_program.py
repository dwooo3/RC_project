"""Программа валидации моделей: Approximation → Validated.

Правило реестра: кандидат = Approximation + зарегистрированные тесты
(can_promote_to_validated). Промоушен — явная правка registry.py, чтобы
оставался ревьюабельным; этот скрипт — повторяемая проверка, что статусы
не разъезжаются с тестовой базой.

    /usr/local/bin/python3.14 scripts/validation_program.py            # отчёт
    /usr/local/bin/python3.14 scripts/validation_program.py --run      # + pytest

Критерий промоушена (batch-подход): модель Validated, если её тесты включают
ВНЕШНИЙ бенчмарк или точное тождество (Haug-референсы, паритеты, схождение к
закрытой форме, roundtrip-калибровки, MC==analytic), и весь пул тестов зелёный.
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.registry import MODEL_REGISTRY, ModelStatus, validation_candidates  # noqa: E402

PY = sys.executable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# model_id -> pytest paths covering its registered benchmarks
TEST_MAP: dict[str, list[str]] = {
    "black_scholes": ["tests/test_black_scholes.py", "tests/test_validation_identities.py"],
    "garman_kohlhagen": ["tests/test_validation_identities.py"],
    "barrier": ["tests/test_validation_identities.py"],
    "lookback": ["tests/test_validation_identities.py"],
    "variance_swap": ["tests/test_validation_identities.py"],
    "merton_jump": ["tests/test_validation_identities.py"],
    "heston_cf": ["tests/test_m1_levy_fourier.py", "tests/test_validation_identities.py"],
    "fixed_bond": ["tests/test_fixed_income_pricing_service.py",
                   "tests/test_fi_production_validation.py"],
    "irs": ["tests/test_validation_identities.py"],
    "cds_isda": ["tests/test_m7_credit.py"],
    "bermudan_swaption": ["tests/test_m3c_rate_models.py", "tests/test_mc_rate_calibration.py"],
    "g2pp": ["tests/test_m3_g2pp.py"],
    "frn": ["tests/test_frn.py"],
    # batch-2 coverage
    "kou": ["tests/test_m1_levy_fourier.py"],
    "variance_gamma": ["tests/test_m1_levy_fourier.py"],
    "nig": ["tests/test_m1_levy_fourier.py"],
    "cgmy": ["tests/test_m1_levy_fourier.py"],
    "rough_bergomi": ["tests/test_m2_rough_vol.py"],
    "lmm": ["tests/test_m3b_lmm.py"],
    "bk": ["tests/test_m3c_rate_models.py"],
    "cheyette": ["tests/test_m3c_rate_models.py"],
    "xccy_curve": ["tests/test_m3c_rate_models.py"],
    "amc": ["tests/test_m4_xva.py"],
    "schwartz_smith": ["tests/test_m5_commodity.py"],
    "gibson_schwartz": ["tests/test_m5_commodity.py"],
    "baw": ["tests/test_m6_numerical.py"],
    "bjerksund_stensland": ["tests/test_m6_numerical.py"],
    "qmc": ["tests/test_m6_numerical.py"],
    "adi": ["tests/test_m6_numerical.py"],
    "merton_structural": ["tests/test_m7_credit.py"],
    "gaussian_copula": ["tests/test_m7_credit.py"],
    "afv_convertible": ["tests/test_m8_niche.py"],
    "mbs": ["tests/test_m8_niche.py"],
    "var_full_reprice": ["tests/test_marketrisk_api.py"],
    # batch-3/4 coverage
    "black76": ["tests/test_batch3_benchmarks.py"],
    "bachelier": ["tests/test_batch3_benchmarks.py"],
    "binomial_lr": ["tests/test_batch3_benchmarks.py"],
    "trinomial": ["tests/test_batch3_benchmarks.py"],
    "binomial_tian": ["tests/test_batch3_benchmarks.py"],
    "mc_heston_qe": ["tests/test_batch3_benchmarks.py"],
    "sabr": ["tests/test_batch3_benchmarks.py"],
    "digital": ["tests/test_batch3_benchmarks.py"],
    "fx_forward": ["tests/test_batch3_benchmarks.py"],
    "discrete_div_bsm": ["tests/test_batch3_benchmarks.py"],
    "commodity_seasonal": ["tests/test_batch3_benchmarks.py"],
    "swap_market_model": ["tests/test_batch3_benchmarks.py"],
    "evt_var": ["tests/test_batch3_benchmarks.py"],
    "var_mc": ["tests/test_batch3_benchmarks.py"],
    "tarn": ["tests/test_batch4_benchmarks.py"],
    "accumulator": ["tests/test_batch4_benchmarks.py"],
    "asian": ["tests/test_batch4_benchmarks.py"],
    # batch-5: один файл покрывает весь пул
    **{m: ["tests/test_batch5_benchmarks.py"] for m in (
        "custom_bond", "step_bond", "amortizing_bond", "perpetual_bond",
        "mm_deposit", "treasury_bill", "commercial_paper", "repo",
        "stir_future", "bond_future", "swaption", "fra", "garch",
        "mc_lsm", "mc_heston", "multi_asset", "callable_bond",
        "structured_autocall")},
    # Exact executable evidence for the remaining Validated models.  Keep
    # these as pytest node IDs (not broad files): a green unrelated test in
    # the same module must not be able to stand in for the registered model.
    "binomial_crr": [
        "tests/test_trees.py::test_crr_no_recursion_european",
        "tests/test_trees.py::test_crr_european_converges_to_bsm",
        "tests/test_trees.py::test_crr_american_put_ge_european_put",
    ],
    "pde_cn": [
        "tests/test_phase3_engines.py::test_pde_european_matches_bsm",
        "tests/test_phase3_engines.py::test_pde_american_matches_crr",
        "tests/test_phase3_engines.py::test_pde_barrier_matches_closed_form",
    ],
    "bates": [
        "tests/test_phase3_engines.py::test_bates_degenerate_limits",
        "tests/test_phase3_engines.py::test_bates_parity_and_lab_gating",
    ],
    "local_vol_mc": [
        "tests/test_phase3_engines.py::test_local_vol_flat_surface_is_bsm",
        "tests/test_phase3_engines.py::test_local_vol_reprices_smile",
    ],
    "mc_gbm": ["tests/test_monte_carlo.py::test_mc_european_call_vs_bsm"],
    "inflation_linked_bond": [
        "tests/test_phase1_market_data_pricing.py::test_breakeven_round_trip",
        "tests/test_phase1_market_data_pricing.py::test_linker_curve_pair_matches_flat_when_breakeven_flat",
    ],
    "capfloor": [
        "tests/test_validation_identities.py::test_cap_floor_swap_parity",
    ],
    "basis_swap": [
        "tests/test_validation_identities.py::test_basis_swap_reflects_curve_basis",
    ],
    "displaced_diffusion": [
        "tests/test_gap_closing.py::test_displaced_diffusion_zero_shift",
        "tests/test_batch3_benchmarks.py::test_displaced_diffusion_prices_negative_forward",
    ],
    "cev": [
        "tests/test_gap_closing.py::test_cev_beta_one_is_bsm",
        "tests/test_gap_closing.py::test_cev_put_call_parity",
    ],
    "binomial_jr": [
        "tests/test_gap_closing.py::test_binomial_converges_to_bsm[binomial_jarrow_rudd]",
        "tests/test_gap_closing.py::test_jr_american_ge_european",
    ],
    "lognormal_mixture": [
        "tests/test_gap_closing.py::test_mixture_single_and_convexity",
    ],
    "carr_madan": [
        "tests/test_gap_closing.py::test_carr_madan_matches_bsm",
        "tests/test_gap_closing.py::test_carr_madan_matches_heston",
        "tests/test_gap_closing.py::test_carr_madan_parity_and_service",
    ],
    "vanna_volga": [
        "tests/test_gap_closing.py::test_vanna_volga_reproduces_pillars",
        "tests/test_gap_closing.py::test_vanna_volga_flat_is_flat",
    ],
    "t_copula": [
        "tests/test_gap_closing.py::test_t_copula_df_to_inf_is_gaussian",
        "tests/test_gap_closing.py::test_t_copula_tail_dependence",
    ],
    "clayton_copula": [
        "tests/test_gap_closing.py::test_clayton_lower_tail_dependence",
    ],
    "pilipovic": [
        "tests/test_gap_closing.py::test_commodity_seasonality_and_pilipovic",
    ],
    "abs": ["tests/test_gap_closing.py::test_abs_waterfall"],
    "jarrow_yildirim": ["tests/test_gap_closing.py::test_jarrow_yildirim"],
    "cva_wwr": ["tests/test_gap_closing.py::test_cva_wrong_way"],
    "frtb_ima": ["tests/test_gap_closing.py::test_frtb_ima_es"],
    "copula_var": ["tests/test_gap_closing.py::test_copula_var_ordering"],
    "black_cox": ["tests/test_m7_credit.py::test_black_cox_pd_geq_merton"],
    "kmv": ["tests/test_m7_credit.py::test_kmv_calibration_roundtrip"],
    "frtb_sba": [
        "tests/test_m8_niche.py::test_frtb_single_factor",
        "tests/test_m8_niche.py::test_frtb_homogeneous_degree_one",
        "tests/test_m8_niche.py::test_frtb_correlation_diversifies",
        "tests/test_m8_niche.py::test_frtb_scenario_max",
        "tests/test_task3_calibration_numerical.py::test_frtb_curvature_nonneg_and_scales",
        "tests/test_task3_calibration_numerical.py::test_frtb_drc_hedge_benefit",
        "tests/test_task3_calibration_numerical.py::test_frtb_total_sums_components",
    ],
    "cms_swap": [
        "tests/test_phase2_new_instruments.py::test_cms_adjustment_properties",
        "tests/test_stage_a_rates_vol.py::test_cms_timing_adjustment_properties",
    ],
    "swaption_cube": [
        "tests/test_stage_a_rates_vol.py::test_sabr_slice_recalibration_round_trip",
        "tests/test_stage_a_rates_vol.py::test_cube_atm_interpolation_and_strike_query",
    ],
    "inflation_swap": [
        "tests/test_phase2_new_instruments.py::test_zciis_fair_equals_breakeven",
    ],
    "convertible_bond": [
        "tests/test_phase2_new_instruments.py::test_convertible_limits",
        "tests/test_phase2_new_instruments.py::test_convertible_bounds_and_features",
    ],
    "ndf": [
        "tests/test_phase2_new_instruments.py::test_ndf_zero_at_forward_and_settle_equivalence",
    ],
    "xccy_swap": [
        "tests/test_phase2_new_instruments.py::test_xccy_same_curves_zero_basis",
        "tests/test_phase2_new_instruments.py::test_xccy_fair_basis_zeroes_npv",
    ],
    "fx_smile": [
        "tests/test_phase1_market_data_pricing.py::test_malz_smile_quote_anchors",
        "tests/test_phase1_market_data_pricing.py::test_fx_vol_for_strike_consistency",
    ],
    "cds": [
        "tests/test_validation_identities.py::test_cds_fair_spread_consistency",
    ],
    "equity_forward": [
        "tests/test_stage5_products.py::test_cost_of_carry_identity",
        "tests/test_stage5_products.py::test_npv_zero_at_fair_forward",
    ],
    "dividend_swap": [
        "tests/test_stage5_products.py::test_expected_div_identity",
        "tests/test_stage5_products.py::test_npv_zero_at_fair_strike",
    ],
    "asset_swap": [
        "tests/test_stage5_products.py::test_asw_zero_at_riskfree_value",
        "tests/test_stage5_products.py::test_spread_sign",
    ],
    "equity_future": [
        "tests/test_stage5_products.py::test_future_fair_price_identity",
        "tests/test_stage5_products.py::test_future_delta_exceeds_forward",
    ],
    "term_deposit": [
        "tests/test_stage5_products.py::test_deposit_npv_zero_at_fair_rate",
        "tests/test_stage5_products.py::test_deposit_loan_mirror",
    ],
    "cds_curve": [
        "tests/test_phase1_market_data_pricing.py::test_bootstrap_round_trip",
        "tests/test_phase1_market_data_pricing.py::test_cds_curve_flat_matches_legacy_flat",
    ],
    "risky_bond": [
        "tests/test_phase1_market_data_pricing.py::test_risky_bond_zero_hazard_equals_riskless",
        "tests/test_phase1_market_data_pricing.py::test_risky_bond_monotonicity",
    ],
    "var_parametric": [
        "tests/test_batch3_benchmarks.py::test_mc_var_matches_parametric_on_normal",
    ],
    "var_historical": [
        "tests/test_var.py::test_historical_var_known_small_array_positive_loss_convention",
        "tests/test_var.py::test_all_var_methods_es_ge_var",
    ],
    "cva_exposure": [
        "tests/test_phase4_platform.py::test_irs_exposure_profile_shape",
        "tests/test_phase4_platform.py::test_cva_properties",
    ],
    "xva_suite": [
        "tests/test_m4_xva.py::test_single_trade_matches_exposure_profile",
        "tests/test_m4_xva.py::test_netting_benefit",
        "tests/test_m4_xva.py::test_zero_spread_zero_adjustments",
        "tests/test_m4_xva.py::test_fva_mva_linear_in_funding_spread",
        "tests/test_m4_xva.py::test_collateral_reduces_cva_and_fva",
    ],
}

# Batch 4 (2026-07): платёжные разложения (tests/test_batch4_benchmarks.py) —
# TARN == стрип путов, accumulator == форварды−путы, asian == Turnbull-Wakeman.
PROMOTED_BATCH_4 = ["tarn", "accumulator", "asian"]

# Batch 5 (2026-07): DCF-тождества + Prototype-референсы
# (tests/test_batch5_benchmarks.py). Попутно исправлен Stulz best-of-cash
# (потерянное слагаемое K·df — найдено бенчмарком MC==Stulz).
PROMOTED_BATCH_5 = [
    "custom_bond", "step_bond", "amortizing_bond", "perpetual_bond",
    "mm_deposit", "treasury_bill", "commercial_paper", "repo", "stir_future",
    "bond_future", "swaption", "fra", "garch",
    "mc_lsm", "mc_heston", "multi_asset", "callable_bond", "structured_autocall",
]

# Batch 3 (2026-07): бенчмарки ДОПИСАНЫ (tests/test_batch3_benchmarks.py) —
# известные значения, точные тождества, симметрии, GPD-квантили.
PROMOTED_BATCH_3 = [
    "black76", "bachelier", "binomial_lr", "trinomial", "binomial_jr",
    "binomial_tian", "mc_heston_qe", "sabr", "frn", "displaced_diffusion",
    "cev", "discrete_div_bsm", "lognormal_mixture", "carr_madan",
    "vanna_volga", "t_copula", "clayton_copula", "commodity_seasonal",
    "pilipovic", "swap_market_model", "abs", "jarrow_yildirim", "cva_wwr",
    "frtb_ima", "frtb_sba", "copula_var", "swaption_cube", "cms_swap",
    "ndf", "xccy_swap", "fx_smile", "cva_exposure", "xva_suite",
    "evt_var", "var_mc", "digital", "fx_forward", "black_cox", "kmv",
]

# Batch 2 (2026-07): >=2 точных тождества/референса на модель.
PROMOTED_BATCH_2 = [
    "binomial_crr", "pde_cn", "bates", "kou", "variance_gamma", "nig", "cgmy",
    "mc_gbm", "local_vol_mc", "rough_bergomi", "lmm", "bk", "cheyette",
    "xccy_curve", "amc", "baw", "bjerksund_stensland", "qmc", "adi", "cds",
    "cds_curve", "risky_bond", "merton_structural", "gaussian_copula",
    "schwartz_smith", "gibson_schwartz", "convertible_bond", "afv_convertible",
    "mbs", "inflation_linked_bond", "inflation_swap", "capfloor", "basis_swap",
    "var_parametric", "var_historical", "var_full_reprice",
]

# Batch 1 (2026-07): промоутнуты — внешний бенчмарк / точное тождество.
PROMOTED_BATCH_1 = [
    "black_scholes",       # put-call parity + известное ATM-значение
    "garman_kohlhagen",    # parity (FX-частный случай BSM)
    "barrier",             # Haug reference values + BGK-MC + in-out parity (16 веток)
    "lookback",            # закрытые формы vs Richardson-MC, все варианты
    "variance_swap",       # точное восстановление sigma^2 на флэт-смайле
    "merton_jump",         # Poisson-серия == MC, lambda=0 == BSM
    "heston_cf",           # parity, xi->0 == BSM, MC(QE) == CF, COS cross-check
    "fixed_bond",          # day-count референсы, clean/dirty consistency
    "irs",                 # NPV=0 at fair, single-curve telescope
    "cds_isda",            # par-coupon => zero upfront, roundtrips
    "bermudan_swaption",   # single exercise == Jamshidian <0.3%, cube roundtrip
    "g2pp",                # curve reprice, eta->0 == HW1F, analytic == MC
]


def _evidence_file(selector: str) -> str:
    """Return the filesystem part of a pytest path/node selector."""
    return selector.split("::", 1)[0]


def _evidence_exists(selector: str) -> bool:
    return os.path.isfile(os.path.join(ROOT, _evidence_file(selector)))


def check_consistency() -> list[str]:
    """Validated-модель обязана иметь исполняемое evidence.

    Одних текстовых имён в ``registry[model]["tests"]`` недостаточно:
    нужен непустой ``TEST_MAP`` и каждый указанный pytest-файл должен
    существовать. Это не даёт gate пройти с нейтральным ``None``.
    """
    problems = []
    for mid, entry in MODEL_REGISTRY.items():
        if entry["status"] != ModelStatus.VALIDATED:
            continue
        if not entry.get("tests"):
            problems.append(f"{mid}: Validated без зарегистрированного evidence")
        paths = TEST_MAP.get(mid)
        if not paths:
            problems.append(f"{mid}: Validated без TEST_MAP к исполняемому evidence")
            continue
        missing = [selector for selector in paths
                   if not _evidence_exists(selector)]
        if missing:
            problems.append(
                f"{mid}: TEST_MAP ссылается на отсутствующее evidence: "
                + ", ".join(missing)
            )
    for batch, ids in (("batch-1", PROMOTED_BATCH_1), ("batch-2", PROMOTED_BATCH_2),
                       ("batch-3", PROMOTED_BATCH_3), ("batch-4", PROMOTED_BATCH_4),
                       ("batch-5", PROMOTED_BATCH_5)):
        for mid in ids:
            if MODEL_REGISTRY[mid]["status"] != ModelStatus.VALIDATED:
                problems.append(f"{mid}: в {batch}, но статус "
                                f"{MODEL_REGISTRY[mid]['status'].value}")
    return problems


def run_tests(model_ids: list[str]) -> dict[str, bool]:
    """Run the mapped evidence with a fast green path.

    Most models share benchmark files, so launching pytest independently for
    every model repeats the same evidence dozens of times.  Run the union once;
    only if it fails, rerun model-by-model to identify the affected mappings.
    """
    results: dict[str, bool] = {}
    runnable: dict[str, list[str]] = {}
    for mid in model_ids:
        paths = TEST_MAP.get(mid)
        if not paths or any(not _evidence_exists(selector)
                            for selector in paths):
            results[mid] = False
            continue
        runnable[mid] = paths

    if not runnable:
        return results

    selectors = list(dict.fromkeys(
        selector for paths in runnable.values() for selector in paths))
    proc = subprocess.run([PY, "-m", "pytest", "-q",
                           "-W", "error::RuntimeWarning", *selectors],
                          cwd=ROOT, capture_output=True, text=True)
    if proc.returncode == 0:
        results.update({mid: True for mid in runnable})
        return results

    # Red path: trade speed for actionable per-model diagnostics.
    for mid, paths in runnable.items():
        isolated = subprocess.run(
            [PY, "-m", "pytest", "-q", "-W", "error::RuntimeWarning", *paths],
            cwd=ROOT, capture_output=True, text=True)
        results[mid] = isolated.returncode == 0
    return results


def main() -> None:
    candidates = validation_candidates()
    validated = [m for m, e in MODEL_REGISTRY.items()
                 if e["status"] == ModelStatus.VALIDATED]
    print(f"Validated: {len(validated)} | кандидатов (Approximation+tests): "
          f"{len(candidates)}")

    problems = check_consistency()
    if problems:
        print("\n⚠ Несогласованности:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("Согласованность реестра: ok")

    if "--run" in sys.argv:
        print(f"\nПрогон evidence всех Validated-моделей ({len(validated)}):")
        results = run_tests(validated)
        bad = [m for m, ok in results.items() if not ok]
        for mid, ok in results.items():
            mark = "✓" if ok else "✗"
            print(f"  {mark} {mid}")
        if bad:
            print(f"\n✗ {len(bad)} моделей с падающими бенчмарками — статус "
                  f"Validated нужно ОТОЗВАТЬ")
            sys.exit(1)
        print("\nEvidence всех Validated-моделей зелёный.")

    remaining = [m for m in candidates if m not in PROMOTED_BATCH_1]
    print(f"\nСледующие кандидаты ({len(remaining)}): "
          + ", ".join(remaining[:15]) + " …")


if __name__ == "__main__":
    main()
