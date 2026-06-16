"""
Gap-closing batches (catalogue items B/C). Each model validated identity-first
against its Black-Scholes / reference limit, plus M0 registry-guard wiring.
"""
import numpy as np
import pytest

from models.black_scholes import bsm, black76


# ══════════════════════ Batch 1: vanilla / vol analytics ══════════════════════

def test_displaced_diffusion_zero_shift():
    from models.vanilla_extra import displaced_diffusion
    assert displaced_diffusion(100, 100, 1, 0.05, 0.2, 0.0, "call") == pytest.approx(
        black76(100, 100, 1, 0.05, 0.2, "call").price, abs=1e-12)


def test_cev_beta_one_is_bsm():
    from models.vanilla_extra import cev_price
    ref = bsm(100, 100, 1, 0.05, 0.2, 0.0, "call").price
    assert cev_price(100, 100, 1, 0.05, 0.2, 1.0, 0.0, "call") == pytest.approx(ref, abs=1e-10)


@pytest.mark.parametrize("beta", [0.4, 0.7, 1.0])
def test_cev_put_call_parity(beta):
    from models.vanilla_extra import cev_price
    c = cev_price(100, 95, 1, 0.05, 0.2, beta, 0.02, "call")
    p = cev_price(100, 95, 1, 0.05, 0.2, beta, 0.02, "put")
    assert c - p == pytest.approx(100 * np.exp(-0.02) - 95 * np.exp(-0.05), abs=1e-8)


def test_discrete_div_no_div_is_bsm():
    from models.vanilla_extra import discrete_dividend_bsm
    ref = bsm(100, 100, 1, 0.05, 0.2, 0.0, "call").price
    assert discrete_dividend_bsm(100, 100, 1, 0.05, 0.2, [], "call") == pytest.approx(ref, abs=1e-12)
    assert discrete_dividend_bsm(100, 100, 1, 0.05, 0.2, [(0.5, 5.0)], "call") < ref


@pytest.mark.parametrize("fn", ["binomial_jarrow_rudd", "binomial_tian"])
def test_binomial_converges_to_bsm(fn):
    import models.vanilla_extra as VE
    ref = bsm(100, 100, 1, 0.05, 0.2, 0.0, "call").price
    assert getattr(VE, fn)(100, 100, 1, 0.05, 0.2, 0.0, "call", 2000) == pytest.approx(ref, abs=5e-3)


def test_jr_american_ge_european():
    from models.vanilla_extra import binomial_jarrow_rudd
    e = binomial_jarrow_rudd(100, 100, 1, 0.05, 0.2, 0.0, "put", 800, "european")
    a = binomial_jarrow_rudd(100, 100, 1, 0.05, 0.2, 0.0, "put", 800, "american")
    assert a >= e - 1e-9


def test_mixture_single_and_convexity():
    from models.vanilla_extra import mixture_price
    ref = bsm(100, 100, 1, 0.05, 0.2, 0.0, "call").price
    assert mixture_price(100, 100, 1, 0.05, [0.2], [1.0], 0.0, "call") == pytest.approx(ref, abs=1e-12)
    blend = mixture_price(100, 100, 1, 0.05, [0.15, 0.30], [0.5, 0.5], 0.0, "call")
    assert blend > bsm(100, 100, 1, 0.05, 0.225, 0.0, "call").price        # vol convexity


def test_batch1_wired_and_service():
    from models import taxonomy as tax, registry as R
    from services.pricing_service import PricingService
    for mid in ("displaced_diffusion", "cev", "discrete_div_bsm", "binomial_jr",
                "binomial_tian", "lognormal_mixture"):
        assert mid in R.MODEL_REGISTRY and tax.classify(mid)["kind"] == "pricer"
    svc = PricingService()
    r = svc.price_vanilla_extra("cev", 100, 100, 1, 0.05, 0.2, beta=0.7)
    assert r["errors"] == [] and r["value"] > 0


# ══════════════════════ Batch 2: Carr-Madan FFT ══════════════════════

@pytest.mark.parametrize("K", [80, 100, 120])
def test_carr_madan_matches_bsm(K):
    from models.fourier import carr_madan_bsm
    ref = bsm(100, K, 1.0, 0.05, 0.2, 0.0, "call").price
    assert carr_madan_bsm(100, K, 1.0, 0.05, 0.2, 0.0, "call") == pytest.approx(ref, abs=2e-3)


@pytest.mark.parametrize("K", [90, 100, 110])
def test_carr_madan_matches_heston(K):
    from models.fourier import carr_madan_heston
    from models.heston import heston_price
    ref = heston_price(100, K, 1.0, 0.03, 0.0, 0.04, 1.5, 0.04, 0.3, -0.6, "call")["price"]
    assert carr_madan_heston(100, K, 1.0, 0.03, 0.0, 0.04, 1.5, 0.04, 0.3, -0.6, "call") == pytest.approx(ref, abs=2e-3)


def test_carr_madan_parity_and_service():
    from models.fourier import carr_madan_bsm
    from services.pricing_service import PricingService
    c = carr_madan_bsm(100, 100, 1, 0.05, 0.2, 0, "call")
    p = carr_madan_bsm(100, 100, 1, 0.05, 0.2, 0, "put")
    assert c - p == pytest.approx(100 - 100 * np.exp(-0.05), abs=1e-6)
    r = PricingService().price_carr_madan("heston", 100, 100, 1.0, 0.03, q=0.0, v0=0.04)
    assert r["errors"] == [] and r["value"] > 0 and r["model_id"] == "carr_madan"


# ══════════════════════ Batch 3: VV smile, copulas, commodity ══════════════════════

def test_vanna_volga_reproduces_pillars():
    from models.vanna_volga import vv_implied_vol
    S, T, rd, rf = 1.20, 1.0, 0.03, 0.01
    Katm, Kp, Kc, satm, sp, sc = 1.20, 1.10, 1.30, 0.10, 0.115, 0.095
    for K, s in [(Kp, sp), (Katm, satm), (Kc, sc)]:
        assert vv_implied_vol(S, K, T, rd, rf, Katm, satm, Kp, sp, Kc, sc) == pytest.approx(s, abs=2e-4)


def test_vanna_volga_flat_is_flat():
    from models.vanna_volga import vv_implied_vol
    v = vv_implied_vol(1.20, 1.25, 1.0, 0.03, 0.01, 1.20, 0.10, 1.10, 0.10, 1.30, 0.10)
    assert v == pytest.approx(0.10, abs=1e-9)


def test_t_copula_df_to_inf_is_gaussian():
    from models.credit_portfolio import basket_mc, basket_mc_t
    pds = [0.05] * 30
    g = basket_mc(pds, 0.3, k=3, n_sims=300_000, seed=1)["kth_prob"]
    t = basket_mc_t(pds, 0.3, df=200, k=3, n_sims=300_000, seed=1)["kth_prob"]
    assert t == pytest.approx(g, abs=0.01)


def test_t_copula_tail_dependence():
    from models.credit_portfolio import basket_mc, basket_mc_t
    pds = [0.05] * 30
    g = basket_mc(pds, 0.3, k=12, n_sims=400_000, seed=1)["kth_prob"]
    t = basket_mc_t(pds, 0.3, df=4, k=12, n_sims=400_000, seed=1)["kth_prob"]
    assert t > g                                          # extreme co-defaults


def test_clayton_lower_tail_dependence():
    from models.credit_portfolio import basket_mc_clayton
    pds = [0.05] * 30
    cl = basket_mc_clayton(pds, theta=2.0, k=5, n_sims=300_000, seed=1)["kth_prob"]
    indep = basket_mc_clayton(pds, theta=1e-3, k=5, n_sims=300_000, seed=1)["kth_prob"]
    assert cl > indep
    el_a = basket_mc_clayton(pds, 2.0, 1, n_sims=200_000)["pool_el"]
    assert el_a == pytest.approx(0.05 * 0.6, abs=3e-3)   # copula-invariant EL


def test_commodity_seasonality_and_pilipovic():
    from models.commodity import SchwartzSmith, seasonal_futures, Pilipovic
    ss = SchwartzSmith(chi0=0.0, xi0=np.log(50), kappa=1.0, sigma_chi=0.2,
                       mu_xi=0.0, sigma_xi=0.1, rho=0.2, r=0.05)
    assert seasonal_futures(ss, 2.0, [(0.0, 0.0)]) == pytest.approx(ss.futures(2.0), abs=1e-12)
    fs = [seasonal_futures(ss, T, [(0.1, 0.05)]) for T in np.linspace(1, 2, 6)]
    assert max(fs) - min(fs) > 0
    p = Pilipovic(60, 2.0, 50, 0.3)
    assert p.futures(0) == pytest.approx(60.0)
    assert p.futures(50) == pytest.approx(50.0, abs=1e-3)
    assert p.futures(0) > p.futures(1) > p.futures(5)


def test_batch3_wired_and_service():
    from models import taxonomy as tax, registry as R
    from services.pricing_service import PricingService
    for mid in ("vanna_volga", "t_copula", "clayton_copula", "commodity_seasonal", "pilipovic"):
        assert mid in R.MODEL_REGISTRY and tax.classify(mid)["asset_class"] in ("fx", "credit", "commodity")
    svc = PricingService()
    vv = svc.price_vanna_volga(1.2, 1.25, 1.0, 0.03, 0.01, 1.20, 0.10, 1.10, 0.115, 1.30, 0.095)
    assert vv["errors"] == [] and vv["value"] > 0
    bc = svc.price_basket_copula("clayton", [0.05] * 20, k=3, theta=2.0, n_sims=50_000)
    assert bc["errors"] == [] and bc["value"] >= 0
