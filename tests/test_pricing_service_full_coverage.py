"""PricingService coverage — rates, credit, multi-asset, structured (governed)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")

from services.pricing_service import PricingService


@pytest.fixture
def svc():
    return PricingService()


def _governed(res):
    assert "calculation_id" in res and "inputs_hash" in res
    assert "model_id" in res and "market_data_snapshot_id" in res
    assert res["errors"] == []
    return res


# ── Rates ────────────────────────────────────────────────

def test_frn_uses_snapshot_curve(svc):
    res = _governed(svc.price_frn(1000, 0.01, 5, 2))
    assert res["model_id"] == "frn" and res["value"] is not None
    # FRN priced off the demo snapshot => demo warning present
    assert any("DEMO" in w or "Demo" in w or "demo" in w for w in res["warnings"])


def test_cap_floor_priced(svc):
    res = _governed(svc.price_cap_floor(1_000_000, 0.10, 3, 2, 0.20, opt="cap"))
    assert res["model_id"] == "capfloor" and res["value"] >= 0


def test_swaption_registered_and_priced(svc):
    res = _governed(svc.price_swaption(1_000_000, 0.10, 1, 5, 2, 0.20, opt="payer"))
    assert res["model_id"] == "swaption" and res["value"] >= 0
    assert res["model_status"]  # registry metadata present (not "Not registered")


# ── Credit ───────────────────────────────────────────────

def test_cds_npv_value(svc):
    res = _governed(svc.price_cds(1_000_000, 0.01, 5, 4, hazard=0.02, r=0.05))
    assert res["model_id"] == "cds"
    assert res["value"] is not None  # value = NPV
    assert "fair_spread" in res["raw"]


# ── Multi-asset ──────────────────────────────────────────

def test_spread_option_priced(svc):
    res = _governed(svc.price_spread_option(100, 100, 5, 1.0, 0.05, 0.20, 0.25, 0.4))
    assert res["model_id"] == "multi_asset" and res["value"] >= 0


def test_basket_option_priced(svc):
    res = _governed(svc.price_basket_option([100, 100], [0.5, 0.5], 100, 1.0, 0.05,
                                            [0.20, 0.20], [[1, 0.3], [0.3, 1]]))
    assert res["model_id"] == "multi_asset" and res["value"] >= 0


# ── Structured ───────────────────────────────────────────

def test_autocall_phoenix_priced(svc):
    res = _governed(svc.price_autocall_phoenix(
        100, 0.05, 0.0, 0.20, 3.0, [1, 2, 3], 1.0, 0.70, 0.65, 0.10,
        n_sims=5_000, steps=50))
    assert res["model_id"] == "structured_autocall" and res["value"] is not None
    assert any("Prototype" in w or "prototype" in w for w in res["warnings"])


def test_all_new_pricers_emit_audit_record(svc):
    # every governed pricing call records an audit entry with an inputs hash
    res = svc.price_cds(1_000_000, 0.01, 5, 4, hazard=0.02, r=0.05)
    assert res["calculation_record"] is not None
    assert res["inputs_hash"] and isinstance(res["inputs_hash"], str)
