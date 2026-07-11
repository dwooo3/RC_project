"""Market Risk workstation (Calypso ERS-style) for the bridge.

Two-step process, faithful to the doc: (1) shifts generation — joint daily
factor changes from REAL stored history (IMOEX equity returns, КБД 5Y absolute
rate changes, RVI vol-point changes); (2) risk metric computation — the demo
book is FULL-REPRICED through its actual pricers on every historical scenario
(PortfolioService.full_reprice_pnl), giving a Hypothetical P&L distribution
from which VaR / ES / EVT metrics and the backtest are computed.

The FX factor runs on 5y of CBR daily fixings (USDRUB:fix, backfilled
2026-07-09); fixings are forward-filled onto trading dates, so gaps produce a
carried level rather than a fake zero move. The vol factor auto-switches from
the RVI proxy to own ATM-IV history (IV:MIX/MXI/RTS) once >=60 points
accumulate.
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


_KBD_TENORS = (0.25, 1.0, 2.0, 5.0, 10.0)


def _book_secids(ctx) -> list[str]:
    """Equity-like secids held in the book — candidates for per-name factors."""
    out = []
    try:
        for pos in ctx.portfolio.positions:
            secid = (pos.params or {}).get("secid")
            if secid and not pos.instrument.startswith(("fx", "ndf", "xccy")):
                out.append(str(secid))
    except Exception:
        pass
    return sorted(set(out))


def _book_fx_pairs(ctx) -> list[str]:
    out = []
    try:
        for pos in ctx.portfolio.positions:
            if pos.instrument.startswith(("fx", "ndf", "xccy")):
                pair = (pos.params or {}).get("ccy_pair") or pos.ccy_pair
                if pair:
                    out.append(str(pair))
    except Exception:
        pass
    return sorted(set(out))


def _ffill_levels(series: dict, dates: list[str]) -> dict:
    """Forward-fill a sparse level series onto the trading-date grid."""
    out, last = {}, None
    for d in dates:
        if series.get(d, 0) > 0:
            last = series[d]
        if last is not None:
            out[d] = last
    return out


def factor_shifts(ctx, window: int = 500, frm: str | None = None,
                  till: str | None = None) -> dict:
    """Step 1 — shifts generation: aligned joint daily factor changes.
    ``frm``/``till`` clip to a fixed period (stress window) — then ``window``
    is ignored."""
    db = ctx.market_db
    eq = dict(_series(db, "IMOEX:price"))
    kbd = dict(_series(db, "KBD:5Y"))
    kbd_tenors = {t: dict(_series(db, f"KBD:{t:g}Y")) for t in _KBD_TENORS}
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

    # A7 (validation report): forward-fill fixings onto the trading-date grid —
    # a fixing gap carries the level, and the change lands on the first date it
    # reappears (close-to-close over holidays), instead of fabricating a chain
    # of zero moves that damped FX vol (was 284/500 non-zero days).
    fx_level = _ffill_levels(usd, dates)

    # M3: per-name equity series for book holdings (fallback: IMOEX move);
    # per-pair FX for book currencies beyond USD/RUB.
    name_levels = {}
    for secid in _book_secids(ctx):
        s = dict(_series(db, f"{secid}:price"))
        if len(s) >= 60:
            name_levels[secid] = s
    pair_levels = {}
    for pair in _book_fx_pairs(ctx):
        s = dict(_series(db, f"{pair.replace('/', '')}:fix"))
        if len(s) >= 60:
            pair_levels[pair] = _ffill_levels(s, dates)

    out_dates, eq_ret, dr, dvol, fx_ret = [], [], [], [], []
    dr_tenors: dict[float, list] = {t: [] for t in _KBD_TENORS}
    eq_names: dict[str, list] = {s: [] for s in name_levels}
    fx_pairs: dict[str, list] = {p: [] for p in pair_levels}
    for prev, cur in zip(dates, dates[1:]):
        if eq[prev] <= 0 or eq[cur] <= 0:
            continue
        out_dates.append(cur)
        eq_move = math.log(eq[cur] / eq[prev])
        eq_ret.append(eq_move)
        dr.append(kbd[cur] - kbd[prev])                 # КБД already decimal
        for t in _KBD_TENORS:
            s = kbd_tenors[t]
            dr_tenors[t].append(s[cur] - s[prev]
                                if (prev in s and cur in s)
                                else kbd[cur] - kbd[prev])   # fallback 5Y
        dvol.append((rvi[cur] - rvi[prev]) * vol_scale)  # points/100 или own IV
        if has_fx and fx_level.get(prev) and fx_level.get(cur):
            fx_ret.append(math.log(fx_level[cur] / fx_level[prev]))
        else:
            fx_ret.append(0.0)
        for secid, s in name_levels.items():
            eq_names[secid].append(math.log(s[cur] / s[prev])
                                   if (s.get(prev, 0) > 0 and s.get(cur, 0) > 0)
                                   else eq_move)          # fallback: индекс
        for pair, s in pair_levels.items():
            fx_pairs[pair].append(math.log(s[cur] / s[prev])
                                  if (s.get(prev) and s.get(cur))
                                  else fx_ret[-1])
    if window and len(out_dates) > window:
        sl = slice(-window, None)
        out_dates, eq_ret, dr, dvol, fx_ret = (
            out_dates[sl], eq_ret[sl], dr[sl], dvol[sl], fx_ret[sl])
        dr_tenors = {t: v[sl] for t, v in dr_tenors.items()}
        eq_names = {s: v[sl] for s, v in eq_names.items()}
        fx_pairs = {p: v[sl] for p, v in fx_pairs.items()}
    factors = ["IMOEX (equity, log-return)"
               + (f" + per-name: {', '.join(eq_names)}" if eq_names else ""),
               f"КБД {len(_KBD_TENORS)} теноров (rates, bucketed by maturity)",
               vol_label,
               ("USD/RUB fix (fx, log-return)"
                + (f" + {', '.join(p for p in fx_pairs if p != 'USD/RUB')}"
                   if any(p != "USD/RUB" for p in fx_pairs) else ""))
               if has_fx else "FX (no history — zero)"]
    return {
        "dates": out_dates,
        "eq": np.array(eq_ret), "dr": np.array(dr), "dvol": np.array(dvol),
        "fx": np.array(fx_ret),
        "dr_tenors": {t: np.array(v) for t, v in dr_tenors.items()},
        "eq_names": {s: np.array(v) for s, v in eq_names.items()},
        "fx_pairs": {p: np.array(v) for p, v in fx_pairs.items()},
        "factors": factors,
        "has_fx": has_fx,
    }


def _reprice_series(ps, shifts: dict) -> tuple[np.ndarray, set[str]]:
    pnl = np.empty(len(shifts["dates"]))
    errors: set[str] = set()
    dr_tenors = shifts.get("dr_tenors") or {}
    eq_names = shifts.get("eq_names") or {}
    fx_pairs = shifts.get("fx_pairs") or {}
    for i in range(len(pnl)):
        res = ps.full_reprice_pnl(
            dS=float(shifts["eq"][i]), dr=float(shifts["dr"][i]),
            dvol=float(shifts["dvol"][i]), dfx=float(shifts["fx"][i]),
            dr_curve=[(t, float(v[i])) for t, v in dr_tenors.items()] or None,
            dS_by_name={s: float(v[i]) for s, v in eq_names.items()} or None,
            dfx_by_pair={p: float(v[i]) for p, v in fx_pairs.items()} or None)
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
             horizon: int = 1, stress: str | None = None,
             book: str | None = None) -> dict:
    """VaR analysis report: HypPL distribution + metrics by method + drill-down.
    ``stress`` selects a named fixed historical period (Stress VaR);
    ``book`` (A4) считает VaR по срезу книги (без кэша)."""
    from risk.var import evt_var, montecarlo_var, parametric_var

    frm, till = STRESS_WINDOWS.get(stress or "", (None, None))
    book_ps = ctx.filtered_portfolio(book=book) if book else None
    hp = hyppl(ctx, window, frm, till, portfolio=book_ps)
    # M1 (validation report): многодневный горизонт — перекрывающиеся h-дневные
    # суммы HypPL (Basel-style), sqrt-time только как помеченный fallback.
    from risk.historical_var import overlapping_horizon_pnl
    pnl, horizon_method = overlapping_horizon_pnl(hp["pnl"], max(int(horizon), 1))
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

    val = (book_ps or ctx.portfolio).value()
    quality = []
    if any("no history" in f for f in hp["factors"]):
        quality.append("FX-фактор без истории — валютный риск в HypPL не учтён")
    if hp["reprice_errors"]:
        quality.append(f"{len(hp['reprice_errors'])} позиций не переоценились")
    if horizon_method == "sqrt_time":
        quality.append("горизонт масштабирован sqrt(h) — истории мало для "
                       "перекрывающихся окон (параметрическое приближение)")

    return {
        "confidence": confidence, "window": window, "horizon": horizon,
        "horizon_method": horizon_method,
        "book": book or "",
        "stress": stress or "",
        "stress_period": f"{frm} … {till}" if frm else "",
        "n_scenarios": len(pnl),
        "portfolio_value": float(val.total_market_value),
        "positions": len((book_ps or ctx.portfolio).positions),
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


def mc_var_matrix(ctx, confidence: float = 0.99, window: int = 500,
                  n_sims: int = 1000, seed: int = 42) -> dict:
    """M4 (Calypso Matrix Transform): correlated Monte Carlo VaR.

    Ковариация фактор-вектора [equity, КБД×5 теноров, vol, fx] оценивается по
    истории, Cholesky превращает независимые нормали в согласованные joint-
    сценарии, книга ПОЛНОСТЬЮ переоценивается на каждом — в отличие от
    var_mc (fitted normal на готовом P&L), здесь корреляции факторов и
    нелинейность позиций входят в хвост честно.
    """
    shifts = factor_shifts(ctx, window)
    cols = [shifts["eq"]]
    col_names = ["equity"]
    for t in _KBD_TENORS:
        cols.append(shifts["dr_tenors"][t])
        col_names.append(f"rates_{t:g}y")
    cols.append(shifts["dvol"]); col_names.append("vol")
    cols.append(shifts["fx"]); col_names.append("fx")
    X = np.column_stack(cols)
    mu, cov = X.mean(axis=0), np.cov(X.T)

    # Cholesky c джиттером — историческая ковариация бывает полуопределённой
    jitter = 0.0
    for _ in range(6):
        try:
            L = np.linalg.cholesky(cov + jitter * np.eye(cov.shape[0]))
            break
        except np.linalg.LinAlgError:
            jitter = max(jitter * 10, 1e-12)
    else:
        raise ValueError("factor covariance is not positive definite")

    rng = np.random.default_rng(seed)
    sims = mu + rng.standard_normal((int(n_sims), len(cols))) @ L.T

    ps = ctx.portfolio
    pnl = np.empty(len(sims))
    errors: set[str] = set()
    ti = {t: 1 + k for k, t in enumerate(_KBD_TENORS)}
    for i, row in enumerate(sims):
        res = ps.full_reprice_pnl(
            dS=float(row[0]), dr=float(row[ti[5.0]]),
            dvol=float(row[-2]), dfx=float(row[-1]),
            dr_curve=[(t, float(row[ti[t]])) for t in _KBD_TENORS])
        pnl[i] = res["pnl"]
        errors.update(res["errors"])
    var, es = _var_es(-pnl, confidence)

    corr = cov / np.sqrt(np.outer(np.diag(cov), np.diag(cov)))
    return {
        "confidence": confidence, "window": window, "n_sims": int(n_sims),
        "var": var, "es": es,
        "pnl_mean": float(pnl.mean()), "pnl_std": float(pnl.std()),
        "histogram": _histogram(pnl),
        "factors": col_names,
        "corr_eq_rates5y": float(corr[0, ti[5.0]]),
        "corr_eq_fx": float(corr[0, -1]),
        "jitter": jitter,
        "reprice_errors": sorted(errors),
        "method": "matrix_transform_full_reprice",
        "note": ("Гауссовы совместные факторы (Cholesky от исторической "
                 "ковариации) + полная переоценка; жирные хвосты факторов "
                 "не моделируются — сравнивайте с historical на том же окне."),
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
    christ = christoffersen_test(np.array(exceptions, dtype=int))  # self-guarding (D1)

    # M6-lite: у Kupiec-отклонения есть НАПРАВЛЕНИЕ — слишком мало пробоев
    # значит модель консервативна (капитал завышен), слишком много — агрессивна
    # (риск недооценён). Без знака reject читается как «модель занижает риск».
    if n_exc < expected:
        bias = "conservative"
    elif n_exc > expected:
        bias = "aggressive"
    else:
        bias = "in_line"

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
        "bias": bias,
        "rows": rows,
    }
