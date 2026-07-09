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
from typing import Callable

from api.instruments import CURVE_LABELS
from models import registry
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
    return P("T", label, default, "contract", minimum=1e-4, maximum=100.0, unit="y")


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
        return svc.price_vanilla_option(
            S, K, T, r, None if use_surface else sig, q, opt, model=analytic[eng],
            snapshot=snapshot, vol_surface_id=surf if use_surface else None)
    if eng == "heston_cf":
        return svc.price_heston_option(S, K, T, r, q, _num(v, "v0", .04), _num(v, "kappa", 1.5),
                                       _num(v, "theta", .04), _num(v, "xi", .5),
                                       _num(v, "rho", -.6), opt, snapshot=snapshot)
    if eng == "bates":
        return svc.price_bates_option(S, K, T, r, q, _num(v, "v0", .04), _num(v, "kappa", 1.5),
                                      _num(v, "theta", .04), _num(v, "xi", .5), _num(v, "rho", -.6),
                                      _num(v, "lam", .3), _num(v, "mu_j", -.1),
                                      _num(v, "delta_j", .15), opt, snapshot=snapshot)
    if eng == "merton_jump":
        return svc.price_merton_option(S, K, T, r, sig, q, _num(v, "lam", .3),
                                       _num(v, "mu_j", -.1), _num(v, "delta_j", .15),
                                       opt, snapshot=snapshot)
    if eng in ("kou", "variance_gamma", "nig", "cgmy"):
        keys = ("lam", "p", "eta1", "eta2", "nu", "theta", "alpha", "beta",
                "delta", "C", "G", "M", "Y", "N")
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
                  "theta": _num(v, "theta", .04), "sigma": _num(v, "xi", .3),
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
        return svc.price_barrier_option_pde(*args, snapshot=snapshot)
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
         E("heston_cf"), E("bates"), E("merton_jump"),
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
         E("heston_adi", "Heston ADI 2-D PDE", model_id="adi", params=[
             P("v0", "Initial variance v0", 0.04, "model", minimum=1e-4, maximum=2.0),
             P("kappa", "Mean reversion κ", 1.5, "model", minimum=1e-3, maximum=20.0),
             P("theta", "Long-run variance θ", 0.04, "model", minimum=1e-4, maximum=2.0),
             P("xi", "Vol of vol ξ", 0.3, "model", minimum=1e-3, maximum=3.0),
             P("rho", "Spot-vol corr ρ", -0.6, "model", minimum=-0.999, maximum=0.999),
             P("NS", "S grid", 160, "numerical", dtype="int", minimum=40, maximum=400),
             P("Nv", "v grid", 80, "numerical", dtype="int", minimum=20, maximum=200),
             P("Nt", "Time steps", 120, "numerical", dtype="int", minimum=20, maximum=1000)]),
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
        _barrier, underlying=_EQ_UNDERLYING),
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
        underlying=_EQ_UNDERLYING),
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
        underlying=_EQ_UNDERLYING),
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
        underlying=_EQ_UNDERLYING),
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

    # ═══ RATES ══════════════════════════════════════════════════════
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
         E("kmv")],
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
        [P("S1", "Spot 1", 100.0, "market", minimum=0.0),
         P("S2", "Spot 2", 100.0, "market", minimum=0.0),
         P("K", "Strike", 5.0, "contract"),
         _mat(), _rate("r", "Rate r", 0.05),
         P("sigma1", "Vol 1", 0.20, "market", minimum=1e-3, maximum=5.0),
         P("sigma2", "Vol 2", 0.25, "market", minimum=1e-3, maximum=5.0),
         P("rho", "Correlation ρ", 0.4, "market", minimum=-0.999, maximum=0.999),
         P("q1", "Div yield 1", 0.0, "market", minimum=-1.0, maximum=1.0),
         P("q2", "Div yield 2", 0.0, "market", minimum=-1.0, maximum=1.0)],
        [E("spread", "Kirk closed form", model_id="multi_asset"),
         E("adi", params=engine_params("adi"))],
        _spread),
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
        [E("adi")],
        _two_asset),
    WsProduct(
        "basket_option", "Basket Option", "hybrid", "Multi-asset",
        [P("spots", "Spots (list)", "100,100,100", "market", dtype="schedule"),
         P("weights", "Weights (list)", "0.4,0.3,0.3", "contract", dtype="schedule"),
         P("sigmas", "Vols (list)", "0.2,0.25,0.3", "market", dtype="schedule"),
         P("rho", "Pairwise corr ρ", 0.4, "market", minimum=-0.5, maximum=0.999),
         _strike(), _mat(), _rate("r", "Rate r", 0.05), _optype()],
        [E("multi_asset", "MC (Cholesky)")],
        _basket_opt),
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
        "asset_class": e.get("asset_class") or "",
        "model_family": e.get("model_family") or "",
        "method": e.get("method") or "",
        "notes": e.get("notes", ""),
        "production_allowed": bool(e.get("production_allowed", False)),
        "analytics_lab_only": bool(e.get("analytics_lab_only", False)),
    }


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
                    "governance": _governance(e.model_id),
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
        "greeks": greeks,
        "measures": measures,
        "series": series,
        "warnings": list(result.get("warnings") or []),
        "errors": list(result.get("errors") or []),
        "limitations": list(result.get("model_limitations") or []),
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


def payoff_ws(svc, snapshot, product_id: str, engine_id: str | None,
              params: dict, steps: int = 41) -> dict:
    """Payoff diagram: value profile over spot today (T как есть) и на
    экспирации (T→0, интринсик) — тем же прайсером через ladder."""
    spot_key = _PAYOFF_SPOT_KEY.get(product_id)
    if spot_key is None:
        raise ValueError(f"payoff не определён для '{product_id}' (нет спот-входа)")
    s0 = float(params.get(spot_key) or 100.0)
    lo, hi = s0 * 0.5, s0 * 1.5

    value = ladder_ws(svc, snapshot, product_id, engine_id, params,
                      spot_key, lo, hi, steps)
    at_expiry = dict(params)
    at_expiry["T"] = 1e-6
    payoff = ladder_ws(svc, snapshot, product_id, engine_id, at_expiry,
                       spot_key, lo, hi, steps)
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


def price_ws(svc, snapshot, product_id: str, engine_id: str | None,
             params: dict) -> dict:
    """Dispatch a workstation pricing request; returns the normalized result."""
    product = find_product(product_id)
    if product is None:
        raise ValueError(f"unknown product '{product_id}'")
    engine_ids = [e.id for e in product.engines]
    values = dict(params)
    values["engine"] = engine_id if engine_id in engine_ids else engine_ids[0]
    result = product.invoke(svc, values, snapshot)
    normalized = normalize_ws_result(result if isinstance(result, dict) else {},
                                     input_keys=set(params.keys()))
    normalized["product"] = product_id
    normalized["engine"] = values["engine"]
    return normalized


# ── trade capture: workstation values -> portfolio Position ─────────
# Only products PortfolioService can revalue are capturable; engine-specific
# model params are dropped — the book reprices positions with its own default
# engines (the workstation engine choice is a pricing view, not a trade term).
def _n(v, key, default=0.0):
    return _num(v, key, default)


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
        "q1": _n(v, "q1", 0), "q2": _n(v, "q2", 0)}, "Spread option"),
    "basket_option": lambda v: ("basket", {
        "assets": _floats(v.get("spots", "100,100,100")),
        "weights": _floats(v.get("weights", "0.4,0.3,0.3")),
        "K": _n(v, "K", 100), "T": _n(v, "T", 1), "r": _n(v, "r", .05),
        "sigmas": _floats(v.get("sigmas", "0.2,0.25,0.3")),
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
        "ccy_pair": "USD/RUB"}, "FX forward"),
}


def to_position(product_id: str, values: dict) -> tuple[str, dict, str] | None:
    """Map workstation form values onto a portfolio position; None if the
    product has no portfolio revaluation route yet."""
    fn = TO_POSITION.get(product_id)
    if fn is None:
        return None
    inst, params, desc = fn(values)
    # fx_forward: an unset agreed rate means "strike at today's fair forward"
    if inst == "fx_forward" and params.get("K") is None:
        import math as _math
        params["K"] = params["S"] * _math.exp(
            (params["r_d"] - params["r_f"]) * params["T"])
    return inst, params, desc


# ── desk risk: ladders + scenario simulation (full revaluation) ──────
# The same pricers, the same market data — Calypso's revaluation principle.
_SPOT_KEYS = ("S", "S0", "S1", "S2", "spot", "V0")
_VOL_KEYS = ("sigma", "vol", "sigma1", "sigma2", "sigma_V", "sigma_chi", "atm",
             "sig_atm", "sig_put", "sig_call")
_RATE_KEYS = ("r", "r_d", "forward_rate", "repo_rate", "discount_rate")


def ladder_ws(svc, snapshot, product_id: str, engine_id: str | None, params: dict,
              bump_key: str, lo: float, hi: float, steps: int = 11) -> dict:
    """Full-revaluation ladder: reprice the instrument over a grid of one input.
    Returns value + P&L vs the base run per grid point."""
    steps = max(2, min(int(steps), 81))
    base = price_ws(svc, snapshot, product_id, engine_id, params)
    base_value = base.get("value")
    rows = []
    for i in range(steps):
        x = lo + (hi - lo) * i / (steps - 1)
        shocked = dict(params)
        shocked[bump_key] = x
        r = price_ws(svc, snapshot, product_id, engine_id, shocked)
        value = r.get("value")
        rows.append({
            "x": x,
            "value": value,
            "pnl": (value - base_value) if (value is not None and base_value is not None)
                   else None,
            "error": (r.get("errors") or [None])[0],
        })
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
                 params: dict) -> dict:
    """Run the historical scenario library through the instrument's own pricer
    (full revaluation, not a greek approximation)."""
    from risk.stress import HISTORICAL_SCENARIOS

    product = find_product(product_id)
    if product is None:
        raise ValueError(f"unknown product '{product_id}'")
    base = price_ws(svc, snapshot, product_id, engine_id, params)
    base_value = base.get("value")
    rows = []
    for name, shocks in HISTORICAL_SCENARIOS.items():
        shocked = _apply_scenario(params, shocks, product.needs_curve)
        r = price_ws(svc, snapshot, product_id, engine_id, shocked)
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
    return {"product": base["product"], "engine": base["engine"],
            "base_value": base_value, "rows": rows}
