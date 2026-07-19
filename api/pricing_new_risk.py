"""Fail-closed market risk for an ad-hoc Pricing_new workstation book.

The existing :mod:`api.marketrisk` endpoints normally operate on the persisted
application portfolio.  A Pricing_new worksheet is a different risk object: it
is an in-memory set of workstation legs that may never be captured into that
portfolio.  This module converts only the subset that the canonical portfolio
repricer can reproduce and always passes the resulting transient
``PortfolioService`` explicitly to the historical HypPL engine.

No number is returned for an unsupported, ambiguous-currency, or partially
convertible book.  Callers can use :func:`evaluate_book_capabilities` to render
the support boundary before requesting a calculation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

import numpy as np

from api import marketrisk
from api.pricing_workstation import (
    PortfolioRepricingContractError,
    portfolio_quantity,
    portfolio_repricing_engine,
    to_position,
)
from domain.portfolio import Position
from services.portfolio_service import PortfolioService


SUPPORTED_MODELS: dict[str, dict[str, str]] = {
    "historical_full_reprice": {
        "label": "Historical (full reprice)",
        "method": "historical",
    },
    "parametric_normal": {
        "label": "Parametric (normal on historical HypPL)",
        "method": "parametric_normal",
    },
    "parametric_t": {
        "label": "Parametric (Student-t on historical HypPL)",
        "method": "parametric_t",
    },
    "monte_carlo_fitted_normal": {
        "label": "Monte Carlo (normal fitted to historical HypPL)",
        "method": "monte_carlo",
    },
}

_MODEL_ALIASES = {
    "historical": "historical_full_reprice",
    "full_reprice": "historical_full_reprice",
    "normal": "parametric_normal",
    "student_t": "parametric_t",
    "t": "parametric_t",
    "monte_carlo": "monte_carlo_fitted_normal",
    "mc": "monte_carlo_fitted_normal",
}


CUSTOM_RISK_PROFILE = marketrisk.CUSTOM_HISTORICAL_REPRICING_PROFILE
CUSTOM_RISK_INNER_PATHS = marketrisk.CUSTOM_HISTORICAL_INNER_PATHS
CUSTOM_RISK_MAX_SCENARIOS = 500
CUSTOM_RISK_MAX_WORK_PATH_POINTS = 1_500_000_000
CUSTOM_RISK_DEADLINE_SECONDS = 60.0


class PricingNewRiskError(ValueError):
    """Typed domain error suitable for a stable API error envelope."""

    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class UnsupportedPricingNewBookError(PricingNewRiskError):
    """The complete worksheet cannot be reproduced by portfolio repricing."""

    def __init__(self, unsupported: list[dict], *, capability: dict):
        super().__init__(
            "unsupported_pricing_new_book",
            "Pricing_new risk is unavailable until every leg has a canonical "
            "portfolio repricing route and an explicit common currency.",
            details={
                "unsupported": list(unsupported),
                "capability": capability,
            },
        )
        self.unsupported = list(unsupported)
        self.capability = capability


def _custom_risk_compute_policy(
    converted: Sequence["_ConvertedLeg"],
    *,
    requested_scenarios: int,
    actual_scenarios: int | None = None,
    enforce: bool = True,
) -> dict:
    """Build and, when requested, enforce the custom historical MC budget."""
    rows: list[dict] = []
    requested_work = 0
    actual_work = 0 if actual_scenarios is not None else None
    for item in converted:
        if item.instrument != "custom_product":
            continue
        numerical = item.params.get("numerical")
        asset_names = item.params.get("asset_names")
        if (not isinstance(numerical, Mapping)
                or not isinstance(asset_names, (list, tuple))
                or not asset_names):
            raise PricingNewRiskError(
                "custom_risk_contract_invalid",
                f"custom leg '{item.leg_id}' has no canonical numerical/asset grid",
            )
        try:
            pricing_paths = int(numerical["paths"])
            steps = int(numerical["steps"])
            seed = int(numerical["seed"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise PricingNewRiskError(
                "custom_risk_contract_invalid",
                f"custom leg '{item.leg_id}' has invalid paths/steps evidence",
            ) from exc
        if (pricing_paths != numerical.get("paths")
                or steps != numerical.get("steps")
                or seed != numerical.get("seed")
                or pricing_paths < 1 or steps < 1 or seed < 0):
            raise PricingNewRiskError(
                "custom_risk_contract_invalid",
                f"custom leg '{item.leg_id}' has invalid paths/steps evidence",
            )
        asset_count = len(asset_names)
        work = (
            int(requested_scenarios)
            * CUSTOM_RISK_INNER_PATHS
            * (steps + 1)
            * asset_count
        )
        requested_work += work
        actual_leg_work = None
        if actual_scenarios is not None:
            actual_leg_work = (
                int(actual_scenarios)
                * CUSTOM_RISK_INNER_PATHS
                * (steps + 1)
                * asset_count
            )
            assert actual_work is not None
            actual_work += actual_leg_work
        rows.append({
            "id": item.leg_id,
            "assets": asset_count,
            "steps": steps,
            "pricing_paths": pricing_paths,
            "risk_inner_paths": CUSTOM_RISK_INNER_PATHS,
            "seed": seed,
            "random_stream_scope": "captured_seed_per_position",
            "requested_work_path_points": work,
            "actual_work_path_points": actual_leg_work,
            "definition_hash": item.params.get("definition_hash"),
            "repricing_contract_hash": item.params.get(
                "repricing_contract_hash"),
        })

    policy = {
        "active": bool(rows),
        "profile": CUSTOM_RISK_PROFILE if rows else None,
        "inner_paths": CUSTOM_RISK_INNER_PATHS if rows else None,
        "common_random_numbers": bool(rows),
        "paired_profile_base": bool(rows),
        "horizon_method": "1d_instantaneous_shock_no_time_roll" if rows else None,
        "requested_scenarios": int(requested_scenarios),
        "actual_scenarios": (
            int(actual_scenarios) if actual_scenarios is not None else None
        ),
        "scenario_limit": CUSTOM_RISK_MAX_SCENARIOS if rows else None,
        "requested_work_path_points": requested_work,
        "actual_work_path_points": actual_work,
        "work_limit_path_points": (
            CUSTOM_RISK_MAX_WORK_PATH_POINTS if rows else None
        ),
        "deadline_seconds": CUSTOM_RISK_DEADLINE_SECONDS if rows else None,
        "custom_legs": rows,
    }
    if enforce and rows and (
        requested_scenarios > CUSTOM_RISK_MAX_SCENARIOS
        or requested_work > CUSTOM_RISK_MAX_WORK_PATH_POINTS
    ):
        reasons = []
        if requested_scenarios > CUSTOM_RISK_MAX_SCENARIOS:
            reasons.append(
                f"{requested_scenarios} scenarios exceed "
                f"{CUSTOM_RISK_MAX_SCENARIOS}")
        if requested_work > CUSTOM_RISK_MAX_WORK_PATH_POINTS:
            reasons.append(
                f"{requested_work} work path-points exceed "
                f"{CUSTOM_RISK_MAX_WORK_PATH_POINTS}")
        raise PricingNewRiskError(
            "custom_risk_resource_limit",
            "custom_product historical risk resource preflight failed: "
            + "; ".join(reasons),
            details=policy,
        )
    return policy


def legs_with_resolved_pricing_inputs(
    legs: Sequence[Any], book_result: Mapping[str, Any] | None,
) -> list[dict]:
    """Attach immutable priced market state needed by canonical repricing.

    The user request remains untouched in the run record.  For products whose
    form contains market identities rather than numerical state, the persisted
    pricing result carries the exact resolved inputs.  Transient risk must use
    those values instead of resolving the SECIDs again against a newer store.
    """
    result_legs = (
        book_result.get("legs")
        if isinstance(book_result, Mapping) else None
    )
    by_id: dict[str, Mapping[str, Any]] = {}
    if isinstance(result_legs, Sequence) and not isinstance(
            result_legs, (str, bytes, Mapping)):
        for item in result_legs:
            if not isinstance(item, Mapping):
                continue
            leg_id = str(item.get("id") or "")
            if leg_id and leg_id not in by_id:
                by_id[leg_id] = item

    enriched: list[dict] = []
    for raw in legs:
        leg = _as_leg_mapping(raw)
        result_leg = by_id.get(str(leg.get("id") or ""))
        unit_result = (
            result_leg.get("result")
            if isinstance(result_leg, Mapping) else None
        )
        result_matches = (
            isinstance(result_leg, Mapping)
            and str(result_leg.get("product") or "")
            == str(leg.get("product") or "")
            and result_leg.get("error") in (None, "")
            and isinstance(unit_result, Mapping)
        )
        params = leg.get("params")
        merged_params = dict(params) if isinstance(params, Mapping) else {}
        resolved_params = (
            unit_result.get("resolved_params")
            if result_matches else None
        )
        if isinstance(resolved_params, Mapping):
            merged_params.update(resolved_params)
            leg["params"] = merged_params

        product = str(leg.get("product") or "")
        if product == "custom_product":
            resolved = (
                unit_result.get("resolved_inputs")
                if isinstance(unit_result, Mapping) else None
            )
            if result_matches and isinstance(resolved, Mapping):
                # Keep the engine-produced contract nested.  Flattening its
                # market/state evidence into form params would allow collisions
                # with mutable builder inputs and make the capture boundary
                # ambiguous.
                merged_params["custom_repricing"] = copy.deepcopy(dict(resolved))
                leg["params"] = merged_params
            enriched.append(leg)
            continue

        if product != "multi_asset_autocall":
            enriched.append(leg)
            continue
        resolved = (
            unit_result.get("resolved_inputs")
            if isinstance(unit_result, Mapping) else None
        )
        if not result_matches or not isinstance(resolved, Mapping):
            # Keep the original leg. The normal capability path will report a
            # precise missing-resolved-input error rather than inventing state.
            enriched.append(leg)
            continue
        for key in (
            "resolved_snapshot_id", "component_secids", "component_kinds", "assets",
            "reference_spots", "sigmas", "incomes", "weights",
            "reference_fixing_dates", "reference_spot_source", "correlation",
        ):
            if key in resolved:
                merged_params[key] = resolved[key]
        leg["params"] = merged_params
        enriched.append(leg)
    return enriched


@dataclass(frozen=True)
class _ConvertedLeg:
    leg_id: str
    label: str
    product: str
    engine: str | None
    currency: str
    quantity: float
    instrument: str
    params: dict
    description: str


def _as_leg_mapping(value: Any) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        dumped = dump()
        if isinstance(dumped, Mapping):
            return dict(dumped)
    raise TypeError("leg must be a mapping")


def _unsupported(leg: dict, index: int, code: str, reason: str) -> dict:
    return {
        "index": index,
        "id": str(leg.get("id") or f"leg-{index + 1}"),
        "label": str(leg.get("label") or ""),
        "product": str(leg.get("product") or ""),
        "engine": (str(leg["engine"]) if leg.get("engine") else None),
        "code": code,
        "reason": reason,
    }


def _currency(leg: dict, params: dict) -> str | None:
    raw = leg.get("currency")
    if raw in (None, ""):
        raw = params.get("currency")
    if raw in (None, ""):
        return None
    token = str(raw).strip().upper()
    if len(token) != 3 or not token.isalpha():
        return ""
    return token


def _convert_leg(
    leg: dict,
    index: int,
    *,
    bound_snapshot_id: str | None = None,
) -> tuple[_ConvertedLeg | None, dict | None]:
    leg_id = str(leg.get("id") or "").strip()
    if not leg_id:
        return None, _unsupported(leg, index, "leg_id_required", "leg id is required")

    product = str(leg.get("product") or "").strip()
    if not product:
        return None, _unsupported(
            leg, index, "product_required", "workstation product id is required")

    params = leg.get("params")
    if not isinstance(params, Mapping):
        return None, _unsupported(
            leg, index, "invalid_params", "params must be an object")
    params = dict(params)

    currency = _currency(leg, params)
    if currency is None:
        return None, _unsupported(
            leg,
            index,
            "currency_required",
            "explicit three-letter P&L currency is required; implicit RUB "
            "would make mixed-book VaR ambiguous",
        )
    if not currency:
        return None, _unsupported(
            leg, index, "invalid_currency", "currency must be a three-letter code")

    try:
        quantity = portfolio_quantity(leg.get("quantity", 1.0))
    except ValueError as exc:
        return None, _unsupported(leg, index, "invalid_quantity", str(exc))

    engine_value = leg.get("engine")
    engine = str(engine_value).strip() if engine_value not in (None, "") else None
    try:
        converted = to_position(product, params, engine_id=engine)
    except PortfolioRepricingContractError as exc:
        return None, _unsupported(leg, index, exc.code, exc.message)
    except (TypeError, ValueError) as exc:
        message = str(exc) or type(exc).__name__
        if "engine" in message and ("reprodu" in message or "unknown" in message):
            code = "engine_not_reproducible"
        else:
            code = "invalid_repricing_inputs"
        return None, _unsupported(leg, index, code, message)
    if converted is None:
        return None, _unsupported(
            leg,
            index,
            "product_not_repriceable",
            f"'{product}' has no canonical PortfolioService repricing route",
        )

    instrument, position_params, description = converted
    if (instrument in {"multi_asset_autocall", "custom_product"}
            and bound_snapshot_id
            and str(position_params.get("resolved_snapshot_id") or "")
            != str(bound_snapshot_id)):
        product_label = (
            "multi_asset_autocall" if instrument == "multi_asset_autocall"
            else "custom_product"
        )
        return None, _unsupported(
            leg,
            index,
            "snapshot_binding_mismatch",
            f"{product_label} resolved inputs belong to snapshot "
            f"'{position_params.get('resolved_snapshot_id') or 'none'}', not "
            f"the immutable run snapshot '{bound_snapshot_id}'",
        )
    # Resolve an omitted engine to the actual canonical engine now.  Persisting
    # ``None`` would make replay depend on a future catalogue ordering change.
    engine = portfolio_repricing_engine(product, engine)
    return _ConvertedLeg(
        leg_id=leg_id,
        label=str(leg.get("label") or description or leg_id),
        product=product,
        engine=engine,
        currency=currency,
        quantity=quantity,
        instrument=instrument,
        params=position_params,
        description=description,
    ), None


def _evaluate(
    legs: Sequence[Any], *, bound_snapshot_id: str | None = None,
) -> tuple[dict, list[_ConvertedLeg]]:
    if isinstance(legs, (str, bytes, Mapping)) or not isinstance(legs, Sequence):
        raise PricingNewRiskError(
            "invalid_legs", "legs must be a sequence of workstation leg objects")

    converted: list[_ConvertedLeg] = []
    unsupported: list[dict] = []
    if not legs:
        unsupported.append({
            "index": -1,
            "id": "",
            "label": "",
            "product": "",
            "engine": None,
            "code": "empty_book",
            "reason": "at least one Pricing_new leg is required",
        })
    seen: set[str] = set()
    for index, raw_leg in enumerate(legs):
        try:
            leg = _as_leg_mapping(raw_leg)
        except TypeError as exc:
            leg = {}
            unsupported.append(_unsupported(leg, index, "invalid_leg", str(exc)))
            continue
        item, error = _convert_leg(
            leg, index, bound_snapshot_id=bound_snapshot_id)
        if error is not None:
            unsupported.append(error)
            continue
        assert item is not None
        if item.leg_id in seen:
            unsupported.append(_unsupported(
                leg, index, "duplicate_leg_id",
                f"duplicate leg id '{item.leg_id}' is not reproducible"))
            continue
        seen.add(item.leg_id)
        converted.append(item)

    currencies = sorted({item.currency for item in converted})
    if len(currencies) > 1:
        for item in converted:
            unsupported.append({
                "index": next(
                    (i for i, raw in enumerate(legs)
                     if isinstance(raw, Mapping)
                     and str(raw.get("id") or "").strip() == item.leg_id),
                    -1,
                ),
                "id": item.leg_id,
                "label": item.label,
                "product": item.product,
                "engine": item.engine,
                "code": "mixed_currency_book",
                "reason": (
                    f"book currencies {', '.join(currencies)} cannot be netted "
                    "without a governed FX translation policy"
                ),
            })

    supported_ids = {item.leg_id for item in converted}
    unsupported_ids = {item.get("id") for item in unsupported}
    supported_rows = [
        {
            "id": item.leg_id,
            "label": item.label,
            "product": item.product,
            "engine": item.engine,
            "instrument": item.instrument,
            "currency": item.currency,
        }
        for item in converted
        if item.leg_id not in unsupported_ids
    ]
    capability = {
        "supported": bool(legs) and not unsupported,
        "requested_count": len(legs),
        "convertible_count": len(converted),
        "supported_count": len(supported_rows),
        "supported_legs": supported_rows,
        "unsupported": unsupported,
        "currencies": currencies,
        "base_currency": currencies[0] if len(currencies) == 1 else None,
        "policy": {
            "partial_book_risk": False,
            "canonical_portfolio_repricing_only": True,
            "explicit_single_currency_required": True,
        },
    }
    # Keep converted rows for a duplicate leg that was rejected out of the
    # executable set; otherwise a future caller could accidentally price both.
    executable = [item for item in converted
                  if item.leg_id in supported_ids and item.leg_id not in unsupported_ids]
    return capability, executable


def evaluate_book_capabilities(
    legs: Sequence[Any], *, bound_snapshot_id: str | None = None,
) -> dict:
    """Return the explicit risk support boundary without running history."""
    capability, _converted = _evaluate(
        legs, bound_snapshot_id=bound_snapshot_id)
    return capability


def _transient_portfolio(ctx, converted: list[_ConvertedLeg]) -> PortfolioService:
    base = ctx.portfolio
    transient = PortfolioService(
        market_data=base.market_data,
        pricing=base.pricing,
        audit=getattr(ctx, "audit", None) or base.audit,
        snapshot=getattr(ctx, "snapshot", None) or base.snapshot,
    )
    transient.portfolio.portfolio_id = "pricing-new-transient"
    transient.portfolio.name = "Pricing_new transient worksheet"
    transient.portfolio.base_currency = converted[0].currency
    for item in converted:
        transient.add(Position(
            id=item.leg_id,
            instrument=item.instrument,
            description=item.label,
            quantity=item.quantity,
            params=dict(item.params),
            currency=item.currency,
            book="Pricing_new",
            model_id=item.engine or "",
            metadata={
                "workstation_product": item.product,
                "workstation_engine": item.engine,
                "transient": True,
            },
        ))
    return transient


def _normalized_model(model: str) -> str:
    token = str(model or "").strip().lower()
    token = _MODEL_ALIASES.get(token, token)
    if token not in SUPPORTED_MODELS:
        raise PricingNewRiskError(
            "unsupported_risk_model",
            f"unsupported Pricing_new risk model '{model}'",
            details={"supported_models": sorted(SUPPORTED_MODELS)},
        )
    return token


def _positive_integer(value: Any, label: str, *, lo: int, hi: int) -> int:
    if isinstance(value, bool):
        raise PricingNewRiskError("invalid_risk_parameter", f"{label} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PricingNewRiskError(
            "invalid_risk_parameter", f"{label} must be an integer") from exc
    try:
        exact = number == value
    except Exception:
        exact = False
    if not exact or not lo <= number <= hi:
        raise PricingNewRiskError(
            "invalid_risk_parameter", f"{label} must be between {lo} and {hi}")
    return number


def _confidence(value: Any) -> float:
    if isinstance(value, bool):
        raise PricingNewRiskError(
            "invalid_risk_parameter", "confidence must be between 0 and 1")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PricingNewRiskError(
            "invalid_risk_parameter", "confidence must be between 0 and 1") from exc
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        raise PricingNewRiskError(
            "invalid_risk_parameter", "confidence must be between 0 and 1")
    return number


def _stable_hash(payload: dict) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _model_result(model: str, pnl: np.ndarray, confidence: float, *,
                  n_sims: int, seed: int) -> tuple[float, float, dict]:
    if model == "historical_full_reprice":
        var, es = marketrisk._var_es(-pnl, confidence)
        return var, es, {"method": "historical_full_reprice"}

    from risk.var import montecarlo_var, parametric_var

    if model == "parametric_normal":
        raw = parametric_var(pnl, 1.0, confidence, 1, "normal")
    elif model == "parametric_t":
        raw = parametric_var(pnl, 1.0, confidence, 1, "t")
    else:
        raw = montecarlo_var(
            pnl, 1.0, confidence, 1, n_sims=n_sims, seed=seed)
    var = float(raw["VaR"])
    es = float(raw.get("ES", raw.get("CVaR", var)))
    diagnostics = {
        key: value
        for key, value in raw.items()
        if key not in {"VaR", "ES", "CVaR"}
        and isinstance(value, (str, int, float, bool, type(None)))
    }
    return var, es, diagnostics


def calculate_transient_book_risk(
    ctx,
    legs: Sequence[Any],
    *,
    confidence: float = 0.99,
    window: int = 500,
    horizon: int = 1,
    model: str = "historical_full_reprice",
    n_sims: int = 100_000,
    seed: int = 42,
) -> dict:
    """Calculate VaR/ES for exactly ``legs`` using stored real factor history.

    The function intentionally has no fallback to ``ctx.portfolio``.  If any
    leg cannot be represented by the canonical portfolio repricer, the entire
    request fails with :class:`UnsupportedPricingNewBookError`.
    """
    confidence = _confidence(confidence)
    window = _positive_integer(window, "window", lo=60, hi=10_000)
    horizon = _positive_integer(horizon, "horizon", lo=1, hi=250)
    n_sims = _positive_integer(n_sims, "n_sims", lo=1_000, hi=2_000_000)
    seed = _positive_integer(seed, "seed", lo=0, hi=2_147_483_647)
    model = _normalized_model(model)

    bound_snapshot_id = str(
        getattr(getattr(ctx, "snapshot", None), "snapshot_id", "") or ""
    )
    capability, converted = _evaluate(
        legs, bound_snapshot_id=bound_snapshot_id or None)
    if not capability["supported"]:
        raise UnsupportedPricingNewBookError(
            capability["unsupported"], capability=capability)
    custom_legs = [item.leg_id for item in converted
                   if item.instrument == "custom_product"]
    if custom_legs and horizon != 1:
        raise PricingNewRiskError(
            "custom_horizon_time_roll_unsupported",
            "custom_product historical risk currently supports horizon=1 only; "
            "multi-day horizon requires canonical elapsed-time/seasoned-state "
            "roll-forward",
            details={
                "requested_horizon": horizon,
                "supported_horizon": 1,
                "custom_legs": custom_legs,
                "time_roll_years": 0.0,
            },
        )
    custom_compute = _custom_risk_compute_policy(
        converted,
        requested_scenarios=window,
    )
    custom_request_policy = copy.deepcopy(custom_compute)

    transient = _transient_portfolio(ctx, converted)
    try:
        # Historical risk needs the base PV once; scenario full repricing uses
        # prices only.  Avoid an expensive custom-AST CRN Greek ladder here —
        # Greeks were already produced by the named Pricing_new price run.
        valuation = transient.value(calculate_risk=False)
    except Exception as exc:
        raise PricingNewRiskError(
            "transient_valuation_failed",
            f"Pricing_new transient valuation failed: {exc}") from exc
    if valuation.errors:
        raise PricingNewRiskError(
            "transient_valuation_failed",
            "Pricing_new transient valuation failed: "
            + "; ".join(map(str, valuation.errors)),
            details={"errors": list(map(str, valuation.errors))},
        )
    portfolio_value = float(valuation.total_market_value)
    if not math.isfinite(portfolio_value):
        raise PricingNewRiskError(
            "transient_valuation_failed", "transient portfolio value is non-finite")

    try:
        hyppl_kwargs = {}
        if custom_compute["active"]:
            hyppl_kwargs.update({
                "custom_repricing_profile": CUSTOM_RISK_PROFILE,
                "deadline_seconds": CUSTOM_RISK_DEADLINE_SECONDS,
            })
        hp = marketrisk.hyppl(
            ctx, window=window, portfolio=transient, horizon=horizon,
            **hyppl_kwargs,
        )
        pnl = marketrisk._validated_hyppl(
            hp, context="Pricing_new transient book risk")
    except PricingNewRiskError:
        raise
    except TimeoutError as exc:
        raise PricingNewRiskError(
            "custom_risk_deadline_exceeded",
            f"Pricing_new custom historical repricing exceeded the "
            f"{CUSTOM_RISK_DEADLINE_SECONDS:.0f}s deadline: {exc}",
            details={
                "deadline_seconds": CUSTOM_RISK_DEADLINE_SECONDS,
                "profile": custom_compute.get("profile"),
                "partial_result_published": False,
            },
        ) from exc
    except Exception as exc:
        raise PricingNewRiskError(
            "historical_repricing_failed",
            f"Pricing_new historical full repricing failed: {exc}") from exc

    if custom_compute["active"]:
        repricing_evidence = hp.get("repricing_evidence")
        scenario_matrix_hash = str(hp.get("scenario_matrix_hash") or "")
        evidence_valid = (
            isinstance(repricing_evidence, Mapping)
            and repricing_evidence.get("profile") == CUSTOM_RISK_PROFILE
            and repricing_evidence.get("inner_paths") == CUSTOM_RISK_INNER_PATHS
            and repricing_evidence.get("common_random_numbers") is True
            and repricing_evidence.get("paired_profile_base") is True
            and repricing_evidence.get("scenario_count") == len(pnl)
            and repricing_evidence.get("base_value") is not None
            and len(scenario_matrix_hash) == 64
        )
        if not evidence_valid:
            raise PricingNewRiskError(
                "historical_repricing_failed",
                "Pricing_new custom historical repricing did not return the "
                "required paired-CRN profile evidence",
                details={
                    "required_profile": CUSTOM_RISK_PROFILE,
                    "required_inner_paths": CUSTOM_RISK_INNER_PATHS,
                    "received_evidence": (
                        dict(repricing_evidence)
                        if isinstance(repricing_evidence, Mapping) else None
                    ),
                    "scenario_matrix_hash": scenario_matrix_hash or None,
                },
            )
        custom_compute = _custom_risk_compute_policy(
            converted,
            requested_scenarios=window,
            actual_scenarios=len(pnl),
            enforce=False,
        )
        custom_compute["execution"] = dict(repricing_evidence)

    try:
        var, es, model_diagnostics = _model_result(
            model, pnl, confidence, n_sims=n_sims, seed=seed)
    except Exception as exc:
        raise PricingNewRiskError(
            "risk_model_failed", f"Pricing_new risk model failed: {exc}") from exc
    if not all(math.isfinite(value) for value in (var, es)):
        raise PricingNewRiskError(
            "risk_model_failed", "Pricing_new risk model returned non-finite VaR/ES")

    request_inputs = {
        "schema": "pricing-new-transient-risk-v1",
        "legs": [
            {
                "id": item.leg_id,
                "label": item.label,
                "product": item.product,
                "engine": item.engine,
                "currency": item.currency,
                "quantity": item.quantity,
                "instrument": item.instrument,
                "params": item.params,
            }
            for item in converted
        ],
        "confidence": confidence,
        "window": window,
        "horizon": horizon,
        "model": model,
        "n_sims": n_sims if model == "monte_carlo_fitted_normal" else None,
        "seed": seed if model == "monte_carlo_fitted_normal" else None,
        "snapshot_id": str(getattr(getattr(ctx, "snapshot", None), "snapshot_id", "")),
        "custom_repricing": (
            custom_request_policy if custom_request_policy["active"] else None
        ),
    }
    inputs_hash = _stable_hash(request_inputs)
    calculation_id = ""
    timestamp = ""
    audit = getattr(ctx, "audit", None)
    if audit is not None and hasattr(audit, "record_calculation"):
        record = audit.record_calculation(
            user_action="Calculate Pricing_new transient book risk",
            calculation_type="pricing_new_market_risk",
            model_id=model,
            model_version="v1",
            market_data_snapshot_id=request_inputs["snapshot_id"],
            inputs=request_inputs,
            result_id=f"pricing_new_risk:{inputs_hash[:16]}",
            details={
                "positions": len(converted),
                "confidence": confidence,
                "window": window,
                "horizon": horizon,
                "var": var,
                "es": es,
                "scenario_count": len(pnl),
                "custom_repricing_profile": custom_compute.get("profile"),
                "custom_work_path_points": custom_compute.get(
                    "actual_work_path_points"),
                "scenario_matrix_hash": hp.get("scenario_matrix_hash"),
            },
        )
        calculation_id = str(getattr(record, "record_id", "") or "")
        record_timestamp = getattr(record, "timestamp", None)
        timestamp = record_timestamp.isoformat() if record_timestamp is not None else ""
        inputs_hash = str(getattr(record, "inputs_hash", "") or inputs_hash)

    dates = list(hp.get("dates") or [])
    model_meta = SUPPORTED_MODELS[model]
    return {
        "scope": "pricing_new_transient_book",
        "partial": False,
        "confidence": confidence,
        "window": window,
        "horizon": horizon,
        "horizon_method": hp.get("horizon_method", "none"),
        "model": model,
        "model_label": model_meta["label"],
        "model_diagnostics": model_diagnostics,
        "currency": capability["base_currency"],
        "portfolio_value": portfolio_value,
        "positions": len(converted),
        "var": var,
        "es": es,
        "n_scenarios": len(pnl),
        "histogram": marketrisk._histogram(pnl),
        "hyppl": [
            {"date": date, "pnl": float(value)}
            for date, value in zip(dates, pnl.tolist())
        ],
        "factors": list(hp.get("factors") or []),
        "data_quality": sorted(set(
            list(hp.get("factor_warnings") or [])
            + list(hp.get("reprice_warnings") or [])
        )),
        "capability": capability,
        "provenance": {
            "history_source": "stored_market_factor_history",
            "history_first_date": dates[0] if dates else None,
            "history_last_date": dates[-1] if dates else None,
            "history_observations": len(dates),
            "factor_diagnostics": dict(hp.get("factor_diagnostics") or {}),
            "snapshot_id": request_inputs["snapshot_id"],
            "valuation_date": str(
                getattr(getattr(ctx, "snapshot", None), "valuation_date", "") or ""),
            "calculation_id": calculation_id,
            "calculation_timestamp": timestamp,
            "inputs_hash": inputs_hash,
            "scenario_matrix_hash": hp.get("scenario_matrix_hash"),
            "portfolio_source": "request_legs_only",
            "global_portfolio_used": False,
            "custom_repricing": (
                custom_compute if custom_compute["active"] else None
            ),
        },
    }
