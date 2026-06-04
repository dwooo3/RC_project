"""Market-data validation rules (spec §5)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

from infra.moex_iss.validation import (
    validate_curve_points, validate_fx, assess_quality,
    QUALITY_OK, QUALITY_STALE, QUALITY_PARTIAL, QUALITY_REJECTED,
)


def test_valid_curve_points_pass():
    pts = [(0.25, 0.155, None), (1.0, 0.145, None), (5.0, 0.127, None)]
    assert validate_curve_points(pts) == []


def test_curve_rejects_non_increasing_tenors():
    pts = [(1.0, 0.14, None), (1.0, 0.13, None), (5.0, 0.12, None)]
    assert any("strictly increasing" in e for e in validate_curve_points(pts))


def test_curve_rejects_non_monotonic_discount_factors():
    # rising DF (negative-ish rate at long end relative to short) -> DF increases
    pts = [(1.0, 0.10, 0.90), (2.0, 0.05, 0.95), (3.0, 0.04, 0.97)]
    assert any("monotonic" in e for e in validate_curve_points(pts))


def test_curve_rejects_too_few_points():
    assert any("required" in e for e in validate_curve_points([(1.0, 0.1, None)]))


def test_fx_positivity_and_cross():
    assert validate_fx({"USD/RUB": 74.0, "EUR/RUB": 86.0}) == []
    assert any("positive" in e for e in validate_fx({"USD/RUB": -1.0}))
    bad_cross = validate_fx({"USD/RUB": 74.0, "EUR/RUB": 86.0, "EUR/USD": 2.0})
    assert any("cross" in e for e in bad_cross)


def test_assess_quality_ok():
    q, w = assess_quality(valuation_date=date(2026, 6, 4), as_of=date(2026, 6, 4),
                          curve_errors=[], fx_errors=[],
                          expected_components={"GCURVE_RUB", "FX"},
                          present_components={"GCURVE_RUB", "FX"})
    assert q == QUALITY_OK and w == []


def test_assess_quality_rejected_on_structural_error():
    q, w = assess_quality(valuation_date=date(2026, 6, 4), as_of=date(2026, 6, 4),
                          curve_errors=["discount factors must be positive"], fx_errors=[],
                          expected_components=set(), present_components=set())
    assert q == QUALITY_REJECTED and w


def test_assess_quality_stale():
    q, _ = assess_quality(valuation_date=date(2026, 6, 4), as_of=date(2026, 5, 1),
                          curve_errors=[], fx_errors=[],
                          expected_components={"GCURVE_RUB"}, present_components={"GCURVE_RUB"})
    assert q == QUALITY_STALE


def test_assess_quality_partial_on_missing_component():
    q, _ = assess_quality(valuation_date=date(2026, 6, 4), as_of=date(2026, 6, 4),
                          curve_errors=[], fx_errors=[],
                          expected_components={"GCURVE_RUB", "FX"},
                          present_components={"GCURVE_RUB"})
    assert q == QUALITY_PARTIAL
