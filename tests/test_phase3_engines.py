"""
Phase 3 — numerical engines.
Crank-Nicolson PDE, Merton/Bates jump-diffusion, Andersen QE Heston scheme,
Dupire local-vol MC. Each engine is pinned to a closed form or an exact limit.
"""
import numpy as np
import pytest

from models.black_scholes import bsm
from services.pricing_service import PricingService


@pytest.fixture(scope="module")
def svc():
    return PricingService()


@pytest.fixture(scope="module")
def lab():
    return PricingService(allow_analytics_lab=True)


# ── Crank-Nicolson PDE ───────────────────────────────────

def test_pde_european_matches_bsm():
    from models.pde import cn_vanilla
    S, K, T, r, q, sig = 100, 105, 1.0, 0.07, 0.02, 0.30
    for opt in ("call", "put"):
        pde = cn_vanilla(S, K, T, r, sig, q, opt)
        ref = bsm(S, K, T, r, sig, q, opt)
        assert pde["price"] == pytest.approx(ref.price, abs=5e-3), opt
        assert pde["delta"] == pytest.approx(ref.delta, abs=1e-3)
        assert pde["gamma"] == pytest.approx(ref.gamma, abs=1e-4)


def test_pde_american_matches_crr():
    from models.pde import cn_vanilla
    from models.trees import binomial_crr
    am = cn_vanilla(100, 105, 1.0, 0.07, 0.30, 0.02, "put", "american")
    crr = binomial_crr(100, 105, 1.0, 0.07, 0.30, 0.02, N=2000,
                       opt="put", exercise="american")
    assert am["price"] == pytest.approx(crr["price"], abs=2e-2)
    assert am["price"] > bsm(100, 105, 1.0, 0.07, 0.30, 0.02, "put").price
    # American call with q=0 has no early-exercise premium
    amc = cn_vanilla(100, 105, 1.0, 0.07, 0.30, 0.0, "call", "american")
    assert amc["price"] == pytest.approx(bsm(100, 105, 1.0, 0.07, 0.30).price, abs=5e-3)


def test_pde_barrier_matches_closed_form():
    from models.pde import cn_barrier
    from instruments.barrier import single_barrier
    cases = [(100, 100, 90, "call", "down-out"), (100, 90, 120, "put", "up-out"),
             (100, 100, 90, "call", "down-in")]
    for S, K, H, opt, btype in cases:
        pde = cn_barrier(S, K, H, 1.0, 0.05, 0.25, 0.02, opt, btype)
        cf = single_barrier(S, K, H, 1.0, 0.05, 0.25, 0.02, opt, btype)
        assert pde["price"] == pytest.approx(cf["price"], abs=3e-2), (opt, btype)


def test_pde_via_vanilla_dispatch_and_service(svc):
    from instruments.vanilla import american, european
    assert european(100, 100, 1, 0.05, 0.2, model="pde")["price"] == pytest.approx(
        bsm(100, 100, 1, 0.05, 0.2).price, abs=5e-3)
    assert american(100, 100, 1, 0.05, 0.2, opt="put", model="pde")["price"] > 0
    res = svc.price_american_option(100, 100, 1.0, 0.05, 0.2, opt="put")
    assert res["errors"] == [] and res["model_id"] == "pde_cn"
    eu = svc.price_vanilla_option(100, 100, 1.0, 0.05, 0.2, model="pde")
    assert eu["errors"] == [] and eu["model_id"] == "pde_cn"
    bar = svc.price_barrier_option_pde(100, 100, 90, 1.0, 0.05, 0.25)
    assert bar["errors"] == []


# ── Merton jump-diffusion ────────────────────────────────

def test_merton_lambda_zero_is_bsm():
    from models.jump_diffusion import merton_price
    m = merton_price(100, 105, 1.0, 0.07, 0.25, 0.02, lam=0.0)
    assert m["price"] == pytest.approx(bsm(100, 105, 1.0, 0.07, 0.25, 0.02).price,
                                       abs=1e-10)
    assert m["delta"] == pytest.approx(bsm(100, 105, 1.0, 0.07, 0.25, 0.02).delta,
                                       abs=1e-10)


def test_merton_parity_and_mc():
    from models.jump_diffusion import merton_mc, merton_price
    args = (100, 105, 1.0, 0.07, 0.25, 0.02, 0.3, -0.12, 0.18)
    c = merton_price(*args, opt="call")
    p = merton_price(*args, opt="put")
    assert c["price"] - p["price"] == pytest.approx(
        100 * np.exp(-0.02) - 105 * np.exp(-0.07), abs=1e-9)
    mc = merton_mc(*args, opt="call", n_sims=200_000)
    assert c["price"] == pytest.approx(mc["price"], abs=4 * mc["stderr"])
    # jumps with negative mean add value to OTM puts
    p0 = merton_price(100, 80, 0.5, 0.05, 0.2, 0.0, lam=0.0, opt="put")["price"]
    pj = merton_price(100, 80, 0.5, 0.05, 0.2, 0.0, lam=0.5, mu_j=-0.2,
                      delta_j=0.1, opt="put")["price"]
    assert pj > p0


def test_merton_service_route(svc):
    res = svc.price_merton_option(100, 100, 1.0, 0.05, 0.2, lam=0.3)
    assert res["errors"] == [] and res["model_id"] == "merton_jump"


# ── Bates ────────────────────────────────────────────────

def test_bates_degenerate_limits():
    from models.heston import heston_price
    from models.jump_diffusion import bates_price, merton_price
    heston_args = (100, 105, 1.0, 0.05, 0.02, 0.09, 1.5, 0.09, 0.4, -0.6)
    b0 = bates_price(*heston_args, lam=0.0)
    h0 = heston_price(*heston_args)
    assert b0["price"] == pytest.approx(h0["price"], abs=5e-4)
    # xi -> 0 with v0 = theta collapses to Merton at sigma = sqrt(v0)
    bm = bates_price(100, 105, 1.0, 0.05, 0.02, 0.0625, 2.0, 0.0625, 1e-4, 0.0,
                     0.3, -0.12, 0.18)
    mm = merton_price(100, 105, 1.0, 0.05, 0.25, 0.02, 0.3, -0.12, 0.18)
    assert bm["price"] == pytest.approx(mm["price"], abs=5e-3)


def test_bates_parity_and_lab_gating(svc, lab):
    from models.jump_diffusion import bates_price
    args = (100, 105, 1.0, 0.05, 0.02, 0.09, 1.5, 0.09, 0.4, -0.6, 0.3, -0.12, 0.18)
    c = bates_price(*args, opt="call")["price"]
    p = bates_price(*args, opt="put")["price"]
    assert c - p == pytest.approx(100 * np.exp(-0.02) - 105 * np.exp(-0.05), abs=1e-9)
    # production service blocks the lab model; lab service prices it
    blocked = svc.price_bates_option(100, 105, 1.0, 0.05, 0.02, 0.09, 1.5, 0.09, 0.4, -0.6)
    assert blocked["errors"]
    ok = lab.price_bates_option(100, 105, 1.0, 0.05, 0.02, 0.09, 1.5, 0.09, 0.4, -0.6)
    assert ok["errors"] == [] and ok["value"] > 0


# ── Andersen QE ──────────────────────────────────────────

def test_qe_beats_euler_at_coarse_steps():
    from models.heston import heston_price
    from models.monte_carlo import heston_mc_price
    cf = heston_price(100, 100, 1.0, 0.05, 0.0, 0.09, 1.5, 0.09, 0.6, -0.7)["price"]
    pay = lambda p: np.maximum(p[:, -1] - 100, 0)
    qe = heston_mc_price(pay, 100, 0.09, 0.05, 0.0, 1.5, 0.09, 0.6, -0.7, 1.0,
                         steps=32, n_sims=200_000, seed=11, scheme="qe")
    eu = heston_mc_price(pay, 100, 0.09, 0.05, 0.0, 1.5, 0.09, 0.6, -0.7, 1.0,
                         steps=32, n_sims=200_000, seed=11, scheme="euler")
    assert abs(qe["price"] - cf) < abs(eu["price"] - cf)        # smaller bias
    assert qe["price"] == pytest.approx(cf, abs=4 * qe["stderr"] + 0.02)


# ── Local vol MC ─────────────────────────────────────────

def test_local_vol_flat_surface_is_bsm():
    from models.local_vol import local_vol_mc, tabulate_local_vol
    from risk.vol_surface import VolSurface
    surf = VolSurface.flat(0.25, S0=100)
    lv = tabulate_local_vol(surf, 100, 0.05, 0.0, 1.0)
    res = local_vol_mc(lambda p: np.maximum(p[:, -1] - 105, 0),
                       100, 0.05, 0.0, lv, 1.0, steps=100, n_sims=80_000)
    ref = bsm(100, 105, 1.0, 0.05, 0.25).price
    assert res["price"] == pytest.approx(ref, abs=4 * res["stderr"] + 0.02)


def test_local_vol_reprices_smile():
    from models.local_vol import local_vol_mc, tabulate_local_vol
    from risk.vol_surface import VolSurface
    K_grid = np.linspace(50, 160, 12)
    T_grid = np.array([0.25, 0.5, 1.0, 2.0])
    vols = np.array([[0.25 + 0.10 * (np.log(k / 100)) ** 2 for _ in T_grid]
                     for k in K_grid])
    smile = VolSurface(K_grid, T_grid, vols, S0=100)
    lv = tabulate_local_vol(smile, 100, 0.05, 0.0, 1.0, n_s=100, n_t=50)
    for K in (90.0, 115.0):
        mc = local_vol_mc(lambda p, K=K: np.maximum(p[:, -1] - K, 0),
                          100, 0.05, 0.0, lv, 1.0, steps=150, n_sims=120_000)
        ref = bsm(100, K, 1.0, 0.05, smile.get_vol(K, 1.0)).price
        assert mc["price"] == pytest.approx(ref, abs=4 * mc["stderr"] + 0.03), K


# ── Catalogue ────────────────────────────────────────────

def test_phase3_catalogue_products(svc):
    from app.panels.pricing_catalogue import PRODUCTS
    by_id = {p.id: p for p in PRODUCTS}
    for pid in ("american", "merton"):
        assert pid in by_id, pid
        p = by_id[pid]
        values = {f.key: f.default for f in p.fields}
        res = p.price(svc, values)
        assert res["errors"] == [], (pid, res["errors"])
        assert res["value"] is not None and res["value"] > 0
