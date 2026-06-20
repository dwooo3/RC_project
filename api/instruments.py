"""Fixed-income (Bond) instrument layer for the bridge.

A catalogue of interest-rate instruments (all rate bonds + money market, no
swaps/derivatives), each with its parameter specs, the curves it consumes, and
an adapter to the right `PricingService` method. Results are normalised to one
shape — price block + analytics (duration/convexity/dv01/spreads) + key-rate
durations + cashflow schedule — so the SwiftUI Bond tab renders any instrument
generically. Mirrors the option pricer catalogue (`catalogue.py`).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Callable

from domain.results import BondPricingRequest
from models import registry
from models.parameters import P, ParameterSpec

# Human labels for the live snapshot curve ids.
CURVE_LABELS = {
    "GCURVE_RUB": "OFZ sovereign (GCURVE)",
    "KEYRATE_RUB": "CBR key rate",
    "RUONIA_RUB": "RUONIA",
    "REALCURVE_OFZIN": "OFZ-IN real",
    "CORP_T1": "Corporate tier 1",
    "CORP_T2": "Corporate tier 2",
    "CORP_T3": "Corporate tier 3",
}

_DAY_COUNTS = ["act365", "act360", "30360", "actact"]
_BDC = ["following", "modified_following", "preceding", "none"]
_CCY = ["RUB", "USD", "EUR", "CNY"]


def _parse_date(value):
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_schedule(text):
    """Parse 't:amount, t:amount' into [(t, amount), ...]."""
    pairs = []
    for chunk in str(text).replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        t, amt = chunk.split(":", 1)
        try:
            pairs.append((float(t), float(amt)))
        except ValueError:
            continue
    return pairs


def _curve_kwargs(svc, b, snap):
    """Resolve the curve kwargs, applying a parallel scenario shift if requested."""
    shift = b.get("shift_bps") or 0
    if shift:
        curve = svc.market_data.get_curve(b["curve_id"], snap).parallel_shift(float(shift))
        return {"curve": curve}
    return {"curve_id": b["curve_id"]}


@dataclass
class Instrument:
    id: str
    model_id: str
    name: str
    group: str                                   # display grouping
    invoke: Callable[[object, dict, object], dict]
    base_specs: list[ParameterSpec] = field(default_factory=list)
    needs_curve: bool = True
    curve_label: str = "Discount curve"
    default_curve: str = "GCURVE_RUB"

    def specs(self, curve_ids: list[str]) -> list[ParameterSpec]:
        specs = list(self.base_specs)
        if self.needs_curve and curve_ids:
            default = self.default_curve if self.default_curve in curve_ids else curve_ids[0]
            specs.append(P("curve_id", self.curve_label, default, "market",
                           dtype="choice", choices=curve_ids,
                           help="market curve from the live snapshot"))
        return specs


# ── reusable spec blocks ─────────────────────────────────
def _face(default=100.0):
    return P("face", "Face / notional", default, "contract", minimum=0.0)


def _coupon(label="Coupon", default=0.075):
    return P("coupon", label, default, "contract", minimum=0.0, maximum=2.0,
             unit="/yr", help="annual rate, decimal (0.075 = 7.5%)")


def _maturity(default=5.0):
    return P("T", "Maturity", default, "contract", minimum=0.02, maximum=100.0, unit="y")


def _freq(default=2):
    return P("freq", "Coupon frequency", default, "contract", dtype="int",
             minimum=1, maximum=12, help="coupons per year")


def _day_count():
    return P("day_count", "Day count", "act365", "contract", dtype="choice", choices=_DAY_COUNTS)


def _shift():
    return P("shift_bps", "Curve shift", 0.0, "market", minimum=-500.0, maximum=500.0,
             unit="bp", help="parallel scenario shift on the curve")


def _settlement_specs():
    return [
        P("settlement_days", "Settlement T+", 0, "contract", dtype="int", minimum=0, maximum=10),
        P("business_day_convention", "Bus.-day conv.", "following", "contract",
          dtype="choice", choices=_BDC),
        P("currency", "Currency", "RUB", "contract", dtype="choice", choices=_CCY),
        P("valuation_date", "Valuation date", "2026-06-13", "market", dtype="date",
          help="pricing date; settlement = T+n from here"),
    ]


# ── adapters ─────────────────────────────────────────────
def _fixed(svc, b, snap):
    request = BondPricingRequest(
        face=b["face"], coupon=b["coupon"], maturity=b["T"], frequency=int(b["freq"]),
        curve_id=b["curve_id"], currency=b.get("currency", "RUB"),
        day_count=b.get("day_count", "act365"),
        business_day_convention=b.get("business_day_convention", "following"),
        settlement_days=int(b.get("settlement_days", 0)),
        valuation_date=_parse_date(b.get("valuation_date")),
    )
    shift = b.get("shift_bps") or 0
    if shift:
        curve = svc.market_data.get_curve(b["curve_id"], snap).parallel_shift(float(shift))
        return svc.price_bond(request, curve=curve, snapshot=snap)
    return svc.price_bond(request, snapshot=snap)


def _frn(svc, b, snap):
    return svc.price_frn(b["face"], b["spread"], b["T"], int(b["freq"]),
                         snapshot=snap, **_curve_kwargs(svc, b, snap))


def _callable(svc, b, snap):
    option = b.get("option", "callable")
    price = b.get("call_price")
    market = b.get("market_price") or None
    kwargs = dict(sigma=b.get("sigma", 0.15), call_start=b.get("call_start", 0.0),
                  put_start=b.get("call_start", 0.0), option=option,
                  market_price=market, snapshot=snap, **_curve_kwargs(svc, b, snap))
    if option == "putable":
        kwargs["put_price"], kwargs["call_price"] = price, None
    else:
        kwargs["call_price"], kwargs["put_price"] = price, None
    return svc.price_callable_bond(b["face"], b["coupon"], b["T"], int(b["freq"]), **kwargs)


def _amortizing(svc, b, snap):
    return svc.price_amortizing_bond(b["face"], b["coupon"], b["T"], int(b["freq"]),
                                     amort_type=b.get("amort_type", "linear"),
                                     day_count=b.get("day_count", "act365"),
                                     snapshot=snap, **_curve_kwargs(svc, b, snap))


def _step(svc, b, snap):
    return svc.price_step_bond(b["face"], b["coupon1"], b["coupon2"], b["switch_year"],
                               b["T"], int(b["freq"]), snapshot=snap, **_curve_kwargs(svc, b, snap))


def _perpetual(svc, b, snap):
    return svc.price_perpetual_bond(b["face"], b["coupon"], int(b.get("freq", 1)),
                                    snapshot=snap, **_curve_kwargs(svc, b, snap))


def _inflation(svc, b, snap):
    return svc.price_inflation_linked_bond(b["face"], b["real_coupon"], b["T"], int(b["freq"]),
                                           base_cpi=b.get("base_cpi", 100.0),
                                           current_cpi=b.get("current_cpi", 105.0),
                                           inflation_rate=b.get("inflation_rate", 0.06),
                                           snapshot=snap, **_curve_kwargs(svc, b, snap))


def _custom(svc, b, snap):
    cashflows = _parse_schedule(b.get("cashflows", ""))
    if not cashflows:
        raise ValueError("Provide cashflows as 't:amount, t:amount'")
    return svc.price_custom_bond(cashflows, freq=int(b.get("freq", 2)),
                                 snapshot=snap, **_curve_kwargs(svc, b, snap))


def _tbill(svc, b, snap):
    return svc.price_treasury_bill(b["face"], b["discount_rate"], b["T"], snapshot=snap)


def _cp(svc, b, snap):
    return svc.price_commercial_paper(b["face"], b["discount_rate"], b["T"], snapshot=snap)


def _deposit(svc, b, snap):
    return svc.price_deposit(b["notional"], b["rate"], b["T"], snapshot=snap, **_curve_kwargs(svc, b, snap))


def _repo(svc, b, snap):
    return svc.price_repo(b["spot"], b["repo_rate"], b["T"],
                          coupon_income=b.get("coupon_income", 0.0),
                          direction=b.get("direction", "repo"), snapshot=snap)


def _mbs(svc, b, snap):
    disc = b.get("disc_rate") or None
    return svc.price_mbs(b["balance"], b["wac"], b["net_coupon"], int(b["wam_months"]),
                         psa=b.get("psa", 100.0), disc_rate=disc, oas=b.get("oas", 0.0),
                         snapshot=snap)


# ── catalogue ────────────────────────────────────────────
INSTRUMENTS: list[Instrument] = [
    Instrument("ofz", "fixed_bond", "ОФЗ (sovereign)", "Sovereign", _fixed,
               base_specs=[_face(), _coupon("Coupon", 0.07), _maturity(7.0), _freq(),
                           P("day_count", "Day count", "actact", "contract",
                             dtype="choice", choices=_DAY_COUNTS),
                           *_settlement_specs(), _shift()],
               default_curve="GCURVE_RUB"),
    Instrument("fixed", "fixed_bond", "Fixed-rate bond", "Fixed coupon", _fixed,
               base_specs=[_face(), _coupon(), _maturity(), _freq(), _day_count(),
                           *_settlement_specs(), _shift()]),
    Instrument("step", "step_bond", "Step-up / step-down", "Fixed coupon", _step,
               base_specs=[_face(),
                           P("coupon1", "Coupon 1", 0.06, "contract", minimum=0.0, maximum=2.0, unit="/yr"),
                           P("coupon2", "Coupon 2", 0.09, "contract", minimum=0.0, maximum=2.0, unit="/yr"),
                           P("switch_year", "Switch year", 3.0, "contract", minimum=0.5, unit="y"),
                           _maturity(), _freq(), _shift()]),
    Instrument("amortizing", "amortizing_bond", "Amortizing bond", "Fixed coupon", _amortizing,
               base_specs=[_face(), _coupon(), _maturity(), _freq(),
                           P("amort_type", "Amortization", "linear", "contract",
                             dtype="choice", choices=["linear", "annuity"]), _day_count(), _shift()]),
    Instrument("perpetual", "perpetual_bond", "Perpetual bond", "Fixed coupon", _perpetual,
               base_specs=[_face(), _coupon(), _freq(1), _shift()]),
    Instrument("custom", "custom_bond", "Custom cashflows", "Custom", _custom,
               base_specs=[P("cashflows", "Cashflows (t:amount)", "0.5:3.75, 1.0:3.75, 1.5:103.75",
                             "contract", dtype="schedule", help="comma-separated time:amount in years"),
                           _freq(), _shift()]),
    Instrument("frn", "frn", "Floating-rate note", "Floating", _frn,
               base_specs=[_face(),
                           P("spread", "Spread", 0.012, "contract", minimum=-0.1, maximum=0.5,
                             unit="/yr", help="spread over the forecast curve"),
                           _maturity(), _freq(4), _shift()],
               curve_label="Forecast curve", default_curve="RUONIA_RUB"),
    Instrument("inflation", "inflation_linked_bond", "Inflation-linked bond", "Floating", _inflation,
               base_specs=[_face(),
                           P("real_coupon", "Real coupon", 0.025, "contract", minimum=0.0, maximum=2.0, unit="/yr"),
                           _maturity(), _freq(),
                           P("base_cpi", "Base CPI", 100.0, "market", minimum=1.0),
                           P("current_cpi", "Current CPI", 105.0, "market", minimum=1.0),
                           P("inflation_rate", "Inflation rate", 0.06, "market",
                             minimum=-0.1, maximum=1.0, unit="/yr"), _shift()],
               default_curve="REALCURVE_OFZIN"),
    Instrument("callable", "callable_bond", "Callable / putable bond", "Embedded option", _callable,
               base_specs=[_face(), _coupon(), _maturity(), _freq(),
                           P("option", "Option", "callable", "contract",
                             dtype="choice", choices=["callable", "putable"]),
                           P("call_price", "Call / put price", 100.0, "contract", minimum=0.0),
                           P("call_start", "Exercise from", 1.0, "contract", minimum=0.0, unit="y"),
                           P("sigma", "Rate vol σ", 0.15, "model", minimum=1e-3, maximum=1.0),
                           P("market_price", "Market price → OAS", 0.0, "model", minimum=0.0,
                             help="0 = use straight value; >0 solves OAS to this price"),
                           _shift()]),
    Instrument("tbill", "treasury_bill", "Treasury bill (OFZ-discount)", "Money market", _tbill,
               base_specs=[_face(1000.0),
                           P("discount_rate", "Discount rate", 0.14, "market", minimum=0.0, maximum=1.0, unit="/yr"),
                           _maturity(0.25)], needs_curve=False),
    Instrument("cp", "commercial_paper", "Commercial paper", "Money market", _cp,
               base_specs=[_face(1000.0),
                           P("discount_rate", "Discount rate", 0.16, "market", minimum=0.0, maximum=1.0, unit="/yr"),
                           _maturity(0.25)], needs_curve=False),
    Instrument("deposit", "mm_deposit", "Money-market deposit", "Money market", _deposit,
               base_specs=[P("notional", "Notional", 1_000_000.0, "contract", minimum=0.0),
                           P("rate", "Deposit rate", 0.15, "market", minimum=0.0, maximum=1.0, unit="/yr"),
                           _maturity(0.25)]),
    Instrument("repo", "repo", "Repo / reverse repo", "Money market", _repo,
               base_specs=[P("spot", "Collateral price", 100.0, "contract", minimum=0.0),
                           P("repo_rate", "Repo rate", 0.15, "market", minimum=0.0, maximum=1.0, unit="/yr"),
                           _maturity(0.08),
                           P("direction", "Direction", "repo", "contract",
                             dtype="choice", choices=["repo", "reverse"]),
                           P("coupon_income", "Coupon income", 0.0, "contract", minimum=0.0)],
               needs_curve=False),
    Instrument("mbs", "mbs", "MBS pass-through", "Securitized", _mbs,
               base_specs=[P("balance", "Pool balance", 1_000_000.0, "contract", minimum=0.0),
                           P("wac", "WAC", 0.09, "contract", minimum=0.0, maximum=1.0, unit="/yr",
                             help="weighted-average coupon"),
                           P("net_coupon", "Net coupon", 0.085, "contract", minimum=0.0, maximum=1.0, unit="/yr"),
                           P("wam_months", "WAM", 360, "contract", dtype="int", minimum=1, maximum=600, unit="mo"),
                           P("psa", "PSA speed", 100.0, "model", minimum=0.0, maximum=1000.0, unit="%",
                             help="PSA prepayment speed"),
                           P("oas", "OAS", 0.0, "model", minimum=-0.1, maximum=0.1, unit="/yr"),
                           P("disc_rate", "Discount rate", 0.12, "market", minimum=0.0, maximum=1.0, unit="/yr")],
               needs_curve=False),
]

_BY_ID = {i.id: i for i in INSTRUMENTS}

_ANALYTIC_KEYS = [
    ("ytm", "Yield to maturity"), ("ytw", "Yield to worst"), ("ytc", "Yield to call"),
    ("ytp", "Yield to put"), ("zspread", "Z-spread"), ("g_spread", "G-spread"),
    ("i_spread", "I-spread"), ("mac_duration", "Macaulay duration"),
    ("mod_duration", "Modified duration"), ("effective_duration", "Effective duration"),
    ("convexity", "Convexity"), ("effective_convexity", "Effective convexity"),
    ("dv01", "DV01"), ("pv01", "PV01"), ("bpv", "BPV"),
    ("oas", "Option-adjusted spread"), ("option_value", "Option value"),
    ("straight_value", "Straight value"),
    ("wal", "Weighted-average life"), ("price_pct", "Price (% of par)"),
]


def find_instrument(instrument_id: str) -> Instrument | None:
    return _BY_ID.get(instrument_id)


def _spec_dict(s: ParameterSpec) -> dict:
    return {"key": s.key, "label": s.label, "default": s.default, "group": s.group,
            "dtype": s.dtype, "choices": s.choices, "minimum": s.minimum, "maximum": s.maximum,
            "advanced": s.advanced, "unit": s.unit, "help": s.help}


def _governance(model_id: str) -> dict:
    e = registry.get(model_id)
    status = e.get("status")
    return {"status": status.value if hasattr(status, "value") else str(status),
            "asset_class": e.get("asset_class", "rates"),
            "method": e.get("method", ""), "notes": e.get("notes", "")}


def build_bond_catalogue(curve_ids: list[str]) -> dict:
    curves = [{"id": c, "label": CURVE_LABELS.get(c, c)} for c in curve_ids]
    instruments = [
        {"id": i.id, "model_id": i.model_id, "name": i.name, "group": i.group,
         "needs_curve": i.needs_curve, "governance": _governance(i.model_id),
         "params": [_spec_dict(s) for s in i.specs(curve_ids)]}
        for i in INSTRUMENTS
    ]
    return {"curves": curves, "instruments": instruments,
            "analytic_labels": dict(_ANALYTIC_KEYS)}


def price_batch(svc, snapshot, rows: list) -> dict:
    """Price a list of {instrument, params, quantity} rows + portfolio aggregate."""
    results = []
    for row in rows:
        inst = find_instrument(row.get("instrument"))
        qty = float(row.get("quantity", 1) or 1)
        if inst is None:
            results.append({"instrument": row.get("instrument"), "name": "?",
                            "quantity": qty, "error": "unknown instrument",
                            "value": None, "analytics": [], "key_rate_durations": [], "cashflows": []})
            continue
        try:
            norm = normalize_bond_result(inst.invoke(svc, row.get("params", {}), snapshot))
        except Exception as exc:
            norm = {"value": None, "analytics": [], "key_rate_durations": [], "cashflows": [],
                    "errors": [str(exc)], "model_status": "", "model_id": inst.model_id}
        norm.update(instrument=inst.id, name=inst.name, quantity=qty,
                    error=(norm.get("errors") or [None])[0])
        results.append(norm)
    return {"results": results, "aggregate": _aggregate(results)}


def _aggregate(results: list) -> dict:
    mv = dv01 = w_dur = w_cvx = 0.0
    krd: dict[float, float] = {}
    count = 0
    for r in results:
        if r.get("value") is None:
            continue
        qty = float(r.get("quantity", 1))
        value = float(r["value"]) * qty
        mv += value
        count += 1
        analytics = {a["key"]: a["value"] for a in r.get("analytics", [])}
        if "mod_duration" in analytics:
            w_dur += value * analytics["mod_duration"]
        if "convexity" in analytics:
            w_cvx += value * analytics["convexity"]
        if "dv01" in analytics:
            dv01 += analytics["dv01"] * qty
        for k in r.get("key_rate_durations", []):
            krd[k["tenor"]] = krd.get(k["tenor"], 0.0) + k["value"] * qty
    return {
        "count": count,
        "market_value": mv,
        "dv01": dv01,
        "mod_duration": (w_dur / mv if mv else 0.0),
        "convexity": (w_cvx / mv if mv else 0.0),
        "key_rate_durations": [{"tenor": t, "value": v} for t, v in sorted(krd.items())],
    }


def _cf_pair(item):
    """Coerce one schedule entry into (t, amount) or None."""
    if isinstance(item, dict):
        t = item.get("time", item.get("t"))
        amt = item.get("cash_flow", item.get("amount", item.get("cashflow", item.get("cf"))))
        if t is not None and amt is not None:
            return float(t), float(amt)
    elif isinstance(item, (list, tuple)) and len(item) >= 2:
        return float(item[0]), float(item[1])
    return None


def _extract_cashflows(raw: dict) -> list:
    """Bond engines return either rich dict schedules (date-based) or (t, amount)
    tuples; prefer the schedule, fall back to the tuple list."""
    for key in ("cashflow_schedule", "cash_flows"):
        out = [{"t": p[0], "amount": p[1]} for p in
               (_cf_pair(i) for i in (raw.get(key) or [])) if p is not None]
        if out:
            return out
    return []


def normalize_bond_result(result: dict) -> dict:
    """Flatten a PricingService bond result into the bridge's bond shape."""
    raw = result.get("raw") or {}

    analytics = []
    for key, label in _ANALYTIC_KEYS:
        v = raw.get(key)
        if v is not None:
            analytics.append({"key": key, "label": label, "value": v})

    cashflows = _extract_cashflows(raw)

    krd = []
    for tenor, value in (raw.get("key_rate_durations") or {}).items():
        try:
            krd.append({"tenor": float(tenor), "value": value})
        except (TypeError, ValueError):
            continue
    krd.sort(key=lambda x: x["tenor"])

    return {
        "value": result.get("value"),
        "clean_price": result.get("clean_price", raw.get("clean_price")),
        "dirty_price": result.get("dirty_price", raw.get("dirty_price")),
        "accrued_interest": result.get("accrued_interest", raw.get("accrued_interest")),
        "analytics": analytics,
        "key_rate_durations": krd,
        "cashflows": cashflows,
        "model_id": result.get("model_id"),
        "model_status": result.get("model_status"),
        "model_limitations": result.get("model_limitations", []),
        "warnings": result.get("warnings", []),
        "errors": result.get("errors", []),
    }
