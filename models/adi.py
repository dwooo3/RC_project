"""
ADI finite-difference solver for 2-D (two-asset) option PDEs, Master-plan M6.

Solves the two-asset Black-Scholes PDE in log-coordinates x=ln S1, y=ln S2,

  U_τ = ½σ1²U_xx + ½σ2²U_yy + ρσ1σ2·U_xy
        + (r-q1-½σ1²)U_x + (r-q2-½σ2²)U_y - rU

with the Douglas ADI scheme: an explicit full-operator predictor (carrying the
cross-derivative ρσ1σ2·U_xy) followed by two implicit tridiagonal corrector
sweeps, one per direction. ADI is the standard treatment for the mixed
∂²/∂x∂y term — a fully implicit 2-D solve would be a large non-banded system,
while ADI only ever solves tridiagonals.

In log-space the coefficients are constant, so the boundaries are clean and the
scheme reaches the exact Margrabe exchange-option price (the validation target);
it then prices a general two-asset payoff (spread, basket, best/worst-of).

The module also implements a separate Heston (S, v) Douglas ADI solver. Its
degenerate v=0 row uses the Hout-Foulon one-sided upwind treatment and is
governed under the distinct canonical identity ``heston_adi``.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm


def _thomas(a, b, c, d):
    """Solve a tridiagonal system (a=sub, b=diag, c=super, d=rhs)."""
    n = len(b)
    cp = np.empty(n); dp = np.empty(n)
    cp[0] = c[0] / b[0]; dp[0] = d[0] / b[0]
    for i in range(1, n):
        m = b[i] - a[i] * cp[i - 1]
        cp[i] = c[i] / m
        dp[i] = (d[i] - a[i] * dp[i - 1]) / m
    x = np.empty(n)
    x[-1] = dp[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


def margrabe(S1, S2, T, q1, q2, sigma1, sigma2, rho) -> float:
    """Exact exchange-option price: option to exchange S2 for S1, max(S1-S2,0)."""
    sig = np.sqrt(sigma1**2 + sigma2**2 - 2 * rho * sigma1 * sigma2)
    sq = sig * np.sqrt(T)
    d1 = (np.log(S1 / S2) + (q2 - q1 + 0.5 * sig**2) * T) / sq
    d2 = d1 - sq
    return S1 * np.exp(-q1 * T) * norm.cdf(d1) - S2 * np.exp(-q2 * T) * norm.cdf(d2)


def two_asset_adi(payoff, S1_0, S2_0, T, r, q1, q2, sigma1, sigma2, rho,
                  N1=80, N2=80, Nt=100, width=5.0):
    """Two-asset European option via Douglas ADI in log-space.

    payoff(S1grid, S2grid) -> terminal value array (len(x) × len(y)).
    Returns the price at (S1_0, S2_0)."""
    x0, y0 = np.log(S1_0), np.log(S2_0)
    hx, hy = width * sigma1 * np.sqrt(T), width * sigma2 * np.sqrt(T)
    x = np.linspace(x0 - hx, x0 + hx, N1 + 1)
    y = np.linspace(y0 - hy, y0 + hy, N2 + 1)
    dx, dy, dt = x[1] - x[0], y[1] - y[0], T / Nt
    S1g, S2g = np.exp(x), np.exp(y)

    U = payoff(S1g[:, None], S2g[None, :]).astype(float)

    mux = r - q1 - 0.5 * sigma1**2
    muy = r - q2 - 0.5 * sigma2**2
    xi = np.arange(1, N1); yj = np.arange(1, N2)

    def edge_value(tau):
        """Far-field Dirichlet: discounted-forward intrinsic of the payoff."""
        F1 = S1g * np.exp((r - q1) * tau)
        F2 = S2g * np.exp((r - q2) * tau)
        return np.exp(-r * tau) * payoff(F1[:, None], F2[None, :])

    def set_bc(W, tau):
        E = edge_value(tau)
        W[0, :] = E[0, :]; W[N1, :] = E[N1, :]
        W[:, 0] = E[:, 0]; W[:, N2] = E[:, N2]
        return W

    def A_full(W):
        out = np.zeros_like(W)
        Wc = W[1:N1, 1:N2]
        Uxx = (W[2:, 1:N2] - 2 * Wc + W[:N1 - 1, 1:N2]) / dx**2
        Uyy = (W[1:N1, 2:] - 2 * Wc + W[1:N1, :N2 - 1]) / dy**2
        Ux = (W[2:, 1:N2] - W[:N1 - 1, 1:N2]) / (2 * dx)
        Uy = (W[1:N1, 2:] - W[1:N1, :N2 - 1]) / (2 * dy)
        Uxy = (W[2:, 2:] - W[2:, :N2 - 1] - W[:N1 - 1, 2:] + W[:N1 - 1, :N2 - 1]) / (4 * dx * dy)
        out[1:N1, 1:N2] = (0.5 * sigma1**2 * Uxx + 0.5 * sigma2**2 * Uyy
                           + rho * sigma1 * sigma2 * Uxy + mux * Ux + muy * Uy - r * Wc)
        return out

    def A1(W):                                          # x-direction
        out = np.zeros_like(W)
        Wc = W[1:N1, 1:N2]
        Uxx = (W[2:, 1:N2] - 2 * Wc + W[:N1 - 1, 1:N2]) / dx**2
        Ux = (W[2:, 1:N2] - W[:N1 - 1, 1:N2]) / (2 * dx)
        out[1:N1, 1:N2] = 0.5 * sigma1**2 * Uxx + mux * Ux - 0.5 * r * Wc
        return out

    def A2(W):                                          # y-direction
        out = np.zeros_like(W)
        Wc = W[1:N1, 1:N2]
        Uyy = (W[1:N1, 2:] - 2 * Wc + W[1:N1, :N2 - 1]) / dy**2
        Uy = (W[1:N1, 2:] - W[1:N1, :N2 - 1]) / (2 * dy)
        out[1:N1, 1:N2] = 0.5 * sigma2**2 * Uyy + muy * Uy - 0.5 * r * Wc
        return out

    half = 0.5
    # constant tridiagonal coefficients (log-space -> coefficients independent of node)
    ax = -half * dt * (0.5 * sigma1**2 / dx**2 - mux / (2 * dx))
    bx = 1 + half * dt * (sigma1**2 / dx**2 + 0.5 * r)
    cx = -half * dt * (0.5 * sigma1**2 / dx**2 + mux / (2 * dx))
    ay = -half * dt * (0.5 * sigma2**2 / dy**2 - muy / (2 * dy))
    by = 1 + half * dt * (sigma2**2 / dy**2 + 0.5 * r)
    cy = -half * dt * (0.5 * sigma2**2 / dy**2 + muy / (2 * dy))
    Ax = np.full(N1 - 1, ax); Bx = np.full(N1 - 1, bx); Cx = np.full(N1 - 1, cx)
    Ay = np.full(N2 - 1, ay); By = np.full(N2 - 1, by); Cy = np.full(N2 - 1, cy)

    U = set_bc(U, 0.0)
    for n in range(Nt):
        tau = (n + 1) * dt
        U0 = U.copy()
        Y0 = set_bc(U + dt * A_full(U), tau)
        # x-sweep: (I - half dt A1) Y1 = Y0 - half dt A1 U0, with Dirichlet edges in RHS
        rhs1 = (Y0 - half * dt * A1(U0))
        Y1 = Y0.copy()
        for j in yj:
            d = rhs1[1:N1, j].copy()
            d[0] -= ax * Y0[0, j]; d[-1] -= cx * Y0[N1, j]
            Y1[1:N1, j] = _thomas(Ax, Bx, Cx, d)
        Y1 = set_bc(Y1, tau)
        # y-sweep
        rhs2 = (Y1 - half * dt * A2(U0))
        Y2 = Y1.copy()
        for i in xi:
            d = rhs2[i, 1:N2].copy()
            d[0] -= ay * Y1[i, 0]; d[-1] -= cy * Y1[i, N2]
            Y2[i, 1:N2] = _thomas(Ay, By, Cy, d)
        U = set_bc(Y2, tau)

    i = min(max(np.searchsorted(x, x0) - 1, 0), N1 - 1)
    j = min(max(np.searchsorted(y, y0) - 1, 0), N2 - 1)
    wx = (x0 - x[i]) / (x[i + 1] - x[i]); wy = (y0 - y[j]) / (y[j + 1] - y[j])
    return float((1 - wx) * (1 - wy) * U[i, j] + wx * (1 - wy) * U[i + 1, j]
                 + (1 - wx) * wy * U[i, j + 1] + wx * wy * U[i + 1, j + 1])


def exchange_option_adi(S1, S2, T, r, q1, q2, sigma1, sigma2, rho, **kw):
    """Margrabe exchange option max(S1-S2,0) via two-asset ADI."""
    return two_asset_adi(lambda a, b: np.maximum(a - b, 0.0),
                         S1, S2, T, r, q1, q2, sigma1, sigma2, rho, **kw)


# ── Heston (S, v) ADI with the Hout-Foulon v=0 boundary ──────

def heston_adi(S0, K, T, r, q, v0, kappa, theta, sigma, rho, opt="call",
               NS=160, Nv=80, Nt=120, S_max=None, v_max=None):
    """European Heston option via Douglas ADI. The degenerate v=0 boundary is
    *evolved* (Hout-Foulon): diffusion vanishes there, so the v-row keeps the
    κθ·U_v drift with a one-sided forward difference (upwind, κθ>0) instead of
    being frozen at the payoff. Validated against the Heston CF."""
    S_max = S_max or 4 * max(S0, K)
    v_max = v_max or max(0.5, 5 * theta, 5 * v0)
    S = np.linspace(0.0, S_max, NS + 1)
    v = np.linspace(0.0, v_max, Nv + 1)
    dS, dv, dt = S[1] - S[0], v[1] - v[0], T / Nt
    half = 0.5

    U = np.maximum((S[:, None] - K) if opt == "call" else (K - S[:, None]), 0.0)
    U = np.repeat(U.astype(float), Nv + 1, axis=1)

    si = np.arange(1, NS)                                # interior S
    jj = np.arange(0, Nv)                                # v rows we evolve (Nv = Neumann)

    def set_bc(W, tau):
        if opt == "call":
            W[0, :] = 0.0
            W[NS, :] = S_max * np.exp(-q * tau) - K * np.exp(-r * tau)
        else:
            W[0, :] = K * np.exp(-r * tau)
            W[NS, :] = 0.0
        W[:, Nv] = W[:, Nv - 1]                          # v_max Neumann
        return W

    Sg = S[si][:, None]; vg = v[jj][None, :]

    def A0(W):                                           # mixed term (interior only)
        out = np.zeros_like(W)
        Usv = (W[2:, 2:] - W[2:, :Nv - 1] - W[:NS - 1, 2:] + W[:NS - 1, :Nv - 1]) / (4 * dS * dv)
        out[1:NS, 1:Nv] = rho * sigma * v[1:Nv][None, :] * S[si][:, None] * Usv
        return out

    def A1(W):                                           # S-direction (all evolved v rows)
        out = np.zeros_like(W)
        Wc = W[1:NS, 0:Nv]
        U_SS = (W[2:, 0:Nv] - 2 * Wc + W[:NS - 1, 0:Nv]) / dS**2
        U_S = (W[2:, 0:Nv] - W[:NS - 1, 0:Nv]) / (2 * dS)
        out[1:NS, 0:Nv] = 0.5 * vg * Sg**2 * U_SS + (r - q) * Sg * U_S - 0.5 * r * Wc
        return out

    def A2(W):                                           # v-direction (forward diff at v=0)
        out = np.zeros_like(W)
        Wc = W[1:NS, 1:Nv]                               # central for j=1..Nv-1
        U_vv = (W[1:NS, 2:] - 2 * Wc + W[1:NS, :Nv - 1]) / dv**2
        U_v = (W[1:NS, 2:] - W[1:NS, :Nv - 1]) / (2 * dv)
        out[1:NS, 1:Nv] = 0.5 * sigma**2 * v[1:Nv] * U_vv + kappa * (theta - v[1:Nv]) * U_v - 0.5 * r * Wc
        U_v0 = (W[1:NS, 1] - W[1:NS, 0]) / dv           # one-sided at v=0
        out[1:NS, 0] = kappa * theta * U_v0 - 0.5 * r * W[1:NS, 0]
        return out

    # S-tridiagonal coeffs per v-row
    def s_coeffs(vv):
        a = -half * dt * (0.5 * vv * S[si]**2 / dS**2 - (r - q) * S[si] / (2 * dS))
        b = 1 + half * dt * (vv * S[si]**2 / dS**2 + 0.5 * r)
        c = -half * dt * (0.5 * vv * S[si]**2 / dS**2 + (r - q) * S[si] / (2 * dS))
        return a, b, c

    # v-tridiagonal coeffs (j=0 forward diff; Neumann fold at j=Nv-1)
    def v_system(rhs_col):
        a = np.zeros(Nv); b = np.zeros(Nv); c = np.zeros(Nv)
        b[0] = 1 + half * dt * (kappa * theta / dv + 0.5 * r)
        c[0] = -half * dt * (kappa * theta / dv)
        for j in range(1, Nv):
            vv = v[j]
            sub = 0.5 * sigma**2 * vv / dv**2 - kappa * (theta - vv) / (2 * dv)
            sup = 0.5 * sigma**2 * vv / dv**2 + kappa * (theta - vv) / (2 * dv)
            a[j] = -half * dt * sub
            b[j] = 1 + half * dt * (sigma**2 * vv / dv**2 + 0.5 * r)
            c[j] = -half * dt * sup
        b[Nv - 1] += c[Nv - 1]                           # Neumann: U[Nv]=U[Nv-1]
        c[Nv - 1] = 0.0
        return _thomas(a, b, c, rhs_col)

    U = set_bc(U, 0.0)
    for n in range(Nt):
        tau = (n + 1) * dt
        U0 = U.copy()
        Y0 = set_bc(U + dt * (A0(U) + A1(U) + A2(U)), tau)
        # implicit S-sweep over every evolved v row
        rhs1 = Y0 - half * dt * A1(U0)
        Y1 = Y0.copy()
        for j in jj:
            a, b, c = s_coeffs(v[j])
            d = rhs1[1:NS, j].copy()
            d[0] -= a[0] * Y0[0, j]; d[-1] -= c[-1] * Y0[NS, j]
            Y1[1:NS, j] = _thomas(a, b, c, d)
        Y1 = set_bc(Y1, tau)
        # implicit v-sweep over interior S
        rhs2 = Y1 - half * dt * A2(U0)
        Y2 = Y1.copy()
        for i in si:
            Y2[i, 0:Nv] = v_system(rhs2[i, 0:Nv])
        U = set_bc(Y2, tau)

    i = min(max(np.searchsorted(S, S0) - 1, 0), NS - 1)
    j = min(max(np.searchsorted(v, v0) - 1, 0), Nv - 1)
    ws = (S0 - S[i]) / (S[i + 1] - S[i]); wv = (v0 - v[j]) / (v[j + 1] - v[j])
    return float((1 - ws) * (1 - wv) * U[i, j] + ws * (1 - wv) * U[i + 1, j]
                 + (1 - ws) * wv * U[i, j + 1] + ws * wv * U[i + 1, j + 1])
