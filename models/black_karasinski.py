"""
Black-Karasinski — lognormal short-rate model, Master-plan M3c.

    d ln r = (θ(t) - a ln r) dt + σ dW,   r(t) = exp(x(t))

The log-rate x is a mean-reverting Gaussian (OU) process, so it lives on the
same clamped trinomial lattice as Hull-White; the short rate r = exp(x) is then
*always positive* — Black-Karasinski's defining feature over the Gaussian
short-rate models (HW/G2++ admit negative rates).

Because r is lognormal, the time-dependent shift α_i cannot be solved in closed
form from the Arrow-Debreu prices (as it can for HW); it is found by a 1-D root
search at each step so the tree reprices the initial discount curve exactly
(Hull, *Options, Futures and Other Derivatives*, BK tree-building).

Provides exact curve fit, a European swaption by backward induction on the
lattice (rolling back the fixed-coupon bond), and is validated by: curve
reprice, strict positivity of all node rates, payer/receiver parity (σ-free,
guaranteed by curve repricing), and the σ→0 collapse to the discounted forward
swap intrinsic.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq


class BlackKarasinski:
    def __init__(self, a: float, sigma: float, curve, T: float,
                 steps_per_year: int = 24):
        self.a, self.sigma, self.curve = float(a), float(sigma), curve
        self.T = float(T)
        self.steps = max(1, int(round(self.T * steps_per_year)))
        self.dt = self.T / self.steps
        self.dx = sigma * np.sqrt(3 * self.dt)
        self.j_max = max(1, int(np.ceil(0.184 / (self.a * self.dt))))
        self._build()

    # branching identical to the HW trinomial lattice (depends only on a)
    def _branch_probs(self, j: int):
        eta = self.a * j * self.dt
        if abs(j) < self.j_max:
            return (1, 0, -1), (1/6 + (eta*eta - eta)/2,
                                2/3 - eta*eta,
                                1/6 + (eta*eta + eta)/2)
        if j >= self.j_max:
            return (0, -1, -2), (7/6 + (eta*eta - 3*eta)/2,
                                 -1/3 + 2*eta - eta*eta,
                                 1/6 + (eta*eta - eta)/2)
        return (0, 1, 2), (7/6 + (eta*eta + 3*eta)/2,
                           -1/3 - 2*eta - eta*eta,
                           1/6 + (eta*eta + eta)/2)

    def _build(self):
        """Fit α_i (log-shift) so the tree reprices P(0,t_{i+1}) — transcendental,
        solved per step by Brent. Node short rate r_ij = exp(α_i + j·dx)."""
        n, jm = self.steps + 1, self.j_max
        width = 2 * jm + 1
        self.alphas = np.zeros(n)
        Q = np.zeros(width)
        Q[jm] = 1.0
        self.Q = [Q.copy()]
        js = np.arange(-jm, jm + 1)
        for i in range(n):
            P_next = self.curve.discount((i + 1) * self.dt)
            mask = Q > 0

            def f(alpha):
                r = np.exp(alpha + js[mask] * self.dx)
                return float(np.sum(Q[mask] * np.exp(-r * self.dt))) - P_next

            # bracket: α small enough -> df≈ΣQ > P_next; α large -> 0 < P_next
            lo, hi = -20.0, 5.0
            while f(hi) > 0 and hi < 50:
                hi += 5.0
            self.alphas[i] = brentq(f, lo, hi, xtol=1e-12, rtol=1e-14)
            Q_next = np.zeros(width)
            for idx in np.where(mask)[0]:
                j = idx - jm
                d = np.exp(-np.exp(self.alphas[i] + j * self.dx) * self.dt)
                moves, probs = self._branch_probs(j)
                for m, p in zip(moves, probs):
                    Q_next[idx + m] += Q[idx] * p * d
            Q = Q_next
            self.Q.append(Q.copy())

    def short_rate(self, i: int, j: int) -> float:
        return float(np.exp(self.alphas[i] + j * self.dx))

    def discount_to_zero(self, i: int) -> float:
        """Roll back a unit payoff at step i to the root — must equal P(0,t_i)."""
        jm = self.j_max
        V = np.ones(2 * jm + 1)
        for k in range(i - 1, -1, -1):
            V_new = np.zeros_like(V)
            for j in range(-jm, jm + 1):
                moves, probs = self._branch_probs(j)
                cont = sum(p * V[j + jm + m] for m, p in zip(moves, probs))
                V_new[j + jm] = cont * np.exp(-self.short_rate(k, j) * self.dt)
            V = V_new
        return float(V[jm])

    def swaption(self, notional: float, K: float, T_opt: float, T_swap: float,
                 freq: int = 2, opt: str = "payer") -> dict:
        """European swaption by backward induction: roll the fixed-coupon bond
        back to T_opt, take the swaption payoff, then discount to 0."""
        jm = self.j_max
        dt_pay = 1.0 / freq
        opt_step = int(round(T_opt / self.dt))
        n_pay = int(round(T_swap * freq))
        pay_steps = {opt_step + int(round(p * dt_pay / self.dt)): p
                     for p in range(1, n_pay + 1)}
        end_step = max(pay_steps)
        coupon = K * dt_pay

        # fixed-coupon bond value rolled back from T_end to T_opt
        V = np.zeros(2 * jm + 1)                       # value just after T_end
        for i in range(end_step, opt_step - 1, -1):
            V_new = np.zeros_like(V)
            for j in range(-jm, jm + 1):
                if i == end_step:
                    cont = 0.0
                else:
                    moves, probs = self._branch_probs(j)
                    cont = sum(p * V[j + jm + m] for m, p in zip(moves, probs))
                    cont *= np.exp(-self.short_rate(i, j) * self.dt)
                cf = (1.0 if i == end_step else 0.0) + (coupon if i in pay_steps else 0.0)
                V_new[j + jm] = cont + cf
            V = V_new
        # V now = fixed-coupon bond price at T_opt (incl. redemption + future coupons)
        sign = 1.0 if opt == "receiver" else -1.0     # receiver = fixed bond - 1
        payoff = np.maximum(sign * (V - 1.0), 0.0) * notional
        # discount payoff from T_opt to 0
        W = payoff
        for i in range(opt_step - 1, -1, -1):
            W_new = np.zeros_like(W)
            for j in range(-jm, jm + 1):
                moves, probs = self._branch_probs(j)
                cont = sum(p * W[j + jm + m] for m, p in zip(moves, probs))
                W_new[j + jm] = cont * np.exp(-self.short_rate(i, j) * self.dt)
            W = W_new
        return dict(price=float(W[jm]), opt=opt, steps=self.steps, j_max=jm)


def bk_swaption(curve, notional, K, T_opt, T_swap, freq=2, a=0.1, sigma=0.20,
                opt="payer", steps_per_year=24) -> dict:
    """Convenience: build a Black-Karasinski tree and price a European swaption."""
    end = T_opt + T_swap
    tree = BlackKarasinski(a, sigma, curve, end, steps_per_year)
    res = tree.swaption(notional, K, T_opt, T_swap, freq, opt)
    res.update(a=a, sigma=sigma)
    return res
