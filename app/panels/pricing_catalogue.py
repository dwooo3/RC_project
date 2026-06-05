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


# ── field shortcuts ───────────────────────────────────────
def F(key, label, default, choices=None):
    return Field(key, label, default, choices)


_OPT = ["call", "put"]

PRODUCTS: list[Product] = [
    # ── Fixed Income ──────────────────────────────────────
    Product("bond", "Bond / OFZ", "Fixed Income",
            [F("face", "Face", 1000), F("coupon", "Coupon", 0.07), F("T", "Maturity (y)", 10),
             F("freq", "Freq/y", 2), F("r", "Flat rate", 0.12)],
            lambda s, v: s.price_bond(v["face"], v["coupon"], v["T"], int(v["freq"]),
                                      curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("bond", dict(face=v["face"], coupon=v["coupon"], T=v["T"],
                                    freq=int(v["freq"]), r=v["r"]), "Bond / OFZ")),
    Product("zcb", "Zero-Coupon Bond", "Fixed Income",
            [F("face", "Face", 1000), F("T", "Maturity (y)", 5), F("r", "Flat rate", 0.12)],
            lambda s, v: s.price_bond(v["face"], 0.0, v["T"], 1,
                                      curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("bond", dict(face=v["face"], coupon=0.0, T=v["T"], freq=1, r=v["r"]),
                       "Zero-Coupon Bond")),
    Product("fra", "Forward Rate Agreement", "Fixed Income",
            [F("notional", "Notional", 1_000_000), F("K", "Fixed rate", 0.10),
             F("T1", "Start (y)", 1), F("T2", "End (y)", 1.5), F("r", "Flat rate", 0.10)],
            lambda s, v: s.price_fra(v["notional"], v["K"], v["T1"], v["T2"],
                                     curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("fra", dict(notional=v["notional"], K=v["K"], T1=v["T1"], T2=v["T2"],
                                   r=v["r"]), "FRA")),
    Product("frn", "Floating Rate Note", "Fixed Income",
            [F("face", "Face", 1000), F("spread", "Spread", 0.01), F("T", "Maturity (y)", 5),
             F("freq", "Freq/y", 2), F("r", "Flat rate", 0.12)],
            lambda s, v: s.price_frn(v["face"], v["spread"], v["T"], int(v["freq"]),
                                     curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("frn", dict(face=v["face"], spread=v["spread"], T=v["T"],
                                   freq=int(v["freq"]), r=v["r"]), "FRN")),
    Product("amortizing", "Amortizing Bond", "Fixed Income",
            [F("face", "Face", 1000), F("coupon", "Coupon", 0.07), F("T", "Maturity (y)", 10),
             F("freq", "Freq/y", 2), F("r", "Flat rate", 0.12),
             F("amort_type", "Amort", "linear", ["linear", "annuity"])],
            lambda s, v: s.price_amortizing_bond(v["face"], v["coupon"], v["T"], int(v["freq"]),
                                                 v["amort_type"], curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("amortizing", dict(face=v["face"], coupon=v["coupon"], T=v["T"],
                                          freq=int(v["freq"]), r=v["r"], amort_type=v["amort_type"]),
                       "Amortizing Bond")),
    Product("step_bond", "Step-Up / Step-Down Bond", "Fixed Income",
            [F("face", "Face", 1000), F("coupon1", "Coupon 1", 0.05), F("coupon2", "Coupon 2", 0.08),
             F("switch_year", "Switch (y)", 3), F("T", "Maturity (y)", 6), F("freq", "Freq/y", 2),
             F("r", "Flat rate", 0.10)],
            lambda s, v: s.price_step_bond(v["face"], v["coupon1"], v["coupon2"], v["switch_year"],
                                           v["T"], int(v["freq"]), curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("step_bond", dict(face=v["face"], coupon1=v["coupon1"], coupon2=v["coupon2"],
                                         switch_year=v["switch_year"], T=v["T"], freq=int(v["freq"]),
                                         r=v["r"]), "Step Bond")),
    Product("perpetual", "Perpetual / Consol", "Fixed Income",
            [F("face", "Face", 1000), F("coupon", "Coupon", 0.08), F("freq", "Freq/y", 1),
             F("r", "Flat rate", 0.09)],
            lambda s, v: s.price_perpetual_bond(v["face"], v["coupon"], int(v["freq"]),
                                                curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("perpetual", dict(face=v["face"], coupon=v["coupon"], freq=int(v["freq"]),
                                         r=v["r"]), "Perpetual")),
    Product("inflation_linked", "Inflation-Linked Bond", "Fixed Income",
            [F("face", "Face", 1000), F("real_coupon", "Real coupon", 0.03), F("T", "Maturity (y)", 10),
             F("freq", "Freq/y", 2), F("base_cpi", "Base CPI", 100), F("current_cpi", "Curr CPI", 110),
             F("inflation_rate", "Inflation", 0.04), F("r", "Flat rate", 0.12)],
            lambda s, v: s.price_inflation_linked_bond(v["face"], v["real_coupon"], v["T"], int(v["freq"]),
                                                       v["base_cpi"], v["current_cpi"], v["inflation_rate"],
                                                       curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("inflation_linked", dict(face=v["face"], real_coupon=v["real_coupon"], T=v["T"],
                                                freq=int(v["freq"]), base_cpi=v["base_cpi"],
                                                current_cpi=v["current_cpi"],
                                                inflation_rate=v["inflation_rate"], r=v["r"]),
                       "Inflation-Linked Bond")),
    Product("repo", "Repo", "Fixed Income",
            [F("spot", "Spot (dirty)", 1000), F("repo_rate", "Repo rate", 0.10),
             F("T", "Term (y)", 0.25), F("coupon_income", "Coupon income", 0.0)],
            lambda s, v: s.price_repo(v["spot"], v["repo_rate"], v["T"], v["coupon_income"], "repo"),
            lambda v: ("repo", dict(spot=v["spot"], repo_rate=v["repo_rate"], T=v["T"],
                                    coupon_income=v["coupon_income"], direction="repo"), "Repo")),
    Product("reverse_repo", "Reverse Repo", "Fixed Income",
            [F("spot", "Spot (dirty)", 1000), F("repo_rate", "Repo rate", 0.10),
             F("T", "Term (y)", 0.25), F("coupon_income", "Coupon income", 0.0)],
            lambda s, v: s.price_repo(v["spot"], v["repo_rate"], v["T"], v["coupon_income"], "reverse"),
            lambda v: ("repo", dict(spot=v["spot"], repo_rate=v["repo_rate"], T=v["T"],
                                    coupon_income=v["coupon_income"], direction="reverse"),
                       "Reverse Repo")),
    Product("deposit", "Money Market Deposit", "Fixed Income",
            [F("notional", "Notional", 1_000_000), F("rate", "Rate", 0.10),
             F("T", "Tenor (y)", 0.25), F("r", "Flat rate", 0.10)],
            lambda s, v: s.price_deposit(v["notional"], v["rate"], v["T"],
                                         curve=s.market_data.flat_curve(v["r"])),
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
    Product("cap_floor", "Cap / Floor", "Fixed Income",
            [F("notional", "Notional", 1_000_000), F("K", "Strike", 0.10), F("T", "Maturity (y)", 3),
             F("freq", "Freq/y", 2), F("vol", "Vol", 0.20), F("r", "Flat rate", 0.10),
             F("opt", "Type", "cap", ["cap", "floor"])],
            lambda s, v: s.price_cap_floor(v["notional"], v["K"], v["T"], int(v["freq"]), v["vol"],
                                           v["opt"], curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("cap_floor", dict(notional=v["notional"], K=v["K"], T=v["T"],
                                         freq=int(v["freq"]), vol=v["vol"], r=v["r"], opt=v["opt"]),
                       "Cap/Floor")),

    # ── Option ────────────────────────────────────────────
    Product("vanilla", "Vanilla Option", "Option",
            [F("S", "Spot", 100), F("K", "Strike", 100), F("T", "Maturity (y)", 1),
             F("r", "Rate", 0.05), F("sigma", "Vol", 0.20), F("q", "Div yld", 0.0),
             F("opt", "Type", "call", _OPT)],
            lambda s, v: s.price_vanilla_option(v["S"], v["K"], v["T"], v["r"], v["sigma"],
                                                v["q"], v["opt"]),
            lambda v: ("option", dict(S=v["S"], K=v["K"], T=v["T"], r=v["r"], sigma=v["sigma"],
                                      q=v["q"], opt=v["opt"]), "Vanilla Option")),
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
                                     curve=s.market_data.flat_curve(v["r"])),
            lambda v: ("irs", dict(notional=v["notional"], fixed_rate=v["fixed_rate"], T=v["T"],
                                   freq=int(v["freq"]), r=v["r"]), "IRS")),
    Product("swaption", "Swaption", "Swaps",
            [F("notional", "Notional", 1_000_000), F("K", "Strike", 0.10),
             F("T_option", "Expiry (y)", 1), F("T_swap", "Swap (y)", 5), F("freq", "Freq/y", 2),
             F("sigma", "Vol", 0.20), F("r", "Flat rate", 0.10),
             F("opt", "Type", "payer", ["payer", "receiver"])],
            lambda s, v: s.price_swaption(v["notional"], v["K"], v["T_option"], v["T_swap"],
                                          int(v["freq"]), v["sigma"], v["opt"],
                                          curve=s.market_data.flat_curve(v["r"])),
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
]


def _obs(T: float) -> list:
    n = max(int(round(T)), 1)
    return [i for i in range(1, n + 1)]


def products_by_category(category: str) -> list[Product]:
    return [p for p in PRODUCTS if p.category == category]
