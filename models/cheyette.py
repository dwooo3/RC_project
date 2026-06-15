"""
Cheyette — one-factor quasi-Gaussian (Markovian HJM) model, Master-plan M3c.

A separable-volatility HJM has a finite-dimensional Markov representation in two
state variables: x (the short-rate deviation) and y (its accumulated variance):

    r(t) = f(0,t) + x(t)
    dx = (y - a x) dt + σ_r(t,x) dW
    dy = (σ_r(t,x)² - 2 a y) dt
    P(t,T) = P(0,T)/P(0,t) · exp(-x·G(t,T) - ½ y·G(t,T)²),  G = (1-e^{-a(T-t)})/a

With a *constant* local vol σ_r ≡ σ this is exactly one-factor Hull-White — the
identity we validate against. The value of Cheyette is the state-dependent
σ_r(t,x): a linear (displaced) local vol σ_r = σ(1 + skew·x) produces an
implied-vol *skew* in swaptions that the Gaussian HW/G2++ cannot, while keeping
a fully Markovian, curve-fitting model (the desk workhorse for skew in rate
exotics). Bonds reconstruct off the initial curve, so every model bond reprices
it by construction.

Pricing is Monte-Carlo under the risk-neutral measure (the money-market account
is rebuilt from ∫x dt since ∫f(0,s)ds = -ln P(0,t)). Validated by: bond
reconstruction at t=0, the constant-vol collapse to Hull-White (swaption MC vs
Jamshidian), payer/receiver parity, and a monotone skew in the swaption smile.
"""

from __future__ import annotations

import numpy as np


class Cheyette:
    def __init__(self, curve, a=0.1, sigma=0.01, skew=0.0):
        self.curve = curve
        self.a, self.sigma, self.skew = float(a), float(sigma), float(skew)

    def _G(self, t, T):
        return (1.0 - np.exp(-self.a * (T - t))) / self.a

    def bond(self, t, T, x, y):
        """Reconstructed P(t,T) from the curve and the state (x,y)."""
        G = self._G(t, T)
        return (self.curve.discount(T) / self.curve.discount(t)
                * np.exp(-x * G - 0.5 * y * G * G))

    def _local_vol(self, x):
        v = self.sigma * (1.0 + self.skew * x)
        return np.maximum(v, 0.05 * self.sigma)            # keep vol positive

    def simulate(self, T, n_sims=50_000, steps=100, seed=12345):
        """Evolve (x, y) and ∫x dt to T under the risk-neutral measure."""
        rng = np.random.default_rng(seed)
        dt = T / steps
        sq = np.sqrt(dt)
        x = np.zeros(n_sims)
        y = np.zeros(n_sims)
        intx = np.zeros(n_sims)
        for _ in range(steps):
            sig = self._local_vol(x)
            x_prev = x
            dW = rng.standard_normal(n_sims) * sq
            x = x + (y - self.a * x) * dt + sig * dW
            y = y + (sig * sig - 2.0 * self.a * y) * dt
            intx += 0.5 * (x_prev + x) * dt                # trapezoidal ∫x dt
        return x, y, intx

    def swaption(self, notional, K, T_opt, T_swap, freq=2, opt="payer",
                 n_sims=50_000, steps=100, seed=12345):
        x, y, intx = self.simulate(T_opt, n_sims, steps, seed)
        dt_pay = 1.0 / freq
        pay_times = [T_opt + i * dt_pay for i in range(1, int(round(T_swap * freq)) + 1)]
        annuity = np.zeros(n_sims)
        for s in pay_times:
            annuity += dt_pay * self.bond(T_opt, s, x, y)
        float_leg = 1.0 - self.bond(T_opt, pay_times[-1], x, y)
        swap = float_leg - K * annuity                     # payer swap value
        if opt == "receiver":
            swap = -swap
        payoff = np.maximum(swap, 0.0)
        disc = self.curve.discount(T_opt) * np.exp(-intx)  # rebuilt MMA
        pv = notional * disc * payoff
        return dict(price=float(pv.mean()),
                    stderr=float(pv.std(ddof=1) / np.sqrt(n_sims)))


def cheyette_swaption(curve, notional, K, T_opt, T_swap, freq=2, a=0.1,
                      sigma=0.01, skew=0.0, opt="payer", n_sims=50_000,
                      steps=100) -> dict:
    """Convenience: build a Cheyette model and price a European swaption (MC)."""
    res = Cheyette(curve, a, sigma, skew).swaption(
        notional, K, T_opt, T_swap, freq, opt, n_sims, steps)
    res.update(a=a, sigma=sigma, skew=skew)
    return res
