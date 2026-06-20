"""Pricer catalogue for the bridge.

A data-driven table of equity-vanilla pricers. Each entry knows its registry
model id (for the governance card), its full parameter spec list (base contract
/ market inputs + any editable model params), and a small adapter that calls the
right `PricingService` method. The Swift client renders the param list generically
and posts the values back to `/price`, so adding a pricer is one row here — no
client change. Mirrors the PySide `ModelParamsDialog` contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from models import registry
from models.parameters import P, ParameterSpec, engine_params


# ── base contract + market specs shared by the equity-vanilla pricers ──
def _base_specs(uses_sigma: bool = True) -> list[ParameterSpec]:
    specs = [
        P("S", "Spot / forward S", 100.0, "market", minimum=0.0,
          help="underlying spot (forward for Black-76)"),
        P("K", "Strike K", 100.0, "contract", minimum=0.0),
        P("T", "Maturity T", 1.0, "contract", minimum=1e-6, unit="y"),
        P("r", "Risk-free r", 0.05, "market", minimum=-1.0, maximum=1.0,
          help="continuously-compounded"),
        P("q", "Dividend yield q", 0.0, "market", minimum=-1.0, maximum=1.0,
          help="r_f for FX (Garman-Kohlhagen)"),
    ]
    if uses_sigma:
        specs.append(P("sigma", "Volatility σ", 0.20, "market",
                       minimum=1e-6, maximum=5.0))
    specs.append(P("opt", "Option type", "call", "contract",
                   dtype="choice", choices=["call", "put"]))
    return specs


@dataclass
class Pricer:
    """One selectable pricing engine on the vanilla screen."""

    id: str                                    # selector id sent back in /price
    model_id: str                              # registry id (governance lookup)
    name: str
    family: str                                # display grouping
    invoke: Callable[[object, dict], dict]     # (PricingService, params) -> result
    uses_sigma: bool = True
    model_params: list[ParameterSpec] = field(default_factory=list)

    def specs(self) -> list[ParameterSpec]:
        return _base_specs(self.uses_sigma) + self.model_params


# ── adapters: pull exactly the kwargs each service method expects ──
def _vanilla(model: str):
    def call(svc, b):
        return svc.price_vanilla_option(
            b["S"], b["K"], b["T"], b["r"], b.get("sigma"),
            b.get("q", 0.0), b.get("opt", "call"), model=model)
    return call


def _heston(svc, b):
    return svc.price_heston_option(
        b["S"], b["K"], b["T"], b["r"], b.get("q", 0.0),
        b["v0"], b["kappa"], b["theta"], b["xi"], b["rho"],
        b.get("opt", "call"))


def _merton(svc, b):
    return svc.price_merton_option(
        b["S"], b["K"], b["T"], b["r"], b["sigma"], b.get("q", 0.0),
        b.get("lam", 0.1), b.get("mu_j", -0.1), b.get("delta_j", 0.15),
        b.get("opt", "call"))


PRICERS: list[Pricer] = [
    Pricer("bsm", "black_scholes", "Black-Scholes / Merton", "Analytic", _vanilla("bsm")),
    Pricer("black76", "black76", "Black-76 (on forward)", "Analytic", _vanilla("black76")),
    Pricer("bachelier", "bachelier", "Bachelier (normal)", "Analytic", _vanilla("bachelier")),
    Pricer("binomial", "binomial_crr", "Binomial (CRR)", "Lattice", _vanilla("binomial")),
    Pricer("binomial_lr", "binomial_lr", "Binomial (Leisen-Reimer)", "Lattice", _vanilla("binomial_lr")),
    Pricer("trinomial", "trinomial", "Trinomial tree", "Lattice", _vanilla("trinomial")),
    Pricer("pde", "pde_cn", "PDE (Crank-Nicolson)", "PDE", _vanilla("pde")),
    Pricer("mc", "mc_gbm", "Monte Carlo (GBM)", "Monte Carlo", _vanilla("mc")),
    Pricer("heston_cf", "heston_cf", "Heston (characteristic fn)", "Stochastic vol",
           _heston, uses_sigma=False, model_params=engine_params("heston_cf")),
    Pricer("merton_jump", "merton_jump", "Merton jump-diffusion", "Jump",
           _merton, model_params=engine_params("merton_jump")),
]

_BY_ID = {p.id: p for p in PRICERS}


def find_pricer(pricer_id: str) -> Pricer | None:
    return _BY_ID.get(pricer_id)


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
        "asset_class": e.get("asset_class", ""),
        "model_family": e.get("model_family", ""),
        "method": e.get("method", ""),
        "notes": e.get("notes", ""),
        "production_allowed": bool(e.get("production_allowed", False)),
        "analytics_lab_only": bool(e.get("analytics_lab_only", False)),
    }


def build_catalogue() -> list[dict]:
    """Full vanilla catalogue: one entry per pricer with governance + specs."""
    return [
        {
            "id": p.id,
            "model_id": p.model_id,
            "name": p.name,
            "family": p.family,
            "governance": _governance(p.model_id),
            "params": [_spec_dict(s) for s in p.specs()],
        }
        for p in PRICERS
    ]
