"""FastAPI bridge for the SwiftUI client.

Run from the project root:

    /usr/local/bin/python3.14 -m api.server         # serves on 127.0.0.1:8765

Endpoints
    GET  /health             liveness + version
    GET  /pricing/catalogue  the universal pricer catalogue (products x engines)
    POST /pricing/price      {"product","engine","params"} -> normalized result

The engine runs in an explicitly analytical mode: Analytics-Lab and other
non-production models may return governed results with status warnings, while
their ``production_allowed`` metadata remains false. Service defaults stay
fail-closed.
"""

from __future__ import annotations

import os
from datetime import date
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api import (
    catalog,
    datahealth,
    history,
    ingest_job,
    intraday,
    instruments,
    livequotes,
    market_entity,
    marketdata,
    payloads,
    rawdata,
    realbonds,
    timeseries,
    volsurface,
)
from api import credit, desk, marketrisk, pricing_workstation, underlying, xva
from api.context import CONTEXT
from api.serialization import jsonable
from services.pricing_service import PricingService

VERSION = "0.2.0"

app = FastAPI(title="RiskCalc Bridge", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_svc = PricingService(
    allow_analytics_lab=True,
    allow_non_production_models=True,
    audit=CONTEXT.audit,
)


class WsPriceRequest(BaseModel):
    product: str
    engine: str | None = None
    params: dict[str, float | int | str | None] = {}
    env_id: str | None = None


class ActualPnlPayload(BaseModel):
    """Импорт фактического P&L (A3): одна запись {date,pnl}, список rows,
    или csv-текст «date,pnl» построчно (заголовок и ';' допускаются)."""
    date: str | None = None
    pnl: float | None = None
    rows: list[dict[str, float | str]] | None = None
    csv: str | None = None
    source: str = "manual"
    note: str = ""


class EnvironmentPayload(BaseModel):
    env_id: str
    name: str
    purpose: str = "fo"
    snapshot_id: str | None = None
    curve_map: dict[str, str] = {}
    surface_map: dict[str, str] = {}
    pricer_overrides: dict[str, str] = {}
    default_params: dict[str, float | int | str] = {}
    measures: list[str] = ["value", "greeks"]
    metadata: dict[str, str] = {}


class WsCaptureRequest(BaseModel):
    product: str
    engine: str | None = None
    params: dict[str, float | int | str | None] = {}
    quantity: float = 1.0
    description: str | None = None


class WsLadderRequest(BaseModel):
    product: str
    engine: str | None = None
    params: dict[str, float | int | str | None] = {}
    bump_key: str
    lo: float
    hi: float
    steps: int = 11


class InstrumentPriceRequest(BaseModel):
    instrument: str
    params: dict[str, float | int | str | None] = {}


class BatchRow(BaseModel):
    instrument: str
    params: dict[str, float | int | str | None] = {}
    quantity: float = 1.0


class BatchPriceRequest(BaseModel):
    bonds: list[BatchRow] = []


class RepriceRequest(BaseModel):
    secid: str
    curve_id: str = "GCURVE_RUB"
    shift_bps: float = 0.0
    forecast_curve_id: str = "RUONIA_RUB"
    float_spread_bps: float = 0.0


@app.get("/health")
def health() -> dict:
    snap = CONTEXT.snapshot                       # resolves the snapshot (sets fallback flag)
    market = CONTEXT.market
    mode = getattr(market, "mode", None)
    return {
        "status": "ok",
        "service": "RiskCalc Bridge",
        "version": VERSION,
        "live": CONTEXT.is_live(),
        "snapshot_id": snap.snapshot_id,
        "source": getattr(snap.source, "value", str(snap.source)),
        "mode": getattr(mode, "value", str(mode)) if mode is not None else "research",
        "is_demo": bool(getattr(snap, "is_demo", False)),
        "fallback_used": bool(getattr(market, "last_fallback_used", False)),
    }


def _vol_surface_ids() -> list[str]:
    """Surface ids in the active snapshot, FORTS first — choices for the pricer's
    vol_surface_id selector."""
    try:
        ids = list(CONTEXT.snapshot.vol_surfaces.keys())
    except Exception:
        return []
    return sorted(ids, key=lambda s: (not s.endswith("_FORTS"), s))


# ── universal pricing workstation ────────────────────────
@app.get("/pricing/catalogue")
def ws_catalogue() -> dict:
    try:
        curve_ids = list(CONTEXT.snapshot.curves.keys())
    except Exception:
        curve_ids = []
    return jsonable(pricing_workstation.build_ws_catalogue(curve_ids, _vol_surface_ids()))


@app.post("/pricing/price")
def ws_price(req: WsPriceRequest) -> dict:
    try:
        env = CONTEXT.environment(req.env_id) if req.env_id else None
        snapshot = CONTEXT.env_snapshot(env) if env else CONTEXT.snapshot
        _svc.market_data = CONTEXT.market
        result = pricing_workstation.price_ws(
            _svc, snapshot, req.product, req.engine, req.params, env=env)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"missing parameter {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=404 if "unknown product" in str(exc) else 400,
                            detail=str(exc))
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return jsonable(result)


# ── pricing environments (A1: FO / Risk / EOD / VaR / Stress контуры) ──
@app.get("/environments")
def environments_list() -> dict:
    CONTEXT.environment()                          # seed defaults on first touch
    return jsonable({"environments": CONTEXT.app_db.list_environments()})


@app.get("/environments/{env_id}")
def environments_get(env_id: str) -> dict:
    try:
        return jsonable(CONTEXT.environment(env_id).to_dict())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.put("/environments/{env_id}")
def environments_put(env_id: str, payload: EnvironmentPayload) -> dict:
    from domain.pricing_environment import PricingEnvironment
    data = payload.model_dump()
    data["env_id"] = env_id.upper()
    try:
        env = PricingEnvironment.from_dict(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    CONTEXT.save_environment(env)
    return jsonable(env.to_dict())


@app.delete("/environments/{env_id}")
def environments_delete(env_id: str) -> dict:
    if env_id.upper() in ("FO",):
        raise HTTPException(status_code=400, detail="базовый контур FO не удаляется")
    CONTEXT.app_db.delete_environment(env_id.upper())
    return {"deleted": env_id.upper()}


@app.get("/pricing/underlying/{category}/{secid}")
def ws_underlying(category: str, secid: str) -> dict:
    try:
        return jsonable(underlying.facts(CONTEXT, category, secid))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class WsGrid2DRequest(BaseModel):
    product: str
    engine: str | None = None
    params: dict[str, float | int | str | None] = {}
    x_key: str
    y_key: str
    x_lo: float
    x_hi: float
    y_lo: float
    y_hi: float
    nx: int = 9
    ny: int = 7


@app.post("/pricing/grid2d")
def ws_grid2d(req: WsGrid2DRequest) -> dict:
    try:
        _svc.market_data = CONTEXT.market
        return jsonable(pricing_workstation.grid2d_ws(
            _svc, CONTEXT.snapshot, req.product, req.engine, req.params,
            req.x_key, req.y_key, req.x_lo, req.x_hi, req.y_lo, req.y_hi,
            req.nx, req.ny))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/pricing/payoff")
def ws_payoff(req: WsPriceRequest) -> dict:
    try:
        _svc.market_data = CONTEXT.market
        return jsonable(pricing_workstation.payoff_ws(
            _svc, CONTEXT.snapshot, req.product, req.engine, req.params))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class WsImpliedVolRequest(BaseModel):
    product: str
    params: dict[str, float | int | str | None] = {}
    market_price: float


@app.post("/pricing/implied_vol")
def ws_implied_vol(req: WsImpliedVolRequest) -> dict:
    try:
        return jsonable(pricing_workstation.implied_vol_ws(
            req.product, req.params, req.market_price))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/pricing/ladder")
def ws_ladder(req: WsLadderRequest) -> dict:
    try:
        _svc.market_data = CONTEXT.market
        result = pricing_workstation.ladder_ws(
            _svc, CONTEXT.snapshot, req.product, req.engine, req.params,
            req.bump_key, req.lo, req.hi, req.steps)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "unknown product" in str(exc) else 400,
                            detail=str(exc))
    return jsonable(result)


# ── Market Risk workstation (ERS-style: HypPL / VaR / backtesting) ──
@app.get("/marketrisk")
def marketrisk_overview(confidence: float = 0.99, window: int = 500,
                        horizon: int = 1, stress: str | None = None,
                        book: str | None = None,
                        evt_threshold: float = 0.10) -> dict:
    try:
        return jsonable(marketrisk.overview(CONTEXT, confidence, window, horizon,
                                            stress=stress, book=book,
                                            evt_threshold=min(max(evt_threshold,
                                                                  0.02), 0.5)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/marketrisk/incremental")
def marketrisk_incremental(req: WsCaptureRequest, confidence: float = 0.99,
                           window: int = 500) -> dict:
    try:
        _svc.market_data = CONTEXT.market
        return jsonable(marketrisk.incremental(
            CONTEXT, req.product, req.engine, req.params, req.quantity,
            confidence, window))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/desk/multisensitivity")
def desk_multisensitivity() -> dict:
    return jsonable(desk.multisensitivity(CONTEXT))


class XvaRequest(BaseModel):
    cpty_issuer: str | None = None
    cpty_spread_bps: float = 200.0
    own_spread_bps: float = 0.0
    recovery: float = 0.40
    funding_spread_bps: float = 100.0
    cost_of_capital: float = 0.10
    csa_enabled: bool = False
    threshold: float = 0.0
    mta: float = 0.0
    mpor_weeks: float = 2.0
    n_sims: int = 4000
    use_book: bool = True


@app.post("/xva")
def xva_run(req: XvaRequest) -> dict:
    try:
        return jsonable(xva.run(CONTEXT, CONTEXT.risk, **req.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── issuer credit: ratings + z-spread hazard curves ──────
@app.get("/credit/ratings")
def credit_ratings() -> dict:
    return jsonable(credit.ratings_table(CONTEXT))


@app.get("/credit/hazard/{query}")
def credit_hazard(query: str) -> dict:
    try:
        return jsonable(credit.issuer_hazard(CONTEXT, query))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/pnl/explain")
def pnl_explain(theta_days: float = 1.0) -> dict:
    try:
        return jsonable(marketrisk.pnl_explain(CONTEXT, theta_days))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/pnl/actual")
def pnl_actual_list(limit: int = 1000) -> dict:
    rows = CONTEXT.app_db.list_actual_pnl(limit)
    return jsonable({"rows": rows, "count": len(rows)})


def _actual_pnl_number(s: str) -> float:
    """Число в ru/en-локали: '-1 234,56', '1.234,56', '1,234.5', '500'.
    При обоих разделителях десятичный — последний; одиночная запятая —
    десятичная (ru-локаль)."""
    s = s.strip().replace("\u00a0", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    return float(s)


@app.post("/pnl/actual")
def pnl_actual_import(req: ActualPnlPayload) -> dict:
    """Импорт атомарный: сначала разбор и валидация ВСЕХ строк, потом
    запись — при 422 в базе не остаётся частичного импорта."""
    entries: list[tuple[str, float]] = []
    try:
        if req.date is not None and req.pnl is not None:
            entries.append((req.date, float(req.pnl)))
        for row in req.rows or []:
            if "date" in row and "pnl" in row:
                entries.append((str(row["date"]),
                                _actual_pnl_number(str(row["pnl"]))))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"не разобран pnl: {exc}")
    for line in (req.csv or "").splitlines():
        sep = ";" if ";" in line else ","
        parts = [p.strip() for p in line.split(sep)]
        if not parts[0] or parts[0].lower() in ("date", "дата"):
            continue
        if len(parts) != 2:
            raise HTTPException(
                status_code=422,
                detail=f"строка CSV не 'date{sep}pnl' (десятичная запятая "
                       f"требует разделителя ';'): {line!r}")
        try:
            entries.append((parts[0], _actual_pnl_number(parts[1])))
        except ValueError:
            raise HTTPException(status_code=422,
                                detail=f"не разобрана строка CSV: {line!r}")
    if not entries:
        raise HTTPException(status_code=422,
                            detail="нет данных: нужен date+pnl, rows или csv")
    for dt, _ in entries:                      # валидация ДО записи
        try:
            date.fromisoformat(dt)             # строгая: 2026-02-31 не пройдёт
        except ValueError:
            raise HTTPException(status_code=422,
                                detail=f"дата не YYYY-MM-DD: {dt!r}")
    for dt, pnl in entries:
        CONTEXT.app_db.save_actual_pnl(dt, pnl, req.source, req.note)
    return jsonable({"imported": len(entries),
                     "total": len(CONTEXT.app_db.list_actual_pnl())})


@app.delete("/pnl/actual/{dt}")
def pnl_actual_delete(dt: str) -> dict:
    CONTEXT.app_db.delete_actual_pnl(dt)
    return jsonable({"deleted": dt})


@app.post("/portfolio/add_market")
def portfolio_add_market(category: str, secid: str, quantity: float = 1.0) -> dict:
    try:
        instrument, params, desc = underlying.market_position(CONTEXT, category, secid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    pos = CONTEXT.add_position(instrument, params, desc, quantity)
    try:
        CONTEXT.portfolio.price_all()
    except Exception:
        pass
    return jsonable({"position_id": pos.id, "instrument": pos.instrument,
                     "description": pos.description, "quantity": pos.quantity,
                     "market_value": pos.market_value,
                     "positions": len(CONTEXT.portfolio.positions)})


@app.get("/marketrisk/montecarlo")
def marketrisk_montecarlo(confidence: float = 0.99, window: int = 500,
                          n_sims: int = 1000) -> dict:
    try:
        return jsonable(marketrisk.mc_var_matrix(CONTEXT, confidence, window,
                                                 min(n_sims, 5000)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/marketrisk/pca")
def marketrisk_pca(confidence: float = 0.99, window: int = 500) -> dict:
    try:
        return jsonable(marketrisk.pca_rates(CONTEXT, confidence, window))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/marketrisk/backtest")
def marketrisk_backtest(confidence: float = 0.99, window: int = 500,
                        lookback: int = 250) -> dict:
    try:
        return jsonable(marketrisk.backtest(CONTEXT, confidence, window, lookback))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/pricing/scenarios")
def ws_scenarios(req: WsPriceRequest) -> dict:
    try:
        _svc.market_data = CONTEXT.market
        result = pricing_workstation.scenarios_ws(
            _svc, CONTEXT.snapshot, req.product, req.engine, req.params)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "unknown product" in str(exc) else 400,
                            detail=str(exc))
    return jsonable(result)


# ── per-screen data endpoints ────────────────────────────
@app.get("/dashboard")
def dashboard() -> dict:
    return jsonable(payloads.dashboard(CONTEXT))


@app.get("/market")
def market() -> dict:
    return jsonable(payloads.market(CONTEXT))


@app.get("/portfolio")
def portfolio(book: str | None = None, instrument: str | None = None,
              currency: str | None = None) -> dict:
    return jsonable(payloads.portfolio(CONTEXT, book, instrument, currency))


@app.get("/portfolio/books")
def portfolio_books() -> dict:
    return jsonable({"books": CONTEXT.books()})


# ── trade capture: workstation -> persistent book ────────
@app.post("/portfolio/add")
def portfolio_add(req: WsCaptureRequest) -> dict:
    try:
        quantity = pricing_workstation.portfolio_quantity(req.quantity)
        mapped = pricing_workstation.to_position(
            req.product, req.params, engine_id=req.engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if mapped is None:
        raise HTTPException(status_code=400,
                            detail=f"'{req.product}' не поддерживается портфельной переоценкой")
    resolved_engine = pricing_workstation.portfolio_repricing_engine(req.product)
    instrument, params, default_desc = mapped
    pos = CONTEXT.add_position(instrument, params,
                               req.description or default_desc, quantity)
    try:
        CONTEXT.portfolio.price_all()
    except Exception:
        pass
    return jsonable({"position_id": pos.id, "instrument": pos.instrument,
                     "engine": resolved_engine,
                     "description": pos.description, "quantity": pos.quantity,
                     "market_value": pos.market_value,
                     "positions": len(CONTEXT.portfolio.positions)})


@app.delete("/portfolio/position/{position_id}")
def portfolio_remove(position_id: str) -> dict:
    ids = {p.id for p in CONTEXT.portfolio.positions}
    if position_id not in ids:
        raise HTTPException(status_code=404, detail=f"unknown position '{position_id}'")
    CONTEXT.remove_position(position_id)
    return {"removed": position_id, "positions": len(CONTEXT.portfolio.positions)}


@app.post("/portfolio/reset")
def portfolio_reset() -> dict:
    CONTEXT.reset_portfolio()
    return {"reset": True, "positions": len(CONTEXT.portfolio.positions)}


@app.get("/risk")
def risk() -> dict:
    return jsonable(payloads.risk(CONTEXT))


@app.get("/governance")
def governance() -> dict:
    return jsonable(payloads.governance(CONTEXT))


@app.get("/analytics")
def analytics() -> dict:
    return jsonable(payloads.analytics(CONTEXT))


# ── fixed income (Bond tab) ──────────────────────────────
@app.get("/curves")
def curves() -> dict:
    return jsonable(payloads.curves(CONTEXT))


@app.get("/instruments/bond")
def bond_catalogue() -> dict:
    curve_ids = list(CONTEXT.snapshot.curves.keys())
    return jsonable(instruments.build_bond_catalogue(curve_ids))


@app.post("/instruments/bond/price")
def bond_price(req: InstrumentPriceRequest) -> dict:
    inst = instruments.find_instrument(req.instrument)
    if inst is None:
        raise HTTPException(status_code=404, detail=f"unknown instrument '{req.instrument}'")
    try:
        result = inst.invoke(_svc, req.params, CONTEXT.snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"missing parameter {exc}")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return jsonable(instruments.normalize_bond_result(result))


@app.post("/instruments/bond/price_batch")
def bond_price_batch(req: BatchPriceRequest) -> dict:
    rows = [r.model_dump() for r in req.bonds]
    return jsonable(instruments.price_batch(_svc, CONTEXT.snapshot, rows))


# ── real bonds (MOEX ISS feed) ───────────────────────────
@app.get("/realbonds")
def real_bonds(board: str | None = None, search: str | None = None, limit: int = 300) -> dict:
    return jsonable(realbonds.list_real_bonds(CONTEXT, board=board, search=search, limit=limit))


@app.post("/realbonds/reprice")
def real_bond_reprice(req: RepriceRequest) -> dict:
    try:
        return jsonable(realbonds.reprice(
            CONTEXT, req.secid, req.curve_id, req.shift_bps,
            forecast_curve_id=req.forecast_curve_id, float_spread_bps=req.float_spread_bps))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── instrument catalog (Market Data) ─────────────────────
@app.post("/ingest/refresh")
def ingest_refresh() -> dict:
    return jsonable(ingest_job.start(CONTEXT))


@app.get("/ingest/status")
def ingest_status() -> dict:
    return jsonable(ingest_job.status())


@app.get("/snapshots")
def snapshots() -> dict:
    return jsonable(marketdata.snapshots(CONTEXT))


@app.get("/marketcurves")
def market_curves(snapshot_id: str | None = None) -> dict:
    return jsonable(marketdata.curves(CONTEXT, snapshot_id=snapshot_id))


@app.get("/catalog/categories")
def catalog_categories(snapshot_id: str | None = None) -> dict:
    return jsonable(catalog.categories(CONTEXT, snapshot_id=snapshot_id))


@app.get("/catalog/{category}")
def catalog_category(category: str, search: str | None = None, limit: int = 500,
                     board: str | None = None, sort: str | None = None, desc: bool = False,
                     snapshot_id: str | None = None) -> dict:
    return jsonable(catalog.catalog(CONTEXT, category, search=search, limit=limit,
                                    board=board, sort=sort, desc=desc, snapshot_id=snapshot_id))


@app.get("/history/{category}/{secid}")
def trade_history(category: str, secid: str, days: int = 180) -> dict:
    return jsonable(history.trade_history(category, secid, days=days))


# ── historical time series (5y backfill store) ───────────
@app.get("/timeseries/catalog")
def timeseries_catalog() -> dict:
    return jsonable(timeseries.catalog(CONTEXT))


@app.get("/timeseries")
def timeseries_series(factor_id: str, frm: str | None = None, till: str | None = None) -> dict:
    return jsonable(timeseries.series(CONTEXT, factor_id, frm=frm, till=till))


# ── instrument-entity market data (continuously-accumulated store) ────────
@app.get("/md/list/{category}")
def md_list(category: str) -> dict:
    return jsonable(market_entity.list_instruments(CONTEXT, category))


@app.get("/md/instrument/{category}/{secid}")
def md_instrument(category: str, secid: str) -> dict:
    try:
        return jsonable(market_entity.instrument(CONTEXT, category, secid))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/md/history/{secid}")
def md_history(secid: str, market: str = "bonds", range: str = "5Y",
               interval: str = "1d", mode: str = "price") -> dict:
    return jsonable(market_entity.history(CONTEXT, secid, market=market, rng=range,
                                          interval=interval, mode=mode))


@app.get("/md/candles/{secid}")
def md_candles(secid: str, market: str = "bonds", interval: int = 60,
               category: str | None = None) -> dict:
    return jsonable(intraday.candles(CONTEXT, secid, market=market,
                                     interval=interval, category=category))


@app.get("/md/live/{category}")
def md_live(category: str) -> dict:
    return jsonable(livequotes.live_quotes(category))


@app.get("/md/overview")
def md_overview() -> dict:
    return jsonable(market_entity.overview(CONTEXT))


@app.get("/md/refdata")
def md_refdata() -> dict:
    return jsonable(market_entity.refdata(CONTEXT))


@app.get("/md/search")
def md_search(q: str = "") -> dict:
    return jsonable(market_entity.search(CONTEXT, q))


@app.get("/md/health")
def md_health() -> dict:
    return jsonable(datahealth.health(CONTEXT))


@app.get("/md/validation")
def md_validation() -> dict:
    return jsonable(datahealth.validation(CONTEXT))


@app.get("/snapshots/{snapshot_id}/validation")
def snapshot_validation(snapshot_id: str) -> dict:
    return jsonable(datahealth.validation(CONTEXT, snapshot_id))


@app.get("/md/raw/tables")
def md_raw_tables() -> dict:
    return jsonable(rawdata.tables(CONTEXT))


@app.get("/md/raw/dictionary")
def md_raw_dictionary() -> dict:
    return jsonable(rawdata.dictionary(CONTEXT))


@app.get("/md/raw/{table}")
def md_raw_table(table: str, limit: int = 200) -> dict:
    return jsonable(rawdata.rows(CONTEXT, table, limit))


@app.get("/md/volsurface")
def md_volsurface_list() -> dict:
    return jsonable(volsurface.list_underlyings(CONTEXT))


@app.get("/md/volsurface/{underlying}")
def md_volsurface(underlying: str) -> dict:
    return jsonable(volsurface.surface(CONTEXT, underlying))


@app.get("/md/volsurface/{underlying}/otc")
def md_volsurface_otc(underlying: str) -> dict:
    return jsonable(volsurface.otc_surface(CONTEXT, underlying))


@app.get("/md/volsurface/{underlying}/plot")
def md_volsurface_plot(underlying: str) -> Response:
    png = volsurface.surface_png(CONTEXT, underlying)
    if not png:
        raise HTTPException(status_code=404, detail="no surface to plot")
    return Response(content=png, media_type="image/png")


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
