"""
LMM / BGM — the LIBOR (forward) Market Model, Master-plan M3b.

Models each forward LIBOR L_k(t) for accrual [T_k, T_{k+1}] as a lognormal
process. Under its own T_{k+1}-forward measure L_k is a driftless martingale,
so a flat per-rate vol reprices Black caplets *exactly* — that is the model's
defining identity and our primary test.

Simulation is under the **terminal T_N-forward measure** (numeraire P(·,T_N)),
where every rate but the last carries a state-dependent drift

    dL_k/L_k = -σ_k Σ_{j=k+1}^{N-1} ρ_{kj} τ_j σ_j L_j / (1 + τ_j L_j) dt + σ_k dW_k

(Brigo-Mercurio §6.3). A log-Euler **predictor-corrector** removes most of the
drift discretisation bias. Pricing a caplet under this measure (non-zero drift,
numeraire reconstructed from the simulated curve) and recovering the analytic
Black price validates the whole change-of-measure machinery.

Swaptions are priced by Monte Carlo and cross-checked against the Rebonato
swaption-vol approximation. The market-model view (one vol/correlation per
forward) is what lets a single calibrated model fit the entire cap and swaption
surface — the foundation of desk-standard rate exotics pricing.
"""

from __future__ import annotations

import numpy as np

from models.black_scholes import black76


def _nearest_pd_corr(c: np.ndarray, floor: float = 1e-8) -> np.ndarray:
    """Repair a correlation matrix to be positive-definite (eigenvalue floor +
    unit-diagonal renormalisation). A no-op for the default exp(-β|ΔT|) form;
    needed only for degenerate user inputs such as all-ones (rank-1)."""
    c = 0.5 * (c + c.T)
    try:
        np.linalg.cholesky(c)
        return c
    except np.linalg.LinAlgError:
        w, V = np.linalg.eigh(c)
        c = (V * np.clip(w, floor, None)) @ V.T
        d = np.sqrt(np.diag(c))
        return c / np.outer(d, d)


class LMM:
    def __init__(self, curve, start=0.0, end=5.0, freq=2, vol=0.20,
                 corr_beta=0.1, vols=None, corr=None):
        self.curve = curve
        n = int(round((end - start) * freq))
        if n < 1:
            raise ValueError("LMM needs at least one accrual period")
        self.T = start + np.arange(n + 1) / freq          # T_0 .. T_N
        self.reset = self.T[:-1]                            # fixing times
        self.pay = self.T[1:]
        self.tau = np.diff(self.T)
        self.N = n
        dfs = np.array([curve.discount(t) for t in self.T])
        self.P0 = dfs
        self.L0 = (dfs[:-1] / dfs[1:] - 1.0) / self.tau     # initial forwards
        self.sigma = (np.full(n, vol) if vols is None
                      else np.asarray(vols, float))
        if self.sigma.shape != (n,):
            raise ValueError("vols must have one entry per forward rate")
        if corr is None:
            d = np.abs(self.reset[:, None] - self.reset[None, :])
            corr = np.exp(-corr_beta * d)
        self.corr = _nearest_pd_corr(np.asarray(corr, float))
        self._chol = np.linalg.cholesky(self.corr)

    # ── analytic caplets (the defining identity) ─────────────

    def caplet_black(self, k: int, K: float, opt: str = "call",
                     notional: float = 1.0) -> float:
        """Exact Black caplet on L_k: P(0,T_{k+1}) τ_k Black76(L_k0, K, T_k)."""
        g = black76(self.L0[k], K, self.reset[k], 0.0, self.sigma[k],
                    "call" if opt in ("call", "cap", "payer") else "put")
        return notional * self.P0[k + 1] * self.tau[k] * g.price

    def cap_black(self, K: float, opt: str = "cap", start: int = 1,
                  notional: float = 1.0) -> float:
        """Cap/floor = strip of caplets/floorlets from index `start`."""
        return sum(self.caplet_black(k, K, opt, notional)
                   for k in range(start, self.N))

    # ── terminal-measure simulation ──────────────────────────

    def _simulate(self, upto: int, n_sims: int, steps: int, seed: int):
        """Evolve all forwards to T_upto under the T_N measure. Returns the
        forward matrix (n_sims, N) at that time (frozen rates hold their fix)."""
        T_target = self.reset[upto]
        n_steps = max(steps, 1)
        dt = T_target / n_steps
        sq = np.sqrt(dt)
        rng = np.random.default_rng(seed)
        sig = self.sigma
        tau = self.tau
        # upper-triangular correlation weights: M[k,j] = rho_kj for j>k
        M = np.triu(self.corr, k=1)
        L = np.broadcast_to(self.L0, (n_sims, self.N)).astype(float).copy()

        def pct_drift(Lcur, live):
            # w_j = tau_j sigma_j L_j / (1+tau_j L_j), only for live rates
            w = (tau * sig * live) * Lcur / (1.0 + tau * Lcur)
            return -sig * (w @ M.T)                        # (n_sims, N)

        t = 0.0
        for _ in range(n_steps):
            live = (self.reset > t + 1e-12).astype(float)  # vol still alive
            if not live.any():
                break
            dW = (rng.standard_normal((n_sims, self.N)) @ self._chol.T) * sq
            d0 = pct_drift(L, live)
            inc_det = (-0.5 * sig**2) * dt + sig * dW       # Ito + diffusion
            lnL = np.log(L)
            L_pred = np.exp(lnL + (d0 * dt + inc_det) * live)
            d1 = pct_drift(L_pred, live)
            L = np.exp(lnL + (0.5 * (d0 + d1) * dt + inc_det) * live)
            t += dt
        return L

    def caplet_mc(self, k: int, K: float, opt: str = "call", n_sims: int = 50_000,
                  steps: int = 24, seed: int = 12345, notional: float = 1.0):
        """Caplet under the T_N measure — recovers caplet_black if drift is
        handled. Discounts via the numeraire P(T_k,T_N) rebuilt from sim rates."""
        L = self._simulate(k, n_sims, steps, seed)
        Lk = L[:, k]
        value = self.tau[k] * np.maximum(
            (Lk - K) if opt in ("call", "cap", "payer") else (K - Lk), 0.0
        ) / (1.0 + self.tau[k] * Lk)                        # value at T_k
        # 1/P(T_k,T_N) = Π_{j=k}^{N-1} (1+τ_j L_j)
        growth = np.prod(1.0 + self.tau[k:] * L[:, k:], axis=1)
        disc = notional * self.P0[-1] * value * growth
        price = disc.mean()
        return dict(price=float(price), stderr=float(disc.std(ddof=1) / np.sqrt(n_sims)))

    # ── swaptions ────────────────────────────────────────────

    def _swap(self, a: int, b: int):
        """Forward swap rate and annuity for swap [T_a, T_b] off the curve."""
        ann = float(np.sum(self.tau[a:b] * self.P0[a + 1:b + 1]))
        S0 = (self.P0[a] - self.P0[b]) / ann
        return S0, ann

    def rebonato_swaption_vol(self, a: int, b: int) -> float:
        """Rebonato approximation of the Black swaption vol for [T_a,T_b]."""
        S0, ann = self._swap(a, b)
        w = self.tau[a:b] * self.P0[a + 1:b + 1] / ann      # swap weights
        L = self.L0[a:b]
        sig = self.sigma[a:b]
        rho = self.corr[a:b, a:b]
        coef = (w * L) @ (rho * np.outer(sig, sig)) @ (w * L)
        return float(np.sqrt(coef) / S0)                    # √(·/T_a)·√T_a cancels

    def swaption_black(self, notional: float, K: float, a: int, b: int,
                       opt: str = "payer") -> float:
        S0, ann = self._swap(a, b)
        vol = self.rebonato_swaption_vol(a, b)
        g = black76(S0, K, self.reset[a], 0.0, vol,
                    "call" if opt == "payer" else "put")
        return notional * ann * g.price

    def swaption(self, notional: float, K: float, a: int, b: int,
                 opt: str = "payer", n_sims: int = 50_000, steps: int = 24,
                 seed: int = 12345):
        """Monte-Carlo European swaption under the T_N measure."""
        L = self._simulate(a, n_sims, steps, seed)
        # discounts P(T_a, T_m) from the simulated alive forwards
        one_plus = 1.0 + self.tau[a:] * L[:, a:]            # (n_sims, N-a)
        cum = np.cumprod(one_plus, axis=1)                  # Π up to each tenor
        P_a = np.empty((L.shape[0], self.N - a + 1))
        P_a[:, 0] = 1.0
        P_a[:, 1:] = 1.0 / cum                              # P(T_a, T_{a+1..N})
        # annuity & swap rate over [a, b]
        ann = np.sum(self.tau[a:b] * P_a[:, 1:b - a + 1], axis=1)
        S = (1.0 - P_a[:, b - a]) / ann
        payoff = ann * np.maximum((S - K) if opt == "payer" else (K - S), 0.0)
        numeraire = P_a[:, self.N - a]                      # P(T_a, T_N)
        disc = notional * self.P0[-1] * payoff / numeraire
        price = disc.mean()
        return dict(price=float(price), stderr=float(disc.std(ddof=1) / np.sqrt(n_sims)),
                    forward=float(self._swap(a, b)[0]))


# ── module-level convenience (service layer) ─────────────────

def lmm_caplet(curve, K, start, end, freq=2, vol=0.20, opt="call",
               notional=1.0):
    m = LMM(curve, start=0.0, end=end, freq=freq, vol=vol)
    k = int(round(start * freq))
    return m.caplet_black(k, K, opt, notional)


def lmm_swaption(curve, notional, K, T_opt, T_swap, freq=2, vol=0.20,
                 corr_beta=0.1, opt="payer", n_sims=50_000, steps=24):
    m = LMM(curve, start=0.0, end=T_opt + T_swap, freq=freq, vol=vol,
            corr_beta=corr_beta)
    a = int(round(T_opt * freq))
    b = int(round((T_opt + T_swap) * freq))
    return m.swaption(notional, K, a, b, opt, n_sims=n_sims, steps=steps)
