"""PricingService coverage — equity exotics (governed, service-backed)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import pytest

warnings.filterwarnings("ignore")

from services.pricing_service import PricingService


@pytest.fixture
def svc():
    return PricingService()


def _ok(res):
    assert res["value"] is not None and res["value"] >= 0
    assert res["errors"] == []
    assert "calculation_id" in res and "inputs_hash" in res
    assert "market_data_snapshot_id" in res
    return res


def test_barrier_option_priced_and_governed(svc):
    res = _ok(svc.price_barrier_option(100, 100, 90, 1.0, 0.05, 0.20, opt="call",
                                       barrier_type="down-out"))
    assert res["model_id"] == "barrier"
    # Prototype model surfaces a governance warning
    assert any("Prototype" in w or "prototype" in w for w in res["warnings"])
    # knock-out worth less than vanilla
    vanilla = svc.price_vanilla_option(100, 100, 1.0, 0.05, 0.20, opt="call")["value"]
    assert res["value"] < vanilla


def test_asian_arithmetic_and_geometric(svc):
    arith = _ok(svc.price_asian_option(100, 100, 1.0, 0.05, 0.20, averaging="arithmetic", n_sims=20_000))
    geo = _ok(svc.price_asian_option(100, 100, 1.0, 0.05, 0.20, averaging="geometric"))
    assert arith["model_id"] == "asian" and geo["model_id"] == "asian"
    # averaging reduces vol => asian cheaper than vanilla
    vanilla = svc.price_vanilla_option(100, 100, 1.0, 0.05, 0.20, opt="call")["value"]
    assert geo["value"] < vanilla


def test_digital_cash_and_asset(svc):
    cash = _ok(svc.price_digital_option(100, 100, 1.0, 0.05, 0.20, style="cash", cash=1.0))
    asset = _ok(svc.price_digital_option(100, 100, 1.0, 0.05, 0.20, style="asset"))
    assert cash["model_id"] == "digital"
    assert cash["value"] < 1.0          # cash-or-nothing <= discounted notional
    assert asset["value"] > cash["value"]


def test_lookback_floating_and_fixed(svc):
    floating = _ok(svc.price_lookback_option(100, 1.0, 0.05, 0.20, strike_type="floating", opt="call"))
    fixed = _ok(svc.price_lookback_option(100, 1.0, 0.05, 0.20, strike_type="fixed", K=100, opt="call"))
    assert floating["model_id"] == "lookback"
    # lookback >= vanilla (optimal exercise advantage)
    vanilla = svc.price_vanilla_option(100, 100, 1.0, 0.05, 0.20, opt="call")["value"]
    assert floating["value"] >= vanilla - 1e-6


def test_exotic_pricing_never_crashes_returns_governed_dict(svc):
    import math
    # bad input must come back as a governed dict, not an exception
    res = svc.price_barrier_option(100, 100, 90, 1.0, 0.05, float("nan"))
    assert "calculation_id" in res and "model_id" in res  # structured result
    assert res["errors"] or res["value"] is None or not math.isfinite(res["value"])
