"""
Structured notes on a basket of *real* underlyings (equities, bonds, indices).

A single, configurable wrapper that covers the four product axes a structuring
desk cares about:

  * underlying mix      — equities / bonds / indices / a blend of all three
  * principal           — protected (capital guarantee) or capital-at-risk
  * coupon              — guaranteed (fixed) or none (pure participation)
  * upside              — participated, capped or uncapped, on the basket return

Redemption (fraction of notional returned at maturity, ex-coupons):

    perf     = basket return ratio  S_T / S_0   (weighted average / worst-of / best-of)
    capital  = protected + (1 - protected) * min(perf, 1)     # downside on the at-risk sleeve
    upside   = participation * max(perf - 1, 0)               # capped at `cap` if set
    R        = capital + upside

Special cases this reproduces:
  * protected = 1.0                       → classic principal-protected note (PPN)
  * protected = 0.0, participation = 1.0  → delta-one basket certificate (full tracking)
  * 0 < protected < 1                     → partial capital-at-risk note (floored at `protected`)
  * guaranteed_coupon > 0                 → fixed coupons paid regardless of performance

The guaranteed coupon leg is risk-free (paid in all states); the redemption leg is
valued by correlated Monte-Carlo on the constituents. The engine is pure numerics —
resolving real SECIDs to spot / vol / income / correlation lives in the market-data
service (``basket_market_inputs``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from models.monte_carlo import multi_asset_paths


@dataclass
class Constituent:
    """One real instrument in the basket."""
    name: str                 # SECID or label, e.g. "SBER", "SU26238RMFS4", "IMOEX"
    kind: str                 # "equity" | "bond" | "index"
    spot: float               # current price / level
    weight: float = 1.0       # basket weight (renormalised internally)
    vol: float = 0.30         # annualised volatility
    income: float = 0.0       # dividend yield (equity) or carry/coupon yield (bond)


def nearest_correlation(corr: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Clamp a symmetric matrix to the nearest positive-definite correlation matrix.

    Eigenvalue floor + unit-diagonal renormalisation so ``np.linalg.cholesky`` never
    fails on an empirically estimated (possibly indefinite) correlation matrix.
    """
    c = np.asarray(corr, dtype=float)
    c = 0.5 * (c + c.T)
    vals, vecs = np.linalg.eigh(c)
    vals = np.clip(vals, eps, None)
    c = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.clip(np.diag(c), eps, None))
    c = c / np.outer(d, d)
    np.fill_diagonal(c, 1.0)
    return c


def _basket_perf(rel_T: np.ndarray, weights: np.ndarray, basket_type: str) -> np.ndarray:
    """Per-path basket return ratio from per-asset S_T/S_0 (shape n_sims × n_assets)."""
    if basket_type == "worst_of":
        return rel_T.min(axis=1)
    if basket_type == "best_of":
        return rel_T.max(axis=1)
    return (rel_T * weights).sum(axis=1)          # weighted average (default)


def basket_note(
    constituents: list[Constituent],
    r: float,
    T: float,
    corr: np.ndarray | None = None,
    *,
    principal_protection: float = 1.0,   # protected fraction of notional in [0, 1]
    guaranteed_coupon: float = 0.0,      # annual guaranteed coupon rate (0 = none)
    coupon_freq: int = 1,
    participation: float = 1.0,          # upside participation on basket return
    cap: float | None = None,            # max upside return (on perf - 1); None = uncapped
    basket_type: str = "average",        # "average" | "worst_of" | "best_of"
    face: float = 1000.0,
    n_sims: int = 50_000,
    steps: int = 52,
    seed: int = 42,
) -> dict:
    """Fair value of a structured note on a basket of real underlyings.

    Returns a dict with the headline ``price`` plus the structuring decomposition
    (bond floor, guaranteed-coupon PV, option budget, fair participation at par) and
    the risk profile (capital-loss probability, expected return, std error).
    """
    if not constituents:
        raise ValueError("Basket must contain at least one instrument.")
    if not 0.0 <= principal_protection <= 1.0:
        raise ValueError("principal_protection must be in [0, 1].")

    S0  = np.array([c.spot   for c in constituents], dtype=float)
    sig = np.array([c.vol    for c in constituents], dtype=float)
    inc = np.array([c.income for c in constituents], dtype=float)
    w   = np.array([c.weight for c in constituents], dtype=float)
    if w.sum() <= 0:
        w = np.ones_like(w)
    w = w / w.sum()
    n = len(constituents)

    if corr is None:
        corr = np.full((n, n), 0.5)
        np.fill_diagonal(corr, 1.0)
    corr = nearest_correlation(corr)

    # Correlated GBM; `income` enters as the dividend/carry yield q.
    paths = multi_asset_paths(S0, r, inc, sig, corr, T, steps, n_sims, seed)
    rel_T = paths[:, :, -1] / S0                       # S_T / S_0 per asset
    perf  = _basket_perf(rel_T, w, basket_type)

    protected = principal_protection
    capital   = protected + (1.0 - protected) * np.minimum(perf, 1.0)
    upside_raw = np.maximum(perf - 1.0, 0.0)

    # Guaranteed coupon leg (risk-free, paid in every state).
    coupon_pv_ratio = 0.0
    coupon_dates: list[float] = []
    if guaranteed_coupon > 0 and coupon_freq > 0:
        periods = max(int(round(T * coupon_freq)), 1)
        coupon_dates = [(i + 1) / coupon_freq for i in range(periods)]
        coupon_pv_ratio = sum(
            (guaranteed_coupon / coupon_freq) * np.exp(-r * t) for t in coupon_dates
        )

    disc = np.exp(-r * T)

    def _redemption(part: float) -> np.ndarray:
        up = part * upside_raw
        if cap is not None:
            up = np.minimum(up, cap)
        return capital + up

    def _price_ratio(part: float) -> float:
        return disc * _redemption(part).mean() + coupon_pv_ratio

    redemption = _redemption(participation)
    price_ratio = disc * redemption.mean() + coupon_pv_ratio
    price = face * price_ratio
    stderr = face * disc * redemption.std() / np.sqrt(n_sims)

    # Structuring decomposition (per notional).
    bond_floor       = face * protected * disc
    guaranteed_cpn_pv = face * coupon_pv_ratio
    option_budget    = face - bond_floor - guaranteed_cpn_pv

    # Participation that prices the note exactly at par (self-financing structure).
    fair_participation = _fair_participation(_price_ratio)

    capital_loss_prob = float((redemption < 1.0).mean())
    expected_return   = float(redemption.mean() - 1.0) + coupon_pv_ratio / max(disc, 1e-12)

    return dict(
        price=price,
        price_ratio=price_ratio,
        stderr=stderr,
        bond_floor=bond_floor,
        guaranteed_coupon_pv=guaranteed_cpn_pv,
        option_budget=option_budget,
        fair_participation=fair_participation,
        participation=participation,
        capital_loss_prob=capital_loss_prob,
        expected_return=expected_return,
        expected_perf=float(perf.mean()),
        prob_above_initial=float((perf >= 1.0).mean()),
        basket_type=basket_type,
        protected=protected,
        n_assets=n,
        n_sims=n_sims,
    )


def _fair_participation(price_ratio_fn, lo: float = 0.0, hi: float = 100.0) -> float | None:
    """Participation that sets the note value to par, or None if unreachable.

    ``price_ratio_fn`` is monotone increasing in participation, so a simple bracket +
    Brent solve is robust. If the structure prices above par even at zero upside
    (over-protected / coupon too rich) the fair participation is 0.0.
    """
    if price_ratio_fn(lo) >= 1.0:
        return 0.0
    if price_ratio_fn(hi) < 1.0:
        return None
    from scipy.optimize import brentq
    try:
        return float(brentq(lambda p: price_ratio_fn(p) - 1.0, lo, hi, xtol=1e-6))
    except ValueError:
        return None
