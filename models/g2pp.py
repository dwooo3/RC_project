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
from scipy.optimize import brentq


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

    # ── analytic swaption (Brigo-Mercurio 4.31) ─────────
    def swaption_analytic(self, notional, K, T_opt, T_swap, freq=2,
                          opt="payer", n_x=128) -> float:
        """Closed-form European swaption: one numerical integral over the first
        factor with the exercise boundary ȳ(x) (Brigo-Mercurio 2006, eq. 4.31).
        The payer integrand is N·P(0,T)·E^T[(1-CB)^+]; receiver via parity."""
        a, b, s, e, rho = self.a, self.b, self.sigma, self.eta, self.rho
        T = T_opt
        dt = 1.0 / freq
        t_i = np.array([T + i * dt for i in range(1, int(round(T_swap * freq)) + 1)])
        tau = np.diff(np.concatenate([[T], t_i]))
        c = K * tau
        c[-1] += 1.0                                       # coupon bond cashflows
        A = np.array([self.bond_price(T, ti, 0.0, 0.0) for ti in t_i])
        Ba = (1.0 - np.exp(-a * (t_i - T))) / a
        Bb = (1.0 - np.exp(-b * (t_i - T))) / b

        sx = s * np.sqrt((1 - np.exp(-2 * a * T)) / (2 * a))
        sy = e * np.sqrt((1 - np.exp(-2 * b * T)) / (2 * b))
        Mx = ((s**2 / a**2 + rho * s * e / (a * b)) * (1 - np.exp(-a * T))
              - s**2 / (2 * a**2) * (1 - np.exp(-2 * a * T))
              - rho * s * e / (b * (a + b)) * (1 - np.exp(-(a + b) * T)))
        My = ((e**2 / b**2 + rho * s * e / (a * b)) * (1 - np.exp(-b * T))
              - e**2 / (2 * b**2) * (1 - np.exp(-2 * b * T))
              - rho * s * e / (a * (a + b)) * (1 - np.exp(-(a + b) * T)))
        mux, muy = -Mx, -My
        rho_xy = rho * s * e / ((a + b) * sx * sy) * (1 - np.exp(-(a + b) * T))
        g = np.sqrt(max(1 - rho_xy**2, 1e-300))

        def ybar(x):
            f = lambda y: float(np.sum(c * A * np.exp(-Ba * x - Bb * y))) - 1.0
            lo, hi = -1.0, 1.0
            while f(lo) < 0 and lo > -50:
                lo -= 1.0
            while f(hi) > 0 and hi < 50:
                hi += 1.0
            return brentq(f, lo, hi, xtol=1e-12)

        xs = np.linspace(mux - 8 * sx, mux + 8 * sx, n_x)
        integ = np.empty(n_x)
        for k, x in enumerate(xs):
            yb = ybar(x)
            h1 = (yb - muy) / (sy * g) - rho_xy * (x - mux) / (sx * g)
            h2 = h1 + Bb * sy * g
            lam = c * A * np.exp(-Ba * x)
            kap = -Bb * (muy - 0.5 * (1 - rho_xy**2) * sy**2 * Bb
                         + rho_xy * sy * (x - mux) / sx)
            integ[k] = (norm.pdf((x - mux) / sx) / sx
                        * (norm.cdf(-h1) - np.sum(lam * np.exp(kap) * norm.cdf(-h2))))
        payer = notional * self.curve.discount(T) * np.trapezoid(integ, xs)
        if opt == "payer":
            return float(payer)
        annuity0 = float(np.sum(tau * np.array([self.curve.discount(ti) for ti in t_i])))
        S0 = (self.curve.discount(T) - self.curve.discount(t_i[-1])) / annuity0
        return float(payer - notional * annuity0 * (S0 - K))    # parity -> receiver

    # ── simulation ───────────────────────────────────────
    def _fwd_means(self, T):
        """Means of (x_T, y_T) under the T-forward measure (Brigo-Mercurio 4.30)."""
        a, b, s, e, rho = self.a, self.b, self.sigma, self.eta, self.rho
        Mx = ((s**2 / a**2 + rho * s * e / (a * b)) * (1 - np.exp(-a * T))
              - s**2 / (2 * a**2) * (1 - np.exp(-2 * a * T))
              - rho * s * e / (b * (a + b)) * (1 - np.exp(-(a + b) * T)))
        My = ((e**2 / b**2 + rho * s * e / (a * b)) * (1 - np.exp(-b * T))
              - e**2 / (2 * b**2) * (1 - np.exp(-2 * b * T))
              - rho * s * e / (a * (a + b)) * (1 - np.exp(-(a + b) * T)))
        return -Mx, -My

    def simulate_factors(self, T, n_sims, seed=42, fwd_measure=False):
        """
        EXACT terminal sampling of (x_T, y_T) — the OU pair is jointly Gaussian,
        so no time-stepping (and no Euler bias) is needed for a European payoff.
        fwd_measure=True shifts the means to the T-forward measure, required when
        discounting the T-payoff with the deterministic numeraire P(0,T).
        """
        rng = np.random.default_rng(seed)
        a, b, s, e, rho = self.a, self.b, self.sigma, self.eta, self.rho
        var_x = s**2 * (1 - np.exp(-2 * a * T)) / (2 * a)
        var_y = e**2 * (1 - np.exp(-2 * b * T)) / (2 * b)
        cov_xy = rho * s * e * (1 - np.exp(-(a + b) * T)) / (a + b)
        cov = np.array([[var_x, cov_xy], [cov_xy, var_y]])
        L = np.linalg.cholesky(cov)
        Z = rng.standard_normal((n_sims, 2)) @ L.T
        if fwd_measure:
            mux, muy = self._fwd_means(T)
            return Z[:, 0] + mux, Z[:, 1] + muy
        return Z[:, 0], Z[:, 1]

    def swaption(self, notional, K, T_opt, T_swap, freq=2, opt="payer",
                 n_sims=50_000, steps=None, seed=42):
        """
        European swaption via MC with exact terminal sampling: draw (x,y) at
        T_opt under the T_opt-forward measure, value the swap there with the
        analytic G2++ bond reconstitution, discount with P(0,T_opt).
        """
        x, y = self.simulate_factors(T_opt, n_sims, seed, fwd_measure=True)
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
                  opt="payer", n_sims=20_000, steps=50, method="analytic") -> dict:
    """Convenience: build G2++ and price a European swaption.

    method="analytic" (default) uses the closed-form Brigo-Mercurio integral;
    "mc" uses exact terminal forward-measure sampling.
    """
    model = G2pp(curve, a, sigma, b, eta, rho)
    if method == "mc":
        res = model.swaption(notional, K, T_opt, T_swap, freq, opt, n_sims, steps)
    else:
        res = {"price": model.swaption_analytic(notional, K, T_opt, T_swap, freq, opt)}
    res.update(a=a, sigma=sigma, b=b, eta=eta, rho=rho, method=method)
    return res
