"""
Path-dependent structured exotics, gap-closing batch 4.

* **TARN** (target accrual redemption note) — accrues a per-period coupon and
  redeems early once cumulative coupons reach a target.
* **Accumulator** — buys a fixed quantity each period at a discount strike (double
  below strike), with an up-and-out knock-out barrier.

Both are GBM Monte-Carlo. Validated by their structural monotonicities: a TARN's
value rises with the target (more coupons collected before redemption) and
collapses to one coupon at target→0; an accumulator's value rises as the
knock-out barrier moves away (less early termination).
"""

from __future__ import annotations

import numpy as np


def _gbm_paths(S0, r, q, sigma, times, n_sims, seed):
    rng = np.random.default_rng(seed)
    n = len(times)
    S = np.empty((n_sims, n))
    prev = np.full(n_sims, float(S0)); tprev = 0.0
    for i, t in enumerate(times):
        dt = t - tprev
        z = rng.standard_normal(n_sims)
        prev = prev * np.exp((r - q - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z)
        S[:, i] = prev; tprev = t
    return S


def tarn(S0, K, T, freq, r, sigma, target, q=0.0, n_sims=100_000, seed=0) -> dict:
    """TARN paying coupon max(K-S_i,0) each fixing; redeems when cumulative ≥ target."""
    times = [(i + 1) / freq for i in range(int(round(T * freq)))]
    S = _gbm_paths(S0, r, q, sigma, times, n_sims, seed)
    cum = np.zeros(n_sims); pv = np.zeros(n_sims); alive = np.ones(n_sims, bool)
    for i, t in enumerate(times):
        cpn = np.maximum(K - S[:, i], 0.0) / freq
        pay = np.where(alive, np.minimum(cpn, np.maximum(target - cum, 0.0)), 0.0)
        pv += pay * np.exp(-r * t)
        cum += pay
        alive &= cum < target - 1e-12
    return dict(price=float(pv.mean()), stderr=float(pv.std() / np.sqrt(n_sims)),
                target=target)


def accumulator(S0, K, barrier, T, freq, r, sigma, q=0.0, qty=1.0,
                n_sims=100_000, seed=0) -> dict:
    """Up-and-out accumulator: each fixing buy qty (2·qty if S<K) at strike K,
    realise (S-K)·qty; knock out if S ≥ barrier."""
    times = [(i + 1) / freq for i in range(int(round(T * freq)))]
    S = _gbm_paths(S0, r, q, sigma, times, n_sims, seed)
    pv = np.zeros(n_sims); alive = np.ones(n_sims, bool)
    for i, t in enumerate(times):
        ko = S[:, i] >= barrier
        live = alive & ~ko
        q_i = np.where(S[:, i] < K, 2 * qty, qty)
        pv += np.where(live, q_i * (S[:, i] - K) * np.exp(-r * t), 0.0)
        alive &= ~ko
    return dict(price=float(pv.mean()), stderr=float(pv.std() / np.sqrt(n_sims)),
                barrier=barrier)
