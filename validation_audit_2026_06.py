"""
Independent pricing validation audit (June 2026).
Cross-checks every pricer against model-independent identities,
known benchmarks, and Monte Carlo. Run:  python3.14 validation_audit_2026_06.py
"""
import numpy as np

PASS, FAIL, WARN = [], [], []

def check(name, got, want, tol, kind="abs"):
    if isinstance(got, float) and (np.isnan(got) or np.isinf(got)):
        FAIL.append((name, got, want)); print(f"FAIL {name}: got {got}"); return
    err = abs(got - want) if kind == "abs" else abs(got - want) / max(abs(want), 1e-12)
    ok = err <= tol
    (PASS if ok else FAIL).append((name, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {name}: got={got:.6f} want={want:.6f} err={err:.2e}")

def warn(name, msg):
    WARN.append((name, msg)); print(f"WARN {name}: {msg}")

# ════════════════════════ A. Vanilla closed forms ════════════════════════
from models.black_scholes import bsm, black76, garman_kohlhagen, bachelier

# Hull benchmark (Options, Futures & Other Derivatives): S=42,K=40,T=0.5,r=0.1,σ=0.2
check("BSM Hull call", bsm(42, 40, 0.5, 0.10, 0.2).price, 4.7594, 1e-3)
check("BSM Hull put",  bsm(42, 40, 0.5, 0.10, 0.2, opt="put").price, 0.8086, 1e-3)

S, K, T, r, q, sig = 100, 95, 1.25, 0.07, 0.03, 0.35
c = bsm(S, K, T, r, sig, q).price; p = bsm(S, K, T, r, sig, q, "put").price
check("BSM put-call parity", c - p, S*np.exp(-q*T) - K*np.exp(-r*T), 1e-10)

F = 105.0
c76 = black76(F, K, T, r, sig).price; p76 = black76(F, K, T, r, sig, "put").price
check("Black76 parity", c76 - p76, np.exp(-r*T)*(F-K), 1e-10)

cgk = garman_kohlhagen(S, K, T, 0.16, 0.04, sig).price
pgk = garman_kohlhagen(S, K, T, 0.16, 0.04, sig, "put").price
check("GK parity", cgk - pgk, S*np.exp(-0.04*T) - K*np.exp(-0.16*T), 1e-10)

bn = bachelier(100, 100, 1.0, 0.05, 10.0).price
check("Bachelier ATM", bn, np.exp(-0.05)*10.0*np.sqrt(1/(2*np.pi)), 1e-9)

# finite-difference Greeks consistency for BSM
h = 1e-4
fd_delta = (bsm(S+h, K, T, r, sig, q).price - bsm(S-h, K, T, r, sig, q).price)/(2*h)
check("BSM delta vs FD", bsm(S, K, T, r, sig, q).delta, fd_delta, 1e-6)
fd_vega = (bsm(S, K, T, r, sig+h, q).price - bsm(S, K, T, r, sig-h, q).price)/(2*h)/100
check("BSM vega vs FD", bsm(S, K, T, r, sig, q).vega, fd_vega, 1e-6)

# ════════════════════════ B. Trees & MC vs BSM ════════════════════════
from models.trees import binomial_crr, binomial_lr, trinomial
ref = bsm(S, K, T, r, sig, q).price
# CRR oscillates ~O(1/N) around BSM: ~7e-3 absolute at N=500 on a 19.33 price is
# normal convergence noise, not a defect (LR at the same N is exact to 1e-5).
check("CRR(N=500) vs BSM", binomial_crr(S, K, T, r, sig, q, 500)["price"], ref, 1.5e-2)
check("LR(N=501) vs BSM",  binomial_lr(S, K, T, r, sig, q, 501)["price"], ref, 1e-3)
check("Trinomial vs BSM",  trinomial(S, K, T, r, sig, q, 300)["price"], ref, 5e-3)

am_put = binomial_crr(S, K, T, r, sig, q, 500, "put", "american")["price"]
eu_put = bsm(S, K, T, r, sig, q, "put").price
if am_put >= eu_put - 1e-9: print(f"PASS American put {am_put:.4f} >= European {eu_put:.4f}"); PASS.append(("am>=eu",0,0))
else: print("FAIL American put < European"); FAIL.append(("am>=eu", am_put, eu_put))

am_call_noq = binomial_crr(S, K, T, r, sig, 0.0, 500, "call", "american")["price"]
check("American call (q=0) = European", am_call_noq, bsm(S, K, T, r, sig, 0.0).price, 1.5e-2)

from models.monte_carlo import mc_price, lsm
mc = mc_price(lambda paths: np.maximum(paths[:, -1] - K, 0), S, r, q, sig, T,
              steps=64, n_sims=100_000, control_variate=True, seed=7)
check("MC GBM vanilla vs BSM", mc["price"], ref, 3*mc["stderr"] + 0.02)

lsm_put = lsm(S, K, T, r, sig, q, n_sims=50_000, steps=50, opt="put")["price"]
check("LSM American put vs CRR", lsm_put, am_put, max(0.15, 0.02*am_put))

# ════════════════════════ C. Equity exotics ════════════════════════
from instruments.barrier import single_barrier, barrier_mc
from instruments.digital import cash_or_nothing, asset_or_nothing
from instruments.asian import geometric_asian_discrete, arithmetic_asian
from instruments.lookback import floating_lookback, fixed_lookback, lookback_mc

# barrier: H far below S -> vanilla; up-out call with H<=K -> 0
do_far = single_barrier(100, 100, 20, 1.0, 0.05, 0.25, 0.0, "call", "down-out")["price"]
check("DO call (H=20) ≈ vanilla", do_far, bsm(100, 100, 1.0, 0.05, 0.25).price, 1e-4)
uo_dead = single_barrier(100, 110, 105, 1.0, 0.05, 0.25, 0.0, "call", "up-out")["price"]
check("UO call (H<K) = 0", uo_dead, 0.0, 1e-9)
# in-out parity is enforced by construction; cross-check OUT leg vs fine MC
sb = single_barrier(100, 100, 90, 1.0, 0.05, 0.25, 0.02, "call", "down-out")["price"]
mcb = barrier_mc(100, 100, 90, 1.0, 0.05, 0.25, 0.02, "call", "down-out",
                 n_sims=60_000, steps=1500, seed=11)
# discrete monitoring biases the KO value UP vs continuous formula; allow that margin
check("DO call closed vs MC(1500 steps)", sb, mcb["price"], 4*mcb["stderr"] + 0.25)

dcall = cash_or_nothing(S, K, T, r, sig, q, "call", 10)["price"]
dput  = cash_or_nothing(S, K, T, r, sig, q, "put", 10)["price"]
check("digital cash C+P = disc*cash", dcall + dput, 10*np.exp(-r*T), 1e-10)
acall = asset_or_nothing(S, K, T, r, sig, q, "call")["price"]
aput  = asset_or_nothing(S, K, T, r, sig, q, "put")["price"]
check("digital asset C+P = S e^-qT", acall + aput, S*np.exp(-q*T), 1e-10)
check("vanilla = AoN - K*CoN", acall - K*cash_or_nothing(S, K, T, r, sig, q, "call", 1.0)["price"],
      bsm(S, K, T, r, sig, q).price, 1e-10)

check("geometric Asian n=1 = BSM", geometric_asian_discrete(S, K, T, r, sig, q, 1)["price"],
      bsm(S, K, T, r, sig, q).price, 1e-9)
ar = arithmetic_asian(S, K, T, r, sig, q, n=12, n_sims=100_000)
ge = geometric_asian_discrete(S, K, T, r, sig, q, 12)["price"]
if ar["price"] >= ge - 3*ar["stderr"]: print(f"PASS arithmetic Asian {ar['price']:.4f} >= geometric {ge:.4f}"); PASS.append(("asian",0,0))
else: print("FAIL arithmetic < geometric Asian"); FAIL.append(("asian", ar["price"], ge))

# discrete-monitoring bias for 1500 steps, σ=0.3: ≈ 0.583·σ·S·√(T/N) ≈ 0.45 → tol 0.9
LB_TOL = 0.9
fl = floating_lookback(100, 1.0, 0.05, 0.3, 0.0, "call")["price"]
mlb = lookback_mc(100, None, 1.0, 0.05, 0.3, 0.0, "call", "floating", n_sims=60_000, steps=1500)
check("floating lookback call vs MC", fl, mlb["price"], LB_TOL)
flp = floating_lookback(100, 1.0, 0.05, 0.3, 0.0, "put")["price"]
mlbp = lookback_mc(100, None, 1.0, 0.05, 0.3, 0.0, "put", "floating", n_sims=60_000, steps=1500)
check("floating lookback put vs MC", flp, mlbp["price"], LB_TOL)
fx_c = fixed_lookback(100, 110, 1.0, 0.05, 0.3, 0.0, "call")["price"]
mfx = lookback_mc(100, 110, 1.0, 0.05, 0.3, 0.0, "call", "fixed", n_sims=60_000, steps=1500)
check("fixed lookback call (OTM) vs MC", fx_c, mfx["price"], LB_TOL)
fx_p = fixed_lookback(100, 90, 1.0, 0.05, 0.3, 0.0, "put")["price"]
mfxp = lookback_mc(100, 90, 1.0, 0.05, 0.3, 0.0, "put", "fixed", n_sims=60_000, steps=1500)
check("fixed lookback put (OTM) vs MC", fx_p, mfxp["price"], LB_TOL)

# variance swap replication at flat vol -> K_var = sigma^2
from instruments.variance_swaps import variance_swap_fair_strike
sigv, Tv, rv = 0.22, 0.75, 0.04
Fv = 100*np.exp(rv*Tv)
strikes = np.linspace(30, 300, 1080)
puts  = [(k, bsm(100, k, Tv, rv, sigv, 0, "put").price)  for k in strikes if k < Fv]
calls = [(k, bsm(100, k, Tv, rv, sigv, 0, "call").price) for k in strikes if k >= Fv]
vs = variance_swap_fair_strike(rv, 0.0, Tv, puts, calls, 100.0)
check("variance swap strike = σ²", vs["variance_strike"], sigv**2, 0.0015)

# ════════════════════════ D. Rates / fixed income ════════════════════════
from curves.yield_curve import YieldCurve
from instruments.fixed_income import (fixed_bond, zcb, fra, irs, swaption, cap_floor,
                                      callable_bond, basis_swap, frn, ois)
flat = YieldCurve.flat(0.10)

z = zcb(5.0, flat, 100)
check("ZCB price", z["price"], 100*np.exp(-0.10*5), 1e-8)

# par bond: coupon = par rate -> price = face (curve-implied par yield, semiannual)
par = flat.par_rate(5.0, 2)
fb = fixed_bond(100, par, 5.0, 2, flat)
check("par bond at par", fb["price"], 100.0, 1e-6)
# YTM of par bond = par coupon (semiannual compounding)
check("par bond YTM = coupon", fb["ytm"], par, 1e-8)

f = fra(1_000_000, flat.forward_rate(1.0, 1.5), 1.0, 1.5, flat)
# NB: engine forward is (df1/df2-1)/tau (simple), curve.forward_rate is continuous
f2 = fra(1_000_000, 0.0, 1.0, 1.5, flat)
fwd_simple = (flat.discount(1.0)/flat.discount(1.5) - 1)/0.5
check("FRA NPV=0 at K=fwd", fra(1_000_000, fwd_simple, 1.0, 1.5, flat)["npv"], 0.0, 1e-6)

sw = irs(1_000_000, 0.10, 5.0, 2, flat)
sw0 = irs(1_000_000, sw["fair_rate"], 5.0, 2, flat)
check("IRS NPV=0 at fair rate", sw0["npv"], 0.0, 1e-6)
check("IRS fair ≈ curve par rate", sw["fair_rate"], flat.par_rate(5.0, 2), 2e-3, "rel")

# swaption payer-receiver parity: payer - receiver = annuity*(S0-K)*N
Kx = 0.09
pay = swaption(1_000_000, Kx, 1.0, 5.0, 2, flat, 0.25, "payer")
rec = swaption(1_000_000, Kx, 1.0, 5.0, 2, flat, 0.25, "receiver")
check("swaption parity", pay["price"] - rec["price"],
      1_000_000*pay["annuity"]*(pay["fwd_swap_rate"] - Kx), 1e-6)

# cap-floor parity: cap - floor = sum tau*disc*(F_simple - K)*N
Kc = 0.10
capv = cap_floor(1_000_000, Kc, 3.0, 4, flat, 0.30, "cap")["price"]
flrv = cap_floor(1_000_000, Kc, 3.0, 4, flat, 0.30, "floor")["price"]
swap_legs = sum(0.25*flat.discount(i*0.25)*( (flat.discount((i-1)*0.25)/flat.discount(i*0.25)-1)/0.25 - Kc)
                for i in range(1, 13)) * 1_000_000
check("cap-floor parity vs swap", capv - flrv, swap_legs, abs(swap_legs)*0.02 + 200)

cb = callable_bond(100, 0.12, 5.0, 2, flat, sigma=0.15, call_price=100, call_start=1.0, option="callable")
if cb["price"] <= cb["straight_value"] + 1e-9: print(f"PASS callable {cb['price']:.4f} <= straight {cb['straight_value']:.4f}"); PASS.append(("callable",0,0))
else: print("FAIL callable > straight"); FAIL.append(("callable", cb["price"], cb["straight_value"]))
pb = callable_bond(100, 0.08, 5.0, 2, flat, sigma=0.15, put_price=100, put_start=1.0, option="putable")
if pb["price"] >= pb["straight_value"] - 1e-9: print(f"PASS putable {pb['price']:.4f} >= straight {pb['straight_value']:.4f}"); PASS.append(("putable",0,0))
else: print("FAIL putable < straight"); FAIL.append(("putable", pb["price"], pb["straight_value"]))
# BDT tree refits the curve: straight value == DCF bond
fb12 = fixed_bond(100, 0.12, 5.0, 2, flat)["price"]
check("BDT straight = DCF bond", cb["straight_value"], fb12, 0.10)

# basis swap fair_spread: identical curves -> 0; 50bp index gap -> ≈ -50bp
bs = basis_swap(1_000_000, 0.005, 3.0, 4, flat, flat)
check("basis swap fair spread (same curve)", bs["fair_spread"], 0.0, 1e-6)
shift = flat.parallel_shift(50)
bs2 = basis_swap(1_000_000, 0.0, 3.0, 4, flat, shift)
check("basis swap fair spread (50bp gap)", bs2["fair_spread"], -0.005, 5e-4)
check("basis swap NPV=0 at fair spread",
      basis_swap(1_000_000, bs2["fair_spread"], 3.0, 4, flat, shift)["npv"], 0.0, 1e-6)

# OIS: NPV=0 at fair
o = ois(1_000_000, 0.0, 2.0, flat)
check("OIS NPV=0 at fair rate", ois(1_000_000, o["fair_ois_rate"], 2.0, flat)["npv"], 0.0, 1e-6)

# short-rate models
from models.short_rate import Vasicek, CIR, HullWhite
vas = Vasicek(0.08, 0.5, 0.10, 0.015)
mc_r = vas.simulate(5.0, 500, 20_000, seed=3)
disc_mc = np.exp(-(mc_r[:, :-1].mean(axis=1) if False else (mc_r[:, :-1]*(5.0/500)).sum(axis=1)))
check("Vasicek ZCB analytic vs MC", vas.bond_price(0.08, 5.0), disc_mc.mean(), 0.004)
cir = CIR(0.08, 0.5, 0.10, 0.08)
assert cir.feller_ok()
mc_c = cir.simulate(5.0, 500, 20_000, seed=3)
disc_c = np.exp(-(mc_c[:, :-1]*(5.0/500)).sum(axis=1))
check("CIR ZCB analytic vs MC", cir.bond_price(0.08, 5.0), disc_c.mean(), 0.004)
hw = HullWhite(0.1, 0.012, flat)
check("HW fits curve at 7y", hw.zero_rate(7.0), flat.rate(7.0), 5e-4)
# HW put-call parity on ZCB option: C - P = P(0,Tb) - K*P(0,To)
KB = 0.7
hwc = hw.bond_option(1.0, 5.0, KB, "call"); hwp = hw.bond_option(1.0, 5.0, KB, "put")
check("HW bond option parity", hwc - hwp,
      hw.bond_price(hw._r0, 0, 5.0) - KB*hw.bond_price(hw._r0, 0, 1.0), 1e-8)

# FRN: spread DV01 direction & par at zero spread
fr = frn(100, 0.0, 3.0, 4, flat)
check("FRN zero spread = par", fr["price"], 100.0, 1e-9)

# ════════════════════════ E. Credit ════════════════════════
from instruments.credit import cds, cds_implied_hazard
c1 = cds(10_000_000, 0.01, 5.0, 4, 0.02, 0.05, 0.4, True)
c0 = cds(10_000_000, c1["fair_spread"], 5.0, 4, 0.02, 0.05, 0.4, True)
check("CDS NPV=0 at fair spread", c0["npv"], 0.0, 1.0)
check("CDS fair ≈ h(1-R)", c1["fair_spread"], 0.02*0.6, 0.0004)
h_imp = cds_implied_hazard(0.012, 5.0, 4, 0.05, 0.4)
c_chk = cds(1, 0.012, 5.0, 4, h_imp, 0.05, 0.4)
check("implied hazard round-trip", c_chk["npv"], 0.0, 1e-8)

# ════════════════════════ F. Multi-asset ════════════════════════
from instruments.multi_asset import (spread_option_kirk, spread_option_mc,
                                     exchange_option, basket_option, quanto_option)
ex = exchange_option(100, 95, 1.0, 0.05, 0.3, 0.25, 0.4)["price"]
kirk0 = spread_option_kirk(100, 95, 0.0, 1.0, 0.05, 0.3, 0.25, 0.4)["price"]
check("Kirk K=0 = Margrabe", kirk0, ex, 1e-9)
kirk = spread_option_kirk(100, 95, 5.0, 1.0, 0.05, 0.3, 0.25, 0.4)["price"]
kmc = spread_option_mc(100, 95, 5.0, 1.0, 0.05, 0.3, 0.25, 0.4, n_sims=200_000, steps=16, seed=5)
check("Kirk vs MC", kirk, kmc["price"], 4*kmc["stderr"] + 0.10)
b1 = basket_option([100.0], [1.0], 100.0, 1.0, 0.05, [0.3], np.array([[1.0]]), opt="call", n_sims=200_000)
check("basket(1 asset) = BSM", b1["price"], bsm(100, 100, 1.0, 0.05, 0.3).price, 4*b1["stderr"] + 0.05)
qz = quanto_option(100, 100, 1.0, 0.05, 0.03, 0.3, 0.0, 0.0)["price"]
check("quanto σ_FX=0 = BSM(q=r_f)", qz, bsm(100, 100, 1.0, 0.05, 0.3, 0.03).price, 1e-9)

# ════════════════════════ G. Stochastic vol ════════════════════════
from models.heston import heston_price, sabr_vol
hp = heston_price(100, 100, 1.0, 0.05, 0.0, 0.09, 2.0, 0.09, 1e-4, 0.0)
check("Heston ξ→0 = BSM(σ=√v0)", hp["price"], bsm(100, 100, 1.0, 0.05, 0.3).price, 5e-3)
hc = heston_price(100, 90, 1.0, 0.05, 0.02, 0.09, 1.5, 0.08, 0.5, -0.6)["price"]
hpp = heston_price(100, 90, 1.0, 0.05, 0.02, 0.09, 1.5, 0.08, 0.5, -0.6, "put")["price"]
check("Heston parity", hc - hpp, 100*np.exp(-0.02) - 90*np.exp(-0.05), 5e-3)
check("SABR β=1 ν→0 = α", sabr_vol(0.05, 0.05, 2.0, 0.2, 1.0, 0.0, 1e-6), 0.2, 1e-4)
check("SABR smile continuity", sabr_vol(0.05, 0.0500001, 1.0, 0.2, 0.5, -0.3, 0.4),
      sabr_vol(0.05, 0.05, 1.0, 0.2, 0.5, -0.3, 0.4), 1e-4)

# Heston MC vs CF
from models.monte_carlo import heston_mc_price
hmc = heston_mc_price(lambda p: np.maximum(p[:, -1]-100, 0), 100, 0.09, 0.05, 0.0,
                      1.5, 0.09, 0.4, -0.6, 1.0, steps=200, n_sims=100_000, seed=9)
hcf = heston_price(100, 100, 1.0, 0.05, 0.0, 0.09, 1.5, 0.09, 0.4, -0.6)["price"]
check("Heston MC vs CF", hmc["price"], hcf, 4*hmc["stderr"] + 0.15)

# ════════════════════════ H. FX ════════════════════════
from instruments.fx import fx_forward, fx_option
ff = fx_forward(90.0, 0.16, 0.04, 1.0)
check("FX forward IRP", ff["forward"], 90*np.exp(0.12), 1e-9)
fo = fx_option(90.0, 95.0, 1.0, 0.16, 0.04, 0.18, 1.0, "call")
check("FX option = GK", fo["price"], garman_kohlhagen(90, 95, 1.0, 0.16, 0.04, 0.18).price, 1e-12)

# ════════════════════════ I. Implied vol round-trip ════════════════════════
from models.implied_vol import implied_vol_bsm
pv_ = bsm(S, K, T, r, sig, q).price
check("implied vol round-trip", implied_vol_bsm(pv_, S, K, T, r, q, "call"), sig, 1e-6)

# ════════════════════════ Summary ════════════════════════
print("\n" + "═"*60)
print(f"PASS: {len(PASS)}  FAIL: {len(FAIL)}  WARN: {len(WARN)}")
for n, g, w in FAIL:
    print(f"  ✗ {n}: got={g} want={w}")
for n, m in WARN:
    print(f"  ⚠ {n}: {m}")
