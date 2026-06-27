"""FastAPI bridge for the SwiftUI client.

Run from the project root:

    /usr/local/bin/python3.14 -m api.server         # serves on 127.0.0.1:8765

Endpoints
    GET  /health      liveness + version
    GET  /catalogue   the vanilla pricer catalogue (governance + param specs)
    POST /price       {"pricer": "<id>", "params": {...}} -> governed result

The engine runs with `allow_analytics_lab=True` so research models (Heston, Merton)
return a governed result with their lab-status warnings rather than a hard block —
the client surfaces the status so nothing is silently treated as production-grade.
"""

from __future__ import annotations

import os
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
    instruments,
    market_entity,
    marketdata,
    payloads,
    rawdata,
    realbonds,
    timeseries,
    volsurface,
)
from api.catalogue import build_catalogue, find_pricer
from api.context import CONTEXT
from api.serialization import jsonable
from services.pricing_service import PricingService

VERSION = "0.2.0"

app = FastAPI(title="RiskCalc Bridge", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_svc = PricingService(allow_analytics_lab=True)


class PriceRequest(BaseModel):
    pricer: str
    params: dict[str, float | int | str | None] = {}


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
    return {
        "status": "ok",
        "service": "RiskCalc Bridge",
        "version": VERSION,
        "live": CONTEXT.is_live(),
        "snapshot_id": CONTEXT.snapshot.snapshot_id,
    }


def _vol_surface_ids() -> list[str]:
    """Surface ids in the active snapshot, FORTS first — choices for the pricer's
    vol_surface_id selector."""
    try:
        ids = list(CONTEXT.snapshot.vol_surfaces.keys())
    except Exception:
        return []
    return sorted(ids, key=lambda s: (not s.endswith("_FORTS"), s))


@app.get("/catalogue")
def catalogue() -> dict:
    return {"pricers": build_catalogue(_vol_surface_ids())}


# ── per-screen data endpoints ────────────────────────────
@app.get("/dashboard")
def dashboard() -> dict:
    return jsonable(payloads.dashboard(CONTEXT))


@app.get("/market")
def market() -> dict:
    return jsonable(payloads.market(CONTEXT))


@app.get("/portfolio")
def portfolio() -> dict:
    return jsonable(payloads.portfolio(CONTEXT))


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
def md_history(secid: str, market: str = "bonds", range: str = "5Y") -> dict:
    return jsonable(market_entity.history(CONTEXT, secid, market=market, rng=range))


@app.get("/md/overview")
def md_overview() -> dict:
    return jsonable(market_entity.overview(CONTEXT))


@app.get("/md/health")
def md_health() -> dict:
    return jsonable(datahealth.health(CONTEXT))


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


@app.get("/md/volsurface/{underlying}/plot")
def md_volsurface_plot(underlying: str) -> Response:
    png = volsurface.surface_png(CONTEXT, underlying)
    if not png:
        raise HTTPException(status_code=404, detail="no surface to plot")
    return Response(content=png, media_type="image/png")


@app.post("/price")
def price(req: PriceRequest) -> dict:
    pricer = find_pricer(req.pricer)
    if pricer is None:
        raise HTTPException(status_code=404, detail=f"unknown pricer '{req.pricer}'")
    try:
        _svc.market_data = CONTEXT.market          # live surfaces for surface-aware pricing
        result = pricer.invoke(_svc, req.params, CONTEXT.snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"missing parameter {exc}")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return jsonable(result)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
