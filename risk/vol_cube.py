"""
Rates volatility structures (Stage A): swaption cube and caplet vol strip.

SwaptionCube = ATM vol matrix (expiry × tenor) + optional SABR smile per node:
ATM queries interpolate bilinearly in (expiry, tenor); strike queries go
through the node's calibrated SABR smile (falling back to ATM when no smile
was quoted). CapletVolStrip is the single-tenor analogue keyed by expiry.

Both feed the rates pricers: Black-76 caps/swaptions get strike-aware vols,
Hull-White calibrates (kappa, sigma) to the cube's ATM prices, and CMS coupons
read the fixing-matched node vol.
"""

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import least_squares

from models.heston import sabr_vol


class _SABRSlice:
    """Calibrated SABR smile at one (expiry, tenor) node."""

    def __init__(self, F: float, T: float, alpha: float, beta: float,
                 rho: float, nu: float, rmse: float = 0.0):
        self.F, self.T = F, T
        self.alpha, self.beta, self.rho, self.nu = alpha, beta, rho, nu
        self.rmse = rmse

    def vol(self, K: float) -> float:
        return float(sabr_vol(self.F, max(K, 1e-6), self.T,
                              self.alpha, self.beta, self.rho, self.nu))

    @classmethod
    def calibrate(cls, F: float, T: float, strikes, vols,
                  beta: float = 0.5) -> "_SABRSlice":
        """
        Least-squares (alpha, rho, nu) fit with multi-start — the lab
        sabr_calibrate (single-start L-BFGS-B) leaves ~1e-3 vol rmse even on
        smiles generated exactly by SABR; cube calibration needs the exact
        round-trip.
        """
        strikes = np.asarray(strikes, dtype=float)
        vols = np.asarray(vols, dtype=float)
        atm_guess = float(vols[np.argmin(np.abs(strikes - F))]) * F ** (1 - beta)

        def resid(p):
            alpha, rho, nu = p
            return [sabr_vol(F, k, T, alpha, beta, rho, nu) - v
                    for k, v in zip(strikes, vols)]

        best = None
        for x0 in ([atm_guess, -0.2, 0.4], [atm_guess, 0.3, 0.8],
                   [atm_guess, -0.6, 1.5]):
            try:
                fit = least_squares(resid, x0,
                                    bounds=([1e-4, -0.999, 1e-3],
                                            [5.0, 0.999, 10.0]))
            except ValueError:
                continue
            if best is None or fit.cost < best.cost:
                best = fit
        if best is None:
            raise ValueError("SABR calibration failed for all starts")
        alpha, rho, nu = best.x
        rmse = float(np.sqrt(2 * best.cost / len(strikes)))
        return cls(F, T, float(alpha), beta, float(rho), float(nu), rmse)


class SwaptionCube:
    """
    ATM swaption vol matrix with optional per-node SABR smiles.
    expiries/tenors: 1-D grids (years); atm_vols: (n_expiry, n_tenor) lognormal.
    """

    def __init__(self, expiries, tenors, atm_vols, smiles: dict | None = None,
                 label: str = "swaption cube", metadata: dict | None = None):
        self.expiries = np.asarray(expiries, dtype=float)
        self.tenors = np.asarray(tenors, dtype=float)
        self.atm_vols = np.asarray(atm_vols, dtype=float)
        if self.atm_vols.shape != (self.expiries.size, self.tenors.size):
            raise ValueError("atm_vols must be (n_expiries, n_tenors)")
        if not np.all(np.isfinite(self.atm_vols)) or np.any(self.atm_vols <= 0):
            raise ValueError("atm_vols must be positive and finite")
        self.smiles = smiles or {}             # {(expiry, tenor): _SABRSlice}
        self.label = label
        self.metadata = metadata or {}
        self._interp = RegularGridInterpolator(
            (self.expiries, self.tenors), self.atm_vols,
            method="linear", bounds_error=False, fill_value=None)

    def atm_vol(self, expiry: float, tenor: float) -> float:
        e = float(np.clip(expiry, self.expiries[0], self.expiries[-1]))
        t = float(np.clip(tenor, self.tenors[0], self.tenors[-1]))
        return float(self._interp((e, t)))

    def _nearest_node(self, expiry: float, tenor: float):
        e = self.expiries[np.argmin(np.abs(self.expiries - expiry))]
        t = self.tenors[np.argmin(np.abs(self.tenors - tenor))]
        return (float(e), float(t))

    def vol(self, expiry: float, tenor: float, K: float | None = None,
            F: float | None = None) -> float:
        """
        Strike-aware vol: SABR smile at the nearest quoted node, recentered so
        the ATM level matches the bilinear ATM interpolation; ATM when no
        strike given or no smile calibrated.
        """
        atm = self.atm_vol(expiry, tenor)
        if K is None:
            return atm
        slice_ = self.smiles.get(self._nearest_node(expiry, tenor))
        if slice_ is None:
            return atm
        skew = slice_.vol(K) - slice_.vol(F if F is not None else slice_.F)
        return max(atm + skew, 1e-4)

    @classmethod
    def calibrate(cls, expiries, tenors, atm_vols, smile_quotes: dict,
                  forward_fn, beta: float = 0.5,
                  label: str = "swaption cube") -> "SwaptionCube":
        """
        smile_quotes: {(expiry, tenor): [(K, vol), ...]} market smiles;
        forward_fn(expiry, tenor) -> forward swap rate from the curve.
        """
        smiles = {}
        for (e, t), quotes in smile_quotes.items():
            F = forward_fn(e, t)
            ks = [q[0] for q in quotes]
            vs = [q[1] for q in quotes]
            smiles[(float(e), float(t))] = _SABRSlice.calibrate(F, e, ks, vs, beta)
        return cls(expiries, tenors, atm_vols, smiles, label=label,
                   metadata={"beta": beta,
                             "smile_nodes": sorted(smiles.keys())})


class CapletVolStrip:
    """
    Caplet vol term structure with optional SABR smile per expiry.
    Queries: vol(T) for ATM, vol(T, K, F) strike-aware.
    """

    def __init__(self, expiries, atm_vols, smiles: dict | None = None,
                 label: str = "caplet strip"):
        self.expiries = np.asarray(expiries, dtype=float)
        self.atm_vols = np.asarray(atm_vols, dtype=float)
        if self.expiries.size != self.atm_vols.size:
            raise ValueError("expiries and atm_vols must have the same length")
        # variance-flat interpolation in total variance keeps sigma(T) arbitrage-sane
        total_var = self.atm_vols**2 * self.expiries
        self._tv = lambda T: np.interp(T, self.expiries, total_var)
        self.smiles = smiles or {}             # {expiry: _SABRSlice}
        self.label = label

    def vol(self, T: float, K: float | None = None, F: float | None = None) -> float:
        T_c = float(np.clip(T, self.expiries[0], self.expiries[-1]))
        atm = float(np.sqrt(max(self._tv(T_c), 1e-12) / max(T_c, 1e-9)))
        if K is None:
            return atm
        e = float(self.expiries[np.argmin(np.abs(self.expiries - T))])
        slice_ = self.smiles.get(e)
        if slice_ is None:
            return atm
        skew = slice_.vol(K) - slice_.vol(F if F is not None else slice_.F)
        return max(atm + skew, 1e-4)

    @classmethod
    def calibrate(cls, expiries, atm_vols, smile_quotes: dict, forward_fn,
                  beta: float = 0.5, label: str = "caplet strip") -> "CapletVolStrip":
        """smile_quotes: {expiry: [(K, vol), ...]}; forward_fn(expiry) -> simple fwd."""
        smiles = {}
        for e, quotes in smile_quotes.items():
            F = forward_fn(e)
            ks = [q[0] for q in quotes]
            vs = [q[1] for q in quotes]
            smiles[float(e)] = _SABRSlice.calibrate(F, e, ks, vs, beta)
        return cls(expiries, atm_vols, smiles, label=label)
