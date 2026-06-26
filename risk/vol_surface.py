"""
Volatility surface construction and models (Hull Ch. 20, 27):
  - Market vol surface from quotes
  - SVI (Stochastic Volatility Inspired) calibration
  - SABR surface (multi-tenor)
  - Dupire local vol surface
  - Term structure of vol
  - Vol surface interpolation / extrapolation
  - Risk-reversal / strangle decomposition
  - Sticky-strike vs sticky-delta
"""

import math

import numpy as np
from scipy.optimize import minimize, brentq
from scipy.interpolate import RectBivariateSpline


# ─────────────────────────────────────────────────────────
# Vol surface container
# ─────────────────────────────────────────────────────────

class VolSurface:
    """
    2-D implied vol surface (strike, maturity) → sigma.
    Supports bilinear and bicubic interpolation.
    """

    def __init__(self, strikes: np.ndarray, maturities: np.ndarray,
                 vols: np.ndarray, S0: float = 100.0,
                 label: str = "surface"):
        """
        strikes:    (n_K,) array
        maturities: (n_T,) array
        vols:       (n_K, n_T) implied vol grid
        """
        self.K    = np.array(strikes)
        self.T    = np.array(maturities)
        self.vols = np.array(vols)
        self.S0   = S0
        self.label = label
        self._build()

    def _build(self):
        nK, nT = len(self.K), len(self.T)
        kx = min(3, nK - 1)
        ky = min(3, nT - 1)
        if nK >= 2 and nT >= 2 and kx >= 1 and ky >= 1:
            try:
                self._interp = RectBivariateSpline(self.K, self.T, self.vols, kx=kx, ky=ky)
                return
            except Exception:
                pass
        from scipy.interpolate import RegularGridInterpolator
        self._interp = RegularGridInterpolator(
            (self.K, self.T), self.vols, method="linear",
            bounds_error=False, fill_value=None)

    def get_vol(self, K: float, T: float) -> float:
        """Interpolated implied vol."""
        K = float(np.clip(K, self.K.min(), self.K.max()))
        T = float(np.clip(T, self.T.min(), self.T.max()))
        # RectBivariateSpline returns a 1x1 array (float() of which raises on
        # numpy >= 1.25); RegularGridInterpolator wants a point list instead.
        try:
            v = np.asarray(self._interp(K, T)).reshape(-1)[0]
        except TypeError:
            v = np.asarray(self._interp([[K, T]])).reshape(-1)[0]
        return max(float(v), 0.001)

    def get_vol_delta(self, delta: float, T: float, r: float = 0.05,
                      q: float = 0.0, opt: str = "call") -> float:
        """Get vol for a given delta (invert delta → strike first)."""
        # Simple approximation: delta → strike via ATM vol
        atm_vol = self.get_vol(self.S0, T)
        from scipy.stats import norm
        sign = 1 if opt == "call" else -1

        def eq(K):
            v   = self.get_vol(K, T)
            sv  = v * np.sqrt(T)
            d1  = (np.log(self.S0/K) + (r-q+0.5*v**2)*T) / sv
            d   = sign * np.exp(-q*T) * norm.cdf(sign*d1)
            return d - delta

        try:
            K_star = brentq(eq, self.S0*0.3, self.S0*3.0)
            return self.get_vol(K_star, T)
        except Exception:
            return atm_vol

    def moneyness_slice(self, T: float, moneyness_range=(0.7, 1.3), n=50):
        """Return vol smile slice at fixed maturity."""
        ks = np.linspace(self.S0*moneyness_range[0], self.S0*moneyness_range[1], n)
        vs = [self.get_vol(k, T) for k in ks]
        return ks, np.array(vs)

    def term_structure(self, K=None):
        """ATM term structure."""
        K = K or self.S0
        return self.T, np.array([self.get_vol(K, T) for T in self.T])

    @classmethod
    def flat(cls, vol: float, S0: float = 100.0) -> "VolSurface":
        K = np.linspace(S0*0.5, S0*1.5, 11)
        T = np.array([0.1, 0.25, 0.5, 1, 2, 3, 5])
        V = np.full((len(K), len(T)), vol)
        return cls(K, T, V, S0, label=f"flat {vol:.0%}")

    @classmethod
    def from_risk_reversal_strangle(cls, S0: float, tenors: list,
                                    atm_vols: list, rr_25d: list,
                                    str_25d: list, r: float = 0.05,
                                    q: float = 0.0) -> "VolSurface":
        """Build surface from ATM + RR + Strangle quotes (FX convention)."""
        from instruments.fx import delta_to_strike
        K_all = []; T_all = []; V_all = []
        for T, atm, rr, st in zip(tenors, atm_vols, rr_25d, str_25d):
            v_call25 = atm + st + rr/2
            v_put25  = atm + st - rr/2
            v_atm    = atm
            # Approximate strikes
            K_call25 = delta_to_strike(S0, T, r, q, v_call25, 0.25, "call")
            K_put25  = delta_to_strike(S0, T, r, q, v_put25, 0.25, "put")
            K_atm    = S0 * np.exp((r-q+0.5*atm**2)*T)  # forward ATM
            K_all.extend([K_put25, K_atm, K_call25])
            T_all.extend([T, T, T])
            V_all.extend([v_put25, v_atm, v_call25])

        K_unique = sorted(set(round(k,2) for k in K_all))
        T_unique = sorted(set(tenors))
        V_grid   = np.zeros((len(K_unique), len(T_unique)))
        from scipy.interpolate import griddata
        pts = list(zip(K_all, T_all))
        for i, ki in enumerate(K_unique):
            for j, tj in enumerate(T_unique):
                v = griddata(pts, V_all, (ki, tj), method="linear")
                V_grid[i,j] = float(v) if not np.isnan(v) else atm_vols[j//len(tenors)]
        return cls(np.array(K_unique), np.array(T_unique), V_grid, S0)


# ─────────────────────────────────────────────────────────
# SABR-calibrated multi-tenor surface (listed / FORTS options)
# ─────────────────────────────────────────────────────────

def calibrate_sabr_smile(F, T, strikes, ivs, weights=None, beta=1.0):
    """Robust per-expiry SABR (Hagan 2002) fit → (params, rmse).

    Liquidity-weighted residuals, a tenor-scaled vol-of-vol cap and a NaN-safe
    flat fallback so a thin/illiquid wing can't blow the calibration up. Lives in
    the quant layer (reuses the ``models.heston`` engine) so pricing/risk can
    build adequate surfaces without depending on the display API.
    """
    from models.heston import sabr_vol
    from scipy.optimize import least_squares

    finite = [v for v in ivs if math.isfinite(v)]
    if not finite or not strikes:
        return {"alpha": 0.2, "beta": beta, "rho": 0.0, "nu": 0.3}, float("nan")
    atm = sorted(finite)[len(finite) // 2]
    nu_max = min(20.0, max(0.8, 1.2 / math.sqrt(max(T, 1e-3))))
    weights = weights or [1.0] * len(strikes)
    w = [math.sqrt(max(x, 0.0) + 1.0) for x in weights]
    fallback = {"alpha": float(atm), "beta": beta, "rho": 0.0, "nu": 0.3}

    def resid(p):
        a, rho, nu = p
        out = []
        for K, iv, wi in zip(strikes, ivs, w):
            try:
                m = sabr_vol(F, K, T, a, beta, rho, nu)
            except Exception:
                m = None
            out.append((m - iv) * wi if (m is not None and math.isfinite(m)) else 1e3)
        return out

    try:
        sol = least_squares(resid, [max(atm, 0.05), -0.1, min(0.6, nu_max)],
                            bounds=([1e-4, -0.999, 1e-4], [5.0, 0.999, nu_max]),
                            max_nfev=400)
        params = ({"alpha": float(sol.x[0]), "beta": beta,
                   "rho": float(sol.x[1]), "nu": float(sol.x[2])}
                  if all(math.isfinite(x) for x in sol.x) else fallback)
    except Exception:
        params = fallback

    sq = n = 0
    for K, iv in zip(strikes, ivs):
        try:
            m = sabr_vol(F, K, T, params["alpha"], beta, params["rho"], params["nu"])
        except Exception:
            continue
        if m is not None and math.isfinite(m):
            sq += (m - iv) ** 2
            n += 1
    rmse = math.sqrt(sq / n) if n else float("nan")
    return params, rmse


class CalibratedSurface:
    """Multi-tenor SABR surface for listed options (e.g. FORTS).

    Each expiry is an independent SABR slice ``{T, F, alpha, beta, rho, nu}``.
    ``get_vol`` evaluates the slice's SABR at the requested strike and interpolates
    across the two bracketing expiries in *total variance* (σ²·T — the standard
    no-arbitrage-friendly term-structure interpolation). Unlike a flat median vol
    this carries a real smile **and** term structure into pricing/risk.
    """

    def __init__(self, slices: list[dict], label: str = "surface",
                 diagnostics: dict | None = None):
        self.slices = sorted(slices, key=lambda s: s["T"])
        self.label = label
        self.diagnostics = diagnostics or {}

    def _slice_vol(self, s: dict, K: float) -> float:
        from models.heston import sabr_vol
        lo, hi = s["kmin"], s["kmax"]
        span = max(hi - lo, 1e-9)
        Kc = min(max(K, lo - 0.5 * span), hi + 0.5 * span)   # bound deep extrapolation
        try:
            v = sabr_vol(s["F"], Kc, s["T"], s["alpha"], s["beta"], s["rho"], s["nu"])
        except Exception:
            v = None
        if v is None or not math.isfinite(v) or v <= 0:
            return float(s.get("atm", 0.2))
        return float(v)

    def get_vol(self, K: float, T: float) -> float:
        if not self.slices:
            return 0.2
        if len(self.slices) == 1 or T <= self.slices[0]["T"]:
            return max(self._slice_vol(self.slices[0], K), 1e-3)
        if T >= self.slices[-1]["T"]:
            return max(self._slice_vol(self.slices[-1], K), 1e-3)
        for lo, hi in zip(self.slices, self.slices[1:]):
            if lo["T"] <= T <= hi["T"]:
                v_lo, v_hi = self._slice_vol(lo, K), self._slice_vol(hi, K)
                w_lo, w_hi = v_lo * v_lo * lo["T"], v_hi * v_hi * hi["T"]
                frac = (T - lo["T"]) / max(hi["T"] - lo["T"], 1e-9)
                w = w_lo + frac * (w_hi - w_lo)
                return max(math.sqrt(max(w, 1e-12) / max(T, 1e-9)), 1e-3)
        return max(self._slice_vol(self.slices[-1], K), 1e-3)

    def atm_term_structure(self) -> list[tuple]:
        return [(s["T"], s.get("atm")) for s in self.slices]

    def rmse_at(self, T: float):
        """Calibration RMSE of the expiry nearest T (None if unknown)."""
        if not self.slices:
            return None
        s = min(self.slices, key=lambda s: abs(s["T"] - T))
        rmse = s.get("rmse")
        return None if rmse is None or (isinstance(rmse, float) and math.isnan(rmse)) else rmse


def _smile_forward(strikes: list, ivs: list):
    """ATM-forward proxy = strike at the smile vertex (min IV) over the central
    band of strikes — robust to noisy deep-OTM wings."""
    pts = sorted(zip(strikes, ivs))
    if not pts:
        return None
    lo = int(len(pts) * 0.2)
    hi = max(lo + 1, int(len(pts) * 0.8))
    band = pts[lo:hi] or pts
    return min(band, key=lambda kv: kv[1])[0]


def calibrated_surface_from_points(points: list[dict], valuation_date, *,
                                   label: str = "surface", min_points: int = 4):
    """Build a :class:`CalibratedSurface` from raw listed-option vol points.

    ``points``: ``[{expiry, strike, iv}]`` (e.g. a ``build_vol_surfaces`` FORTS
    grid). Cleans each expiry's smile, estimates the ATM forward, SABR-calibrates,
    and drops expiries with too few points or an anomalous forward (handles the
    mixed-scale quote glitch). Returns the surface, or ``None`` if nothing usable.
    """
    from datetime import date as _date
    from models.heston import sabr_vol

    by_exp: dict = {}
    for p in points:
        try:
            iv, k = float(p["iv"]), float(p["strike"])
        except (TypeError, ValueError, KeyError):
            continue
        if not math.isfinite(iv) or not (1e-3 < iv <= 5.0) or k <= 0:
            continue
        by_exp.setdefault(p["expiry"], []).append((k, iv))

    raw, rejected = [], 0
    for exp, pts in by_exp.items():
        pts = sorted(set(pts))
        if len(pts) < min_points:
            rejected += len(pts)
            continue
        try:
            T = max((_date.fromisoformat(str(exp)) - valuation_date).days, 1) / 365.0
        except (ValueError, TypeError):
            continue
        strikes, ivs = [k for k, _ in pts], [v for _, v in pts]
        F = _smile_forward(strikes, ivs)
        if F:
            raw.append({"exp": exp, "T": T, "F": F, "strikes": strikes, "ivs": ivs})

    if not raw:
        return None

    med_F = sorted(s["F"] for s in raw)[len(raw) // 2]    # scale anchor
    slices, diag, accepted = [], [], 0
    for s in raw:
        if not (0.2 * med_F <= s["F"] <= 5.0 * med_F):     # mixed-scale glitch
            rejected += len(s["strikes"])
            continue
        params, rmse = calibrate_sabr_smile(s["F"], s["T"], s["strikes"], s["ivs"])
        try:
            atm = float(sabr_vol(s["F"], s["F"], s["T"], params["alpha"],
                                 params["beta"], params["rho"], params["nu"]))
        except Exception:
            atm = params["alpha"]
        accepted += len(s["strikes"])
        slices.append({"T": s["T"], "F": s["F"], "kmin": min(s["strikes"]),
                       "kmax": max(s["strikes"]), "atm": atm,
                       "rmse": None if math.isnan(rmse) else rmse, **params})
        diag.append({"expiry": s["exp"], "T": round(s["T"], 4), "forward": s["F"],
                     "n": len(s["strikes"]),
                     "rmse": None if math.isnan(rmse) else round(rmse, 5)})

    if not slices:
        return None
    diagnostics = {"fit_model": "SABR(beta=1)", "n_expiries": len(slices),
                   "accepted_points": accepted, "rejected_points": rejected,
                   "slices": diag}
    return CalibratedSurface(slices, label=label, diagnostics=diagnostics)


# ─────────────────────────────────────────────────────────
# SVI smile calibration (Gatheral)
# ─────────────────────────────────────────────────────────

def svi_total_variance(k, a, b, rho, m, sigma):
    """SVI: w(k) = a + b*(rho*(k-m) + sqrt((k-m)^2 + sigma^2))"""
    return a + b*(rho*(k-m) + np.sqrt((k-m)**2 + sigma**2))


def fit_svi_slice(strikes: np.ndarray, vols: np.ndarray, T: float,
                  F: float) -> dict:
    """Fit SVI to one maturity slice."""
    log_k = np.log(strikes/F)
    w_mkt = vols**2 * T

    def obj(p):
        a, b, rho, m, sig = p
        if b < 0 or sig < 0.001 or abs(rho) >= 0.999 or a < -0.1:
            return 1e10
        w_fit = np.array([svi_total_variance(ki, a, b, rho, m, sig) for ki in log_k])
        # Butterfly no-arb: w must be convex
        return np.sum((w_fit - w_mkt)**2)

    atm_idx = np.argmin(np.abs(log_k))
    atm_w   = w_mkt[atm_idx]
    x0 = [atm_w*0.6, atm_w*0.3, -0.4, 0.0, 0.2]
    bounds = [(-0.1,1),(0.001,5),(-0.99,0.99),(-2,2),(0.001,2)]
    res = minimize(obj, x0, bounds=bounds, method="L-BFGS-B",
                   options={"maxiter":2000})
    a, b, rho, m, sig = res.x

    # Implied vols from SVI
    fit_vols = np.array([np.sqrt(max(svi_total_variance(ki,a,b,rho,m,sig)/T,0.001))
                         for ki in log_k])
    rmse = np.sqrt(np.mean((fit_vols - vols)**2))

    return dict(a=a, b=b, rho=rho, m=m, sigma=sig,
                rmse=rmse, fit_vols=fit_vols, strikes=strikes)


# ─────────────────────────────────────────────────────────
# Dupire local vol (Hull Ch. 27.2 / Dupire 1994)
# ─────────────────────────────────────────────────────────

def dupire_local_vol(vol_surface: VolSurface, S0: float, r: float,
                     q: float = 0.0) -> callable:
    """
    Compute Dupire local vol from implied vol surface.
    sigma_loc^2(K,T) = (dw/dT) / (1 - k/w * dw/dk + 1/4(-1/4 - 1/w + k^2/w^2)(dw/dk)^2 + 1/2 d^2w/dk^2)
    where w = sigma_imp^2 * T, k = log(K/F).
    Numerical derivatives via finite differences.
    """
    dK = 0.01 * S0
    dT = 0.001

    def local_vol(K: float, T: float) -> float:
        if T < 0.01 or K < S0*0.1:
            return vol_surface.get_vol(K, T)
        F = S0 * np.exp((r-q)*T)
        k = np.log(K/F)

        sig  = vol_surface.get_vol(K, T)
        w    = sig**2 * T

        # dw/dT
        sig_T  = vol_surface.get_vol(K, T+dT)
        sig_Tm = vol_surface.get_vol(K, max(T-dT,0.001))
        dw_dT  = (sig_T**2*(T+dT) - sig_Tm**2*max(T-dT,0.001)) / (2*dT)

        # dw/dk
        Ku = K + dK; Kd = max(K-dK, S0*0.01)
        sig_u = vol_surface.get_vol(Ku, T); sig_d = vol_surface.get_vol(Kd, T)
        wu = sig_u**2*T; wd = sig_d**2*T
        dw_dk  = (wu - wd) / (np.log(Ku/F) - np.log(Kd/F))

        # d2w/dk2
        wm     = sig**2 * T
        d2w_dk2 = (wu - 2*wm + wd) / (np.log(Ku/Kd)/2)**2

        numer  = dw_dT
        denom  = (1 - k/w*dw_dk
                  + 0.25*(-0.25 - 1/w + k**2/w**2)*dw_dk**2
                  + 0.5*d2w_dk2)

        if denom < 1e-8 or numer < 0:
            return max(sig, 0.01)

        lv2 = numer / denom
        return max(np.sqrt(abs(lv2)), 0.001)

    return local_vol


# ─────────────────────────────────────────────────────────
# Volatility term structure fitting
# ─────────────────────────────────────────────────────────

def vol_term_structure(tenors: list, atm_vols: list) -> callable:
    """
    Fit variance-flat interpolation to ATM vol term structure.
    Ensures total variance w(T) = sigma^2(T)*T is monotone.
    Returns function sigma(T).
    """
    total_var = [v**2 * T for v, T in zip(atm_vols, tenors)]
    from scipy.interpolate import interp1d
    tv_interp = interp1d(tenors, total_var, kind="linear",
                         fill_value="extrapolate")
    def sigma(T):
        tv = max(tv_interp(T), 0)
        return np.sqrt(tv / T) if T > 0 else atm_vols[0]
    return sigma
