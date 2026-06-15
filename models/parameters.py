"""
Parameter specification system (Master-plan M0).

Replaces the flat per-product `Field` list with `ParameterSpec`s grouped into
four buckets so every model AND numerical setting is manually editable:

    contract   — deal terms (strike, maturity, notional, freq, type)
    market     — market inputs (spot, rate, vol, div), auto-fillable from a
                 snapshot via `source`, with manual override
    model      — the chosen engine's model params (Heston kappa/theta/xi/rho,
                 SABR alpha/beta/rho/nu, jump intensity, ...)
    numerical  — method settings (n_sims, steps, tree N, PDE grid, scheme, seed)

`ENGINE_PARAMS` is the library of model+numerical specs per engine; the pricing
UI shows contract+market always and the engine's model+numerical specs in an
Advanced section, rebuilt when the engine changes. Pure data — no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field


GROUPS = ("contract", "market", "model", "numerical")


@dataclass
class ParameterSpec:
    key: str
    label: str
    default: float | int | str
    group: str = "contract"               # contract | market | model | numerical
    dtype: str = "float"                  # float | int | choice | text | date | schedule
    choices: list | None = None
    minimum: float | None = None
    maximum: float | None = None
    source: str = "manual"               # manual | snapshot:<curve_id> | snapshot:fx:<pair> | derived
    advanced: bool = False
    unit: str = ""
    help: str = ""

    def __post_init__(self):
        if self.group not in GROUPS:
            raise ValueError(f"group must be one of {GROUPS}, got {self.group!r}")
        if self.dtype == "choice" and not self.choices:
            raise ValueError(f"choice param {self.key!r} needs choices")
        # model/numerical params default to the Advanced section
        if self.group in ("model", "numerical") and not self.advanced:
            self.advanced = True

    def validate_value(self, value) -> tuple[bool, str]:
        """Check a user value against dtype and min/max bounds."""
        if self.dtype in ("text", "schedule", "date") or self.choices:
            return True, ""
        try:
            v = int(value) if self.dtype == "int" else float(value)
        except (TypeError, ValueError):
            return False, f"{self.label}: not a number"
        if self.minimum is not None and v < self.minimum:
            return False, f"{self.label}: below {self.minimum}"
        if self.maximum is not None and v > self.maximum:
            return False, f"{self.label}: above {self.maximum}"
        return True, ""


def P(key, label, default, group="contract", **kw) -> ParameterSpec:
    return ParameterSpec(key=key, label=label, default=default, group=group, **kw)


# ── Common reusable spec blocks ──────────────────────────
def _mc_specs(n_sims=50_000, steps=100) -> list[ParameterSpec]:
    return [
        P("n_sims", "MC paths", n_sims, "numerical", dtype="int", minimum=1000, maximum=2_000_000),
        P("steps", "Time steps", steps, "numerical", dtype="int", minimum=1, maximum=5000),
        P("seed", "Random seed", 42, "numerical", dtype="int"),
    ]


def _tree_specs(N=500) -> list[ParameterSpec]:
    return [P("N", "Tree steps", N, "numerical", dtype="int", minimum=10, maximum=5000)]


def _pde_specs() -> list[ParameterSpec]:
    return [
        P("Ns", "PDE space nodes", 400, "numerical", dtype="int", minimum=50, maximum=4000),
        P("Nt", "PDE time steps", 400, "numerical", dtype="int", minimum=20, maximum=4000),
    ]


# ── Engine parameter library: model_id -> [ParameterSpec] (model+numerical) ──
ENGINE_PARAMS: dict[str, list[ParameterSpec]] = {
    "black_scholes": [],
    "binomial_crr": _tree_specs(500),
    "binomial_lr": _tree_specs(501),
    "trinomial": _tree_specs(300),
    "pde_cn": _pde_specs(),
    "mc_gbm": _mc_specs(100_000, 64),
    "mc_lsm": _mc_specs(50_000, 50),

    "heston_cf": [
        P("v0", "Initial variance v0", 0.04, "model", minimum=1e-4, maximum=2.0,
          help="spot variance (sigma^2)"),
        P("kappa", "Mean reversion κ", 1.5, "model", minimum=1e-3, maximum=20.0),
        P("theta", "Long-run variance θ", 0.04, "model", minimum=1e-4, maximum=2.0),
        P("xi", "Vol of vol ξ", 0.5, "model", minimum=1e-3, maximum=3.0),
        P("rho", "Spot-vol corr ρ", -0.6, "model", minimum=-0.999, maximum=0.999),
    ],
    "mc_heston_qe": [
        P("v0", "Initial variance v0", 0.04, "model", minimum=1e-4, maximum=2.0),
        P("kappa", "Mean reversion κ", 1.5, "model", minimum=1e-3, maximum=20.0),
        P("theta", "Long-run variance θ", 0.04, "model", minimum=1e-4, maximum=2.0),
        P("xi", "Vol of vol ξ", 0.5, "model", minimum=1e-3, maximum=3.0),
        P("rho", "Spot-vol corr ρ", -0.6, "model", minimum=-0.999, maximum=0.999),
        P("scheme", "MC scheme", "qe", "numerical", dtype="choice", choices=["qe", "euler"]),
        *_mc_specs(100_000, 100),
    ],
    "merton_jump": [
        P("lam", "Jump intensity λ", 0.3, "model", minimum=0.0, maximum=10.0),
        P("mu_j", "Mean jump μ_J", -0.10, "model", minimum=-1.0, maximum=1.0),
        P("delta_j", "Jump vol δ_J", 0.15, "model", minimum=1e-3, maximum=2.0),
    ],
    "bates": [
        P("v0", "Initial variance v0", 0.04, "model", minimum=1e-4, maximum=2.0),
        P("kappa", "Mean reversion κ", 1.5, "model", minimum=1e-3, maximum=20.0),
        P("theta", "Long-run variance θ", 0.04, "model", minimum=1e-4, maximum=2.0),
        P("xi", "Vol of vol ξ", 0.5, "model", minimum=1e-3, maximum=3.0),
        P("rho", "Spot-vol corr ρ", -0.6, "model", minimum=-0.999, maximum=0.999),
        P("lam", "Jump intensity λ", 0.3, "model", minimum=0.0, maximum=10.0),
        P("mu_j", "Mean jump μ_J", -0.10, "model", minimum=-1.0, maximum=1.0),
        P("delta_j", "Jump vol δ_J", 0.15, "model", minimum=1e-3, maximum=2.0),
    ],
    "sabr": [
        P("alpha", "SABR α", 0.20, "model", minimum=1e-3, maximum=3.0),
        P("beta", "SABR β", 0.5, "model", minimum=0.0, maximum=1.0),
        P("rho", "SABR ρ", -0.3, "model", minimum=-0.999, maximum=0.999),
        P("nu", "SABR vol-of-vol ν", 0.4, "model", minimum=1e-3, maximum=5.0),
    ],
    # ── Lévy / jump (Fourier COS) — M1 ────────────────────
    "kou": [
        P("lam", "Jump intensity λ", 0.5, "model", minimum=0.0, maximum=10.0),
        P("p", "P(up jump)", 0.4, "model", minimum=0.0, maximum=1.0),
        P("eta1", "Up-jump rate η1", 10.0, "model", minimum=1.001, maximum=50.0,
          help="η1>1 required for finite mean"),
        P("eta2", "Down-jump rate η2", 5.0, "model", minimum=0.1, maximum=50.0),
        P("N", "COS terms", 256, "numerical", dtype="int", minimum=64, maximum=2048),
    ],
    "variance_gamma": [
        P("nu", "VG variance rate ν", 0.2, "model", minimum=1e-3, maximum=2.0),
        P("theta", "VG skew θ", -0.1, "model", minimum=-1.0, maximum=1.0),
        P("N", "COS terms", 256, "numerical", dtype="int", minimum=64, maximum=2048),
    ],
    "nig": [
        P("alpha", "NIG tail α", 15.0, "model", minimum=0.5, maximum=100.0),
        P("beta", "NIG skew β", -5.0, "model", minimum=-99.0, maximum=99.0,
          help="|β|<α required"),
        P("delta", "NIG scale δ", 0.5, "model", minimum=1e-3, maximum=5.0),
        P("N", "COS terms", 256, "numerical", dtype="int", minimum=64, maximum=2048),
    ],
    "cgmy": [
        P("C", "CGMY activity C", 0.1, "model", minimum=1e-3, maximum=5.0),
        P("G", "CGMY down decay G", 5.0, "model", minimum=0.1, maximum=50.0),
        P("M", "CGMY up decay M", 5.0, "model", minimum=0.1, maximum=50.0),
        P("Y", "CGMY fine structure Y", 0.8, "model", minimum=-5.0, maximum=1.99),
        P("N", "COS terms", 512, "numerical", dtype="int", minimum=128, maximum=4096),
    ],
    "rough_bergomi": [
        P("H", "Hurst H", 0.1, "model", minimum=0.01, maximum=0.49,
          help="<0.5 = rough"),
        P("eta", "Vol-of-vol η", 1.5, "model", minimum=1e-3, maximum=5.0),
        P("rho", "Spot-vol corr ρ", -0.7, "model", minimum=-0.999, maximum=0.999),
        P("xi0", "Forward variance ξ0", 0.04, "model", minimum=1e-4, maximum=2.0),
        P("n_paths", "MC paths", 40_000, "numerical", dtype="int",
          minimum=2000, maximum=500_000),
        P("steps", "Time steps", 100, "numerical", dtype="int", minimum=20, maximum=1000),
    ],
    "local_vol_mc": _mc_specs(80_000, 100),
    "callable_bond": [
        P("sigma", "Rate vol σ", 0.15, "model", minimum=1e-3, maximum=1.0),
        P("m", "Tree steps/period", 2, "numerical", dtype="int", minimum=1, maximum=20),
    ],
    "bermudan_swaption": [
        P("kappa", "HW mean reversion κ", 0.1, "model", minimum=1e-3, maximum=3.0),
        P("sigma", "HW vol σ", 0.012, "model", minimum=1e-4, maximum=0.5),
        P("steps", "Tree steps", 200, "numerical", dtype="int", minimum=20, maximum=2000),
        P("calibrate_to_cube", "Calibrate to cube", "no", "model",
          dtype="choice", choices=["no", "yes"]),
    ],
    "g2pp": [
        P("a", "Factor-1 mean reversion a", 0.1, "model", minimum=1e-3, maximum=3.0),
        P("sigma", "Factor-1 vol σ", 0.01, "model", minimum=1e-4, maximum=0.5),
        P("b", "Factor-2 mean reversion b", 0.3, "model", minimum=1e-3, maximum=5.0),
        P("eta", "Factor-2 vol η", 0.012, "model", minimum=1e-7, maximum=0.5),
        P("rho", "Factor correlation ρ", -0.7, "model", minimum=-0.999, maximum=0.999),
        P("n_sims", "MC paths", 50_000, "numerical", dtype="int",
          minimum=5000, maximum=500_000),
    ],
    "lmm": [
        P("vol", "Forward vol σ", 0.20, "model", minimum=1e-3, maximum=2.0,
          help="flat per-rate lognormal vol"),
        P("corr_beta", "Corr decay β", 0.1, "model", minimum=0.0, maximum=2.0,
          help="ρ_ij = exp(-β|T_i-T_j|)"),
        P("n_sims", "MC paths", 50_000, "numerical", dtype="int",
          minimum=5000, maximum=500_000),
        P("steps", "Time steps", 24, "numerical", dtype="int",
          minimum=4, maximum=500),
    ],
    "bk": [
        P("a", "Mean reversion a", 0.1, "model", minimum=1e-3, maximum=3.0),
        P("sigma", "Log-rate vol σ", 0.20, "model", minimum=1e-3, maximum=2.0),
        P("steps_per_year", "Tree steps/year", 24, "numerical", dtype="int",
          minimum=4, maximum=200),
    ],
    "cheyette": [
        P("a", "Mean reversion a", 0.1, "model", minimum=1e-3, maximum=3.0),
        P("sigma", "Vol σ", 0.01, "model", minimum=1e-4, maximum=0.5),
        P("skew", "Local-vol skew", 0.0, "model", minimum=-10.0, maximum=10.0,
          help="σ_r = σ(1+skew·x); 0 = Hull-White"),
        P("n_sims", "MC paths", 50_000, "numerical", dtype="int",
          minimum=5000, maximum=500_000),
        P("steps", "Time steps", 100, "numerical", dtype="int", minimum=20, maximum=1000),
    ],
    "schwartz_smith": [
        P("kappa", "Short-term mean reversion κ", 1.0, "model", minimum=1e-2, maximum=10.0),
        P("sigma_chi", "Short-term vol σ_χ", 0.30, "model", minimum=1e-3, maximum=3.0),
        P("mu_xi", "Equilibrium drift μ_ξ", 0.0, "model", minimum=-1.0, maximum=1.0),
        P("sigma_xi", "Equilibrium vol σ_ξ", 0.15, "model", minimum=1e-3, maximum=3.0),
        P("rho", "Factor correlation ρ", 0.3, "model", minimum=-0.999, maximum=0.999),
        P("chi0", "Initial short-term χ0", 0.0, "model", minimum=-2.0, maximum=2.0),
    ],
    "gibson_schwartz": [
        P("delta0", "Initial convenience yield δ0", 0.05, "model", minimum=-0.5, maximum=1.0),
        P("kappa", "CY mean reversion κ", 1.0, "model", minimum=1e-2, maximum=10.0),
        P("sigma_S", "Spot vol σ_S", 0.30, "model", minimum=1e-3, maximum=3.0),
        P("alpha_tilde", "Long-run CY α̃", 0.05, "model", minimum=-0.5, maximum=1.0),
        P("sigma_delta", "CY vol σ_δ", 0.30, "model", minimum=1e-3, maximum=3.0),
        P("rho", "Spot-CY correlation ρ", 0.3, "model", minimum=-0.999, maximum=0.999),
    ],
    "cds_curve": [
        P("recovery", "Recovery rate", 0.4, "model", minimum=0.0, maximum=0.99),
    ],
}


def engine_params(engine_id: str) -> list[ParameterSpec]:
    """Model + numerical specs for an engine (empty for plain analytic)."""
    return list(ENGINE_PARAMS.get(engine_id, []))


def specs_by_group(specs: list[ParameterSpec]) -> dict[str, list[ParameterSpec]]:
    """Bucket specs into the four groups for grouped rendering."""
    out: dict[str, list[ParameterSpec]] = {g: [] for g in GROUPS}
    for s in specs:
        out[s.group].append(s)
    return out


def from_legacy_fields(fields) -> list[ParameterSpec]:
    """
    Migrate existing catalogue Field objects to ParameterSpec (M0 auto-converter):
    choices -> choice, schedule-ish (wide text) -> contract text, else contract
    float. Lets the new grouped renderer drive old products unchanged.
    """
    specs = []
    for f in fields:
        if getattr(f, "choices", None):
            specs.append(P(f.key, f.label, f.default, "contract",
                           dtype="choice", choices=list(f.choices)))
        elif isinstance(f.default, str):
            dtype = "schedule" if getattr(f, "wide", False) else "text"
            specs.append(P(f.key, f.label, f.default, "contract", dtype=dtype))
        else:
            # rate/vol/spot heuristics -> market group; rest -> contract
            grp = "market" if f.key in {"r", "r_d", "r_f", "sigma", "vol", "q",
                                        "S", "S0", "spot"} else "contract"
            specs.append(P(f.key, f.label, f.default, grp))
    return specs
