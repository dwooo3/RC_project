"""Market Risk workstation (Calypso ERS-style) for the bridge.

Two-step process, faithful to the doc: (1) shifts generation — joint daily
factor changes from REAL stored history (IMOEX equity returns, КБД 5Y absolute
rate changes, RVI vol-point changes); (2) risk metric computation — the demo
book is FULL-REPRICED through its actual pricers on every historical scenario
(PortfolioService.full_reprice_pnl), giving a Hypothetical P&L distribution
from which VaR / ES / EVT metrics and the backtest are computed.

FX fixings history is too short in the store (12 snapshots), so the FX factor
is zero for now — flagged in `data_quality`.
"""

from __future__ import annotations

import math

import numpy as np

# HypPL series cache: (snapshot_id, window) -> {"dates": [...], "pnl": np.ndarray, ...}
_CACHE: dict = {}


def invalidate_cache() -> None:
    """Drop cached HypPL series — called on any portfolio mutation."""
    _CACHE.clear()


def _series(db, factor_id: str) -> list[tuple[str, float]]:
    rows = db.get_time_series(factor_id) or []
    return [(r["dt"], float(r["value"])) for r in rows if r.get("value") is not None]


# Named stress windows for Stress VaR (Calypso §2.3): a fixed historical
# period whose shifts are applied to the CURRENT portfolio.
STRESS_WINDOWS = {
    "2022": ("2022-01-01", "2022-12-30"),          # мобилизация/санкции
    "2024h2": ("2024-09-01", "2025-03-31"),        # цикл КС 21%
}


def factor_shifts(ctx, window: int = 500, frm: str | None = None,
                  till: str | None = None) -> dict:
    """Step 1 — shifts generation: aligned joint daily factor changes.
    ``frm``/``till`` clip to a fixed period (stress window) — then ``window``
    is ignored."""
    db = ctx.market_db
    eq = dict(_series(db, "IMOEX:price"))
    kbd = dict(_series(db, "KBD:5Y"))
    usd = dict(_series(db, "USDRUB:fix"))
    # vega factor: собственная ATM-IV история (индексные андерлаинги FORTS),
    # когда накопится >=60 точек; до тех пор — RVI-прокси. IV уже в decimal.
    rvi, vol_label, vol_scale = {}, "RVI (vol, Δ points)", 1.0 / 100.0
    for iv_id in ("IV:MIX", "IV:MXI", "IV:RTS"):
        s = dict(_series(db, iv_id))
        if len(s) >= 60:
            rvi, vol_label, vol_scale = s, f"{iv_id} (vol, ΔIV own history)", 1.0
            break
    if not rvi:
        rvi = dict(_series(db, "RVI:price"))
    dates = sorted(set(eq) & set(kbd) & set(rvi))
    if frm or till:
        dates = [d for d in dates if (not frm or d >= frm) and (not till or d <= till)]
        window = 0
    if len(dates) < 60:
        raise ValueError("not enough joint factor history (need >= 60 days)")
    has_fx = len(usd) >= 60

    out_dates, eq_ret, dr, dvol, fx_ret = [], [], [], [], []
    for prev, cur in zip(dates, dates[1:]):
        if eq[prev] <= 0 or eq[cur] <= 0:
            continue
        out_dates.append(cur)
        eq_ret.append(math.log(eq[cur] / eq[prev]))
        dr.append(kbd[cur] - kbd[prev])                 # КБД already decimal
        dvol.append((rvi[cur] - rvi[prev]) * vol_scale)  # points/100 или own IV
        # FX fixings can miss local holidays — carry the last known fix.
        if has_fx and usd.get(prev, 0) > 0 and usd.get(cur, 0) > 0:
            fx_ret.append(math.log(usd[cur] / usd[prev]))
        else:
            fx_ret.append(0.0)
    if window and len(out_dates) > window:
        out_dates, eq_ret, dr, dvol, fx_ret = (
            out_dates[-window:], eq_ret[-window:], dr[-window:],
            dvol[-window:], fx_ret[-window:])
    factors = ["IMOEX (equity, log-return)", "КБД 5Y (rates, abs Δ)",
               vol_label,
               "USD/RUB fix (fx, log-return)" if has_fx
               else "FX (no history — zero)"]
    return {
        "dates": out_dates,
        "eq": np.array(eq_ret), "dr": np.array(dr), "dvol": np.array(dvol),
        "fx": np.array(fx_ret),
        "factors": factors,
        "has_fx": has_fx,
    }


def _reprice_series(ps, shifts: dict) -> tuple[np.ndarray, set[str]]:
    pnl = np.empty(len(shifts["dates"]))
    errors: set[str] = set()
    for i in range(len(pnl)):
        res = ps.full_reprice_pnl(dS=float(shifts["eq"][i]), dr=float(shifts["dr"][i]),
                                  dvol=float(shifts["dvol"][i]), dfx=float(shifts["fx"][i]))
        pnl[i] = res["pnl"]
        errors.update(res["errors"])
    return pnl, errors


def hyppl(ctx, window: int = 500, frm: str | None = None,
          till: str | None = None, portfolio=None) -> dict:
    """Step 2 — Hypothetical P&L: full revaluation of the book on every
    historical joint scenario. Cached per (snapshot, window/stress period) for
    the MAIN book; ad-hoc books (what-if) are never cached."""
    key = (getattr(ctx.snapshot, "snapshot_id", "?"), int(window), frm, till)
    if portfolio is None and key in _CACHE:
        return _CACHE[key]
    shifts = factor_shifts(ctx, window, frm, till)
    ps = portfolio if portfolio is not None else ctx.portfolio
    pnl, errors = _reprice_series(ps, shifts)
    out = {"dates": shifts["dates"], "pnl": pnl, "factors": shifts["factors"],
           "reprice_errors": sorted(errors)}
    if portfolio is None:
        _CACHE[key] = out
    return out


def _histogram(pnl: np.ndarray, bins: int = 31) -> list[dict]:
    counts, edges = np.histogram(pnl, bins=bins)
    return [{"x": float((edges[i] + edges[i + 1]) / 2), "count": int(counts[i])}
            for i in range(len(counts))]


def _var_es(losses: np.ndarray, confidence: float) -> tuple[float, float]:
    var = float(np.quantile(losses, confidence))
    tail = losses[losses >= var]
    return var, (float(tail.mean()) if tail.size else var)


def overview(ctx, confidence: float = 0.99, window: int = 500,
             horizon: int = 1, stress: str | None = None) -> dict:
    """VaR analysis report: HypPL distribution + metrics by method + drill-down.
    ``stress`` selects a named fixed historical period (Stress VaR)."""
    from risk.var import evt_var, montecarlo_var, parametric_var

    frm, till = STRESS_WINDOWS.get(stress or "", (None, None))
    hp = hyppl(ctx, window, frm, till)
    pnl = hp["pnl"] * math.sqrt(max(horizon, 1))     # sqrt-time to the horizon
    losses = -pnl
    var_h, es_h = _var_es(losses, confidence)

    methods = [{
        "method": "historical", "label": "Historical (full reprice)",
        "model_id": "var_full_reprice", "var": var_h, "es": es_h,
    }]
    try:
        p = parametric_var(pnl, 1.0, confidence, 1, "normal")
        methods.append({"method": "parametric", "label": "Parametric (normal)",
                        "model_id": "var_parametric",
                        "var": float(p["VaR"]), "es": float(p.get("ES", p["VaR"]))})
    except Exception:
        pass
    try:
        t = parametric_var(pnl, 1.0, confidence, 1, "t")
        methods.append({"method": "parametric_t", "label": "Parametric (Student-t)",
                        "model_id": "var_parametric",
                        "var": float(t["VaR"]), "es": float(t.get("ES", t["VaR"]))})
    except Exception:
        pass
    try:
        mc = montecarlo_var(pnl, 1.0, confidence, 1)
        methods.append({"method": "monte_carlo", "label": "Monte Carlo (fitted normal)",
                        "model_id": "var_mc",
                        "var": float(mc["VaR"]), "es": float(mc.get("ES", mc["VaR"]))})
    except Exception:
        pass
    try:
        ev = evt_var(pnl, 1.0, max(confidence, 0.99))
        methods.append({"method": "evt", "label": "EVT (GPD tail)",
                        "model_id": "evt_var",
                        "var": float(ev["VaR"]), "es": float(ev.get("ES", ev["VaR"]))})
    except Exception:
        pass

    order = np.argsort(pnl)
    worst = [{"date": hp["dates"][int(i)], "pnl": float(pnl[int(i)])} for i in order[:5]]
    best = [{"date": hp["dates"][int(i)], "pnl": float(pnl[int(i)])} for i in order[-5:][::-1]]

    val = ctx.portfolio.value()
    quality = []
    if any("no history" in f for f in hp["factors"]):
        quality.append("FX-фактор без истории — валютный риск в HypPL не учтён")
    if hp["reprice_errors"]:
        quality.append(f"{len(hp['reprice_errors'])} позиций не переоценились")

    return {
        "confidence": confidence, "window": window, "horizon": horizon,
        "stress": stress or "",
        "stress_period": f"{frm} … {till}" if frm else "",
        "n_scenarios": len(pnl),
        "portfolio_value": float(val.total_market_value),
        "positions": len(ctx.portfolio.positions),
        "var": var_h, "es": es_h,
        "methods": methods,
        "histogram": _histogram(pnl),
        "var_line": -var_h,
        "hyppl": [{"date": d, "pnl": float(p)} for d, p in zip(hp["dates"], pnl.tolist())],
        "worst": worst, "best": best,
        "factors": hp["factors"],
        "data_quality": quality,
        "pnl_mean": float(pnl.mean()), "pnl_std": float(pnl.std()),
    }


def incremental(ctx, product: str, engine: str | None, params: dict,
                quantity: float = 1.0, confidence: float = 0.99,
                window: int = 500) -> dict:
    """Incremental VaR (Calypso §2.3): VaR(book + hypothetical trade) −
    VaR(book), full revaluation on the same historical scenarios. The trade is
    NOT persisted — pure what-if."""
    import copy

    from api.pricing_workstation import to_position
    from domain.portfolio import Position
    from services.portfolio_service import PortfolioService

    mapped = to_position(product, params)
    if mapped is None:
        raise ValueError(f"'{product}' не поддерживается портфельной переоценкой")
    instrument, pos_params, desc = mapped

    base_hp = hyppl(ctx, window)
    losses = -base_hp["pnl"]
    var_base, _ = _var_es(losses, confidence)

    trade = Position(id="whatif_trade", instrument=instrument, quantity=quantity,
                     description=desc, params=pos_params)

    what_if = PortfolioService()
    for pos in ctx.portfolio.positions:
        what_if.add(copy.deepcopy(pos))
    what_if.add(copy.deepcopy(trade))
    hp_new = hyppl(ctx, window, portfolio=what_if)
    var_new, _ = _var_es(-hp_new["pnl"], confidence)

    solo = PortfolioService()
    solo.add(copy.deepcopy(trade))
    hp_solo = hyppl(ctx, window, portfolio=solo)
    var_solo, _ = _var_es(-hp_solo["pnl"], confidence)

    incr = var_new - var_base
    return {
        "product": product, "instrument": instrument, "quantity": quantity,
        "confidence": confidence, "window": window,
        "var_base": var_base, "var_with_trade": var_new,
        "incremental_var": incr,
        "standalone_var": var_solo,
        "diversification_benefit": var_solo - incr,
    }


def pnl_explain(ctx, theta_days: float = 1.0) -> dict:
    """P&L Explained (Calypso §2.4): the latest day's ACTUAL factor moves →
    full-reprice total P&L, attributed via greeks into market-data effects
    (delta/gamma/vega/rho) + time effect (theta); the unexplained remainder is
    the residual (higher-order + FX + cross terms)."""
    shifts = factor_shifts(ctx, window=30)
    dS, dr = float(shifts["eq"][-1]), float(shifts["dr"][-1])
    dvol, dfx = float(shifts["dvol"][-1]), float(shifts["fx"][-1])
    as_of = shifts["dates"][-1]

    ps = ctx.portfolio
    actual = ps.full_reprice_pnl(dS=dS, dr=dr, dvol=dvol, dfx=dfx)
    result = ps.explain_pnl(total_pnl=actual["pnl"], dS=dS, dVol=dvol, dr=dr,
                            theta_days=theta_days)

    labels = {"delta_pnl": "Delta (equity)", "gamma_pnl": "Gamma",
              "vega_pnl": "Vega (vol)", "theta_pnl": "Theta (time)",
              "rate_pnl": "Rates", "rho_pnl": "Rates (rho)",
              "fx_pnl": "FX", "spread_pnl": "Credit spread"}
    comp = dict(result.components or {})
    effects = [{"key": k, "label": labels.get(k, k.replace("_pnl", "").capitalize()),
                "value": float(v)} for k, v in comp.items()]
    return {
        "as_of": as_of,
        "moves": {"equity": dS, "rates_bp": dr * 10000, "vol_pts": dvol * 100,
                  "fx": dfx},
        "total_pnl": float(actual["pnl"]),
        "explained": float(sum(comp.values())),
        "residual": float(result.residual),
        "effects": effects,
        "by_factor": [{"factor": k, "pnl": float(v)}
                      for k, v in (result.factor_pnl or {}).items()],
        "by_position": [{"position": k, "pnl": float(v)}
                        for k, v in (result.position_pnl or {}).items()],
        "note": ("Market-data effect по грикам, time effect = theta; residual — "
                 "нелинейность/кросс-эффекты/FX (FX-атрибуция по грикам пока не "
                 "разложена)."),
        "warnings": list(result.warnings or []),
    }


_PCA_TENORS = (0.25, 1.0, 2.0, 5.0, 10.0)          # КБД series in the backfill


def pca_rates(ctx, confidence: float = 0.99, window: int = 500,
              n_components: int = 3) -> dict:
    """PCA of the КБД curve (level/slope/curvature) + PCA-VaR of the book's
    rate exposure mapped onto the tenor pillars — Calypso's bucketed rate risk
    against our single-factor (5Y parallel) HypPL treatment."""
    from risk.historical_var import pca_var

    db = ctx.market_db
    series = {t: dict(_series(db, f"KBD:{t:g}Y")) for t in _PCA_TENORS}
    dates = sorted(set.intersection(*(set(s) for s in series.values())))
    if len(dates) < 60:
        raise ValueError("not enough КБД tenor history for PCA")
    dates = dates[-(window + 1):]
    changes = np.array([[series[t][d1] - series[t][d0] for t in _PCA_TENORS]
                        for d0, d1 in zip(dates, dates[1:])]) * 10000  # bp units

    # DV01 vector: bond key-rate exposures land on their pillar, everything
    # else (IRS/swaption DV01) on the nearest pillar to its maturity.
    ps = ctx.portfolio
    ps.value()
    dv01 = np.zeros(len(_PCA_TENORS))
    for pos in ps.positions:
        exposures = getattr(pos, "exposures", []) or []
        krd, headline = [], []
        for exp in exposures:
            unit = str(getattr(exp, "unit", "")).lower()
            if "dv01" not in unit:
                continue
            factor = str(getattr(exp, "factor_name", ""))
            amount = float(getattr(exp, "sensitivity", 0.0) or 0.0)
            if factor.startswith("kr_"):
                try:
                    krd.append((float(factor[3:].rstrip("y")), amount))
                except ValueError:
                    continue
            elif "key rate" not in unit:
                headline.append(amount)
        if krd:                                     # bucketed beats the headline
            rows = krd
        else:
            t_pos = float(pos.params.get("T", 5.0)) if pos.params else 5.0
            rows = [(t_pos, a) for a in headline]
        for tenor, amount in rows:
            idx = int(np.argmin([abs(tenor - t) for t in _PCA_TENORS]))
            dv01[idx] += amount

    res = pca_var(changes, dv01, confidence, n_components)
    names = ["Level", "Slope", "Curvature"][:n_components]
    loadings = [
        {"component": names[i] if i < len(names) else f"PC{i+1}",
         "variance_share": float(res["eigenvalues"][i] / res["eigenvalues"].sum()
                                 * res["pct_variance_explained"]),
         "dv01": float(res["factor_dv01"][i]),
         "vol_annual_bp": float(res["factor_vol_annual"][i]),
         "weights": [{"tenor": t, "w": float(res["eigenvectors"][j, i])}
                     for j, t in enumerate(_PCA_TENORS)]}
        for i in range(n_components)
    ]
    # parallel-only comparison: total DV01 x quantile of the 5Y change
    par_losses = -changes[:, _PCA_TENORS.index(5.0)] * dv01.sum()
    var_parallel = float(np.quantile(np.abs(par_losses), confidence))
    return {
        "confidence": confidence, "window": len(changes),
        "tenors": list(_PCA_TENORS),
        "dv01_vector": [{"tenor": t, "dv01": float(v)}
                        for t, v in zip(_PCA_TENORS, dv01)],
        "pca_var": float(res["VaR"]),
        "parallel_var": var_parallel,
        "variance_explained": float(res["pct_variance_explained"]),
        "components": loadings,
        "note": ("PCA по дневным изменениям КБД (bp); Level/Slope/Curvature. "
                 "DV01 бондов — по key-rate корзинам, свопов — на ближайший "
                 "пиллар. HypPL пока использует один 5Y-фактор — PCA-VaR "
                 "показывает вклад формы кривой."),
    }


def backtest(ctx, confidence: float = 0.99, window: int = 500,
             lookback: int = 250) -> dict:
    """Backtesting analysis: rolling historical VaR vs next-day HypPL —
    exceptions, Kupiec POF, Christoffersen independence, Basel traffic light."""
    from risk.var import christoffersen_test, kupiec_test

    hp = hyppl(ctx, window)
    pnl = hp["pnl"]
    if len(pnl) <= lookback + 20:
        lookback = max(60, len(pnl) // 2)

    rows, exceptions = [], []
    for t in range(lookback, len(pnl)):
        var_t = float(np.quantile(-pnl[t - lookback:t], confidence))
        breach = bool(pnl[t] < -var_t)
        exceptions.append(breach)
        rows.append({"date": hp["dates"][t], "pnl": float(pnl[t]),
                     "var": -var_t, "breach": breach})

    n_obs, n_exc = len(exceptions), int(sum(exceptions))
    expected = n_obs * (1 - confidence)
    kupiec = kupiec_test(n_obs, n_exc, confidence)
    christ = christoffersen_test(exceptions) if n_exc > 0 else {}

    # Basel traffic light, generalized: the 99%/250d thresholds (5/10 breaches)
    # are exactly 2x/4x the expected count — apply that ratio at any confidence.
    ratio = (n_exc / expected) if expected > 0 else 0.0
    zone = "green" if ratio < 2.0 else ("amber" if ratio < 4.0 else "red")

    return {
        "confidence": confidence, "lookback": lookback,
        "n_obs": n_obs, "n_exceptions": n_exc,
        "expected_exceptions": expected,
        "exception_rate": (n_exc / n_obs) if n_obs else 0.0,
        "kupiec": kupiec, "christoffersen": christ,
        "traffic_light": zone,
        "rows": rows,
    }
