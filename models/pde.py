"""
Crank-Nicolson PDE engine (Phase 3).

Log-spot finite differences with Rannacher startup (two fully implicit steps to
damp the payoff kink), Thomas tridiagonal solves, Dirichlet asymptotic
boundaries. One engine covers European and American vanillas (projection step
for early exercise) and single-barrier knock-outs (barrier-aligned grid).
"""

import numpy as np
from scipy.linalg import solve_banded


def _cn_engine(S: float, K: float, T: float, r: float, sigma: float, q: float,
               opt: str, exercise: str = "european",
               barrier: float | None = None, barrier_dir: str = "down",
               rebate: float = 0.0, Ns: int = 400, Nt: int = 400) -> dict:
    """Backward CN sweep; returns price/delta/gamma at S."""
    x0 = np.log(S)
    span = 5.0 * sigma * np.sqrt(T) + abs(r - q) * T + 1.0
    if barrier is not None:
        xb = np.log(barrier)
        if barrier_dir == "down":
            lo, hi = xb, max(x0, np.log(K)) + span
        else:
            lo, hi = min(x0, np.log(K)) - span, xb
    else:
        lo, hi = min(x0, np.log(K)) - span, max(x0, np.log(K)) + span
    if not (lo < x0 < hi):
        raise ValueError("Spot outside the PDE domain (already through the barrier?)")

    # uniform grid with x0 on a node AND boundaries exactly at lo/hi:
    # choose dx from the larger side, then rebuild both sides
    n_lo = max(1, int(round((x0 - lo) / (hi - lo) * Ns)))
    n_hi = max(1, Ns - n_lo)
    dx_lo = (x0 - lo) / n_lo
    dx_hi = (hi - x0) / n_hi
    dx = min(dx_lo, dx_hi)
    n_lo = max(1, int(np.ceil((x0 - lo) / dx)))
    n_hi = max(1, int(np.ceil((hi - x0) / dx)))
    x = np.concatenate([x0 - dx * np.arange(n_lo, 0, -1), [x0],
                        x0 + dx * np.arange(1, n_hi + 1)])
    idx0 = n_lo
    S_grid = np.exp(x)
    n = len(x)

    dt = T / Nt
    a = r - q - 0.5 * sigma * sigma
    b = 0.5 * sigma * sigma
    # spatial operator M (central differences), interior rows
    alpha = b / dx**2 - a / (2 * dx)      # sub-diagonal
    beta = -2 * b / dx**2 - r             # diagonal
    gamma = b / dx**2 + a / (2 * dx)      # super-diagonal

    sign = 1.0 if opt == "call" else -1.0
    intrinsic = np.maximum(sign * (S_grid - K), 0.0)
    V = intrinsic.copy()

    def boundary(tau: float):
        """Dirichlet values at the grid ends, time-to-maturity tau."""
        if barrier is not None and barrier_dir == "down":
            v_lo = rebate
        elif opt == "call":
            v_lo = 0.0
        else:
            v_lo = K * np.exp(-r * tau) - S_grid[0] * np.exp(-q * tau)
            if exercise == "american":
                v_lo = max(v_lo, K - S_grid[0])
        if barrier is not None and barrier_dir == "up":
            v_hi = rebate
        elif opt == "call":
            v_hi = S_grid[-1] * np.exp(-q * tau) - K * np.exp(-r * tau)
            if exercise == "american":
                v_hi = max(v_hi, S_grid[-1] - K)
        else:
            v_hi = 0.0
        return max(v_lo, 0.0) if barrier is None else v_lo, \
               max(v_hi, 0.0) if barrier is None else v_hi

    def step(theta: float, dt_step: float):
        nonlocal V
        # (I - theta*dt*M) V_new = (I + (1-theta)*dt*M) V_old, interior nodes
        rhs = V.copy()
        if theta < 1.0:
            w = (1 - theta) * dt_step
            rhs[1:-1] = (V[1:-1] * (1 + w * beta)
                         + w * alpha * V[:-2] + w * gamma * V[2:])
        tau = (k + 1) * dt          # time to maturity AFTER this step (set by loop)
        v_lo, v_hi = boundary(tau)
        ab = np.zeros((3, n - 2))
        ab[0, 1:] = -theta * dt_step * gamma
        ab[1, :] = 1 - theta * dt_step * beta
        ab[2, :-1] = -theta * dt_step * alpha
        d = rhs[1:-1].copy()
        d[0] += theta * dt_step * alpha * v_lo
        d[-1] += theta * dt_step * gamma * v_hi
        interior = solve_banded((1, 1), ab, d)
        V[1:-1] = interior
        V[0], V[-1] = v_lo, v_hi
        if exercise == "american":
            np.maximum(V, intrinsic, out=V)

    for k in range(Nt):
        theta = 1.0 if k < 2 else 0.5      # Rannacher startup
        step(theta, dt)

    price = float(V[idx0])
    # Greeks in S-space from the log grid
    dV = (V[idx0 + 1] - V[idx0 - 1]) / (2 * dx)
    d2V = (V[idx0 + 1] - 2 * V[idx0] + V[idx0 - 1]) / dx**2
    delta = dV / S
    gamma_g = (d2V - dV) / (S * S)
    return dict(price=price, delta=float(delta), gamma=float(gamma_g),
                grid_nodes=n, time_steps=Nt, dx=dx)


def cn_vanilla(S: float, K: float, T: float, r: float, sigma: float,
               q: float = 0.0, opt: str = "call", exercise: str = "european",
               Ns: int = 400, Nt: int = 400) -> dict:
    """European/American vanilla via Crank-Nicolson."""
    res = _cn_engine(S, K, T, r, sigma, q, opt, exercise, Ns=Ns, Nt=Nt)
    res["exercise"] = exercise
    res["model"] = "pde_cn"
    return res


def cn_barrier(S: float, K: float, H: float, T: float, r: float, sigma: float,
               q: float = 0.0, opt: str = "call", barrier_type: str = "down-out",
               rebate: float = 0.0, Ns: int = 400, Nt: int = 400) -> dict:
    """
    Single-barrier option via Crank-Nicolson with the boundary pinned exactly on
    the barrier. Knock-ins via in-out parity with the CN vanilla (zero rebate).
    """
    direction = "down" if "down" in barrier_type else "up"
    if (direction == "down" and S <= H) or (direction == "up" and S >= H):
        vanilla = cn_vanilla(S, K, T, r, sigma, q, opt, Ns=Ns, Nt=Nt)["price"]
        price = rebate if "out" in barrier_type else vanilla
        return dict(price=price, barrier=H, barrier_type=barrier_type, model="pde_cn")

    out = _cn_engine(S, K, T, r, sigma, q, opt, "european",
                     barrier=H, barrier_dir=direction, rebate=rebate, Ns=Ns, Nt=Nt)
    if "out" in barrier_type:
        out.update(barrier=H, barrier_type=barrier_type, model="pde_cn")
        return out
    vanilla = cn_vanilla(S, K, T, r, sigma, q, opt, Ns=Ns, Nt=Nt)["price"]
    ko_zero_rebate = (_cn_engine(S, K, T, r, sigma, q, opt, "european", barrier=H,
                                 barrier_dir=direction, rebate=0.0, Ns=Ns, Nt=Nt)["price"]
                      if rebate else out["price"])
    return dict(price=max(vanilla - ko_zero_rebate, 0.0), barrier=H,
                barrier_type=barrier_type, vanilla=vanilla, model="pde_cn")
