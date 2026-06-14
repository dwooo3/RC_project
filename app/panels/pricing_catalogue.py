"""
Declarative pricing-product catalogue (no Qt).

Each Product knows its input fields, how to price through PricingService, and how
to become a portfolio Position. The 7 Pricing categories are driven entirely by
this list, so adding a product needs no UI code.
"""

from dataclasses import dataclass, field
from typing import Callable

CATEGORIES = ["Fixed Income", "Option", "Equity", "FX", "Swaps", "Structured Notes", "Credit"]


@dataclass
class Field:
    key: str
    label: str
    default: float | str
    choices: list[str] | None = None
    wide: bool = False        # render full-width in the Parameters grid (e.g. schedules)

    @property
    def is_text(self) -> bool:
        return self.choices is not None or isinstance(self.default, str)


@dataclass
class Product:
    id: str
    label: str
    category: str
    fields: list[Field]
    price: Callable          # (PricingService, values) -> governed result dict
    to_position: Callable    # (values) -> (instrument:str, params:dict, description:str)
    curve_roles: list[str] = None   # which curves the UI may select: ["disc"] / ["disc","proj"]
    instrument: str = None   # M0: ENGINES key -> engine dropdown + advanced model/numerical params

    def __post_init__(self):
        if self.curve_roles is None:
            self.curve_roles = []

    def engines(self) -> list[str]:
        """Selectable engine ids for this product (empty if single-engine)."""
        if not self.instrument:
            return []
        from models.taxonomy import engines_for
        return engines_for(self.instrument)


def _disc(s, v):
    """Discount curve: UI-selected snapshot curve, else flat curve from the rate field."""
    return v.get("__disc_curve") or s.market_data.flat_curve(v["r"])


def _proj(v):
    """Projection curve: UI-selected snapshot curve, else None (single-curve)."""
    return v.get("__proj_curve")


# ── field shortcuts ───────────────────────────────────────
def F(key, label, default, choices=None, wide=False):
    return Field(key, label, default, choices, wide)


_OPT = ["call", "put"]
_DC = ["act365", "act360", "30360", "actact"]


def _vanilla_engine(s, v):
    """
    M0 engine-aware vanilla pricer: dispatch on the selected engine, pulling its
    Advanced model/numerical params from `v`. Engines without a service route yet
    return a governed error rather than failing.
    """
    eng = v.get("__engine", "black_scholes")
    S, K, T, r, sig = v["S"], v["K"], v["T"], v["r"], v["sigma"]
    q, opt = v.get("q", 0.0), v.get("opt", "call")
    analytic = {"black_scholes": "bsm", "binomial_crr": "binomial",
                "binomial_lr": "binomial_lr", "trinomial": "trinomial",
                "pde_cn": "pde", "mc_gbm": "mc"}
    if eng in analytic:
        return s.price_vanilla_option(S, K, T, r, sig, q, opt, model=analytic[eng])
    if eng == "merton_jump":
        return s.price_merton_option(S, K, T, r, sig, q, v.get("lam", 0.3),
                                     v.get("mu_j", -0.1), v.get("delta_j", 0.15), opt)
    if eng == "bates":
        return s.price_bates_option(S, K, T, r, q, v.get("v0", 0.04),
                                    v.get("kappa", 1.5), v.get("theta", 0.04),
                                    v.get("xi", 0.5), v.get("rho", -0.6),
                                    v.get("lam", 0.3), v.get("mu_j", -0.1),
                                    v.get("delta_j", 0.15), opt)
    if eng == "heston_cf":
        return s.price_heston_option(S, K, T, r, q, v.get("v0", 0.04),
                                     v.get("kappa", 1.5), v.get("theta", 0.04),
                                     v.get("xi", 0.5), v.get("rho", -0.6), opt)
    if eng in ("kou", "variance_gamma", "nig", "cgmy", "merton_cos"):
        params = {k: v[k] for k in ("lam", "p", "eta1", "eta2", "nu", "theta",
                                    "alpha", "beta", "delta", "C", "G", "M", "Y",
                                    "mu_j", "delta_j", "N") if k in v}
        return s.price_levy_option(eng, S, K, T, r, sig, q, opt, **params)
    if eng == "rough_bergomi":
        return s.price_rough_bergomi_option(S, K, T, r, q, v.get("H", 0.1),
                                            v.get("eta", 1.5), v.get("rho", -0.7),
                                            v.get("xi0", sig**2), opt,
                                            int(v.get("n_paths", 40000)),
                                            int(v.get("steps", 100)))
    # unrecognised / not yet wired -> governed error
    return s.price_vanilla_option(S, K, T, r, sig, q, opt, model="bsm")


def parse_cashflows(text) -> list:
    """Parse a manual schedule 't:amount,t:amount' into [(t, amount), ...]."""
    if isinstance(text, (list, tuple)):
        return [(float(t), float(a)) for t, a in text]
    out = []
    for part in str(text).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        t, a = part.split(":")
        out.append((float(t), float(a)))
    return out

PRODUCTS: list[Product] = [
    # ── Fixed Income ──────────────────────────────────────
    Product("bond", "Bond / OFZ", "Fixed Income",
            [F("face", "Face", 1000), F("coupon", "Coupon", 0.07), F("T", "Maturity (y)", 10),
             F("freq", "Freq/y", 2), F("r", "Flat rate", 0.12),
             F("day_count", "Day count", "act365", _DC)],
            lambda s, v: s.price_bond(v["face"], v["coupon"], v["T"], int(v["freq"]),
                                      curve=_disc(s, v), day_count=v["day_count"]),
            lambda v: ("bond", dict(face=v["face"], coupon=v["coupon"], T=v["T"],
                                    freq=int(v["freq"]), r=v["r"]), "Bond / OFZ")),
    Product("zcb", "Zero-Coupon Bond", "Fixed Income",
            [F("face", "Face", 1000), F("T", "Maturity (y)", 5), F("r", "Flat rate", 0.12)],
            lambda s, v: s.price_bond(v["face"], 0.0, v["T"], 1,
                                      curve=_disc(s, v)),
            lambda v: ("bond", dict(face=v["face"], coupon=0.0, T=v["T"], freq=1, r=v["r"]),
                       "Zero-Coupon Bond")),
    Product("fra", "Forward Rate Agreement", "Fixed Income",
            [F("notional", "Notional", 1_000_000), F("K", "Fixed rate", 0.10),
             F("T1", "Start (y)", 1), F("T2", "End (y)", 1.5), F("r", "Flat rate", 0.10)],
            lambda s, v: s.price_fra(v["notional"], v["K"], v["T1"], v["T2"],
                                     curve=_disc(s, v), proj_curve=_proj(v)),
            lambda v: ("fra", dict(notional=v["notional"], K=v["K"], T1=v["T1"], T2=v["T2"],
                                   r=v["r"]), "FRA")),
    Product("frn", "Floating Rate Note", "Fixed Income",
            [F("face", "Face", 1000), F("spread", "Spread", 0.01), F("T", "Maturity (y)", 5),
             F("freq", "Freq/y", 2), F("r", "Flat rate", 0.12)],
            lambda s, v: s.price_frn(v["face"], v["spread"], v["T"], int(v["freq"]),
                                     curve=_disc(s, v)),
            lambda v: ("frn", dict(face=v["face"], spread=v["spread"], T=v["T"],
                                   freq=int(v["freq"]), r=v["r"]), "FRN")),
    Product("custom_bond", "Custom Cashflow Bond", "Fixed Income",
            [F("cashflows", "Cashflows t:amt", "1:35,2:35,3:1035", wide=True), F("freq", "Freq/y", 2),
             F("r", "Flat rate", 0.10)],
            lambda s, v: s.price_custom_bond(parse_cashflows(v["cashflows"]), int(v["freq"]),
                                             curve=_disc(s, v)),
            lambda v: ("custom_bond", dict(cashflows=parse_cashflows(v["cashflows"]),
                                           freq=int(v["freq"]), r=v["r"]), "Custom Bond")),
    Product("amortizing", "Amortizing Bond", "Fixed Income",
            [F("face", "Face", 1000), F("coupon", "Coupon", 0.07), F("T", "Maturity (y)", 10),
             F("freq", "Freq/y", 2), F("r", "Flat rate", 0.12),
             F("amort_type", "Amort", "linear", ["linear", "annuity"]),
             F("day_count", "Day count", "act365", _DC)],
            lambda s, v: s.price_amortizing_bond(v["face"], v["coupon"], v["T"], int(v["freq"]),
                                                 v["amort_type"], v["day_count"],
                                                 curve=_disc(s, v)),
            lambda v: ("amortizing", dict(face=v["face"], coupon=v["coupon"], T=v["T"],
                                          freq=int(v["freq"]), r=v["r"], amort_type=v["amort_type"],
                                          day_count=v["day_count"]), "Amortizing Bond")),
    Product("step_bond", "Step-Up / Step-Down Bond", "Fixed Income",
            [F("face", "Face", 1000), F("coupon1", "Coupon 1", 0.05), F("coupon2", "Coupon 2", 0.08),
             F("switch_year", "Switch (y)", 3), F("T", "Maturity (y)", 6), F("freq", "Freq/y", 2),
             F("r", "Flat rate", 0.10), F("day_count", "Day count", "act365", _DC)],
            lambda s, v: s.price_step_bond(v["face"], v["coupon1"], v["coupon2"], v["switch_year"],
                                           v["T"], int(v["freq"]), v["day_count"],
                                           curve=_disc(s, v)),
            lambda v: ("step_bond", dict(face=v["face"], coupon1=v["coupon1"], coupon2=v["coupon2"],
                                         switch_year=v["switch_year"], T=v["T"], freq=int(v["freq"]),
                                         r=v["r"], day_count=v["day_count"]), "Step Bond")),
    Product("perpetual", "Perpetual / Consol", "Fixed Income",
            [F("face", "Face", 1000), F("coupon", "Coupon", 0.08), F("freq", "Freq/y", 1),
             F("r", "Flat rate", 0.09)],
            lambda s, v: s.price_perpetual_bond(v["face"], v["coupon"], int(v["freq"]),
                                                curve=_disc(s, v)),
            lambda v: ("perpetual", dict(face=v["face"], coupon=v["coupon"], freq=int(v["freq"]),
                                         r=v["r"]), "Perpetual")),
    Product("inflation_linked", "Inflation-Linked Bond", "Fixed Income",
            [F("face", "Face", 1000), F("real_coupon", "Real coupon", 0.03), F("T", "Maturity (y)", 10),
             F("freq", "Freq/y", 2), F("base_cpi", "Base CPI", 100), F("current_cpi", "Curr CPI", 110),
             F("inflation_rate", "Inflation", 0.04), F("r", "Flat rate", 0.12),
             F("day_count", "Day count", "act365", _DC)],
            lambda s, v: s.price_inflation_linked_bond(v["face"], v["real_coupon"], v["T"], int(v["freq"]),
                                                       v["base_cpi"], v["current_cpi"], v["inflation_rate"],
                                                       v["day_count"], curve=_disc(s, v)),
            lambda v: ("inflation_linked", dict(face=v["face"], real_coupon=v["real_coupon"], T=v["T"],
                                                freq=int(v["freq"]), base_cpi=v["base_cpi"],
                                                current_cpi=v["current_cpi"],
                                                inflation_rate=v["inflation_rate"], r=v["r"],
                                                day_count=v["day_count"]), "Inflation-Linked Bond")),
    Product("callable", "Callable Bond (OAS)", "Fixed Income",
            [F("face", "Face", 1000), F("coupon", "Coupon", 0.08), F("T", "Maturity (y)", 5),
             F("freq", "Freq/y", 2), F("sigma", "Rate vol", 0.15), F("call_price", "Call price", 1000),
             F("call_start", "Call from (y)", 2), F("r", "Flat rate", 0.07)],
            lambda s, v: s.price_callable_bond(v["face"], v["coupon"], v["T"], int(v["freq"]),
                                               v["sigma"], v["call_price"], v["call_start"],
                                               option="callable", curve=_disc(s, v)),
            lambda v: ("callable", dict(face=v["face"], coupon=v["coupon"], T=v["T"], freq=int(v["freq"]),
                                        sigma=v["sigma"], call_price=v["call_price"],
                                        call_start=v["call_start"], r=v["r"]), "Callable Bond")),
    Product("putable", "Putable Bond (OAS)", "Fixed Income",
            [F("face", "Face", 1000), F("coupon", "Coupon", 0.06), F("T", "Maturity (y)", 5),
             F("freq", "Freq/y", 2), F("sigma", "Rate vol", 0.15), F("put_price", "Put price", 1000),
             F("put_start", "Put from (y)", 2), F("r", "Flat rate", 0.07)],
            lambda s, v: s.price_callable_bond(v["face"], v["coupon"], v["T"], int(v["freq"]),
                                               v["sigma"], put_price=v["put_price"], put_start=v["put_start"],
                                               option="putable", curve=_disc(s, v)),
            lambda v: ("putable", dict(face=v["face"], coupon=v["coupon"], T=v["T"], freq=int(v["freq"]),
                                       sigma=v["sigma"], put_price=v["put_price"],
                                       put_start=v["put_start"], r=v["r"]), "Putable Bond")),
    Product("bond_future", "Bond Future (CTD)", "Fixed Income",
            [F("clean_price", "CTD clean", 98), F("accrued", "Accrued", 1.0),
             F("conversion_factor", "Conv factor", 0.9), F("coupon_income", "Coupon inc", 0.0),
             F("ctd_dv01", "CTD DV01", 0.08), F("futures_price", "Futures px", 108),
             F("repo_rate", "Repo rate", 0.08), F("T_delivery", "Delivery (y)", 0.25),
             F("target_bpv", "Target BPV", 1000)],
            lambda s, v: s.price_bond_future(
                [{"name": "CTD", "clean_price": v["clean_price"], "accrued": v["accrued"],
                  "conversion_factor": v["conversion_factor"], "coupon_income": v["coupon_income"],
                  "dv01": v["ctd_dv01"]}],
                v["futures_price"], v["repo_rate"], v["T_delivery"], v["target_bpv"]),
            lambda v: ("bond_future", dict(clean_price=v["clean_price"], accrued=v["accrued"],
                                           conversion_factor=v["conversion_factor"],
                                           coupon_income=v["coupon_income"], ctd_dv01=v["ctd_dv01"],
                                           futures_price=v["futures_price"], repo_rate=v["repo_rate"],
                                           T_delivery=v["T_delivery"], target_bpv=v["target_bpv"]),
                       "Bond Future")),
    Product("stir_future", "STIR Future", "Fixed Income",
            [F("forward_rate", "Rate", 0.10), F("notional", "Notional", 1_000_000),
             F("tenor", "Tenor (y)", 0.25)],
            lambda s, v: s.price_stir_future(v["forward_rate"], v["notional"], v["tenor"]),
            lambda v: ("stir_future", dict(forward_rate=v["forward_rate"], notional=v["notional"],
                                           tenor=v["tenor"]), "STIR Future")),
    Product("deposit", "Money Market Deposit", "Fixed Income",
            [F("notional", "Notional", 1_000_000), F("rate", "Rate", 0.10),
             F("T", "Tenor (y)", 0.25), F("r", "Flat rate", 0.10)],
            lambda s, v: s.price_deposit(v["notional"], v["rate"], v["T"],
                                         curve=_disc(s, v)),
            lambda v: ("deposit", dict(notional=v["notional"], rate=v["rate"], T=v["T"], r=v["r"]),
                       "MM Deposit")),
    Product("treasury_bill", "Treasury Bill", "Fixed Income",
            [F("face", "Face", 1000), F("discount_rate", "Discount", 0.09), F("T", "Tenor (y)", 0.25)],
            lambda s, v: s.price_treasury_bill(v["face"], v["discount_rate"], v["T"]),
            lambda v: ("treasury_bill", dict(face=v["face"], discount_rate=v["discount_rate"], T=v["T"]),
                       "Treasury Bill")),
    Product("commercial_paper", "Commercial Paper", "Fixed Income",
            [F("face", "Face", 1000), F("discount_rate", "Discount", 0.11), F("T", "Tenor (y)", 0.25)],
            lambda s, v: s.price_commercial_paper(v["face"], v["discount_rate"], v["T"]),
            lambda v: ("commercial_paper", dict(face=v["face"], discount_rate=v["discount_rate"], T=v["T"]),
                       "Commercial Paper")),
    Product("cap_floor", "Cap / Floor", "Option",
            [F("notional", "Notional", 1_000_000), F("K", "Strike", 0.10), F("T", "Maturity (y)", 3),
             F("freq", "Freq/y", 2), F("vol", "Vol", 0.20), F("r", "Flat rate", 0.10),
             F("opt", "Type", "cap", ["cap", "floor"])],
            lambda s, v: s.price_cap_floor(v["notional"], v["K"], v["T"], int(v["freq"]), v["vol"],
                                           v["opt"], curve=_disc(s, v), proj_curve=_proj(v)),
            lambda v: ("cap_floor", dict(notional=v["notional"], K=v["K"], T=v["T"],
                                         freq=int(v["freq"]), vol=v["vol"], r=v["r"], opt=v["opt"]),
                       "Cap/Floor")),

    # ── Option ────────────────────────────────────────────
    Product("vanilla", "Vanilla Option", "Option",
            [F("S", "Spot", 100), F("K", "Strike", 100), F("T", "Maturity (y)", 1),
             F("r", "Rate", 0.05), F("sigma", "Vol", 0.20), F("q", "Div yld", 0.0),
             F("opt", "Type", "call", _OPT)],
            _vanilla_engine,
            lambda v: ("option", dict(S=v["S"], K=v["K"], T=v["T"], r=v["r"], sigma=v["sigma"],
                                      q=v["q"], opt=v["opt"]), "Vanilla Option"),
            instrument="european_option"),
    Product("american", "American Option (PDE)", "Option",
            [F("S", "Spot", 100), F("K", "Strike", 100), F("T", "Maturity (y)", 1),
             F("r", "Rate", 0.05), F("sigma", "Vol", 0.20), F("q", "Div yld", 0.0),
             F("opt", "Type", "put", _OPT),
             F("model", "Engine", "pde", ["pde", "binomial", "binomial_lr", "trinomial", "lsm"])],
            lambda s, v: s.price_american_option(v["S"], v["K"], v["T"], v["r"], v["sigma"],
                                                 v["q"], v["opt"], v["model"]),
            lambda v: ("american", dict(S=v["S"], K=v["K"], T=v["T"], r=v["r"],
                                        sigma=v["sigma"], q=v["q"], opt=v["opt"],
                                        model=v["model"]), "American Option")),
    Product("merton", "Merton Jump Option", "Option",
            [F("S", "Spot", 100), F("K", "Strike", 100), F("T", "Maturity (y)", 1),
             F("r", "Rate", 0.05), F("sigma", "Diff vol", 0.20), F("q", "Div yld", 0.0),
             F("lam", "Jump intensity", 0.3), F("mu_j", "Jump mean", -0.10),
             F("delta_j", "Jump vol", 0.15), F("opt", "Type", "call", _OPT)],
            lambda s, v: s.price_merton_option(v["S"], v["K"], v["T"], v["r"], v["sigma"],
                                               v["q"], v["lam"], v["mu_j"], v["delta_j"],
                                               v["opt"]),
            lambda v: ("merton", dict(S=v["S"], K=v["K"], T=v["T"], r=v["r"],
                                      sigma=v["sigma"], q=v["q"], lam=v["lam"],
                                      mu_j=v["mu_j"], delta_j=v["delta_j"],
                                      opt=v["opt"]), "Merton Jump Option")),
    Product("barrier", "Barrier Option", "Option",
            [F("S", "Spot", 100), F("K", "Strike", 100), F("H", "Barrier", 90),
             F("T", "Maturity (y)", 1), F("r", "Rate", 0.05), F("sigma", "Vol", 0.20),
             F("q", "Div yld", 0.0), F("opt", "Type", "call", _OPT),
             F("barrier_type", "Barrier", "down-out", ["down-out", "down-in", "up-out", "up-in"])],
            lambda s, v: s.price_barrier_option(v["S"], v["K"], v["H"], v["T"], v["r"], v["sigma"],
                                                v["q"], v["opt"], v["barrier_type"]),
            lambda v: ("barrier", dict(S=v["S"], K=v["K"], H=v["H"], T=v["T"], r=v["r"],
                                       sigma=v["sigma"], q=v["q"], opt=v["opt"],
                                       barrier_type=v["barrier_type"]), "Barrier Option")),
    Product("asian", "Asian Option", "Option",
            [F("S", "Spot", 100), F("K", "Strike", 100), F("T", "Maturity (y)", 1),
             F("r", "Rate", 0.05), F("sigma", "Vol", 0.20), F("q", "Div yld", 0.0),
             F("opt", "Type", "call", _OPT),
             F("averaging", "Avg", "arithmetic", ["arithmetic", "geometric"])],
            lambda s, v: s.price_asian_option(v["S"], v["K"], v["T"], v["r"], v["sigma"], v["q"],
                                              v["opt"], v["averaging"]),
            lambda v: ("asian", dict(S=v["S"], K=v["K"], T=v["T"], r=v["r"], sigma=v["sigma"],
                                     q=v["q"], opt=v["opt"], averaging=v["averaging"]),
                       "Asian Option")),
    Product("digital", "Digital Option", "Option",
            [F("S", "Spot", 100), F("K", "Strike", 100), F("T", "Maturity (y)", 0.5),
             F("r", "Rate", 0.04), F("sigma", "Vol", 0.20), F("q", "Div yld", 0.0),
             F("opt", "Type", "call", _OPT), F("style", "Style", "cash", ["cash", "asset"]),
             F("cash", "Cash", 1.0)],
            lambda s, v: s.price_digital_option(v["S"], v["K"], v["T"], v["r"], v["sigma"], v["q"],
                                                v["opt"], v["style"], v["cash"]),
            lambda v: ("digital", dict(S=v["S"], K=v["K"], T=v["T"], r=v["r"], sigma=v["sigma"],
                                       q=v["q"], opt=v["opt"], style=v["style"], cash=v["cash"]),
                       "Digital Option")),
    Product("lookback", "Lookback Option", "Option",
            [F("S", "Spot", 100), F("T", "Maturity (y)", 1), F("r", "Rate", 0.05),
             F("sigma", "Vol", 0.20), F("q", "Div yld", 0.0), F("opt", "Type", "call", _OPT),
             F("strike_type", "Strike", "floating", ["floating", "fixed"]), F("K", "Strike", 100)],
            lambda s, v: s.price_lookback_option(v["S"], v["T"], v["r"], v["sigma"], v["q"],
                                                 v["opt"], v["strike_type"], v["K"]),
            lambda v: ("lookback", dict(S=v["S"], T=v["T"], r=v["r"], sigma=v["sigma"], q=v["q"],
                                        opt=v["opt"], strike_type=v["strike_type"], K=v["K"]),
                       "Lookback Option")),

    # ── Equity (multi-underlying derivatives) ─────────────
    Product("spread", "Spread Option", "Equity",
            [F("S1", "Spot 1", 100), F("S2", "Spot 2", 100), F("K", "Strike", 5),
             F("T", "Maturity (y)", 1), F("r", "Rate", 0.05), F("sigma1", "Vol 1", 0.20),
             F("sigma2", "Vol 2", 0.25), F("rho", "Corr", 0.4)],
            lambda s, v: s.price_spread_option(v["S1"], v["S2"], v["K"], v["T"], v["r"],
                                               v["sigma1"], v["sigma2"], v["rho"]),
            lambda v: ("spread", dict(S1=v["S1"], S2=v["S2"], K=v["K"], T=v["T"], r=v["r"],
                                      sigma1=v["sigma1"], sigma2=v["sigma2"], rho=v["rho"]),
                       "Spread Option")),

    # ── FX ────────────────────────────────────────────────
    Product("fx_forward", "FX Forward", "FX",
            [F("S", "Spot", 90), F("r_d", "Dom rate", 0.10), F("r_f", "For rate", 0.04),
             F("T", "Maturity (y)", 1)],
            lambda s, v: s.price_fx_forward(v["S"], v["r_d"], v["r_f"], v["T"]),
            lambda v: ("fx_forward", dict(S=v["S"], r_d=v["r_d"], r_f=v["r_f"], T=v["T"]),
                       "FX Forward")),
    Product("fx_option", "FX Option", "FX",
            [F("S", "Spot", 90), F("K", "Strike", 92), F("T", "Maturity (y)", 1),
             F("r_d", "Dom rate", 0.10), F("r_f", "For rate", 0.04), F("sigma", "Vol", 0.15),
             F("opt", "Type", "call", _OPT)],
            lambda s, v: s.price_fx_option(v["S"], v["K"], v["T"], v["r_d"], v["r_f"], v["sigma"],
                                           opt=v["opt"]),
            lambda v: ("option", dict(S=v["S"], K=v["K"], T=v["T"], r=v["r_d"], sigma=v["sigma"],
                                      q=v["r_f"], opt=v["opt"]), "FX Option")),

    # ── Swaps ─────────────────────────────────────────────
    Product("irs", "Interest Rate Swap", "Swaps",
            [F("notional", "Notional", 1_000_000), F("fixed_rate", "Fixed", 0.10),
             F("T", "Maturity (y)", 5), F("freq", "Freq/y", 4), F("r", "Flat rate", 0.10)],
            lambda s, v: s.price_irs(v["notional"], v["fixed_rate"], v["T"], int(v["freq"]),
                                     curve=_disc(s, v), proj_curve=_proj(v)),
            lambda v: ("irs", dict(notional=v["notional"], fixed_rate=v["fixed_rate"], T=v["T"],
                                   freq=int(v["freq"]), r=v["r"]), "IRS")),
    Product("swaption", "Swaption", "Swaps",
            [F("notional", "Notional", 1_000_000), F("K", "Strike", 0.10),
             F("T_option", "Expiry (y)", 1), F("T_swap", "Swap (y)", 5), F("freq", "Freq/y", 2),
             F("sigma", "Vol", 0.20), F("r", "Flat rate", 0.10),
             F("opt", "Type", "payer", ["payer", "receiver"])],
            lambda s, v: s.price_swaption(v["notional"], v["K"], v["T_option"], v["T_swap"],
                                          int(v["freq"]), v["sigma"], v["opt"],
                                          curve=_disc(s, v)),
            lambda v: ("swaption", dict(notional=v["notional"], K=v["K"], T_option=v["T_option"],
                                        T_swap=v["T_swap"], freq=int(v["freq"]), sigma=v["sigma"],
                                        r=v["r"], opt=v["opt"]), "Swaption")),

    # ── Structured Notes ──────────────────────────────────
    Product("autocall", "Autocall / Phoenix", "Structured Notes",
            [F("S0", "Spot", 100), F("r", "Rate", 0.05), F("q", "Div yld", 0.0),
             F("sigma", "Vol", 0.20), F("T", "Maturity (y)", 3), F("autocall_barrier", "AC barrier", 1.0),
             F("coupon_barrier", "Cpn barrier", 0.70), F("ki_barrier", "KI barrier", 0.65),
             F("coupon_rate", "Coupon", 0.10), F("n_sims", "Sims", 20000)],
            lambda s, v: s.price_autocall_phoenix(
                v["S0"], v["r"], v["q"], v["sigma"], v["T"], _obs(v["T"]), v["autocall_barrier"],
                v["coupon_barrier"], v["ki_barrier"], v["coupon_rate"], n_sims=int(v["n_sims"]),
                steps=100),
            lambda v: ("autocall", dict(S0=v["S0"], r=v["r"], q=v["q"], sigma=v["sigma"], T=v["T"],
                                        obs_dates=_obs(v["T"]), autocall_barrier=v["autocall_barrier"],
                                        coupon_barrier=v["coupon_barrier"], ki_barrier=v["ki_barrier"],
                                        coupon_rate=v["coupon_rate"], n_sims=int(v["n_sims"]),
                                        steps=100), "Autocall / Phoenix")),

    Product("ndf", "NDF (Non-Deliverable Fwd)", "FX",
            [F("S", "Spot", 90), F("K", "NDF rate", 92), F("T", "Maturity (y)", 0.5),
             F("r_d", "Dom rate", 0.16), F("r_f", "For rate", 0.05),
             F("notional", "Notional (fgn)", 1_000_000),
             F("settle", "Settle ccy", "foreign", ["foreign", "domestic"]),
             F("position", "Position", "long", ["long", "short"])],
            lambda s, v: s.price_ndf(v["S"], v["K"], v["T"], v["r_d"], v["r_f"],
                                     v["notional"], v["settle"], v["position"]),
            lambda v: ("ndf", dict(S=v["S"], K=v["K"], T=v["T"], r_d=v["r_d"], r_f=v["r_f"],
                                   notional_fgn=v["notional"], settle=v["settle"],
                                   position=v["position"]), "NDF")),
    Product("fx_option_smile", "FX Option (Smile)", "FX",
            [F("S", "Spot", 90), F("K", "Strike", 95), F("T", "Maturity (y)", 1),
             F("r_d", "Dom rate", 0.16), F("r_f", "For rate", 0.04),
             F("atm", "ATM vol", 0.18), F("rr", "25Δ RR", -0.025), F("bf", "25Δ BF", 0.008),
             F("notional", "Notional", 1_000_000), F("opt", "Type", "call", _OPT)],
            lambda s, v: s.price_fx_option_smile(v["S"], v["K"], v["T"], v["r_d"], v["r_f"],
                                                 v["atm"], v["rr"], v["bf"],
                                                 v["notional"], v["opt"]),
            lambda v: ("fx_option_smile", dict(S=v["S"], K=v["K"], T=v["T"], r_d=v["r_d"],
                                               r_f=v["r_f"], atm=v["atm"], rr=v["rr"],
                                               bf=v["bf"], notional=v["notional"],
                                               opt=v["opt"]), "FX Option (Smile)")),
    Product("xccy", "Cross-Currency Swap", "Swaps",
            [F("notional", "Notional (dom)", 90_000_000), F("S", "FX spot", 90),
             F("T", "Maturity (y)", 5), F("freq", "Freq/y", 4),
             F("basis", "Basis spread", -0.005), F("r", "Dom rate", 0.14),
             F("fgn_rate", "Fgn rate", 0.05),
             F("leg_dom", "Dom leg", "float", ["float", "fixed"]),
             F("leg_fgn", "Fgn leg", "float", ["float", "fixed"]),
             F("fixed_dom", "Dom fixed", 0.14), F("fixed_fgn", "Fgn fixed", 0.05)],
            lambda s, v: s.price_xccy_swap(v["notional"], v["S"], v["T"], int(v["freq"]),
                                           v["basis"], v["leg_dom"], v["leg_fgn"],
                                           v["fixed_dom"], v["fixed_fgn"],
                                           disc_dom=_disc(s, v), fgn_rate=v["fgn_rate"]),
            lambda v: ("xccy", dict(notional_dom=v["notional"], S=v["S"], T=v["T"],
                                    freq=int(v["freq"]), basis_spread=v["basis"], r=v["r"],
                                    fgn_rate=v["fgn_rate"], leg_dom=v["leg_dom"],
                                    leg_fgn=v["leg_fgn"], fixed_rate_dom=v["fixed_dom"],
                                    fixed_rate_fgn=v["fixed_fgn"]), "XCCY Swap")),
    Product("zciis", "Inflation Swap (ZC)", "Swaps",
            [F("notional", "Notional", 1_000_000), F("K", "Fixed infl", 0.08),
             F("T", "Maturity (y)", 5),
             F("side", "Side", "pay fixed", ["pay fixed", "receive fixed"])],
            lambda s, v: s.price_zc_inflation_swap(v["notional"], v["K"], v["T"],
                                                   v["side"] == "pay fixed"),
            lambda v: ("zciis", dict(notional=v["notional"], K=v["K"], T=v["T"],
                                     pay_fixed=v["side"] == "pay fixed"),
                       "ZC Inflation Swap")),
    Product("yoyiis", "Inflation Swap (YoY)", "Swaps",
            [F("notional", "Notional", 1_000_000), F("K", "Fixed infl", 0.08),
             F("T", "Maturity (y)", 5), F("freq", "Freq/y", 1),
             F("side", "Side", "pay fixed", ["pay fixed", "receive fixed"])],
            lambda s, v: s.price_yoy_inflation_swap(v["notional"], v["K"], v["T"],
                                                    int(v["freq"]),
                                                    v["side"] == "pay fixed"),
            lambda v: ("yoyiis", dict(notional=v["notional"], K=v["K"], T=v["T"],
                                      freq=int(v["freq"]),
                                      pay_fixed=v["side"] == "pay fixed"),
                       "YoY Inflation Swap")),
    Product("bermudan_swaption", "Bermudan Swaption (HW)", "Swaps",
            [F("notional", "Notional", 1_000_000), F("K", "Strike", 0.10),
             F("ex_dates", "Exercise dates (y)", "1,2,3", wide=True),
             F("T_end", "Swap end (y)", 6), F("freq", "Freq/y", 2),
             F("kappa", "HW kappa", 0.10), F("sigma", "HW sigma", 0.012),
             F("r", "Flat rate", 0.10), F("opt", "Type", "payer", ["payer", "receiver"])],
            lambda s, v: s.price_bermudan_swaption(
                v["notional"], v["K"], _parse_dates(v["ex_dates"]),
                v["T_end"], int(v["freq"]), v["kappa"], v["sigma"], v["opt"],
                curve=_disc(s, v)),
            lambda v: ("bermudan_swaption", dict(
                notional=v["notional"], K=v["K"], exercise_dates=_parse_dates(v["ex_dates"]),
                T_end=v["T_end"], freq=int(v["freq"]), kappa=v["kappa"], sigma=v["sigma"],
                r=v["r"], opt=v["opt"]), "Bermudan Swaption")),
    Product("cms_swap", "CMS Swap", "Swaps",
            [F("notional", "Notional", 1_000_000), F("K", "Fixed", 0.10),
             F("T", "Maturity (y)", 5), F("freq", "Freq/y", 4),
             F("swap_tenor", "CMS tenor (y)", 5), F("sigma", "Swap vol", 0.25),
             F("r", "Flat rate", 0.10)],
            lambda s, v: s.price_cms_swap(v["notional"], v["K"], v["T"], int(v["freq"]),
                                          v["swap_tenor"], v["sigma"], curve=_disc(s, v)),
            lambda v: ("cms_swap", dict(notional=v["notional"], K=v["K"], T=v["T"],
                                        freq=int(v["freq"]), swap_tenor=v["swap_tenor"],
                                        sigma=v["sigma"], r=v["r"]), "CMS Swap")),

    # ── Credit ────────────────────────────────────────────
    Product("cds", "Credit Default Swap", "Credit",
            [F("notional", "Notional", 1_000_000), F("spread", "Spread", 0.01),
             F("T", "Maturity (y)", 5), F("freq", "Freq/y", 4), F("hazard", "Hazard", 0.02),
             F("r", "Rate", 0.05), F("recovery", "Recovery", 0.4)],
            lambda s, v: s.price_cds(v["notional"], v["spread"], v["T"], int(v["freq"]),
                                     v["hazard"], v["r"], v["recovery"]),
            lambda v: ("cds", dict(notional=v["notional"], spread=v["spread"], T=v["T"],
                                   freq=int(v["freq"]), r=v["r"], recovery=v["recovery"]),
                       "CDS")),
    Product("cds_curve", "CDS (Hazard Curve)", "Credit",
            [F("notional", "Notional", 10_000_000), F("spread", "Spread", 0.012),
             F("T", "Maturity (y)", 5), F("freq", "Freq/y", 4),
             F("hazard_id", "Hazard curve", "hazard_1t_demo",
               ["hazard_1t_demo", "hazard_hy_demo"])],
            lambda s, v: s.price_cds_curve(v["notional"], v["spread"], v["T"],
                                           int(v["freq"]), hazard_id=v["hazard_id"]),
            lambda v: ("cds_curve", dict(notional=v["notional"], spread=v["spread"], T=v["T"],
                                         freq=int(v["freq"]), hazard_id=v["hazard_id"]),
                       "CDS (Hazard Curve)")),
    Product("risky_bond", "Risky Bond (Credit)", "Credit",
            [F("face", "Face", 1000), F("coupon", "Coupon", 0.13), F("T", "Maturity (y)", 5),
             F("freq", "Freq/y", 2),
             F("hazard_id", "Hazard curve", "hazard_1t_demo",
               ["hazard_1t_demo", "hazard_hy_demo"])],
            lambda s, v: s.price_risky_bond(v["face"], v["coupon"], v["T"], int(v["freq"]),
                                            hazard_id=v["hazard_id"]),
            lambda v: ("risky_bond", dict(face=v["face"], coupon=v["coupon"], T=v["T"],
                                          freq=int(v["freq"]), hazard_id=v["hazard_id"]),
                       "Risky Bond")),
    Product("convertible", "Convertible Bond (TF)", "Credit",
            [F("S", "Stock spot", 100), F("sigma", "Equity vol", 0.30), F("q", "Div yld", 0.0),
             F("face", "Face", 1000), F("coupon", "Coupon", 0.05), F("freq", "Freq/y", 2),
             F("T", "Maturity (y)", 5), F("conv_ratio", "Conv ratio", 10),
             F("credit_spread", "Credit spread", 0.02), F("r", "Flat rate", 0.10)],
            lambda s, v: s.price_convertible_bond(v["S"], v["sigma"], v["q"], v["face"],
                                                  v["coupon"], int(v["freq"]), v["T"],
                                                  v["conv_ratio"], v["credit_spread"],
                                                  curve=_disc(s, v)),
            lambda v: ("convertible", dict(S=v["S"], sigma=v["sigma"], q=v["q"], face=v["face"],
                                           coupon=v["coupon"], freq=int(v["freq"]), T=v["T"],
                                           conv_ratio=v["conv_ratio"],
                                           credit_spread=v["credit_spread"], r=v["r"]),
                       "Convertible Bond")),
]


def _parse_dates(text) -> list:
    """Parse '1,2,3' into [1.0, 2.0, 3.0]."""
    if isinstance(text, (list, tuple)):
        return [float(t) for t in text]
    return [float(x) for x in str(text).replace(";", ",").split(",") if x.strip()]



_DUAL_CURVE = {"fra", "cap_floor", "irs"}
_DISC_CURVE = {"bond", "zcb", "amortizing", "step_bond", "perpetual", "inflation_linked",
               "custom_bond", "callable", "putable", "frn", "deposit",
               "xccy", "bermudan_swaption", "cms_swap", "convertible"}
for _p in PRODUCTS:
    if _p.id in _DUAL_CURVE:
        _p.curve_roles = ["disc", "proj"]
    elif _p.id in _DISC_CURVE:
        _p.curve_roles = ["disc"]


def _obs(T: float) -> list:
    n = max(int(round(T)), 1)
    return [i for i in range(1, n + 1)]


def products_by_category(category: str) -> list[Product]:
    return [p for p in PRODUCTS if p.category == category]
