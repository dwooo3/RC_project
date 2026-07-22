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
from datetime import date as _date
import hashlib
import json
import math
import os
import tempfile
import time
import uuid

import numpy as np

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

    raw_slots = defn.get("slots")
    if raw_slots is not None and not isinstance(raw_slots, dict):
        _issue(issues, "SCHEMA_TYPE", "slots должен быть объектом", "slots")
        slots = {}
    else:
        slots = raw_slots or {}
    for name, spec in slots.items():
        path = f"slots.{name}"
        if not isinstance(spec, dict):
            _issue(issues, "SCHEMA_TYPE", f"слот '{name}' должен быть объектом", path)
            continue
        default = spec.get("default")
        if (isinstance(default, bool)
                or not isinstance(default, (int, float))
                or not np.isfinite(float(default))):
            _issue(issues, "SCHEMA_TYPE",
                   f"слот '{name}' должен иметь конечный числовой default",
                   path)
            continue
        bounds: dict[str, float] = {}
        for bound_name in ("min", "max"):
            if spec.get(bound_name) is None:
                continue
            bound = spec[bound_name]
            if (isinstance(bound, bool)
                    or not isinstance(bound, (int, float))
                    or not np.isfinite(float(bound))):
                _issue(issues, "SCHEMA_TYPE",
                       f"slots.{name}.{bound_name} должен быть конечным числом",
                       f"{path}.{bound_name}")
            else:
                bounds[bound_name] = float(bound)
        if ("min" in bounds and "max" in bounds
                and bounds["min"] > bounds["max"]):
            _issue(issues, "SCHEMA_TYPE", f"слот '{name}': min выше max", path)
        if "min" in bounds and float(default) < bounds["min"]:
            _issue(issues, "SCHEMA_TYPE", f"слот '{name}': default ниже min", path)
        if "max" in bounds and float(default) > bounds["max"]:
            _issue(issues, "SCHEMA_TYPE", f"слот '{name}': default выше max", path)
    state = defn.get("state") or {}
    for name, init in state.items():
        if not isinstance(init, (int, float)) or isinstance(init, bool):
            _issue(issues, "CUSTOM_PRODUCT_UNDECLARED_STATE",
                   f"state '{name}' должен иметь числовое начальное значение",
                   f"state.{name}")

    raw_schedule = defn.get("schedule")
    if not isinstance(raw_schedule, dict):
        _issue(issues, "SCHEMA_TYPE", "schedule должен быть объектом", "schedule")
        sched = {}
    else:
        sched = raw_schedule
    n_obs = _resolve_scalar(sched.get("observations"), slots)
    maturity = _resolve_scalar(sched.get("maturity"), slots)
    valid_observations = False
    try:
        n_obs_number = float(n_obs)
        valid_observations = (
            np.isfinite(n_obs_number)
            and n_obs_number == int(n_obs_number)
            and 1 <= int(n_obs_number) <= 10_000
        )
    except (TypeError, ValueError, OverflowError):
        pass
    if not valid_observations:
        _issue(issues, "CUSTOM_PRODUCT_SCHEDULE_INVALID",
               "schedule.observations должен быть целым числом 1 … 10000",
               "schedule.observations")
    try:
        maturity_number = float(maturity)
        valid_maturity = np.isfinite(maturity_number) and maturity_number > 0.0
    except (TypeError, ValueError, OverflowError):
        valid_maturity = False
    if not valid_maturity:
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


def _resolved_slot_values(defn: dict, overrides: dict | None = None) -> dict:
    """Resolve one governed slot grid with bounds checked exactly once."""
    specs = defn.get("slots") or {}
    if not isinstance(specs, dict):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "definition.slots must be an object",
        )
    raw_overrides = overrides or {}
    if not isinstance(raw_overrides, dict):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "slot overrides must be an object",
        )
    unknown = sorted(set(raw_overrides) - set(specs))
    if unknown:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "неизвестный слот: " + ", ".join(unknown),
        )
    values = {}
    for name, spec in specs.items():
        if not isinstance(spec, dict) or "default" not in spec:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                f"definition slot {name} has no governed numeric default",
            )
        raw = raw_overrides.get(name, spec.get("default"))
        value = _contract_finite(raw, f"slots.{name}")
        minimum = (_contract_finite(spec["min"], f"slots.{name}.min")
                   if spec.get("min") is not None else None)
        maximum = (_contract_finite(spec["max"], f"slots.{name}.max")
                   if spec.get("max") is not None else None)
        if minimum is not None and maximum is not None and minimum > maximum:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                f"definition slot {name} has min above max",
            )
        if minimum is not None and value < minimum:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                f"слот '{name}': {value} ниже минимума {minimum}",
            )
        if maximum is not None and value > maximum:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                f"слот '{name}': {value} выше максимума {maximum}",
            )
        values[name] = value
    return values


def _resolved_schedule(defn: dict, slots: dict | None = None) -> tuple[int, float]:
    specs = defn.get("slots") or {}
    values = _resolved_slot_values(defn, slots)
    schedule = defn.get("schedule") or {}
    observations = _resolve_scalar(schedule.get("observations"), specs, values)
    maturity = _resolve_scalar(schedule.get("maturity"), specs, values)
    try:
        observations_number = float(observations)
        maturity_number = float(maturity)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "definition schedule cannot be resolved",
        ) from exc
    if (not np.isfinite(observations_number)
            or observations_number != int(observations_number)
            or not 1 <= int(observations_number) <= 10_000):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "schedule.observations must be an integer in [1, 10000]",
        )
    if not np.isfinite(maturity_number) or maturity_number <= 0.0:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "schedule.maturity must be positive",
        )
    return int(observations_number), maturity_number


def definition_hash(defn: dict) -> str:
    canon = json.dumps(defn, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


_REPRICING_CONTRACT = "custom_ast_scenario_repricing"
_REPRICING_CONTRACT_VERSION = 1
_RNG_CONTRACT_VERSION = 2
_VALUATION_STATE_KEYS = {
    "schema_version", "mode", "asset_names", "current_spots",
    "reference_spots", "observation_index", "state_values",
    "running_min", "running_max", "elapsed_time", "alive",
    "state_contract", "state_as_of", "state_source_hash",
    "instance_schedule_hash", "inception_seed_hash", "fixing_ledger_hash",
}
_SEASONED_STATE_CONTRACT = "custom_ast_seasoned_state_v1"
_INSTANCE_SCHEDULE_CONTRACT = "custom_ast_instance_schedule_v1"
_FIXING_LEDGER_CONTRACT = "custom_ast_dated_fixing_ledger_v1"
_INCEPTION_SEED_CONTRACT = "custom_ast_inception_seed_v1"
_HISTORICAL_RECONSTRUCTION_CONTRACT = (
    "custom_ast_historical_state_reconstruction_v1"
)
_DATED_PATH_ROLL_CONTRACT = "custom_ast_dated_path_roll_v1"
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
                              include_greeks: bool = False,
                              chunk_size: int | None = None) -> dict:
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

    if chunk_size is not None:
        try:
            parsed_chunk_size = int(chunk_size)
            numeric_chunk_size = float(chunk_size)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_RESOURCE_LIMIT",
                "chunk_size: требуется целое число",
            ) from exc
        if (isinstance(chunk_size, bool)
                or not np.isfinite(numeric_chunk_size)
                or parsed_chunk_size != numeric_chunk_size):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_RESOURCE_LIMIT", "chunk_size: требуется целое число")
        chunk_size = parsed_chunk_size
        if not 256 <= chunk_size <= 100_000:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_RESOURCE_LIMIT",
                "chunk_size: допустимый диапазон 256 … 100000",
            )
    peak_paths = parsed["paths"] if chunk_size is None else min(parsed["paths"], chunk_size)
    path_points = parsed["assets"] * peak_paths * (parsed["steps"] + 1)
    total_path_points = parsed["assets"] * parsed["paths"] * (parsed["steps"] + 1)
    estimated_peak_bytes = (
        path_points * _ESTIMATED_PEAK_BYTES_PER_PATH_POINT
    )
    # Worst-case ladder: base + per-asset spot/vol central bumps + two
    # parallel bumps + four corner repricings for every Hessian cross term.
    greek_repricings = (
        3 + 4 * parsed["assets"]
        + 4 * (parsed["assets"] * (parsed["assets"] - 1) // 2)
        if include_greeks else 1
    )
    work_path_points = total_path_points * greek_repricings
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
        "chunk_size": chunk_size,
        "chunked": bool(chunk_size is not None and chunk_size < parsed["paths"]),
        "total_path_points": total_path_points,
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


def _iso_contract_date(value: object, label: str, code: str) -> _date:
    """Parse one canonical JSON date without accepting timestamps/aliases."""
    if not isinstance(value, str) or not value:
        raise CustomProductRepricingError(code, f"{label} must be YYYY-MM-DD")
    try:
        parsed = _date.fromisoformat(value)
    except ValueError as exc:
        raise CustomProductRepricingError(
            code, f"{label} must be a valid ISO calendar date",
        ) from exc
    if parsed.isoformat() != value:
        raise CustomProductRepricingError(code, f"{label} must be YYYY-MM-DD")
    return parsed


def _sha256_contract_token(value: object, label: str, code: str) -> str:
    token = str(value or "").strip().lower()
    if (len(token) != 64
            or any(char not in "0123456789abcdef" for char in token)):
        raise CustomProductRepricingError(
            code, f"{label} must be a SHA-256 hex digest",
        )
    return token


def _strict_contract_keys(raw: object, *, label: str, allowed: set[str],
                          required: set[str], code: str) -> dict:
    if not isinstance(raw, dict):
        raise CustomProductRepricingError(code, f"{label} must be an object")
    unknown = sorted(set(raw) - allowed)
    missing = sorted(required - set(raw))
    if unknown or missing:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise CustomProductRepricingError(
            code, f"{label} schema mismatch: {'; '.join(details)}",
        )
    return raw


def canonical_instance_contract_schedule(
    defn: dict,
    contract_schedule: dict,
    *,
    slots: dict | None = None,
) -> dict:
    """Build/verify a dated instance schedule over resolved trading sessions.

    The calendar is evidence, not a calendar calculator: the caller passes the
    already-resolved session list (for example, MOEX securities sessions).
    This keeps historic replay deterministic when an upstream calendar later
    changes.  Re-feeding the canonical output verifies both embedded hashes.
    """
    code = "CUSTOM_PRODUCT_INSTANCE_SCHEDULE_INVALID"
    integrity_code = "CUSTOM_PRODUCT_INSTANCE_SCHEDULE_INTEGRITY"
    raw = _strict_contract_keys(
        contract_schedule,
        label="contract_schedule",
        allowed={
            "schema_version", "contract", "definition_hash",
            "resolved_slots_hash", "effective_date", "maturity_date",
            "observation_dates", "contractual_maturity_date",
            "contractual_observation_dates", "business_day_convention",
            "day_count_convention",
            "fixing_convention", "valuation_cutoff", "calendar",
            "schedule_hash",
        },
        required={
            "effective_date", "maturity_date", "observation_dates",
            "calendar",
        },
        code=code,
    )
    if raw.get("schema_version", 1) != 1:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_SCHEMA_UNSUPPORTED",
            "contract_schedule supports schema_version=1 only",
        )
    if raw.get("contract", _INSTANCE_SCHEDULE_CONTRACT) \
            != _INSTANCE_SCHEDULE_CONTRACT:
        raise CustomProductRepricingError(code, "unsupported schedule contract")

    resolved_slots = _resolved_slot_values(defn, slots)
    n_obs, _ = _resolved_schedule(defn, resolved_slots)
    expected_definition_hash = definition_hash(defn)
    expected_slots_hash = _contract_hash(resolved_slots)
    if (raw.get("definition_hash") is not None
            and raw["definition_hash"] != expected_definition_hash):
        raise CustomProductRepricingError(
            integrity_code, "contract_schedule definition_hash mismatch",
        )
    if (raw.get("resolved_slots_hash") is not None
            and raw["resolved_slots_hash"] != expected_slots_hash):
        raise CustomProductRepricingError(
            integrity_code, "contract_schedule resolved_slots_hash mismatch",
        )

    effective = _iso_contract_date(raw["effective_date"], "effective_date", code)
    maturity = _iso_contract_date(raw["maturity_date"], "maturity_date", code)
    if maturity <= effective:
        raise CustomProductRepricingError(
            code, "maturity_date must be after effective_date",
        )
    raw_observations = raw["observation_dates"]
    if not isinstance(raw_observations, list) or len(raw_observations) != n_obs:
        raise CustomProductRepricingError(
            code, f"observation_dates must contain exactly {n_obs} dates",
        )
    observations = [
        _iso_contract_date(value, f"observation_dates[{index}]", code)
        for index, value in enumerate(raw_observations)
    ]
    if any(left >= right for left, right in zip(observations, observations[1:])):
        raise CustomProductRepricingError(
            code, "observation_dates must be strictly increasing",
        )
    if observations[0] <= effective or observations[-1] != maturity:
        raise CustomProductRepricingError(
            code,
            "observations must be after effective_date and end on maturity_date",
        )

    contractual_maturity = _iso_contract_date(
        raw.get("contractual_maturity_date", maturity.isoformat()),
        "contractual_maturity_date", code,
    )
    raw_contractual_observations = raw.get(
        "contractual_observation_dates", raw_observations,
    )
    if (not isinstance(raw_contractual_observations, list)
            or len(raw_contractual_observations) != n_obs):
        raise CustomProductRepricingError(
            code,
            f"contractual_observation_dates must contain exactly {n_obs} dates",
        )
    contractual_observations = [
        _iso_contract_date(
            value, f"contractual_observation_dates[{index}]", code,
        )
        for index, value in enumerate(raw_contractual_observations)
    ]
    if any(left >= right for left, right in zip(
            contractual_observations, contractual_observations[1:])):
        raise CustomProductRepricingError(
            code, "contractual_observation_dates must be strictly increasing",
        )
    if (contractual_observations[0] <= effective
            or contractual_observations[-1] != contractual_maturity):
        raise CustomProductRepricingError(
            code, "contractual observations must end on contractual maturity",
        )
    business_day_convention = str(
        raw.get("business_day_convention", "UNADJUSTED")
    ).strip().upper()
    if business_day_convention not in {
        "UNADJUSTED", "FOLLOWING", "MODIFIED_FOLLOWING", "PRECEDING",
        "MODIFIED_PRECEDING",
    }:
        raise CustomProductRepricingError(
            code, "unsupported business_day_convention",
        )
    if (business_day_convention == "UNADJUSTED"
            and (contractual_observations != observations
                 or contractual_maturity != maturity)):
        raise CustomProductRepricingError(
            code, "UNADJUSTED dates cannot differ from resolved dates",
        )

    day_count = str(raw.get("day_count_convention", "ACT/365F")).strip()
    if day_count != "ACT/365F":
        raise CustomProductRepricingError(
            code, "dated custom-product v1 supports ACT/365F only",
        )
    fixing_convention = str(
        raw.get("fixing_convention", "MOEX_OFFICIAL_CLOSE")
    ).strip()
    if not fixing_convention:
        raise CustomProductRepricingError(code, "fixing_convention is required")
    valuation_cutoff = str(
        raw.get("valuation_cutoff", "POST_CLOSE_POST_EVENTS")
    ).strip()
    if valuation_cutoff != "POST_CLOSE_POST_EVENTS":
        raise CustomProductRepricingError(
            code, "dated state v1 requires POST_CLOSE_POST_EVENTS cutoff",
        )

    calendar = _strict_contract_keys(
        raw["calendar"],
        label="contract_schedule.calendar",
        allowed={
            "calendar_id", "source", "version", "payload_hash",
            "resolved_sessions", "source_hash",
        },
        required={"calendar_id", "source", "version", "resolved_sessions"},
        code=code,
    )
    calendar_id = str(calendar["calendar_id"]).strip()
    calendar_source = str(calendar["source"]).strip()
    calendar_version = str(calendar["version"]).strip()
    if not calendar_id or not calendar_source or not calendar_version:
        raise CustomProductRepricingError(
            code, "calendar_id, source and immutable version are required",
        )
    supplied_payload_hash = (
        calendar.get("payload_hash") if calendar.get("payload_hash") is not None
        else calendar.get("source_hash")
    )
    if supplied_payload_hash is None:
        raise CustomProductRepricingError(
            code, "calendar.payload_hash (official source digest) is required",
        )
    payload_hash = _sha256_contract_token(
        supplied_payload_hash, "calendar.payload_hash", integrity_code,
    )
    if calendar.get("source_hash") is not None:
        source_hash = _sha256_contract_token(
            calendar["source_hash"], "calendar.source_hash", integrity_code,
        )
        if source_hash != payload_hash:
            raise CustomProductRepricingError(
                integrity_code, "calendar payload_hash/source_hash mismatch",
            )
    raw_sessions = calendar["resolved_sessions"]
    if (not isinstance(raw_sessions, list) or not raw_sessions
            or len(raw_sessions) > 10_000):
        raise CustomProductRepricingError(
            code, "calendar.resolved_sessions must contain 1 … 10000 dates",
        )
    sessions = [
        _iso_contract_date(value, f"calendar.resolved_sessions[{index}]", code)
        for index, value in enumerate(raw_sessions)
    ]
    if any(left >= right for left, right in zip(sessions, sessions[1:])):
        raise CustomProductRepricingError(
            code, "calendar.resolved_sessions must be strictly increasing",
        )
    if sessions[0] != effective or sessions[-1] != maturity:
        raise CustomProductRepricingError(
            code,
            "resolved_sessions must cover exactly effective_date … maturity_date",
        )
    session_set = set(sessions)
    missing_events = [day.isoformat() for day in observations
                      if day not in session_set]
    if missing_events:
        raise CustomProductRepricingError(
            code, "event dates are not resolved trading sessions: "
            + ", ".join(missing_events),
        )

    def _adjust_contractual_date(day: _date) -> _date:
        if day in session_set:
            return day
        following = next((session for session in sessions if session > day), None)
        preceding = next(
            (session for session in reversed(sessions) if session < day), None,
        )
        if business_day_convention == "UNADJUSTED":
            raise CustomProductRepricingError(
                code, f"unadjusted event {day.isoformat()} is not a session",
            )
        if business_day_convention == "FOLLOWING":
            adjusted = following
        elif business_day_convention == "PRECEDING":
            adjusted = preceding
        elif business_day_convention == "MODIFIED_FOLLOWING":
            adjusted = (following if following is not None
                        and following.month == day.month else preceding)
        else:  # MODIFIED_PRECEDING
            adjusted = (preceding if preceding is not None
                        and preceding.month == day.month else following)
        if adjusted is None:
            raise CustomProductRepricingError(
                code, f"calendar cannot resolve event {day.isoformat()}",
            )
        return adjusted

    adjusted_observations = [
        _adjust_contractual_date(day) for day in contractual_observations
    ]
    if adjusted_observations != observations:
        raise CustomProductRepricingError(
            code,
            "resolved observation_dates do not match business-day convention",
        )
    calendar_payload = {
        "calendar_id": calendar_id,
        "source": calendar_source,
        "version": calendar_version,
        "payload_hash": payload_hash,
        "resolved_sessions": [day.isoformat() for day in sessions],
        "source_hash": payload_hash,
    }

    canonical = {
        "schema_version": 1,
        "contract": _INSTANCE_SCHEDULE_CONTRACT,
        "definition_hash": expected_definition_hash,
        "resolved_slots_hash": expected_slots_hash,
        "effective_date": effective.isoformat(),
        "maturity_date": maturity.isoformat(),
        "observation_dates": [day.isoformat() for day in observations],
        "contractual_maturity_date": contractual_maturity.isoformat(),
        "contractual_observation_dates": [
            day.isoformat() for day in contractual_observations
        ],
        "business_day_convention": business_day_convention,
        "day_count_convention": day_count,
        "fixing_convention": fixing_convention,
        "valuation_cutoff": valuation_cutoff,
        "calendar": calendar_payload,
    }
    expected_schedule_hash = _contract_hash(canonical)
    if raw.get("schedule_hash") is not None:
        supplied = _sha256_contract_token(
            raw["schedule_hash"], "schedule_hash", integrity_code,
        )
        if supplied != expected_schedule_hash:
            raise CustomProductRepricingError(
                integrity_code, "contract_schedule schedule_hash mismatch",
            )
    canonical["schedule_hash"] = expected_schedule_hash
    return canonical


def _contract_schedule_times(contract_schedule: dict) -> list[float]:
    effective = _date.fromisoformat(contract_schedule["effective_date"])
    return [
        (_date.fromisoformat(value) - effective).days / 365.0
        for value in contract_schedule["observation_dates"]
    ]


def _contract_schedule_elapsed(contract_schedule: dict, as_of: str) -> float:
    effective = _date.fromisoformat(contract_schedule["effective_date"])
    return (_date.fromisoformat(as_of) - effective).days / 365.0


def canonical_dated_fixing_ledger(
    defn: dict,
    contract_schedule: dict,
    fixing_ledger: dict,
    *,
    slots: dict | None = None,
) -> dict:
    """Build/verify an absolute-price ledger pinned to one instance schedule."""
    code = "CUSTOM_PRODUCT_FIXING_LEDGER_INVALID"
    integrity_code = "CUSTOM_PRODUCT_FIXING_LEDGER_INTEGRITY"
    schedule = canonical_instance_contract_schedule(
        defn, contract_schedule, slots=slots,
    )
    raw = _strict_contract_keys(
        fixing_ledger,
        label="fixing_ledger",
        allowed={
            "schema_version", "contract", "definition_hash", "schedule_hash",
            "asset_names", "source", "source_version", "payload_hash",
            "fixings", "source_hash", "ledger_hash",
        },
        required={"source", "source_version", "payload_hash", "fixings"},
        code=code,
    )
    if raw.get("schema_version", 1) != 1:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_SCHEMA_UNSUPPORTED",
            "fixing_ledger supports schema_version=1 only",
        )
    if raw.get("contract", _FIXING_LEDGER_CONTRACT) != _FIXING_LEDGER_CONTRACT:
        raise CustomProductRepricingError(code, "unsupported fixing ledger contract")
    if (raw.get("definition_hash") is not None
            and raw["definition_hash"] != definition_hash(defn)):
        raise CustomProductRepricingError(
            integrity_code, "fixing_ledger definition_hash mismatch",
        )
    if (raw.get("schedule_hash") is not None
            and raw["schedule_hash"] != schedule["schedule_hash"]):
        raise CustomProductRepricingError(
            integrity_code, "fixing_ledger schedule_hash mismatch",
        )
    assets = _asset_names(defn)
    if raw.get("asset_names") is not None and raw["asset_names"] != assets:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_ASSET_MISMATCH",
            "fixing_ledger.asset_names must match definition.assets",
        )
    source = str(raw["source"]).strip()
    source_version = str(raw["source_version"]).strip()
    if not source or not source_version:
        raise CustomProductRepricingError(
            code, "fixing_ledger source and immutable source_version are required",
        )
    payload_hash = _sha256_contract_token(
        raw["payload_hash"], "fixing_ledger.payload_hash", integrity_code,
    )
    raw_fixings = raw["fixings"]
    if (not isinstance(raw_fixings, list) or not raw_fixings
            or len(raw_fixings) > 10_000):
        raise CustomProductRepricingError(
            code, "fixing_ledger.fixings must contain 1 … 10000 rows",
        )
    session_set = set(schedule["calendar"]["resolved_sessions"])
    canonical_fixings = []
    fixing_dates: list[_date] = []
    for index, row in enumerate(raw_fixings):
        row = _strict_contract_keys(
            row,
            label=f"fixing_ledger.fixings[{index}]",
            allowed={"date", "spots"},
            required={"date", "spots"},
            code=code,
        )
        day = _iso_contract_date(row["date"], f"fixings[{index}].date", code)
        if day.isoformat() not in session_set:
            raise CustomProductRepricingError(
                code, f"fixing date {day.isoformat()} is not a resolved session",
            )
        spots = _asset_vector(
            row["spots"], assets, f"fixings[{index}].spots", positive=True,
        )
        fixing_dates.append(day)
        canonical_fixings.append({
            "date": day.isoformat(),
            "spots": dict(zip(assets, spots.tolist())),
        })
    if any(left >= right for left, right in zip(fixing_dates, fixing_dates[1:])):
        raise CustomProductRepricingError(
            code, "fixing rows must be strictly increasing and unique",
        )
    source_payload = {
        "source": source,
        "source_version": source_version,
        "payload_hash": payload_hash,
        "calendar_source_hash": schedule["calendar"]["source_hash"],
        "asset_names": assets,
        "fixings": canonical_fixings,
    }
    expected_source_hash = _contract_hash(source_payload)
    if raw.get("source_hash") is not None:
        supplied = _sha256_contract_token(
            raw["source_hash"], "fixing_ledger.source_hash", integrity_code,
        )
        if supplied != expected_source_hash:
            raise CustomProductRepricingError(
                integrity_code, "fixing_ledger source_hash mismatch",
            )
    canonical = {
        "schema_version": 1,
        "contract": _FIXING_LEDGER_CONTRACT,
        "definition_hash": definition_hash(defn),
        "schedule_hash": schedule["schedule_hash"],
        "asset_names": list(assets),
        "source": source,
        "source_version": source_version,
        "payload_hash": payload_hash,
        "fixings": canonical_fixings,
        "source_hash": expected_source_hash,
    }
    expected_ledger_hash = _contract_hash(canonical)
    if raw.get("ledger_hash") is not None:
        supplied = _sha256_contract_token(
            raw["ledger_hash"], "fixing_ledger.ledger_hash", integrity_code,
        )
        if supplied != expected_ledger_hash:
            raise CustomProductRepricingError(
                integrity_code, "fixing_ledger ledger_hash mismatch",
            )
    canonical["ledger_hash"] = expected_ledger_hash
    return canonical


def inception_valuation_seed(
    defn: dict,
    contract_schedule: dict,
    reference_spots: object,
    *,
    slots: dict | None = None,
    reference_source: str = "contractual_initial_fixing",
) -> dict:
    """Create the immutable origin from which dated states are reconstructed."""
    schedule = canonical_instance_contract_schedule(
        defn, contract_schedule, slots=slots,
    )
    assets = _asset_names(defn)
    reference = _asset_vector(
        reference_spots, assets, "reference_spots", positive=True,
    )
    source = str(reference_source).strip()
    if not source:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_INCEPTION_SEED_INVALID",
            "reference_source is required",
        )
    reference_fixing = {
        "date": schedule["effective_date"],
        "spots": dict(zip(assets, reference.tolist())),
        "source": source,
    }
    reference_fixing["source_hash"] = _contract_hash(reference_fixing)
    valuation_state = inception_valuation_state(
        defn, reference_spots, reference_spots,
    )
    valuation_state.update({
        "state_contract": None,
        "elapsed_time": 0.0,
        "alive": True,
        "state_as_of": schedule["effective_date"],
        "state_source_hash": reference_fixing["source_hash"],
        "instance_schedule_hash": schedule["schedule_hash"],
        "inception_seed_hash": None,
        "fixing_ledger_hash": None,
    })
    canonical = {
        "schema_version": 1,
        "contract": _INCEPTION_SEED_CONTRACT,
        "definition_hash": definition_hash(defn),
        "schedule_hash": schedule["schedule_hash"],
        "effective_date": schedule["effective_date"],
        "asset_names": list(assets),
        "reference_fixing": reference_fixing,
        "valuation_state": valuation_state,
    }
    canonical["seed_hash"] = _contract_hash(canonical)
    return canonical


def inception_valuation_state(defn: dict, current_spots: object,
                              reference_spots: object | None = None) -> dict:
    """Build the canonical state at contractual inception."""
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


def seasoned_valuation_state(
    defn: dict,
    current_spots: object,
    reference_spots: object,
    observation_index: int,
    *,
    state_values: dict | None = None,
    running_min: object | None = None,
    running_max: object | None = None,
    elapsed_time: float | None = None,
    alive: bool = True,
    slots: dict | None = None,
    state_as_of: str | None = None,
    state_source_hash: str | None = None,
) -> dict:
    """Build a validated state for a product already in progress.

    ``observation_index`` is the number of contractual observations already
    processed.  Spots are absolute current levels, while running extrema are
    performance ratios versus immutable contract fixings.  The helper is the
    canonical entry point for multi-day roll-forward and prevents callers from
    manufacturing a partially populated seasoned state by hand.
    """
    assets = _asset_names(defn)
    current = _asset_vector(current_spots, assets, "current_spots", positive=True)
    reference = _asset_vector(reference_spots, assets, "reference_spots", positive=True)
    n_obs, maturity = _resolved_schedule(defn, slots)
    if isinstance(observation_index, bool) or not isinstance(observation_index, int):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "observation_index должен быть целым числом",
        )
    if not 0 <= observation_index < n_obs:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            f"observation_index должен быть в диапазоне 0 … {n_obs - 1}",
        )
    if observation_index > 0 and (running_min is None or running_max is None):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "processed seasoned state requires explicit running extrema",
        )
    performance = current / reference
    run_min = performance if running_min is None else _asset_vector(
        running_min, assets, "running_min", positive=True)
    run_max = performance if running_max is None else _asset_vector(
        running_max, assets, "running_max", positive=True)
    if np.any(run_min > performance + 1e-12) or np.any(run_max < performance - 1e-12):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "running_min/running_max должны содержать текущую performance",
        )
    elapsed = (maturity * observation_index / n_obs
               if elapsed_time is None else float(elapsed_time))
    if not np.isfinite(elapsed) or not 0.0 < elapsed < maturity:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "elapsed_time должен быть в интервале (0, maturity)",
        )
    def _uses_path_extrema(value: object) -> bool:
        if isinstance(value, dict):
            if value.get("node") in {
                    "path_min", "path_max", "worst_path_min"}:
                return True
            return any(_uses_path_extrema(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(_uses_path_extrema(item) for item in value)
        return False

    if (_uses_path_extrema(defn)
            and (running_min is None or running_max is None)):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "seasoned path-dependent state requires explicit running extrema",
        )
    processed_time = maturity * observation_index / n_obs
    next_time = maturity * (observation_index + 1) / n_obs
    if elapsed < processed_time - 1e-12 or elapsed >= next_time - 1e-12:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "observation_index не согласован с elapsed_time и schedule",
        )
    defaults = {name: _contract_finite(value, f"state_values.{name}")
                for name, value in (defn.get("state") or {}).items()}
    if observation_index > 0 and defaults and state_values is None:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "processed seasoned state requires explicit state_values",
        )
    values = defaults if state_values is None else state_values
    if not isinstance(values, dict) or set(values) != set(defaults):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "state_values должен точно совпадать с definition.state",
        )
    values = {name: _contract_finite(values[name], f"state_values.{name}")
              for name in defaults}
    if not isinstance(alive, (bool, np.bool_)):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "alive должен быть boolean",
        )
    state_as_of_token = str(state_as_of or "").strip() or None
    state_source_hash_token = str(state_source_hash or "").strip() or None
    if (state_source_hash_token is not None
            and (len(state_source_hash_token) != 64
                 or any(char not in "0123456789abcdefABCDEF"
                        for char in state_source_hash_token))):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "state_source_hash must be a SHA-256 hex digest",
        )
    if state_as_of_token is not None:
        try:
            time.strptime(state_as_of_token, "%Y-%m-%d")
        except ValueError as exc:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "state_as_of must be an ISO calendar date",
            ) from exc
    return {
        "schema_version": _REPRICING_CONTRACT_VERSION,
        "state_contract": _SEASONED_STATE_CONTRACT,
        "mode": "seasoned",
        "asset_names": list(assets),
        "current_spots": dict(zip(assets, current.tolist())),
        "reference_spots": dict(zip(assets, reference.tolist())),
        "observation_index": observation_index,
        "state_values": values,
        "running_min": dict(zip(assets, run_min.tolist())),
        "running_max": dict(zip(assets, run_max.tolist())),
        "elapsed_time": elapsed,
        "alive": bool(alive),
        "state_as_of": state_as_of_token,
        "state_source_hash": state_source_hash_token,
    }


def _canonical_valuation_state(defn: dict, valuation_state: dict | None,
                               *, require_explicit: bool,
                               slots: dict | None = None,
                               contract_schedule: dict | None = None,
                               ) -> tuple[dict, str]:
    assets = _asset_names(defn)
    dated_schedule = (
        canonical_instance_contract_schedule(
            defn, contract_schedule, slots=slots,
        )
        if contract_schedule is not None else None
    )
    if valuation_state is None:
        if require_explicit:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_STATE_REQUIRED",
                "scenario repricing требует canonical valuation_state",
            )
        legacy = inception_valuation_state(defn, [1.0] * len(assets))
        if dated_schedule is not None:
            source_payload = {
                "source": "legacy_unit_inception",
                "date": dated_schedule["effective_date"],
                "spots": legacy["reference_spots"],
            }
            legacy.update({
                "elapsed_time": 0.0,
                "alive": True,
                "state_as_of": dated_schedule["effective_date"],
                "state_source_hash": _contract_hash(source_payload),
                "instance_schedule_hash": dated_schedule["schedule_hash"],
            })
        valuation_state = legacy
        state_source_label = "legacy_unit_inception"
    else:
        state_source_label = None
    if not isinstance(valuation_state, dict):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "valuation_state должен быть объектом",
        )
    unknown = sorted(set(valuation_state) - _VALUATION_STATE_KEYS)
    required_state_keys = _VALUATION_STATE_KEYS - {
        "elapsed_time", "alive", "state_contract", "state_as_of",
        "state_source_hash", "instance_schedule_hash", "inception_seed_hash",
        "fixing_ledger_hash",
    }
    missing = sorted(required_state_keys - set(valuation_state))
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
    mode = valuation_state.get("mode")
    if mode not in ("inception", "seasoned"):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "mode должен быть inception или seasoned",
        )
    if mode == "seasoned" and valuation_state.get("state_contract") != _SEASONED_STATE_CONTRACT:
        # Keep the old stable failure for hand-mutated/partial states.  A
        # seasoned state must be created by seasoned_valuation_state().
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "seasoned state требует полного canonical state_contract",
        )
    if mode == "seasoned" and "alive" not in valuation_state:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "seasoned state requires explicit alive flag",
        )
    if "alive" in valuation_state and not isinstance(
            valuation_state.get("alive"), (bool, np.bool_)):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "valuation_state.alive must be boolean",
        )
    state_assets = valuation_state.get("asset_names")
    if state_assets != assets:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_ASSET_MISMATCH",
            "valuation_state.asset_names должен точно совпадать с definition.assets",
        )
    observation_index = valuation_state.get("observation_index")
    if (isinstance(observation_index, bool)
            or not isinstance(observation_index, int)):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "observation_index должен быть целым числом",
        )
    if mode == "inception" and observation_index != 0:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "observation_index должен быть 0 для inception",
        )
    if mode == "seasoned" and observation_index < 0:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "seasoned observation_index не может быть отрицательным",
        )
    current = _asset_vector(valuation_state.get("current_spots"), assets,
                            "current_spots", positive=True)
    reference = _asset_vector(valuation_state.get("reference_spots"), assets,
                              "reference_spots", positive=True)
    performances = current / reference
    if mode == "inception" and not np.allclose(performances, 1.0, rtol=0.0, atol=1e-12):
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
    if mode == "inception" and any(not np.isclose(state_values[name], defaults[name], rtol=0.0,
                           atol=1e-12) for name in defaults):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "inception state_values должны совпадать с definition defaults",
        )
    running_min = _asset_vector(valuation_state.get("running_min"), assets,
                                "running_min", positive=True)
    running_max = _asset_vector(valuation_state.get("running_max"), assets,
                                "running_max", positive=True)
    if (np.any(running_min > performances + 1e-12)
            or np.any(running_max < performances - 1e-12)
            or np.any(running_min > running_max + 1e-12)):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "running extrema must contain current performance",
        )
    if mode == "inception" and (not np.allclose(running_min, performances, rtol=0.0, atol=1e-12)
            or not np.allclose(running_max, performances, rtol=0.0,
                               atol=1e-12)):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_SEASONED_STATE_UNSUPPORTED",
            "inception running_min/running_max должны равняться current/reference",
        )
    n_obs, numeric_maturity = _resolved_schedule(defn, slots)
    maturity = (_contract_schedule_times(dated_schedule)[-1]
                if dated_schedule is not None else numeric_maturity)
    elapsed_time = float(valuation_state.get("elapsed_time", 0.0))
    if mode == "seasoned" and (not np.isfinite(elapsed_time)
                                or not 0.0 < elapsed_time < maturity):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "seasoned elapsed_time должен быть в интервале (0, maturity)",
        )
    if observation_index >= n_obs:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "valuation_state observation_index is outside the schedule",
        )
    if mode == "seasoned" and dated_schedule is None:
        processed_time = numeric_maturity * observation_index / n_obs
        next_time = numeric_maturity * (observation_index + 1) / n_obs
        if (elapsed_time < processed_time - 1e-12
                or elapsed_time >= next_time - 1e-12):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "seasoned observation_index is inconsistent with elapsed_time",
            )
    if mode == "inception":
        elapsed_time = 0.0
    state_as_of = str(valuation_state.get("state_as_of") or "").strip() or None
    state_source_hash = str(
        valuation_state.get("state_source_hash") or "").strip() or None
    if state_as_of is not None:
        try:
            time.strptime(state_as_of, "%Y-%m-%d")
        except ValueError as exc:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "state_as_of must be an ISO calendar date",
            ) from exc
    if (state_source_hash is not None
            and (len(state_source_hash) != 64
                 or any(char not in "0123456789abcdefABCDEF"
                        for char in state_source_hash))):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "state_source_hash must be a SHA-256 hex digest",
        )
    provenance_hashes = {}
    for field in (
            "instance_schedule_hash", "inception_seed_hash",
            "fixing_ledger_hash"):
        token = str(valuation_state.get(field) or "").strip() or None
        if token is not None:
            token = _sha256_contract_token(
                token, f"valuation_state.{field}",
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            )
        provenance_hashes[field] = token

    if dated_schedule is not None:
        if state_as_of is None:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "dated valuation_state requires state_as_of",
            )
        sessions = set(dated_schedule["calendar"]["resolved_sessions"])
        if state_as_of not in sessions:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "state_as_of is not a resolved contract session",
            )
        expected_elapsed = _contract_schedule_elapsed(
            dated_schedule, state_as_of,
        )
        processed_dates = sum(
            event_date <= state_as_of
            for event_date in dated_schedule["observation_dates"]
        )
        if mode == "inception":
            if (state_as_of != dated_schedule["effective_date"]
                    or observation_index != 0):
                raise CustomProductRepricingError(
                    "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                    "dated inception state must be exactly effective_date",
                )
        elif (state_as_of >= dated_schedule["maturity_date"]
              or observation_index != processed_dates):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "dated state observation_index/date is inconsistent with "
                "contract_schedule",
            )
        if not np.isclose(elapsed_time, expected_elapsed, rtol=0.0,
                          atol=1e-12):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "dated state elapsed_time is inconsistent with state_as_of",
            )
        if (provenance_hashes["instance_schedule_hash"]
                != dated_schedule["schedule_hash"]):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "dated state instance_schedule_hash mismatch",
            )
        if state_source_hash is None:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "dated state requires state_source_hash",
            )
    elif provenance_hashes["instance_schedule_hash"] is not None:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
            "contract_schedule is required for a schedule-bound state",
        )
    canonical = {
        "schema_version": _REPRICING_CONTRACT_VERSION,
        "state_contract": (_SEASONED_STATE_CONTRACT if mode == "seasoned" else None),
        "mode": mode,
        "asset_names": list(assets),
        "current_spots": dict(zip(assets, current.tolist())),
        "reference_spots": dict(zip(assets, reference.tolist())),
        "observation_index": observation_index,
        "state_values": state_values,
        "running_min": dict(zip(assets, running_min.tolist())),
        "running_max": dict(zip(assets, running_max.tolist())),
        "elapsed_time": elapsed_time,
        "alive": bool(valuation_state.get("alive", True)),
        "state_as_of": state_as_of,
        "state_source_hash": state_source_hash,
        "instance_schedule_hash": provenance_hashes["instance_schedule_hash"],
        "inception_seed_hash": provenance_hashes["inception_seed_hash"],
        "fixing_ledger_hash": provenance_hashes["fixing_ledger_hash"],
    }
    if state_source_label is not None:
        return canonical, state_source_label
    return canonical, ("explicit_canonical_seasoned"
                       if mode == "seasoned" else "explicit_canonical_inception")


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


def roll_forward_valuation_state(
    defn: dict,
    valuation_state: dict,
    observations: list[dict | tuple],
    *,
    slots: dict | None = None,
) -> dict:
    """Apply a sequence of realised observation points to a canonical state.

    Each observation is ``{"observation_index": i, "spots": {...}}`` (or a
    two-tuple ``(i, spots)``).  The function executes the product's observation
    program in order, updates state variables and running path extrema, and
    returns a new seasoned state.  It deliberately does not value cashflows;
    the returned state is then passed to :func:`scenario_price_definition` for
    a remaining-life valuation.  This makes multi-day risk rolls reproducible
    and avoids silently re-running already observed coupons/autocalls.
    """
    canonical, _ = _canonical_valuation_state(
        defn, valuation_state, require_explicit=True, slots=slots)
    assets = _asset_names(defn)
    resolved_slots = _resolved_slot_values(defn, slots)
    n_obs, maturity = _resolved_schedule(defn, resolved_slots)
    current_index = int(canonical["observation_index"])
    current_elapsed = float(canonical.get("elapsed_time", 0.0))
    current_spots = _asset_vector(canonical["current_spots"], assets,
                                  "current_spots", positive=True)
    running_min = _asset_vector(canonical["running_min"], assets,
                                "running_min", positive=True)
    running_max = _asset_vector(canonical["running_max"], assets,
                                "running_max", positive=True)
    state_values = dict(canonical["state_values"])
    alive = bool(canonical.get("alive", True))
    ordered = []
    for item in observations:
        if isinstance(item, dict):
            idx = item.get("observation_index", item.get("index"))
            spots = item.get("spots", item.get("current_spots"))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            idx, spots = item
        else:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "roll-forward observation must contain index and spots",
            )
        if isinstance(idx, bool) or not isinstance(idx, int):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "roll-forward observation_index must be an integer",
            )
        if idx != current_index + 1 or idx >= n_obs:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "roll-forward observations must be consecutive and before maturity",
            )
        ordered.append((idx, _asset_vector(spots, assets, "observation.spots",
                                            positive=True)))
        current_index = idx
    if not ordered:
        return canonical
    # Process each point independently so the state transition is sequential,
    # even when the caller supplies a multi-day batch.
    current_index = int(canonical["observation_index"])
    current_elapsed = float(canonical.get("elapsed_time", 0.0))
    for idx, next_spots in ordered:
        next_elapsed = maturity * idx / n_obs
        dt = next_elapsed - current_elapsed
        if dt <= 0.0:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_STATE",
                "roll-forward elapsed time must increase",
            )
        path = np.stack([current_spots / _asset_vector(
            canonical["reference_spots"], assets, "reference_spots", positive=True),
                         next_spots / _asset_vector(
                             canonical["reference_spots"], assets,
                             "reference_spots", positive=True)], axis=0)[None, :, :]
        transition = _evaluate_paths(
            defn, resolved_slots,
            path, np.array([0.0, dt]), r=0.0,
            initial_state=state_values,
            initial_running_min=running_min,
            initial_running_max=running_max,
            start_observation_index=current_index,
            elapsed_time=current_elapsed,
            initial_alive=alive,
            stop_observation_index=idx,
            return_state=True,
        )
        state_values = transition["state_values"]
        running_min = np.asarray(transition["running_min"], dtype=float)
        running_max = np.asarray(transition["running_max"], dtype=float)
        alive = bool(transition["alive"])
        current_spots = next_spots
        current_index = idx
        current_elapsed = next_elapsed
    return {
        "schema_version": _REPRICING_CONTRACT_VERSION,
        "state_contract": _SEASONED_STATE_CONTRACT,
        "mode": "seasoned",
        "asset_names": list(assets),
        "current_spots": dict(zip(assets, current_spots.tolist())),
        "reference_spots": dict(zip(assets, _asset_vector(
            canonical["reference_spots"], assets, "reference_spots", positive=True).tolist())),
        "observation_index": current_index,
        "state_values": state_values,
        "running_min": dict(zip(assets, running_min.tolist())),
        "running_max": dict(zip(assets, running_max.tolist())),
        "elapsed_time": current_elapsed,
        "alive": alive,
    }


def historical_roll_forward_state(
    defn: dict,
    valuation_state: dict,
    log_return_path: list[dict],
    *,
    slots: dict | None = None,
    day_count_basis: int = 252,
    reinvestment_rate: float = 0.0,
    contract_schedule: dict | None = None,
    path_dates: list[str] | None = None,
    source_dates: list[str] | None = None,
) -> dict:
    """Roll a current product state through one historical return window.

    Historical simulation applies the *sequence* of observed daily log
    returns to today's absolute spots.  Running extrema are updated every day,
    contractual observation programs are executed when their schedule times
    are crossed, and any cash paid inside the horizon is carried to the
    horizon end.  The returned state is therefore suitable for remaining-life
    repricing without replaying already observed coupons or autocalls.

    This is deliberately an envelope rather than a valuation-state object:
    a product may terminate or mature inside the horizon, in which case there
    is no remaining state to price and only ``horizon_cashflow`` survives.
    """
    # source_dates are pure provenance: they identify the historical calendar
    # window the return sequence was observed on, which is intentionally
    # distinct from path_dates (the forward sessions the sequence is applied
    # to). They never drive the roll math — only the evidence record.
    if source_dates is not None and (
            not isinstance(source_dates, list)
            or len(source_dates) != len(log_return_path)):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "source_dates must provide one observation date per return row",
        )
    if contract_schedule is not None:
        return _historical_roll_forward_dated_returns(
            defn, valuation_state, log_return_path,
            contract_schedule=contract_schedule,
            path_dates=path_dates,
            source_dates=source_dates,
            slots=slots,
            reinvestment_rate=reinvestment_rate,
        )
    if path_dates is not None:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "path_dates require contract_schedule",
        )
    canonical, _ = _canonical_valuation_state(
        defn, valuation_state, require_explicit=True, slots=slots)
    assets = _asset_names(defn)
    if (not isinstance(log_return_path, list) or not log_return_path
            or len(log_return_path) > 250):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "historical log-return path must contain 1 … 250 daily points",
        )
    if (isinstance(day_count_basis, bool)
            or not isinstance(day_count_basis, int)
            or day_count_basis < 1):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "day_count_basis must be a positive integer",
        )
    rate = _contract_finite(reinvestment_rate, "reinvestment_rate")
    if not -1.0 <= rate <= 2.0:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "reinvestment_rate must be in [-1, 2]",
        )
    parsed_path: list[np.ndarray] = []
    for index, row in enumerate(log_return_path):
        if not isinstance(row, dict):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                f"historical path point {index} must be an asset mapping",
            )
        parsed_path.append(_asset_vector(
            row, assets, f"historical_path[{index}]"))

    resolved_slots = _resolved_slot_values(defn, slots)
    n_obs, maturity = _resolved_schedule(defn, resolved_slots)

    start_elapsed = float(canonical.get("elapsed_time", 0.0))
    requested_end = start_elapsed + len(parsed_path) / day_count_basis
    current_elapsed = start_elapsed
    current_index = int(canonical["observation_index"])
    current_spots = _asset_vector(
        canonical["current_spots"], assets, "current_spots", positive=True)
    reference_spots = _asset_vector(
        canonical["reference_spots"], assets, "reference_spots", positive=True)
    running_min = _asset_vector(
        canonical["running_min"], assets, "running_min", positive=True)
    running_max = _asset_vector(
        canonical["running_max"], assets, "running_max", positive=True)
    state_values = dict(canonical["state_values"])
    alive = bool(canonical.get("alive", True))
    cashflows: list[dict] = []
    consumed_days = 0

    for returns in parsed_path:
        if current_elapsed >= maturity - 1e-12 or not alive:
            break
        try:
            multipliers = np.exp(returns)
        except FloatingPointError as exc:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                "historical path contains an overflowing log return",
            ) from exc
        next_spots = current_spots * multipliers
        if (not np.all(np.isfinite(next_spots))
                or np.any(next_spots <= 0.0)):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                "historical path produces a non-finite or non-positive spot",
            )
        next_elapsed = min(
            start_elapsed + (consumed_days + 1) / day_count_basis,
            maturity,
        )
        performance = next_spots / reference_spots
        running_min = np.minimum(running_min, performance)
        running_max = np.maximum(running_max, performance)

        while current_index < n_obs:
            event_time = maturity * (current_index + 1) / n_obs
            if event_time > next_elapsed + 1e-12:
                break
            dt = max(event_time - current_elapsed, 0.0)
            start_perf = current_spots / reference_spots
            end_perf = next_spots / reference_spots
            event_path = np.stack([start_perf, end_perf], axis=0)[None, :, :]
            transition = _evaluate_paths(
                defn,
                resolved_slots,
                event_path,
                np.array([0.0, dt]),
                r=0.0,
                initial_state=state_values,
                initial_running_min=running_min,
                initial_running_max=running_max,
                start_observation_index=current_index,
                elapsed_time=current_elapsed,
                initial_alive=alive,
                stop_observation_index=current_index + 1,
                return_state=True,
            )
            amount = float(transition["payoffs"][0])
            if amount:
                cashflows.append({"time": float(event_time), "amount": amount})
            state_values = transition["state_values"]
            running_min = np.asarray(transition["running_min"], dtype=float)
            running_max = np.asarray(transition["running_max"], dtype=float)
            alive = bool(transition["alive"])
            current_index += 1
            current_elapsed = event_time
            if not alive:
                break

        current_spots = next_spots
        current_elapsed = next_elapsed
        consumed_days += 1

    terminal = (not alive) or current_elapsed >= maturity - 1e-12
    horizon_cashflow = float(sum(
        row["amount"] * math.exp(rate * max(requested_end - row["time"], 0.0))
        for row in cashflows
    ))
    state = None
    if not terminal:
        state = seasoned_valuation_state(
            defn,
            dict(zip(assets, current_spots.tolist())),
            dict(zip(assets, reference_spots.tolist())),
            current_index,
            state_values=state_values,
            running_min=dict(zip(assets, running_min.tolist())),
            running_max=dict(zip(assets, running_max.tolist())),
            elapsed_time=current_elapsed,
            alive=alive,
            slots=resolved_slots,
        )
    path_payload = {
        "assets": assets,
        "day_count_basis": day_count_basis,
        "log_returns": [row.tolist() for row in parsed_path],
    }
    output_payload = {
        "valuation_state": state,
        "terminal": bool(terminal),
        "cashflows": cashflows,
        "horizon_cashflow": horizon_cashflow,
    }
    transition_payload = {
        "contract": "custom_ast_historical_path_roll_v1",
        "definition_hash": definition_hash(defn),
        "initial_state_hash": _contract_hash(canonical),
        "slots_hash": _contract_hash(resolved_slots),
        "path_hash": _contract_hash(path_payload),
        "reinvestment_rate": rate,
        "output": output_payload,
    }
    return {
        "valuation_state": state,
        "terminal": bool(terminal),
        "horizon_cashflow": horizon_cashflow,
        "cashflows": cashflows,
        "evidence": {
            "contract": "custom_ast_historical_path_roll_v1",
            "definition_hash": transition_payload["definition_hash"],
            "initial_state_hash": transition_payload["initial_state_hash"],
            "slots_hash": transition_payload["slots_hash"],
            "path_hash": transition_payload["path_hash"],
            "output_state_hash": (
                _contract_hash(state) if state is not None else None),
            "cashflow_ledger_hash": _contract_hash(cashflows),
            "transition_hash": _contract_hash(transition_payload),
            "requested_days": len(parsed_path),
            "consumed_days": consumed_days,
            "day_count_basis": day_count_basis,
            "start_elapsed_time": start_elapsed,
            "end_elapsed_time": current_elapsed,
            "requested_end_elapsed_time": requested_end,
            "processed_observations": current_index - int(
                canonical["observation_index"]),
            "terminal": bool(terminal),
            "terminated_early": bool(not alive and current_elapsed < maturity - 1e-12),
            "cashflow_count": len(cashflows),
            "horizon_cashflow": horizon_cashflow,
            "reinvestment_rate": rate,
            "source_dates": list(source_dates) if source_dates is not None else None,
        },
    }


def _historical_roll_forward_dated_returns(
    defn: dict,
    valuation_state: dict,
    log_return_path: list[dict],
    *,
    contract_schedule: dict,
    path_dates: list[str] | None,
    slots: dict | None,
    reinvestment_rate: float,
    source_dates: list[str] | None = None,
) -> dict:
    """Dated compatibility route for current-state historical HypPL paths."""
    if (not isinstance(log_return_path, list) or not log_return_path
            or len(log_return_path) > 250):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "historical log-return path must contain 1 … 250 daily points",
        )
    if not isinstance(path_dates, list) or len(path_dates) != len(log_return_path):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "dated historical path requires one path_date per return row",
        )
    resolved_slots = _resolved_slot_values(defn, slots)
    schedule = canonical_instance_contract_schedule(
        defn, contract_schedule, slots=resolved_slots,
    )
    canonical, _ = _canonical_valuation_state(
        defn, valuation_state, require_explicit=True, slots=resolved_slots,
        contract_schedule=schedule,
    )
    start_as_of = str(canonical["state_as_of"])
    sessions = schedule["calendar"]["resolved_sessions"]
    start_position = sessions.index(start_as_of)
    expected_dates = sessions[
        start_position + 1:start_position + 1 + len(log_return_path)
    ]
    parsed_dates = [
        _iso_contract_date(
            value, f"path_dates[{index}]",
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
        ).isoformat()
        for index, value in enumerate(path_dates)
    ]
    if parsed_dates != expected_dates:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_GAP",
            "path_dates must be the exact consecutive resolved sessions",
        )
    assets = _asset_names(defn)
    current = _asset_vector(
        canonical["current_spots"], assets, "current_spots", positive=True,
    )
    fixing_rows = [{
        "date": start_as_of,
        "spots": dict(zip(assets, current.tolist())),
    }]
    canonical_returns = []
    for index, (day, row) in enumerate(zip(parsed_dates, log_return_path)):
        if not isinstance(row, dict):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                f"historical path point {index} must be an asset mapping",
            )
        returns = _asset_vector(row, assets, f"historical_path[{index}]")
        with np.errstate(over="raise", invalid="raise"):
            try:
                current = current * np.exp(returns)
            except FloatingPointError as exc:
                raise CustomProductRepricingError(
                    "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                    "historical path contains an overflowing log return",
                ) from exc
        if not np.all(np.isfinite(current)) or np.any(current <= 0.0):
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                "historical path produces non-positive/non-finite spots",
            )
        canonical_returns.append(dict(zip(assets, returns.tolist())))
        fixing_rows.append({
            "date": day,
            "spots": dict(zip(assets, current.tolist())),
        })
    raw_ledger = {
        "source": "dated_historical_log_return_path",
        "source_version": "generated_v1",
        "payload_hash": _contract_hash({
            "dates": parsed_dates,
            "asset_names": assets,
            "log_returns": canonical_returns,
        }),
        "fixings": fixing_rows,
    }
    rolled = roll_forward_dated_valuation_state(
        defn, schedule, canonical, raw_ledger, parsed_dates[-1],
        slots=resolved_slots,
    )
    rate = _contract_finite(reinvestment_rate, "reinvestment_rate")
    if not -1.0 <= rate <= 2.0:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
            "reinvestment_rate must be in [-1, 2]",
        )
    requested_end = _contract_schedule_elapsed(schedule, parsed_dates[-1])
    horizon_cashflow = float(sum(
        row["amount"] * math.exp(rate * max(requested_end - row["time"], 0.0))
        for row in rolled["cashflows"]
    ))
    rolled["horizon_cashflow"] = horizon_cashflow
    rolled["evidence"].update({
        "historical_path_contract": "dated_log_returns_exact_sessions_v1",
        "path_hash": _contract_hash({
            "dates": parsed_dates,
            "asset_names": assets,
            "log_returns": canonical_returns,
        }),
        "requested_days": len(parsed_dates),
        "consumed_days": rolled["evidence"]["processed_session_count"],
        "day_count_basis": "ACT/365F",
        "horizon_cashflow": horizon_cashflow,
        "reinvestment_rate": rate,
        "source_dates": list(source_dates) if source_dates is not None else None,
    })
    return rolled


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
    try:
        n_obs, maturity = _resolved_schedule(defn)
    except CustomProductRepricingError:
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
    try:
        n_obs, maturity = _resolved_schedule(defn)
        schedule_text = f"{n_obs} наблюдений до погашения через {maturity} лет."
    except CustomProductRepricingError:
        schedule_text = "Расписание не определено."
    lines = [schedule_text]
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
                    initial_running_max: np.ndarray | None = None,
                    start_observation_index: int = 0,
                    elapsed_time: float = 0.0,
                    initial_alive: bool = True,
                    stop_observation_index: int | None = None,
                    return_state: bool = False,
                    observation_times: list[float] | None = None) -> dict:
    """Run the definition programs over pre-generated paths (perf terms).

    ``paths`` has shape (n_paths, n_steps+1, n_assets)."""
    n_obs, numeric_maturity = _resolved_schedule(defn, slots)
    if observation_times is None:
        maturity = numeric_maturity
        obs_times = [maturity * (i + 1) / n_obs for i in range(n_obs)]
    else:
        if len(observation_times) != n_obs:
            raise ValueError("observation_times count differs from schedule")
        obs_times = [float(value) for value in observation_times]
        if (not all(np.isfinite(value) and value > 0.0 for value in obs_times)
                or any(left >= right for left, right in zip(
                    obs_times, obs_times[1:]))):
            raise ValueError("observation_times must be finite and increasing")
        maturity = obs_times[-1]
    if not 0 <= start_observation_index <= n_obs:
        raise ValueError("start_observation_index is outside the schedule")
    stop_index = n_obs if stop_observation_index is None else stop_observation_index
    if not start_observation_index <= stop_index <= n_obs:
        raise ValueError("stop_observation_index is outside the schedule")

    n_paths, n_steps = paths.shape[0], paths.shape[1] - 1
    payoffs = np.zeros(n_paths)
    alive = np.full(n_paths, bool(initial_alive), dtype=bool)
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

    # Contract expressions see absolute schedule time and contractual accrual.
    # Discounting alone is relative to the current valuation state's elapsed
    # time.  This distinction is essential for seasoned products: resetting
    # ``time``/``accrual`` at every valuation date changes their economics.
    prev_t = (0.0 if start_observation_index == 0
              else obs_times[start_observation_index - 1])
    for obs_index, t_abs in enumerate(obs_times):
        if obs_index < start_observation_index or obs_index >= stop_index:
            continue
        t_obs = float(t_abs - elapsed_time)
        if t_obs < -1e-12:
            continue
        # ``times`` is relative to the current valuation date.  Preserve the
        # established regular-grid fixing convention used by the dedicated
        # structured pricers (nearest path point, Python half-even rounding).
        # Irregular historical/roll-forward grids retain an explicit left
        # search so an event is never evaluated before it is crossed.
        grid = np.diff(times)
        regular_grid = (
            n_steps > 0 and len(times) == n_steps + 1
            and grid.size == n_steps
            and np.allclose(grid, grid[0], rtol=1e-12, atol=1e-15)
            and grid[0] > 0.0
        )
        if regular_grid:
            step = int(round(max(t_obs, 0.0) / float(grid[0])))
        else:
            step = int(np.searchsorted(times, max(t_obs, 0.0), side="left"))
        step = min(max(step, 0), n_steps)
        running_min, running_max = _running_extrema(step)
        ctx = _Ctx(paths[:, step, :], running_min, running_max,
                   t_abs, t_abs - prev_t, slots, state)
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
        prev_t = t_abs

    # Maturity is evaluated only when the requested horizon reaches maturity.
    # This is what makes the same evaluator usable for a seasoned roll-forward
    # state: past observations are replayed into state, future ones are priced.
    if stop_index == n_obs:
        running_min, running_max = _running_extrema(n_steps)
        ctx = _Ctx(paths[:, -1, :], running_min, running_max,
                   maturity, maturity - prev_t,
                   slots, state)
        disc_T = np.exp(-r * max(maturity - elapsed_time, 0.0))
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
    out = {"payoffs": payoffs, "early_redemption_prob": early}
    if return_state:
        out["state_values"] = {name: float(value[0]) for name, value in state.items()}
        out["running_min"] = running_min[0].tolist()
        out["running_max"] = running_max[0].tolist()
        out["alive"] = bool(alive[0])
        out["observation_index"] = int(stop_index)
    return out


def _canonical_inception_valuation_seed(
    defn: dict,
    contract_schedule: dict,
    inception_seed: dict,
    *,
    slots: dict | None = None,
) -> dict:
    code = "CUSTOM_PRODUCT_INCEPTION_SEED_INVALID"
    integrity_code = "CUSTOM_PRODUCT_INCEPTION_SEED_INTEGRITY"
    schedule = canonical_instance_contract_schedule(
        defn, contract_schedule, slots=slots,
    )
    raw = _strict_contract_keys(
        inception_seed,
        label="inception_seed",
        allowed={
            "schema_version", "contract", "definition_hash", "schedule_hash",
            "effective_date", "asset_names", "reference_fixing",
            "valuation_state", "seed_hash",
        },
        required={
            "schema_version", "contract", "definition_hash", "schedule_hash",
            "effective_date", "asset_names", "reference_fixing",
            "valuation_state", "seed_hash",
        },
        code=code,
    )
    if raw["schema_version"] != 1 or raw["contract"] != _INCEPTION_SEED_CONTRACT:
        raise CustomProductRepricingError(code, "unsupported inception seed contract")
    if raw["definition_hash"] != definition_hash(defn):
        raise CustomProductRepricingError(
            integrity_code, "inception_seed definition_hash mismatch",
        )
    if raw["schedule_hash"] != schedule["schedule_hash"]:
        raise CustomProductRepricingError(
            integrity_code, "inception_seed schedule_hash mismatch",
        )
    supplied_seed_hash = _sha256_contract_token(
        raw["seed_hash"], "inception_seed.seed_hash", integrity_code,
    )
    seed_payload = copy.deepcopy(raw)
    seed_payload.pop("seed_hash")
    if supplied_seed_hash != _contract_hash(seed_payload):
        raise CustomProductRepricingError(
            integrity_code, "inception_seed seed_hash mismatch",
        )
    assets = _asset_names(defn)
    if raw["asset_names"] != assets:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_REPRICING_ASSET_MISMATCH",
            "inception_seed.asset_names must match definition.assets",
        )
    if raw["effective_date"] != schedule["effective_date"]:
        raise CustomProductRepricingError(
            integrity_code, "inception_seed effective_date mismatch",
        )
    fixing = _strict_contract_keys(
        raw["reference_fixing"],
        label="inception_seed.reference_fixing",
        allowed={"date", "spots", "source", "source_hash"},
        required={"date", "spots", "source", "source_hash"},
        code=code,
    )
    if fixing["date"] != schedule["effective_date"]:
        raise CustomProductRepricingError(
            integrity_code, "reference_fixing date mismatch",
        )
    source = str(fixing["source"]).strip()
    if not source:
        raise CustomProductRepricingError(code, "reference_fixing.source is required")
    reference = _asset_vector(
        fixing["spots"], assets, "reference_fixing.spots", positive=True,
    )
    fixing_payload = {
        "date": fixing["date"],
        "spots": dict(zip(assets, reference.tolist())),
        "source": source,
    }
    fixing_hash = _sha256_contract_token(
        fixing["source_hash"], "reference_fixing.source_hash", integrity_code,
    )
    if fixing_hash != _contract_hash(fixing_payload):
        raise CustomProductRepricingError(
            integrity_code, "reference_fixing source_hash mismatch",
        )
    state, _ = _canonical_valuation_state(
        defn, raw["valuation_state"], require_explicit=True, slots=slots,
        contract_schedule=schedule,
    )
    if state["mode"] != "inception":
        raise CustomProductRepricingError(code, "inception seed state is not inception")
    state_reference = _asset_vector(
        state["reference_spots"], assets, "reference_spots", positive=True,
    )
    if (not np.allclose(state_reference, reference, rtol=0.0, atol=1e-12)
            or state["state_source_hash"] != fixing_hash):
        raise CustomProductRepricingError(
            integrity_code, "inception seed state/reference evidence mismatch",
        )
    canonical = copy.deepcopy(seed_payload)
    canonical["reference_fixing"] = {**fixing_payload, "source_hash": fixing_hash}
    canonical["valuation_state"] = state
    canonical["seed_hash"] = supplied_seed_hash
    return canonical


def _realized_scalar(value: object, label: str) -> float:
    array = np.asarray(value)
    if array.size != 1:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_INVALID",
            f"{label} did not resolve to one realized value",
        )
    return _contract_finite(array.reshape(-1)[0], label)


def _realized_boolean(value: object, label: str) -> bool:
    array = np.asarray(value)
    if array.size != 1:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_INVALID",
            f"{label} did not resolve to one realized condition",
        )
    return bool(array.reshape(-1)[0])


def _apply_dated_realized_program(
    program: list[dict],
    *,
    perfs: np.ndarray,
    running_min: np.ndarray,
    running_max: np.ndarray,
    event_time: float,
    accrual: float,
    slots: dict,
    state_values: dict,
    alive: bool,
    event_date: str,
    phase: str,
    observation_index: int,
) -> tuple[dict, bool, list[dict]]:
    """Execute one AST program on a single historically observed state."""
    state_arrays = {
        name: np.asarray([float(value)], dtype=float)
        for name, value in state_values.items()
    }
    ctx = _Ctx(
        perfs[None, :], running_min[None, :], running_max[None, :],
        event_time, accrual, slots, state_arrays,
    )
    cashflows: list[dict] = []
    for action_index, action in enumerate(program):
        if not alive:
            break
        kind = action["action"]
        if kind in ("set", "accumulate"):
            name = action["name"]
            value = _realized_scalar(
                _eval(action["value"], ctx),
                f"{phase}[{action_index}].value",
            )
            if kind == "set":
                state_arrays[name][0] = value
            else:
                state_arrays[name][0] += value
            continue
        condition = True
        if "when" in action:
            condition = _realized_boolean(
                _eval(action["when"], ctx),
                f"{phase}[{action_index}].when",
            )
        if not condition:
            continue
        if kind == "pay":
            amount = _realized_scalar(
                _eval(action["amount"], ctx),
                f"{phase}[{action_index}].amount",
            )
        elif kind == "terminate":
            amount = _realized_scalar(
                _eval(action["payout"], ctx),
                f"{phase}[{action_index}].payout",
            )
            alive = False
            for values in state_arrays.values():
                values[0] = 0.0
        else:  # protected by definition compilation, retained fail-closed.
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_HISTORICAL_STATE_INVALID",
                f"unsupported realized action {kind}",
            )
        if amount:
            cashflows.append({
                "date": event_date,
                "time": float(event_time),
                "amount": float(amount),
                "phase": phase,
                "action_index": action_index,
                "observation_index": observation_index,
            })
    return ({name: float(values[0]) for name, values in state_arrays.items()},
            alive, cashflows)


def _dated_fixing_window(
    schedule: dict,
    ledger: dict,
    start_date: str,
    end_date: str,
) -> list[dict]:
    code = "CUSTOM_PRODUCT_HISTORICAL_STATE_GAP"
    sessions = schedule["calendar"]["resolved_sessions"]
    if start_date not in sessions or end_date not in sessions:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_INVALID",
            "dated roll endpoints must be resolved sessions",
        )
    if end_date < start_date:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_INVALID",
            "dated roll cannot move backwards",
        )
    required_dates = [
        day for day in sessions if start_date <= day <= end_date
    ]
    by_date = {row["date"]: row for row in ledger["fixings"]}
    missing = [day for day in required_dates if day not in by_date]
    if missing:
        raise CustomProductRepricingError(
            code, "missing exact session fixings: " + ", ".join(missing),
        )
    return [by_date[day] for day in required_dates]


def _roll_dated_state_core(
    defn: dict,
    schedule: dict,
    initial_state: dict,
    ledger: dict,
    end_as_of: str,
    *,
    slots: dict,
    inception_seed_hash: str | None,
    evidence_contract: str,
) -> dict:
    assets = _asset_names(defn)
    start_as_of = initial_state.get("state_as_of")
    if not start_as_of:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_INVALID",
            "dated initial state requires state_as_of",
        )
    _iso_contract_date(
        end_as_of, "end_as_of", "CUSTOM_PRODUCT_HISTORICAL_STATE_INVALID",
    )
    window = _dated_fixing_window(schedule, ledger, start_as_of, end_as_of)
    current_spots = _asset_vector(
        initial_state["current_spots"], assets, "current_spots", positive=True,
    )
    start_fixing = _asset_vector(
        window[0]["spots"], assets, "start fixing", positive=True,
    )
    if not np.allclose(current_spots, start_fixing, rtol=0.0, atol=1e-12):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_INTEGRITY",
            "initial state spots differ from the fixing ledger at state_as_of",
        )
    reference_spots = _asset_vector(
        initial_state["reference_spots"], assets, "reference_spots", positive=True,
    )
    running_min = _asset_vector(
        initial_state["running_min"], assets, "running_min", positive=True,
    )
    running_max = _asset_vector(
        initial_state["running_max"], assets, "running_max", positive=True,
    )
    state_values = dict(initial_state["state_values"])
    alive = bool(initial_state.get("alive", True))
    if not alive:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_INVALID",
            "a terminated state cannot be rolled",
        )
    observation_dates = schedule["observation_dates"]
    observation_times = _contract_schedule_times(schedule)
    event_index_by_date = {
        day: index for index, day in enumerate(observation_dates)
    }
    current_index = int(initial_state["observation_index"])
    expected_start_index = sum(day <= start_as_of for day in observation_dates)
    if current_index != expected_start_index:
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_INTEGRITY",
            "initial state observation_index is not post-event for state_as_of",
        )
    previous_event_time = (
        0.0 if current_index == 0 else observation_times[current_index - 1]
    )
    cashflows: list[dict] = []
    processed_sessions = 0
    processed_events = 0
    terminal_reason = None

    for row in window[1:]:
        day = row["date"]
        current_spots = _asset_vector(
            row["spots"], assets, f"fixing[{day}]", positive=True,
        )
        performance = current_spots / reference_spots
        running_min = np.minimum(running_min, performance)
        running_max = np.maximum(running_max, performance)
        processed_sessions += 1
        if day not in event_index_by_date:
            continue
        event_index = event_index_by_date[day]
        if event_index != current_index:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_HISTORICAL_STATE_INTEGRITY",
                "event sequence is inconsistent with initial state",
            )
        event_time = observation_times[event_index]
        state_values, alive, event_cashflows = _apply_dated_realized_program(
            defn.get("observation_program") or [],
            perfs=performance,
            running_min=running_min,
            running_max=running_max,
            event_time=event_time,
            accrual=event_time - previous_event_time,
            slots=slots,
            state_values=state_values,
            alive=alive,
            event_date=day,
            phase="observation",
            observation_index=event_index,
        )
        cashflows.extend(event_cashflows)
        current_index += 1
        processed_events += 1
        previous_event_time = event_time
        if not alive:
            terminal_reason = "early_termination"
            break
        if day == schedule["maturity_date"]:
            state_values, alive, maturity_cashflows = _apply_dated_realized_program(
                defn.get("maturity_program") or [],
                perfs=performance,
                running_min=running_min,
                running_max=running_max,
                event_time=event_time,
                accrual=0.0,
                slots=slots,
                state_values=state_values,
                alive=alive,
                event_date=day,
                phase="maturity",
                observation_index=event_index,
            )
            cashflows.extend(maturity_cashflows)
            terminal_reason = "maturity"
            break

    terminal = terminal_reason is not None
    # The full required window (not only event dates) is bound into state
    # evidence.  A missing intermediate close therefore cannot be hidden by an
    # unchanged terminal spot.
    source_payload = {
        "contract": evidence_contract,
        "prior_state_source_hash": initial_state.get("state_source_hash"),
        "schedule_hash": schedule["schedule_hash"],
        "ledger_hash": ledger["ledger_hash"],
        "start_as_of": start_as_of,
        "end_as_of": end_as_of,
        "fixings": window,
    }
    output_state = None
    if not terminal:
        elapsed = _contract_schedule_elapsed(schedule, end_as_of)
        mode = ("inception" if end_as_of == schedule["effective_date"]
                else "seasoned")
        output_state = {
            "schema_version": 1,
            "state_contract": (
                None if mode == "inception" else _SEASONED_STATE_CONTRACT
            ),
            "mode": mode,
            "asset_names": list(assets),
            "current_spots": dict(zip(assets, current_spots.tolist())),
            "reference_spots": dict(zip(assets, reference_spots.tolist())),
            "observation_index": current_index,
            "state_values": state_values,
            "running_min": dict(zip(assets, running_min.tolist())),
            "running_max": dict(zip(assets, running_max.tolist())),
            "elapsed_time": elapsed,
            "alive": True,
            "state_as_of": end_as_of,
            "state_source_hash": _contract_hash(source_payload),
            "instance_schedule_hash": schedule["schedule_hash"],
            "inception_seed_hash": inception_seed_hash,
            "fixing_ledger_hash": ledger["ledger_hash"],
        }
        output_state, _ = _canonical_valuation_state(
            defn, output_state, require_explicit=True, slots=slots,
            contract_schedule=schedule,
        )
    output_payload = {
        "valuation_state": output_state,
        "terminal": terminal,
        "terminal_reason": terminal_reason,
        "cashflows": cashflows,
    }
    evidence_payload = {
        "contract": evidence_contract,
        "definition_hash": definition_hash(defn),
        "schedule_hash": schedule["schedule_hash"],
        "initial_state_hash": _contract_hash(initial_state),
        "fixing_ledger_hash": ledger["ledger_hash"],
        "start_as_of": start_as_of,
        "end_as_of": end_as_of,
        "output": output_payload,
    }
    return {
        **output_payload,
        "evidence": {
            "contract": evidence_contract,
            "definition_hash": definition_hash(defn),
            "schedule_hash": schedule["schedule_hash"],
            "calendar_source_hash": schedule["calendar"]["source_hash"],
            "initial_state_hash": _contract_hash(initial_state),
            "fixing_ledger_hash": ledger["ledger_hash"],
            "fixing_source_hash": ledger["source_hash"],
            "start_as_of": start_as_of,
            "end_as_of": end_as_of,
            "required_session_count": len(window),
            "processed_session_count": processed_sessions,
            "processed_event_count": processed_events,
            "cashflow_ledger_hash": _contract_hash(cashflows),
            "output_state_hash": (
                _contract_hash(output_state) if output_state is not None else None
            ),
            "terminal": terminal,
            "terminal_reason": terminal_reason,
            "transition_hash": _contract_hash(evidence_payload),
        },
    }


def reconstruct_historical_valuation_state(
    defn: dict,
    contract_schedule: dict,
    inception_seed: dict,
    fixing_ledger: dict,
    as_of: str,
    *,
    slots: dict | None = None,
) -> dict:
    """Rebuild the actual post-close/post-event state on a historic session."""
    resolved_slots = _resolved_slot_values(defn, slots)
    schedule = canonical_instance_contract_schedule(
        defn, contract_schedule, slots=resolved_slots,
    )
    seed = _canonical_inception_valuation_seed(
        defn, schedule, inception_seed, slots=resolved_slots,
    )
    ledger = canonical_dated_fixing_ledger(
        defn, schedule, fixing_ledger, slots=resolved_slots,
    )
    result = _roll_dated_state_core(
        defn, schedule, seed["valuation_state"], ledger, as_of,
        slots=resolved_slots,
        inception_seed_hash=seed["seed_hash"],
        evidence_contract=_HISTORICAL_RECONSTRUCTION_CONTRACT,
    )
    result["evidence"]["inception_seed_hash"] = seed["seed_hash"]
    return result


def roll_forward_dated_valuation_state(
    defn: dict,
    contract_schedule: dict,
    valuation_state: dict,
    fixing_ledger: dict,
    end_as_of: str,
    *,
    slots: dict | None = None,
) -> dict:
    """Advance a reconstructed state over exact dated sessions/events."""
    resolved_slots = _resolved_slot_values(defn, slots)
    schedule = canonical_instance_contract_schedule(
        defn, contract_schedule, slots=resolved_slots,
    )
    canonical_state, _ = _canonical_valuation_state(
        defn, valuation_state, require_explicit=True, slots=resolved_slots,
        contract_schedule=schedule,
    )
    if end_as_of <= str(canonical_state["state_as_of"]):
        raise CustomProductRepricingError(
            "CUSTOM_PRODUCT_HISTORICAL_STATE_INVALID",
            "dated roll end_as_of must be after state_as_of",
        )
    ledger = canonical_dated_fixing_ledger(
        defn, schedule, fixing_ledger, slots=resolved_slots,
    )
    return _roll_dated_state_core(
        defn, schedule, canonical_state, ledger, end_as_of,
        slots=resolved_slots,
        inception_seed_hash=canonical_state.get("inception_seed_hash"),
        evidence_contract=_DATED_PATH_ROLL_CONTRACT,
    )


def _deterministic_payoff(defn: dict, slots: dict, drift: float) -> float:
    """One synthetic linear scenario — regression vector. Asset i drifts to
    1+drift−0.05·i so multi-asset aggregations are actually exercised."""
    n_obs, maturity = _resolved_schedule(defn, slots)
    n_assets = len(_asset_names(defn))
    steps = max(n_obs * 4, 8)
    path = np.stack([np.linspace(1.0, 1.0 + drift - 0.05 * i, steps + 1)
                     for i in range(n_assets)], axis=1)[None, :, :]
    result = _evaluate_paths(defn, slots, path, np.linspace(0, maturity, steps + 1), r=0.0)
    return float(result["payoffs"][0])


def _price_definition_core(defn: dict, slots: dict, market: dict,
                           n_sims: int = 50_000, steps: int = 252,
                           seed: int = 42, *,
                           valuation_state: dict | None = None,
                           scenario: dict | None = None,
                           require_explicit_state: bool = False,
                           chunk_size: int | None = None,
                           contract_schedule: dict | None = None) -> dict:
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

    merged = _resolved_slot_values(defn, slots)
    dated_schedule = (
        canonical_instance_contract_schedule(
            defn, contract_schedule, slots=merged,
        )
        if contract_schedule is not None else None
    )

    assets = _asset_names(defn)
    n_assets = len(assets)
    canonical_state, state_source = _canonical_valuation_state(
        defn, valuation_state, require_explicit=require_explicit_state,
        slots=merged, contract_schedule=dated_schedule,
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
    start_observation_index = int(canonical_state["observation_index"])
    elapsed_time = float(canonical_state.get("elapsed_time", 0.0))
    initial_alive = bool(canonical_state.get("alive", True))
    r = _finite(market.get("r", 0.05), "market.r")
    if not -1.0 <= r <= 2.0:
        raise ValueError("market.r: значение должно быть в диапазоне -1 … 2")
    if dated_schedule is None:
        _, maturity = _resolved_schedule(defn, merged)
        observation_times = None
    else:
        observation_times = _contract_schedule_times(dated_schedule)
        maturity = observation_times[-1]
    if elapsed_time < 0.0 or elapsed_time >= maturity:
        raise ValueError("valuation_state.elapsed_time must be in [0, maturity)")
    remaining_maturity = maturity - elapsed_time
    n_sims = _bounded_int(n_sims, "n_sims", 1_000, 200_000)
    steps = _bounded_int(steps, "steps", 16, 1_024)
    seed = _bounded_int(seed, "seed", 0, 2_147_483_647)
    resource_budget = custom_mc_resource_budget(
        n_assets, n_sims, steps, include_greeks=False,
        chunk_size=chunk_size,
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

    corr_out = None
    corr = None
    if n_assets > 1:
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
            corr_out = corr.tolist()
        except np.linalg.LinAlgError:
            raise ValueError("корреляционная матрица не положительно "
                             "определена") from None
    path_rng = np.random.default_rng(seed)

    def _multi_paths(count: int):
        dt = remaining_maturity / steps
        chol = np.linalg.cholesky(corr)
        z = path_rng.standard_normal((count, steps, n_assets)) @ chol.T
        increments = (
            (r - q_vec - 0.5 * sigma_vec ** 2) * dt
            + sigma_vec * np.sqrt(dt) * z
        )
        raw = np.empty((count, steps + 1, n_assets), dtype=float)
        raw[:, 0, :] = initial_performances
        raw[:, 1:, :] = initial_performances * np.exp(
            np.cumsum(increments, axis=1))
        return raw, corr_out

    def _single_paths_from_normals(z: np.ndarray) -> np.ndarray:
        dt = remaining_maturity / steps
        increments = (
            (r - q_vec[0] - 0.5 * sigma_vec[0] ** 2) * dt
            + sigma_vec[0] * np.sqrt(dt) * z
        )
        raw = np.empty((len(z), steps + 1), dtype=float)
        raw[:, 0] = initial_performances[0]
        raw[:, 1:] = initial_performances[0] * np.exp(
            np.cumsum(increments, axis=1))
        return raw[:, :, None]

    def _single_path_batches():
        """Dedicated-pricer-compatible antithetic stream without a full cube.

        ``models.monte_carlo.gbm_paths`` generates half a normal grid, applies
        one global moment match, then appends its antithetic half.  Compute the
        same two global moments in deterministic 256-path passes and replay the
        RNG for positive/negative batches.  The sequence is therefore stable
        across caller-selected chunk sizes while the temporary normal grid is
        bounded.  For an odd request the final unpaired path consumes the next
        normal row and is normalized by the same governed moments.
        """
        positive_count = (n_sims + 1) // 2
        negative_count = n_sims // 2
        statistics_batch = min(256, positive_count)

        def _base_normal_batches():
            rng = np.random.default_rng(seed)
            for offset in range(0, positive_count, statistics_batch):
                count = min(statistics_batch, positive_count - offset)
                yield rng.standard_normal((count, steps))

        total = 0.0
        observations = 0
        for block in _base_normal_batches():
            total += float(np.sum(block, dtype=np.float64))
            observations += block.size
        mean = total / observations
        squared = 0.0
        for block in _base_normal_batches():
            squared += float(np.sum((block - mean) ** 2, dtype=np.float64))
        std = math.sqrt(squared / observations)
        if not np.isfinite(std) or std <= 0.0:
            raise CustomProductRepricingError(
                "CUSTOM_PRODUCT_REPRICING_INVALID_SCENARIO",
                "single-asset normal stream has zero or non-finite variance",
            )

        output_batch = (
            positive_count if chunk_size is None
            else max(1, min(int(chunk_size), positive_count))
        )
        for sign, path_count in (
                (1.0, positive_count), (-1.0, negative_count)):
            rng = np.random.default_rng(seed)
            for offset in range(0, path_count, output_batch):
                count = min(output_batch, path_count - offset)
                z = sign * (rng.standard_normal((count, steps)) - mean) / std
                yield _single_paths_from_normals(z)

    # Chunking is intentionally at the path-cube boundary.  The payoff IR is
    # evaluated unchanged per chunk and only sufficient statistics are kept,
    # so peak memory is bounded by ``chunk_size * steps * assets``.
    if n_assets == 1:
        path_batches = _single_path_batches()
    else:
        chunk = n_sims if chunk_size is None else int(chunk_size)
        path_batches = (
            _multi_paths(min(chunk, n_sims - offset))[0]
            for offset in range(0, n_sims, chunk)
        )
    payoff_parts = []
    early_weighted = 0.0
    total_paths = 0
    for paths in path_batches:
        result = _evaluate_paths(
            defn, merged, paths, np.linspace(0, remaining_maturity, paths.shape[1]), r=r,
            initial_state=canonical_state["state_values"],
            initial_running_min=initial_running_min,
            initial_running_max=initial_running_max,
            start_observation_index=start_observation_index,
            elapsed_time=elapsed_time,
            initial_alive=initial_alive,
            observation_times=observation_times,
        )
        payoff_parts.append(result["payoffs"])
        early_weighted += float(result["early_redemption_prob"]) * len(result["payoffs"])
        total_paths += len(result["payoffs"])
    payoffs = np.concatenate(payoff_parts) if len(payoff_parts) > 1 else payoff_parts[0]
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
        "time_roll_years": float(elapsed_time),
        "current_performances": dict(zip(assets,
                                              initial_performances.tolist())),
        "common_random_numbers": {
            "enabled": True,
            "method": (
                "same_seed_antithetic_moment_matched_chunk_invariant"
                if n_assets == 1 else
                "same_seed_single_stream_chunk_invariant"
            ),
            "seed": seed,
        },
        "rng_contract": {
            "version": _RNG_CONTRACT_VERSION,
            "generator_api": "numpy.random.default_rng",
            "bit_generator": type(
                np.random.default_rng(seed).bit_generator).__name__,
            "numpy_version": np.__version__,
            "streaming_algorithm": (
                "chunk_invariant_antithetic_moment_match_v2"
                if n_assets == 1 else
                "chunk_invariant_sequential_normals_v2"
            ),
            "variance_reduction": (
                "antithetic_moment_matching_with_odd_tail"
                if n_assets == 1 else "none"
            ),
        },
        "seasoned_state_supported": canonical_state["mode"] == "seasoned",
        "resource_budget": resource_budget,
        "timing_contract": (
            "resolved_dated_schedule_act_365f_v1"
            if dated_schedule is not None else "numeric_regular_grid_v1"
        ),
        "instance_schedule_hash": (
            dated_schedule["schedule_hash"]
            if dated_schedule is not None else None
        ),
        "observation_times": (
            observation_times if observation_times is not None else
            [maturity * (index + 1) /
             int(_resolved_schedule(defn, merged)[0])
             for index in range(int(_resolved_schedule(defn, merged)[0]))]
        ),
    }
    return {
        "value": float(payoffs.mean()),
        "stderr": float(payoffs.std(ddof=1) / np.sqrt(n_sims)),
        "early_redemption_prob": float(early_weighted / max(total_paths, 1)),
        "definition_hash": definition_hash(defn),
        "slots": merged,
        "assets": assets,
        "market": market_out,
        "valuation_state": canonical_state,
        "scenario": canonical_scenario,
        "repricing_evidence": repricing_evidence,
        "resource_budget": resource_budget,
        "contract_schedule": dated_schedule,
        "n_sims": n_sims, "steps": steps, "seed": seed,
        "engine": "custom_mc_gbm" if n_assets == 1 else "custom_mc_multi_gbm",
    }


def price_definition(defn: dict, slots: dict, market: dict,
                     n_sims: int = 50_000, steps: int = 252,
                     seed: int = 42, *,
                     valuation_state: dict | None = None,
                     chunk_size: int | None = None,
                     contract_schedule: dict | None = None) -> dict:
    """Price a compiled definition from a unit or explicit valuation state.

    Existing callers without a state retain exact S0=1 behaviour.  Scenario
    callers should use :func:`scenario_price_definition`, which requires the
    complete canonical state contract.
    """
    return _price_definition_core(
        defn, slots, market, n_sims=n_sims, steps=steps, seed=seed,
        valuation_state=valuation_state, scenario=None,
        chunk_size=chunk_size,
        contract_schedule=contract_schedule,
        require_explicit_state=False,
    )


def scenario_price_definition(defn: dict, slots: dict, market: dict,
                              valuation_state: dict, scenario: dict | None,
                              n_sims: int = 50_000, steps: int = 252,
                              seed: int = 42,
                              chunk_size: int | None = None,
                              contract_schedule: dict | None = None) -> dict:
    """Canonical full reprice under one instantaneous market scenario."""
    return _price_definition_core(
        defn, slots, market, n_sims=n_sims, steps=steps, seed=seed,
        valuation_state=valuation_state, scenario=scenario,
        chunk_size=chunk_size,
        contract_schedule=contract_schedule,
        require_explicit_state=True,
    )


def component_greeks_definition(
    defn: dict, slots: dict, market: dict, valuation_state: dict,
    scenario: dict | None = None, n_sims: int = 50_000, steps: int = 252,
    seed: int = 42, *, spot_bump_relative: float = 0.005,
    volatility_bump: float = 0.01, chunk_size: int | None = None,
    contract_schedule: dict | None = None,
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
        chunk_size=chunk_size,
    )

    base = scenario_price_definition(
        defn, slots, market, valuation_state, scenario,
        n_sims=n_sims, steps=steps, seed=seed, chunk_size=chunk_size,
        contract_schedule=contract_schedule,
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
            seed=seed, chunk_size=chunk_size,
            contract_schedule=contract_schedule,
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

    cross_gamma_matrix = np.zeros((len(assets), len(assets)), dtype=float)
    for index, asset_name in enumerate(assets):
        cross_gamma_matrix[index, index] = float(
            components[asset_name]["gamma"])
    cross_gamma_pairs: list[dict] = []
    for left in range(len(assets)):
        left_bump = abs(float(current[left])) * spot_bump_relative
        for right in range(left + 1, len(assets)):
            right_bump = abs(float(current[right])) * spot_bump_relative
            corner_values = []
            for left_sign, right_sign in ((1.0, 1.0), (1.0, -1.0),
                                          (-1.0, 1.0), (-1.0, -1.0)):
                corner = current.copy()
                corner[left] += left_sign * left_bump
                corner[right] += right_sign * right_bump
                corner_values.append(_value(corner, base_sigma_shifts))
            cross = (
                corner_values[0] - corner_values[1]
                - corner_values[2] + corner_values[3]
            ) / (4.0 * left_bump * right_bump)
            if not np.isfinite(cross):
                raise ValueError("custom-product cross Gamma is non-finite")
            cross_gamma_matrix[left, right] = cross
            cross_gamma_matrix[right, left] = cross
            cross_gamma_pairs.append({
                "left_asset": assets[left],
                "right_asset": assets[right],
                "cross_gamma": float(cross),
                "parallel_contribution": float(
                    2.0 * cross * current[left] * current[right]),
                "method": "four_corner_central_common_random_numbers",
            })
            repricings += 4

    # The sum of component d2PV/dS_i2 values is only the diagonal Hessian.
    # Reprice one common relative spot shock to expose the economically useful
    # parallel Gamma and the omitted cross terms for multi-asset payoffs.
    parallel_bump = float(spot_bump_relative)
    parallel_up = current * (1.0 + parallel_bump)
    parallel_down = current * (1.0 - parallel_bump)
    parallel_up_value = _value(parallel_up, base_sigma_shifts)
    parallel_down_value = _value(parallel_down, base_sigma_shifts)
    parallel_delta = (parallel_up_value - parallel_down_value) / (2.0 * parallel_bump)
    parallel_gamma = (
        parallel_up_value - 2.0 * base_value + parallel_down_value
    ) / (parallel_bump * parallel_bump)
    diagonal_gamma = float(sum(
        float(row["gamma"]) * float(current[index]) ** 2
        for index, row in enumerate(components.values())
    ))
    parallel_cross_gamma = parallel_gamma - diagonal_gamma
    pairwise_cross_contribution = float(sum(
        row["parallel_contribution"] for row in cross_gamma_pairs))
    hessian_parallel_gamma = diagonal_gamma + pairwise_cross_contribution
    if not all(np.isfinite(value) for value in (
            parallel_delta, parallel_gamma, diagonal_gamma,
            parallel_cross_gamma)):
        raise ValueError("parallel custom-product Greeks are non-finite")
    base["component_greeks"] = components
    base["parallel_delta"] = float(parallel_delta)
    base["parallel_gamma"] = float(parallel_gamma)
    base["parallel_diagonal_gamma"] = float(diagonal_gamma)
    base["parallel_cross_gamma"] = float(parallel_cross_gamma)
    base["pairwise_cross_gamma_contribution"] = pairwise_cross_contribution
    base["hessian_parallel_gamma"] = float(hessian_parallel_gamma)
    base["cross_gamma_matrix"] = cross_gamma_matrix.tolist()
    base["cross_gamma_pairs"] = cross_gamma_pairs
    base["parallel_spot_bump_relative"] = parallel_bump
    base["gamma"] = float(parallel_gamma)
    base["gamma_convention"] = "d2PV/dx2 for parallel relative spot shock"
    base["greeks_evidence"] = {
        "method": "finite_difference_common_random_numbers",
        "asset_key": "logical_definition_asset_name",
        "seed": base["seed"],
        "paths": base["n_sims"],
        "steps": base["steps"],
        "repricings": repricings,
        "aggregate_repricings": 2,
        "total_repricings": repricings + 2,
        "units": {
            "delta": "dPV per +1 absolute spot unit",
            "gamma": "d2PV per squared absolute spot unit",
            "vega": "dPV per +1 volatility point (0.01 absolute sigma)",
        },
        "bumps": {
            "spot_relative": spot_bump_relative,
            "volatility_absolute": volatility_bump,
        },
        "parallel_gamma": {
            "method": "central_common_random_numbers",
            "spot_bump_relative": parallel_bump,
            "diagonal_gamma": diagonal_gamma,
            "cross_gamma": float(parallel_cross_gamma),
            "pairwise_cross_contribution": pairwise_cross_contribution,
            "hessian_parallel_gamma": float(hessian_parallel_gamma),
            "units": "d2PV/dx2 for S_i(x)=S_i*(1+x)",
        },
        "cross_gamma": {
            "method": "four_corner_central_common_random_numbers",
            "matrix_asset_order": assets,
            "pair_count": len(cross_gamma_pairs),
            "repricings": 4 * len(cross_gamma_pairs),
            "units": "d2PV per absolute spot_i and spot_j units",
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
              expected_definition_hash: str | None = None,
              contract_schedule: dict | None = None) -> dict:
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
                                  n_sims=n_sims, steps=steps, seed=seed,
                                  contract_schedule=contract_schedule)
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
                chunk_size: int | None = None,
                version: int | None = None,
                expected_definition_hash: str | None = None,
                include_greeks: bool = False,
                spot_bump_relative: float = 0.005,
                volatility_bump: float = 0.01,
                contract_schedule: dict | None = None) -> dict:
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
                chunk_size=chunk_size,
                contract_schedule=contract_schedule,
                spot_bump_relative=spot_bump_relative,
                volatility_bump=volatility_bump,
            )
        else:
            result = scenario_price_definition(
                head["definition"], slots, market, valuation_state, scenario,
                n_sims=n_sims, steps=steps, seed=seed,
                chunk_size=chunk_size,
                contract_schedule=contract_schedule,
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
        chunk_size: int | None = None,
        version: int | None = None,
        expected_definition_hash: str | None = None,
        spot_bump_relative: float = 0.005,
        volatility_bump: float = 0.01,
        contract_schedule: dict | None = None,
    ) -> dict:
        """Version-pinned component Greeks, keyed by definition asset name."""
        return self.reprice(
            product_id, slots, market, valuation_state=valuation_state,
            scenario=scenario, n_sims=n_sims, steps=steps, seed=seed,
            chunk_size=chunk_size,
            contract_schedule=contract_schedule,
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
