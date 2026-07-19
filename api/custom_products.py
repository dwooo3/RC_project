"""Custom Product Engine (spec §16): declarative, typed, versioned product
definitions compiled to a payoff IR and executed by a generic MC evaluator.

Core rules (spec §16.5): no user code is ever executed — a definition is a
JSON document over an allowlisted typed AST; the compiler fail-closes on
anything outside the allowlist. Published artifacts are immutable; changes
require a new version. Approval is maker≠checker (§20).

No FastAPI imports: the engine, compiler, store and lifecycle are plain
Python so the whole contract runs in CI. HTTP wiring lives in api/server.py.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import time
import uuid

import numpy as np

from models.monte_carlo import gbm_paths, multi_asset_paths

# ── typed AST allowlist ──────────────────────────────────

NUMBER, BOOL = "number", "bool"

# node kind → (argument spec, result type); "n" = numeric child, "b" = bool
_EXPR_NODES = {
    "const":     ((), NUMBER),          # {"node":"const","value":1.0}
    "param":     ((), NUMBER),          # slot reference {"name": ...}
    "state":     ((), NUMBER),          # state variable {"name": ...}
    "perf":      ((), NUMBER),          # S_t / S0 (single-underlying only)
    "time":      ((), NUMBER),          # current observation time, years
    "accrual":   ((), NUMBER),          # t_i - t_{i-1}
    "path_min":  ((), NUMBER),          # running min of perf (single-asset)
    "path_max":  ((), NUMBER),          # running max of perf (single-asset)
    # multi-asset aggregations (spec §16.2: basket, worst/best/nth/weighted)
    "asset":     ((), NUMBER),          # perf of one asset {"index": i}
    "worst_of":  ((), NUMBER),          # min over assets at current obs
    "best_of":   ((), NUMBER),          # max over assets at current obs
    "basket_avg": ((), NUMBER),         # equally-weighted basket perf
    "weighted":  ((), NUMBER),          # weighted basket {"weights": [...]}
    "nth_worst": ((), NUMBER),          # rank-th worst perf {"rank": n}
    "worst_path_min": ((), NUMBER),     # running min over time AND assets
    "add":       (("n", "n"), NUMBER),
    "sub":       (("n", "n"), NUMBER),
    "mul":       (("n", "n"), NUMBER),
    "div":       (("n", "n"), NUMBER),
    "neg":       (("n",), NUMBER),
    "min":       (("n", "n"), NUMBER),
    "max":       (("n", "n"), NUMBER),
    "ge":        (("n", "n"), BOOL),
    "gt":        (("n", "n"), BOOL),
    "le":        (("n", "n"), BOOL),
    "lt":        (("n", "n"), BOOL),
    "and":       (("b", "b"), BOOL),
    "or":        (("b", "b"), BOOL),
    "not":       (("b",), BOOL),
    "if":        (("b", "n", "n"), NUMBER),
}

_ACTIONS = {"set", "accumulate", "pay", "terminate"}
_MAX_DEPTH = 64
_MAX_NODES = 512

_TOP_KEYS = {"name", "description", "author", "slots", "state", "assets",
             "schedule", "observation_program", "maturity_program"}


def _asset_names(defn: dict) -> list[str]:
    assets = defn.get("assets")
    if isinstance(assets, list) and assets:
        return [str(a) for a in assets]
    return ["S"]

# Lifecycle (spec §16.5); validate/compile/test collapse into one server
# compile step, whose report records each stage's evidence.
_STATES = ("draft", "validated", "tested", "submitted", "approved",
           "published", "deprecated")


def _issue(issues, code, message, path=""):
    issues.append({"code": code, "severity": "error",
                   "message": message, "path": path})


# ── compiler: schema/type/consistency checks (spec §16.4) ─

def _check_expr(expr, defn, issues, path, depth=0, count=None):
    """Recursive allowlist + type check; returns the expression type."""
    if count is None:
        count = [0]
    count[0] += 1
    if count[0] > _MAX_NODES:
        _issue(issues, "CUSTOM_PRODUCT_RESOURCE", f"AST больше {_MAX_NODES} узлов", path)
        return NUMBER
    if depth > _MAX_DEPTH:
        _issue(issues, "CUSTOM_PRODUCT_RESOURCE", f"AST глубже {_MAX_DEPTH}", path)
        return NUMBER
    if not isinstance(expr, dict) or "node" not in expr:
        _issue(issues, "CUSTOM_PRODUCT_UNKNOWN_NODE", "выражение не является узлом", path)
        return NUMBER
    kind = expr["node"]
    if kind not in _EXPR_NODES:
        _issue(issues, "CUSTOM_PRODUCT_UNKNOWN_NODE", f"узел '{kind}' вне allowlist", path)
        return NUMBER
    argspec, result = _EXPR_NODES[kind]
    if kind == "const":
        if not isinstance(expr.get("value"), (int, float)) or isinstance(expr.get("value"), bool):
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH", "const.value должен быть числом", path)
    elif kind == "param":
        if expr.get("name") not in (defn.get("slots") or {}):
            _issue(issues, "CUSTOM_PRODUCT_UNDECLARED_SLOT",
                   f"слот '{expr.get('name')}' не объявлен", path)
    elif kind == "state":
        if expr.get("name") not in (defn.get("state") or {}):
            _issue(issues, "CUSTOM_PRODUCT_UNDECLARED_STATE",
                   f"state '{expr.get('name')}' не объявлен", path)
    n_assets = len(_asset_names(defn))
    if kind in ("perf", "path_min", "path_max") and n_assets > 1:
        _issue(issues, "CUSTOM_PRODUCT_AMBIGUOUS_ASSET",
               f"'{kind}' неоднозначен при {n_assets} активах — используй "
               "asset/worst_of/best_of/basket_avg/worst_path_min", path)
    elif kind == "asset":
        index = expr.get("index")
        if not isinstance(index, int) or not 0 <= index < n_assets:
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH",
                   f"asset.index должен быть 0..{n_assets - 1}", path)
    elif kind == "nth_worst":
        rank = expr.get("rank")
        if not isinstance(rank, int) or not 1 <= rank <= n_assets:
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH",
                   f"nth_worst.rank должен быть 1..{n_assets}", path)
    elif kind == "weighted":
        weights = expr.get("weights")
        if (not isinstance(weights, list) or len(weights) != n_assets
                or not all(isinstance(w, (int, float)) and not isinstance(w, bool)
                           for w in weights)):
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH",
                   f"weighted.weights: нужен список из {n_assets} чисел", path)
    args = expr.get("args", [])
    if argspec and (not isinstance(args, list) or len(args) != len(argspec)):
        _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH",
               f"'{kind}' ожидает {len(argspec)} аргументов", path)
        return result
    for i, (want, arg) in enumerate(zip(argspec, args)):
        got = _check_expr(arg, defn, issues, f"{path}.args[{i}]", depth + 1, count)
        want_t = NUMBER if want == "n" else BOOL
        if got != want_t:
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH",
                   f"'{kind}' аргумент {i}: ожидается {want_t}, получен {got}",
                   f"{path}.args[{i}]")
    return result


def _check_action(action, defn, issues, path):
    if not isinstance(action, dict) or action.get("action") not in _ACTIONS:
        _issue(issues, "CUSTOM_PRODUCT_UNKNOWN_NODE",
               f"действие '{(action or {}).get('action')}' вне allowlist", path)
        return
    kind = action["action"]
    if kind in ("set", "accumulate"):
        if action.get("name") not in (defn.get("state") or {}):
            _issue(issues, "CUSTOM_PRODUCT_UNDECLARED_STATE",
                   f"state '{action.get('name')}' не объявлен", path)
        if _check_expr(action.get("value"), defn, issues, f"{path}.value") != NUMBER:
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH", "value должен быть числом", path)
    elif kind == "pay":
        if _check_expr(action.get("amount"), defn, issues, f"{path}.amount") != NUMBER:
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH", "amount должен быть числом", path)
        if "when" in action and _check_expr(action["when"], defn, issues, f"{path}.when") != BOOL:
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH", "when должен быть булевым", path)
    elif kind == "terminate":
        if _check_expr(action.get("when"), defn, issues, f"{path}.when") != BOOL:
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH", "when должен быть булевым", path)
        if _check_expr(action.get("payout"), defn, issues, f"{path}.payout") != NUMBER:
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH", "payout должен быть числом", path)


def validate_definition(defn: dict) -> list[dict]:
    """Fail-closed structural/type/consistency validation (spec §16.4)."""
    issues: list[dict] = []
    if not isinstance(defn, dict):
        _issue(issues, "SCHEMA_TYPE", "definition должен быть объектом")
        return issues
    for key in defn:
        if key not in _TOP_KEYS:
            _issue(issues, "SCHEMA_UNKNOWN_FIELD", f"неизвестное поле '{key}'", key)
    if not str(defn.get("name") or "").strip():
        _issue(issues, "SCHEMA_MISSING_FIELD", "name обязателен", "name")

    assets = defn.get("assets")
    if assets is not None:
        if (not isinstance(assets, list) or not assets
                or not all(isinstance(a, str) and a.strip() for a in assets)):
            _issue(issues, "SCHEMA_TYPE",
                   "assets должен быть непустым списком имён", "assets")
        elif len(set(assets)) != len(assets):
            _issue(issues, "SCHEMA_TYPE", "имена активов дублируются", "assets")

    slots = defn.get("slots") or {}
    for name, spec in slots.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("default"), (int, float)):
            _issue(issues, "SCHEMA_TYPE", f"слот '{name}' должен иметь числовой default",
                   f"slots.{name}")
    state = defn.get("state") or {}
    for name, init in state.items():
        if not isinstance(init, (int, float)) or isinstance(init, bool):
            _issue(issues, "CUSTOM_PRODUCT_UNDECLARED_STATE",
                   f"state '{name}' должен иметь числовое начальное значение",
                   f"state.{name}")

    sched = defn.get("schedule") or {}
    n_obs = _resolve_scalar(sched.get("observations"), slots)
    maturity = _resolve_scalar(sched.get("maturity"), slots)
    if n_obs is None or int(n_obs) < 1:
        _issue(issues, "CUSTOM_PRODUCT_SCHEDULE_INVALID",
               "schedule.observations должен быть ≥ 1", "schedule.observations")
    if maturity is None or maturity <= 0:
        _issue(issues, "CUSTOM_PRODUCT_SCHEDULE_INVALID",
               "schedule.maturity должен быть > 0", "schedule.maturity")

    obs_prog = defn.get("observation_program") or []
    mat_prog = defn.get("maturity_program") or []
    if not obs_prog and not mat_prog:
        _issue(issues, "CUSTOM_PRODUCT_EMPTY", "нет ни одной программы")
    for i, action in enumerate(obs_prog):
        _check_action(action, defn, issues, f"observation_program[{i}]")
    for i, action in enumerate(mat_prog):
        _check_action(action, defn, issues, f"maturity_program[{i}]")
        if isinstance(action, dict) and action.get("action") == "terminate":
            _issue(issues, "CUSTOM_PRODUCT_TYPE_MISMATCH",
                   "terminate в maturity_program не имеет смысла",
                   f"maturity_program[{i}]")
    # payout in every terminating branch (§16.4): survivors must be paid
    # unconditionally at maturity.
    if not any(isinstance(a, dict) and a.get("action") == "pay" and "when" not in a
               for a in mat_prog):
        _issue(issues, "CUSTOM_PRODUCT_NO_TERMINAL_PAYOUT",
               "maturity_program обязан содержать безусловный pay", "maturity_program")
    return issues


def _resolve_scalar(value, slots, overrides=None):
    """Literal number or {"slot": name} reference resolved to a float."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, dict) and "slot" in value:
        name = value["slot"]
        if overrides and name in overrides:
            return float(overrides[name])
        spec = (slots or {}).get(name)
        if isinstance(spec, dict) and isinstance(spec.get("default"), (int, float)):
            return float(spec["default"])
    return None


def definition_hash(defn: dict) -> str:
    canon = json.dumps(defn, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


_REPRICING_CONTRACT = "custom_ast_scenario_repricing"
_REPRICING_CONTRACT_VERSION = 1
_RNG_CONTRACT_VERSION = 1
_VALUATION_STATE_KEYS = {
    "schema_version", "mode", "asset_names", "current_spots",
    "reference_spots", "observation_index", "state_values",
    "running_min", "running_max",
}
_SCENARIO_KEYS = {
    "schema_version", "spot_multipliers", "absolute_current_spots",
    "sigma_shifts",
}
_MAX_UNIT_PATH_POINTS = 25_000_000
_MAX_GREEK_WORK_PATH_POINTS = 250_000_000
_ESTIMATED_PEAK_BYTES_PER_PATH_POINT = 32
_MAX_ESTIMATED_PEAK_BYTES = 1_073_741_824


class CustomProductRepricingError(ValueError):
    """A canonical custom-product state/scenario cannot be repriced safely.

    ``code`` is stable machine-readable evidence for PortfolioService/API
    adapters.  ``reason`` remains suitable for an operator-facing log.
    """

    def __init__(self, code: str, reason: str):
        self.code = str(code)
        self.reason = str(reason)
        super().__init__(f"{self.code}: {self.reason}")

    def as_dict(self) -> dict:
        return {"code": self.code, "reason": self.reason}


def custom_mc_resource_budget(n_assets: int, n_sims: int, steps: int, *,
                              include_greeks: bool = False) -> dict:
    """Fail-closed allocation/work preflight shared by every custom MC route.

    The path generators materialise dense arrays.  Validate the worst useful
    allocation before the first random number is drawn; process-level OOM is
    not an acceptable validation mechanism for a user-authored product.
    """
    values = {
        "assets": n_assets,
        "paths": n_sims,
        "steps": steps,
    }
    parsed: dict[str, int] = {}
    for label, value in values.items():
        if isinstance(value, bool):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_RESOURCE_LIMIT",
                f"{label}: требуется положительное целое число",
            )
        try:
            integer = int(value)
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_RESOURCE_LIMIT",
                f"{label}: требуется положительное целое число",
            ) from exc
        if numeric != integer or integer <= 0:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_RESOURCE_LIMIT",
                f"{label}: требуется положительное целое число",
            )
        parsed[label] = integer

    path_points = (
        parsed["assets"] * parsed["paths"] * (parsed["steps"] + 1)
    )
    estimated_peak_bytes = (
        path_points * _ESTIMATED_PEAK_BYTES_PER_PATH_POINT
    )
    greek_repricings = 1 + 4 * parsed["assets"] if include_greeks else 1
    work_path_points = path_points * greek_repricings
    if (path_points > _MAX_UNIT_PATH_POINTS
            or estimated_peak_bytes > _MAX_ESTIMATED_PEAK_BYTES):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_RESOURCE_LIMIT",
            "custom MC grid exceeds the unit-repricing allocation envelope "
            f"(path_points={path_points}, limit={_MAX_UNIT_PATH_POINTS}, "
            f"estimated_peak_bytes={estimated_peak_bytes})",
        )
    if include_greeks and work_path_points > _MAX_GREEK_WORK_PATH_POINTS:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_RESOURCE_LIMIT",
            "custom MC component Greeks exceed the governed work envelope "
            f"(work_path_points={work_path_points}, "
            f"limit={_MAX_GREEK_WORK_PATH_POINTS})",
        )
    return {
        "policy": "custom_mc_resource_v1",
        "assets": parsed["assets"],
        "paths": parsed["paths"],
        "steps": parsed["steps"],
        "path_points": path_points,
        "estimated_peak_bytes": estimated_peak_bytes,
        "estimated_bytes_per_path_point": (
            _ESTIMATED_PEAK_BYTES_PER_PATH_POINT
        ),
        "unit_path_points_limit": _MAX_UNIT_PATH_POINTS,
        "greek_repricings": greek_repricings,
        "work_path_points": work_path_points,
        "greek_work_path_points_limit": _MAX_GREEK_WORK_PATH_POINTS,
    }


def _contract_hash(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _contract_finite(value: object, label: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            f"{label}: требуется число",
        ) from exc
    if not np.isfinite(numeric):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            f"{label}: значение должно быть конечным",
        )
    return numeric


def _asset_vector(value: object, assets: list[str], label: str, *,
                  positive: bool = False) -> np.ndarray:
    """Resolve an exact asset-name mapping (or engine-internal aligned list)."""
    if isinstance(value, dict):
        missing = [name for name in assets if name not in value]
        unknown = [str(name) for name in value if name not in assets]
        if missing or unknown:
            details = []
            if missing:
                details.append("нет " + ", ".join(missing))
            if unknown:
                details.append("неизвестны " + ", ".join(unknown))
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_ASSET_MISMATCH",
                f"{label}: набор активов не совпадает ({'; '.join(details)})",
            )
        raw = [value[name] for name in assets]
    elif isinstance(value, (list, tuple, np.ndarray)):
        if len(value) != len(assets):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_ASSET_MISMATCH",
                f"{label}: нужно {len(assets)} значений в порядке asset_names",
            )
        raw = list(value)
    else:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            f"{label}: нужен объект по asset name",
        )
    vector = np.asarray([
        _contract_finite(item, f"{label}.{assets[index]}")
        for index, item in enumerate(raw)
    ], dtype=float)
    if positive and np.any(vector <= 0.0):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            f"{label}: значения должны быть строго положительными",
        )
    return vector


def inception_valuation_state(defn: dict, current_spots: object,
                              reference_spots: object | None = None) -> dict:
    """Build the only currently supported canonical roll-forward state.

    Seasoned products require prior observation/state/path history.  Until
    that state machine is implemented, callers can only originate an
    inception state and shock it instantaneously through a scenario.
    """
    assets = _asset_names(defn)
    current = _asset_vector(current_spots, assets, "current_spots",
                            positive=True)
    reference = _asset_vector(
        current_spots if reference_spots is None else reference_spots,
        assets, "reference_spots", positive=True,
    )
    performances = current / reference
    if not np.allclose(performances, 1.0, rtol=0.0, atol=1e-12):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "inception state требует current_spots = reference_spots",
        )
    state_values = {
        name: _contract_finite(value, f"state_values.{name}")
        for name, value in (defn.get("state") or {}).items()
    }
    return {
        "schema_version": _REPRICING_CONTRACT_VERSION,
        "mode": "inception",
        "asset_names": list(assets),
        "current_spots": dict(zip(assets, current.tolist())),
        "reference_spots": dict(zip(assets, reference.tolist())),
        "observation_index": 0,
        "state_values": state_values,
        "running_min": dict(zip(assets, performances.tolist())),
        "running_max": dict(zip(assets, performances.tolist())),
    }


def _canonical_valuation_state(defn: dict, valuation_state: dict | None,
                               *, require_explicit: bool) -> tuple[dict, str]:
    assets = _asset_names(defn)
    if valuation_state is None:
        if require_explicit:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_STATE_REQUIRED",
                "scenario repricing требует canonical valuation_state",
            )
        return inception_valuation_state(defn, [1.0] * len(assets)), \
            "legacy_unit_inception"
    if not isinstance(valuation_state, dict):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "valuation_state должен быть объектом",
        )
    unknown = sorted(set(valuation_state) - _VALUATION_STATE_KEYS)
    missing = sorted(_VALUATION_STATE_KEYS - set(valuation_state))
    if unknown or missing:
        details = []
        if missing:
            details.append("нет " + ", ".join(missing))
        if unknown:
            details.append("неизвестны " + ", ".join(unknown))
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "valuation_state schema mismatch: " + "; ".join(details),
        )
    if valuation_state.get("schema_version") != _REPRICING_CONTRACT_VERSION:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_SCHEMA_UNSUPPORTED",
            "поддерживается valuation_state.schema_version=1",
        )
    if valuation_state.get("mode") != "inception":
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "поддерживается только mode='inception'; нужен полный seasoned "
            "observation/state/path contract",
        )
    state_assets = valuation_state.get("asset_names")
    if state_assets != assets:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_ASSET_MISMATCH",
            "valuation_state.asset_names должен точно совпадать с definition.assets",
        )
    observation_index = valuation_state.get("observation_index")
    if (isinstance(observation_index, bool)
            or not isinstance(observation_index, int)
            or observation_index != 0):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "observation_index должен быть 0 для inception; seasoned state "
            "пока не поддерживается",
        )
    current = _asset_vector(valuation_state.get("current_spots"), assets,
                            "current_spots", positive=True)
    reference = _asset_vector(valuation_state.get("reference_spots"), assets,
                              "reference_spots", positive=True)
    performances = current / reference
    if not np.allclose(performances, 1.0, rtol=0.0, atol=1e-12):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "inception current_spots должны совпадать с contractual "
            "reference_spots; ненулевая performance требует seasoned state",
        )
    defaults = {
        name: _contract_finite(value, f"definition.state.{name}")
        for name, value in (defn.get("state") or {}).items()
    }
    raw_state = valuation_state.get("state_values")
    if not isinstance(raw_state, dict) or set(raw_state) != set(defaults):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "state_values должен точно совпадать с definition.state",
        )
    state_values = {
        name: _contract_finite(raw_state[name], f"state_values.{name}")
        for name in defaults
    }
    if any(not np.isclose(state_values[name], defaults[name], rtol=0.0,
                          atol=1e-12) for name in defaults):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "inception state_values должны совпадать с definition defaults",
        )
    running_min = _asset_vector(valuation_state.get("running_min"), assets,
                                "running_min", positive=True)
    running_max = _asset_vector(valuation_state.get("running_max"), assets,
                                "running_max", positive=True)
    if (not np.allclose(running_min, performances, rtol=0.0, atol=1e-12)
            or not np.allclose(running_max, performances, rtol=0.0,
                               atol=1e-12)):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "inception running_min/running_max должны равняться current/reference",
        )
    canonical = {
        "schema_version": _REPRICING_CONTRACT_VERSION,
        "mode": "inception",
        "asset_names": list(assets),
        "current_spots": dict(zip(assets, current.tolist())),
        "reference_spots": dict(zip(assets, reference.tolist())),
        "observation_index": 0,
        "state_values": state_values,
        "running_min": dict(zip(assets, running_min.tolist())),
        "running_max": dict(zip(assets, running_max.tolist())),
    }
    return canonical, "explicit_canonical_inception"


def _canonical_scenario(scenario: dict | None, assets: list[str],
                        base_current: np.ndarray) -> tuple[dict, np.ndarray, np.ndarray]:
    raw = {} if scenario is None else scenario
    if not isinstance(raw, dict):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "scenario должен быть объектом",
        )
    unknown = sorted(set(raw) - _SCENARIO_KEYS)
    if unknown:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "неизвестные поля scenario: " + ", ".join(unknown),
        )
    if raw.get("schema_version", _REPRICING_CONTRACT_VERSION) \
            != _REPRICING_CONTRACT_VERSION:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_SCHEMA_UNSUPPORTED",
            "поддерживается scenario.schema_version=1",
        )
    has_multipliers = "spot_multipliers" in raw
    has_absolute = "absolute_current_spots" in raw
    if has_multipliers:
        multipliers = _asset_vector(raw["spot_multipliers"], assets,
                                    "spot_multipliers", positive=True)
        current = base_current * multipliers
        if has_absolute:
            absolute = _asset_vector(raw["absolute_current_spots"], assets,
                                     "absolute_current_spots", positive=True)
            if not np.allclose(current, absolute, rtol=1e-12, atol=1e-12):
                raise CustomProductRepricingError(
                    "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                    "spot_multipliers и absolute_current_spots противоречат "
                    "друг другу",
                )
            current = absolute
    elif has_absolute:
        current = _asset_vector(raw["absolute_current_spots"], assets,
                                "absolute_current_spots", positive=True)
        multipliers = current / base_current
    else:
        current = base_current.copy()
        multipliers = np.ones(len(assets))
    sigma_shifts = (_asset_vector(raw["sigma_shifts"], assets, "sigma_shifts")
                    if "sigma_shifts" in raw else np.zeros(len(assets)))
    canonical = {
        "schema_version": _REPRICING_CONTRACT_VERSION,
        "spot_multipliers": dict(zip(assets, multipliers.tolist())),
        "absolute_current_spots": dict(zip(assets, current.tolist())),
        "sigma_shifts": dict(zip(assets, sigma_shifts.tolist())),
    }
    return canonical, current, sigma_shifts


def _action_label(action: dict) -> str:
    kind = action.get("action")
    if kind == "accumulate":
        return f"накопление «{action.get('name')}»"
    if kind == "set":
        return f"запись «{action.get('name')}»"
    if kind == "pay":
        return "выплата (условная)" if "when" in action else "выплата"
    if kind == "terminate":
        return "досрочное погашение?"
    return str(kind)


def event_timeline(defn: dict) -> list[dict]:
    """Generated event/cashflow timeline (spec §16.3) — data, not pixels."""
    slots = defn.get("slots") or {}
    sched = defn.get("schedule") or {}
    n_obs = int(_resolve_scalar(sched.get("observations"), slots) or 0)
    maturity = float(_resolve_scalar(sched.get("maturity"), slots) or 0.0)
    if n_obs < 1 or maturity <= 0:
        return []
    obs_events = [_action_label(a) for a in defn.get("observation_program") or []]
    timeline = [{"t": round(maturity * (i + 1) / n_obs, 6),
                 "kind": "observation", "events": obs_events}
                for i in range(n_obs)]
    timeline.append({"t": round(maturity, 6), "kind": "maturity",
                     "events": [_action_label(a)
                                for a in defn.get("maturity_program") or []]})
    return timeline


def economic_summary(defn: dict) -> str:
    """Mechanically generated natural-language summary (spec §16.3)."""
    slots = defn.get("slots") or {}
    sched = defn.get("schedule") or {}
    n_obs = _resolve_scalar(sched.get("observations"), slots)
    maturity = _resolve_scalar(sched.get("maturity"), slots)
    lines = [f"{int(n_obs or 0)} наблюдений до погашения через {maturity} лет."]
    for action in defn.get("observation_program") or []:
        kind = action.get("action")
        if kind == "terminate":
            lines.append("На дате наблюдения возможно досрочное погашение (autocall).")
        elif kind == "accumulate":
            lines.append(f"Начисление в state '{action.get('name')}' на каждой дате.")
        elif kind == "pay":
            lines.append("Купонная выплата на дате наблюдения"
                         + (" (условная)." if "when" in action else "."))
    for action in defn.get("maturity_program") or []:
        if action.get("action") == "pay":
            lines.append("Финальная выплата на погашении"
                         + (" (условная)." if "when" in action else "."))
    if defn.get("state"):
        lines.append(f"State-переменные: {', '.join(defn['state'])}.")
    return " ".join(lines)


def compile_definition(defn: dict) -> dict:
    """Validate + compile + generate regression vectors (spec §16.4).

    Returns the full compile report; ``ok`` is False when any check failed."""
    issues = validate_definition(defn)
    report = {
        "ok": not issues,
        "issues": issues,
        "definition_hash": definition_hash(defn),
        "summary": None,
        "classification": None,
        "compatible_engines": [],
        "test_vectors": [],
        "timeline": [],
    }
    if issues:
        return report

    report["summary"] = economic_summary(defn)
    report["timeline"] = event_timeline(defn)
    n_assets = len(_asset_names(defn))
    uses_state = bool(defn.get("state"))
    uses_path = _mentions_node(defn, {"path_min", "path_max", "worst_path_min"})
    has_terminate = _mentions_action(defn, "terminate")
    report["classification"] = {
        "path_dependent": uses_state or uses_path,
        "early_redemption": has_terminate,
        "underlyings": n_assets,
        "dynamics": "gbm" if n_assets == 1 else "correlated_gbm",
    }
    report["compatible_engines"] = (["custom_mc_gbm"] if n_assets == 1
                                    else ["custom_mc_multi_gbm"])

    # Deterministic regression vectors (§16.4): flat / up / down scenarios.
    slots = {k: v.get("default") for k, v in (defn.get("slots") or {}).items()}
    for label, drift in (("flat", 0.0), ("up", 0.3), ("down", -0.4)):
        value = _deterministic_payoff(defn, slots, drift)
        report["test_vectors"].append({"scenario": label,
                                       "terminal_perf": round(1.0 + drift, 6),
                                       "pv": value})
    return report


def _mentions_node(defn, kinds: set[str]) -> bool:
    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("node") in kinds:
                return True
            return any(walk(v) for v in obj.values())
        if isinstance(obj, list):
            return any(walk(v) for v in obj)
        return False
    return walk(defn.get("observation_program")) or walk(defn.get("maturity_program"))


def _mentions_action(defn, kind: str) -> bool:
    programs = (defn.get("observation_program") or []) + (defn.get("maturity_program") or [])
    return any(isinstance(a, dict) and a.get("action") == kind for a in programs)


# ── evaluator: PayoffIR over paths ───────────────────────

class _Ctx:
    __slots__ = ("perfs", "run_min", "run_max", "t", "accrual",
                 "slots", "state")

    def __init__(self, perfs, run_min, run_max, t, accrual, slots, state):
        # perfs / run_min / run_max: (n_paths, n_assets) at the current obs
        self.perfs, self.run_min, self.run_max = perfs, run_min, run_max
        self.t, self.accrual = t, accrual
        self.slots, self.state = slots, state


def _eval(expr, ctx):
    kind = expr["node"]
    if kind == "const":
        return float(expr["value"])
    if kind == "param":
        return float(ctx.slots[expr["name"]])
    if kind == "state":
        return ctx.state[expr["name"]]
    if kind == "perf":
        return ctx.perfs[:, 0]
    if kind == "time":
        return ctx.t
    if kind == "accrual":
        return ctx.accrual
    if kind == "path_min":
        return ctx.run_min[:, 0]
    if kind == "path_max":
        return ctx.run_max[:, 0]
    if kind == "asset":
        return ctx.perfs[:, int(expr["index"])]
    if kind == "worst_of":
        return ctx.perfs.min(axis=1)
    if kind == "best_of":
        return ctx.perfs.max(axis=1)
    if kind == "basket_avg":
        return ctx.perfs.mean(axis=1)
    if kind == "weighted":
        return ctx.perfs @ np.asarray(expr["weights"], dtype=float)
    if kind == "nth_worst":
        return np.sort(ctx.perfs, axis=1)[:, int(expr["rank"]) - 1]
    if kind == "worst_path_min":
        return ctx.run_min.min(axis=1)
    a = expr.get("args", [])
    if kind == "add":
        return _eval(a[0], ctx) + _eval(a[1], ctx)
    if kind == "sub":
        return _eval(a[0], ctx) - _eval(a[1], ctx)
    if kind == "mul":
        return _eval(a[0], ctx) * _eval(a[1], ctx)
    if kind == "div":
        return _eval(a[0], ctx) / _eval(a[1], ctx)
    if kind == "neg":
        return -_eval(a[0], ctx)
    if kind == "min":
        return np.minimum(_eval(a[0], ctx), _eval(a[1], ctx))
    if kind == "max":
        return np.maximum(_eval(a[0], ctx), _eval(a[1], ctx))
    if kind == "ge":
        return _eval(a[0], ctx) >= _eval(a[1], ctx)
    if kind == "gt":
        return _eval(a[0], ctx) > _eval(a[1], ctx)
    if kind == "le":
        return _eval(a[0], ctx) <= _eval(a[1], ctx)
    if kind == "lt":
        return _eval(a[0], ctx) < _eval(a[1], ctx)
    if kind == "and":
        return np.logical_and(_eval(a[0], ctx), _eval(a[1], ctx))
    if kind == "or":
        return np.logical_or(_eval(a[0], ctx), _eval(a[1], ctx))
    if kind == "not":
        return np.logical_not(_eval(a[0], ctx))
    if kind == "if":
        return np.where(_eval(a[0], ctx), _eval(a[1], ctx), _eval(a[2], ctx))
    raise ValueError(f"unknown node '{kind}'")   # unreachable after compile


def _evaluate_paths(defn: dict, slots: dict, paths: np.ndarray,
                    times: np.ndarray, r: float, *,
                    initial_state: dict | None = None,
                    initial_running_min: np.ndarray | None = None,
                    initial_running_max: np.ndarray | None = None) -> dict:
    """Run the definition programs over pre-generated paths (perf terms).

    ``paths`` has shape (n_paths, n_steps+1, n_assets)."""
    sched = defn.get("schedule") or {}
    slot_specs = defn.get("slots") or {}
    n_obs = int(_resolve_scalar(sched.get("observations"), slot_specs, slots))
    maturity = float(_resolve_scalar(sched.get("maturity"), slot_specs, slots))
    obs_times = [maturity * (i + 1) / n_obs for i in range(n_obs)]

    n_paths, n_steps = paths.shape[0], paths.shape[1] - 1
    payoffs = np.zeros(n_paths)
    alive = np.ones(n_paths, dtype=bool)
    state_seed = ((defn.get("state") or {}) if initial_state is None
                  else initial_state)
    state = {k: np.full(n_paths, float(v)) for k, v in state_seed.items()}
    if initial_running_min is not None:
        initial_running_min = np.asarray(initial_running_min, dtype=float)[None, :]
    if initial_running_max is not None:
        initial_running_max = np.asarray(initial_running_max, dtype=float)[None, :]

    # Update path extrema once per newly visited time slice. The previous
    # implementation rescanned ``paths[:, :step]`` at every observation,
    # turning dense schedules into quadratic memory traffic.
    extrema_step = 0
    running_min = paths[:, 0, :].copy()
    running_max = paths[:, 0, :].copy()
    if initial_running_min is not None:
        running_min = np.minimum(running_min, initial_running_min)
    if initial_running_max is not None:
        running_max = np.maximum(running_max, initial_running_max)

    def _running_extrema(last_step: int) -> tuple[np.ndarray, np.ndarray]:
        nonlocal extrema_step, running_min, running_max
        if last_step < extrema_step:
            raise ValueError("observation schedule maps to decreasing path steps")
        if last_step > extrema_step:
            segment = paths[:, extrema_step + 1:last_step + 1, :]
            running_min = np.minimum(running_min, segment.min(axis=1))
            running_max = np.maximum(running_max, segment.max(axis=1))
            extrema_step = last_step
        return running_min, running_max

    prev_t = 0.0
    for t_obs in obs_times:
        step = min(int(round(t_obs / maturity * n_steps)), n_steps)
        running_min, running_max = _running_extrema(step)
        ctx = _Ctx(paths[:, step, :], running_min, running_max,
                   t_obs, t_obs - prev_t, slots, state)
        disc_t = np.exp(-r * t_obs)
        for action in defn.get("observation_program") or []:
            kind = action["action"]
            if kind == "set":
                value = _eval(action["value"], ctx)
                state[action["name"]] = np.where(alive, value, state[action["name"]])
            elif kind == "accumulate":
                value = _eval(action["value"], ctx)
                state[action["name"]] = state[action["name"]] + np.where(alive, value, 0.0)
            elif kind == "pay":
                mask = alive.copy()
                if "when" in action:
                    mask &= np.asarray(_eval(action["when"], ctx), dtype=bool)
                amount = _eval(action["amount"], ctx)
                payoffs += np.where(mask, disc_t * amount, 0.0)
            elif kind == "terminate":
                mask = alive & np.asarray(_eval(action["when"], ctx), dtype=bool)
                if mask.any():
                    payout = _eval(action["payout"], ctx)
                    payoffs = np.where(mask, payoffs + disc_t * payout, payoffs)
                    alive = alive & ~mask
                    for name in state:
                        state[name] = np.where(mask, 0.0, state[name])
        prev_t = t_obs

    running_min, running_max = _running_extrema(n_steps)
    ctx = _Ctx(paths[:, -1, :], running_min, running_max,
               maturity, maturity - (obs_times[-2] if n_obs > 1 else 0.0),
               slots, state)
    disc_T = np.exp(-r * maturity)
    for action in defn.get("maturity_program") or []:
        kind = action["action"]
        if kind == "set":
            value = _eval(action["value"], ctx)
            state[action["name"]] = np.where(alive, value, state[action["name"]])
        elif kind == "accumulate":
            value = _eval(action["value"], ctx)
            state[action["name"]] = state[action["name"]] + np.where(alive, value, 0.0)
        elif kind == "pay":
            mask = alive.copy()
            if "when" in action:
                mask &= np.asarray(_eval(action["when"], ctx), dtype=bool)
            amount = _eval(action["amount"], ctx)
            payoffs += np.where(mask, disc_T * amount, 0.0)

    early = float((~alive).mean())
    return {"payoffs": payoffs, "early_redemption_prob": early}


def _deterministic_payoff(defn: dict, slots: dict, drift: float) -> float:
    """One synthetic linear scenario — regression vector. Asset i drifts to
    1+drift−0.05·i so multi-asset aggregations are actually exercised."""
    sched = defn.get("schedule") or {}
    slot_specs = defn.get("slots") or {}
    n_obs = int(_resolve_scalar(sched.get("observations"), slot_specs, slots) or 1)
    n_assets = len(_asset_names(defn))
    steps = max(n_obs * 4, 8)
    path = np.stack([np.linspace(1.0, 1.0 + drift - 0.05 * i, steps + 1)
                     for i in range(n_assets)], axis=1)[None, :, :]
    maturity = float(_resolve_scalar(sched.get("maturity"), slot_specs, slots) or 1.0)
    result = _evaluate_paths(defn, slots, path, np.linspace(0, maturity, steps + 1), r=0.0)
    return float(result["payoffs"][0])


def _price_definition_core(defn: dict, slots: dict, market: dict,
                           n_sims: int = 50_000, steps: int = 252,
                           seed: int = 42, *,
                           valuation_state: dict | None = None,
                           scenario: dict | None = None,
                           require_explicit_state: bool = False) -> dict:
    """Price an AST from a canonical state plus an instantaneous scenario."""
    issues = validate_definition(defn)
    if issues:
        raise ValueError("определение не проходит компиляцию: "
                         + "; ".join(i["message"] for i in issues[:3]))
    def _finite(value, label: str) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{label}: требуется число") from exc
        if not np.isfinite(numeric):
            raise ValueError(f"{label}: значение должно быть конечным")
        return numeric

    def _bounded_int(value, label: str, lower: int, upper: int) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{label}: требуется целое число")
        numeric = _finite(value, label)
        integer = int(numeric)
        if numeric != integer or not lower <= integer <= upper:
            raise ValueError(f"{label}: требуется целое число {lower} … {upper}")
        return integer

    slot_specs = defn.get("slots") or {}
    merged = {k: _finite(v.get("default"), f"слот '{k}'")
              for k, v in slot_specs.items()}
    for key, value in (slots or {}).items():
        if key not in slot_specs:
            raise ValueError(f"неизвестный слот '{key}'")
        spec = slot_specs[key]
        value = _finite(value, f"слот '{key}'")
        if spec.get("min") is not None and value < spec["min"]:
            raise ValueError(f"слот '{key}': {value} ниже минимума {spec['min']}")
        if spec.get("max") is not None and value > spec["max"]:
            raise ValueError(f"слот '{key}': {value} выше максимума {spec['max']}")
        merged[key] = value

    assets = _asset_names(defn)
    n_assets = len(assets)
    canonical_state, state_source = _canonical_valuation_state(
        defn, valuation_state, require_explicit=require_explicit_state,
    )
    base_current = _asset_vector(canonical_state["current_spots"], assets,
                                 "current_spots", positive=True)
    reference_spots = _asset_vector(canonical_state["reference_spots"], assets,
                                    "reference_spots", positive=True)
    canonical_scenario, scenario_current, sigma_shifts = _canonical_scenario(
        scenario, assets, base_current,
    )
    initial_performances = scenario_current / reference_spots
    initial_running_min = _asset_vector(
        canonical_state["running_min"], assets, "running_min", positive=True,
    )
    initial_running_max = _asset_vector(
        canonical_state["running_max"], assets, "running_max", positive=True,
    )
    r = _finite(market.get("r", 0.05), "market.r")
    if not -1.0 <= r <= 2.0:
        raise ValueError("market.r: значение должно быть в диапазоне -1 … 2")
    sched = defn.get("schedule") or {}
    maturity = _finite(
        _resolve_scalar(sched.get("maturity"), slot_specs, merged),
        "schedule.maturity",
    )
    if maturity <= 0:
        raise ValueError("schedule.maturity: срок должен быть положительным")
    n_sims = _bounded_int(n_sims, "n_sims", 1_000, 200_000)
    steps = _bounded_int(steps, "steps", 16, 1_024)
    seed = _bounded_int(seed, "seed", 0, 2_147_483_647)
    resource_budget = custom_mc_resource_budget(
        n_assets, n_sims, steps, include_greeks=False,
    )

    def _vector(key_list, key_scalar, default):
        listed = market.get(key_list)
        if listed is not None:
            values = [_finite(v, f"market.{key_list}[{index}]")
                      for index, v in enumerate(listed)]
            if len(values) != n_assets:
                raise ValueError(f"{key_list}: нужно {n_assets} значений "
                                 f"(активы {', '.join(assets)})")
            return np.asarray(values)
        return np.full(
            n_assets,
            _finite(market.get(key_scalar, default), f"market.{key_scalar}"),
        )

    sigma_vec = _vector("sigmas", "sigma", 0.2) + sigma_shifts
    q_vec = _vector("qs", "q", 0.0)
    if np.any((sigma_vec < 0.0) | (sigma_vec > 5.0)):
        raise ValueError("market.sigmas: значения должны быть в диапазоне 0 … 5")
    if np.any((q_vec < -1.0) | (q_vec > 1.0)):
        raise ValueError("market.qs: значения должны быть в диапазоне -1 … 1")

    if n_assets == 1:
        paths = gbm_paths(float(initial_performances[0]), r, float(q_vec[0]),
                          float(sigma_vec[0]),
                          maturity, steps, n_sims, seed=seed)[:, :, None]
        corr_out = None
    else:
        corr_raw = market.get("corr")
        if corr_raw is not None:
            try:
                corr = np.asarray(corr_raw, dtype=float)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("corr: все элементы должны быть числами") from exc
            if corr.shape != (n_assets, n_assets):
                raise ValueError(f"corr: нужна матрица {n_assets}×{n_assets}")
        else:
            rho = _finite(market.get("rho", 0.5), "market.rho")
            if not -0.999 <= rho <= 0.999:
                raise ValueError("market.rho: значение должно быть в диапазоне -0.999 … 0.999")
            corr = np.full((n_assets, n_assets), rho)
            np.fill_diagonal(corr, 1.0)
        if not np.all(np.isfinite(corr)):
            raise ValueError("corr: все элементы должны быть конечными")
        if np.any(np.abs(corr) > 1.0):
            raise ValueError("corr: корреляции должны быть в диапазоне -1 … 1")
        if not np.allclose(corr, corr.T, rtol=0.0, atol=1e-12):
            raise ValueError("corr: матрица должна быть симметричной")
        if not np.allclose(np.diag(corr), 1.0, rtol=0.0, atol=1e-12):
            raise ValueError("corr: диагональ должна быть равна 1")
        try:
            np.linalg.cholesky(corr)
            raw = multi_asset_paths(initial_performances, r, q_vec, sigma_vec,
                                    corr, maturity, steps, n_sims,
                                    seed=seed)
        except np.linalg.LinAlgError:
            raise ValueError("корреляционная матрица не положительно "
                             "определена") from None
        paths = raw.transpose(0, 2, 1)      # → (n_sims, steps+1, n_assets)
        corr_out = corr.tolist()

    result = _evaluate_paths(
        defn, merged, paths, np.linspace(0, maturity, steps + 1), r=r,
        initial_state=canonical_state["state_values"],
        initial_running_min=initial_running_min,
        initial_running_max=initial_running_max,
    )
    payoffs = result["payoffs"]
    market_out = {"r": r, "sigmas": sigma_vec.tolist(), "qs": q_vec.tolist()}
    if corr_out is not None:
        market_out["corr"] = corr_out
    repricing_evidence = {
        "contract": _REPRICING_CONTRACT,
        "contract_version": _REPRICING_CONTRACT_VERSION,
        "state_mode": canonical_state["mode"],
        "state_source": state_source,
        "valuation_state_hash": _contract_hash(canonical_state),
        "scenario_hash": _contract_hash(canonical_scenario),
        "definition_hash": definition_hash(defn),
        "observation_index": canonical_state["observation_index"],
        "time_roll_years": 0.0,
        "current_performances": dict(zip(assets,
                                              initial_performances.tolist())),
        "common_random_numbers": {
            "enabled": True,
            "method": "same_seed_regeneration",
            "seed": seed,
        },
        "rng_contract": {
            "version": _RNG_CONTRACT_VERSION,
            "generator_api": "numpy.random.default_rng",
            "bit_generator": type(
                np.random.default_rng(seed).bit_generator).__name__,
            "numpy_version": np.__version__,
        },
        "seasoned_state_supported": False,
        "resource_budget": resource_budget,
    }
    return {
        "value": float(payoffs.mean()),
        "stderr": float(payoffs.std(ddof=1) / np.sqrt(n_sims)),
        "early_redemption_prob": result["early_redemption_prob"],
        "definition_hash": definition_hash(defn),
        "slots": merged,
        "assets": assets,
        "market": market_out,
        "valuation_state": canonical_state,
        "scenario": canonical_scenario,
        "repricing_evidence": repricing_evidence,
        "resource_budget": resource_budget,
        "n_sims": n_sims, "steps": steps, "seed": seed,
        "engine": "custom_mc_gbm" if n_assets == 1 else "custom_mc_multi_gbm",
    }


def price_definition(defn: dict, slots: dict, market: dict,
                     n_sims: int = 50_000, steps: int = 252,
                     seed: int = 42, *,
                     valuation_state: dict | None = None) -> dict:
    """Price a compiled definition from a unit or explicit inception state.

    Existing callers without a state retain exact S0=1 behaviour.  Risk and
    scenario callers should use :func:`scenario_price_definition`, which
    requires the complete canonical state contract.
    """
    return _price_definition_core(
        defn, slots, market, n_sims=n_sims, steps=steps, seed=seed,
        valuation_state=valuation_state, scenario=None,
        require_explicit_state=False,
    )


def scenario_price_definition(defn: dict, slots: dict, market: dict,
                              valuation_state: dict, scenario: dict | None,
                              n_sims: int = 50_000, steps: int = 252,
                              seed: int = 42) -> dict:
    """Canonical full reprice under one instantaneous market scenario."""
    return _price_definition_core(
        defn, slots, market, n_sims=n_sims, steps=steps, seed=seed,
        valuation_state=valuation_state, scenario=scenario,
        require_explicit_state=True,
    )


def component_greeks_definition(
    defn: dict, slots: dict, market: dict, valuation_state: dict,
    scenario: dict | None = None, n_sims: int = 50_000, steps: int = 252,
    seed: int = 42, *, spot_bump_relative: float = 0.005,
    volatility_bump: float = 0.01,
) -> dict:
    """CRN finite-difference Delta/Gamma/Vega for every logical asset slot.

    Delta and Gamma are per one absolute spot unit.  Vega follows the rest of
    the platform and is dPV for +1 volatility point (0.01 absolute sigma).
    All legs regenerate the exact same random stream from ``seed``.
    """
    try:
        spot_bump_relative = float(spot_bump_relative)
        volatility_bump = float(volatility_bump)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Greek bumps must be numeric") from exc
    if (not np.isfinite(spot_bump_relative)
            or not 0.0 < spot_bump_relative < 1.0):
        raise ValueError("spot_bump_relative must be finite and in (0, 1)")
    if (not np.isfinite(volatility_bump)
            or not 0.0 < volatility_bump <= 1.0):
        raise ValueError("volatility_bump must be finite and in (0, 1]")

    # Combined Greek work is checked before the base valuation allocates its
    # first path cube.  Each asset has two spot and two volatility bumps.
    resource_budget = custom_mc_resource_budget(
        len(_asset_names(defn)), n_sims, steps, include_greeks=True,
    )

    base = scenario_price_definition(
        defn, slots, market, valuation_state, scenario,
        n_sims=n_sims, steps=steps, seed=seed,
    )
    assets = list(base["assets"])
    base_value = float(base["value"])
    current = _asset_vector(
        base["scenario"]["absolute_current_spots"], assets,
        "absolute_current_spots", positive=True,
    )
    base_sigma = np.asarray(base["market"]["sigmas"], dtype=float)
    # Scenario shifts are relative to the unshocked market sigma, so preserve
    # the input shift and add each Greek bump to that vector.
    base_sigma_shifts = _asset_vector(
        base["scenario"]["sigma_shifts"], assets, "sigma_shifts",
    )

    def _scenario_at(spots: np.ndarray,
                     shifts: np.ndarray) -> dict:
        return {
            "schema_version": _REPRICING_CONTRACT_VERSION,
            "absolute_current_spots": dict(zip(assets, spots.tolist())),
            "sigma_shifts": dict(zip(assets, shifts.tolist())),
        }

    def _value(spots: np.ndarray, shifts: np.ndarray) -> float:
        return float(scenario_price_definition(
            defn, slots, market, valuation_state,
            _scenario_at(spots, shifts), n_sims=n_sims, steps=steps,
            seed=seed,
        )["value"])

    components: dict[str, dict] = {}
    repricings = 1
    for index, asset_name in enumerate(assets):
        spot_bump = abs(float(current[index])) * spot_bump_relative
        up_spots = current.copy()
        down_spots = current.copy()
        up_spots[index] += spot_bump
        down_spots[index] -= spot_bump
        up_value = _value(up_spots, base_sigma_shifts)
        down_value = _value(down_spots, base_sigma_shifts)
        repricings += 2
        delta = (up_value - down_value) / (2.0 * spot_bump)
        gamma = (up_value - 2.0 * base_value + down_value) / spot_bump ** 2

        up_shifts = base_sigma_shifts.copy()
        down_shifts = base_sigma_shifts.copy()
        if (base_sigma[index] - volatility_bump >= 0.0
                and base_sigma[index] + volatility_bump <= 5.0):
            up_shifts[index] += volatility_bump
            down_shifts[index] -= volatility_bump
            vol_up = _value(current, up_shifts)
            vol_down = _value(current, down_shifts)
            vega = ((vol_up - vol_down) / (2.0 * volatility_bump)) * 0.01
            vega_method = "central"
            repricings += 2
        elif base_sigma[index] + volatility_bump <= 5.0:
            up_shifts[index] += volatility_bump
            vol_up = _value(current, up_shifts)
            vega = ((vol_up - base_value) / volatility_bump) * 0.01
            vega_method = "forward_boundary"
            repricings += 1
        else:
            down_shifts[index] -= volatility_bump
            vol_down = _value(current, down_shifts)
            vega = ((base_value - vol_down) / volatility_bump) * 0.01
            vega_method = "backward_boundary"
            repricings += 1
        components[asset_name] = {
            "asset_name": asset_name,
            "asset_index": index,
            "spot": float(current[index]),
            "reference_spot": float(_asset_vector(
                base["valuation_state"]["reference_spots"], assets,
                "reference_spots", positive=True,
            )[index]),
            "delta": float(delta),
            "gamma": float(gamma),
            "vega": float(vega),
            "bump": {
                "spot_relative": spot_bump_relative,
                "spot_absolute": float(spot_bump),
                "volatility_absolute": volatility_bump,
            },
            "method": {
                "delta": "central",
                "gamma": "central",
                "vega": vega_method,
            },
        }

    base["component_greeks"] = components
    base["greeks_evidence"] = {
        "method": "finite_difference_common_random_numbers",
        "asset_key": "logical_definition_asset_name",
        "seed": base["seed"],
        "paths": base["n_sims"],
        "steps": base["steps"],
        "repricings": repricings,
        "units": {
            "delta": "dPV per +1 absolute spot unit",
            "gamma": "d2PV per squared absolute spot unit",
            "vega": "dPV per +1 volatility point (0.01 absolute sigma)",
        },
        "bumps": {
            "spot_relative": spot_bump_relative,
            "volatility_absolute": volatility_bump,
        },
        "common_random_numbers": {
            "enabled": True,
            "method": "same_seed_regeneration",
            "seed": base["seed"],
        },
        "rng_contract": dict(base["repricing_evidence"]["rng_contract"]),
        "valuation_state_hash": base["repricing_evidence"][
            "valuation_state_hash"],
        "scenario_hash": base["repricing_evidence"]["scenario_hash"],
        "definition_hash": base["definition_hash"],
        "resource_budget": resource_budget,
    }
    base["resource_budget"] = resource_budget
    base["repricing_evidence"]["resource_budget"] = resource_budget
    return base


# ── store + lifecycle (spec §16.5, §20) ──────────────────

class CustomProductIntegrityError(ValueError):
    """Persisted custom-product economics failed an integrity check."""


class CustomProductStore:
    """Versioned definitions persisted as one JSON document; published
    versions are immutable — edits fork a new draft version."""

    def __init__(self, path: str):
        self.path = path
        self._data: dict[str, dict] = {}
        self._load()
        self._seed_templates()          # idempotent: fills in missing seeds

    # ── persistence ──────────────────────────────────────
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                loaded = json.load(fh)
        except FileNotFoundError:
            self._data = {}
            return
        except json.JSONDecodeError as exc:
            raise CustomProductIntegrityError(
                "custom product store is not valid JSON") from exc
        self._validate_loaded_data(loaded)
        self._data = loaded

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ── helpers ──────────────────────────────────────────
    @staticmethod
    def _validated_version(product_id: str, item: object) -> tuple[dict, str]:
        """Return a version only when its persisted economics match its hash."""
        version = item.get("version", "?") if isinstance(item, dict) else "?"
        if not isinstance(item, dict) or not isinstance(item.get("definition"), dict):
            raise CustomProductIntegrityError(
                f"custom product '{product_id}' version {version} has an "
                "invalid definition record")
        stored_hash = item.get("definition_hash")
        if not isinstance(stored_hash, str) or not stored_hash:
            raise CustomProductIntegrityError(
                f"custom product '{product_id}' version {version} has no "
                "definition hash")
        actual_hash = definition_hash(item["definition"])
        if actual_hash != stored_hash:
            raise CustomProductIntegrityError(
                f"custom product '{product_id}' version {version} definition "
                "hash integrity mismatch")
        return item, actual_hash

    @classmethod
    def _validate_loaded_data(cls, loaded: object) -> None:
        if not isinstance(loaded, dict):
            raise CustomProductIntegrityError(
                "custom product store root must be an object")
        for product_id, product in loaded.items():
            if not isinstance(product_id, str) or not isinstance(product, dict):
                raise CustomProductIntegrityError(
                    "custom product store contains an invalid product record")
            versions = product.get("versions")
            if not isinstance(versions, list) or not versions:
                raise CustomProductIntegrityError(
                    f"custom product '{product_id}' has no version records")
            for item in versions:
                cls._validated_version(product_id, item)

    def _latest(self, product_id: str) -> dict:
        product = self._data.get(product_id)
        if not product or not product["versions"]:
            raise KeyError(f"unknown custom product '{product_id}'")
        return self._validated_version(
            product_id, product["versions"][-1])[0]

    def _version(self, product_id: str, version: int | None = None) -> dict:
        """Resolve an exact immutable definition version for replay."""
        product = self._data.get(product_id)
        if not product or not product["versions"]:
            raise KeyError(f"unknown custom product '{product_id}'")
        if version is None:
            return self._validated_version(
                product_id, product["versions"][-1])[0]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("custom product version must be a positive integer")
        for item in product["versions"]:
            validated = self._validated_version(product_id, item)[0]
            if validated.get("version") == version:
                return validated
        raise ValueError(
            f"custom product '{product_id}' has no version {version}")

    def list_products(self) -> list[dict]:
        out = []
        for pid, product in self._data.items():
            head = self._validated_version(pid, product["versions"][-1])[0]
            out.append({
                "id": pid, "name": head["definition"].get("name", pid),
                "version": head["version"], "state": head["state"],
                "author": head["definition"].get("author", ""),
                "definition_hash": head["definition_hash"],
                "is_template": bool(product.get("is_template")),
                "versions": len(product["versions"]),
            })
        return sorted(out, key=lambda p: p["name"])

    def get(self, product_id: str) -> dict:
        head = self._latest(product_id)
        return copy.deepcopy({
            "id": product_id, **head,
            "is_template": bool(self._data[product_id].get("is_template")),
        })

    def get_version(self, product_id: str, version: int) -> dict:
        """Return a defensive copy of one exact, integrity-checked version."""
        item = self._version(product_id, version)
        return copy.deepcopy({
            "id": product_id, **item,
            "is_template": bool(self._data[product_id].get("is_template")),
        })

    def templates(self) -> list[dict]:
        return [p for p in self.list_products()
                if p["is_template"] and p["state"] == "published"]

    # ── lifecycle ────────────────────────────────────────
    def create(self, definition: dict | None = None,
               template_id: str | None = None,
               name: str | None = None, author: str = "user",
               slot_defaults: dict | None = None) -> dict:
        """Template mode (clone published template, override slot defaults)
        or advanced mode (raw definition document)."""
        if template_id is not None:
            template = self._latest(template_id)
            if template["state"] != "published":
                raise ValueError("шаблон должен быть в состоянии published")
            definition = json.loads(json.dumps(template["definition"]))
            definition["author"] = author
            if name:
                definition["name"] = name
            for key, value in (slot_defaults or {}).items():
                if key not in (definition.get("slots") or {}):
                    raise ValueError(f"неизвестный слот шаблона '{key}'")
                definition["slots"][key]["default"] = float(value)
        elif definition is None:
            raise ValueError("нужен template_id или definition")
        else:
            definition = json.loads(json.dumps(definition))
            definition.setdefault("author", author)

        product_id = uuid.uuid4().hex[:10]
        version = {
            "version": 1, "state": "draft",
            "definition": definition,
            "definition_hash": definition_hash(definition),
            "created_at": time.time(), "author": author,
            "compile_report": None, "submitted_by": None, "approved_by": None,
            "from_template": template_id,
        }
        self._data[product_id] = {"versions": [version], "is_template": False}
        self._save()
        return self.get(product_id)

    def update_definition(self, product_id: str, definition: dict) -> dict:
        head = self._latest(product_id)
        if head["state"] in ("published", "deprecated"):
            raise ValueError("published-версия неизменяема — создай новую версию")
        head["definition"] = definition
        head["definition_hash"] = definition_hash(definition)
        head["state"] = "draft"                # any edit resets the pipeline
        head["compile_report"] = None
        head["submitted_by"] = head["approved_by"] = None
        self._save()
        return self.get(product_id)

    def compile(self, product_id: str) -> dict:
        head = self._latest(product_id)
        if head["state"] in ("published", "deprecated"):
            raise ValueError("published-версия уже скомпилирована и неизменяема")
        report = compile_definition(head["definition"])
        head["compile_report"] = report
        head["state"] = "tested" if report["ok"] else "draft"
        self._save()
        return self.get(product_id)

    def submit(self, product_id: str, user: str) -> dict:
        head = self._latest(product_id)
        if head["state"] != "tested":
            raise ValueError(f"submit возможен только из tested (сейчас {head['state']})")
        head["state"] = "submitted"
        head["submitted_by"] = user
        self._save()
        return self.get(product_id)

    def approve(self, product_id: str, user: str) -> dict:
        head = self._latest(product_id)
        if head["state"] != "submitted":
            raise ValueError(f"approve возможен только из submitted (сейчас {head['state']})")
        if user == head["author"]:
            raise ValueError("maker≠checker: автор не может согласовать сам себя")
        head["state"] = "approved"
        head["approved_by"] = user
        self._save()
        return self.get(product_id)

    def publish(self, product_id: str) -> dict:
        head = self._latest(product_id)
        if head["state"] != "approved":
            raise ValueError(f"publish возможен только из approved (сейчас {head['state']})")
        head["state"] = "published"
        self._save()
        return self.get(product_id)

    def deprecate(self, product_id: str) -> dict:
        head = self._latest(product_id)
        if head["state"] != "published":
            raise ValueError("deprecate применим только к published")
        head["state"] = "deprecated"
        self._save()
        return self.get(product_id)

    def new_version(self, product_id: str, author: str = "user") -> dict:
        product = self._data.get(product_id)
        if product is None:
            raise KeyError(f"unknown custom product '{product_id}'")
        head = product["versions"][-1]
        if head["state"] not in ("published", "deprecated"):
            raise ValueError("новая версия форкается только от published/deprecated")
        clone = json.loads(json.dumps(head["definition"]))
        product["versions"].append({
            "version": head["version"] + 1, "state": "draft",
            "definition": clone, "definition_hash": definition_hash(clone),
            "created_at": time.time(), "author": author,
            "compile_report": None, "submitted_by": None, "approved_by": None,
            "from_template": head.get("from_template"),
        })
        self._save()
        return self.get(product_id)

    def diff(self, product_id: str, v_old: int, v_new: int) -> dict:
        product = self._data.get(product_id)
        if product is None:
            raise KeyError(f"unknown custom product '{product_id}'")
        by_v = {v["version"]: v for v in product["versions"]}
        if v_old not in by_v or v_new not in by_v:
            raise ValueError("нет такой версии")
        changes = []
        _diff_walk(by_v[v_old]["definition"], by_v[v_new]["definition"], "", changes)
        return {"id": product_id, "from": v_old, "to": v_new,
                "from_hash": by_v[v_old]["definition_hash"],
                "to_hash": by_v[v_new]["definition_hash"],
                "changes": changes}

    def price(self, product_id: str, slots: dict, market: dict,
              n_sims: int = 50_000, steps: int = 252, seed: int = 42,
              *, version: int | None = None,
              expected_definition_hash: str | None = None) -> dict:
        head = self._version(product_id, version)
        trusted_hash = self._validated_version(product_id, head)[1]
        if (expected_definition_hash is not None
                and str(expected_definition_hash) != trusted_hash):
            raise ValueError(
                "custom product definition hash mismatch for requested version")
        # Fail closed: uncompiled economics never price (spec §4.2, §16.5).
        if head["state"] in ("draft", "deprecated"):
            raise ValueError(f"расчёт запрещён в состоянии '{head['state']}' — "
                             "сначала compile")
        result = price_definition(head["definition"], slots, market,
                                  n_sims=n_sims, steps=steps, seed=seed)
        post_price_hash = self._validated_version(product_id, head)[1]
        if post_price_hash != trusted_hash:
            raise CustomProductIntegrityError(
                "custom product definition changed during pricing")
        if result.get("definition_hash") != trusted_hash:
            raise CustomProductIntegrityError(
                "custom product pricing result definition hash mismatch")
        result["state"] = head["state"]
        result["version"] = head["version"]
        # Research watermark for anything not fully published (spec §20).
        result["watermark"] = None if head["state"] == "published" else "research"
        return result

    def reprice(self, product_id: str, slots: dict, market: dict, *,
                valuation_state: dict, scenario: dict | None = None,
                n_sims: int = 50_000, steps: int = 252, seed: int = 42,
                version: int | None = None,
                expected_definition_hash: str | None = None,
                include_greeks: bool = False,
                spot_bump_relative: float = 0.005,
                volatility_bump: float = 0.01) -> dict:
        """Integrity-checked canonical scenario reprice for risk workflows."""
        head = self._version(product_id, version)
        trusted_hash = self._validated_version(product_id, head)[1]
        if (expected_definition_hash is not None
                and str(expected_definition_hash) != trusted_hash):
            raise ValueError(
                "custom product definition hash mismatch for requested version")
        if head["state"] in ("draft", "deprecated"):
            raise ValueError(f"расчёт запрещён в состоянии '{head['state']}' — "
                             "сначала compile")
        if include_greeks:
            result = component_greeks_definition(
                head["definition"], slots, market, valuation_state, scenario,
                n_sims=n_sims, steps=steps, seed=seed,
                spot_bump_relative=spot_bump_relative,
                volatility_bump=volatility_bump,
            )
        else:
            result = scenario_price_definition(
                head["definition"], slots, market, valuation_state, scenario,
                n_sims=n_sims, steps=steps, seed=seed,
            )
        post_price_hash = self._validated_version(product_id, head)[1]
        if post_price_hash != trusted_hash:
            raise CustomProductIntegrityError(
                "custom product definition changed during scenario repricing")
        if result.get("definition_hash") != trusted_hash:
            raise CustomProductIntegrityError(
                "custom product repricing result definition hash mismatch")
        result["product_id"] = product_id
        result["state"] = head["state"]
        result["version"] = head["version"]
        result["watermark"] = (None if head["state"] == "published"
                               else "research")
        result["repricing_evidence"]["product_id"] = product_id
        result["repricing_evidence"]["definition_version"] = head["version"]
        return result

    def component_greeks(
        self, product_id: str, slots: dict, market: dict, *,
        valuation_state: dict, scenario: dict | None = None,
        n_sims: int = 50_000, steps: int = 252, seed: int = 42,
        version: int | None = None,
        expected_definition_hash: str | None = None,
        spot_bump_relative: float = 0.005,
        volatility_bump: float = 0.01,
    ) -> dict:
        """Version-pinned component Greeks, keyed by definition asset name."""
        return self.reprice(
            product_id, slots, market, valuation_state=valuation_state,
            scenario=scenario, n_sims=n_sims, steps=steps, seed=seed,
            version=version,
            expected_definition_hash=expected_definition_hash,
            include_greeks=True,
            spot_bump_relative=spot_bump_relative,
            volatility_bump=volatility_bump,
        )

    # ── seed templates ───────────────────────────────────
    def _seed_templates(self):
        changed = False
        for template in (_phoenix_template(), _reverse_convertible_template(),
                         _worst_of_barrier_rc_template()):
            product_id = template["name"].lower().replace(" ", "_").replace("-", "_")
            if product_id in self._data:
                continue
            report = compile_definition(template)
            assert report["ok"], report["issues"]
            self._data[product_id] = {
                "is_template": True,
                "versions": [{
                    "version": 1, "state": "published",
                    "definition": template,
                    "definition_hash": report["definition_hash"],
                    "created_at": time.time(), "author": "riskcalc-seed",
                    "compile_report": report,
                    "submitted_by": "riskcalc-seed", "approved_by": "model-governance",
                    "from_template": None,
                }],
            }
            changed = True
        if changed:
            self._save()


def _diff_walk(old, new, path, changes):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            sub = f"{path}.{key}" if path else key
            if key not in old:
                changes.append({"path": sub, "kind": "added", "to": new[key]})
            elif key not in new:
                changes.append({"path": sub, "kind": "removed", "from": old[key]})
            else:
                _diff_walk(old[key], new[key], sub, changes)
    elif isinstance(old, list) and isinstance(new, list):
        if old != new:
            if len(old) != len(new):
                changes.append({"path": path, "kind": "changed",
                                "from": f"{len(old)} элементов",
                                "to": f"{len(new)} элементов"})
            else:
                for i, (a, b) in enumerate(zip(old, new)):
                    _diff_walk(a, b, f"{path}[{i}]", changes)
    elif old != new:
        changes.append({"path": path, "kind": "changed", "from": old, "to": new})


# ── seeded template definitions ──────────────────────────

def _n(kind, *args, **kw):
    node = {"node": kind, **kw}
    if args:
        node["args"] = list(args)
    return node


def _phoenix_template() -> dict:
    """Phoenix/autocall assembled purely from AST primitives — the phase 4
    exit criterion: no product-specific Swift or Python pricing code."""
    coupon = _n("mul", _n("param", name="coupon_rate"), _n("accrual"))
    return {
        "name": "Phoenix Autocall",
        "description": "Автоколл с memory-купоном: досрочное погашение при "
                       "perf ≥ autocall-барьера, купон копится в памяти, "
                       "защита капитала до KI-барьера на погашении.",
        "author": "riskcalc-seed",
        "slots": {
            "T": {"label": "Maturity, y", "default": 2.0, "min": 0.25, "max": 10.0},
            "n_obs": {"label": "Observations", "default": 8, "min": 1, "max": 48},
            "autocall_barrier": {"label": "Autocall barrier", "default": 1.0,
                                 "min": 0.5, "max": 1.5},
            "ki_barrier": {"label": "Knock-in barrier", "default": 0.65,
                           "min": 0.1, "max": 1.0},
            "coupon_rate": {"label": "Coupon p.a.", "default": 0.10,
                            "min": 0.0, "max": 1.0},
        },
        "state": {"memory": 0.0},
        "schedule": {"observations": {"slot": "n_obs"}, "maturity": {"slot": "T"}},
        "observation_program": [
            {"action": "accumulate", "name": "memory", "value": coupon},
            {"action": "terminate",
             "when": _n("ge", _n("perf"), _n("param", name="autocall_barrier")),
             "payout": _n("add", _n("const", value=1.0), _n("state", name="memory"))},
        ],
        "maturity_program": [
            {"action": "pay",
             "amount": _n("add",
                          _n("if",
                             _n("ge", _n("perf"), _n("param", name="ki_barrier")),
                             _n("const", value=1.0),
                             _n("perf")),
                          _n("state", name="memory"))},
        ],
    }


def _reverse_convertible_template() -> dict:
    """Reverse convertible via the path_min primitive (barrier monitoring)."""
    ki_hit = _n("le", _n("path_min"), _n("param", name="ki_barrier"))
    return {
        "name": "Reverse Convertible",
        "description": "Купон гарантирован; если барьер пробит и perf < 1 на "
                       "погашении — поставка акции (линейное участие вниз).",
        "author": "riskcalc-seed",
        "slots": {
            "T": {"label": "Maturity, y", "default": 1.0, "min": 0.25, "max": 5.0},
            "ki_barrier": {"label": "Knock-in barrier", "default": 0.70,
                           "min": 0.1, "max": 1.0},
            "coupon_rate": {"label": "Coupon p.a.", "default": 0.12,
                            "min": 0.0, "max": 1.0},
        },
        "state": {},
        "schedule": {"observations": 1, "maturity": {"slot": "T"}},
        "observation_program": [],
        "maturity_program": [
            {"action": "pay",
             "amount": _n("add",
                          _n("if",
                             _n("and", ki_hit, _n("lt", _n("perf"), _n("const", value=1.0))),
                             _n("perf"),
                             _n("const", value=1.0)),
                          _n("mul", _n("param", name="coupon_rate"),
                             _n("param", name="T")))},
        ],
    }


def _worst_of_barrier_rc_template() -> dict:
    """Worst-of Barrier Reverse Convertible on a 2-asset basket — exercises
    the multi-asset primitives (worst_of, worst_path_min, spec §16.2)."""
    ki_hit = _n("le", _n("worst_path_min"), _n("param", name="ki_barrier"))
    return {
        "name": "Worst-of Barrier RC",
        "description": "Купон гарантирован; барьер мониторится по ХУДШЕМУ "
                       "активу корзины непрерывно; при пробое и worst < 1 на "
                       "погашении — поставка худшего актива.",
        "author": "riskcalc-seed",
        "assets": ["Asset A", "Asset B"],
        "slots": {
            "T": {"label": "Maturity, y", "default": 1.0, "min": 0.25, "max": 5.0},
            "ki_barrier": {"label": "Knock-in barrier", "default": 0.70,
                           "min": 0.1, "max": 1.0},
            "coupon_rate": {"label": "Coupon p.a.", "default": 0.15,
                            "min": 0.0, "max": 1.0},
        },
        "state": {},
        "schedule": {"observations": 1, "maturity": {"slot": "T"}},
        "observation_program": [],
        "maturity_program": [
            {"action": "pay",
             "amount": _n("add",
                          _n("if",
                             _n("and", ki_hit,
                                _n("lt", _n("worst_of"), _n("const", value=1.0))),
                             _n("worst_of"),
                             _n("const", value=1.0)),
                          _n("mul", _n("param", name="coupon_rate"),
                             _n("param", name="T")))},
        ],
    }


_STORE: CustomProductStore | None = None


def get_store(path: str | None = None) -> CustomProductStore:
    global _STORE
    if _STORE is None:
        default = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "custom_products.json")
        _STORE = CustomProductStore(path or default)
    return _STORE
