"""
Vanilla options: European, American, Bermudan
with multiple model choices.
"""

from models.black_scholes import bsm, black76, garman_kohlhagen, bachelier
from models.trees import binomial_crr, binomial_lr, trinomial
from models.monte_carlo import mc_price, lsm
import numpy as np


def european(S, K, T, r, sigma, q=0.0, opt="call", model="bsm",
             n=None, n_sims=None, steps=None, seed=None,
             ns=None, nt=None) -> dict:
    """
    European option.
    model: bsm | black76 | gk | bachelier | binomial | trinomial | mc
    For black76: S is treated as forward F.
    For gk: pass q as r_f.
    n / n_sims / steps / seed: optional numerical overrides (lattice size,
    MC paths/time steps/seed); the engine defaults apply when omitted.
    """
    if model == "bsm":
        g = bsm(S, K, T, r, sigma, q, opt)
        return g.as_dict()
    elif model == "black76":
        g = black76(S, K, T, r, sigma, opt)
        return g.as_dict()
    elif model == "gk":
        g = garman_kohlhagen(S, K, T, r, q, sigma, opt)
        return g.as_dict()
    elif model == "bachelier":
        g = bachelier(S, K, T, r, sigma, opt)
        return g.as_dict()
    elif model == "binomial":
        return binomial_crr(S, K, T, r, sigma, q, N=int(n or 500), opt=opt,
                            exercise="european")
    elif model == "binomial_lr":
        N = int(n or 501)
        if N % 2 == 0:
            N += 1                    # Leisen-Reimer requires an odd grid
        return binomial_lr(S, K, T, r, sigma, q, N=N, opt=opt,
                           exercise="european")
    elif model == "trinomial":
        return trinomial(S, K, T, r, sigma, q, N=int(n or 300), opt=opt,
                         exercise="european")
    elif model == "mc":
        if opt == "call":
            pf = lambda paths: np.maximum(paths[:, -1] - K, 0)
        else:
            pf = lambda paths: np.maximum(K - paths[:, -1], 0)
        return mc_price(pf, S, r, q, sigma, T,
                        steps=int(steps or 252),
                        n_sims=int(n_sims or 100_000),
                        seed=int(seed) if seed is not None else 42)
    elif model == "pde":
        from models.pde import cn_vanilla
        return cn_vanilla(S, K, T, r, sigma, q, opt, "european",
                          Ns=int(ns or 400), Nt=int(nt or 400))
    else:
        raise ValueError(f"Unknown model: {model}")


def american(S, K, T, r, sigma, q=0.0, opt="call", model="binomial", *,
             N=None, ns=None, nt=None, n_sims=None, steps=None, seed=None) -> dict:
    """
    American option.
    model: binomial | binomial_lr | trinomial | lsm
    """
    if model == "binomial":
        return binomial_crr(S, K, T, r, sigma, q, N=int(N or 500),
                            opt=opt, exercise="american")
    elif model == "binomial_lr":
        grid = int(N or 501)
        if grid % 2 == 0:
            grid += 1
        return binomial_lr(S, K, T, r, sigma, q, N=grid,
                           opt=opt, exercise="american")
    elif model == "trinomial":
        return trinomial(S, K, T, r, sigma, q, N=int(N or 300),
                         opt=opt, exercise="american")
    elif model == "lsm":
        return lsm(S, K, T, r, sigma, q,
                   n_sims=int(n_sims or 50_000), steps=int(steps or 252),
                   opt=opt, seed=int(seed) if seed is not None else 42)
    elif model == "pde":
        from models.pde import cn_vanilla
        return cn_vanilla(S, K, T, r, sigma, q, opt, "american",
                          Ns=int(ns or 400), Nt=int(nt or 400))
    else:
        raise ValueError(f"Unknown model: {model}")


def bermudan(S, K, T, r, sigma, q=0.0, opt="call",
             exercise_dates=None, model="binomial") -> dict:
    """
    Bermudan option with discrete exercise dates (years).
    exercise_dates: list of times in years, e.g. [0.25, 0.5, 0.75]
    """
    if exercise_dates is None:
        exercise_dates = [T * i / 4 for i in range(1, 5)]
    if model == "binomial":
        return binomial_crr(S, K, T, r, sigma, q, N=500, opt=opt,
                            exercise="bermudan", bermudan_dates=exercise_dates)
    elif model == "lsm":
        return lsm(S, K, T, r, sigma, q, opt=opt, exercise_dates=exercise_dates)
    else:
        raise ValueError(f"Unknown model: {model}")
