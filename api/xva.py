"""XVA workstation for the bridge (Calypso §2.5, pricing/risk layer).

Netting set = the IRS positions of the CURRENT book (fallback: a representative
demo set when the book carries no swaps). Counterparty credit comes either
from an issuer's z-spread-implied hazard curve (api/credit — рейтинг +
baseline recovery) or from a flat spread input. Discounting on the live
GCURVE; the MtM cube is a shared Hull-White simulation (risk/xva.py), CSA
variation margin optional.
"""

from __future__ import annotations

from curves.hazard import hazard_curve_from_corp_spreads

DEMO_TRADES = [
    {"notional": 50_000_000.0, "fixed_rate": 0.13, "T": 5.0, "freq": 4,
     "pay_fixed": True, "source": "demo"},
    {"notional": 30_000_000.0, "fixed_rate": 0.125, "T": 3.0, "freq": 4,
     "pay_fixed": False, "source": "demo"},
]


def _book_trades(ctx) -> list[dict]:
    """IRS positions of the persistent book -> netting-set trade specs."""
    trades = []
    for pos in ctx.portfolio.positions:
        if pos.instrument not in ("irs", "swap"):
            continue
        p = pos.params or {}
        trades.append({
            "notional": float(p.get("notional", 1e6)) * float(pos.quantity or 1.0),
            "fixed_rate": float(p.get("fixed_rate", 0.10)),
            "T": float(p.get("T", 5.0)),
            "freq": int(p.get("freq", 4)),
            "pay_fixed": bool(p.get("pay_fixed", True)),
            "source": pos.id,
        })
    return trades


def _cpty_hazard(ctx, issuer: str | None, spread_bps: float, recovery: float):
    """(HazardCurve, meta-note). Issuer beats the flat spread."""
    issuer = (issuer or "").strip()
    if issuer:
        from api.credit import issuer_hazard_curve
        curve, meta = issuer_hazard_curve(ctx, issuer)
        rating = meta.get("rating") or {}
        note = (f"{meta['issuer']} · {rating.get('rating', 'без рейтинга')} · "
                f"R={meta['recovery']:.0%} ({meta['recovery_source']}) · "
                f"hazard из z-спредов {len(meta['bonds'])} бумаг")
        return curve, note
    sp = max(spread_bps, 1.0) / 10000.0
    curve = hazard_curve_from_corp_spreads([1.0, 5.0, 10.0], [sp, sp, sp],
                                           recovery, label="flat cpty spread")
    return curve, f"флэт-спред контрагента {spread_bps:.0f}bp · R={recovery:.0%}"


def run(ctx, risk_service, *,
        cpty_issuer: str | None = None,
        cpty_spread_bps: float = 200.0,
        own_spread_bps: float = 0.0,
        recovery: float = 0.40,
        funding_spread_bps: float = 100.0,
        cost_of_capital: float = 0.10,
        csa_enabled: bool = False,
        threshold: float = 0.0,
        mta: float = 0.0,
        mpor_weeks: float = 2.0,
        n_sims: int = 4000,
        use_book: bool = True) -> dict:
    """Full XVA on the netting set; returns metrics + exposure profiles."""
    trades = _book_trades(ctx) if use_book else []
    used_book = bool(trades)
    if not trades:
        trades = [dict(t) for t in DEMO_TRADES]

    cpty, cpty_note = _cpty_hazard(ctx, cpty_issuer, cpty_spread_bps, recovery)
    own = None
    own_note = ""
    if own_spread_bps > 0:
        own, own_note = _cpty_hazard(ctx, None, own_spread_bps, recovery)

    curves = getattr(ctx.snapshot, "curves", {}) or {}
    curve_id = "GCURVE_RUB" if "GCURVE_RUB" in curves else "ofz_demo"
    csa = ({"threshold": threshold, "mta": mta, "mpor": mpor_weeks / 52.0}
           if csa_enabled else None)

    result = risk_service.xva_netting_set(
        trades, curve_id=curve_id, funding_spread=funding_spread_bps / 10000.0,
        cost_of_capital=cost_of_capital, csa=csa, n_sims=int(n_sims),
        snapshot=ctx.snapshot, cpty_hazard=cpty, own_hazard=own)

    raw = result.get("raw") or {}
    profile = raw.get("profile") or {}
    metrics = [
        {"key": k, "label": lbl, "value": float(raw.get(k, 0.0) or 0.0)}
        for k, lbl in (("cva", "CVA"), ("dva", "DVA"), ("bcva", "BCVA"),
                       ("fva", "FVA"), ("mva", "MVA"), ("kva", "KVA"),
                       ("total_xva", "Total XVA"))
    ]
    return {
        "value": result.get("value"),
        "errors": list(result.get("errors") or []),
        "warnings": list(result.get("warnings") or []),
        "model_status": str(getattr(result.get("model_status"), "value",
                                    result.get("model_status")) or ""),
        "metrics": metrics,
        "peak_epe": float(raw.get("peak_epe", 0.0) or 0.0),
        "peak_im": float(raw.get("peak_im", 0.0) or 0.0),
        "collateralised": bool(raw.get("collateralised", False)),
        "profile": profile,
        "trades": trades,
        "netting_source": "book" if used_book else "demo",
        "curve_id": curve_id,
        "cpty_note": cpty_note,
        "own_note": own_note,
        "n_sims": int(n_sims),
    }
