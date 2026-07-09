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

PY = "/usr/local/bin/python3.14"
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
}

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


def check_consistency() -> list[str]:
    """Validated-модель обязана иметь тесты; промоутнутые — статус Validated."""
    problems = []
    for mid, entry in MODEL_REGISTRY.items():
        if entry["status"] == ModelStatus.VALIDATED and not entry.get("tests"):
            problems.append(f"{mid}: Validated без зарегистрированных тестов")
    for batch, ids in (("batch-1", PROMOTED_BATCH_1), ("batch-2", PROMOTED_BATCH_2)):
        for mid in ids:
            if MODEL_REGISTRY[mid]["status"] != ModelStatus.VALIDATED:
                problems.append(f"{mid}: в {batch}, но статус "
                                f"{MODEL_REGISTRY[mid]['status'].value}")
    return problems


def run_tests(model_ids: list[str]) -> dict[str, bool]:
    results = {}
    for mid in model_ids:
        paths = TEST_MAP.get(mid)
        if not paths:
            results[mid] = None
            continue
        proc = subprocess.run([PY, "-m", "pytest", "-q", *paths],
                              cwd=ROOT, capture_output=True, text=True)
        results[mid] = proc.returncode == 0
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
        promoted = PROMOTED_BATCH_1 + PROMOTED_BATCH_2
        print(f"\nПрогон бенчмарков промоутнутых моделей ({len(promoted)}):")
        results = run_tests(promoted)
        bad = [m for m, ok in results.items() if ok is False]
        for mid, ok in results.items():
            mark = {True: "✓", False: "✗", None: "—"}[ok]
            print(f"  {mark} {mid}")
        if bad:
            print(f"\n✗ {len(bad)} моделей с падающими бенчмарками — статус "
                  f"Validated нужно ОТОЗВАТЬ")
            sys.exit(1)
        print("\nВсе бенчмарки промоутнутых моделей зелёные "
              "(«—» = покрыто общим пулом tests/).")

    remaining = [m for m in candidates if m not in PROMOTED_BATCH_1]
    print(f"\nСледующие кандидаты ({len(remaining)}): "
          + ", ".join(remaining[:15]) + " …")


if __name__ == "__main__":
    main()
