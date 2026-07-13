"""Directed regressions for typed multi-asset spot/vol factor routing."""

from __future__ import annotations

import math

import pytest

from api.pricing_workstation import to_position
from domain.portfolio import Position
from services.portfolio_service import PortfolioService


class _LinearMultiAssetPricing:
    """Cheap deterministic pricers that expose every routed component."""

    audit = None

    @staticmethod
    def _result(value):
        return {
            "value": float(value), "errors": [], "warnings": [], "raw": {},
            "model_id": "test_linear", "model_status": "test",
            "market_data_snapshot_id": "test",
        }

    def price_spread_option(self, S1, S2, K, T, r, sigma1, sigma2, rho,
                            q1=0.0, q2=0.0):
        del K, T, r, rho, q1, q2
        return self._result(S1 - 2.0 * S2 + 100.0 * sigma1 + 200.0 * sigma2)

    def price_basket_option(self, assets, weights, K, T, r, sigmas, corr,
                            opt="call"):
        del weights, K, T, r, corr, opt
        return self._result(sum(assets) + 100.0 * sum(sigmas))


def _service(position: Position) -> PortfolioService:
    service = PortfolioService(pricing=_LinearMultiAssetPricing())
    service.add(position)
    return service


def test_spread_routes_spot_and_vol_by_component_identity():
    service = _service(Position(
        id="spread", instrument="spread", quantity=1.0, description="spread",
        params={
            "S1": 100.0, "S2": 80.0, "K": 5.0, "T": 1.0, "r": 0.0,
            "sigma1": 0.2, "sigma2": 0.3, "rho": 0.2,
            "q1": 0.0, "q2": 0.0,
            "component_secids": ["AAA", "BBB"],
        }))

    spot = service.full_reprice_pnl(
        dS=0.0, dS_by_name={"AAA": 0.10, "BBB": 0.0})
    vol = service.full_reprice_pnl(
        dvol=0.0, dvol_by_name={"AAA": 0.01, "BBB": 0.02})

    assert spot["pnl"] == pytest.approx(10.0)
    assert vol["pnl"] == pytest.approx(5.0)
    assert spot["errors"] == vol["errors"] == []


def test_basket_global_and_component_shocks_cover_list_fields():
    service = _service(Position(
        id="basket", instrument="basket", quantity=1.0, description="basket",
        params={
            "assets": [100.0, 80.0, 50.0], "weights": [0.4, 0.3, 0.3],
            "K": 100.0, "T": 1.0, "r": 0.0,
            "sigmas": [0.2, 0.25, 0.3],
            "corr": [[1.0, 0.2, 0.2], [0.2, 1.0, 0.2], [0.2, 0.2, 1.0]],
            "opt": "call", "component_secids": ["AAA", "BBB", "CCC"],
        }))

    global_spot = service.full_reprice_pnl(dS=0.10)
    component_spot = service.full_reprice_pnl(
        dS=0.0, dS_by_name={"BBB": 0.10})
    component_vol = service.full_reprice_pnl(
        dvol=0.0, dvol_by_name={"CCC": 0.02})

    assert global_spot["pnl"] == pytest.approx(23.0)
    assert component_spot["pnl"] == pytest.approx(8.0)
    assert component_vol["pnl"] == pytest.approx(2.0)


def test_component_log_shock_matches_equivalent_simple_shock():
    service = _service(Position(
        id="spread", instrument="spread", quantity=1.0, description="spread",
        params={
            "S1": 100.0, "S2": 80.0, "K": 5.0, "T": 1.0, "r": 0.0,
            "sigma1": 0.2, "sigma2": 0.3, "rho": 0.2,
            "q1": 0.0, "q2": 0.0,
            "component_secids": ["AAA", "BBB"],
        }))
    simple = service.full_reprice_pnl(
        dS_by_name={"AAA": 0.10}, spot_shock_convention="simple")
    log = service.full_reprice_pnl(
        dS_by_name={"AAA": math.log1p(0.10)},
        spot_shock_convention="log")
    assert log["pnl"] == pytest.approx(simple["pnl"])


def test_capture_preserves_and_validates_component_secids():
    spread = to_position("spread_option", {
        "S1": 100, "S2": 90, "K": 5, "T": 1, "r": 0.05,
        "sigma1": 0.2, "sigma2": 0.25, "rho": 0.3,
        "q1": 0, "q2": 0, "component_secids": "SBER, GAZP",
    })
    basket = to_position("basket_option", {
        "spots": "100,90,80", "weights": "0.4,0.3,0.3",
        "sigmas": "0.2,0.25,0.3", "rho": 0.2, "K": 90,
        "T": 1, "r": 0.05, "opt": "call",
        "component_secids": "SBER:1.0, GAZP:1.0, LKOH:1.0",
    })

    assert spread[1]["component_secids"] == ["SBER", "GAZP"]
    assert basket[1]["component_secids"] == ["SBER", "GAZP", "LKOH"]
    with pytest.raises(ValueError, match="requires 3 component SECIDs"):
        to_position("basket_option", {
            "spots": "100,90,80", "weights": "0.4,0.3,0.3",
            "sigmas": "0.2,0.25,0.3", "component_secids": "SBER,GAZP",
        })
    with pytest.raises(ValueError, match="assets and sigmas"):
        to_position("basket_option", {
            "spots": "100,90", "weights": "0.5,0.5", "sigmas": "0.2",
        })


def test_capture_rejects_duplicate_component_secids():
    with pytest.raises(ValueError, match="component SECIDs must be unique"):
        to_position("spread_option", {
            "S1": 100, "S2": 90, "K": 5, "T": 1, "r": 0.05,
            "sigma1": 0.2, "sigma2": 0.25, "rho": 0.3,
            "q1": 0, "q2": 0, "component_secids": "SBER,SBER",
        })


def test_repricing_rejects_duplicate_persisted_component_secids():
    service = _service(Position(
        id="duplicate-spread", instrument="spread", quantity=1.0,
        description="ambiguous identity",
        params={
            "S1": 100.0, "S2": 80.0, "K": 5.0, "T": 1.0,
            "r": 0.0, "sigma1": 0.2, "sigma2": 0.3, "rho": 0.2,
            "q1": 0.0, "q2": 0.0,
            "component_secids": ["AAA", "AAA"],
        },
    ))

    with pytest.raises(ValueError, match="component_secids must be unique"):
        service.full_reprice_pnl(dS_by_name={"AAA": 0.10})


def test_capture_preserves_curve_and_surface_provenance():
    option = to_position("european_option", {
        "S": 100, "K": 100, "T": 1, "r": 0.05, "sigma": 0.2, "q": 0,
        "opt": "call", "secid": "SBER", "vol_surface_id": "SBRF_FORTS",
    })
    irs = to_position("irs", {
        "notional": 1_000_000, "fixed_rate": 0.1, "T": 5, "freq": 4,
        "r": 0.1, "side": "pay fixed", "curve_id": "GCURVE_RUB",
        "proj_curve_id": "RUONIA_RUB",
    })

    assert option[1]["vol_surface_id"] == "SBRF_FORTS"
    assert irs[1]["curve_id"] == "GCURVE_RUB"
    assert irs[1]["proj_curve_id"] == "RUONIA_RUB"


def test_spread_component_greeks_are_attributed_to_named_factors():
    service = _service(Position(
        id="spread", instrument="spread", quantity=1.0, description="spread",
        params={
            "S1": 100.0, "S2": 80.0, "K": 5.0, "T": 1.0, "r": 0.0,
            "sigma1": 0.2, "sigma2": 0.3, "rho": 0.2,
            "q1": 0.0, "q2": 0.0,
            "component_secids": ["AAA", "BBB"],
        }))

    result = service.value()
    position = result.positions[0]
    exposures = {
        exposure.factor_id: exposure.sensitivity
        for exposure in position.exposures
    }

    assert result.errors == []
    assert position.delta == pytest.approx(-1.0)
    assert position.gamma == pytest.approx(0.0, abs=1e-12)
    assert position.vega == pytest.approx(3.0)
    assert exposures["equity.aaa.spot"] == pytest.approx(1.0)
    assert exposures["equity.bbb.spot"] == pytest.approx(-2.0)
    assert exposures["vol.aaa.implied"] == pytest.approx(1.0)
    assert exposures["vol.bbb.implied"] == pytest.approx(2.0)


def test_basket_component_greeks_cover_every_named_factor():
    service = _service(Position(
        id="basket", instrument="basket", quantity=1.0,
        description="basket",
        params={
            "assets": [100.0, 80.0, 50.0],
            "weights": [0.4, 0.3, 0.3], "K": 100.0, "T": 1.0,
            "r": 0.0, "sigmas": [0.2, 0.25, 0.3],
            "corr": [
                [1.0, 0.2, 0.2], [0.2, 1.0, 0.2], [0.2, 0.2, 1.0],
            ],
            "opt": "call", "component_secids": ["AAA", "BBB", "CCC"],
        }))

    position = service.value().positions[0]
    exposures = {
        exposure.factor_id: exposure.sensitivity
        for exposure in position.exposures
    }

    for secid in ("aaa", "bbb", "ccc"):
        assert exposures[f"equity.{secid}.spot"] == pytest.approx(1.0)
        assert exposures[f"vol.{secid}.implied"] == pytest.approx(1.0)
    assert position.delta == pytest.approx(3.0)
    assert position.vega == pytest.approx(3.0)


def test_pnl_explain_uses_component_spot_and_vol_moves():
    service = _service(Position(
        id="spread", instrument="spread", quantity=1.0, description="spread",
        params={
            "S1": 100.0, "S2": 80.0, "K": 5.0, "T": 1.0, "r": 0.0,
            "sigma1": 0.2, "sigma2": 0.3, "rho": 0.2,
            "q1": 0.0, "q2": 0.0,
            "component_secids": ["AAA", "BBB"],
        }))

    result = service.explain_pnl(
        dS_relative=0.0,
        dS_relative_by_name={"AAA": 0.10, "BBB": 0.20},
        dVol=0.0,
        dVol_by_name={"AAA": 0.01, "BBB": 0.02},
    )

    assert result.delta_pnl == pytest.approx(-22.0)
    assert result.gamma_pnl == pytest.approx(0.0, abs=1e-10)
    assert result.vega_pnl == pytest.approx(5.0)
    assert result.explained_pnl == pytest.approx(-17.0)
    assert result.factor_pnl["equity.aaa.spot"] == pytest.approx(10.0)
    assert result.factor_pnl["equity.bbb.spot"] == pytest.approx(-32.0)
    assert result.factor_pnl["vol.aaa.implied"] == pytest.approx(1.0)
    assert result.factor_pnl["vol.bbb.implied"] == pytest.approx(4.0)
