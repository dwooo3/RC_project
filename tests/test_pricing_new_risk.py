from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from api import pricing_new_risk
from api.pricing_workstation import portfolio_repricing_engine
from domain.market_data import MarketDataSnapshot, MarketDataSource
from domain.portfolio import Position
from services.portfolio_service import PortfolioService


def _leg(
    leg_id: str = "leg-1",
    *,
    product: str = "european_option",
    engine: str | None = None,
    currency: str | None = "RUB",
    quantity: float = 2.0,
    params: dict | None = None,
) -> dict:
    payload = {
        "id": leg_id,
        "label": f"Position {leg_id}",
        "product": product,
        "engine": engine or portfolio_repricing_engine(product),
        "quantity": quantity,
        "params": params or {
            "S": 100.0,
            "K": 100.0,
            "T": 1.0,
            "r": 0.05,
            "sigma": 0.2,
            "q": 0.0,
            "opt": "call",
            "secid": "SBER",
        },
    }
    if currency is not None:
        payload["currency"] = currency
    return payload


def _context() -> SimpleNamespace:
    base = PortfolioService()
    base.portfolio.portfolio_id = "global-book"
    base.add(Position(
        id="global-position",
        instrument="option",
        description="must never enter Pricing_new risk",
        quantity=1.0,
        currency="RUB",
        params={
            "S": 100.0,
            "K": 100.0,
            "T": 1.0,
            "r": 0.05,
            "sigma": 0.2,
            "q": 0.0,
            "opt": "call",
        },
    ))
    snapshot = MarketDataSnapshot(
        snapshot_id="SNAP-TEST",
        valuation_date=date(2026, 7, 16),
        source=MarketDataSource.MANUAL,
        quality=MarketDataSource.MANUAL.value,
    )
    return SimpleNamespace(
        portfolio=base,
        snapshot=snapshot,
        audit=base.audit,
    )


def test_capability_accepts_only_canonical_repriceable_leg():
    result = pricing_new_risk.evaluate_book_capabilities([_leg()])

    assert result["supported"] is True
    assert result["supported_count"] == 1
    assert result["base_currency"] == "RUB"
    assert result["supported_legs"][0]["instrument"] == "option"
    assert result["policy"]["partial_book_risk"] is False


def test_capability_materializes_omitted_engine_for_replay():
    leg = _leg()
    leg["engine"] = None
    result = pricing_new_risk.evaluate_book_capabilities([leg])

    assert result["supported"] is True
    assert result["supported_legs"][0]["engine"] == "black_scholes"


def test_capability_reports_missing_currency_and_unsupported_product():
    no_currency = _leg(currency=None)
    custom = {
        "id": "custom",
        "label": "Custom payoff",
        "product": "custom_product",
        "engine": "monte_carlo",
        "currency": "RUB",
        "quantity": 1.0,
        "params": {},
    }

    result = pricing_new_risk.evaluate_book_capabilities([no_currency, custom])

    assert result["supported"] is False
    assert {row["code"] for row in result["unsupported"]} == {
        "currency_required",
        "product_not_repriceable",
    }


def test_capability_blocks_noncanonical_engine_and_duplicate_ids():
    wrong_engine = _leg(engine="finite_difference")
    duplicate_a = _leg("duplicate")
    duplicate_b = _leg("duplicate")

    engine_result = pricing_new_risk.evaluate_book_capabilities([wrong_engine])
    duplicate_result = pricing_new_risk.evaluate_book_capabilities(
        [duplicate_a, duplicate_b])

    assert engine_result["supported"] is False
    assert engine_result["unsupported"][0]["code"] == "engine_not_reproducible"
    assert duplicate_result["supported"] is False
    assert duplicate_result["supported_count"] == 0
    assert duplicate_result["unsupported"][0]["code"] == "duplicate_leg_id"


def test_capability_blocks_mixed_currency_without_fx_translation_policy():
    result = pricing_new_risk.evaluate_book_capabilities([
        _leg("rub", currency="RUB"),
        _leg("usd", currency="USD"),
    ])

    assert result["supported"] is False
    assert result["base_currency"] is None
    assert result["currencies"] == ["RUB", "USD"]
    assert {row["code"] for row in result["unsupported"]} == {
        "mixed_currency_book"
    }


def test_calculation_uses_only_transient_book_and_returns_provenance(monkeypatch):
    ctx = _context()
    observed = {}

    def fake_hyppl(call_ctx, window, frm=None, till=None, portfolio=None, horizon=1):
        observed["ctx"] = call_ctx
        observed["portfolio"] = portfolio
        observed["window"] = window
        observed["horizon"] = horizon
        assert portfolio is not ctx.portfolio
        assert [position.id for position in portfolio.positions] == ["leg-1"]
        return {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            "pnl": np.asarray([-10.0, 5.0, -20.0, 15.0]),
            "factors": ["EQ:SBER", "RVI:price"],
            "factor_warnings": [],
            "factor_diagnostics": {
                "equity": {"source": "SBER:price", "ready": True},
            },
            "reprice_errors": [],
            "horizon_method": "none",
        }

    monkeypatch.setattr(pricing_new_risk.marketrisk, "hyppl", fake_hyppl)

    result = pricing_new_risk.calculate_transient_book_risk(
        ctx,
        [_leg()],
        confidence=0.75,
        window=250,
        horizon=1,
        model="historical_full_reprice",
    )

    assert observed["ctx"] is ctx
    assert observed["window"] == 250
    assert observed["horizon"] == 1
    assert result["scope"] == "pricing_new_transient_book"
    assert result["partial"] is False
    assert result["positions"] == 1
    assert result["var"] == 12.5
    assert result["es"] == 20.0
    assert result["n_scenarios"] == 4
    assert result["provenance"]["history_source"] == "stored_market_factor_history"
    assert result["provenance"]["portfolio_source"] == "request_legs_only"
    assert result["provenance"]["global_portfolio_used"] is False
    assert result["provenance"]["snapshot_id"] == "SNAP-TEST"
    assert result["provenance"]["inputs_hash"]
    assert result["provenance"]["calculation_id"]


def test_calculation_fails_closed_before_history_when_any_leg_is_unsupported(
    monkeypatch,
):
    ctx = _context()
    history_called = False

    def fake_hyppl(*args, **kwargs):
        nonlocal history_called
        history_called = True
        raise AssertionError("history must not run for a partial book")

    monkeypatch.setattr(pricing_new_risk.marketrisk, "hyppl", fake_hyppl)
    unsupported = {
        "id": "unsupported",
        "label": "Unsupported",
        "product": "american_option",
        "engine": "binomial",
        "currency": "RUB",
        "quantity": 1.0,
        "params": {},
    }

    with pytest.raises(
        pricing_new_risk.UnsupportedPricingNewBookError
    ) as caught:
        pricing_new_risk.calculate_transient_book_risk(
            ctx, [_leg(), unsupported], window=250)

    assert history_called is False
    payload = caught.value.to_dict()
    assert payload["code"] == "unsupported_pricing_new_book"
    assert payload["details"]["capability"]["supported"] is False
    assert payload["details"]["unsupported"][0]["id"] == "unsupported"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", 1.0),
        ("window", 59),
        ("horizon", 0),
        ("n_sims", 999),
        ("seed", -1),
    ],
)
def test_calculation_validates_risk_controls_before_running_history(
    monkeypatch, field, value
):
    monkeypatch.setattr(
        pricing_new_risk.marketrisk,
        "hyppl",
        lambda *args, **kwargs: pytest.fail("history must not run"),
    )
    kwargs = {field: value}
    with pytest.raises(pricing_new_risk.PricingNewRiskError) as caught:
        pricing_new_risk.calculate_transient_book_risk(
            _context(), [_leg()], **kwargs)

    assert caught.value.code == "invalid_risk_parameter"


def test_empty_book_is_an_explicit_capability_error():
    capability = pricing_new_risk.evaluate_book_capabilities([])
    assert capability["supported"] is False
    assert capability["unsupported"][0]["code"] == "empty_book"
