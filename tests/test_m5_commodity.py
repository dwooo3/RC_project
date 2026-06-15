"""
M5 — two-factor commodity models. Identity-first: futures at τ=0 = spot, the
Schwartz-Smith ≡ Gibson-Schwartz equivalence (to machine precision — the
flagship cross-check of both closed forms), Monte-Carlo futures, futures-option
parity and the Samuelson vol decay; plus M0 wiring + service routing.
"""
import numpy as np
import pytest

from models.commodity import SchwartzSmith, GibsonSchwartz, commodity_futures_curve


@pytest.fixture(scope="module")
def gs():
    return GibsonSchwartz(spot=50, delta0=0.07, kappa=1.5, sigma_S=0.3,
                          alpha_tilde=0.05, sigma_delta=0.4, rho=0.3, r=0.05)


# ── basics ───────────────────────────────────────────────

def test_futures_at_zero_is_spot(gs):
    assert gs.futures(0.0) == pytest.approx(gs.spot, abs=1e-9)
    ss = SchwartzSmith(chi0=0.1, xi0=np.log(50) - 0.1)
    assert ss.futures(0.0) == pytest.approx(ss.spot, abs=1e-9)


# ── flagship: GS ≡ SS ────────────────────────────────────

def test_gs_ss_futures_equivalence(gs):
    ss = gs.to_schwartz_smith()
    for T in (0.25, 0.5, 1, 2, 3, 5, 7, 10):
        assert gs.futures(T) == pytest.approx(ss.futures(T), rel=1e-12), T


def test_gs_ss_option_equivalence(gs):
    ss = gs.to_schwartz_smith()
    for K in (45, 50, 55):
        for opt in ("call", "put"):
            assert gs.futures_option(1, 2, K, opt) == pytest.approx(
                ss.futures_option(1, 2, K, opt), rel=1e-12)


# ── MC ground truth ──────────────────────────────────────

def test_mc_matches_futures(gs):
    for T in (1, 3, 5):
        mc = gs.simulate_spot(T, n_sims=200_000, steps=300, seed=1)
        F = gs.futures(T)
        se = mc.std() / np.sqrt(len(mc))
        assert mc.mean() == pytest.approx(F, abs=4 * se)


def test_ss_option_vs_mc():
    ss = SchwartzSmith(chi0=0.0, xi0=np.log(50), kappa=1.5, sigma_chi=0.3,
                       mu_xi=0.0, sigma_xi=0.15, rho=0.2, r=0.05)
    To, Tf = 1.0, 2.0
    for K in (45, 50, 55):
        an = ss.futures_option(To, Tf, K, "call")
        rng = np.random.default_rng(2)
        k, sc, sx, rho = ss.kappa, ss.sigma_chi, ss.sigma_xi, ss.rho
        vchi = (1 - np.exp(-2 * k * To)) * sc**2 / (2 * k)
        vxi = sx**2 * To
        cov = (1 - np.exp(-k * To)) * rho * sc * sx / k
        Z = rng.standard_normal((300_000, 2)) @ np.linalg.cholesky([[vchi, cov], [cov, vxi]]).T
        chi = np.exp(-k * To) * ss.chi0 + Z[:, 0]
        xi = ss.xi0 + ss.mu_xi * To + Z[:, 1]
        F = np.exp(np.exp(-k * (Tf - To)) * chi + xi + ss._A(Tf - To))
        px = np.exp(-ss.r * To) * np.maximum(F - K, 0.0)
        se = px.std() / np.sqrt(len(px))
        assert an == pytest.approx(px.mean(), abs=4 * se), K


# ── option / vol structure ───────────────────────────────

def test_futures_option_parity(gs):
    ss = gs.to_schwartz_smith()
    To, Tf, K = 1.0, 2.0, 50
    c = ss.futures_option(To, Tf, K, "call")
    p = ss.futures_option(To, Tf, K, "put")
    df, F = np.exp(-ss.r * To), ss.futures(Tf)
    assert c - p == pytest.approx(df * (F - K), abs=1e-10)


def test_samuelson_vol_decay():
    """Short-term-dominant model: near futures more volatile; long end -> σ_ξ."""
    ss = SchwartzSmith(chi0=0.0, xi0=np.log(50), kappa=1.5, sigma_chi=0.4,
                       mu_xi=0.0, sigma_xi=0.05, rho=0.2, r=0.05)
    vols = [np.sqrt(ss.futures_log_var(0.5, Tf) / 0.5) for Tf in (0.5, 1, 2, 5, 10)]
    assert all(a > b for a, b in zip(vols, vols[1:]))
    assert vols[-1] == pytest.approx(ss.sigma_xi, abs=1e-3)


def test_contango_backwardation(gs):
    """Positive convenience yield above the risk-free drift -> backwardation front."""
    curve = commodity_futures_curve(gs, [0.25, 0.5, 1.0])
    assert curve[0.25] < gs.spot                       # front in backwardation


# ── M0 wiring + service ──────────────────────────────────

def test_commodity_wired():
    from models import taxonomy as tax
    from models import parameters as P
    from models import registry as R
    for mid in ("schwartz_smith", "gibson_schwartz"):
        assert tax.classify(mid)["asset_class"] == "commodity"
        assert R.MODEL_REGISTRY[mid]["status"].value == "Approximation"
    assert "schwartz_smith" in tax.engines_for("commodity_option")
    assert {"kappa", "sigma_chi", "rho"} <= {s.key for s in P.engine_params("schwartz_smith")}
    assert {"delta0", "sigma_delta"} <= {s.key for s in P.engine_params("gibson_schwartz")}


def test_commodity_service_routes():
    from services.pricing_service import PricingService
    svc = PricingService()
    for model in ("schwartz_smith", "gibson_schwartz"):
        opt = svc.price_commodity_option(model, 50, 50, 1.0, 2.0, "call")
        assert opt["errors"] == [] and opt["value"] > 0 and opt["model_id"] == model
        cur = svc.commodity_futures_curve(model, 50, [0.5, 1, 2, 5])
        assert cur["errors"] == [] and len(cur["curve"]) == 4
