"""
G2++ — two-factor Gaussian short-rate model (Brigo-Mercurio §4.2), Master-plan M3a.

    r(t) = x(t) + y(t) + φ(t)
    dx = -a x dt + σ dW1,   dy = -b y dt + η dW2,   dW1·dW2 = ρ dt

φ(t) is fitted to the initial discount curve, so every model bond reprices the
curve by construction. Two factors give a richer, decorrelated term-structure
than one-factor Hull-White — the workhorse for Bermudan/CMS-style rate exotics.

Provides: analytic P(t,T), exact curve fit, a closed-form zero-coupon bond
option (Gaussian), and a Monte-Carlo European swaption. Validated by: curve
reprice, the η→0 collapse to one-factor Hull-White, bond-option put-call parity,
and swaption MC vs the one-factor analytic price.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm


class G2pp:
    def __init__(self, curve, a=0.1, sigma=0.01, b=0.3, eta=0.012, rho=-0.7):
        self.curve = curve
        self.a, self.sigma = a, sigma
        self.b, self.eta = b, eta
        self.rho = rho

    # ── helpers ──────────────────────────────────────────
    @staticmethod
    def _B(z, t, T):
        return (1.0 - np.exp(-z * (T - t))) / z

    def _V(self, t, T):
        """Variance term V(t,T) of ∫ r du (Brigo-Mercurio 4.10)."""
        a, b, s, e, rho = self.a, self.b, self.sigma, self.eta, self.rho
        tau = T - t
        Va = (s**2 / a**2) * (tau + (2 / a) * np.exp(-a * tau)
                              - (1 / (2 * a)) * np.exp(-2 * a * tau) - 3 / (2 * a))
        Vb = (e**2 / b**2) * (tau + (2 / b) * np.exp(-b * tau)
                              - (1 / (2 * b)) * np.exp(-2 * b * tau) - 3 / (2 * b))
        Vab = (2 * rho * s * e / (a * b)) * (
            tau + (np.exp(-a * tau) - 1) / a + (np.exp(-b * tau) - 1) / b
            - (np.exp(-(a + b) * tau) - 1) / (a + b))
        return Va + Vb + Vab

    def bond_price(self, t, T, x=0.0, y=0.0):
        """P(t,T) given factors (x,y) at t, reconstituted from the initial curve."""
        pm_T = self.curve.discount(T)
        pm_t = self.curve.discount(t) if t > 1e-12 else 1.0
        A = (pm_T / pm_t) * np.exp(
            0.5 * (self._V(t, T) - self._V(0, T) + self._V(0, t))
            - self._B(self.a, t, T) * x - self._B(self.b, t, T) * y)
        return A

    def zero_rate(self, T):
        P = self.bond_price(0.0, T, 0.0, 0.0)
        return -np.log(P) / T if T > 0 else self.curve.rate(1e-4)

    # ── ZCB option (closed form, Brigo-Mercurio 4.31) ────
    def zcb_option(self, T_opt, T_bond, K, opt="call"):
        """European option on P(T_opt, T_bond), strike K (closed form)."""
        a, b, s, e, rho = self.a, self.b, self.sigma, self.eta, self.rho
        Ba = self._B(a, T_opt, T_bond)
        Bb = self._B(b, T_opt, T_bond)
        # Σ²: variance of ln P(T_opt,T_bond) under the T_opt-forward measure
        Sigma2 = (s**2 / (2 * a**3)) * (1 - np.exp(-a * (T_bond - T_opt)))**2 * (1 - np.exp(-2 * a * T_opt)) \
            + (e**2 / (2 * b**3)) * (1 - np.exp(-b * (T_bond - T_opt)))**2 * (1 - np.exp(-2 * b * T_opt)) \
            + (2 * rho * s * e / (a * b * (a + b))) * (1 - np.exp(-a * (T_bond - T_opt))) \
            * (1 - np.exp(-b * (T_bond - T_opt))) * (1 - np.exp(-(a + b) * T_opt))
        Sigma = np.sqrt(max(Sigma2, 1e-300))
        P_T = self.curve.discount(T_opt)
        P_S = self.curve.discount(T_bond)
        h = np.log(P_S / (K * P_T)) / Sigma + 0.5 * Sigma
        if opt == "call":
            return P_S * norm.cdf(h) - K * P_T * norm.cdf(h - Sigma)
        return K * P_T * norm.cdf(-h + Sigma) - P_S * norm.cdf(-h)

    # ── simulation ───────────────────────────────────────
    def simulate_factors(self, T, n_sims, seed=42):
        """
        EXACT terminal sampling of (x_T, y_T) from x_0=y_0=0 — the OU pair is
        jointly Gaussian, so no time-stepping (and no Euler bias) is needed for a
        European payoff at T.
        """
        rng = np.random.default_rng(seed)
        a, b, s, e, rho = self.a, self.b, self.sigma, self.eta, self.rho
        var_x = s**2 * (1 - np.exp(-2 * a * T)) / (2 * a)
        var_y = e**2 * (1 - np.exp(-2 * b * T)) / (2 * b)
        cov_xy = rho * s * e * (1 - np.exp(-(a + b) * T)) / (a + b)
        cov = np.array([[var_x, cov_xy], [cov_xy, var_y]])
        L = np.linalg.cholesky(cov)
        Z = rng.standard_normal((n_sims, 2)) @ L.T
        return Z[:, 0], Z[:, 1]

    def swaption(self, notional, K, T_opt, T_swap, freq=2, opt="payer",
                 n_sims=50_000, steps=None, seed=42):
        """
        European swaption via MC with exact terminal sampling: draw (x,y) at
        T_opt, value the swap there with the analytic G2++ bond reconstitution,
        discount under the T_opt-forward measure.
        """
        x, y = self.simulate_factors(T_opt, n_sims, seed)
        dt = 1.0 / freq
        pay_times = [T_opt + i * dt for i in range(1, int(round(T_swap * freq)) + 1)]
        # numeraire: deterministic P(0,T_opt) discount of the T_opt payoff (T_opt-forward)
        annuity = np.zeros(n_sims)
        for s in pay_times:
            annuity += dt * self.bond_price(T_opt, s, x, y)
        P_end = self.bond_price(T_opt, pay_times[-1], x, y)
        float_pv = 1.0 - P_end
        swap = float_pv - K * annuity
        sign = 1.0 if opt == "payer" else -1.0
        payoff = np.maximum(sign * swap, 0.0)
        price = notional * self.curve.discount(T_opt) * payoff.mean()
        stderr = notional * self.curve.discount(T_opt) * payoff.std() / np.sqrt(n_sims)
        return dict(price=price, stderr=stderr, opt=opt, n_sims=n_sims)


def g2pp_swaption(curve, notional, K, T_opt, T_swap, freq=2,
                  a=0.1, sigma=0.01, b=0.3, eta=0.012, rho=-0.7,
                  opt="payer", n_sims=20_000, steps=50) -> dict:
    """Convenience: build G2++ and price a European swaption (MC)."""
    model = G2pp(curve, a, sigma, b, eta, rho)
    res = model.swaption(notional, K, T_opt, T_swap, freq, opt, n_sims, steps)
    res.update(a=a, sigma=sigma, b=b, eta=eta, rho=rho)
    return res
