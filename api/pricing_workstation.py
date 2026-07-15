"""Universal pricing-workstation catalogue for the bridge.

Every pricer in the model library becomes visible here: one `WsProduct` per
instrument (grouped by asset class), each carrying its full parameter specs
(contract / market / model / numerical) and a list of selectable engines from
`models.taxonomy.ENGINES`. The Swift client renders the whole thing generically
— adding a product or an engine is a table edit here, no client change.

Market-data hooks per product:
    * curve params  — snapshot curve ids injected as choices (+ flat-r sentinel
      and a parallel `shift_bps` scenario input);
    * vol surfaces  — calibrated SABR surface ids as a σ source;
    * underlying    — a market-data instrument picker with an autofill map
      (spot / vol / dividend yield / expiry pulled from the live store via
      /pricing/underlying).

Mirrors api/catalogue.py (vanilla) and api/instruments.py (bonds) but covers
the entire ENGINES matrix: rates, credit, FX, commodity, inflation, equity
exotics, multi-asset and structured products.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
from typing import Callable

from api.instruments import CURVE_LABELS
from models import registry
from models.engine_eligibility import (
    approval_is_active,
    build_engine_eligibility,
    effective_production_allowed,
    eligibility_policy_issues,
)
from models.parameters import P, ParameterSpec, engine_params

FLAT_CURVE = "— флэт r —"
PROJ_AS_DISC = "— как discount —"
MANUAL_VOL = "— вручную σ —"

ASSET_CLASSES = [
    ("equity", "Equity / Options"),
    ("rates", "Rates"),
    ("fx", "FX"),
    ("credit", "Credit"),
    ("commodity", "Commodity"),
    ("inflation", "Inflation"),
    ("hybrid", "Multi-asset & Structured"),
]

_OPT = ["call", "put"]


# ── parsing helpers (schedule / list / matrix text inputs) ───────────
def _floats(text) -> list[float]:
    """'1, 2, 3' -> [1.0, 2.0, 3.0]."""
    if isinstance(text, (list, tuple)):
        return [float(x) for x in text]
    return [float(x) for x in str(text).replace(";", ",").split(",") if x.strip()]


def _component_secids(text) -> list[str]:
    """Parse a component identity schedule, accepting ``SECID:weight`` too."""
    if text in (None, "", []):
        return []
    values = text if isinstance(text, (list, tuple)) else str(text).replace(";", ",").split(",")
    out = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("secid") or value.get("id") or ""
        secid = str(value).strip().split(":", 1)[0].strip()
        if secid:
            out.append(secid)
    return out


def _pairs(text) -> list[tuple[float, float]]:
    """'t:amount, t:amount' -> [(t, amount), ...]."""
    if isinstance(text, (list, tuple)):
        return [(float(t), float(a)) for t, a in text]
    out = []
    for part in str(text).replace(";", ",").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        t, a = part.split(":", 1)
        out.append((float(t), float(a)))
    return out


def _corr_matrix(rho: float, n: int) -> list[list[float]]:
    return [[1.0 if i == j else float(rho) for j in range(n)] for i in range(n)]


_INDEX_IDS = {"IMOEX", "RTSI", "RGBI", "RUCBTRNS", "RVI", "MOEX"}


def _infer_kind(secid: str) -> str:
    s = secid.upper()
    if s in _INDEX_IDS:
        return "index"
    if s.startswith("SU") or s.startswith("RU000"):
        return "bond"
    return "equity"


def _parse_basket(text) -> list[dict]:
    """'SBER:0.4, GAZP:0.3' -> [{secid, kind, weight}] (kind inferred)."""
    if isinstance(text, (list, tuple)):
        return [dict(s) for s in text]
    specs = []
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        parts = [p.strip() for p in token.split(":")]
        if not parts[0]:
            continue
        weight = float(parts[1]) if len(parts) > 1 and parts[1] else 1.0
        kind = parts[2] if len(parts) > 2 and parts[2] else _infer_kind(parts[0])
        specs.append({"secid": parts[0], "kind": kind, "weight": weight})
    return specs


# ── curve resolution (flat sentinel / snapshot curve / parallel shift) ──
def _curve(svc, v, snapshot, key="curve_id", rate_key="r", shift_key="shift_bps"):
    cid = v.get(key)
    if not cid or cid == FLAT_CURVE:
        curve = svc.market_data.flat_curve(float(v.get(rate_key, 0.10)))
    else:
        curve = svc.market_data.get_curve(cid, snapshot)
    shift = float(v.get(shift_key) or 0.0)
    return curve.parallel_shift(shift) if shift else curve


def _proj(svc, v, snapshot):
    cid = v.get("proj_curve_id")
    if not cid or cid == PROJ_AS_DISC:
        return None
    return svc.market_data.get_curve(cid, snapshot)


def _num(v, key, default=0.0):
    x = v.get(key, default)
    return default if x in (None, "") else float(x)


# ── product / engine descriptors ─────────────────────────────────────
@dataclass
class Engine:
    id: str                                   # selector id sent back in /pricing/price
    model_id: str                             # registry id for governance
    name: str
    params: list[ParameterSpec] = field(default_factory=list)


def E(engine_id: str, name: str | None = None, model_id: str | None = None,
      params: list[ParameterSpec] | None = None) -> Engine:
    mid = model_id or engine_id
    display = name or registry.get(mid).get("name", engine_id)
    return Engine(engine_id, mid, display,
                  params if params is not None else engine_params(mid))


@dataclass
class WsProduct:
    id: str
    name: str
    asset_class: str
    group: str
    base_params: list[ParameterSpec]
    engines: list[Engine]
    invoke: Callable                         # (svc, values, snapshot) -> governed dict
    underlying: dict | None = None           # {"categories": [...], "fill": {param: fact}}
    needs_curve: bool = False
    curve_label: str = "Discount curve"
    default_curve: str = "GCURVE_RUB"
    needs_proj: bool = False
    vol_surfaces: bool = False               # inject vol_surface_id choices
    note: str = ""

    def curve_specs(self, curve_ids: list[str]) -> list[ParameterSpec]:
        specs: list[ParameterSpec] = []
        if self.needs_curve:
            choices = [FLAT_CURVE] + list(curve_ids)
            default = self.default_curve if self.default_curve in curve_ids else FLAT_CURVE
            specs.append(P("curve_id", self.curve_label, default, "market",
                           dtype="choice", choices=choices,
                           help="снапшот-кривая или флэт из поля r"))
            specs.append(P("shift_bps", "Curve shift (bp)", 0.0, "market",
                           minimum=-1000, maximum=1000,
                           help="параллельный сдвиг кривой — сценарий"))
        if self.needs_proj:
            specs.append(P("proj_curve_id", "Projection curve", PROJ_AS_DISC, "market",
                           dtype="choice", choices=[PROJ_AS_DISC] + list(curve_ids),
                           help="кривая проекции форвардов (dual-curve)"))
        return specs

    def params_for(self, engine: Engine, curve_ids: list[str],
                   surface_ids: list[str]) -> list[ParameterSpec]:
        specs = list(self.base_params) + self.curve_specs(curve_ids)
        if self.vol_surfaces and surface_ids:
            specs.append(P("vol_surface_id", "Vol surface", MANUAL_VOL, "market",
                           dtype="choice", choices=[MANUAL_VOL] + list(surface_ids),
                           help="источник σ — калиброванный SABR-смайл; "
                                f"'{MANUAL_VOL}' = поле σ"))
        specs += list(engine.params)
        # engine params override same-key base params (e.g. the Black vol field
        # is meaningless once a short-rate engine defines its own sigma)
        by_key: dict[str, ParameterSpec] = {}
        for s in specs:
            by_key[s.key] = s
        return list(by_key.values())


# ── reusable spec blocks ─────────────────────────────────────────────
def _spot(label="Spot S", default=100.0):
    return P("S", label, default, "market", minimum=0.0)


def _strike(default=100.0):
    return P("K", "Strike K", default, "contract", minimum=0.0)


def _mat(default=1.0, label="Maturity T"):
    return P("T", label, default, "contract", minimum=1e-4, maximum=100.0, unit="y",
             help="в годах, ACT/365 (T = дни/365)")


def _rate(key="r", label="Rate r", default=0.10):
    return P(key, label, default, "market", minimum=-1.0, maximum=2.0,
             help="непрерывное начисление")


def _sigma(default=0.20, label="Volatility σ"):
    return P("sigma", label, default, "market", minimum=1e-4, maximum=5.0)


def _div():
    return P("q", "Dividend yield q", 0.0, "market", minimum=-1.0, maximum=1.0)


def _optype(default="call", choices=None):
    return P("opt", "Option type", default, "contract",
             dtype="choice", choices=choices or _OPT)


def _notional(default=1_000_000.0, label="Notional"):
    return P("notional", label, default, "contract", minimum=0.0)


def _freq(default=2):
    return P("freq", "Frequency /y", default, "contract", dtype="int",
             minimum=1, maximum=12)


_EQ_UNDERLYING = {
    "categories": ["equities", "indices", "futures", "commodities"],
    "fill": {"S": "spot", "sigma": "vol", "q": "div_yield"},
}
_FX_UNDERLYING = {
    "categories": ["fx", "futures"],
    "fill": {"S": "spot", "sigma": "vol", "T": "expiry_T"},
}


# ── engine dispatchers ───────────────────────────────────────────────
def _european(svc, v, snapshot):
    eng = v.get("engine", "black_scholes")
    S, K, T, r = _num(v, "S", 100), _num(v, "K", 100), _num(v, "T", 1), _num(v, "r", 0.05)
    sig, q, opt = _num(v, "sigma", 0.2), _num(v, "q", 0.0), v.get("opt", "call")
    analytic = {"black_scholes": "bsm", "black76": "black76", "bachelier": "bachelier",
                "garman_kohlhagen": "gk", "binomial_crr": "binomial",
                "binomial_lr": "binomial_lr", "trinomial": "trinomial",
                "pde_cn": "pde", "mc_gbm": "mc"}
    if eng in analytic:
        surf = v.get("vol_surface_id")
        use_surface = bool(surf) and surf != MANUAL_VOL

        def _opt_int(key):
            val = v.get(key)
            return int(val) if isinstance(val, (int, float)) else None

        return svc.price_vanilla_option(
            S, K, T, r, None if use_surface else sig, q, opt, model=analytic[eng],
            snapshot=snapshot, vol_surface_id=surf if use_surface else None,
            n=_opt_int("N"), n_sims=_opt_int("n_sims"),
            steps=_opt_int("steps"), seed=_opt_int("seed"),
            ns=_opt_int("Ns"), nt=_opt_int("Nt"))
    if eng == "heston_cf":
        return svc.price_heston_option(S, K, T, r, q, _num(v, "v0", .04), _num(v, "kappa", 1.5),
                                       _num(v, "theta", .04), _num(v, "xi", .5),
                                       _num(v, "rho", -.6), opt, snapshot=snapshot)
    if eng in {"mc_heston", "mc_heston_qe"}:
        return svc.price_heston_mc_option(
            S, K, T, r, q, _num(v, "v0", .04), _num(v, "kappa", 1.5),
            _num(v, "theta", .04), _num(v, "xi", .5), _num(v, "rho", -.6),
            opt, "qe" if eng == "mc_heston_qe" else "euler",
            int(_num(v, "n_sims", 100000)), int(_num(v, "steps", 100)),
            int(_num(v, "seed", 42)), snapshot=snapshot,
        )
    if eng == "bates":
        return svc.price_bates_option(S, K, T, r, q, _num(v, "v0", .04), _num(v, "kappa", 1.5),
                                      _num(v, "theta", .04), _num(v, "xi", .5), _num(v, "rho", -.6),
                                      _num(v, "lam", .3), _num(v, "mu_j", -.1),
                                      _num(v, "delta_j", .15), opt, snapshot=snapshot)
    if eng == "merton_jump":
        return svc.price_merton_option(S, K, T, r, sig, q, _num(v, "lam", .3),
                                       _num(v, "mu_j", -.1), _num(v, "delta_j", .15),
                                       opt, snapshot=snapshot)
    if eng in ("merton_cos", "kou", "variance_gamma", "nig", "cgmy"):
        keys = ("lam", "p", "eta1", "eta2", "nu", "theta", "alpha", "beta",
                "delta", "mu_j", "delta_j", "C", "G", "M", "Y", "N")
        params = {k: v[k] for k in keys if k in v and v[k] is not None}
        if "N" in params:
            params["N"] = int(params["N"])
        return svc.price_levy_option(eng, S, K, T, r, sig, q, opt,
                                     snapshot=snapshot, **params)
    if eng == "rough_bergomi":
        return svc.price_rough_bergomi_option(S, K, T, r, q, _num(v, "H", .1),
                                              _num(v, "eta", 1.5), _num(v, "rho", -.7),
                                              _num(v, "xi0", .04), opt,
                                              int(_num(v, "n_paths", 40000)),
                                              int(_num(v, "steps", 100)), snapshot=snapshot)
    if eng == "qmc":
        return svc.price_qmc_option(S, K, T, r, sig, q, opt, "european",
                                    int(_num(v, "n", 16384)), snapshot=snapshot)
    if eng == "carr_madan":
        model = v.get("cf_model", "bsm")
        kw = {}
        if model == "heston":
            kw = {"v0": _num(v, "v0", .04), "kappa": _num(v, "kappa", 1.5),
                  "theta": _num(v, "theta", .04), "xi": _num(v, "xi", .3),
                  "rho": _num(v, "rho", -.6)}
        return svc.price_carr_madan(model, S, K, T, r, sig, q, opt,
                                    snapshot=snapshot, **kw)
    if eng == "heston_adi":
        return svc.price_heston_adi(S, K, T, r, q, _num(v, "v0", .04), _num(v, "kappa", 1.5),
                                    _num(v, "theta", .04), _num(v, "xi", .3), _num(v, "rho", -.6),
                                    opt, int(_num(v, "NS", 160)), int(_num(v, "Nv", 80)),
                                    int(_num(v, "Nt", 120)), snapshot=snapshot)
    if eng in ("cev", "displaced_diffusion", "discrete_div_bsm",
               "lognormal_mixture", "binomial_jr", "binomial_tian"):
        kw = {}
        if eng == "cev":
            kw["beta"] = _num(v, "beta", 1.0)
        elif eng == "displaced_diffusion":
            kw["shift"] = _num(v, "shift", 0.0)
        elif eng == "discrete_div_bsm":
            kw["dividends"] = _pairs(v.get("dividends", ""))
        elif eng == "lognormal_mixture":
            kw["sigma_list"] = _floats(v.get("sigma_list", str(sig)))
            kw["weights"] = _floats(v.get("weights", "1"))
        else:
            kw["N"] = int(_num(v, "N", 500))
        return svc.price_vanilla_extra(eng, S, K, T, r, sig, q, opt,
                                       snapshot=snapshot, **kw)
    return svc.price_vanilla_option(S, K, T, r, sig, q, opt, model="bsm",
                                    snapshot=snapshot)


_AMERICAN_ARG = {"pde_cn": "pde", "binomial_crr": "binomial", "binomial_lr": "binomial_lr",
                 "trinomial": "trinomial", "mc_lsm": "lsm", "baw": "baw",
                 "bjerksund_stensland": "bjerksund_stensland"}


def _american(svc, v, snapshot):
    model = _AMERICAN_ARG.get(v.get("engine", "pde_cn"), "pde")
    return svc.price_american_option(_num(v, "S", 100), _num(v, "K", 100), _num(v, "T", 1),
                                     _num(v, "r", .05), _num(v, "sigma", .2), _num(v, "q", 0),
                                     v.get("opt", "put"), model, snapshot=snapshot)


def _barrier(svc, v, snapshot):
    args = (_num(v, "S", 100), _num(v, "K", 100), _num(v, "H", 90), _num(v, "T", 1),
            _num(v, "r", .05), _num(v, "sigma", .2), _num(v, "q", 0),
            v.get("opt", "call"), v.get("barrier_type", "down-out"))
    if v.get("engine") == "pde_cn":
        return svc.price_barrier_option_pde(
            *args, ns=int(_num(v, "Ns", 400)), nt=int(_num(v, "Nt", 400)),
            snapshot=snapshot)
    return svc.price_barrier_option(*args, _num(v, "rebate", 0.0), snapshot=snapshot)


def _swaption(svc, v, snapshot):
    eng = v.get("engine", "swaption")
    N, K = _num(v, "notional", 1e6), _num(v, "K", 0.10)
    To, Ts = _num(v, "T_option", 1), _num(v, "T_swap", 5)
    freq, opt = int(_num(v, "freq", 2)), v.get("opt", "payer")
    curve = _curve(svc, v, snapshot)
    if eng == "g2pp":
        return svc.price_g2pp_swaption(N, K, To, Ts, freq, _num(v, "a", .1),
                                       _num(v, "sigma", .01), _num(v, "b", .3),
                                       _num(v, "eta", .012), _num(v, "rho", -.7), opt,
                                       int(_num(v, "n_sims", 50000)), curve=curve,
                                       snapshot=snapshot, method=v.get("method", "analytic"))
    if eng == "lmm":
        return svc.price_lmm_swaption(N, K, To, Ts, freq, _num(v, "vol", .2),
                                      _num(v, "corr_beta", .1), opt,
                                      int(_num(v, "n_sims", 50000)), int(_num(v, "steps", 24)),
                                      curve=curve, snapshot=snapshot)
    if eng == "bk":
        return svc.price_bk_swaption(N, K, To, Ts, freq, _num(v, "a", .1),
                                     _num(v, "sigma", .2), opt,
                                     int(_num(v, "steps_per_year", 24)),
                                     curve=curve, snapshot=snapshot)
    if eng == "cheyette":
        return svc.price_cheyette_swaption(N, K, To, Ts, freq, _num(v, "a", .1),
                                           _num(v, "sigma", .01), _num(v, "skew", 0), opt,
                                           int(_num(v, "n_sims", 50000)),
                                           int(_num(v, "steps", 100)),
                                           curve=curve, snapshot=snapshot)
    if eng == "swap_market_model":
        return svc.price_smm_swaption(N, K, To, Ts, freq, _num(v, "sigma", .2),
                                      _num(v, "shift", 0.0), opt,
                                      curve=curve, snapshot=snapshot)
    return svc.price_swaption(N, K, To, Ts, freq, _num(v, "sigma", .2), opt,
                              curve=curve, snapshot=snapshot)


def _bermudan(svc, v, snapshot):
    N, K = _num(v, "notional", 1e6), _num(v, "K", 0.10)
    dates = _floats(v.get("ex_dates", "1,2,3"))
    T_end, freq = _num(v, "T_end", 6), int(_num(v, "freq", 2))
    opt, curve = v.get("opt", "payer"), _curve(svc, v, snapshot)
    if v.get("engine") == "amc":
        return svc.price_amc_bermudan_swaption(N, K, dates, T_end, freq,
                                               _num(v, "kappa", .1), _num(v, "sigma_r", .012),
                                               opt, int(_num(v, "n_sims", 20000)),
                                               curve=curve, snapshot=snapshot)
    return svc.price_bermudan_swaption(N, K, dates, T_end, freq, _num(v, "kappa", .1),
                                       _num(v, "sigma", .012), opt,
                                       int(_num(v, "steps", 200)), curve=curve,
                                       snapshot=snapshot,
                                       calibrate_to_cube=v.get("calibrate_to_cube") == "yes")


def _capfloor(svc, v, snapshot):
    N, K, T = _num(v, "notional", 1e6), _num(v, "K", .1), _num(v, "T", 3)
    freq, opt = int(_num(v, "freq", 2)), v.get("opt", "cap")
    curve = _curve(svc, v, snapshot)
    if v.get("engine") == "lmm":
        return svc.price_lmm_cap(N, K, T, freq, _num(v, "vol", .2), opt,
                                 curve=curve, snapshot=snapshot)
    return svc.price_cap_floor(N, K, T, freq, _num(v, "vol", .2), opt, curve=curve,
                               proj_curve=_proj(svc, v, snapshot), snapshot=snapshot)


def _issuer_hazard(issuer: str):
    """Issuer hazard curve from real bond z-spreads (lazy: bridge context only).
    Returns (curve, meta) or (None, None) when the issuer field is empty."""
    issuer = (issuer or "").strip()
    if not issuer:
        return None, None
    from api.context import CONTEXT
    from api.credit import issuer_hazard_curve
    return issuer_hazard_curve(CONTEXT, issuer)


def _hazard_note(meta: dict) -> str:
    rating = meta.get("rating") or {}
    return (f"hazard из z-спредов: {meta['issuer']} · "
            f"{rating.get('rating', 'без рейтинга')}"
            f"{' (' + rating['agency'] + ')' if rating.get('agency') else ''} · "
            f"R={meta['recovery']:.0%} ({meta['recovery_source']}) · "
            f"{len(meta['bonds'])} бумаг")


def _with_note(result: dict, note: str | None) -> dict:
    if note and isinstance(result, dict):
        result["warnings"] = list(result.get("warnings") or []) + [note]
    return result


def _cds(svc, v, snapshot):
    eng = v.get("engine", "cds")
    N, sp, T = _num(v, "notional", 1e6), _num(v, "spread", .01), _num(v, "T", 5)
    freq = int(_num(v, "freq", 4))
    hazard_curve, meta = _issuer_hazard(v.get("issuer", ""))
    if hazard_curve is not None or eng == "cds_curve":
        res = svc.price_cds_curve(N, sp, T, freq,
                                  hazard_curve=hazard_curve,
                                  hazard_id=v.get("hazard_id", "hazard_1t_demo"),
                                  curve_id=_credit_disc_id(snapshot),
                                  recovery=(meta["recovery"] if meta
                                            else _num(v, "recovery", .4)),
                                  snapshot=snapshot)
        return _with_note(res, _hazard_note(meta) if meta else None)
    if eng == "cds_isda":
        return svc.price_isda_cds(N, _num(v, "coupon", .01), sp, T, freq,
                                  _num(v, "r", .05), _num(v, "recovery", .4),
                                  snapshot=snapshot)
    return svc.price_cds(N, sp, T, freq, _num(v, "hazard", .02), _num(v, "r", .05),
                         _num(v, "recovery", .4), snapshot=snapshot)


def _risky_bond(svc, v, snapshot):
    hazard_curve, meta = _issuer_hazard(v.get("issuer", ""))
    res = svc.price_risky_bond(
        _num(v, "face", 1000), _num(v, "coupon", .13), _num(v, "T", 5),
        int(_num(v, "freq", 2)), hazard_curve=hazard_curve,
        hazard_id=v.get("hazard_id", "hazard_1t_demo"),
        curve_id=_credit_disc_id(snapshot),
        recovery=(meta["recovery"] if meta else _num(v, "recovery", .4)),
        snapshot=snapshot)
    return _with_note(res, _hazard_note(meta) if meta else None)


def _credit_disc_id(snapshot) -> str:
    """Live snapshots carry GCURVE_RUB, the demo one carries ofz_demo."""
    curves = getattr(snapshot, "curves", None) or {}
    return "GCURVE_RUB" if "GCURVE_RUB" in curves else "ofz_demo"


def _structural(svc, v, snapshot):
    return svc.price_structural_credit(
        v.get("engine", "merton_structural"), _num(v, "V0", 100), _num(v, "D", 70),
        _num(v, "T", 1), _num(v, "r", .05), _num(v, "sigma_V", .25),
        barrier=(_num(v, "barrier", 0) or None), snapshot=snapshot)


def _basket_default(svc, v, snapshot):
    eng = v.get("engine", "gaussian_copula")
    pds = _floats(v.get("pds", "0.02,0.03,0.04,0.02,0.05"))
    k, rec = int(_num(v, "k", 1)), _num(v, "recovery", .4)
    rho = _num(v, "rho", .3)
    if eng in ("t_copula", "clayton_copula"):
        return svc.price_basket_copula(
            "t" if eng == "t_copula" else "clayton", pds, k, rec, rho,
            int(_num(v, "df", 5)), _num(v, "theta", 1.0),
            int(_num(v, "n_sims", 100000)), snapshot=snapshot)
    return svc.price_kth_to_default(pds, rho, k, snapshot=snapshot)


def _convertible(svc, v, snapshot):
    S, sig, q = _num(v, "S", 100), _num(v, "sigma", .3), _num(v, "q", 0)
    face, cpn = _num(v, "face", 1000), _num(v, "coupon", .05)
    freq, T, ratio = int(_num(v, "freq", 2)), _num(v, "T", 5), _num(v, "conv_ratio", 10)
    if v.get("engine") == "afv_convertible":
        return svc.price_afv_convertible(S, sig, q, face, cpn, freq, T, ratio,
                                         _num(v, "r", .1), _num(v, "lam0", .02),
                                         _num(v, "alpha", 1.2), _num(v, "recovery", .4),
                                         int(_num(v, "N", 400)), snapshot=snapshot)
    return svc.price_convertible_bond(S, sig, q, face, cpn, freq, T, ratio,
                                      _num(v, "credit_spread", .02),
                                      N=int(_num(v, "N", 400)),
                                      curve=_curve(svc, v, snapshot), snapshot=snapshot)


def _fx_option(svc, v, snapshot):
    eng = v.get("engine", "garman_kohlhagen")
    S, K, T = _num(v, "S", 90), _num(v, "K", 92), _num(v, "T", 1)
    rd, rf = _num(v, "r_d", .16), _num(v, "r_f", .05)
    if eng == "fx_smile":
        return svc.price_fx_option_smile(S, K, T, rd, rf, _num(v, "atm", .18),
                                         _num(v, "rr", -.025), _num(v, "bf", .008),
                                         _num(v, "notional", 1e6), v.get("opt", "call"),
                                         snapshot=snapshot)
    if eng == "vanna_volga":
        return svc.price_vanna_volga(S, K, T, rd, rf, _num(v, "K_atm", 92),
                                     _num(v, "sig_atm", .18), _num(v, "K_put", 85),
                                     _num(v, "sig_put", .21), _num(v, "K_call", 99),
                                     _num(v, "sig_call", .19), v.get("opt", "call"),
                                     snapshot=snapshot)
    return svc.price_fx_option(S, K, T, rd, rf, _num(v, "sigma", .15),
                               _num(v, "notional", 1e6), v.get("opt", "call"),
                               snapshot=snapshot)


def _commodity_option(svc, v, snapshot):
    model = v.get("engine", "schwartz_smith")
    kw = {k: float(v[k]) for k in ("sigma_chi", "mu_xi", "sigma_xi", "chi0", "delta0",
                                   "sigma_S", "alpha_tilde", "sigma_delta")
          if k in v and v[k] is not None}
    return svc.price_commodity_option(model, _num(v, "spot", 100), _num(v, "K", 100),
                                      _num(v, "T_option", 1), _num(v, "T_future", 1.25),
                                      v.get("opt", "call"), _num(v, "r", .05),
                                      _num(v, "kappa", 1.0), _num(v, "rho", .3),
                                      snapshot=snapshot, **kw)


def _commodity_curve(svc, v, snapshot):
    model = v.get("engine", "schwartz_smith")
    kw = {k: float(v[k]) for k in ("sigma_chi", "mu_xi", "sigma_xi", "chi0", "delta0",
                                   "sigma_S", "alpha_tilde", "sigma_delta")
          if k in v and v[k] is not None}
    return svc.commodity_futures_curve(model, _num(v, "spot", 100),
                                       _floats(v.get("tenors", "0.25,0.5,1,2,3,5")),
                                       _num(v, "r", .05), _num(v, "kappa", 1.0),
                                       _num(v, "rho", .3), **kw)


def _two_asset(svc, v, snapshot):
    return svc.price_two_asset_option(_num(v, "S1", 100), _num(v, "S2", 100),
                                      _num(v, "T", 1), _num(v, "r", .05),
                                      _num(v, "q1", 0), _num(v, "q2", 0),
                                      _num(v, "sigma1", .2), _num(v, "sigma2", .25),
                                      _num(v, "rho", .4), v.get("kind", "exchange"),
                                      _num(v, "K", 0), int(_num(v, "N1", 80)),
                                      int(_num(v, "N2", 80)), int(_num(v, "Nt", 100)),
                                      snapshot=snapshot)


def _spread(svc, v, snapshot):
    if v.get("engine") == "adi":
        vv = dict(v)
        vv["kind"] = "spread"
        return _two_asset(svc, vv, snapshot)
    return svc.price_spread_option(_num(v, "S1", 100), _num(v, "S2", 100), _num(v, "K", 5),
                                   _num(v, "T", 1), _num(v, "r", .05), _num(v, "sigma1", .2),
                                   _num(v, "sigma2", .25), _num(v, "rho", .4),
                                   _num(v, "q1", 0), _num(v, "q2", 0), snapshot=snapshot)


def _basket_opt(svc, v, snapshot):
    spots = _floats(v.get("spots", "100,100,100"))
    weights = _floats(v.get("weights", "0.4,0.3,0.3"))
    sigmas = _floats(v.get("sigmas", "0.2,0.25,0.3"))
    corr = _corr_matrix(_num(v, "rho", .4), len(spots))
    return svc.price_basket_option(spots, weights, _num(v, "K", 100), _num(v, "T", 1),
                                   _num(v, "r", .05), sigmas, corr,
                                   v.get("opt", "call"), snapshot=snapshot)


def _rainbow(svc, v, snapshot):
    spots = _floats(v.get("spots", "100,95"))
    sigmas = _floats(v.get("sigmas", "0.2,0.3"))
    corr = _corr_matrix(_num(v, "rho", .3), len(spots))
    return svc.price_rainbow_option(spots, _num(v, "T", 1), _num(v, "r", .05), sigmas,
                                    corr, v.get("style", "best_of_cash"),
                                    _num(v, "cash", 90), snapshot=snapshot)


def _autocall(svc, v, snapshot):
    T = _num(v, "T", 3)
    obs = _floats(v.get("obs_dates", "")) or [float(i) for i in range(1, max(int(round(T)), 1) + 1)]
    return svc.price_autocall_phoenix(_num(v, "S0", 100), _num(v, "r", .05), _num(v, "q", 0),
                                      _num(v, "sigma", .2), T, obs,
                                      _num(v, "autocall_barrier", 1.0),
                                      _num(v, "coupon_barrier", .7), _num(v, "ki_barrier", .65),
                                      _num(v, "coupon_rate", .1),
                                      v.get("memory_coupon", "yes") == "yes",
                                      int(_num(v, "n_sims", 20000)),
                                      int(_num(v, "steps", 100)), snapshot=snapshot)


def _basket_note(svc, v, snapshot):
    cap = _num(v, "cap", 0.0)
    return svc.price_basket_note(_parse_basket(v.get("basket", "SBER:0.4,GAZP:0.3,LKOH:0.3")),
                                 _num(v, "r", .16), _num(v, "T", 3),
                                 principal_protection=_num(v, "principal_protection", 1.0),
                                 guaranteed_coupon=_num(v, "guaranteed_coupon", 0.0),
                                 coupon_freq=int(_num(v, "coupon_freq", 1)),
                                 participation=_num(v, "participation", 1.0),
                                 cap=(cap or None), basket_type=v.get("basket_type", "average"),
                                 face=_num(v, "face", 1000),
                                 n_sims=int(_num(v, "n_sims", 20000)), snapshot=snapshot)


# ── the catalogue ────────────────────────────────────────────────────
PRODUCTS: list[WsProduct] = [
    # ═══ EQUITY / OPTIONS ═══════════════════════════════════════════
    WsProduct(
        "european_option", "European Option", "equity", "Vanilla",
        [_spot(), _strike(), _mat(), _rate("r", "Risk-free r", 0.05), _div(),
         _sigma(), _optype()],
        [E("black_scholes"), E("black76"), E("bachelier"),
         E("binomial_crr"), E("binomial_lr"), E("trinomial"),
         E("binomial_jr", params=[P("N", "Tree steps", 500, "numerical", dtype="int",
                                    minimum=10, maximum=5000)]),
         E("binomial_tian", params=[P("N", "Tree steps", 500, "numerical", dtype="int",
                                      minimum=10, maximum=5000)]),
         E("pde_cn"), E("mc_gbm"), E("qmc"),
         E("heston_cf"), E("mc_heston", "Heston Monte Carlo (Euler)"),
         E("mc_heston_qe", "Heston Monte Carlo (Andersen QE)"),
         E("bates"), E("merton_jump"), E("merton_cos"),
         E("kou"), E("variance_gamma"), E("nig"), E("cgmy"),
         E("rough_bergomi"),
         E("carr_madan", params=[
             P("cf_model", "Char. function", "bsm", "model", dtype="choice",
               choices=["bsm", "heston"]),
             P("v0", "Heston v0", 0.04, "model", minimum=1e-4, maximum=2.0),
             P("kappa", "Heston κ", 1.5, "model", minimum=1e-3, maximum=20.0),
             P("theta", "Heston θ", 0.04, "model", minimum=1e-4, maximum=2.0),
             P("xi", "Heston ξ", 0.3, "model", minimum=1e-3, maximum=3.0),
             P("rho", "Heston ρ", -0.6, "model", minimum=-0.999, maximum=0.999)]),
         E("heston_adi", "Heston ADI 2-D PDE", model_id="heston_adi"),
         E("cev", params=[P("beta", "CEV β", 1.0, "model", minimum=0.1, maximum=1.0,
                            help="β=1 → BSM; σ в CEV-единицах")]),
         E("displaced_diffusion", params=[P("shift", "Displacement", 0.0, "model",
                                            minimum=0.0, maximum=1000.0)]),
         E("discrete_div_bsm", params=[P("dividends", "Dividends t:amt", "0.5:2.0",
                                         "model", dtype="schedule")]),
         E("lognormal_mixture", params=[
             P("sigma_list", "σ components", "0.15,0.30", "model", dtype="text"),
             P("weights", "Weights", "0.6,0.4", "model", dtype="text")])],
        _european, underlying=_EQ_UNDERLYING, vol_surfaces=True),
    WsProduct(
        "american_option", "American Option", "equity", "Vanilla",
        [_spot(), _strike(), _mat(), _rate("r", "Risk-free r", 0.05), _div(),
         _sigma(), _optype("put")],
        [E("pde_cn"), E("binomial_crr"), E("binomial_lr"), E("trinomial"),
         E("mc_lsm"), E("baw"), E("bjerksund_stensland")],
        _american, underlying=_EQ_UNDERLYING),
    WsProduct(
        "barrier_option", "Barrier Option", "equity", "Exotics",
        [_spot(), _strike(), P("H", "Barrier H", 90.0, "contract", minimum=0.0),
         P("rebate", "Rebate", 0.0, "contract", minimum=0.0),
         _mat(), _rate("r", "Risk-free r", 0.05), _div(), _sigma(), _optype(),
         P("barrier_type", "Barrier type", "down-out", "contract", dtype="choice",
           choices=["down-out", "down-in", "up-out", "up-in"])],
        [E("barrier"), E("pde_cn")],
        _barrier, underlying=_EQ_UNDERLYING,
        note="Непрерывный мониторинг барьера (Reiner–Rubinstein); дискретный "
             "мониторинг не моделируется (поправка Броди–Глассермана-Коу не "
             "применяется) — дискретный барьер пробивается реже."),
    WsProduct(
        "asian_option", "Asian Option", "equity", "Exotics",
        [_spot(), _strike(), _mat(), _rate("r", "Risk-free r", 0.05), _div(), _sigma(),
         _optype(),
         P("averaging", "Averaging", "arithmetic", "contract", dtype="choice",
           choices=["arithmetic", "geometric"]),
         P("n", "Fixings", 12, "contract", dtype="int", minimum=1, maximum=252),
         P("n_sims", "MC paths", 50000, "numerical", dtype="int",
           minimum=1000, maximum=500000)],
        [E("asian")],
        lambda svc, v, snap: svc.price_asian_option(
            _num(v, "S", 100), _num(v, "K", 100), _num(v, "T", 1), _num(v, "r", .05),
            _num(v, "sigma", .2), _num(v, "q", 0), v.get("opt", "call"),
            v.get("averaging", "arithmetic"), int(_num(v, "n", 12)),
            int(_num(v, "n_sims", 50000)), snapshot=snap),
        underlying=_EQ_UNDERLYING,
        note="Фиксинги равномерные по сроку (n штук), среднее арифметич./геом. "
             "по цене; MC с фиксированным seed (воспроизводимость)."),
    WsProduct(
        "digital_option", "Digital Option", "equity", "Exotics",
        [_spot(), _strike(), _mat(0.5), _rate("r", "Risk-free r", 0.04), _div(), _sigma(),
         _optype(),
         P("style", "Payout", "cash", "contract", dtype="choice", choices=["cash", "asset"]),
         P("cash", "Cash payout", 1.0, "contract", minimum=0.0)],
        [E("digital")],
        lambda svc, v, snap: svc.price_digital_option(
            _num(v, "S", 100), _num(v, "K", 100), _num(v, "T", .5), _num(v, "r", .04),
            _num(v, "sigma", .2), _num(v, "q", 0), v.get("opt", "call"),
            v.get("style", "cash"), _num(v, "cash", 1.0), snapshot=snap),
        underlying=_EQ_UNDERLYING,
        note="Разрывный payoff: greeks у страйка вблизи экспирации нестабильны; "
             "спред-репликация (call spread) не применяется."),
    WsProduct(
        "lookback_option", "Lookback Option", "equity", "Exotics",
        [_spot(), _mat(), _rate("r", "Risk-free r", 0.05), _div(), _sigma(), _optype(),
         P("strike_type", "Strike type", "floating", "contract", dtype="choice",
           choices=["floating", "fixed"]),
         _strike()],
        [E("lookback")],
        lambda svc, v, snap: svc.price_lookback_option(
            _num(v, "S", 100), _num(v, "T", 1), _num(v, "r", .05), _num(v, "sigma", .2),
            _num(v, "q", 0), v.get("opt", "call"), v.get("strike_type", "floating"),
            _num(v, "K", 100), snapshot=snap),
        underlying=_EQ_UNDERLYING,
        note="Непрерывное наблюдение экстремума (Goldman–Sosin–Gatto); "
             "дискретное наблюдение даёт меньшую стоимость."),
    WsProduct(
        "variance_swap", "Variance Swap", "equity", "Volatility",
        [_spot(), _mat(), _rate("r", "Risk-free r", 0.05), _div(),
         _sigma(0.20, "ATM vol σ"),
         P("skew", "Smile skew", 0.0, "market", minimum=-3.0, maximum=3.0,
           help="σ(K)=σ·(1+skew·ln(K/F)); 0 = флэт"),
         P("vega_notional", "Vega notional", 100000.0, "contract", minimum=0.0),
         P("n_strikes", "Strikes per wing", 25, "numerical", dtype="int",
           minimum=5, maximum=200),
         P("width", "Strip width ±%F", 0.5, "numerical", minimum=0.1, maximum=0.9)],
        [E("variance_swap")],
        lambda svc, v, snap: svc.price_variance_swap(
            _num(v, "S", 100), _num(v, "T", 1), _num(v, "r", .05), _num(v, "sigma", .2),
            _num(v, "q", 0), _num(v, "skew", 0), _num(v, "vega_notional", 1e5),
            int(_num(v, "n_strikes", 25)), _num(v, "width", .5), snapshot=snap),
        underlying=_EQ_UNDERLYING,
        note="Fair strike репликацией лог-контракта (Demeterfi); headline в vol-пунктах."),
    WsProduct(
        "equity_forward", "Equity Forward", "equity", "Linear",
        [_spot(), _strike(), _mat(), _rate("r", "Risk-free r", 0.05), _div(),
         _notional(1.0, "Notional (units)"),
         P("position", "Position", "long", "contract", dtype="choice",
           choices=["long", "short"])],
        [E("equity_forward")],
        lambda svc, v, snap: svc.price_equity_forward(
            _num(v, "S", 100), _num(v, "K", 100), _num(v, "T", 1),
            _num(v, "r", .05), _num(v, "q", 0), _num(v, "notional", 1),
            v.get("position", "long"), snapshot=snap),
        underlying=_EQ_UNDERLYING,
        note="Точный cost-of-carry F=S·e^{(r−q)T}; без волатильности. Дискретные дивиденды не моделируются."),
    WsProduct(
        "equity_swap", "Equity Total-Return Swap", "equity", "Linear",
        [_spot(), _notional(1e6, "Notional"), _mat(5.0),
         _rate("r", "Financing rate r", 0.10), _div(),
         P("spread", "Financing spread", 0.005, "contract",
           minimum=-0.5, maximum=0.5, help="спред над плавающей ставкой"),
         _freq(4),
         P("receive_equity", "Receive equity leg", "yes", "contract",
           dtype="choice", choices=["yes", "no"])],
        [E("equity_swap")],
        lambda svc, v, snap: svc.price_equity_swap(
            _num(v, "S", 100), _num(v, "notional", 1e6), _num(v, "T", 5),
            _num(v, "r", .10), _num(v, "q", 0), _num(v, "spread", .005),
            int(_num(v, "freq", 4)), v.get("receive_equity", "yes") == "yes",
            snapshot=snap),
        underlying=_EQ_UNDERLYING,
        note="Total-return vs финансирование+спред; непрерывный ресет (carry/дивиденды сокращаются). Дискретные фиксинги и borrow не моделируются."),
    WsProduct(
        "dividend_swap", "Dividend Swap", "equity", "Linear",
        [_spot(), _mat(), _rate("r", "Risk-free r", 0.05),
         P("q", "Dividend yield q", 0.03, "market", minimum=0.0, maximum=1.0),
         P("div_strike", "Dividend strike", 0.0, "contract", minimum=0.0,
           help="0 = использовать fair strike"),
         _notional(1.0, "Notional (units)"),
         P("position", "Position", "long", "contract", dtype="choice",
           choices=["long", "short"])],
        [E("dividend_swap")],
        lambda svc, v, snap: svc.price_dividend_swap(
            _num(v, "S", 100), _num(v, "T", 1), _num(v, "r", .05),
            _num(v, "q", .03),
            (_num(v, "div_strike", 0) or None), _num(v, "notional", 1),
            v.get("position", "long"), snapshot=snap),
        underlying=_EQ_UNDERLYING,
        note="Реализованные дивиденды vs фиксированный страйк; PV=S(1−e^{−qT}) при непрерывной q."),
    WsProduct(
        "equity_future", "Equity Future", "equity", "Linear",
        [_spot(), _strike(), _mat(), _rate("r", "Risk-free r", 0.05), _div(),
         _notional(1.0, "Notional (units)"),
         P("position", "Position", "long", "contract", dtype="choice",
           choices=["long", "short"])],
        [E("equity_future")],
        lambda svc, v, snap: svc.price_equity_future(
            _num(v, "S", 100), _num(v, "K", 100), _num(v, "T", 1),
            _num(v, "r", .05), _num(v, "q", 0), _num(v, "notional", 1),
            v.get("position", "long"), snapshot=snap),
        underlying=_EQ_UNDERLYING,
        note="Фьючерс: F=S·e^{(r−q)T}, MtM без дисконта (daily variation margin); futures delta > forward."),
    WsProduct(
        "warrant", "Warrant (dilution-adjusted)", "equity", "Vanilla",
        [_spot(), _strike(), _mat(2.0), _rate("r", "Risk-free r", 0.05), _div(),
         _sigma(), _optype(),
         P("n_shares", "Shares outstanding", 100.0, "contract", minimum=1.0),
         P("n_warrants", "Warrants issued", 10.0, "contract", minimum=0.0),
         _notional(1.0, "Notional (units)")],
        [E("warrant")],
        lambda svc, v, snap: svc.price_warrant(
            _num(v, "S", 100), _num(v, "K", 100), _num(v, "T", 2),
            _num(v, "r", .05), _num(v, "sigma", .2), _num(v, "q", 0),
            _num(v, "n_shares", 100), _num(v, "n_warrants", 10),
            v.get("opt", "call"), _num(v, "notional", 1), snapshot=snap),
        underlying=_EQ_UNDERLYING,
        note="Разводнение W=(N/(N+M))·C_BSM (dilution-factor аппроксимация)."),

    # ═══ RATES ══════════════════════════════════════════════════════
    WsProduct(
        "term_deposit", "Money-Market Deposit", "rates", "Linear",
        [_notional(1e6, "Notional"),
         P("deposit_rate", "Deposit rate", 0.12, "contract",
           minimum=-1.0, maximum=2.0), _mat(0.25),
         _rate("r", "Discount rate r", 0.10),
         P("basis", "Accrual", "simple", "contract", dtype="choice",
           choices=["simple", "continuous"]),
         P("deposit", "Side", "deposit", "contract", dtype="choice",
           choices=["deposit", "loan"])],
        [E("term_deposit")],
        lambda svc, v, snap: svc.price_term_deposit(
            _num(v, "notional", 1e6), _num(v, "deposit_rate", .12),
            _num(v, "T", .25), _num(v, "r", .10), v.get("basis", "simple"),
            v.get("deposit", "deposit") == "deposit", snapshot=snap),
        note="Депозит/заём МБК: простое (ACT/365) или непрерывное начисление, дисконт к плоской ставке."),
    WsProduct(
        "fra", "Forward Rate Agreement", "rates", "Linear",
        [_notional(), P("K", "Fixed rate", 0.10, "contract", minimum=-1.0, maximum=2.0),
         P("T1", "Start", 1.0, "contract", minimum=0.01, maximum=50.0, unit="y"),
         P("T2", "End", 1.5, "contract", minimum=0.02, maximum=50.0, unit="y"),
         _rate()],
        [E("fra")],
        lambda svc, v, snap: svc.price_fra(
            _num(v, "notional", 1e6), _num(v, "K", .1), _num(v, "T1", 1), _num(v, "T2", 1.5),
            curve=_curve(svc, v, snap), proj_curve=_proj(svc, v, snap), snapshot=snap),
        needs_curve=True, needs_proj=True),
    WsProduct(
        "irs", "Interest Rate Swap", "rates", "Linear",
        [_notional(), P("fixed_rate", "Fixed rate", 0.10, "contract", minimum=-1.0, maximum=2.0),
         _mat(5.0), _freq(4), _rate(),
         P("side", "Direction", "pay fixed", "contract", dtype="choice",
           choices=["pay fixed", "receive fixed"])],
        [E("irs")],
        lambda svc, v, snap: svc.price_irs(
            _num(v, "notional", 1e6), _num(v, "fixed_rate", .1), _num(v, "T", 5),
            int(_num(v, "freq", 4)), curve=_curve(svc, v, snap),
            pay_fixed=v.get("side", "pay fixed") == "pay fixed",
            proj_curve=_proj(svc, v, snap), snapshot=snap),
        needs_curve=True, needs_proj=True),
    WsProduct(
        "cap_floor", "Cap / Floor", "rates", "Options",
        [_notional(), P("K", "Strike rate", 0.10, "contract", minimum=-1.0, maximum=2.0),
         _mat(3.0), _freq(2),
         P("vol", "Rate vol", 0.20, "market", minimum=1e-3, maximum=3.0), _rate(),
         _optype("cap", ["cap", "floor"])],
        [E("capfloor", "Black-76 caplet strip"),
         E("lmm", params=[P("vol", "LMM forward vol", 0.20, "model",
                            minimum=1e-3, maximum=2.0)])],
        _capfloor, needs_curve=True, needs_proj=True,
        note="⚠️ IRVOL: рыночного источника вол ставок нет — vol вводится вручную. НЕ для прод-оценки. Коррекция: ATM-матрица swaption vols (ручная загрузка/платный источник) или калибровка HW к историческим переоценкам ОФЗ."),
    WsProduct(
        "swaption", "European Swaption", "rates", "Options",
        [_notional(), P("K", "Strike rate", 0.10, "contract", minimum=-1.0, maximum=2.0),
         P("T_option", "Expiry", 1.0, "contract", minimum=0.05, maximum=30.0, unit="y"),
         P("T_swap", "Swap tenor", 5.0, "contract", minimum=0.25, maximum=50.0, unit="y"),
         _freq(2), P("sigma", "Black vol", 0.20, "market", minimum=1e-3, maximum=3.0),
         _rate(), _optype("payer", ["payer", "receiver"])],
        [E("swaption", "Black-76"), E("g2pp"), E("lmm"), E("bk"), E("cheyette"),
         E("swap_market_model", params=[
             P("sigma", "SMM vol", 0.20, "model", minimum=1e-3, maximum=2.0),
             P("shift", "Displacement", 0.0, "model", minimum=0.0, maximum=0.5)])],
        _swaption, needs_curve=True, note="⚠️ IRVOL: рыночного источника вол ставок нет — vol вводится вручную. НЕ для прод-оценки. Коррекция: ATM-матрица swaption vols (ручная загрузка/платный источник) или калибровка HW к историческим переоценкам ОФЗ."),
    WsProduct(
        "bermudan_swaption", "Bermudan Swaption", "rates", "Options",
        [_notional(), P("K", "Strike rate", 0.10, "contract", minimum=-1.0, maximum=2.0),
         P("ex_dates", "Exercise dates (y)", "1,2,3", "contract", dtype="schedule"),
         P("T_end", "Swap end", 6.0, "contract", minimum=0.5, maximum=50.0, unit="y"),
         _freq(2), _rate(), _optype("payer", ["payer", "receiver"])],
        [E("bermudan_swaption", "Hull-White tree"),
         E("amc", "AMC (Longstaff-Schwartz)", params=[
             P("kappa", "HW mean reversion κ", 0.1, "model", minimum=1e-3, maximum=3.0),
             P("sigma_r", "HW vol σ", 0.012, "model", minimum=1e-4, maximum=0.5),
             P("n_sims", "MC paths", 20000, "numerical", dtype="int",
               minimum=2000, maximum=200000)])],
        _bermudan, needs_curve=True, note="⚠️ IRVOL: рыночного источника вол ставок нет — vol вводится вручную. НЕ для прод-оценки. Коррекция: ATM-матрица swaption vols (ручная загрузка/платный источник) или калибровка HW к историческим переоценкам ОФЗ."),
    WsProduct(
        "cms_swap", "CMS Swap", "rates", "Exotic rates",
        [_notional(), P("K", "Fixed rate", 0.10, "contract", minimum=-1.0, maximum=2.0),
         _mat(5.0), _freq(4),
         P("swap_tenor", "CMS tenor", 5.0, "contract", minimum=1.0, maximum=30.0, unit="y"),
         P("sigma", "Swap-rate vol", 0.25, "market", minimum=1e-3, maximum=3.0), _rate()],
        [E("cms_swap")],
        lambda svc, v, snap: svc.price_cms_swap(
            _num(v, "notional", 1e6), _num(v, "K", .1), _num(v, "T", 5),
            int(_num(v, "freq", 4)), _num(v, "swap_tenor", 5), _num(v, "sigma", .25),
            curve=_curve(svc, v, snap), snapshot=snap),
        needs_curve=True,
        note="Форвардная своп-ставка + convexity adjustment (Hull) + timing adjustment. ⚠️ IRVOL: рыночного источника вол ставок нет — vol вводится вручную. НЕ для прод-оценки. Коррекция: ATM-матрица swaption vols (ручная загрузка/платный источник) или калибровка HW к историческим переоценкам ОФЗ."),
    WsProduct(
        "stir_future", "STIR Future", "rates", "Futures",
        [P("forward_rate", "Forward rate", 0.10, "market", minimum=-1.0, maximum=2.0),
         _notional(), P("tenor", "Tenor", 0.25, "contract", minimum=0.02, maximum=2.0,
                        unit="y")],
        [E("stir_future")],
        lambda svc, v, snap: svc.price_stir_future(
            _num(v, "forward_rate", .1), _num(v, "notional", 1e6),
            _num(v, "tenor", .25), snapshot=snap)),
    WsProduct(
        "bond_future", "Bond Future (CTD)", "rates", "Futures",
        [P("clean_price", "CTD clean price", 98.0, "market", minimum=0.0),
         P("accrued", "Accrued", 1.0, "market", minimum=0.0),
         P("conversion_factor", "Conversion factor", 0.9, "contract",
           minimum=0.01, maximum=3.0),
         P("coupon_income", "Coupon income", 0.0, "contract"),
         P("ctd_dv01", "CTD DV01", 0.08, "market", minimum=0.0),
         P("futures_price", "Futures price", 108.0, "market", minimum=0.0),
         P("repo_rate", "Repo rate", 0.08, "market", minimum=-1.0, maximum=2.0),
         P("T_delivery", "Delivery", 0.25, "contract", minimum=0.01, maximum=3.0, unit="y"),
         P("target_bpv", "Target BPV", 1000.0, "contract", minimum=0.0)],
        [E("bond_future")],
        lambda svc, v, snap: svc.price_bond_future(
            [{"name": "CTD", "clean_price": _num(v, "clean_price", 98),
              "accrued": _num(v, "accrued", 1),
              "conversion_factor": _num(v, "conversion_factor", .9),
              "coupon_income": _num(v, "coupon_income", 0),
              "dv01": _num(v, "ctd_dv01", .08)}],
            _num(v, "futures_price", 108), _num(v, "repo_rate", .08),
            _num(v, "T_delivery", .25), _num(v, "target_bpv", 1000), snapshot=snap)),

    # ═══ FX ═════════════════════════════════════════════════════════
    WsProduct(
        "fx_forward", "FX Forward", "fx", "Linear",
        [_spot("FX spot", 90.0), P("r_d", "Domestic rate", 0.16, "market",
                                   minimum=-1.0, maximum=2.0),
         P("r_f", "Foreign rate", 0.05, "market", minimum=-1.0, maximum=2.0),
         _mat(), _notional(1e6, "Notional (fgn)"),
         P("forward_agreed", "Agreed forward (0=fair)", 0.0, "contract", minimum=0.0)],
        [E("fx_forward")],
        lambda svc, v, snap: svc.price_fx_forward(
            _num(v, "S", 90), _num(v, "r_d", .16), _num(v, "r_f", .05), _num(v, "T", 1),
            _num(v, "notional", 1e6), (_num(v, "forward_agreed", 0) or None),
            snapshot=snap),
        underlying=_FX_UNDERLYING),
    WsProduct(
        "ndf", "Non-Deliverable Forward", "fx", "Linear",
        [_spot("FX spot", 90.0), P("K", "NDF rate", 92.0, "contract", minimum=0.0),
         _mat(0.5), P("r_d", "Domestic rate", 0.16, "market", minimum=-1.0, maximum=2.0),
         P("r_f", "Foreign rate", 0.05, "market", minimum=-1.0, maximum=2.0),
         _notional(1e6, "Notional (fgn)"),
         P("settle", "Settlement ccy", "foreign", "contract", dtype="choice",
           choices=["foreign", "domestic"]),
         P("position", "Position", "long", "contract", dtype="choice",
           choices=["long", "short"])],
        [E("ndf")],
        lambda svc, v, snap: svc.price_ndf(
            _num(v, "S", 90), _num(v, "K", 92), _num(v, "T", .5), _num(v, "r_d", .16),
            _num(v, "r_f", .05), _num(v, "notional", 1e6), v.get("settle", "foreign"),
            v.get("position", "long"), snapshot=snap),
        underlying=_FX_UNDERLYING),
    WsProduct(
        "fx_option", "FX Option", "fx", "Options",
        [_spot("FX spot", 90.0), _strike(92.0), _mat(),
         P("r_d", "Domestic rate", 0.16, "market", minimum=-1.0, maximum=2.0),
         P("r_f", "Foreign rate", 0.05, "market", minimum=-1.0, maximum=2.0),
         _sigma(0.15), _notional(), _optype()],
        [E("garman_kohlhagen"),
         E("fx_smile", "Malz smile (ATM/RR/BF)", params=[
             P("atm", "ATM vol", 0.18, "model", minimum=1e-3, maximum=3.0),
             P("rr", "25Δ risk reversal", -0.025, "model", minimum=-1.0, maximum=1.0),
             P("bf", "25Δ butterfly", 0.008, "model", minimum=-1.0, maximum=1.0)]),
         E("vanna_volga", params=[
             P("K_atm", "ATM strike", 92.0, "model", minimum=0.0),
             P("sig_atm", "ATM vol", 0.18, "model", minimum=1e-3, maximum=3.0),
             P("K_put", "25Δ put strike", 85.0, "model", minimum=0.0),
             P("sig_put", "25Δ put vol", 0.21, "model", minimum=1e-3, maximum=3.0),
             P("K_call", "25Δ call strike", 99.0, "model", minimum=0.0),
             P("sig_call", "25Δ call vol", 0.19, "model", minimum=1e-3, maximum=3.0)])],
        _fx_option, underlying=_FX_UNDERLYING),
    WsProduct(
        "fx_barrier", "FX Barrier Option", "fx", "Options",
        [_spot("FX spot", 90.0), _strike(92.0),
         P("H", "Barrier H", 85.0, "contract", minimum=0.0),
         P("rebate", "Rebate", 0.0, "contract", minimum=0.0), _mat(),
         P("r_d", "Domestic rate", 0.16, "market", minimum=-1.0, maximum=2.0),
         P("r_f", "Foreign rate", 0.05, "market", minimum=-1.0, maximum=2.0),
         _sigma(0.15), _optype(),
         P("barrier_type", "Barrier type", "down-out", "contract", dtype="choice",
           choices=["down-out", "down-in", "up-out", "up-in"]),
         _notional()],
        [E("barrier", "FX barrier (GK closed form)")],
        lambda svc, v, snap: svc.price_fx_barrier(
            _num(v, "S", 90), _num(v, "K", 92), _num(v, "H", 85), _num(v, "T", 1),
            _num(v, "r_d", .16), _num(v, "r_f", .05), _num(v, "sigma", .15),
            v.get("opt", "call"), v.get("barrier_type", "down-out"),
            _num(v, "rebate", 0), _num(v, "notional", 1e6), snapshot=snap),
        underlying=_FX_UNDERLYING,
        note="Garman-Kohlhagen carry (q=r_f), непрерывный мониторинг барьера; премия в domestic."),
    WsProduct(
        "fx_digital", "FX Digital Option", "fx", "Options",
        [_spot("FX spot", 90.0), _strike(92.0), _mat(0.5),
         P("r_d", "Domestic rate", 0.16, "market", minimum=-1.0, maximum=2.0),
         P("r_f", "Foreign rate", 0.05, "market", minimum=-1.0, maximum=2.0),
         _sigma(0.15), _optype(),
         P("style", "Payout", "cash", "contract", dtype="choice",
           choices=["cash", "asset"]),
         P("cash", "Cash payout", 1.0, "contract", minimum=0.0), _notional()],
        [E("digital", "FX digital (GK)")],
        lambda svc, v, snap: svc.price_fx_digital(
            _num(v, "S", 90), _num(v, "K", 92), _num(v, "T", .5),
            _num(v, "r_d", .16), _num(v, "r_f", .05), _num(v, "sigma", .15),
            v.get("opt", "call"), v.get("style", "cash"), _num(v, "cash", 1),
            _num(v, "notional", 1e6), snapshot=snap),
        underlying=_FX_UNDERLYING,
        note="Cash/asset-or-nothing, GK carry q=r_f; разрывный payoff — greeks у страйка нестабильны."),
    WsProduct(
        "fx_asian", "FX Asian Option", "fx", "Options",
        [_spot("FX spot", 90.0), _strike(92.0), _mat(),
         P("r_d", "Domestic rate", 0.16, "market", minimum=-1.0, maximum=2.0),
         P("r_f", "Foreign rate", 0.05, "market", minimum=-1.0, maximum=2.0),
         _sigma(0.15), _optype(),
         P("averaging", "Averaging", "arithmetic", "contract", dtype="choice",
           choices=["arithmetic", "geometric"]),
         P("n", "Fixings", 12, "contract", dtype="int", minimum=1, maximum=252),
         P("n_sims", "MC paths", 50000, "numerical", dtype="int",
           minimum=1000, maximum=500000), _notional()],
        [E("asian", "FX asian (GK)")],
        lambda svc, v, snap: svc.price_fx_asian(
            _num(v, "S", 90), _num(v, "K", 92), _num(v, "T", 1),
            _num(v, "r_d", .16), _num(v, "r_f", .05), _num(v, "sigma", .15),
            v.get("opt", "call"), v.get("averaging", "arithmetic"),
            int(_num(v, "n", 12)), int(_num(v, "n_sims", 50000)),
            _num(v, "notional", 1e6), snapshot=snap),
        underlying=_FX_UNDERLYING,
        note="Равномерные фиксинги по сроку, GK carry q=r_f; MC с фиксированным seed."),
    WsProduct(
        "fx_lookback", "FX Lookback Option", "fx", "Options",
        [_spot("FX spot", 90.0), _mat(),
         P("r_d", "Domestic rate", 0.16, "market", minimum=-1.0, maximum=2.0),
         P("r_f", "Foreign rate", 0.05, "market", minimum=-1.0, maximum=2.0),
         _sigma(0.15), _optype(),
         P("strike_type", "Strike type", "floating", "contract", dtype="choice",
           choices=["floating", "fixed"]),
         _strike(92.0), _notional()],
        [E("lookback", "FX lookback (GK)")],
        lambda svc, v, snap: svc.price_fx_lookback(
            _num(v, "S", 90), _num(v, "T", 1), _num(v, "r_d", .16),
            _num(v, "r_f", .05), _num(v, "sigma", .15), v.get("opt", "call"),
            v.get("strike_type", "floating"), _num(v, "K", 92),
            _num(v, "notional", 1e6), snapshot=snap),
        underlying=_FX_UNDERLYING,
        note="Непрерывное наблюдение экстремума, GK carry q=r_f."),
    WsProduct(
        "xccy_swap", "Cross-Currency Swap", "fx", "Swaps",
        [_notional(90e6, "Notional (dom)"), _spot("FX spot", 90.0), _mat(5.0), _freq(4),
         P("basis_spread", "Basis spread", -0.005, "contract", minimum=-0.2, maximum=0.2),
         _rate("r", "Domestic rate", 0.14),
         P("fgn_rate", "Foreign rate", 0.05, "market", minimum=-1.0, maximum=2.0),
         P("leg_dom", "Domestic leg", "float", "contract", dtype="choice",
           choices=["float", "fixed"]),
         P("leg_fgn", "Foreign leg", "float", "contract", dtype="choice",
           choices=["float", "fixed"]),
         P("fixed_rate_dom", "Domestic fixed", 0.14, "contract", minimum=-1.0, maximum=2.0),
         P("fixed_rate_fgn", "Foreign fixed", 0.05, "contract", minimum=-1.0, maximum=2.0)],
        [E("xccy_swap")],
        lambda svc, v, snap: svc.price_xccy_swap(
            _num(v, "notional", 9e7), _num(v, "S", 90), _num(v, "T", 5),
            int(_num(v, "freq", 4)), _num(v, "basis_spread", -.005),
            v.get("leg_dom", "float"), v.get("leg_fgn", "float"),
            _num(v, "fixed_rate_dom", .14), _num(v, "fixed_rate_fgn", .05),
            disc_dom=_curve(svc, v, snap), fgn_rate=_num(v, "fgn_rate", .05),
            snapshot=snap),
        needs_curve=True, curve_label="Domestic discount curve",
        underlying=_FX_UNDERLYING),

    # ═══ CREDIT ═════════════════════════════════════════════════════
    WsProduct(
        "cds_index", "CDS Index", "credit", "Index",
        [_notional(10e6, "Notional"),
         P("index_spread", "Index spread", 0.011, "market", minimum=0.0,
           maximum=1.0, help="котируемый спред индекса (iTraxx/CDX-стиль)"),
         P("coupon", "Fixed coupon", 0.01, "contract", minimum=0.0, maximum=0.1,
           help="стандартный купон 100/500bp"),
         _mat(5.0), _freq(4),
         P("recovery", "Recovery", 0.4, "market", minimum=0.0, maximum=0.99),
         P("n_names", "Names in pool", 125, "contract", dtype="int",
           minimum=1, maximum=500),
         _rate("r", "Rate r", 0.08),
         P("buy_protection", "Buy protection", "yes", "contract",
           dtype="choice", choices=["yes", "no"])],
        [E("cds_index", "CDS index (homogeneous pool)")],
        lambda svc, v, snap: svc.price_cds_index(
            _num(v, "notional", 10e6), _num(v, "index_spread", .011),
            _num(v, "coupon", .01), _num(v, "T", 5), int(_num(v, "freq", 4)),
            _num(v, "r", .08), _num(v, "recovery", .4),
            int(_num(v, "n_names", 125)),
            v.get("buy_protection", "yes") == "yes", snapshot=snap),
        note="Гомогенный пул, плоский hazard из индекс-спреда (ISDA-стиль); upfront на фикс-купоне. Дисперсия имён/index skew не моделируются."),
    WsProduct(
        "cds_index_option", "CDS Index Option", "credit", "Index",
        [_notional(10e6, "Notional"),
         P("strike_spread", "Strike spread", 0.011, "contract", minimum=1e-8,
           maximum=1.0),
         P("current_spread", "Current index spread", 0.011, "market",
           minimum=1e-8, maximum=1.0),
         P("sigma", "Spread vol", 0.5, "market", minimum=1e-3, maximum=3.0,
           help="лог-нормальная вол спреда (Black)"),
         P("T_opt", "Option expiry", 0.5, "contract", minimum=1e-3, maximum=10.0,
           unit="y"),
         P("T_index", "Index maturity", 5.0, "contract", minimum=0.5,
           maximum=30.0, unit="y"),
         _freq(4), _rate("r", "Rate r", 0.08),
         P("recovery", "Recovery", 0.4, "market", minimum=0.0, maximum=0.99),
         P("option", "Option", "payer", "contract", dtype="choice",
           choices=["payer", "receiver"])],
        [E("cds_index_option", "CDS index option (Black)")],
        lambda svc, v, snap: svc.price_cds_index_option(
            _num(v, "notional", 10e6), _num(v, "strike_spread", .011),
            _num(v, "current_spread", .011), _num(v, "sigma", .5),
            _num(v, "T_opt", .5), _num(v, "T_index", 5), int(_num(v, "freq", 4)),
            _num(v, "r", .08), _num(v, "recovery", .4),
            v.get("option", "payer"), snapshot=snap),
        note="Black на форвардном индекс-спреде с RPV01-нумерером. F≈current (без convexity), FEP не добавляется."),
    WsProduct(
        "asset_swap", "Asset Swap (par-par)", "credit", "Single name",
        [P("face", "Face", 100.0, "contract", minimum=0.0),
         P("coupon", "Bond coupon", 0.08, "contract", minimum=0.0, maximum=2.0),
         _mat(5.0), _freq(2),
         P("market_price", "Bond dirty price", 95.0, "market", minimum=0.0,
           help="рыночная грязная цена бумаги (на номинал face)"),
         _rate("r", "Swap (risk-free) rate r", 0.10)],
        [E("asset_swap", "Asset swap (par-par spread)")],
        lambda svc, v, snap: svc.price_asset_swap(
            _num(v, "face", 100), _num(v, "coupon", .08), _num(v, "T", 5),
            int(_num(v, "freq", 2)), _num(v, "market_price", 95),
            _num(v, "r", .10), snapshot=snap),
        note="Par-par ASW spread = (цена бонда по risk-free кривой − рыночная цена)/(par·аннуитет); headline в bp. Плоская ставка, recovery не входит."),
    WsProduct(
        "cds", "Credit Default Swap", "credit", "Single name",
        [_notional(), P("spread", "Spread", 0.01, "contract", minimum=0.0, maximum=1.0),
         _mat(5.0), _freq(4),
         P("issuer", "Эмитент (hazard из z-спредов)", "", "market", dtype="text",
           help="пусто = движок по своим параметрам; имя эмитента — кривая "
                "дефолтов из z-спредов его облигаций (движок cds_curve)"),
         P("recovery", "Recovery", 0.4, "market", minimum=0.0, maximum=0.99),
         _rate("r", "Rate r", 0.05)],
        [E("cds", params=[P("hazard", "Hazard rate λ", 0.02, "model",
                            minimum=0.0, maximum=2.0)]),
         E("cds_curve", params=[P("hazard_id", "Hazard curve (демо)", "hazard_1t_demo",
                                  "model", dtype="choice",
                                  choices=["hazard_1t_demo", "hazard_hy_demo"])]),
         E("cds_isda", params=[P("coupon", "Fixed coupon", 0.01, "model",
                                 minimum=0.0, maximum=0.1)])],
        _cds,
        note="Поле «Эмитент» строит hazard из реальных z-спредов книги облигаций "
             "+ рейтинг АКРА/Эксперт РА (recovery — baseline-корзина)."),
    WsProduct(
        "risky_bond", "Credit-Risky Bond", "credit", "Single name",
        [P("face", "Face", 1000.0, "contract", minimum=0.0),
         P("coupon", "Coupon", 0.13, "contract", minimum=0.0, maximum=2.0),
         _mat(5.0), _freq(2),
         P("issuer", "Эмитент (hazard из z-спредов)", "", "market", dtype="text",
           help="пусто = демо hazard-кривая; имя эмитента (РЖД, Самолет…) — "
                "кривая дефолтов из z-спредов его облигаций + рейтинг АКРА/Эксперт РА"),
         P("hazard_id", "Hazard curve (демо)", "hazard_1t_demo", "market", dtype="choice",
           choices=["hazard_1t_demo", "hazard_hy_demo"]),
         P("recovery", "Recovery", 0.4, "market", minimum=0.0, maximum=0.99)],
        [E("risky_bond")],
        _risky_bond,
        note="Поле «Эмитент» строит hazard-кривую из реальных z-спредов; "
             "recovery берётся из рейтинговой корзины (baseline)."),
    WsProduct(
        "structural_credit", "Structural Default Model", "credit", "Structural",
        [P("V0", "Firm asset value", 100.0, "market", minimum=0.0),
         P("D", "Debt face", 70.0, "contract", minimum=0.0),
         _mat(), _rate("r", "Rate r", 0.05),
         P("sigma_V", "Asset vol σ_V", 0.25, "market", minimum=1e-3, maximum=3.0)],
        [E("merton_structural"),
         E("black_cox", params=[P("barrier", "Default barrier", 60.0, "model",
                                  minimum=0.0)]),
         E("kmv", params=[
             P("V0", "Observable equity value", 100.0, "market", minimum=0.0),
             P("sigma_V", "Observable equity vol σ_E", 0.25, "market",
               minimum=1e-3, maximum=3.0)])],
        _structural,
        note="Equity = колл на активы; PD, distance-to-default, кредитный спред."),
    WsProduct(
        "cdo_tranche", "CDO Tranche", "credit", "Portfolio",
        [P("pds", "PDs (list)", "0.02,0.03,0.04,0.02,0.05,0.03,0.04,0.02,0.03,0.04",
           "contract", dtype="schedule", help="дефолтные вероятности имён через запятую"),
         P("rho", "Default corr ρ", 0.3, "model", minimum=0.0, maximum=0.999),
         P("K1", "Attachment", 0.03, "contract", minimum=0.0, maximum=1.0),
         P("K2", "Detachment", 0.07, "contract", minimum=0.0, maximum=1.0),
         P("recovery", "Recovery", 0.4, "market", minimum=0.0, maximum=0.99)],
        [E("gaussian_copula")],
        lambda svc, v, snap: svc.price_cdo_tranche(
            _floats(v.get("pds", "0.02,0.03")), _num(v, "rho", .3), _num(v, "K1", .03),
            _num(v, "K2", .07), _num(v, "recovery", .4), snapshot=snap)),
    WsProduct(
        "kth_to_default", "Kth-to-Default Basket", "credit", "Portfolio",
        [P("pds", "PDs (list)", "0.02,0.03,0.04,0.02,0.05", "contract", dtype="schedule"),
         P("k", "k (номер дефолта)", 1, "contract", dtype="int", minimum=1, maximum=20),
         P("rho", "Default corr ρ", 0.3, "model", minimum=0.0, maximum=0.999),
         P("recovery", "Recovery", 0.4, "market", minimum=0.0, maximum=0.99)],
        [E("gaussian_copula"),
         E("t_copula", params=[
             P("df", "Degrees of freedom", 5, "model", dtype="int", minimum=2, maximum=100),
             P("n_sims", "MC paths", 100000, "numerical", dtype="int",
               minimum=10000, maximum=1000000)]),
         E("clayton_copula", params=[
             P("theta", "Clayton θ", 1.0, "model", minimum=0.01, maximum=20.0),
             P("n_sims", "MC paths", 100000, "numerical", dtype="int",
               minimum=10000, maximum=1000000)])],
        _basket_default),

    # ═══ COMMODITY ══════════════════════════════════════════════════
    WsProduct(
        "commodity_option", "Commodity Futures Option", "commodity", "Options",
        [P("spot", "Spot", 100.0, "market", minimum=0.0),
         _strike(), P("T_option", "Option expiry", 1.0, "contract", minimum=0.02,
                      maximum=30.0, unit="y"),
         P("T_future", "Futures expiry", 1.25, "contract", minimum=0.02, maximum=30.0,
           unit="y"),
         _rate("r", "Rate r", 0.05),
         P("kappa", "Mean reversion κ", 1.0, "model", minimum=1e-2, maximum=10.0),
         P("rho", "Factor corr ρ", 0.3, "model", minimum=-0.999, maximum=0.999),
         _optype()],
        [E("schwartz_smith", params=[p for p in engine_params("schwartz_smith")
                                     if p.key not in ("kappa", "rho")]),
         E("gibson_schwartz", params=[p for p in engine_params("gibson_schwartz")
                                      if p.key not in ("kappa", "rho")])],
        _commodity_option,
        underlying={"categories": ["commodities", "futures"],
                    "fill": {"spot": "spot", "T_future": "expiry_T"}}),
    WsProduct(
        "commodity_curve", "Commodity Futures Curve", "commodity", "Curves",
        [P("spot", "Spot", 100.0, "market", minimum=0.0),
         P("tenors", "Tenors (y)", "0.25,0.5,1,2,3,5", "contract", dtype="schedule"),
         _rate("r", "Rate r", 0.05),
         P("kappa", "Mean reversion κ", 1.0, "model", minimum=1e-2, maximum=10.0),
         P("rho", "Factor corr ρ", 0.3, "model", minimum=-0.999, maximum=0.999)],
        [E("schwartz_smith", params=[p for p in engine_params("schwartz_smith")
                                     if p.key not in ("kappa", "rho")]),
         E("gibson_schwartz", params=[p for p in engine_params("gibson_schwartz")
                                      if p.key not in ("kappa", "rho")])],
        _commodity_curve,
        underlying={"categories": ["commodities", "futures"], "fill": {"spot": "spot"}},
        note="Термоструктура F(0,T); Samuelson-эффект затухания волатильности."),

    # ═══ INFLATION ══════════════════════════════════════════════════
    WsProduct(
        "zciis", "Inflation Swap (ZC)", "inflation", "Swaps",
        [_notional(), P("K", "Fixed inflation", 0.08, "contract", minimum=-0.2, maximum=1.0),
         _mat(5.0),
         P("side", "Side", "pay fixed", "contract", dtype="choice",
           choices=["pay fixed", "receive fixed"])],
        [E("inflation_swap", "ZCIIS (nominal/real curves)")],
        lambda svc, v, snap: svc.price_zc_inflation_swap(
            _num(v, "notional", 1e6), _num(v, "K", .08), _num(v, "T", 5),
            v.get("side", "pay fixed") == "pay fixed", snapshot=snap),
        note="Fair rate = кривой брейк-ивен (номинальная против реальной OFZ-IN)."),
    WsProduct(
        "yoyiis", "Inflation Swap (YoY)", "inflation", "Swaps",
        [_notional(), P("K", "Fixed inflation", 0.08, "contract", minimum=-0.2, maximum=1.0),
         _mat(5.0), _freq(1),
         P("side", "Side", "pay fixed", "contract", dtype="choice",
           choices=["pay fixed", "receive fixed"])],
        [E("inflation_swap", "YoYIIS (forward breakevens)")],
        lambda svc, v, snap: svc.price_yoy_inflation_swap(
            _num(v, "notional", 1e6), _num(v, "K", .08), _num(v, "T", 5),
            int(_num(v, "freq", 1)), v.get("side", "pay fixed") == "pay fixed",
            snapshot=snap)),

    # ═══ MULTI-ASSET & STRUCTURED ═══════════════════════════════════
    WsProduct(
        "spread_option", "Spread Option", "hybrid", "Multi-asset",
        [P("component_secids", "Component SECIDs", "", "market", dtype="schedule",
           help="два SECID в порядке Spot 1, Spot 2 для granular VaR"),
         P("S1", "Spot 1", 100.0, "market", minimum=0.0),
         P("S2", "Spot 2", 100.0, "market", minimum=0.0),
         P("K", "Strike", 5.0, "contract"),
         _mat(), _rate("r", "Rate r", 0.05),
         P("sigma1", "Vol 1", 0.20, "market", minimum=1e-3, maximum=5.0),
         P("sigma2", "Vol 2", 0.25, "market", minimum=1e-3, maximum=5.0),
         P("rho", "Correlation ρ", 0.4, "market", minimum=-0.999, maximum=0.999),
         P("q1", "Div yield 1", 0.0, "market", minimum=-1.0, maximum=1.0),
         P("q2", "Div yield 2", 0.0, "market", minimum=-1.0, maximum=1.0)],
        [E("spread", "Kirk closed form", model_id="multi_asset"),
         E("adi", model_id="two_asset_adi")],
        _spread,
        underlying={"categories": ["equities", "indices"], "fill": {},
                    "append_to": "component_secids"}),
    WsProduct(
        "two_asset_option", "Two-Asset Option (ADI PDE)", "hybrid", "Multi-asset",
        [P("S1", "Spot 1", 100.0, "market", minimum=0.0),
         P("S2", "Spot 2", 100.0, "market", minimum=0.0),
         P("kind", "Payoff", "exchange", "contract", dtype="choice",
           choices=["exchange", "spread", "basket"]),
         P("K", "Strike", 0.0, "contract"),
         _mat(), _rate("r", "Rate r", 0.05),
         P("q1", "Div yield 1", 0.0, "market", minimum=-1.0, maximum=1.0),
         P("q2", "Div yield 2", 0.0, "market", minimum=-1.0, maximum=1.0),
         P("sigma1", "Vol 1", 0.20, "market", minimum=1e-3, maximum=5.0),
         P("sigma2", "Vol 2", 0.25, "market", minimum=1e-3, maximum=5.0),
         P("rho", "Correlation ρ", 0.4, "market", minimum=-0.999, maximum=0.999)],
        [E("adi", model_id="two_asset_adi")],
        _two_asset),
    WsProduct(
        "basket_option", "Basket Option", "hybrid", "Multi-asset",
        [P("component_secids", "Component SECIDs", "", "market", dtype="schedule",
           help="SECID каждого spot в том же порядке для granular VaR"),
         P("spots", "Spots (list)", "100,100,100", "market", dtype="schedule"),
         P("weights", "Weights (list)", "0.4,0.3,0.3", "contract", dtype="schedule"),
         P("sigmas", "Vols (list)", "0.2,0.25,0.3", "market", dtype="schedule"),
         P("rho", "Pairwise corr ρ", 0.4, "market", minimum=-0.5, maximum=0.999),
         _strike(), _mat(), _rate("r", "Rate r", 0.05), _optype()],
        [E("multi_asset", "MC (Cholesky)")],
        _basket_opt,
        underlying={"categories": ["equities", "indices"], "fill": {},
                    "append_to": "component_secids"}),
    WsProduct(
        "rainbow_option", "Rainbow (Best/Worst-of)", "hybrid", "Multi-asset",
        [P("spots", "Spots (list)", "100,95", "market", dtype="schedule"),
         P("sigmas", "Vols (list)", "0.2,0.3", "market", dtype="schedule"),
         P("rho", "Pairwise corr ρ", 0.3, "market", minimum=-0.5, maximum=0.999),
         P("style", "Payoff", "best_of_cash", "contract", dtype="choice",
           choices=["best_of_cash", "worst_of"]),
         P("cash", "Cash floor", 90.0, "contract", minimum=0.0),
         _mat(), _rate("r", "Rate r", 0.05)],
        [E("multi_asset", "Stulz / MC")],
        _rainbow),
    WsProduct(
        "autocall", "Autocall / Phoenix", "hybrid", "Structured notes",
        [P("S0", "Spot", 100.0, "market", minimum=0.0),
         _rate("r", "Rate r", 0.05), _div(),
         _sigma(), _mat(3.0),
         P("obs_dates", "Observation dates (y)", "1,2,3", "contract", dtype="schedule",
           help="пусто = ежегодно до T"),
         P("autocall_barrier", "Autocall barrier", 1.0, "contract",
           minimum=0.1, maximum=3.0, help="доля от спота"),
         P("coupon_barrier", "Coupon barrier", 0.70, "contract", minimum=0.1, maximum=3.0),
         P("ki_barrier", "Knock-in barrier", 0.65, "contract", minimum=0.1, maximum=3.0),
         P("coupon_rate", "Coupon rate", 0.10, "contract", minimum=0.0, maximum=2.0),
         P("memory_coupon", "Coupon memory", "yes", "contract", dtype="choice",
           choices=["yes", "no"]),
         P("n_sims", "MC paths", 20000, "numerical", dtype="int",
           minimum=2000, maximum=500000),
         P("steps", "Time steps", 100, "numerical", dtype="int", minimum=20, maximum=2000)],
        [E("structured_autocall", "GBM path MC")],
        _autocall, underlying=dict(_EQ_UNDERLYING, fill={"S0": "spot", "sigma": "vol"})),
    WsProduct(
        "basket_note", "Basket Note (real underlyings)", "hybrid", "Structured notes",
        [P("basket", "Basket SECID:weight", "SBER:0.4, GAZP:0.3, LKOH:0.3", "contract",
           dtype="schedule", help="реальные бумаги из маркет даты"),
         _rate("r", "Rate r", 0.16), _mat(3.0),
         P("principal_protection", "Principal protection", 1.0, "contract",
           minimum=0.0, maximum=1.0),
         P("guaranteed_coupon", "Guaranteed coupon", 0.0, "contract",
           minimum=0.0, maximum=1.0),
         P("coupon_freq", "Coupon freq /y", 1, "contract", dtype="int",
           minimum=1, maximum=12),
         P("participation", "Participation", 1.0, "contract", minimum=0.0, maximum=5.0),
         P("cap", "Upside cap (0=none)", 0.0, "contract", minimum=0.0, maximum=10.0),
         P("basket_type", "Basket type", "average", "contract", dtype="choice",
           choices=["average", "worst_of", "best_of"]),
         P("face", "Face", 1000.0, "contract", minimum=0.0),
         P("n_sims", "MC paths", 20000, "numerical", dtype="int",
           minimum=2000, maximum=200000)],
        [E("structured_basket_note", "Correlated GBM on market store")],
        _basket_note,
        underlying={"categories": ["equities", "indices"], "fill": {},
                    "append_to": "basket"},
        note="Спот/волатильность/дивиденды/корреляции берутся из накопленного стора."),
    WsProduct(
        "tarn", "TARN", "hybrid", "Structured notes",
        [P("S0", "Spot", 100.0, "market", minimum=0.0), _strike(),
         _mat(3.0), _freq(4), _rate("r", "Rate r", 0.05), _sigma(), _div(),
         P("target", "Cumulative target", 0.15, "contract", minimum=0.0, maximum=5.0),
         P("n_sims", "MC paths", 50000, "numerical", dtype="int",
           minimum=5000, maximum=500000)],
        [E("tarn", "GBM path MC")],
        lambda svc, v, snap: svc.price_tarn(
            _num(v, "S0", 100), _num(v, "K", 100), _num(v, "T", 3),
            int(_num(v, "freq", 4)), _num(v, "r", .05), _num(v, "sigma", .2),
            _num(v, "target", .15), _num(v, "q", 0),
            int(_num(v, "n_sims", 50000)), snapshot=snap),
        underlying=dict(_EQ_UNDERLYING, fill={"S0": "spot", "sigma": "vol"})),
    WsProduct(
        "accumulator", "Accumulator", "hybrid", "Structured notes",
        [P("S0", "Spot", 100.0, "market", minimum=0.0),
         P("K", "Purchase strike", 95.0, "contract", minimum=0.0),
         P("barrier", "Knock-out barrier", 110.0, "contract", minimum=0.0),
         _mat(), _freq(12), _rate("r", "Rate r", 0.05), _sigma(), _div(),
         P("qty", "Qty per fixing", 1.0, "contract", minimum=0.0),
         P("n_sims", "MC paths", 50000, "numerical", dtype="int",
           minimum=5000, maximum=500000)],
        [E("accumulator", "GBM path MC")],
        lambda svc, v, snap: svc.price_accumulator(
            _num(v, "S0", 100), _num(v, "K", 95), _num(v, "barrier", 110),
            _num(v, "T", 1), int(_num(v, "freq", 12)), _num(v, "r", .05),
            _num(v, "sigma", .2), _num(v, "q", 0), _num(v, "qty", 1),
            int(_num(v, "n_sims", 50000)), snapshot=snap),
        underlying=dict(_EQ_UNDERLYING, fill={"S0": "spot", "sigma": "vol"})),
    WsProduct(
        "convertible", "Convertible Bond", "hybrid", "Hybrid credit",
        [_spot("Stock spot", 100.0), _sigma(0.30, "Equity vol σ"), _div(),
         P("face", "Face", 1000.0, "contract", minimum=0.0),
         P("coupon", "Coupon", 0.05, "contract", minimum=0.0, maximum=2.0),
         _freq(2), _mat(5.0),
         P("conv_ratio", "Conversion ratio", 10.0, "contract", minimum=0.0),
         _rate("r", "Rate r", 0.10)],
        [E("convertible_bond", "Tsiveriotis-Fernandes", params=[
             P("credit_spread", "Credit spread", 0.02, "model", minimum=0.0, maximum=1.0),
             P("N", "Tree steps", 400, "numerical", dtype="int",
               minimum=50, maximum=2000)]),
         E("afv_convertible")],
        _convertible, needs_curve=True,
        underlying=dict(_EQ_UNDERLYING, fill={"S": "spot", "sigma": "vol",
                                              "q": "div_yield"})),
]

_BY_ID = {p.id: p for p in PRODUCTS}


def find_product(product_id: str) -> WsProduct | None:
    return _BY_ID.get(product_id)


# ── serialization ────────────────────────────────────────────────────
def _spec_dict(s: ParameterSpec) -> dict:
    return {
        "key": s.key, "label": s.label, "default": s.default, "group": s.group,
        "dtype": s.dtype, "choices": s.choices, "minimum": s.minimum,
        "maximum": s.maximum, "advanced": s.advanced, "unit": s.unit, "help": s.help,
    }


def _governance(model_id: str) -> dict:
    e = registry.get(model_id)
    status = e.get("status")
    return {
        "status": status.value if hasattr(status, "value") else str(status),
        "canonical_component_id": e.get("canonical_component_id", model_id),
        "requested_component_id": e.get("requested_component_id", model_id),
        "deprecated_alias": bool(e.get("deprecated_alias", False)),
        "component_kind": e.get("component_kind") or "",
        "q_level": e.get("q_level") or "",
        "implementation_scope": e.get("implementation_scope") or "",
        "asset_class": e.get("asset_class") or "",
        "model_family": e.get("model_family") or "",
        "method": e.get("method") or "",
        "notes": e.get("notes", ""),
        "production_allowed": bool(e.get("production_allowed", False)),
        "analytics_lab_only": bool(e.get("analytics_lab_only", False)),
    }


def _engine_eligibility(product: WsProduct, engine: Engine,
                        params: dict | None = None):
    dependencies = []
    if product.needs_curve:
        dependencies.append("discount_curve")
    if product.needs_proj:
        dependencies.append("projection_curve")
    if product.vol_surfaces:
        dependencies.append("volatility_surface_or_manual_vol")
    if product.underlying:
        dependencies.append("underlying_market_facts")
    features = (product.group, product.note) if product.note else (product.group,)
    return build_engine_eligibility(
        product_id=product.id,
        selector_id=engine.id,
        implementation_component_id=engine.model_id,
        params=params,
        required_market_dependencies=dependencies,
        supported_product_features=features,
    )


def _eligibility_dict(eligibility) -> dict:
    approval_active = approval_is_active(eligibility)
    return {
        "eligibility_id": eligibility.engine_id,
        "eligibility_version": eligibility.version,
        "product_definition_id": eligibility.product_definition_id,
        "selector_id": eligibility.selector_id,
        "implementation_component_id": eligibility.implementation_component_id,
        "model_definition_id": eligibility.model_ref.definition_id,
        "model_definition_version": eligibility.model_ref.version,
        "solver_definition_id": eligibility.solver_ref.definition_id,
        "solver_definition_version": eligibility.solver_ref.version,
        "pricer_component_id": eligibility.pricer_component_id,
        "parameterization_component_id": eligibility.parameterization_component_id,
        "runtime_variant": eligibility.runtime_variant,
        "status": eligibility.eligibility_status,
        "production_allowed": eligibility.production_allowed,
        "approval_basis": eligibility.approval_basis,
        "approval_ref": eligibility.approval_ref,
        "approval_expires_on": (
            eligibility.approval_expires_on.isoformat()
            if eligibility.approval_expires_on else ""
        ),
        "approval_active": approval_active,
        "effective_production_allowed": effective_production_allowed(eligibility),
        "fallback_policy": eligibility.fallback_policy,
        "workflow_layer": eligibility.workflow_layer,
    }


def _engine_eligibility_variants(product: WsProduct, engine: Engine) -> list[dict]:
    """Publish every governance-relevant runtime variant of a selector."""
    if engine.id == "carr_madan":
        return [
            _eligibility_dict(_engine_eligibility(
                product, engine, {"cf_model": runtime_variant}
            ))
            for runtime_variant in ("bsm", "heston")
        ]
    return [_eligibility_dict(_engine_eligibility(product, engine))]


def _engine_governance(product: WsProduct, engine: Engine) -> dict:
    """Compatibility governance view with engine-owned production approval."""
    governance = _governance(engine.model_id)
    eligibility = _engine_eligibility(product, engine)
    governance["component_production_allowed_legacy"] = governance[
        "production_allowed"
    ]
    governance["production_allowed"] = eligibility.production_allowed
    return governance


def build_ws_catalogue(curve_ids: list[str] | None = None,
                       surface_ids: list[str] | None = None) -> dict:
    """The full workstation catalogue: asset classes -> products -> engines."""
    curve_ids = curve_ids or []
    surface_ids = surface_ids or []
    products = []
    for p in PRODUCTS:
        products.append({
            "id": p.id,
            "name": p.name,
            "asset_class": p.asset_class,
            "group": p.group,
            "note": p.note,
            "capturable": p.id in TO_POSITION,
            "underlying": p.underlying,
            "engines": [
                {
                    "id": e.id,
                    "model_id": e.model_id,
                    "name": e.name,
                    "governance": _engine_governance(p, e),
                    "eligibility": _eligibility_dict(_engine_eligibility(p, e)),
                    "eligibility_variants": _engine_eligibility_variants(p, e),
                    "params": [_spec_dict(s)
                               for s in p.params_for(e, curve_ids, surface_ids)],
                }
                for e in p.engines
            ],
        })
    return {
        "asset_classes": [{"id": ac, "label": label} for ac, label in ASSET_CLASSES],
        "curves": [{"id": c, "label": CURVE_LABELS.get(c, c)} for c in curve_ids],
        "products": products,
        # A5: глобальные конвенции воркстейшена — то, что раньше жило неявно
        "conventions": [
            "Сроки T — в годах, ACT/365 (T = календарные дни / 365).",
            "Ставки r и дивидендные доходности q — непрерывное начисление; "
            "купоны облигаций и фиксированные ноги — простые периодические "
            "выплаты face·c/freq, дисконтируемые по непрерывной ставке.",
            "Дивиденды акций — непрерывная дивидендная доходность q.",
            "MC-движки используют фиксированный seed — результат воспроизводим; "
            "stderr в результате — оценка MC-погрешности.",
            "FD-грики портфеля: bump 1% спота, 1 в.п. вола, 1 б.п. ставки.",
            "Кривые из снапшота маркет-даты последнего торгового дня; "
            "'— флэт r —' — плоская кривая из поля r.",
            "Vol surface — калиброванный SABR-смайл по IV опционов MOEX; "
            "'— ручная σ —' — поле σ.",
        ],
    }


# ── result normalization ─────────────────────────────────────────────
_GREEK_KEYS = ["delta", "gamma", "vega", "theta", "rho", "vanna", "volga", "charm",
               "dv01", "cs01", "stderr", "std_error"]

_MEASURE_LABELS = {
    "price": "Price", "npv": "NPV", "value": "Value", "fair_rate": "Fair rate",
    "fair_spread": "Fair spread", "fair_strike": "Fair strike",
    "variance_strike": "Variance strike", "vol_strike": "Vol strike",
    "forward": "Forward", "forward_rate": "Forward rate", "fixed_leg": "Fixed leg",
    "float_leg": "Float leg", "premium_leg": "Premium leg",
    "protection_leg": "Protection leg", "upfront": "Upfront",
    "par_spread": "Par spread", "hazard": "Hazard λ", "pd": "PD",
    "survival": "Survival", "expected_loss": "Expected loss",
    "distance_to_default": "Distance to default", "edf": "EDF",
    "credit_spread": "Credit spread", "equity": "Equity value",
    "debt": "Debt value", "wal": "WAL", "oas": "OAS",
    "conversion_value": "Conversion value", "bond_floor": "Bond floor",
    "option_value": "Option value", "straight_value": "Straight value",
    "annuity": "Annuity", "breakeven": "Breakeven", "zciis_rate": "ZCIIS rate",
    "futures_dv01": "Futures DV01", "hedge_ratio": "Hedge ratio",
    "implied_repo": "Implied repo", "net_basis": "Net basis",
    "invoice_price": "Invoice price", "theoretical_price": "Theoretical price",
    "carry": "Carry", "exercise_probability": "P(exercise)",
    "autocall_probability": "P(autocall)", "ki_probability": "P(knock-in)",
    "expected_life": "Expected life", "convexity_adjustment": "Convexity adj",
    "timing_adjustment": "Timing adj",
}

_SKIP_KEYS = {"model", "model_id", "engine", "errors", "warnings", "vol_surface_id",
              "style", "n_sims", "seed", "inputs"}


def _prettify(key: str) -> str:
    if key in _MEASURE_LABELS:
        return _MEASURE_LABELS[key]
    return key.replace("_", " ").strip().capitalize()


def normalize_ws_result(result: dict, input_keys: set[str] | None = None) -> dict:
    """Flatten a governed pricing result into one client-renderable shape:
    headline value + greeks + scalar measures + chartable series. Raw keys that
    merely echo request inputs (model params) are dropped from the measures."""
    raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
    if not raw and "curve" in result:               # bare engine dicts (futures strips)
        raw = {"curve": result["curve"]}

    greeks, measures, series = [], [], []
    value = result.get("value")
    skip = _SKIP_KEYS | (input_keys or set())

    for key, val in raw.items():
        if key in skip:
            continue
        if isinstance(val, bool):
            measures.append({"key": key, "label": _prettify(key),
                             "value": 1.0 if val else 0.0, "kind": "flag"})
        elif isinstance(val, (int, float)):
            entry = {"key": key, "label": _prettify(key), "value": float(val)}
            if key in ("price", "npv", "value") and value is not None:
                continue                          # already the headline
            if key.lower() in _GREEK_KEYS:
                greeks.append(entry)
            else:
                measures.append(entry)
        elif isinstance(val, (list, tuple)) and val:
            pts = _series_points(val)
            if pts:
                series.append({"key": key, "label": _prettify(key), "points": pts})
        elif isinstance(val, dict) and val:
            items = list(val.items())
            numeric_map = all(isinstance(v2, (int, float)) for _, v2 in items)
            if numeric_map and all(_is_num_key(k2) for k2, _ in items):
                # {tenor: value} maps (commodity futures strip) -> chart series
                pts = sorted(({"x": float(k2), "y": float(v2)} for k2, v2 in items),
                             key=lambda p: p["x"])
                series.append({"key": key, "label": _prettify(key), "points": pts})
            else:
                # nested greek blocks {delta: .., gamma: ..} or measure dicts
                for k2, v2 in items:
                    if isinstance(v2, (int, float)):
                        name = str(k2)
                        entry = {"key": f"{key}.{name}", "label": _prettify(name),
                                 "value": float(v2)}
                        (greeks if name.lower() in _GREEK_KEYS else measures).append(entry)

    model_status = result.get("model_status")
    return {
        "value": value,
        "model_id": result.get("model_id", ""),
        "model_status": getattr(model_status, "value", model_status) or "",
        "eligibility_id": str(result.get("engine_eligibility_id") or ""),
        "eligibility_version": str(result.get("engine_eligibility_version") or ""),
        "model_definition_id": str(result.get("model_definition_id") or ""),
        "model_definition_version": str(result.get("model_definition_version") or ""),
        "solver_definition_id": str(result.get("solver_definition_id") or ""),
        "solver_definition_version": str(result.get("solver_definition_version") or ""),
        "pricer_component_id": result.get("pricer_component_id"),
        "runtime_variant": str(result.get("engine_runtime_variant") or "default"),
        "effective_production_allowed": bool(result.get(
            "engine_effective_production_allowed",
            result.get("engine_production_allowed", False),
        )),
        "greeks": greeks,
        "measures": measures,
        "series": series,
        "warnings": list(result.get("warnings") or []),
        "errors": list(result.get("errors") or []),
        "limitations": list(result.get("model_limitations") or []),
        # Immutable-evidence passthrough (spec §10.3): PricingService already
        # produces this per calculation; expose it instead of stripping it.
        "provenance": {
            "calculation_id": str(result.get("calculation_id") or ""),
            "inputs_hash": str(result.get("inputs_hash") or ""),
            "snapshot_id": str(result.get("market_data_snapshot_id") or ""),
            "market_data_source": str(result.get("market_data_source") or ""),
            "market_data_quality": str(result.get("market_data_quality") or ""),
            "model_version": str(result.get("model_version") or ""),
            "model_owner": str(result.get("model_owner") or ""),
            "model_validation_date": str(result.get("model_validation_date") or ""),
            "eligibility_id": str(result.get("engine_eligibility_id") or ""),
            "eligibility_version": str(result.get("engine_eligibility_version") or ""),
            "model_definition_id": str(result.get("model_definition_id") or ""),
            "model_definition_version": str(result.get("model_definition_version") or ""),
            "solver_definition_id": str(result.get("solver_definition_id") or ""),
            "solver_definition_version": str(result.get("solver_definition_version") or ""),
            "implementation_component_id": str(
                result.get("implementation_component_id") or result.get("model_id") or ""
            ),
            "requested_engine_selector": str(
                result.get("requested_engine_selector") or ""
            ),
            "runtime_variant": str(result.get("engine_runtime_variant") or "default"),
            "production_allowed": bool(result.get(
                "engine_effective_production_allowed",
                result.get(
                    "engine_production_allowed",
                    result.get("model_production_allowed", False),
                ),
            )),
            "declared_production_allowed": bool(result.get(
                "engine_production_allowed",
                result.get("model_production_allowed", False),
            )),
            "approval_expires_on": str(
                result.get("engine_approval_expires_on") or ""
            ),
            "valuation_time": str(result.get("calculation_timestamp") or ""),
        },
    }


def _is_num_key(key) -> bool:
    try:
        float(key)
        return True
    except (TypeError, ValueError):
        return False


def _series_points(val) -> list[dict]:
    """Coerce list-shaped raw values into [{x, y}] chart points."""
    pts = []
    for item in val:
        if isinstance(item, dict):
            x = item.get("t", item.get("T", item.get("tenor", item.get("time"))))
            y = item.get("amount", item.get("F", item.get("value",
                        item.get("rate", item.get("epe")))))
            if x is not None and y is not None:
                pts.append({"x": float(x), "y": float(y)})
        elif isinstance(item, (list, tuple)) and len(item) >= 2 and all(
                isinstance(z, (int, float)) for z in item[:2]):
            pts.append({"x": float(item[0]), "y": float(item[1])})
    return pts


_PAYOFF_SPOT_KEY = {p.id: k for p in PRODUCTS
                    for k in ("S", "S0", "spot") if any(s.key == k
                    for s in p.base_params)}


def _derived_effective_params(
    product_id: str, engine_id: str | None, params: dict, *, env=None,
    curve_ids: list[str] | None = None,
    surface_ids: list[str] | None = None,
) -> dict:
    """Materialize environment defaults before constructing shocks/ranges."""
    product = find_product(product_id)
    if product is None:
        raise ValueError(f"unknown product '{product_id}'")
    engine_ids = [item.id for item in product.engines]
    if engine_id is None and env is not None:
        engine_id = (env.pricer_overrides or {}).get(product_id)
    resolved_engine = engine_id or engine_ids[0]
    if resolved_engine not in engine_ids:
        raise ValueError(
            f"unknown engine '{resolved_engine}' for product '{product_id}'"
        )
    engine = next(item for item in product.engines if item.id == resolved_engine)
    allowed_keys = {
        spec.key for spec in product.params_for(
            engine, curve_ids or [], surface_ids or []
        )
    }
    return _effective_ws_params(product, params, env, allowed_keys)


def grid2d_ws(svc, snapshot, product_id: str, engine_id: str | None,
              params: dict, x_key: str, y_key: str,
              x_lo: float, x_hi: float, y_lo: float, y_hi: float,
              nx: int = 9, ny: int = 7, *, env=None,
              curve_ids: list[str] | None = None,
              surface_ids: list[str] | None = None,
              hook=None) -> dict:
    """2-D what-if grid (Desk Risk): full revaluation over a mesh of two
    inputs (обычно spot × vol) — P&L vs the base run per cell.

    `hook(done, total, cell)` runs after each cell; may raise to abort."""
    nx, ny = max(3, min(int(nx), 15)), max(3, min(int(ny), 15))
    params = _derived_effective_params(
        product_id, engine_id, params, env=env,
        curve_ids=curve_ids, surface_ids=surface_ids,
    )
    base = price_ws(
        svc, snapshot, product_id, engine_id, params, env=env,
        curve_ids=curve_ids, surface_ids=surface_ids,
    )
    base_value = base.get("value")
    cells = []
    for j in range(ny):
        y = y_lo + (y_hi - y_lo) * j / (ny - 1)
        for i in range(nx):
            x = x_lo + (x_hi - x_lo) * i / (nx - 1)
            shocked = dict(params)
            shocked[x_key], shocked[y_key] = x, y
            r = price_ws(
                svc, snapshot, product_id, engine_id, shocked, env=env,
                curve_ids=curve_ids, surface_ids=surface_ids,
            )
            value = r.get("value")
            cells.append({
                "x": x, "y": y, "value": value,
                "pnl": (value - base_value)
                       if (value is not None and base_value is not None) else None,
            })
            if hook is not None:
                hook(len(cells), nx * ny, cells[-1])
    return {"product": base["product"], "engine": base["engine"],
            "x_key": x_key, "y_key": y_key, "base_value": base_value,
            "nx": nx, "ny": ny, "cells": cells}


def payoff_ws(svc, snapshot, product_id: str, engine_id: str | None,
              params: dict, steps: int = 41, *, env=None,
              curve_ids: list[str] | None = None,
              surface_ids: list[str] | None = None,
              hook=None) -> dict:
    """Payoff diagram: value profile over spot today (T как есть) и на
    экспирации (T→0, интринсик) — тем же прайсером через ladder.

    `hook(done, total, row)` spans both ladders (total = 2·steps)."""
    spot_key = _PAYOFF_SPOT_KEY.get(product_id)
    if spot_key is None:
        raise ValueError(f"payoff не определён для '{product_id}' (нет спот-входа)")
    params = _derived_effective_params(
        product_id, engine_id, params, env=env,
        curve_ids=curve_ids, surface_ids=surface_ids,
    )
    s0 = float(params.get(spot_key) or 100.0)
    lo, hi = s0 * 0.5, s0 * 1.5

    def _leg_hook(offset):
        if hook is None:
            return None
        return lambda done, total, row: hook(offset + done, 2 * total, row)

    value = ladder_ws(svc, snapshot, product_id, engine_id, params,
                      spot_key, lo, hi, steps, env=env,
                      curve_ids=curve_ids, surface_ids=surface_ids,
                      hook=_leg_hook(0))
    at_expiry = dict(params)
    # Use the published schema floor: small enough to approximate intrinsic
    # value without making the derived request fail its own validation.
    at_expiry["T"] = 1e-4
    payoff = ladder_ws(svc, snapshot, product_id, engine_id, at_expiry,
                       spot_key, lo, hi, steps, env=env,
                       curve_ids=curve_ids, surface_ids=surface_ids,
                       hook=_leg_hook(len(value["rows"])))
    return {
        "product": product_id, "engine": value["engine"], "spot_key": spot_key,
        "spot": s0, "base_value": value["base_value"],
        "value": [{"x": r["x"], "y": r["value"]} for r in value["rows"]
                  if r["value"] is not None],
        "payoff": [{"x": r["x"], "y": r["value"]} for r in payoff["rows"]
                   if r["value"] is not None],
    }


def implied_vol_ws(product_id: str, params: dict, market_price: float) -> dict:
    """Implied vol from a market price: BSM for equity options, GK for FX.
    Only vanilla products carry a single well-defined σ to invert."""
    import math

    from models.implied_vol import implied_vol_bsm, implied_vol_gk

    if product_id == "european_option":
        iv = implied_vol_bsm(market_price, _num(params, "S", 100),
                             _num(params, "K", 100), _num(params, "T", 1),
                             _num(params, "r", .05), _num(params, "q", 0),
                             params.get("opt", "call"))
    elif product_id == "fx_option":
        iv = implied_vol_gk(market_price, _num(params, "S", 90),
                            _num(params, "K", 92), _num(params, "T", 1),
                            _num(params, "r_d", .16), _num(params, "r_f", .05),
                            params.get("opt", "call"))
    else:
        raise ValueError(f"implied vol не поддержан для '{product_id}' "
                         "(только european_option / fx_option)")
    if iv is None or (isinstance(iv, float) and math.isnan(iv)):
        raise ValueError("цена вне арбитражных границ — σ не существует")
    return {"product": product_id, "market_price": market_price,
            "implied_vol": float(iv)}


# Params the client may send that are consumed outside ParameterSpec forms
# (market-identity passthrough for capture/repricing).
_EXTRA_PARAM_KEYS = {"secid"}


def _effective_ws_params(product: WsProduct, params: dict, env=None,
                         allowed_keys: set[str] | None = None) -> dict:
    """Apply environment defaults exactly once for validation and pricing."""
    values = dict(params)
    if env is None:
        return values
    for key, value in (env.default_params or {}).items():
        if allowed_keys is None or key in allowed_keys:
            values.setdefault(key, value)
    if product.needs_curve and not values.get("curve_id"):
        discount_curve = (env.curve_map or {}).get("discount")
        if discount_curve:
            values["curve_id"] = discount_curve
    if product.needs_proj and not values.get("proj_curve_id"):
        projection_curve = (env.curve_map or {}).get("projection")
        if projection_curve:
            values["proj_curve_id"] = projection_curve
    return values


def validate_ws(product_id: str, engine_id: str | None, params: dict,
                curve_ids: list[str] | None = None,
                surface_ids: list[str] | None = None,
                env=None, *,
                allow_analytics_lab: bool = False,
                allow_non_production: bool = False) -> dict:
    """Authoritative request validation (spec §7.5): fail-closed checks of
    product, engine and every parameter against the published schema —
    unknown keys, dtype mismatches, choice membership and numeric ranges.
    Returns structured issues; never prices anything."""
    issues: list[dict] = []

    def issue(code: str, severity: str, message: str, param: str | None = None):
        issues.append({"code": code, "severity": severity,
                       "message": message, "param": param})

    product = find_product(product_id)
    if product is None:
        issue("PRODUCT_UNKNOWN", "error", f"unknown product '{product_id}'")
        return {"valid": False, "issues": issues,
                "product": product_id, "engine": engine_id}

    engine_ids = [e.id for e in product.engines]
    if engine_id is None and env is not None:
        engine_id = (env.pricer_overrides or {}).get(product_id)
    if engine_id is not None and engine_id not in engine_ids:
        issue("ENGINE_UNKNOWN", "error",
              f"unknown engine '{engine_id}' for product '{product_id}'")
        return {"valid": False, "issues": issues,
                "product": product_id, "engine": engine_id}
    resolved_engine = engine_id or engine_ids[0]
    engine = next(e for e in product.engines if e.id == resolved_engine)

    specs = {s.key: s for s in product.params_for(engine, curve_ids or [],
                                                  surface_ids or [])}
    effective_params = _effective_ws_params(product, params, env, set(specs))
    for key, value in effective_params.items():
        spec = specs.get(key)
        if spec is None:
            if key in _EXTRA_PARAM_KEYS:
                continue
            issue("SCHEMA_UNKNOWN_FIELD", "error",
                  f"параметр '{key}' не входит в схему движка "
                  f"'{resolved_engine}'", key)
            continue
        if value is None:
            issue("TERMS_NULL_VALUE", "error",
                  f"параметр '{spec.label}' не задан", key)
            continue
        if spec.dtype in ("float", "int"):
            if isinstance(value, bool) or not isinstance(value, Real):
                issue("SCHEMA_TYPE_MISMATCH", "error",
                      f"'{spec.label}': ожидается число, получено "
                      f"{type(value).__name__}", key)
                continue
            num = float(value)
            if spec.dtype == "int" and num != int(num):
                issue("SCHEMA_TYPE_MISMATCH", "error",
                      f"'{spec.label}': ожидается целое число", key)
            if spec.minimum is not None and num < spec.minimum:
                issue("TERMS_OUT_OF_RANGE", "error",
                      f"'{spec.label}': {num:g} ниже минимума "
                      f"{spec.minimum:g}", key)
            if spec.maximum is not None and num > spec.maximum:
                issue("TERMS_OUT_OF_RANGE", "error",
                      f"'{spec.label}': {num:g} выше максимума "
                      f"{spec.maximum:g}", key)
        elif spec.dtype == "choice":
            allowed = list(spec.choices or [])
            if allowed and str(value) not in allowed:
                issue("TERMS_INVALID_CHOICE", "error",
                      f"'{spec.label}': значение '{value}' не входит в "
                      f"список выбора", key)

    eligibility_payload = None
    try:
        eligibility = _engine_eligibility(product, engine, effective_params)
        eligibility_payload = _eligibility_dict(eligibility)
        for code, message in eligibility_policy_issues(
            eligibility,
            allow_analytics_lab=allow_analytics_lab,
            allow_non_production=allow_non_production,
        ):
            issue(code, "error", message)
    except (KeyError, ValueError) as exc:
        issue("ENGINE_BINDING_INVALID", "error", str(exc))

    errors = [i for i in issues if i["severity"] == "error"]
    return {
        "valid": not errors,
        "issues": issues,
        "product": product_id,
        "engine": resolved_engine,
        "checked_params": sorted(specs.keys()),
        "eligibility": eligibility_payload,
    }


def price_ws(svc, snapshot, product_id: str, engine_id: str | None,
             params: dict, env=None, curve_ids: list[str] | None = None,
             surface_ids: list[str] | None = None) -> dict:
    """Dispatch a workstation pricing request; returns the normalized result.

    ``env`` (PricingEnvironment, A1): контур задаёт ДЕФОЛТЫ — движок
    (pricer_overrides), кривую discount-роли (curve_map) и численные параметры
    (default_params); явные значения запроса всегда побеждают.
    """
    product = find_product(product_id)
    if product is None:
        raise ValueError(f"unknown product '{product_id}'")
    engine_ids = [e.id for e in product.engines]
    if engine_id is None and env is not None:
        engine_id = (env.pricer_overrides or {}).get(product_id)
    # Fail closed (spec §4.2): an unknown engine is an error, never a silent
    # substitution with the default engine.
    if engine_id is not None and engine_id not in engine_ids:
        raise ValueError(
            f"unknown engine '{engine_id}' for product '{product_id}'")
    if curve_ids is None:
        curve_ids = list((getattr(snapshot, "curves", None) or {}).keys())
    if surface_ids is None:
        surface_ids = list((getattr(snapshot, "vol_surfaces", None) or {}).keys())
    validation = validate_ws(
        product_id, engine_id, params,
        curve_ids=curve_ids, surface_ids=surface_ids, env=env,
        allow_analytics_lab=bool(getattr(svc, "allow_analytics_lab", False)),
        allow_non_production=bool(getattr(
            svc, "allow_non_production_models", False
        )))
    if not validation["valid"]:
        messages = [f"{item['code']}: {item['message']}"
                    for item in validation["issues"]
                    if item["severity"] == "error"]
        raise ValueError("invalid pricing request: " + "; ".join(messages))

    values = _effective_ws_params(
        product, params, env, set(validation["checked_params"]))
    values["engine"] = engine_id or engine_ids[0]
    engine = next(item for item in product.engines if item.id == values["engine"])
    eligibility = _engine_eligibility(product, engine, values)
    engine_metadata = {
        "engine_eligibility_id": eligibility.engine_id,
        "engine_eligibility_version": eligibility.version,
        "model_definition_id": eligibility.model_ref.definition_id,
        "model_definition_version": eligibility.model_ref.version,
        "solver_definition_id": eligibility.solver_ref.definition_id,
        "solver_definition_version": eligibility.solver_ref.version,
        "pricer_component_id": eligibility.pricer_component_id,
        "parameterization_component_id": eligibility.parameterization_component_id,
        "implementation_component_id": eligibility.implementation_component_id,
        "requested_engine_selector": eligibility.selector_id,
        "engine_runtime_variant": eligibility.runtime_variant,
        "engine_production_allowed": eligibility.production_allowed,
        "engine_effective_production_allowed": effective_production_allowed(
            eligibility
        ),
        "engine_approval_basis": eligibility.approval_basis,
        "engine_approval_ref": eligibility.approval_ref,
        "engine_approval_expires_on": (
            eligibility.approval_expires_on.isoformat()
            if eligibility.approval_expires_on else ""
        ),
    }
    if hasattr(svc, "engine_context"):
        with svc.engine_context(engine_metadata):
            result = product.invoke(svc, values, snapshot)
    else:
        result = product.invoke(svc, values, snapshot)
    normalized = normalize_ws_result(result if isinstance(result, dict) else {},
                                     input_keys=set(params.keys()))
    normalized["product"] = product_id
    normalized["engine"] = values["engine"]
    if env is not None:
        normalized["environment"] = env.env_id
    return normalized


# ── trade capture: workstation values -> portfolio Position ─────────
# Only products PortfolioService can revalue are capturable. The canonical
# portfolio engine is the product's first/default workstation engine; callers
# that supply a different engine must be rejected instead of silently losing
# the model choice during conversion to Position.
def _n(v, key, default=0.0):
    return _num(v, key, default)


def _fx_pair(v: dict) -> str:
    """Resolve the risk-factor pair from explicit input or selected MOEX id."""
    explicit = v.get("ccy_pair")
    if explicit not in (None, ""):
        return str(explicit)
    secid = str(v.get("secid") or "").strip()
    compact = "".join(ch for ch in secid.upper() if ch.isalnum())
    direct = {
        "USDRUB": "USD/RUB", "EURRUB": "EUR/RUB", "CNYRUB": "CNY/RUB",
        "EURUSD": "EUR/USD",
    }
    for prefix, pair in direct.items():
        if compact.startswith(prefix):  # e.g. EURRUB_TOM / CNYRUBTOD
            return pair
    # FORTS futures: SiU6 / EuU6 / CNYU6 -> strip month and year suffix.
    root = compact[:-2] if (len(compact) >= 3 and compact[-1].isdigit()
                             and compact[-2] in "FGHJKMNQUVXZ") else compact
    return {
        "SI": "USD/RUB", "EU": "EUR/RUB", "CNY": "CNY/RUB",
        "ED": "EUR/USD",
    }.get(root, "USD/RUB")


TO_POSITION: dict[str, Callable[[dict], tuple[str, dict, str]]] = {
    "european_option": lambda v: ("option", {
        "S": _n(v, "S", 100), "K": _n(v, "K", 100), "T": _n(v, "T", 1),
        "r": _n(v, "r", .05), "sigma": _n(v, "sigma", .2), "q": _n(v, "q", 0),
        "opt": v.get("opt", "call")}, "European option"),
    "barrier_option": lambda v: ("barrier", {
        "S": _n(v, "S", 100), "K": _n(v, "K", 100), "H": _n(v, "H", 90),
        "T": _n(v, "T", 1), "r": _n(v, "r", .05), "sigma": _n(v, "sigma", .2),
        "q": _n(v, "q", 0), "opt": v.get("opt", "call"),
        "barrier_type": v.get("barrier_type", "down-out")}, "Barrier option"),
    "asian_option": lambda v: ("asian", {
        "S": _n(v, "S", 100), "K": _n(v, "K", 100), "T": _n(v, "T", 1),
        "r": _n(v, "r", .05), "sigma": _n(v, "sigma", .2), "q": _n(v, "q", 0),
        "opt": v.get("opt", "call"), "averaging": v.get("averaging", "arithmetic"),
        "n": int(_n(v, "n", 12))}, "Asian option"),
    "digital_option": lambda v: ("digital", {
        "S": _n(v, "S", 100), "K": _n(v, "K", 100), "T": _n(v, "T", .5),
        "r": _n(v, "r", .04), "sigma": _n(v, "sigma", .2), "q": _n(v, "q", 0),
        "opt": v.get("opt", "call"), "style": v.get("style", "cash"),
        "cash": _n(v, "cash", 1.0)}, "Digital option"),
    "lookback_option": lambda v: ("lookback", {
        "S": _n(v, "S", 100), "T": _n(v, "T", 1), "r": _n(v, "r", .05),
        "sigma": _n(v, "sigma", .2), "q": _n(v, "q", 0), "opt": v.get("opt", "call"),
        "strike_type": v.get("strike_type", "floating"),
        "K": _n(v, "K", 100)}, "Lookback option"),
    "spread_option": lambda v: ("spread", {
        "S1": _n(v, "S1", 100), "S2": _n(v, "S2", 100), "K": _n(v, "K", 5),
        "T": _n(v, "T", 1), "r": _n(v, "r", .05), "sigma1": _n(v, "sigma1", .2),
        "sigma2": _n(v, "sigma2", .25), "rho": _n(v, "rho", .4),
        "q1": _n(v, "q1", 0), "q2": _n(v, "q2", 0),
        "component_secids": _component_secids(v.get("component_secids"))},
        "Spread option"),
    "basket_option": lambda v: ("basket", {
        "assets": _floats(v.get("spots", "100,100,100")),
        "weights": _floats(v.get("weights", "0.4,0.3,0.3")),
        "K": _n(v, "K", 100), "T": _n(v, "T", 1), "r": _n(v, "r", .05),
        "sigmas": _floats(v.get("sigmas", "0.2,0.25,0.3")),
        "component_secids": _component_secids(v.get("component_secids")),
        "corr": _corr_matrix(_n(v, "rho", .4),
                             len(_floats(v.get("spots", "100,100,100")))),
        "opt": v.get("opt", "call")}, "Basket option"),
    "autocall": lambda v: ("autocall", {
        "S0": _n(v, "S0", 100), "r": _n(v, "r", .05), "q": _n(v, "q", 0),
        "sigma": _n(v, "sigma", .2), "T": _n(v, "T", 3),
        "obs_dates": _floats(v.get("obs_dates", "")) or
                     [float(i) for i in range(1, max(int(round(_n(v, "T", 3))), 1) + 1)],
        "autocall_barrier": _n(v, "autocall_barrier", 1.0),
        "coupon_barrier": _n(v, "coupon_barrier", .7),
        "ki_barrier": _n(v, "ki_barrier", .65),
        "coupon_rate": _n(v, "coupon_rate", .1),
        "n_sims": int(_n(v, "n_sims", 20000))}, "Autocall / Phoenix"),
    "fra": lambda v: ("fra", {
        "notional": _n(v, "notional", 1e6), "K": _n(v, "K", .1),
        "T1": _n(v, "T1", 1), "T2": _n(v, "T2", 1.5), "r": _n(v, "r", .1)}, "FRA"),
    "irs": lambda v: ("irs", {
        "notional": _n(v, "notional", 1e6), "fixed_rate": _n(v, "fixed_rate", .1),
        "T": _n(v, "T", 5), "freq": int(_n(v, "freq", 4)), "r": _n(v, "r", .1),
        "pay_fixed": v.get("side", "pay fixed") == "pay fixed"}, "IRS"),
    "cap_floor": lambda v: ("cap_floor", {
        "notional": _n(v, "notional", 1e6), "K": _n(v, "K", .1), "T": _n(v, "T", 3),
        "freq": int(_n(v, "freq", 2)), "vol": _n(v, "vol", .2), "r": _n(v, "r", .1),
        "opt": v.get("opt", "cap")}, "Cap/Floor"),
    "swaption": lambda v: ("swaption", {
        "notional": _n(v, "notional", 1e6), "K": _n(v, "K", .1),
        "T_option": _n(v, "T_option", 1), "T_swap": _n(v, "T_swap", 5),
        "freq": int(_n(v, "freq", 2)), "sigma": _n(v, "sigma", .2),
        "r": _n(v, "r", .1), "opt": v.get("opt", "payer")}, "European swaption"),
    "stir_future": lambda v: ("stir_future", {
        "forward_rate": _n(v, "forward_rate", .1), "notional": _n(v, "notional", 1e6),
        "tenor": _n(v, "tenor", .25)}, "STIR future"),
    "bond_future": lambda v: ("bond_future", {
        "clean_price": _n(v, "clean_price", 98), "accrued": _n(v, "accrued", 1),
        "conversion_factor": _n(v, "conversion_factor", .9),
        "coupon_income": _n(v, "coupon_income", 0), "ctd_dv01": _n(v, "ctd_dv01", .08),
        "futures_price": _n(v, "futures_price", 108), "repo_rate": _n(v, "repo_rate", .08),
        "T_delivery": _n(v, "T_delivery", .25),
        "target_bpv": _n(v, "target_bpv", 1000)}, "Bond future (CTD)"),
    "cds": lambda v: ("cds", {
        "notional": _n(v, "notional", 1e6), "spread": _n(v, "spread", .01),
        "T": _n(v, "T", 5), "freq": int(_n(v, "freq", 4)),
        "hazard": _n(v, "hazard", .02), "r": _n(v, "r", .05),
        "recovery": _n(v, "recovery", .4)}, "CDS"),
    "fx_forward": lambda v: ("fx_forward", {
        "S": _n(v, "S", 90), "K": _n(v, "forward_agreed", 0) or None,
        "r_d": _n(v, "r_d", .16), "r_f": _n(v, "r_f", .05), "T": _n(v, "T", 1),
        "notional": _n(v, "notional", 1e6),
        "ccy_pair": _fx_pair(v)}, "FX forward"),
}


def portfolio_repricing_engine(product_id: str,
                               engine_id: str | None = None) -> str | None:
    """Resolve and validate the engine reproducible by PortfolioService."""
    if product_id not in TO_POSITION:
        return None
    product = find_product(product_id)
    if product is None or not product.engines:
        raise ValueError(f"no pricing engines configured for '{product_id}'")
    engine_ids = [engine.id for engine in product.engines]
    canonical = engine_ids[0]
    if engine_id is None:
        return canonical
    if engine_id not in engine_ids:
        raise ValueError(f"unknown engine '{engine_id}' for '{product_id}'")
    if engine_id != canonical:
        raise ValueError(
            f"engine '{engine_id}' cannot be reproduced by the canonical "
            f"portfolio repricer for '{product_id}'; use '{canonical}'")
    return canonical


def portfolio_quantity(value) -> float:
    """Validate a capture/what-if quantity before it reaches valuation."""
    if isinstance(value, bool):
        raise ValueError("portfolio quantity must be a finite number")
    try:
        quantity = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("portfolio quantity must be a finite number") from exc
    if not math.isfinite(quantity):
        raise ValueError("portfolio quantity must be a finite number")
    return quantity


def _validate_finite_position_params(value, path: str = "params") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, Real):
        if not math.isfinite(float(value)):
            raise ValueError(f"{path} must be finite")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_position_params(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_finite_position_params(child, f"{path}[{index}]")


def to_position(product_id: str, values: dict,
                engine_id: str | None = None) -> tuple[str, dict, str] | None:
    """Map workstation form values onto a portfolio position; None if the
    product has no portfolio revaluation route yet. When supplied, ``engine``
    is validated against the canonical engine used for portfolio repricing."""
    fn = TO_POSITION.get(product_id)
    if fn is None:
        return None
    portfolio_repricing_engine(product_id, engine_id)
    inst, params, desc = fn(values)
    if inst in ("spread", "basket"):
        expected = 2 if inst == "spread" else len(params.get("assets") or [])
        component_secids = params.get("component_secids") or []
        if component_secids and len(component_secids) != expected:
            raise ValueError(
                f"{product_id} requires {expected} component SECIDs; "
                f"got {len(component_secids)}")
        canonical_secids = [secid.casefold() for secid in component_secids]
        if component_secids and len(set(canonical_secids)) != len(component_secids):
            raise ValueError(
                f"{product_id} component SECIDs must be unique for factor attribution")
        if inst == "basket":
            n_assets = len(params.get("assets") or [])
            if len(params.get("weights") or []) != n_assets:
                raise ValueError("basket assets and weights must have equal length")
            if len(params.get("sigmas") or []) != n_assets:
                raise ValueError("basket assets and sigmas must have equal length")
    # Retain factor identity supplied by underlying selection / what-if input.
    # Without it incremental VaR silently falls back to IMOEX or USD/RUB.
    if values.get("secid") not in (None, ""):
        params["secid"] = str(values["secid"])
    if values.get("ccy_pair") not in (None, ""):
        params["ccy_pair"] = str(values["ccy_pair"])
    # Preserve selected market-data provenance even where the current
    # portfolio repricer intentionally freezes the resolved numeric input.
    # Exact historical curve/surface-node routing is a separate MR-4 step;
    # dropping the identity here would make that step impossible to audit.
    for key, sentinels in {
        "vol_surface_id": {MANUAL_VOL},
        "curve_id": {FLAT_CURVE},
        "proj_curve_id": {PROJ_AS_DISC},
    }.items():
        value = values.get(key)
        if value not in (None, "") and value not in sentinels:
            params[key] = str(value)
    # fx_forward: an unset agreed rate means "strike at today's fair forward"
    if inst == "fx_forward" and params.get("K") is None:
        import math as _math
        params["K"] = params["S"] * _math.exp(
            (params["r_d"] - params["r_f"]) * params["T"])
    _validate_finite_position_params(params)
    return inst, params, desc


# ── desk risk: ladders + scenario simulation (full revaluation) ──────
# The same pricers, the same market data — Calypso's revaluation principle.
_SPOT_KEYS = ("S", "S0", "S1", "S2", "spot", "V0")
_VOL_KEYS = ("sigma", "vol", "sigma1", "sigma2", "sigma_V", "sigma_chi", "atm",
             "sig_atm", "sig_put", "sig_call")
_RATE_KEYS = ("r", "r_d", "forward_rate", "repo_rate", "discount_rate")


def ladder_ws(svc, snapshot, product_id: str, engine_id: str | None, params: dict,
              bump_key: str, lo: float, hi: float, steps: int = 11, *, env=None,
              curve_ids: list[str] | None = None,
              surface_ids: list[str] | None = None,
              hook=None) -> dict:
    """Full-revaluation ladder: reprice the instrument over a grid of one input.
    Returns value + P&L vs the base run per grid point.

    `hook(done, total, row)` is called after each grid point (async job
    progress/partial/cancel — spec §18); it may raise to abort the run."""
    steps = max(2, min(int(steps), 81))
    params = _derived_effective_params(
        product_id, engine_id, params, env=env,
        curve_ids=curve_ids, surface_ids=surface_ids,
    )
    base = price_ws(
        svc, snapshot, product_id, engine_id, params, env=env,
        curve_ids=curve_ids, surface_ids=surface_ids,
    )
    base_value = base.get("value")
    rows = []
    for i in range(steps):
        x = lo + (hi - lo) * i / (steps - 1)
        shocked = dict(params)
        shocked[bump_key] = x
        r = price_ws(
            svc, snapshot, product_id, engine_id, shocked, env=env,
            curve_ids=curve_ids, surface_ids=surface_ids,
        )
        value = r.get("value")
        rows.append({
            "x": x,
            "value": value,
            "pnl": (value - base_value) if (value is not None and base_value is not None)
                   else None,
            "error": (r.get("errors") or [None])[0],
        })
        if hook is not None:
            hook(i + 1, steps, rows[-1])
    return {"product": base["product"], "engine": base["engine"],
            "bump_key": bump_key, "base_value": base_value, "rows": rows}


def _apply_scenario(params: dict, shocks: dict, has_curve: bool) -> dict:
    """Map a named macro scenario (relative spot/vol, absolute rate) onto
    whatever inputs this product actually has."""
    out = dict(params)
    spot_mult = 1.0 + shocks.get("spot", 0.0)
    vol_mult = 1.0 + shocks.get("vol", 0.0)
    rate_add = shocks.get("rate", 0.0)
    for key in _SPOT_KEYS:
        if isinstance(out.get(key), (int, float)):
            out[key] = float(out[key]) * spot_mult
    for key in _VOL_KEYS:
        if isinstance(out.get(key), (int, float)):
            out[key] = max(float(out[key]) * vol_mult, 1e-4)
    for key in _RATE_KEYS:
        if isinstance(out.get(key), (int, float)):
            out[key] = float(out[key]) + rate_add
    # Snapshot-curve pricing ignores the flat r field, so the rate shock must
    # travel through the parallel shift. With the flat-r sentinel the shifted r
    # already builds the shocked curve — adding shift_bps too would double it.
    if has_curve and out.get("curve_id") not in (None, "", FLAT_CURVE):
        out["shift_bps"] = float(out.get("shift_bps") or 0.0) + rate_add * 10000
    return out


def scenarios_ws(svc, snapshot, product_id: str, engine_id: str | None,
                 params: dict, *, env=None,
                 curve_ids: list[str] | None = None,
                 surface_ids: list[str] | None = None,
                 hook=None) -> dict:
    """Run the historical scenario library through the instrument's own pricer
    (full revaluation, not a greek approximation).

    `hook(done, total, row)` runs after each scenario; may raise to abort."""
    from risk.stress import HISTORICAL_SCENARIOS

    product = find_product(product_id)
    if product is None:
        raise ValueError(f"unknown product '{product_id}'")
    params = _derived_effective_params(
        product_id, engine_id, params, env=env,
        curve_ids=curve_ids, surface_ids=surface_ids,
    )
    base = price_ws(
        svc, snapshot, product_id, engine_id, params, env=env,
        curve_ids=curve_ids, surface_ids=surface_ids,
    )
    base_value = base.get("value")
    rows = []
    total = len(HISTORICAL_SCENARIOS)
    for name, shocks in HISTORICAL_SCENARIOS.items():
        shocked = _apply_scenario(params, shocks, product.needs_curve)
        r = price_ws(
            svc, snapshot, product_id, engine_id, shocked, env=env,
            curve_ids=curve_ids, surface_ids=surface_ids,
        )
        value = r.get("value")
        pnl = (value - base_value) if (value is not None and base_value is not None) else None
        rows.append({
            "scenario": name,
            "spot_shock": shocks.get("spot", 0.0),
            "vol_shock": shocks.get("vol", 0.0),
            "rate_shock": shocks.get("rate", 0.0),
            "value": value,
            "pnl": pnl,
            "pnl_pct": (pnl / abs(base_value)) if (pnl is not None and base_value) else None,
            "error": (r.get("errors") or [None])[0],
        })
        if hook is not None:
            hook(len(rows), total, rows[-1])
    return {"product": base["product"], "engine": base["engine"],
            "base_value": base_value, "rows": rows}


# ── Phase 3: model comparison / convergence / solve-for / simulation lab ──

def _engine_param_filter(product: WsProduct, engine: Engine, params: dict,
                         curve_ids, surface_ids) -> dict:
    """Restrict a shared param dict to the keys this engine declares —
    engine-specific numericals of OTHER engines fall back to defaults."""
    specs = product.params_for(engine, curve_ids or [], surface_ids or [])
    allowed = {s.key for s in specs} | _EXTRA_PARAM_KEYS
    return {k: v for k, v in params.items() if k in allowed}


def _measure_value(result: dict, *keys: str):
    for item in result.get("measures") or []:
        if isinstance(item, dict) and item.get("key") in keys:
            return item.get("value")
    return None


def compare_ws(svc, snapshot, product_id: str, reference_engine: str | None,
               params: dict, *, env=None,
               curve_ids: list[str] | None = None,
               surface_ids: list[str] | None = None,
               hook=None) -> dict:
    """Run every engine of the product on ONE frozen context (spec §15).

    The shared intent (contract/market params, environment, snapshot) is
    hashed once; every row carries that same context_hash — the visible
    proof that no engine ran on different inputs. Engine-specific numerical
    params of the currently selected engine are filtered away for engines
    that do not declare them (their own defaults apply).
    """
    import hashlib as _hashlib
    import json as _json
    import time as _time

    product = find_product(product_id)
    if product is None:
        raise ValueError(f"unknown product '{product_id}'")
    engines = list(product.engines)
    engine_ids = [e.id for e in engines]
    ref_id = reference_engine or engine_ids[0]
    if ref_id not in engine_ids:
        raise ValueError(f"unknown engine '{ref_id}' for product '{product_id}'")

    context = {
        "product": product_id,
        "env": getattr(env, "env_id", None) or "",
        "snapshot": str(getattr(snapshot, "snapshot_id", "") or ""),
        "params": {k: params[k] for k in sorted(params)},
    }
    context_hash = _hashlib.sha256(_json.dumps(
        context, sort_keys=True, separators=(",", ":"),
        default=str).encode()).hexdigest()

    rows = []
    for engine in engines:
        gov = _engine_governance(product, engine)
        row = {
            "engine": engine.id, "name": engine.name,
            "model_id": engine.model_id,
            "status": gov.get("status", ""),
            "production_allowed": bool(gov.get("production_allowed", False)),
            "context_hash": context_hash,
            "value": None, "delta": None, "stderr": None,
            "runtime_ms": None, "inputs_hash": "", "snapshot_id": "",
            "error": None,
        }
        filtered = _engine_param_filter(product, engine, params,
                                        curve_ids, surface_ids)
        t0 = _time.perf_counter()
        try:
            result = price_ws(svc, snapshot, product_id, engine.id, filtered,
                              env=env, curve_ids=curve_ids,
                              surface_ids=surface_ids)
        except (KeyError, ValueError, TypeError) as exc:
            row["runtime_ms"] = (_time.perf_counter() - t0) * 1000.0
            row["error"] = str(exc)
        else:
            row["runtime_ms"] = (_time.perf_counter() - t0) * 1000.0
            row["value"] = result.get("value")
            row["stderr"] = _measure_value(result, "stderr", "std_error")
            for greek in result.get("greeks") or []:
                if isinstance(greek, dict) and greek.get("key") == "delta":
                    row["delta"] = greek.get("value")
            prov = result.get("provenance") or {}
            row["inputs_hash"] = prov.get("inputs_hash", "")
            row["snapshot_id"] = prov.get("snapshot_id", "")
            if result.get("errors"):
                row["error"] = result["errors"][0]
        rows.append(row)
        if hook is not None:
            hook(len(rows), len(engines), row)

    ref_value = next((r["value"] for r in rows if r["engine"] == ref_id), None)
    for row in rows:
        ok = row["value"] is not None and ref_value is not None
        row["diff"] = (row["value"] - ref_value) if ok else None
        row["diff_pct"] = ((row["value"] - ref_value) / abs(ref_value)
                           if ok and ref_value else None)
    return {"product": product_id, "reference": ref_id,
            "reference_value": ref_value,
            "context": context, "context_hash": context_hash, "rows": rows}


# Effort knobs recognized for convergence ladders, most specific first.
_EFFORT_KEYS = ("n_sims", "n_paths", "n_z", "n", "steps", "N", "NS", "Nt")


def convergence_ws(svc, snapshot, product_id: str, engine_id: str | None,
                   params: dict, *, levels: list[int] | None = None,
                   env=None, curve_ids: list[str] | None = None,
                   surface_ids: list[str] | None = None,
                   hook=None) -> dict:
    """Reprice the SAME frozen request at increasing numerical effort
    (paths/steps/grid) — estimate, engine stderr and runtime per level;
    the highest level is the reference (spec §14 convergence)."""
    import time as _time

    product = find_product(product_id)
    if product is None:
        raise ValueError(f"unknown product '{product_id}'")
    engine = next((e for e in product.engines
                   if e.id == (engine_id or product.engines[0].id)), None)
    if engine is None:
        raise ValueError(f"unknown engine '{engine_id}' for '{product_id}'")
    specs = {s.key: s for s in product.params_for(
        engine, curve_ids or [], surface_ids or [])}
    effort_key = next((k for k in _EFFORT_KEYS if k in specs), None)
    if effort_key is None:
        raise ValueError(
            f"'{engine.id}' не имеет параметра сходимости (пути/шаги) — "
            "convergence неприменим")
    spec = specs[effort_key]
    base = int(params.get(effort_key) or spec.default or 1000)
    if levels is None:
        levels = [max(int(base * f), 2)
                  for f in (0.0625, 0.125, 0.25, 0.5, 1.0, 2.0)]
    lo_bound = int(spec.minimum) if spec.minimum is not None else 2
    hi_bound = int(spec.maximum) if spec.maximum is not None else None
    clipped = set()
    for level in levels:
        level = max(int(level), lo_bound)
        if hi_bound is not None:
            level = min(level, hi_bound)
        clipped.add(level)
    levels = sorted(clipped)

    rows = []
    for level in levels:
        shocked = dict(params)
        shocked[effort_key] = level
        t0 = _time.perf_counter()
        r = price_ws(svc, snapshot, product_id, engine.id, shocked, env=env,
                     curve_ids=curve_ids, surface_ids=surface_ids)
        rows.append({
            "effort": level,
            "value": r.get("value"),
            "stderr": _measure_value(r, "stderr", "std_error"),
            "runtime_ms": (_time.perf_counter() - t0) * 1000.0,
            "error": (r.get("errors") or [None])[0],
        })
        if hook is not None:
            hook(len(rows), len(levels), rows[-1])

    reference = rows[-1]["value"] if rows else None
    for row in rows:
        ok = row["value"] is not None and reference is not None
        row["error_vs_ref"] = (row["value"] - reference) if ok else None
    return {"product": product_id, "engine": engine.id,
            "effort_key": effort_key, "reference": reference, "rows": rows}


def solve_ws(svc, snapshot, product_id: str, engine_id: str | None,
             params: dict, solve_key: str, target: float,
             lo: float, hi: float, *, tol: float = 1e-9, max_iter: int = 80,
             env=None, curve_ids: list[str] | None = None,
             surface_ids: list[str] | None = None) -> dict:
    """Break-even / solve-for (spec §13.2): bisection on one numeric input so
    that PV equals `target`, always through the real pricer on the frozen
    context. Fails loudly when the bracket does not straddle the target."""
    product = find_product(product_id)
    if product is None:
        raise ValueError(f"unknown product '{product_id}'")
    engine = next((e for e in product.engines
                   if e.id == (engine_id or product.engines[0].id)), None)
    if engine is None:
        raise ValueError(f"unknown engine '{engine_id}' for '{product_id}'")
    specs = {s.key: s for s in product.params_for(
        engine, curve_ids or [], surface_ids or [])}
    if solve_key not in specs or specs[solve_key].dtype not in ("float", "int"):
        raise ValueError(f"'{solve_key}' не числовой параметр движка "
                         f"'{engine.id}' — solve-for неприменим")
    if not lo < hi:
        raise ValueError(f"пустой интервал поиска [{lo}, {hi}]")

    evaluations = 0

    def pv(x: float):
        nonlocal evaluations
        evaluations += 1
        shocked = dict(params)
        shocked[solve_key] = x
        return price_ws(svc, snapshot, product_id, engine.id, shocked,
                        env=env, curve_ids=curve_ids,
                        surface_ids=surface_ids).get("value")

    f_lo, f_hi = pv(lo), pv(hi)
    if f_lo is None or f_hi is None:
        raise ValueError("прайсер не вернул значение на границах интервала")
    g_lo, g_hi = f_lo - target, f_hi - target
    if g_lo == 0.0:
        return {"solve_key": solve_key, "target": target, "root": lo,
                "achieved": f_lo, "residual": 0.0, "iterations": 0,
                "evaluations": evaluations, "engine": engine.id}
    if g_hi == 0.0:
        return {"solve_key": solve_key, "target": target, "root": hi,
                "achieved": f_hi, "residual": 0.0, "iterations": 0,
                "evaluations": evaluations, "engine": engine.id}
    if g_lo * g_hi > 0:
        raise ValueError(
            f"цель {target} вне интервала: PV({lo})={f_lo:.6g}, "
            f"PV({hi})={f_hi:.6g} — нет смены знака, расширь границы")

    a, b, ga = lo, hi, g_lo
    iterations = 0
    mid, achieved = a, f_lo
    for iterations in range(1, max_iter + 1):
        mid = 0.5 * (a + b)
        achieved = pv(mid)
        if achieved is None:
            raise ValueError(f"прайсер не вернул значение в точке {mid}")
        g_mid = achieved - target
        if abs(g_mid) <= tol * (1.0 + abs(target)) or (b - a) <= 1e-12 * (1.0 + abs(mid)):
            break
        if ga * g_mid < 0:
            b = mid
        else:
            a, ga = mid, g_mid
    return {"solve_key": solve_key, "target": target, "root": mid,
            "achieved": achieved, "residual": achieved - target,
            "iterations": iterations, "evaluations": evaluations,
            "engine": engine.id}


def simlab_ws(product_id: str, params: dict, n_paths: int = 2000,
              n_steps: int = 60, seed: int = 42) -> dict:
    """Simulation Lab (spec §14): risk-neutral GBM path fan + terminal and
    payoff distributions with a deterministic seed.

    This is an ILLUSTRATIVE PATH PREVIEW of the underlying under flat
    lognormal dynamics — explicitly not the selected engine's pricing
    simulation; the `nature` field keeps the two from being conflated."""
    import numpy as np

    spot_key = _PAYOFF_SPOT_KEY.get(product_id)
    if spot_key is None:
        raise ValueError(
            f"simulation lab не определён для '{product_id}' (нет спот-входа)")
    s0 = float(params.get(spot_key) or 100.0)
    sigma = float(params.get("sigma") or params.get("vol") or 0.2)
    T = float(params.get("T") or 1.0)
    r = float(params.get("r") if params.get("r") is not None
              else params.get("r_d") or 0.05)
    q = float(params.get("q") if params.get("q") is not None
              else params.get("r_f") or 0.0)
    if s0 <= 0 or sigma <= 0 or T <= 0:
        raise ValueError("нужны положительные спот, вола и срок")
    n_paths = max(200, min(int(n_paths), 20000))
    n_steps = max(10, min(int(n_steps), 250))

    rng = np.random.default_rng(int(seed))
    dt = T / n_steps
    z = rng.standard_normal((n_paths, n_steps))
    increments = (r - q - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * z
    paths = s0 * np.exp(np.hstack([np.zeros((n_paths, 1)),
                                   np.cumsum(increments, axis=1)]))
    times = np.linspace(0.0, T, n_steps + 1)

    fan = [{"p": p, "values": np.percentile(paths, p, axis=0).tolist()}
           for p in (5, 25, 50, 75, 95)]
    sample_paths = paths[:24].tolist()

    terminal = paths[:, -1]
    counts, edges = np.histogram(terminal, bins=40)
    mean = float(terminal.mean())
    std = float(terminal.std(ddof=1))
    centered = terminal - mean
    skew = float((centered ** 3).mean() / std ** 3) if std > 0 else 0.0
    kurtosis = float((centered ** 4).mean() / std ** 4 - 3.0) if std > 0 else 0.0
    percentiles = {str(p): float(np.percentile(terminal, p))
                   for p in (1, 5, 25, 50, 75, 95, 99)}

    payoff_block = None
    strike = params.get("K")
    if strike is not None:
        strike = float(strike)
        opt = str(params.get("opt") or "call")
        intrinsic = (np.maximum(terminal - strike, 0.0) if opt == "call"
                     else np.maximum(strike - terminal, 0.0))
        disc = float(np.exp(-r * T))
        payoff_block = {
            "opt": opt, "strike": strike,
            "mc_price": disc * float(intrinsic.mean()),
            "mc_stderr": disc * float(intrinsic.std(ddof=1)
                                      / np.sqrt(n_paths)),
            "prob_itm": float((intrinsic > 0).mean()),
            "mean_payoff": float(intrinsic.mean()),
        }

    return {
        "nature": "illustrative_path_preview",
        "product": product_id, "seed": int(seed),
        "n_paths": n_paths, "n_steps": n_steps,
        "spot": s0, "sigma": sigma, "T": T, "r": r, "q": q,
        "times": times.tolist(),
        "fan": fan,
        "sample_paths": sample_paths,
        "terminal": {
            "bins": [{"lo": float(edges[i]), "hi": float(edges[i + 1]),
                      "count": int(counts[i])} for i in range(len(counts))],
            "mean": mean, "std": std, "skew": skew, "kurtosis": kurtosis,
            "percentiles": percentiles,
        },
        "payoff": payoff_block,
        "warnings": ["GBM risk-neutral preview — иллюстрация динамики, "
                     "не расчёт выбранного движка"],
    }
