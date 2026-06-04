"""Phase C — equity/index time series feeding VaR / backtest / stress (fixtures)."""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, timedelta

import numpy as np
import pytest

from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.ingest import MoexIngestor
from services.market_data_service import MarketDataService
from services.risk_service import RiskService
from risk.historical_var import backtest_var

VAL = date(2026, 6, 2)


def _price_history(n=60, start=3000.0, drift=0.0003, vol=0.012, seed=1):
    """Deterministic synthetic close-price history rows (TRADEDATE, CLOSE)."""
    rng = np.random.default_rng(seed)
    px = start
    rows = []
    d = date(2026, 1, 1)
    for _ in range(n):
        px *= math.exp(drift + vol * rng.standard_normal())
        rows.append({"TRADEDATE": d.isoformat(), "CLOSE": round(px, 2)})
        d += timedelta(days=1)
    return rows


class FakeClient:
    def __init__(self, blocks): self.blocks = blocks
    def get_blocks(self, path, params=None): return self.blocks.get(path, {})
    def get_block_paginated(self, path, block, params=None, **kw):
        return self.blocks.get(path, {}).get(block, [])


# ── ingestion ────────────────────────────────────────────

def test_ingest_index_history_to_time_series():
    db = MarketDataDB(":memory:")
    path = "history/engines/stock/markets/index/securities/IMOEX"
    client = FakeClient({path: {"history": _price_history(40)}})
    n = MoexIngestor(client, db).ingest_index_history("IMOEX", date(2026, 1, 1), VAL)
    assert n == 40
    ts = db.get_time_series("IMOEX:price", "price")
    assert len(ts) == 40 and ts[0]["value"] > 0


def test_ingest_equity_history_to_time_series():
    db = MarketDataDB(":memory:")
    path = "history/engines/stock/markets/shares/boards/TQBR/securities/SBER"
    client = FakeClient({path: {"history": _price_history(30, start=300.0)}})
    n = MoexIngestor(client, db).ingest_equity_history("SBER", date(2026, 1, 1), VAL)
    assert n == 30
    assert len(db.get_time_series("SBER:price", "price")) == 30


def test_ingest_equity_quotes_spot():
    db = MarketDataDB(":memory:")
    path = "engines/stock/markets/shares/boards/TQBR/securities"
    client = FakeClient({path: {
        "securities": [{"SECID": "SBER", "PREVPRICE": 305.0}],
        "marketdata": [{"SECID": "SBER", "LAST": 307.5, "VALTODAY": 1e9}],
    }})
    sid = MoexIngestor.snapshot_id_for(VAL)
    n = MoexIngestor(client, db).ingest_equity_quotes(sid, VAL)
    assert n == 1
    assert db.get_equity_spot(sid, "SBER") == pytest.approx(307.5)


# ── returns builder ──────────────────────────────────────

def test_get_returns_log_and_simple():
    db = MarketDataDB(":memory:")
    db.save_time_series("X:price", "price",
                        [("2026-06-01", 100.0), ("2026-06-02", 110.0), ("2026-06-03", 99.0)])
    svc = MarketDataService(market_db=db)
    log_r = svc.get_returns("X:price", method="log")
    assert log_r[0] == pytest.approx(math.log(110/100))
    simple_r = svc.get_returns("X:price", method="simple")
    assert simple_r[0] == pytest.approx(0.10)


def test_get_returns_requires_db():
    with pytest.raises(RuntimeError, match="market_db"):
        MarketDataService().get_returns("X:price")


# ── feed into VaR / backtest / stress ────────────────────

def _service_with_index():
    db = MarketDataDB(":memory:")
    path = "history/engines/stock/markets/index/securities/IMOEX"
    client = FakeClient({path: {"history": _price_history(120, seed=7)}})
    MoexIngestor(client, db).ingest_index_history("IMOEX", date(2026, 1, 1), VAL)
    return MarketDataService(market_db=db)


@pytest.mark.parametrize("method", ["historical", "parametric", "monte_carlo"])
def test_var_from_index_returns(method):
    svc = _service_with_index()
    returns = svc.get_returns("IMOEX:price")
    assert returns.size == 119
    res = RiskService().var(returns, position_value=1_000_000, confidence=0.99, method=method)
    assert res["value"] is not None and res["value"] > 0
    assert res["raw"]["CVaR"] >= res["raw"]["VaR"] - 1e-9  # ES >= VaR


def test_backtest_from_index_returns():
    svc = _service_with_index()
    returns = svc.get_returns("IMOEX:price")
    position = 1_000_000.0
    pnl = returns * position
    var_pct = RiskService().var(returns, position, confidence=0.99)["raw"]["VaR_pct"]
    var_series = np.full(len(pnl), var_pct * position)
    bt = backtest_var(pnl, var_series, confidence=0.99)
    assert bt["n_obs"] == len(pnl)
    assert bt["basel_zone"] in {"Green", "Yellow", "Red"}
    assert 0 <= bt["exception_rate"] <= 1


def test_historical_stress_scenario_from_returns():
    svc = _service_with_index()
    returns = svc.get_returns("IMOEX:price")
    position = 1_000_000.0
    worst_move = float(returns.min())            # worst 1-day historical return
    stress_loss = -worst_move * position
    assert worst_move < 0 and stress_loss > 0
    assert math.isfinite(stress_loss)
