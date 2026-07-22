"""End-to-end binding of governed MOEX fixings into actual-state HypPL."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from api import custom_products, marketrisk, pricing_new_risk
from domain.portfolio import Position
from infra.db.market_data_db import MarketDataDB
from infra.moex_calendar import (
    MoexCalendarResolver,
    calendar_payload_hash,
)
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService


def _sha(payload: object) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _definition() -> dict:
    return {
        "name": "Actual-state integration note",
        "description": "MOEX fixing-ledger integration test",
        "author": "test",
        "assets": ["S"],
        "slots": {},
        "state": {"accrued": 0.0},
        "schedule": {"observations": 2, "maturity": 1.0},
        "observation_program": [{
            "action": "accumulate",
            "name": "accrued",
            "value": {"node": "accrual"},
        }],
        "maturity_program": [{
            "action": "pay",
            "amount": {"node": "state", "name": "accrued"},
        }],
    }


def _published_store(monkeypatch, tmp_path) -> tuple[dict, dict]:
    store = custom_products.CustomProductStore(str(tmp_path / "custom.json"))
    monkeypatch.setattr(custom_products, "_STORE", store)
    created = store.create(definition=_definition(), author="maker")
    store.compile(created["id"])
    store.submit(created["id"], "maker")
    store.approve(created["id"], "checker")
    detail = store.publish(created["id"])
    return detail, detail["definition"]


def _calendar(db: MarketDataDB) -> tuple[MoexCalendarResolver, dict]:
    start, end = date(2024, 12, 30), date(2025, 8, 1)
    rows = []
    cursor = start
    while cursor <= end:
        traded = int(cursor.weekday() < 5)
        rows.append({
            "tradedate": cursor.isoformat(),
            "is_traded": traded,
            "trade_session_date": None,
            "reason": None if traded else "H",
            "updatetime": "2025-08-01 23:00:00",
        })
        cursor += timedelta(days=1)
    digest = calendar_payload_hash(
        calendar_id="MOEX_STOCK", market="stock",
        from_date=start, till_date=end, days=rows,
    )
    stored = db.save_trading_calendar_version(
        calendar_id="MOEX_STOCK", market="stock",
        from_date=start, till_date=end, days=rows,
        source="MOEX",
        source_url="https://apim.moex.com/iss/calendars/stock",
        payload_hash=digest,
        fetched_at="2025-08-01T23:01:00+00:00",
    )
    return MoexCalendarResolver.from_db(
        db, "MOEX_STOCK", int(stored["version"])), stored


def _environment(monkeypatch, tmp_path, *, missing_fixing: str | None = None):
    detail, definition = _published_store(monkeypatch, tmp_path)
    db = MarketDataDB(":memory:")
    db.init_schema()
    resolver, stored = _calendar(db)

    effective = "2025-01-02"
    maturity = "2025-07-31"
    sessions = [
        item.isoformat()
        for item in resolver.business_sessions(effective, maturity)
    ]
    observation_dates = [sessions[62], sessions[-1]]
    schedule = custom_products.canonical_instance_contract_schedule(
        definition,
        {
            "effective_date": effective,
            "contractual_observation_dates": observation_dates,
            "observation_dates": observation_dates,
            "contractual_maturity_date": maturity,
            "maturity_date": maturity,
            "business_day_convention": "UNADJUSTED",
            "fixing_convention": "MOEX_OFFICIAL_CLOSE",
            "calendar": {
                "calendar_id": "MOEX_STOCK",
                "source": "MOEX ISS official calendar payload",
                "version": str(stored["version"]),
                "payload_hash": resolver.payload_hash,
                "resolved_sessions": sessions,
            },
        },
    )
    seed = custom_products.inception_valuation_seed(
        definition, schedule, {"S": 100.0},
    )
    cutoff = sessions[100]
    ledger_rows = [
        {"date": session, "spots": {"S": 100.0 + index * 0.05}}
        for index, session in enumerate(sessions)
        if session <= cutoff
    ]
    captured_ledger = custom_products.canonical_dated_fixing_ledger(
        definition,
        schedule,
        {
            "source": "test exact MOEX fixings",
            "source_version": "test-v1",
            "payload_hash": "a" * 64,
            "fixings": ledger_rows,
        },
    )
    captured = custom_products.reconstruct_historical_valuation_state(
        definition, schedule, seed, captured_ledger, cutoff,
    )["valuation_state"]

    binding = {
        "asset_name": "S",
        "secid": "SBER",
        "factor_id": "SBER:price",
        "price_basis": "CLOSE",
        "board": "TQBR",
        "session": "",
        "source": "MOEX",
        "missing_fixing_policy": "error",
    }
    bindings = {
        "schema_version": 1,
        "contract": "moex_exact_fixing_bindings_v1",
        "schedule_hash": schedule["schedule_hash"],
        "calendar_id": "MOEX_STOCK",
        "calendar_version": int(stored["version"]),
        "calendar_payload_hash": resolver.payload_hash,
        "asset_names": ["S"],
        "bindings": [binding],
    }
    bindings["bindings_hash"] = _sha(bindings)

    db_rows = []
    for row in ledger_rows:
        if row["date"] == missing_fixing:
            continue
        semantic = {
            "factor_id": "SBER:price",
            "observed_date": row["date"],
            "value": row["spots"]["S"],
            "price_basis": "CLOSE",
            "board": "TQBR",
            "session": "",
            "source": "MOEX",
        }
        db_rows.append({
            **semantic,
            "fetched_at": "2025-08-01T23:05:00+00:00",
            "payload_hash": _sha(semantic),
        })
    db.save_contract_fixings(db_rows)

    service = PortfolioService(market_data=MarketDataService(market_db=db))
    service.add(Position(
        id="custom-actual",
        instrument="custom_product",
        quantity=1_000.0,
        currency="RUB",
        description="Actual-state custom product",
        params={
            "custom_product_id": detail["id"],
            "definition_version": detail["version"],
            "definition_hash": detail["definition_hash"],
            "slots": {},
            "asset_names": ["S"],
            "component_secids": ["SBER"],
            "contract_schedule": schedule,
            "fixing_bindings": bindings,
            "inception_seed": seed,
            "valuation_state": captured,
        },
    ))

    # Include one pre-effective window, followed by 61 valid one-session
    # windows.  The former may be dropped; the valid in-life set must stay
    # exactly aligned across every scenario array.
    scenario_sessions = sessions[:62]
    starts = ["2025-01-01", *scenario_sessions[:-1]]
    ends = scenario_sessions
    paths = [[end] for end in ends]
    count = len(ends)
    zeros = np.zeros(count)
    shifts = {
        "dates": ends,
        "previous_dates": starts,
        "eq": zeros.copy(), "dr": zeros.copy(),
        "dvol": zeros.copy(), "fx": zeros.copy(),
        "dr_tenors": {}, "dr_curves": {},
        "eq_names": {"SBER": zeros.copy()},
        "vol_names": {}, "dvol_positions": {}, "fx_pairs": {},
        "factors": ["SBER:price"],
        "spot_return_paths": {
            "schema": "historical-spot-return-paths-v1",
            "day_count_basis": 252,
            "dates": paths,
            "start_dates": starts,
            "fallback_log_returns": [[0.0] for _ in ends],
            "log_returns_by_factor": {
                "SBER": [[0.0] for _ in ends],
            },
        },
    }
    return SimpleNamespace(market_db=db), service, shifts, cutoff


def test_actual_prepare_builds_private_hash_bound_ledger_and_drops_only_pre_effective(
    monkeypatch, tmp_path,
):
    ctx, original, shifts, cutoff = _environment(monkeypatch, tmp_path)

    prepared, prepared_shifts = marketrisk._prepare_actual_trade_backcast(
        ctx, original, shifts,
    )

    assert "historical_backcast_contract" not in original.positions[0].params
    contract = prepared.positions[0].params["historical_backcast_contract"]
    assert contract["schema"] == "custom-product-actual-backcast-v1"
    assert contract["fixing_ledger"]["fixings"][-1]["date"] == cutoff
    assert len(contract["contract_hash"]) == 64
    meta = prepared_shifts["actual_trade_backcast"]
    assert meta["dropped_pre_effective_scenarios"] == 1
    assert meta["scenario_count"] == 61
    assert len(prepared_shifts["dates"]) == 61
    assert meta["positions"][0]["backcast_contract_hash"] == \
        contract["contract_hash"]
    assert len(meta["positions"][0]["current_state_reconciliation_hash"]) == 64


def test_actual_prepare_fails_closed_on_one_missing_exact_moex_fixing(
    monkeypatch, tmp_path,
):
    missing = "2025-02-03"
    ctx, service, shifts, _cutoff = _environment(
        monkeypatch, tmp_path, missing_fixing=missing,
    )

    with pytest.raises(ValueError, match="exact fixing coverage failed"):
        marketrisk._prepare_actual_trade_backcast(ctx, service, shifts)


def test_actual_reprice_threads_scenario_dates_and_collects_dated_evidence():
    token = "d" * 64

    class ActualPortfolio:
        positions = [SimpleNamespace(
            id="custom-actual", instrument="custom_product")]

        @staticmethod
        def full_reprice_pnl(**kwargs):
            assert kwargs["historical_state_mode"] == "actual_trade_backcast"
            assert kwargs["custom_path_scenario"]["start_date"] == "2025-04-01"
            assert kwargs["custom_path_scenario"]["end_date"] == "2025-04-02"
            assert kwargs["custom_path_scenario"]["dates"] == ["2025-04-02"]
            return {
                "pnl": 2.5,
                "base_value": 101.0,
                "shocked_value": 103.5,
                "errors": [],
                "valid": True,
                "warnings": [],
                "historical_state_mode": "actual_trade_backcast",
                "custom_repricing_profile": "custom_hist_crn_v1",
                "base_value_source": "actual_trade_backcast_reconstructed",
                "pnl_convention": (
                    "horizon_cashflows_plus_end_pv_minus_backcast_start_pv"),
                "actual_trade_backcast_evidence": [{
                    "position_id": "custom-actual",
                    "backcast_contract_hash": token,
                    "start_state_value": 0.101,
                    "end_state_value": 0.1035,
                    "normalized_horizon_cashflow": 0.0,
                    "quantity": 1_000.0,
                    "cashflow_unit": "normalized_notional",
                    "reconstruction": {
                        "contract": (
                            "custom_ast_historical_state_reconstruction_v1"),
                        "end_as_of": "2025-04-01",
                        "schedule_hash": token,
                        "fixing_ledger_hash": token,
                        "transition_hash": token,
                    },
                    "dated_roll": {
                        "contract": "custom_ast_dated_path_roll_v1",
                        "start_as_of": "2025-04-01",
                        "end_as_of": "2025-04-02",
                        "transition_hash": token,
                        "cashflow_ledger_hash": token,
                    },
                }],
            }

    zeros = np.zeros(1)
    shifts = {
        "dates": ["2025-04-02"],
        "previous_dates": ["2025-04-01"],
        "eq": zeros, "dr": zeros, "dvol": zeros, "fx": zeros,
        "dr_tenors": {}, "dr_curves": {}, "eq_names": {},
        "vol_names": {}, "dvol_positions": {}, "fx_pairs": {},
        "spot_return_paths": {
            "schema": "historical-spot-return-paths-v1",
            "day_count_basis": 252,
            "dates": [["2025-04-02"]],
            "start_dates": ["2025-04-01"],
            "fallback_log_returns": [[0.0]],
            "log_returns_by_factor": {},
        },
        "actual_trade_backcast": {
            "schema": "actual-trade-state-backcast-scenarios-v1",
            "scenario_count": 1,
            "positions": [{"position_id": "custom-actual"}],
        },
    }
    evidence = {}

    pnl, warnings = marketrisk._reprice_series(
        ActualPortfolio(), shifts,
        custom_repricing_profile="custom_hist_crn_v1",
        historical_state_mode="actual_trade_backcast",
        evidence=evidence,
    )

    assert pnl.tolist() == [2.5]
    assert warnings == set()
    assert evidence["paired_scenario_start_end"] is True
    assert evidence["paired_profile_base"] is False
    assert evidence["scenario_base_values"] == [101.0]
    assert evidence["actual_trade_backcast_evidence"][0][
        "scenario_start_date"] == "2025-04-01"
    assert evidence["pnl_convention"] == (
        "horizon_cashflows_plus_end_pv_minus_backcast_start_pv")


def test_pricing_new_accepts_complete_actual_evidence_and_rejects_pnl_tamper():
    token = "e" * 64
    position_meta = {
        "position_id": "custom-actual",
        "schedule_hash": token,
        "bindings_hash": token,
        "inception_seed_hash": token,
        "fixing_ledger_hash": token,
        "fixing_source_hash": token,
        "backcast_contract_hash": token,
        "current_state_reconciliation_hash": token,
    }
    reconstruction = {
        "contract": "custom_ast_historical_state_reconstruction_v1",
        "definition_hash": token,
        "schedule_hash": token,
        "calendar_source_hash": token,
        "initial_state_hash": token,
        "fixing_ledger_hash": token,
        "fixing_source_hash": token,
        "cashflow_ledger_hash": token,
        "output_state_hash": token,
        "transition_hash": token,
        "inception_seed_hash": token,
        "start_as_of": "2025-01-02",
        "end_as_of": "2025-04-01",
        "terminal": False,
    }
    dated_roll = {
        "contract": "custom_ast_dated_path_roll_v1",
        "definition_hash": token,
        "schedule_hash": token,
        "calendar_source_hash": token,
        "initial_state_hash": token,
        "fixing_ledger_hash": token,
        "fixing_source_hash": token,
        "cashflow_ledger_hash": token,
        "output_state_hash": token,
        "transition_hash": token,
        "start_as_of": "2025-04-01",
        "end_as_of": "2025-04-02",
        "terminal": False,
    }
    record = {
        "scenario_index": 0,
        "scenario_start_date": "2025-04-01",
        "scenario_end_date": "2025-04-02",
        "position_id": "custom-actual",
        "backcast_contract_hash": token,
        "start_state_value": 0.100,
        "end_state_value": 0.102,
        "normalized_horizon_cashflow": 0.001,
        "quantity": 1_000.0,
        "cashflow_unit": "normalized_notional",
        "reconstruction": reconstruction,
        "dated_roll": dated_roll,
    }
    evidence = {
        "profile": "custom_hist_crn_v1",
        "inner_paths": pricing_new_risk.CUSTOM_RISK_INNER_PATHS,
        "common_random_numbers": True,
        "paired_profile_base": False,
        "paired_scenario_start_end": True,
        "base_value": None,
        "base_value_repriced_once": False,
        "base_value_sources": [],
        "scenario_count": 1,
        "scenario_base_values": [100.0],
        "spot_shock_convention": "log",
        "path_roll_applied": True,
        "path_days": 1,
        "path_day_count_basis": 252,
        "path_roll_contract": "custom_ast_dated_path_roll_v1",
        "path_roll_hashes": [],
        "path_roll_evidence": [],
        "historical_state_mode": "actual_trade_backcast",
        "pnl_convention": (
            "horizon_cashflows_plus_end_pv_minus_backcast_start_pv"),
        "loss_convention": "negative_pnl",
        "actual_trade_backcast_evidence": [record],
        "actual_trade_backcast": {
            "schema": "actual-trade-state-backcast-scenarios-v1",
            "calendar_id": "MOEX_STOCK",
            "calendar_version": 1,
            "calendar_payload_hash": token,
            "dropped_pre_effective_scenarios": 3,
            "scenario_count": 1,
            "positions": [position_meta],
            "non_spot_market_parameter_basis": (
                "current_snapshot_levels_plus_historical_rate_vol_changes"),
        },
    }

    valid, provenance = pricing_new_risk._validate_actual_trade_backcast_evidence(
        evidence,
        scenario_dates=["2025-04-02"],
        pnl=np.asarray([3.0]),
        custom_leg_ids=["custom-actual"],
        horizon=1,
    )
    assert valid is True
    assert provenance["evidence_record_count"] == 1
    assert len(provenance["evidence_hash"]) == 64

    invalid, _ = pricing_new_risk._validate_actual_trade_backcast_evidence(
        evidence,
        scenario_dates=["2025-04-02"],
        pnl=np.asarray([3.01]),
        custom_leg_ids=["custom-actual"],
        horizon=1,
    )
    assert invalid is False
