"""
Two-factor commodity term-structure models, Master-plan M5.

Two equivalent parametrisations of the same dynamics:

* **Schwartz-Smith (2000)** — log spot = χ + ξ, a mean-reverting short-term
  deviation χ plus an arithmetic-Brownian equilibrium level ξ:
      dχ = (-κχ - λ_χ) dt + σ_χ dW_χ
      dξ =  μ_ξ* dt + σ_ξ dW_ξ,   dW_χ·dW_ξ = ρ dt
  Futures are log-normal: ln F(t,T) = e^{-κτ}χ_t + ξ_t + A(τ).

* **Gibson-Schwartz (1990)** — spot S with a stochastic convenience yield δ:
      dS/S = (r - δ) dt + σ_S dW_S
      dδ   = κ(α̃ - δ) dt + σ_δ dW_δ,   dW_S·dW_δ = ρ dt
  Futures: F(t,T) = S exp(C(τ) - δ B(τ)),  B(τ)=(1-e^{-κτ})/κ.

Schwartz & Smith proved the two are the *same* model under a linear change of
factors — the flagship identity here: `GibsonSchwartz.to_schwartz_smith()`
reproduces the GS futures curve and option prices exactly. Both are further
checked against Monte-Carlo (F(0,T) = E^Q[S_T]).

Used for oil/gas/metals: the mean-reverting factor gives Samuelson vol decay
(near futures more volatile than far) and a curve that can be in contango or
backwardation depending on the convenience yield.
"""

from __future__ import annotations

import numpy as np

from models.black_scholes import black76


def _black_total_var(F, K, V, df, opt):
    """Black option with total log-variance V (not annualised) and discount df."""
    sigma = np.sqrt(max(V, 1e-300))
    g = black76(F, K, 1.0, 0.0, sigma, "call" if opt in ("call", "c") else "put")
    return df * g.price


class SchwartzSmith:
    def __init__(self, chi0=0.0, xi0=None, kappa=1.0, sigma_chi=0.3,
                 mu_xi=0.0, sigma_xi=0.15, rho=0.3, lambda_chi=0.0, r=0.05,
                 spot=None):
        if xi0 is None:
            xi0 = np.log(spot) - chi0 if spot is not None else np.log(50.0)
        self.chi0, self.xi0 = float(chi0), float(xi0)
        self.kappa, self.sigma_chi = float(kappa), float(sigma_chi)
        self.mu_xi, self.sigma_xi = float(mu_xi), float(sigma_xi)
        self.rho, self.lambda_chi, self.r = float(rho), float(lambda_chi), float(r)

    @property
    def spot(self):
        return np.exp(self.chi0 + self.xi0)

    def _A(self, tau):
        k, sc, sx, rho = self.kappa, self.sigma_chi, self.sigma_xi, self.rho
        return (self.mu_xi * tau - (1 - np.exp(-k * tau)) * self.lambda_chi / k
                + 0.5 * ((1 - np.exp(-2 * k * tau)) * sc**2 / (2 * k)
                         + sx**2 * tau
                         + 2 * (1 - np.exp(-k * tau)) * rho * sc * sx / k))

    def futures(self, T):
        tau = float(T)
        return float(np.exp(np.exp(-self.kappa * tau) * self.chi0 + self.xi0
                            + self._A(tau)))

    def futures_log_var(self, T_opt, T_fut):
        """Var_0[ln F(T_opt, T_fut)] — drives options on the T_fut future."""
        k, sc, sx, rho = self.kappa, self.sigma_chi, self.sigma_xi, self.rho
        lag = np.exp(-k * (T_fut - T_opt))
        var_chi = (1 - np.exp(-2 * k * T_opt)) * sc**2 / (2 * k)
        var_xi = sx**2 * T_opt
        cov = (1 - np.exp(-k * T_opt)) * rho * sc * sx / k
        return lag**2 * var_chi + var_xi + 2 * lag * cov

    def futures_option(self, T_opt, T_fut, K, opt="call"):
        F = self.futures(T_fut)
        V = self.futures_log_var(T_opt, T_fut)
        return _black_total_var(F, K, V, np.exp(-self.r * T_opt), opt)

    def simulate_spot(self, T, n_sims=100_000, seed=42):
        """Exact terminal (χ_T, ξ_T) sampling -> S_T = exp(χ_T+ξ_T)."""
        k, sc, sx, rho = self.kappa, self.sigma_chi, self.sigma_xi, self.rho
        rng = np.random.default_rng(seed)
        m_chi = np.exp(-k * T) * self.chi0 - (1 - np.exp(-k * T)) * self.lambda_chi / k
        m_xi = self.xi0 + self.mu_xi * T
        v_chi = (1 - np.exp(-2 * k * T)) * sc**2 / (2 * k)
        v_xi = sx**2 * T
        cov = (1 - np.exp(-k * T)) * rho * sc * sx / k
        L = np.linalg.cholesky(np.array([[v_chi, cov], [cov, v_xi]]))
        Z = rng.standard_normal((n_sims, 2)) @ L.T
        return np.exp((m_chi + Z[:, 0]) + (m_xi + Z[:, 1]))


class GibsonSchwartz:
    def __init__(self, spot=50.0, delta0=0.05, kappa=1.0, sigma_S=0.3,
                 alpha_tilde=0.05, sigma_delta=0.3, rho=0.3, r=0.05):
        self.spot, self.delta0 = float(spot), float(delta0)
        self.kappa, self.sigma_S = float(kappa), float(sigma_S)
        self.alpha_tilde, self.sigma_delta = float(alpha_tilde), float(sigma_delta)
        self.rho, self.r = float(rho), float(r)

    def _B(self, tau):
        return (1 - np.exp(-self.kappa * tau)) / self.kappa

    def _C(self, tau):
        k, sS, sd, rho = self.kappa, self.sigma_S, self.sigma_delta, self.rho
        a = self.alpha_tilde
        B = self._B(tau)
        return ((self.r - a) * tau + a * B
                + 0.5 * (sd**2 / k**2) * (tau - 2 * B + (1 - np.exp(-2 * k * tau)) / (2 * k))
                - (rho * sS * sd / k) * (tau - B))

    def futures(self, T):
        tau = float(T)
        return float(self.spot * np.exp(self._C(tau) - self.delta0 * self._B(tau)))

    def to_schwartz_smith(self) -> SchwartzSmith:
        """The Schwartz-Smith model with identical dynamics (2000 equivalence)."""
        k, sS, sd, rho = self.kappa, self.sigma_S, self.sigma_delta, self.rho
        sigma_chi = sd / k
        chi0 = (self.delta0 - self.alpha_tilde) / k
        xi0 = np.log(self.spot) - chi0
        mu_xi = self.r - self.alpha_tilde - 0.5 * sS**2
        sigma_xi = np.sqrt(max(sS**2 + sigma_chi**2 - 2 * rho * sS * sigma_chi, 1e-300))
        rho_cx = (rho * sS - sigma_chi) / sigma_xi
        return SchwartzSmith(chi0=chi0, xi0=xi0, kappa=k, sigma_chi=sigma_chi,
                             mu_xi=mu_xi, sigma_xi=sigma_xi, rho=rho_cx,
                             lambda_chi=0.0, r=self.r)

    def futures_option(self, T_opt, T_fut, K, opt="call"):
        return self.to_schwartz_smith().futures_option(T_opt, T_fut, K, opt)

    def simulate_spot(self, T, n_sims=100_000, steps=200, seed=42):
        """Euler MC of (S, δ) under Q — independent check of the futures formula."""
        rng = np.random.default_rng(seed)
        dt, sq = T / steps, np.sqrt(T / steps)
        S = np.full(n_sims, self.spot)
        d = np.full(n_sims, self.delta0)
        chol = np.linalg.cholesky([[1.0, self.rho], [self.rho, 1.0]])
        for _ in range(steps):
            Z = rng.standard_normal((n_sims, 2)) @ chol.T
            S = S * np.exp((self.r - d - 0.5 * self.sigma_S**2) * dt + self.sigma_S * sq * Z[:, 0])
            d = d + self.kappa * (self.alpha_tilde - d) * dt + self.sigma_delta * sq * Z[:, 1]
        return S


def commodity_futures_curve(model, tenors):
    """Futures term structure F(0,T) for a list of tenors."""
    return {float(T): model.futures(T) for T in tenors}


# ── seasonality + Pilipovic mean-reversion, gap-closing batch 3 ─────

def seasonal_factor(t, amps):
    """Deterministic seasonal log-adjustment Σ_k [a_k cos(2πkt) + b_k sin(2πkt)].
    amps: list of (a_k, b_k) for harmonics k=1,2,…"""
    s = 0.0
    for k, (a, b) in enumerate(amps, start=1):
        s += a * np.cos(2 * np.pi * k * t) + b * np.sin(2 * np.pi * k * t)
    return s


def seasonal_futures(model, T, amps):
    """Schwartz-Smith/Gibson-Schwartz futures with a deterministic seasonal factor:
    F_seasonal(0,T) = F_model(0,T)·exp(seasonal(T)). Zero amplitude → base model."""
    return float(model.futures(T) * np.exp(seasonal_factor(T, amps)))


class Pilipovic:
    """One-factor mean-reverting (Pilipovic) spot: dS = κ(μ-S)dt + σS dW.
    Risk-neutral futures F(0,T) = μ + (S0-μ)e^{-κT}: F(0,0)=S0, F(0,∞)→μ."""
    def __init__(self, S0, kappa, mu, sigma):
        self.S0, self.kappa, self.mu, self.sigma = float(S0), float(kappa), float(mu), float(sigma)

    def futures(self, T):
        return float(self.mu + (self.S0 - self.mu) * np.exp(-self.kappa * T))
