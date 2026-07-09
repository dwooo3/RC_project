"""Desk Risk: MultiSensitivity — кросс-ассет чувствительности одной книгой
(Calypso §2.2). Два слоя, которые обязаны сходиться:

  * greek-слой: агрегированные чувствительности позиций (delta/vega/DV01/…)
    из портфельной оценки;
  * full-reprice слой: параллельные бампы факторов ±(equity 1%, rates 1bp,
    vol 1pt, fx 1%) с ПОЛНОЙ переоценкой книги — нелинейность видна как
    асимметрия up/down.
"""

from __future__ import annotations

_GREEK_COLS = ["delta", "gamma", "vega", "theta", "rho", "dv01", "cs01", "fx_delta"]

# factor -> (label, bump kwargs, bump description)
_BUMPS = [
    ("equity", "Equity ±1%", {"dS": 0.01}, "спот-фактор, относительный"),
    ("rates", "Rates ±1bp", {"dr": 0.0001}, "параллельный сдвиг ставок"),
    ("vol", "Vol ±1pt", {"dvol": 0.01}, "абсолютный сдвиг волатильности"),
    ("fx", "FX ±1%", {"dfx": 0.01}, "относительный сдвиг курса"),
]


def multisensitivity(ctx) -> dict:
    ps = ctx.portfolio
    valuation = ps.value()

    rows, totals = [], {c: 0.0 for c in _GREEK_COLS}
    for pos in ps.positions:
        row = {"id": pos.id, "instrument": pos.instrument,
               "description": pos.description, "quantity": float(pos.quantity or 0),
               "market_value": float(pos.market_value or 0)}
        for col in _GREEK_COLS:
            v = float(getattr(pos, col, 0.0) or 0.0)
            row[col] = v
            totals[col] += v
        rows.append(row)

    # bucket totals from the valuation's exposure aggregation
    buckets: dict[str, dict[str, float]] = {}
    for pos in ps.positions:
        for exp in getattr(pos, "exposures", []) or []:
            b = str(getattr(exp, "bucket", "Unclassified"))
            u = str(getattr(exp, "unit", ""))
            buckets.setdefault(b, {}).setdefault(u, 0.0)
            buckets[b][u] += float(getattr(exp, "sensitivity", 0.0) or 0.0)

    # full-reprice bumps, up and down — asymmetry = convexity/nonlinearity
    bumps = []
    for key, label, kw, note in _BUMPS:
        up = ps.full_reprice_pnl(**kw)
        down = ps.full_reprice_pnl(**{k: -v for k, v in kw.items()})
        pnl_up, pnl_down = float(up["pnl"]), float(down["pnl"])
        bumps.append({
            "factor": key, "label": label, "note": note,
            "pnl_up": pnl_up, "pnl_down": pnl_down,
            "linear": (pnl_up - pnl_down) / 2.0,          # odd part ≈ delta-term
            "convexity": (pnl_up + pnl_down) / 2.0,       # even part ≈ gamma-term
            "errors": sorted(set(up["errors"]) | set(down["errors"])),
        })

    return {
        "positions": rows,
        "totals": totals,
        "buckets": buckets,
        "bumps": bumps,
        "market_value": float(valuation.total_market_value),
        "n_positions": len(rows),
        "note": ("Greek-слой — агрегация чувствительностей позиций (единицы "
                 "смешанные: delta в штуках, DV01 в деньгах/bp). Bump-слой — "
                 "полная переоценка книги; асимметрия up/down = нелинейность."),
        "warnings": list(valuation.warnings or []),
    }
