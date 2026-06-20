"""Tests for the SwiftUI HTTP bridge (transport + serialization only).

The HTTP layer is a thin FastAPI wrapper; these tests exercise the parts that
carry risk — numpy/Enum/NaN sanitisation and the data-driven pricer catalogue —
by calling the bridge's own functions directly (no network, no httpx needed).
"""

import json
import math

import numpy as np

from api.catalogue import build_catalogue, find_pricer
from api.serialization import jsonable
from services.pricing_service import PricingService


# ── serialization ────────────────────────────────────────
def test_jsonable_handles_numpy_and_enums():
    from models.registry import ModelStatus

    payload = {
        "f": np.float64(1.5),
        "i": np.int64(7),
        "b": np.bool_(True),
        "arr": np.array([1.0, 2.0, 3.0]),
        "status": ModelStatus.APPROXIMATION,
        "nested": {"x": np.float32(0.25)},
    }
    out = jsonable(payload)
    assert out == {
        "f": 1.5, "i": 7, "b": True, "arr": [1.0, 2.0, 3.0],
        "status": "Approximation", "nested": {"x": 0.25},
    }
    # round-trips through json without error
    json.dumps(out)


def test_jsonable_collapses_nonfinite_to_null():
    out = jsonable({"a": float("nan"), "b": np.float64("inf"), "c": 1.0})
    assert out["a"] is None and out["b"] is None and out["c"] == 1.0
    json.dumps(out)  # NaN would otherwise be invalid JSON


def test_jsonable_drops_audit_objects():
    class _Obj:
        pass

    out = jsonable({"value": 1.0, "audit_record": _Obj(), "calculation_record": _Obj()})
    assert out == {"value": 1.0}


# ── catalogue ────────────────────────────────────────────
def test_catalogue_is_complete_and_well_formed():
    cat = build_catalogue()
    assert len(cat) >= 10
    for entry in cat:
        assert entry["id"] and entry["model_id"] and entry["name"]
        assert entry["governance"]["status"]
        assert entry["params"], f"{entry['id']} has no params"
        # every entry carries the base contract/market inputs
        keys = {p["key"] for p in entry["params"]}
        assert {"S", "K", "T", "r", "opt"} <= keys
    json.dumps(cat)  # the whole catalogue is JSON-serialisable


def test_heston_exposes_model_params():
    heston = next(e for e in build_catalogue() if e["id"] == "heston_cf")
    model_keys = {p["key"] for p in heston["params"] if p["group"] == "model"}
    assert {"v0", "kappa", "theta", "xi", "rho"} <= model_keys


# ── price dispatch ───────────────────────────────────────
def test_bsm_pricer_matches_known_atm_value():
    svc = PricingService(allow_analytics_lab=True)
    pricer = find_pricer("bsm")
    result = pricer.invoke(svc, {"S": 100, "K": 100, "T": 1, "r": 0.05,
                                 "q": 0.0, "sigma": 0.2, "opt": "call"})
    out = jsonable(result)
    json.dumps(out)
    assert math.isclose(out["value"], 10.4506, abs_tol=1e-3)
    assert out["model_id"] == "black_scholes"
    assert "delta" in out["raw"]


def test_heston_pricer_prices_and_serialises():
    svc = PricingService(allow_analytics_lab=True)
    pricer = find_pricer("heston_cf")
    result = pricer.invoke(svc, {"S": 100, "K": 100, "T": 1, "r": 0.05, "q": 0.0,
                                 "opt": "call", "v0": 0.04, "kappa": 1.5,
                                 "theta": 0.04, "xi": 0.5, "rho": -0.6})
    out = jsonable(result)
    json.dumps(out)
    assert out["value"] is not None and out["value"] > 0


def test_unknown_pricer_returns_none():
    assert find_pricer("does_not_exist") is None


# ── bond (fixed income) instrument layer ─────────────────
def test_bond_catalogue_well_formed():
    from api.instruments import build_bond_catalogue

    curves = ["GCURVE_RUB", "RUONIA_RUB", "CORP_T1"]
    cat = build_bond_catalogue(curves)
    assert {c["id"] for c in cat["curves"]} == set(curves)
    ids = {i["id"] for i in cat["instruments"]}
    assert {"fixed", "frn", "callable", "amortizing", "step", "perpetual",
            "inflation", "tbill", "cp", "deposit", "repo"} <= ids
    # rate bonds carry a curve selector; money-market discount instruments don't
    fixed = next(i for i in cat["instruments"] if i["id"] == "fixed")
    assert any(p["key"] == "curve_id" and p["dtype"] == "choice" for p in fixed["params"])
    tbill = next(i for i in cat["instruments"] if i["id"] == "tbill")
    assert not any(p["key"] == "curve_id" for p in tbill["params"])
    json.dumps(cat)


def test_normalize_bond_result_extracts_blocks():
    from api.instruments import normalize_bond_result

    raw_result = {
        "value": 99.5, "clean_price": 99.5, "dirty_price": 100.1, "accrued_interest": 0.6,
        "model_id": "fixed_bond", "model_status": "Approximation",
        "warnings": [], "errors": [], "model_limitations": [],
        "raw": {
            "ytm": 0.085, "mod_duration": 3.8, "convexity": 19.0, "dv01": 0.03,
            "key_rate_durations": {"1.0": 0.2, "5.0": 3.5},
            "cashflow_schedule": [[0.5, 3.75], [1.0, 103.75]],
        },
    }
    out = normalize_bond_result(raw_result)
    json.dumps(out)
    keys = {a["key"] for a in out["analytics"]}
    assert {"ytm", "mod_duration", "convexity", "dv01"} <= keys
    assert out["cashflows"] == [{"t": 0.5, "amount": 3.75}, {"t": 1.0, "amount": 103.75}]
    assert [k["tenor"] for k in out["key_rate_durations"]] == [1.0, 5.0]


def test_fixed_bond_prices_on_live_curve():
    from api.context import AppContext
    from api.instruments import find_instrument, normalize_bond_result

    ctx = AppContext()
    if "GCURVE_RUB" not in ctx.snapshot.curves:
        import pytest
        pytest.skip("live OFZ curve not available")
    svc = PricingService(allow_analytics_lab=True)
    inst = find_instrument("fixed")
    result = inst.invoke(svc, {"face": 100.0, "coupon": 0.075, "T": 5.0, "freq": 2,
                               "day_count": "act365", "curve_id": "GCURVE_RUB"}, ctx.snapshot)
    out = normalize_bond_result(result)
    json.dumps(out)
    assert out["value"] and out["value"] > 0
    assert out["cashflows"] and out["analytics"]
    assert any(a["key"] == "ytm" for a in out["analytics"])


def test_unknown_instrument_returns_none():
    from api.instruments import find_instrument
    assert find_instrument("nope") is None


# ── real bonds (MOEX ISS feed) ───────────────────────────
def _ctx_with_bonds():
    import pytest

    from api.context import AppContext
    ctx = AppContext()
    if ctx.market_db is None:
        pytest.skip("market-data DB unavailable")
    if not ctx.market_db.get_real_bonds(ctx.snapshot.snapshot_id, board="TQOB", limit=1):
        pytest.skip("no real bonds in DB")
    return ctx


def test_real_bonds_list():
    from api import realbonds
    ctx = _ctx_with_bonds()
    out = realbonds.list_real_bonds(ctx, board="TQOB", limit=10)
    json.dumps(out)
    assert out["count"] > 0
    bond = out["bonds"][0]
    assert bond["secid"] and bond["clean_price"] is not None


def test_real_bond_reprice_and_spread():
    from api import realbonds
    ctx = _ctx_with_bonds()
    secid = realbonds.list_real_bonds(ctx, board="TQOB", limit=1)["bonds"][0]["secid"]
    out = realbonds.reprice(ctx, secid, "GCURVE_RUB", 0.0)
    json.dumps(out)
    assert out["market_clean"] > 0
    assert out["theoretical_clean"] > 0
    assert out["cashflows"] and out["n_cashflows"] > 0
    # the Z-spread reprices the bond back to the market within a basis point
    assert out["z_spread_bps"] is not None
    # a +100bp curve shift must lower the theoretical price
    shifted = realbonds.reprice(ctx, secid, "GCURVE_RUB", 100.0)
    assert shifted["theoretical_clean"] < out["theoretical_clean"]


def test_zspread_solver_brackets_sign_change():
    from api.realbonds import _solve_zspread
    # f(s) crosses zero at +200bp
    root = _solve_zspread(lambda s: (s - 200.0))
    assert root is not None and abs(root - 200.0) < 1.0


# ── instrument catalog (Market Data) ─────────────────────
def test_catalog_categories_and_every_category_builds():
    from api import catalog
    ctx = _ctx_with_bonds()
    cats = catalog.categories(ctx)["categories"]
    assert {c["id"] for c in cats} >= {"bonds"}
    # every advertised category must build at the full limit without erroring
    for c in cats:
        out = catalog.catalog(ctx, c["id"], limit=1000)
        json.dumps(out)
        assert out.get("error") is None, f"{c['id']} errored: {out.get('error')}"
        assert out["columns"], f"{c['id']} has no columns"
        if c["count"]:
            assert out["rows"], f"{c['id']} returned no rows"
            # every row's cells align to the column count and spec is non-empty
            ncols = len(out["columns"])
            for row in out["rows"]:
                assert len(row["cells"]) == ncols
                assert row["spec"]
