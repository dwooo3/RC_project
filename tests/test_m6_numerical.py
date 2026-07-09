"""
M6 — numerical methods. American analytic approximations (BAW, Bjerksund-
Stensland), Sobol quasi-Monte-Carlo, and a two-asset Douglas-ADI PDE. Each
validated against an independent reference: the binomial American lattice, the
Black-Scholes / geometric-Asian closed forms, and the Margrabe exchange formula.
"""
import warnings
import numpy as np
import pytest

from models.american_approx import baw, bjerksund_stensland
from models import qmc as Q
from models.adi import exchange_option_adi, margrabe, two_asset_adi
from models.black_scholes import bsm
from instruments.vanilla import american, european

warnings.filterwarnings("ignore")


# ══════════════════════ American approximations ══════════════════════

@pytest.mark.parametrize("approx", [baw, bjerksund_stensland])
@pytest.mark.parametrize("opt", ["call", "put"])
def test_american_approx_matches_binomial(approx, opt):
    S, K, T, r, sig, q = 100, 100, 0.5, 0.08, 0.25, 0.06
    for Sx in (80, 100, 120):
        ref = american(Sx, K, T, r, sig, q, opt, "binomial")["price"]
        assert approx(Sx, K, T, r, sig, q, opt) == pytest.approx(ref, rel=0.01, abs=0.08)


@pytest.mark.parametrize("approx", [baw, bjerksund_stensland])
def test_american_geq_european(approx):
    S, K, T, r, sig, q = 100, 100, 1.0, 0.06, 0.3, 0.04
    for opt in ("call", "put"):
        eu = european(S, K, T, r, sig, q, opt)["price"]
        assert approx(S, K, T, r, sig, q, opt) >= eu - 1e-9


@pytest.mark.parametrize("approx", [baw, bjerksund_stensland])
def test_no_dividend_call_is_european(approx):
    for Sx in (90, 100, 110):
        eu = european(Sx, 100, 1.0, 0.05, 0.3, 0.0, "call")["price"]
        assert approx(Sx, 100, 1.0, 0.05, 0.3, 0.0, "call") == pytest.approx(eu, rel=1e-6)


# ══════════════════════ Quasi-Monte-Carlo ══════════════════════

def test_qmc_european_matches_bs():
    bs = bsm(100, 100, 1.0, 0.05, 0.2, 0.0, "call").price
    qmc = Q.qmc_european(100, 100, 1.0, 0.05, 0.2, 0.0, "call", n=2**15)
    assert qmc == pytest.approx(bs, abs=5e-3)


def test_qmc_geometric_asian_matches_cf():
    cf = Q.geometric_asian_closed_form(100, 100, 1.0, 0.05, 0.2, 0.0, "call", m=12)
    qmc = Q.geometric_asian_qmc(100, 100, 1.0, 0.05, 0.2, 0.0, "call", m=12, n=2**14)
    assert qmc == pytest.approx(cf, abs=0.02)


def test_qmc_converges_faster_than_pseudo():
    bs = bsm(100, 100, 1.0, 0.05, 0.2, 0.0, "call").price
    N = 2**12
    qr = Q.rqmc_rmse(lambda n, seed: Q.qmc_european(100, 100, 1, 0.05, 0.2, 0, "call", n, seed),
                     bs, N, reps=12)
    pr = Q.rqmc_rmse(lambda n, seed: Q.pseudo_european(100, 100, 1, 0.05, 0.2, 0, "call", n, seed),
                     bs, N, reps=12)
    assert qr < pr / 5                                  # QMC RMSE at least 5x lower


# ══════════════════════ ADI two-asset PDE ══════════════════════

@pytest.mark.parametrize("rho", [-0.5, 0.0, 0.5])
def test_adi_exchange_matches_margrabe(rho):
    cf = margrabe(100, 100, 1.0, 0.02, 0.03, 0.25, 0.30, rho)
    adi = exchange_option_adi(100, 100, 1.0, 0.04, 0.02, 0.03, 0.25, 0.30, rho,
                              N1=100, N2=100, Nt=100)
    assert adi == pytest.approx(cf, rel=3e-3)


def test_adi_spread_zero_strike_is_exchange():
    cf = margrabe(100, 95, 1.0, 0.02, 0.03, 0.25, 0.30, 0.3)
    sp = two_asset_adi(lambda a, b: np.maximum(a - b, 0.0), 100, 95, 1.0, 0.04,
                       0.02, 0.03, 0.25, 0.30, 0.3, N1=90, N2=90, Nt=90)
    assert sp == pytest.approx(cf, rel=3e-3)


# ══════════════════════ M0 wiring + service ══════════════════════

def test_m6_wired():
    from models import taxonomy as tax
    from models import registry as R
    assert "baw" in tax.engines_for("american_option")
    assert "bjerksund_stensland" in tax.engines_for("american_option")
    assert "qmc" in tax.engines_for("european_option")
    assert "adi" in tax.engines_for("multi_asset_option")
    for mid in ("baw", "bjerksund_stensland", "qmc", "adi"):
        assert R.MODEL_REGISTRY[mid]["status"].value in ("Approximation", "Validated")
        assert tax.classify(mid)["asset_class"] in ("equity", "hybrid")


def test_m6_service_routes():
    from services.pricing_service import PricingService
    svc = PricingService()
    a = svc.price_american_option(100, 100, 1.0, 0.06, 0.3, 0.04, "put", "baw")
    assert a["errors"] == [] and a["value"] > 0 and a["model_id"] == "baw"
    bs = svc.price_american_option(100, 100, 1.0, 0.06, 0.3, 0.04, "put", "bjerksund_stensland")
    assert bs["errors"] == [] and bs["value"] > 0
    qm = svc.price_qmc_option(100, 100, 1.0, 0.05, 0.2, 0.0, "call", n=2**13)
    assert qm["errors"] == [] and qm["value"] > 0 and qm["model_id"] == "qmc"
    ad = svc.price_two_asset_option(100, 100, 1.0, 0.04, 0.02, 0.03, 0.25, 0.30, 0.3,
                                    N1=60, N2=60, Nt=60)
    assert ad["errors"] == [] and ad["value"] > 0 and ad["model_id"] == "adi"
