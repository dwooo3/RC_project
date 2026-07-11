"""Этап 3 плана по отчёту валидации: A1 PricingEnvironment,
A2 durable audit, A4 books/trade filters."""

from __future__ import annotations

import os

import pytest

from domain.pricing_environment import PricingEnvironment, default_environments
from infra.db.app_db import AppDB


# ── A1: контракт и хранение окружений ────────────────────


def test_environment_roundtrip_appdb():
    db = AppDB(":memory:")
    env = PricingEnvironment("TEST", "Тестовый контур", "risk",
                             snapshot_id="moex-2026-01-01",
                             curve_map={"discount": "GCURVE_RUB"},
                             pricer_overrides={"european_option": "heston_cf"},
                             default_params={"n_sims": 5000})
    db.save_environment(env)
    loaded = PricingEnvironment.from_dict(db.load_environment("TEST"))
    assert loaded == env
    assert [e["env_id"] for e in db.list_environments()] == ["TEST"]
    db.delete_environment("TEST")
    assert db.load_environment("TEST") is None


def test_default_environments_cover_contours():
    envs = {e.env_id: e for e in default_environments()}
    assert set(envs) == {"FO", "RISK", "EOD", "VAR", "STRESS"}
    assert envs["FO"].purpose == "fo" and envs["STRESS"].purpose == "stress"
    for e in envs.values():
        assert e.snapshot_id is None                # все на активном снапшоте
        assert e.curve_map["discount"] == "GCURVE_RUB"


def test_environment_invalid_purpose_raises():
    with pytest.raises(ValueError):
        PricingEnvironment("X", "bad", "trading")


# ── A1: price_ws уважает контур ──────────────────────────


def test_price_ws_honors_environment_defaults():
    from api.pricing_workstation import FLAT_CURVE, price_ws
    from services.pricing_service import PricingService
    svc = PricingService(allow_analytics_lab=True)
    env = PricingEnvironment(
        "T1", "test", "risk",
        curve_map={"discount": FLAT_CURVE},
        pricer_overrides={"european_option": "heston_cf"},
        default_params={"sigma": 0.30})
    base = {"S": 100, "K": 100, "T": 1, "r": 0.05, "q": 0, "opt": "call"}

    res = price_ws(svc, None, "european_option", None, base, env=env)
    assert res["engine"] == "heston_cf", "контур выбирает движок по умолчанию"
    assert res["environment"] == "T1"

    # запрос побеждает контур: явный движок и явная сигма
    res2 = price_ws(svc, None, "european_option", "black_scholes",
                    {**base, "sigma": 0.20}, env=env)
    assert res2["engine"] == "black_scholes"
    res3 = price_ws(svc, None, "european_option", "black_scholes", base, env=env)
    assert res3["value"] > res2["value"], "дефолтная σ=0.30 контура дороже явной 0.20"

    # кривая discount-роли из контура попадает в needs_curve продукт
    irs_res = price_ws(svc, None, "irs", "irs",
                       {"notional": 1e6, "fixed_rate": 0.1, "T": 5, "freq": 4,
                        "r": 0.1, "side": "pay fixed"}, env=env)
    assert irs_res["errors"] == []                 # FLAT_CURVE из curve_map сработал


# ── A2: durable audit ────────────────────────────────────


def test_audit_persists_and_survives_restart():
    from services.audit_service import AuditService
    from services.governance_service import GovernanceService
    from services.pricing_service import PricingService

    db = AppDB(":memory:")
    svc = PricingService(audit=AuditService(db=db))
    svc.price_vanilla_option(100, 100, 1.0, 0.05, 0.2)
    assert db.audit_count() >= 1

    # «перезапуск»: новые сервисы на той же БД видят историю
    fresh_gov = GovernanceService(audit=AuditService(db=db))
    trail = fresh_gov.audit_trail()
    assert trail and trail[0]["status"] == "Recorded"
    assert trail[0]["model_id"] == "black_scholes"
    assert trail[0]["inputs_hash"]


def test_governance_placeholder_without_db():
    from services.governance_service import GovernanceService
    trail = GovernanceService().audit_trail()
    assert trail[0]["status"] == "Pending"          # история не выдумывается


# ── живая БД: сиды окружений, book-фильтры ───────────────

_DB = os.path.join(os.path.dirname(__file__), "..", "data", "market_data.sqlite")
live = pytest.mark.skipif(not os.path.exists(_DB),
                          reason="live market store not present")


@live
def test_context_seeds_default_environments():
    from api.context import CONTEXT
    fo = CONTEXT.environment()
    assert fo.env_id == "FO"
    var_env = CONTEXT.environment("var")
    assert var_env.purpose == "var"
    ids = {e["env_id"] for e in CONTEXT.app_db.list_environments()}
    assert {"FO", "RISK", "EOD", "VAR", "STRESS"} <= ids


@live
def test_book_filter_slices_portfolio():
    from api.context import CONTEXT
    full = CONTEXT.portfolio
    sliced = CONTEXT.filtered_portfolio(book="Trading")
    assert len(sliced.positions) == len(
        [p for p in full.positions if p.book == "Trading"])
    empty = CONTEXT.filtered_portfolio(book="NoSuchBook")
    assert len(empty.positions) == 0
    books = CONTEXT.books()
    assert any(b["book"] == "Trading" for b in books)


@live
def test_marketrisk_book_slice_matches_full_when_single_book():
    """Вся демо-книга в book='Trading' ⇒ VaR по срезу == VaR всей книги."""
    from api.context import CONTEXT
    from api import marketrisk
    marketrisk.invalidate_cache()
    full = marketrisk.overview(CONTEXT, 0.99, 300, 1)
    sliced = marketrisk.overview(CONTEXT, 0.99, 300, 1, book="Trading")
    assert sliced["book"] == "Trading"
    assert sliced["var"] == pytest.approx(full["var"], rel=1e-9)
    assert sliced["positions"] == full["positions"]
