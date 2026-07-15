"""FastAPI bridge for the SwiftUI client.

Run from the project root:

    /usr/local/bin/python3.14 -m api.server         # serves on 127.0.0.1:8765

Endpoints
    GET  /health             liveness + version
    GET  /pricing/catalogue  the universal pricer catalogue (products x engines)
    POST /pricing/price      {"product","engine","params"} -> normalized result

Workstation endpoints are fail-closed by default. Research and other
non-production engines may execute only in the explicit, server-owned ``LAB``
pricing environment; every derived pricing route uses the same policy.
"""

from __future__ import annotations

import os
from datetime import date
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
from api import capture_workflow, credit, custom_products, desk, marketrisk, pricing_jobs, pricing_workstation, underlying, xva
from api.context import CONTEXT
from api.serialization import jsonable
from services.pricing_service import PricingService

VERSION = "0.2.0"

app = FastAPI(title="RiskCalc Bridge", version=VERSION)
# Local desktop bridge: only browser clients on this machine may call it
# (the Swift app uses URLSession and is unaffected). No wildcard in line
# with spec §23/§27.16; auth/entitlements remain a known gap (см. отчёт).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost",
                   "http://127.0.0.1:8765", "http://localhost:8765"],
    allow_methods=["*"], allow_headers=["*"],
)

_svc = PricingService(
    allow_analytics_lab=True,
    allow_non_production_models=True,
    audit=CONTEXT.audit,
)


_WORKSTATION_ENV_PERMISSIONS = {
    # Server-owned permission map. Environment metadata is user-editable and
    # therefore must never grant research/non-production execution rights.
    "LAB": (True, True),
}


def _workstation_permissions(env) -> tuple[bool, bool]:
    """Resolve server-owned research permissions for an explicit environment."""
    if env is None:
        return False, False
    env_id = str(getattr(env, "env_id", "")).upper()
    purpose = str(getattr(env, "purpose", "")).lower()
    if env_id == "LAB" and purpose != "research":
        return False, False
    return _WORKSTATION_ENV_PERMISSIONS.get(env_id, (False, False))


def _workstation_service(env) -> PricingService:
    allow_lab, allow_non_production = _workstation_permissions(env)
    return PricingService(
        market_data=CONTEXT.market,
        governance=_svc.governance,
        audit=CONTEXT.audit,
        allow_analytics_lab=allow_lab,
        allow_non_production_models=allow_non_production,
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
    env_id: str | None = None


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


def _vol_surface_ids(snapshot=None) -> list[str]:
    """Surface ids in the selected snapshot, FORTS first — choices for the pricer's
    vol_surface_id selector."""
    try:
        ids = list((snapshot or CONTEXT.snapshot).vol_surfaces.keys())
    except Exception:
        return []
    return sorted(ids, key=lambda s: (not s.endswith("_FORTS"), s))


def _workstation_runtime(env_id: str | None):
    """Resolve one immutable request-local workstation execution context."""
    env = CONTEXT.environment(env_id) if env_id else None
    snapshot = CONTEXT.env_snapshot(env) if env else CONTEXT.snapshot
    curve_ids = list((getattr(snapshot, "curves", None) or {}).keys())
    surface_ids = _vol_surface_ids(snapshot)
    return env, snapshot, _workstation_service(env), curve_ids, surface_ids


# ── universal pricing workstation ────────────────────────
@app.get("/pricing/catalogue")
def ws_catalogue() -> dict:
    try:
        curve_ids = list(CONTEXT.snapshot.curves.keys())
    except Exception:
        curve_ids = []
    return jsonable(pricing_workstation.build_ws_catalogue(curve_ids, _vol_surface_ids()))


@app.post("/pricing/validate")
def ws_validate(req: WsPriceRequest) -> dict:
    """Authoritative fail-closed validation of a pricing request (spec §7.5):
    product/engine existence, unknown params, dtype/choice/range checks."""
    try:
        env, snapshot, _, curve_ids, surface_ids = _workstation_runtime(req.env_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    allow_lab, allow_non_production = _workstation_permissions(env)
    return jsonable(pricing_workstation.validate_ws(
        req.product, req.engine, req.params,
        curve_ids=curve_ids, surface_ids=surface_ids, env=env,
        allow_analytics_lab=allow_lab,
        allow_non_production=allow_non_production))


@app.post("/pricing/price")
def ws_price(req: WsPriceRequest) -> dict:
    try:
        env, snapshot, ws_service, curve_ids, surface_ids = _workstation_runtime(
            req.env_id
        )
        result = pricing_workstation.price_ws(
            ws_service, snapshot, req.product, req.engine, req.params, env=env,
            curve_ids=curve_ids, surface_ids=surface_ids)
    except KeyError as exc:
        status = 404 if "pricing environment" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc))
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
    if env_id.upper() in ("FO", "LAB"):
        raise HTTPException(
            status_code=400,
            detail="базовые контуры FO/LAB не удаляются",
        )
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
    env_id: str | None = None


@app.post("/pricing/grid2d")
def ws_grid2d(req: WsGrid2DRequest) -> dict:
    try:
        env, snapshot, svc, curve_ids, surface_ids = _workstation_runtime(req.env_id)
        return jsonable(pricing_workstation.grid2d_ws(
            svc, snapshot, req.product, req.engine, req.params,
            req.x_key, req.y_key, req.x_lo, req.x_hi, req.y_lo, req.y_hi,
            req.nx, req.ny, env=env, curve_ids=curve_ids,
            surface_ids=surface_ids))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/pricing/payoff")
def ws_payoff(req: WsPriceRequest) -> dict:
    try:
        env, snapshot, svc, curve_ids, surface_ids = _workstation_runtime(req.env_id)
        return jsonable(pricing_workstation.payoff_ws(
            svc, snapshot, req.product, req.engine, req.params, env=env,
            curve_ids=curve_ids, surface_ids=surface_ids))
    except (KeyError, ValueError, TypeError) as exc:
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
        env, snapshot, svc, curve_ids, surface_ids = _workstation_runtime(req.env_id)
        result = pricing_workstation.ladder_ws(
            svc, snapshot, req.product, req.engine, req.params,
            req.bump_key, req.lo, req.hi, req.steps, env=env,
            curve_ids=curve_ids, surface_ids=surface_ids)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=404 if "unknown product" in str(exc) else 400,
                            detail=str(exc))
    return jsonable(result)


# ── async analytics jobs (spec §18): progress / partial / cancel ──
class WsJobRequest(BaseModel):
    kind: str                      # ladder | grid2d | scenarios | payoff
    product: str
    engine: str | None = None
    params: dict[str, float | int | str | None] = {}
    env_id: str | None = None
    client_request_id: str | None = None
    # ladder
    bump_key: str | None = None
    lo: float | None = None
    hi: float | None = None
    steps: int = 15
    # grid2d
    x_key: str | None = None
    y_key: str | None = None
    x_lo: float | None = None
    x_hi: float | None = None
    y_lo: float | None = None
    y_hi: float | None = None
    nx: int = 9
    ny: int = 7
    # compare / convergence (phase 3)
    reference_engine: str | None = None
    levels: list[int] | None = None


_JOB_KINDS = {"ladder", "grid2d", "scenarios", "payoff", "compare",
              "convergence"}
_JOB_REQUIRED = {"ladder": ("bump_key", "lo", "hi"),
                 "grid2d": ("x_key", "y_key", "x_lo", "x_hi", "y_lo", "y_hi")}


@app.post("/pricing/jobs", status_code=202)
def ws_job_submit(req: WsJobRequest) -> dict:
    if req.kind not in _JOB_KINDS:
        raise HTTPException(status_code=422, detail={
            "code": "JOB_UNKNOWN_KIND",
            "message": f"unknown job kind '{req.kind}'"})
    for field in _JOB_REQUIRED.get(req.kind, ()):
        if getattr(req, field) is None:
            raise HTTPException(status_code=422, detail={
                "code": "SCHEMA_MISSING_FIELD",
                "message": f"'{field}' is required for kind '{req.kind}'"})
    # Freeze one execution context at submit (spec §13.3) and validate
    # fail-closed BEFORE a job exists — invalid inputs never enqueue.
    env, snapshot, svc, curve_ids, surface_ids = _workstation_runtime(req.env_id)
    validation = pricing_workstation.validate_ws(
        req.product, req.engine, req.params,
        curve_ids=curve_ids, surface_ids=surface_ids, env=env)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_FAILED",
            "issues": jsonable(validation["issues"])})

    kind = req.kind

    def work(hook):
        if kind == "ladder":
            return pricing_workstation.ladder_ws(
                svc, snapshot, req.product, req.engine, req.params,
                req.bump_key, req.lo, req.hi, req.steps, env=env,
                curve_ids=curve_ids, surface_ids=surface_ids, hook=hook)
        if kind == "grid2d":
            return pricing_workstation.grid2d_ws(
                svc, snapshot, req.product, req.engine, req.params,
                req.x_key, req.y_key, req.x_lo, req.x_hi, req.y_lo, req.y_hi,
                req.nx, req.ny, env=env,
                curve_ids=curve_ids, surface_ids=surface_ids, hook=hook)
        if kind == "payoff":
            return pricing_workstation.payoff_ws(
                svc, snapshot, req.product, req.engine, req.params, env=env,
                curve_ids=curve_ids, surface_ids=surface_ids, hook=hook)
        if kind == "compare":
            return pricing_workstation.compare_ws(
                svc, snapshot, req.product,
                req.reference_engine or req.engine, req.params, env=env,
                curve_ids=curve_ids, surface_ids=surface_ids, hook=hook)
        if kind == "convergence":
            return pricing_workstation.convergence_ws(
                svc, snapshot, req.product, req.engine, req.params,
                levels=req.levels, env=env,
                curve_ids=curve_ids, surface_ids=surface_ids, hook=hook)
        return pricing_workstation.scenarios_ws(
            svc, snapshot, req.product, req.engine, req.params, env=env,
            curve_ids=curve_ids, surface_ids=surface_ids, hook=hook)

    job = pricing_jobs.MANAGER.submit(
        kind, req.model_dump(), work, client_request_id=req.client_request_id)
    return jsonable(job.snapshot())


def _job_or_404(job_id: str) -> pricing_jobs.PricingJob:
    job = pricing_jobs.MANAGER.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={
            "code": "JOB_NOT_FOUND", "message": f"job '{job_id}' not found"})
    return job


@app.get("/pricing/jobs/{job_id}")
def ws_job_snapshot(job_id: str) -> dict:
    return jsonable(_job_or_404(job_id).snapshot())


@app.get("/pricing/jobs/{job_id}/events")
def ws_job_events(job_id: str, after: int = 0, wait: float = 0.0) -> dict:
    """Ordered events after seq `after`; wait>0 long-polls up to 25 s."""
    job = _job_or_404(job_id)
    events = (job.wait_events(after, timeout=min(wait, 25.0)) if wait > 0
              else job.events_since(after))
    return jsonable({"job_id": job.job_id, "state": job.state,
                     "events": events})


@app.post("/pricing/jobs/{job_id}/cancel")
def ws_job_cancel(job_id: str) -> dict:
    """Idempotent: cancelling a terminal job returns its state unchanged."""
    job = _job_or_404(job_id)
    return {"job_id": job.job_id, "state": job.request_cancel()}


@app.get("/pricing/jobs/{job_id}/stream")
def ws_job_stream(job_id: str, request: Request) -> StreamingResponse:
    """SSE event stream; resume with the standard Last-Event-ID header."""
    import json as _json

    job = _job_or_404(job_id)
    try:
        after = int(request.headers.get("last-event-id") or 0)
    except ValueError:
        after = 0

    def gen():
        cursor = after
        while True:
            events = job.wait_events(cursor, timeout=20.0)
            for e in events:
                cursor = e["seq"]
                payload = _json.dumps(
                    jsonable({"state": job.state, **e["data"]}),
                    ensure_ascii=False)
                yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {payload}\n\n"
            if (job.state in ("completed", "failed", "cancelled", "expired")
                    and not job.events_since(cursor)):
                return
            if not events:
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── Phase 3 sync analytics: solve-for and simulation lab ──
class WsSolveRequest(BaseModel):
    product: str
    engine: str | None = None
    params: dict[str, float | int | str | None] = {}
    solve_key: str
    target: float
    lo: float
    hi: float
    env_id: str | None = None


@app.post("/pricing/solve")
def ws_solve(req: WsSolveRequest) -> dict:
    try:
        env, snapshot, svc, curve_ids, surface_ids = _workstation_runtime(
            req.env_id)
        return jsonable(pricing_workstation.solve_ws(
            svc, snapshot, req.product, req.engine, req.params,
            req.solve_key, req.target, req.lo, req.hi, env=env,
            curve_ids=curve_ids, surface_ids=surface_ids))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=404 if "unknown product" in str(exc)
                            else 400, detail=str(exc))


class WsSimLabRequest(BaseModel):
    product: str
    params: dict[str, float | int | str | None] = {}
    n_paths: int = 2000
    n_steps: int = 60
    seed: int = 42


@app.post("/pricing/simlab")
def ws_simlab(req: WsSimLabRequest) -> dict:
    try:
        return jsonable(pricing_workstation.simlab_ws(
            req.product, req.params, req.n_paths, req.n_steps, req.seed))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=404 if "unknown product" in str(exc)
                            else 400, detail=str(exc))


# ── Custom Product Engine (spec §16) ──
class CustomCreateRequest(BaseModel):
    template_id: str | None = None
    definition: dict | None = None
    name: str | None = None
    author: str = "user"
    slot_defaults: dict[str, float] = {}


class CustomDefinitionRequest(BaseModel):
    definition: dict


class CustomActionRequest(BaseModel):
    user: str = "user"


class CustomPriceRequest(BaseModel):
    slots: dict[str, float] = {}
    # scalar r/sigma/q/rho, per-asset sigmas/qs lists, corr matrix
    market: dict[str, float | list[float] | list[list[float]]] = {}
    n_sims: int = 50_000
    steps: int = 252
    seed: int = 42


def _custom(fn):
    try:
        return jsonable(fn())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/custom/templates")
def custom_templates() -> dict:
    return jsonable({"templates": custom_products.get_store().templates()})


@app.get("/custom/products")
def custom_list() -> dict:
    return jsonable({"products": custom_products.get_store().list_products()})


@app.get("/custom/products/{product_id}")
def custom_get(product_id: str) -> dict:
    return _custom(lambda: custom_products.get_store().get(product_id))


@app.post("/custom/products", status_code=201)
def custom_create(req: CustomCreateRequest) -> dict:
    return _custom(lambda: custom_products.get_store().create(
        definition=req.definition, template_id=req.template_id,
        name=req.name, author=req.author, slot_defaults=req.slot_defaults))


@app.put("/custom/products/{product_id}")
def custom_update(product_id: str, req: CustomDefinitionRequest) -> dict:
    return _custom(lambda: custom_products.get_store().update_definition(
        product_id, req.definition))


@app.post("/custom/products/{product_id}/compile")
def custom_compile(product_id: str) -> dict:
    return _custom(lambda: custom_products.get_store().compile(product_id))


@app.post("/custom/products/{product_id}/submit")
def custom_submit(product_id: str, req: CustomActionRequest) -> dict:
    return _custom(lambda: custom_products.get_store().submit(product_id, req.user))


@app.post("/custom/products/{product_id}/approve")
def custom_approve(product_id: str, req: CustomActionRequest) -> dict:
    return _custom(lambda: custom_products.get_store().approve(product_id, req.user))


@app.post("/custom/products/{product_id}/publish")
def custom_publish(product_id: str) -> dict:
    return _custom(lambda: custom_products.get_store().publish(product_id))


@app.post("/custom/products/{product_id}/deprecate")
def custom_deprecate(product_id: str) -> dict:
    return _custom(lambda: custom_products.get_store().deprecate(product_id))


@app.post("/custom/products/{product_id}/versions")
def custom_new_version(product_id: str, req: CustomActionRequest) -> dict:
    return _custom(lambda: custom_products.get_store().new_version(
        product_id, author=req.user))


@app.get("/custom/products/{product_id}/diff")
def custom_diff(product_id: str, v_from: int, v_to: int) -> dict:
    return _custom(lambda: custom_products.get_store().diff(product_id, v_from, v_to))


@app.post("/custom/products/{product_id}/price")
def custom_price(product_id: str, req: CustomPriceRequest) -> dict:
    return _custom(lambda: custom_products.get_store().price(
        product_id, req.slots, req.market,
        n_sims=req.n_sims, steps=req.steps, seed=req.seed))


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
        env, snapshot, svc, curve_ids, surface_ids = _workstation_runtime(req.env_id)
        result = pricing_workstation.scenarios_ws(
            svc, snapshot, req.product, req.engine, req.params, env=env,
            curve_ids=curve_ids, surface_ids=surface_ids)
    except (KeyError, ValueError, TypeError) as exc:
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
    """DEPRECATED: без hash-гейта и approval-политики. Новый клиентский путь —
    POST /portfolio/capture (атомарный, exact-run, replay-паритет)."""
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


# ── Phase 5: approval evidence + atomic capture (spec §17, §20) ──
_APPROVALS = capture_workflow.ApprovalRegistry(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "data", "run_approvals.json"))


class RunApproveRequest(BaseModel):
    inputs_hash: str
    calculation_id: str = ""
    user: str


@app.post("/pricing/runs/approve")
def pricing_run_approve(req: RunApproveRequest) -> dict:
    try:
        return jsonable(_APPROVALS.approve(req.inputs_hash,
                                           req.calculation_id, req.user))
    except capture_workflow.CaptureError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.payload())


class WsAtomicCaptureRequest(BaseModel):
    product: str
    engine: str | None = None
    params: dict[str, float | int | str | None] = {}
    quantity: float = 1.0
    description: str | None = None
    expected_inputs_hash: str
    requested_by: str = "user"
    env_id: str | None = None


@app.post("/portfolio/capture")
def portfolio_capture(req: WsAtomicCaptureRequest) -> dict:
    """Atomic capture: server-side reprice on the frozen context, exact
    inputs_hash match (409 on drift), policy approval gate, rollback on
    book-reprice failure — returns the position + replay lineage."""
    env, snapshot, svc, curve_ids, surface_ids = _workstation_runtime(req.env_id)
    try:
        quantity = pricing_workstation.portfolio_quantity(req.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    def reprice() -> dict:
        return pricing_workstation.price_ws(
            svc, snapshot, req.product, req.engine, req.params, env=env,
            curve_ids=curve_ids, surface_ids=surface_ids)

    def map_position():
        mapped = pricing_workstation.to_position(
            req.product, req.params, engine_id=req.engine)
        if mapped is None:
            return None
        instrument, params, default_desc = mapped
        return instrument, params, req.description or default_desc

    def add_position(instrument, params, description, qty):
        return CONTEXT.add_position(instrument, params, description, qty)

    def remove_position(position):
        CONTEXT.remove_position(position.id)

    def reprice_book():
        CONTEXT.portfolio.price_all()

    def position_value(position):
        return position.market_value

    try:
        outcome = capture_workflow.atomic_capture(
            reprice=reprice, map_position=map_position,
            add_position=add_position, remove_position=remove_position,
            reprice_book=reprice_book, approvals=_APPROVALS,
            quantity=quantity, expected_inputs_hash=req.expected_inputs_hash,
            requested_by=req.requested_by, position_value=position_value)
    except capture_workflow.CaptureError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.payload())
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    position = outcome["position"]
    return jsonable({
        "position_id": position.id, "instrument": position.instrument,
        "description": position.description, "quantity": position.quantity,
        "market_value": position.market_value,
        "positions": len(CONTEXT.portfolio.positions),
        "lineage": outcome["lineage"],
        "replay": outcome["replay"],
    })


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


@app.get("/governance/quant-components")
def quant_governance() -> dict:
    """Versioned QW1 model, solver, eligibility and publication ledgers."""
    return jsonable(payloads.quant_governance(CONTEXT))


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
