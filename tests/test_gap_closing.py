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
    blocked = PricingService().price_carr_madan(
        "heston", 100, 100, 1.0, 0.03, q=0.0, v0=0.04
    )
    assert blocked["value"] is None
    assert any("ENGINE_RESEARCH_ONLY" in error for error in blocked["errors"])
    r = PricingService(allow_analytics_lab=True).price_carr_madan(
        "heston", 100, 100, 1.0, 0.03, q=0.0, v0=0.04
    )
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


# ══════════════════════ Batch 4: SMM, exotics, ABS, inflation, WWR, risk ══════════════════════

def test_smm_swaption_equals_black():
    from curves.yield_curve import YieldCurve
    from models.rates_market import smm_swaption
    from models.short_rate import black_swaption_price
    curve = YieldCurve.flat(0.05)
    for opt in ("payer", "receiver"):
        smm = smm_swaption(curve, 1e6, 0.05, 2.0, 5.0, 2, 0.2, 0.0, opt)["price"]
        blk = black_swaption_price(1e6, 0.05, 2.0, 5.0, 2, curve, 0.2, opt)
        assert smm == pytest.approx(blk, abs=1e-6)


def test_tarn_monotone_in_target():
    from models.exotics_extra import tarn
    vals = [tarn(100, 105, 3.0, 4, 0.03, 0.25, tg, n_sims=40_000, seed=1)["price"]
            for tg in (0.001, 0.1, 0.3, 1e9)]
    assert all(a <= b + 1e-6 for a, b in zip(vals, vals[1:]))


def test_accumulator_monotone_in_barrier():
    from models.exotics_extra import accumulator
    vals = [accumulator(100, 98, b, 1.0, 12, 0.03, 0.2, n_sims=40_000, seed=1)["price"]
            for b in (105, 115, 130, 1e9)]
    assert all(a <= b + 1e-3 for a, b in zip(vals, vals[1:]))


def test_abs_waterfall():
    from models.mbs import abs_waterfall
    tr = abs_waterfall(100.0, 0.05, 0.05, 360,
                       [("A", 60, 0.04), ("B", 25, 0.05), ("C", 15, 0.07)],
                       psa=150, disc_rate=0.05)
    assert sum(t["principal"].sum() for t in tr) == pytest.approx(100.0, abs=1e-3)
    assert tr[0]["wal"] < tr[2]["wal"]                    # senior shorter
    assert tr[0]["principal"][0] > tr[2]["principal"][0]  # senior paid first


def test_jarrow_yildirim():
    from models.inflation_jy import breakeven_inflation, zciis_fair_rate, forward_cpi
    assert breakeven_inflation(0.05, 0.05, 5) == pytest.approx(0.0, abs=1e-12)
    assert (1 + zciis_fair_rate(0.06, 0.02, 5)) ** 5 == pytest.approx(forward_cpi(1, 0.06, 0.02, 5), abs=1e-9)


def test_cva_wrong_way():
    from curves.yield_curve import YieldCurve
    from curves.hazard import HazardCurve
    from risk.xva import simulate_irs_portfolio, xva_suite, cva_wrong_way
    curve, cp = YieldCurve.flat(0.06), HazardCurve.flat(0.03)
    sim = simulate_irs_portfolio([dict(notional=1e7, fixed_rate=0.06, T=5.0, freq=2, pay_fixed=True)],
                                 curve, n_sims=6000, n_grid=20, seed=1)
    indep = xva_suite(sim, curve, cp)["cva"]
    assert cva_wrong_way(sim, curve, cp, beta=0.0) == pytest.approx(indep, abs=2.0)
    assert cva_wrong_way(sim, curve, cp, beta=3.0) > indep


def test_frtb_ima_es():
    from models.frtb import frtb_ima_es
    import numpy as np
    rng = np.random.default_rng(0)
    pnl = rng.standard_normal(100_000)
    r = frtb_ima_es(pnl, 0.975)
    assert r["es"] >= r["var"] and r["es"] == pytest.approx(2.34, abs=0.05)


def test_copula_var_ordering():
    from risk.var import copula_var
    import numpy as np
    w, vols = [1e6, 1e6, 1e6], [0.2, 0.3, 0.25]
    I, ones = np.eye(3), np.ones((3, 3))
    indep = copula_var(w, vols, I, 0.99, n_sims=200_000)["var"]
    como = copula_var(w, vols, ones, 0.99, n_sims=200_000)["var"]
    assert indep < como
    from scipy.stats import norm
    assert como == pytest.approx(norm.ppf(0.99) * sum(wi * si for wi, si in zip(w, vols)), rel=0.03)


def test_batch4_wired_and_service():
    from models import taxonomy as tax, registry as R
    from services.pricing_service import PricingService
    from services.risk_service import RiskService
    for mid in ("swap_market_model", "tarn", "accumulator", "abs", "jarrow_yildirim",
                "cva_wwr", "frtb_ima", "copula_var"):
        assert mid in R.MODEL_REGISTRY and mid in tax.CLASSIFICATION
    ps, rs = PricingService(), RiskService()
    assert ps.price_smm_swaption(1e6, 0.05, 2.0, 5.0)["errors"] == []
    assert ps.price_tarn(100, 105, 2.0, 4, 0.03, 0.25, 0.2, n_sims=20_000)["errors"] == []
    import numpy as np
    assert rs.frtb_ima(list(np.random.default_rng(0).standard_normal(20_000)))["errors"] == []
    assert rs.copula_var([1e6, 1e6], [0.2, 0.3], np.eye(2).tolist(), n_sims=20_000)["errors"] == []


# ══════════════════════ Batch B: partial-model fixes ══════════════════════

@pytest.mark.parametrize("Y", [0.5, 0.8, 1.2, 1.5])
def test_cgmy_parity_tight_after_c4_widening(Y):
    from models.levy import cgmy_price
    c = cgmy_price(100, 100, 1.0, 0.05, 0.1, 5, 5, Y, 0.0, "call")["price"]
    p = cgmy_price(100, 100, 1.0, 0.05, 0.1, 5, 5, Y, 0.0, "put")["price"]
    assert c - p == pytest.approx(100 - 100 * np.exp(-0.05), abs=1e-5)


def test_cgmy_promoted_and_deprecations():
    from models import registry as R
    assert R.MODEL_REGISTRY["cgmy"]["status"].value in ("Approximation", "Validated")
    assert "DEPRECATED" in R.MODEL_REGISTRY["cva_dva"]["notes"]
    assert "DEPRECATED" in R.MODEL_REGISTRY["cln_ftd"]["notes"]


# ══════════════════════ Part 2: real-data migration ══════════════════════

def test_commodity_real_data_path():
    """Schwartz-Smith calibrates to the live MOEX-FORTS futures strip when the
    market DB is present; otherwise the path degrades gracefully."""
    from app.runtime import market_service, active_snapshot, is_live
    ms = market_service()
    if not is_live():
        pytest.skip("no live market DB in this environment")
    curve = ms.get_commodity_curve("BR", active_snapshot(ms))
    if len(curve) < 3:
        pytest.skip("no BR futures strip in snapshot")
    assert all(t > 0 and px > 0 for t, px in curve.items())
    from services.pricing_service import PricingService
    res = PricingService().calibrate_commodity_from_market("BR")
    assert res.get("errors", []) == [] and res["rmse"] < 0.05
