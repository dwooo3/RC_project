"""Этап 4 плана по отчёту валидации: A3 actual vs hypothetical P&L,
A5 sweep скрытых допущений."""

from __future__ import annotations

import os

import pytest

from infra.db.app_db import AppDB


# ── A3: хранилище фактического P&L ───────────────────────


def test_actual_pnl_roundtrip():
    db = AppDB(":memory:")
    db.save_actual_pnl("2026-07-09", -1234.5, "csv", "выгрузка бэк-офиса")
    row = db.load_actual_pnl("2026-07-09")
    assert row["pnl"] == -1234.5 and row["source"] == "csv"
    db.save_actual_pnl("2026-07-09", -1000.0)          # upsert той же даты
    assert db.load_actual_pnl("2026-07-09")["pnl"] == -1000.0
    db.save_actual_pnl("2026-07-08", 500.0)
    assert [r["dt"] for r in db.list_actual_pnl()] == ["2026-07-09", "2026-07-08"]
    db.delete_actual_pnl("2026-07-08")
    assert db.load_actual_pnl("2026-07-08") is None


# ── A3: разбор чисел ru/en-локали и атомарность импорта ──
# (находки adversarial-ревью: десятичная запятая, partial import, 500 vs 422)


def test_actual_pnl_number_locales():
    pytest.importorskip("fastapi")            # api.server требует FastAPI (нет в CI)
    from api.server import _actual_pnl_number
    assert _actual_pnl_number("-1234,56") == -1234.56       # ru десятичная
    assert _actual_pnl_number("-1 234,56") == -1234.56      # ru + пробел тысяч
    assert _actual_pnl_number("1.234,56") == 1234.56        # eu тысячи+десятичная
    assert _actual_pnl_number("1,234.5") == 1234.5          # en тысячи
    assert _actual_pnl_number("500") == 500.0
    assert _actual_pnl_number("-12.5") == -12.5
    with pytest.raises(ValueError):
        _actual_pnl_number("abc")


def test_actual_pnl_import_validation():
    """CSV с ';' и десятичной запятой; 422 на мусор ДО записи (атомарно);
    невозможные даты отвергаются."""
    pytest.importorskip("fastapi")            # api.server требует FastAPI (нет в CI)
    from fastapi import HTTPException

    from api import server
    from api.server import ActualPnlPayload, pnl_actual_import

    class _FakeDB:
        def __init__(self):
            self.rows = {}
        def save_actual_pnl(self, dt, pnl, source="manual", note=""):
            self.rows[dt] = pnl
        def list_actual_pnl(self, limit=1000):
            return [{"dt": d, "pnl": p} for d, p in self.rows.items()]

    class _FakeCtx:
        app_db = _FakeDB()

    real_ctx = server.CONTEXT
    server.CONTEXT = _FakeCtx()
    try:
        db = _FakeCtx.app_db
        # ru-CSV: ';' + десятичная запятая — значение НЕ обрезается до -1234
        pnl_actual_import(ActualPnlPayload(csv="Дата;PnL\n2026-07-09;-1 234,56\n"))
        assert db.rows["2026-07-09"] == -1234.56
        # плохая дата в середине пачки → 422 и НИ ОДНОЙ записи (атомарность)
        db.rows.clear()
        with pytest.raises(HTTPException) as exc:
            pnl_actual_import(ActualPnlPayload(
                rows=[{"date": "2026-07-01", "pnl": 1},
                      {"date": "07/02/2026", "pnl": 2}]))
        assert exc.value.status_code == 422 and db.rows == {}
        # невозможная календарная дата → 422 (fromisoformat, не регэксп)
        with pytest.raises(HTTPException) as exc:
            pnl_actual_import(ActualPnlPayload(date="2026-02-31", pnl=1.0))
        assert exc.value.status_code == 422
        # нечисловой pnl в rows → 422, а не 500
        with pytest.raises(HTTPException) as exc:
            pnl_actual_import(ActualPnlPayload(
                rows=[{"date": "2026-07-01", "pnl": "abc"}]))
        assert exc.value.status_code == 422
    finally:
        server.CONTEXT = real_ctx


# ── A5: допущения видимы в каталоге ──────────────────────


def test_catalogue_exposes_conventions():
    from api.pricing_workstation import build_ws_catalogue
    cat = build_ws_catalogue()
    conv = " ".join(cat["conventions"])
    assert "ACT/365" in conv and "seed" in conv
    notes = {p["id"]: p["note"] for p in cat["products"]}
    assert "мониторинг" in notes["barrier_option"]      # непрерывный барьер
    assert "Фиксинги" in notes["asian_option"]
    assert "наблюдение" in notes["lookback_option"]
    assert "Разрывный" in notes["digital_option"]
    # day count у срока T теперь в help
    eur = next(p for p in cat["products"] if p["id"] == "european_option")
    t_spec = next(s for e in eur["engines"] for s in e["params"]
                  if s["key"] == "T")
    assert "ACT/365" in t_spec["help"]


def test_evt_threshold_is_a_parameter():
    import inspect

    from api import marketrisk
    sig = inspect.signature(marketrisk.overview)
    assert "evt_threshold" in sig.parameters
    assert sig.parameters["evt_threshold"].default == 0.10


# ── живая БД: APL split в P&L Explained и бэктесте ───────

_DB = os.path.join(os.path.dirname(__file__), "..", "data", "market_data.sqlite")
live = pytest.mark.skipif(not os.path.exists(_DB),
                          reason="live market store not present")


@live
def test_pnl_explain_reports_apl_split():
    from api import marketrisk
    from api.context import CONTEXT
    rep = marketrisk.pnl_explain(CONTEXT)
    as_of = rep["as_of"]
    try:
        CONTEXT.app_db.save_actual_pnl(as_of, rep["total_pnl"] - 777.0, "test")
        rep2 = marketrisk.pnl_explain(CONTEXT)
        apl = rep2["actual_vs_hypothetical"]
        assert apl["available"] and apl["hypothetical_pnl"] == rep2["total_pnl"]
        assert apl["gap"] == pytest.approx(-777.0)
        assert isinstance(rep2["lifecycle"], list)
    finally:
        CONTEXT.app_db.delete_actual_pnl(as_of)
    rep3 = marketrisk.pnl_explain(CONTEXT)
    assert rep3["actual_vs_hypothetical"]["available"] is False


@live
def test_backtest_actual_leg():
    from api import marketrisk
    from api.context import CONTEXT
    base = marketrisk.backtest(CONTEXT, 0.99, 300, 100)
    assert base["actual_backtest"]["n_obs"] == 0      # actual не импортирован
    # импортируем actual == hyppl на все даты хвоста: пробои совпадают
    dates = [r["date"] for r in base["rows"]]
    try:
        for r in base["rows"]:
            CONTEXT.app_db.save_actual_pnl(r["date"], r["pnl"], "test")
        rep = marketrisk.backtest(CONTEXT, 0.99, 300, 100)
        ab = rep["actual_backtest"]
        assert ab["n_obs"] == len(rep["rows"])
        assert ab["n_exceptions"] == rep["n_exceptions"]
        assert all("actual_breach" in r for r in rep["rows"])
    finally:
        for d in dates:
            CONTEXT.app_db.delete_actual_pnl(d)
