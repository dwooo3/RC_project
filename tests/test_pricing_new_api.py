"""HTTP-adapter contract for the unified Pricing_new worksheet."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.pricing_new_runs import PricingNewRunService
from domain.market_data import MarketDataSnapshot, MarketDataSource
from services.pricing_service import PricingService


PARAMS = {
    "S": 100.0,
    "K": 100.0,
    "T": 1.0,
    "r": 0.05,
    "q": 0.0,
    "sigma": 0.2,
    "opt": "call",
}


def _leg(leg_id: str = "leg-1", *, strike: float = 100.0) -> dict:
    return {
        "id": leg_id,
        "label": f"Call {strike:g}",
        "product": "european_option",
        "engine": "black_scholes",
        "risk_factor_id": "SBER",
        "currency": "RUB",
        "params": {**PARAMS, "K": strike, "secid": "SBER"},
        "quantity": 1.0,
    }


@pytest.fixture
def isolated_server(monkeypatch, tmp_path):
    from api import server

    service = PricingService(
        allow_analytics_lab=True,
        allow_non_production_models=True,
    )
    store = PricingNewRunService(tmp_path / "pricing-new-runs.json")
    calls: list[str | None] = []

    def runtime(env_id):
        calls.append(env_id)
        snapshot = SimpleNamespace(
            snapshot_id="SNAP-PNEW",
            curves={},
            vol_surfaces={},
        )
        return None, snapshot, service, [], []

    monkeypatch.setattr(server, "_pricing_new_runs", store)
    monkeypatch.setattr(server, "_workstation_runtime", runtime)
    return server, store, calls


def test_pricing_new_request_enforces_named_one_to_five_leg_worksheet():
    from api.server import PricingNewLegRequest, PricingNewPriceRequest

    leg = PricingNewLegRequest(**_leg())
    with pytest.raises(ValidationError):
        PricingNewPriceRequest(name="", legs=[leg])
    with pytest.raises(ValidationError):
        PricingNewPriceRequest(name="No legs", legs=[])
    with pytest.raises(ValidationError):
        PricingNewPriceRequest(name="Too many", legs=[leg] * 6)

    request = PricingNewPriceRequest(name="Two calls", legs=[
        leg,
        PricingNewLegRequest(**_leg("leg-2", strike=110.0)),
    ])
    assert request.name == "Two calls"
    assert len(request.legs) == 2


def test_price_route_freezes_once_and_persists_exact_request_and_result(
    isolated_server,
):
    server, store, calls = isolated_server
    request = server.PricingNewPriceRequest(
        name="Desk validation",
        env_id="FO",
        legs=[server.PricingNewLegRequest(**_leg())],
    )

    response = server.pricing_new_price(request)

    assert calls == ["FO"]
    assert response["name"] == "Desk validation"
    assert response["request"]["env_id"] == "FO"
    assert response["request"]["legs"][0]["currency"] == "RUB"
    assert response["result"]["snapshot_id"] == "SNAP-PNEW"
    assert response["result"]["success_count"] == 1
    assert store.get_run(response["run_id"]).as_dict() == response


def test_history_is_lightweight_and_full_run_restores(isolated_server):
    server, _store, _calls = isolated_server
    for index in range(2):
        server.pricing_new_price(server.PricingNewPriceRequest(
            name=f"Run {index}",
            legs=[server.PricingNewLegRequest(**_leg(f"leg-{index}"))],
        ))

    history = server.pricing_new_history(limit=10, offset=0)["runs"]

    assert [row["name"] for row in history] == ["Run 1", "Run 0"]
    assert "request" not in history[0]
    restored = server.pricing_new_run(history[0]["run_id"])
    assert restored["name"] == "Run 1"
    assert restored["request"]["legs"][0]["id"] == "leg-1"
    assert restored["result"]["legs"][0]["result"] is not None


def test_risk_route_uses_exact_saved_legs_and_pinned_environment(
    isolated_server, monkeypatch,
):
    server, _store, calls = isolated_server
    priced = server.pricing_new_price(server.PricingNewPriceRequest(
        name="Risk source",
        env_id="FO",
        legs=[server.PricingNewLegRequest(**_leg())],
    ))
    observed = {}

    def calculate(ctx, legs, **controls):
        observed["snapshot"] = ctx.snapshot.snapshot_id
        observed["legs"] = legs
        observed["controls"] = controls
        return {
            "scope": "pricing_new_transient_book",
            "var": 12.0,
            "es": 15.0,
        }

    monkeypatch.setattr(
        server.pricing_new_risk, "calculate_transient_book_risk", calculate)
    response = server.pricing_new_run_risk(
        priced["run_id"],
        server.PricingNewRiskRequest(
            confidence=0.975,
            window=250,
            horizon=10,
            model="parametric_t",
        ),
    )

    assert calls == ["FO", "FO"]
    assert observed["snapshot"] == "SNAP-PNEW"
    assert observed["legs"] == priced["request"]["legs"]
    assert observed["controls"]["confidence"] == pytest.approx(0.975)
    assert observed["controls"]["horizon"] == 10
    assert response["pricing_run_id"] == priced["run_id"]
    assert response["pricing_run_name"] == "Risk source"


def test_risk_reopens_saved_snapshot_after_environment_advances(
    monkeypatch, tmp_path,
):
    from datetime import date
    from api import server

    service = PricingService()
    old = MarketDataSnapshot(
        snapshot_id="SNAP-OLD",
        valuation_date=date(2026, 7, 16),
        source=MarketDataSource.MANUAL,
        quality="MANUAL",
    )
    current = MarketDataSnapshot(
        snapshot_id="SNAP-CURRENT",
        valuation_date=date(2026, 7, 18),
        source=MarketDataSource.MANUAL,
        quality="MANUAL",
    )
    runtime_snapshot = {"value": old}

    def runtime(_env_id):
        snapshot = runtime_snapshot["value"]
        return None, snapshot, service, [], []

    monkeypatch.setattr(
        service.market_data, "resolve_pinned_snapshot",
        lambda snapshot_id: old if snapshot_id == old.snapshot_id
        else pytest.fail("unexpected snapshot id"),
        raising=False,
    )
    monkeypatch.setattr(server, "_workstation_runtime", runtime)
    monkeypatch.setattr(
        server, "_pricing_new_runs",
        PricingNewRunService(tmp_path / "pinned-runs.json"),
    )
    priced = server.pricing_new_price(server.PricingNewPriceRequest(
        name="Pinned snapshot",
        env_id="FO",
        legs=[server.PricingNewLegRequest(**_leg())],
    ))
    runtime_snapshot["value"] = current
    observed = {}

    def calculate(ctx, legs, **_controls):
        observed["snapshot_id"] = ctx.snapshot.snapshot_id
        return {"scope": "pricing_new_transient_book", "var": 1.0, "es": 2.0}

    monkeypatch.setattr(
        server.pricing_new_risk, "calculate_transient_book_risk", calculate)

    capability = server.pricing_new_risk_capabilities(priced["run_id"])
    result = server.pricing_new_run_risk(
        priced["run_id"], server.PricingNewRiskRequest())

    assert capability["supported"] is True
    assert observed["snapshot_id"] == "SNAP-OLD"
    assert result["pricing_run_id"] == priced["run_id"]


def test_openapi_exposes_pricing_new_without_replacing_current_pricing():
    from api.server import app

    paths = app.openapi()["paths"]
    assert "/pricing/price" in paths
    assert "/pricing/book/price" in paths
    assert "/pricing-new/runs/price" in paths
    assert "/pricing-new/runs/{run_id}/risk" in paths
    assert "/pricing-new/runs/{run_id}/risk/capabilities" in paths
