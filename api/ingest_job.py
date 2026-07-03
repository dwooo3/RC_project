"""Background MOEX ingestion job.

Pulls a fresh, comprehensive snapshot for today from ISS in a worker thread and
activates it, so the app moves from the stored snapshot up to the current day.
Progress is exposed via `status()` for the UI to poll. One job at a time.
"""

from __future__ import annotations

import datetime
import threading

_state: dict = {"status": "idle", "message": "", "steps": [],
                "snapshot_id": None, "started": None, "finished": None}
_lock = threading.Lock()


def status() -> dict:
    with _lock:
        return {**_state, "steps": list(_state["steps"])}


def start(ctx) -> dict:
    with _lock:
        if _state["status"] == "running":
            return {"started": False, **_state}
        _state.update(status="running", message="starting…", steps=[],
                      started=datetime.datetime.now().isoformat(), finished=None)
    threading.Thread(target=_run, args=(ctx,), daemon=True).start()
    return {"started": True, **status()}


def _set(**kw) -> None:
    with _lock:
        _state.update(**kw)


def _step(name: str, fn) -> None:
    _set(message=f"ingesting {name}…")
    try:
        rows = fn()
        with _lock:
            _state["steps"].append({"step": name, "rows": int(rows), "ok": True})
    except Exception as exc:
        with _lock:
            _state["steps"].append({"step": name, "rows": 0, "ok": False, "error": str(exc)[:140]})


def _run(ctx) -> None:
    try:
        from app import runtime

        from infra.cbr.client import CbrClient
        from infra.db.market_data_db import MarketDataDB
        from infra.jobs.eod_ingest import EodIngestJob
        from infra.moex_iss.client import IssClient
        from infra.moex_iss.ingest import MoexIngestor

        path = runtime.db_path()
        if not path:
            _set(status="error", message="no market-data DB path",
                 finished=datetime.datetime.now().isoformat())
            return

        vd = datetime.date.today()
        sid = MoexIngestor.snapshot_id_for(vd)
        _set(snapshot_id=sid, message="running full ISS + CBR ingest (curves, bonds, "
             "corporate, FX/FXFWD, equities, vols, bondization)…")

        db = MarketDataDB(path)
        db.init_schema()
        # Canonical comprehensive pipeline — every curve (incl. CBR key-rate /
        # RUONIA + FX-forward), bonds (OFZ + corporate), schedules, equities, vols.
        job = EodIngestJob(db, IssClient(), CbrClient(), corp_board="TQCB", bondization_top=120)
        summary = job.run(vd)
        with _lock:
            _state["steps"] = [{"step": name, "result": str(res)} for name, res in summary.get("steps", {}).items()]

        # Keep the continuous store in step with the snapshot: append the
        # missing EOD days market-wide (cheap — one request per board per date),
        # refresh CBR FX, then recompute the denormalised list quotes.
        from infra.market_store import MarketStore
        store = MarketStore(db, IssClient(), CbrClient())
        _step("daily_history", lambda: sum(
            m["rows_added"] for m in store.append_daily().values()))
        _step("fx_history", lambda: store.preload_fx()["rows_added"])
        _step("list_quotes", store.refresh_last_change)
        db.close()

        ctx.reload()
        snap = ctx.snapshot
        activated = snap.snapshot_id
        ok = activated == sid and not getattr(snap, "is_demo", True)
        _set(status="done" if ok else "warning",
             message=(f"activated {activated}" if ok else
                      f"ingested {sid} but active snapshot is {activated} "
                      f"({'demo' if getattr(snap, 'is_demo', True) else 'older'})"),
             finished=datetime.datetime.now().isoformat())
    except Exception as exc:
        _set(status="error", message=str(exc)[:200],
             finished=datetime.datetime.now().isoformat())
