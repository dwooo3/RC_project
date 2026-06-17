"""
Short rate models (Hull Ch. 31-32):
  - Vasicek
  - CIR (Cox-Ingersoll-Ross)
  - Hull-White (one-factor, extended Vasicek)
  - Black-Derman-Toy (BDT)
  - Black-Karasinski (BK)
  - Ho-Lee

Bond and bond option pricing from each model.
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq


# ─────────────────────────────────────────────────────────
# Vasicek model
# ─────────────────────────────────────────────────────────

class Vasicek:
    """
    dr = kappa(theta - r)dt + sigma dW
    Analytic bond prices, bond option prices.
    """
    def __init__(self, r0: float, kappa: float, theta: float, sigma: float):
        self.r0    = r0
        self.kappa = kappa
        self.theta = theta
        self.sigma = sigma

    def _AB(self, T: float):
        k, th, sig = self.kappa, self.theta, self.sigma
        if k == 0:
            B = T
            A = (sig**2 * T**3 / 6)
            return A, B
        B = (1 - np.exp(-k*T)) / k
        A = ((B - T)*(k**2*th - sig**2/2)/k**2 - sig**2*B**2/(4*k))
        return A, B

    def bond_price(self, r: float, T: float) -> float:
        A, B = self._AB(T)
        return np.exp(A - B*r)

    def zero_rate(self, T: float) -> float:
        if T < 1e-10:
            return self.r0
        P = self.bond_price(self.r0, T)
        return -np.log(P) / T

    def bond_option(self, T_opt: float, T_bond: float, K: float,
                    opt: str = "call") -> float:
        """European option on zero-coupon bond (Jamshidian)."""
        _, B_opt  = self._AB(T_opt)
        P_T  = self.bond_price(self.r0, T_opt)
        P_Tb = self.bond_price(self.r0, T_bond)
        sigma_p = self.sigma * np.sqrt((1-np.exp(-2*self.kappa*T_opt))/(2*self.kappa)) * B_opt
        if sigma_p < 1e-10:
            return max(P_Tb - K*P_T, 0) if opt=="call" else max(K*P_T - P_Tb, 0)
        h = np.log(P_Tb/(K*P_T))/sigma_p + sigma_p/2
        if opt == "call":
            return P_Tb*norm.cdf(h) - K*P_T*norm.cdf(h-sigma_p)
        else:
            return K*P_T*norm.cdf(-h+sigma_p) - P_Tb*norm.cdf(-h)

    def simulate(self, T: float, steps: int = 252, n_sims: int = 10_000,
                 seed: int = 42) -> np.ndarray:
        """Simulate short rate paths. Returns (n_sims, steps+1)."""
        rng = np.random.default_rng(seed)
        dt  = T / steps
        r   = np.full((n_sims, steps+1), self.r0)
        for i in range(steps):
            Z = rng.standard_normal(n_sims)
            dr = self.kappa*(self.theta - r[:,i])*dt + self.sigma*np.sqrt(dt)*Z
            r[:,i+1] = r[:,i] + dr
        return r

    def mean_reversion_half_life(self) -> float:
        return np.log(2) / self.kappa

    @property
    def long_run_vol(self) -> float:
        return self.sigma / np.sqrt(2 * self.kappa)


# ─────────────────────────────────────────────────────────
# CIR model
# ─────────────────────────────────────────────────────────

class CIR:
    """
    dr = kappa(theta - r)dt + sigma sqrt(r) dW
    Feller condition: 2*kappa*theta > sigma^2
    """
    def __init__(self, r0: float, kappa: float, theta: float, sigma: float):
        self.r0    = r0
        self.kappa = kappa
        self.theta = theta
        self.sigma = sigma

    def _ABh(self, T: float):
        k, th, sig = self.kappa, self.theta, self.sigma
        h = np.sqrt(k**2 + 2*sig**2)
        denom = 2*h + (k+h)*(np.exp(h*T)-1)
        B = 2*(np.exp(h*T)-1) / denom
        A = (2*h*np.exp((k+h)*T/2) / denom)**(2*k*th/sig**2)
        return A, B, h

    def bond_price(self, r: float, T: float) -> float:
        A, B, _ = self._ABh(T)
        return A * np.exp(-B*r)

    def zero_rate(self, T: float) -> float:
        if T < 1e-10:
            return self.r0
        return -np.log(self.bond_price(self.r0, T)) / T

    def feller_ok(self) -> bool:
        return 2*self.kappa*self.theta > self.sigma**2

    def simulate(self, T: float, steps: int = 252, n_sims: int = 10_000,
                 seed: int = 42) -> np.ndarray:
        rng = np.random.default_rng(seed)
        dt  = T / steps
        r   = np.full((n_sims, steps+1), self.r0)
        for i in range(steps):
            Z = rng.standard_normal(n_sims)
            r_pos = np.maximum(r[:,i], 0)
            dr = self.kappa*(self.theta - r_pos)*dt + self.sigma*np.sqrt(r_pos*dt)*Z
            r[:,i+1] = np.maximum(r[:,i] + dr, 0)
        return r


# ─────────────────────────────────────────────────────────
# Hull-White one-factor (extended Vasicek)
# ─────────────────────────────────────────────────────────

class HullWhite:
    """
    dr = [theta(t) - kappa*r]dt + sigma dW
    theta(t) calibrated to fit initial term structure exactly.
    """
    def __init__(self, kappa: float, sigma: float, curve):
        self.kappa = kappa
        self.sigma = sigma
        self.curve = curve  # YieldCurve for calibration

    def _B(self, T: float) -> float:
        return (1 - np.exp(-self.kappa*T)) / self.kappa

    def _inst_forward(self, t: float, dt: float = 1e-5) -> float:
        """
        Instantaneous forward rate f(0,t) = -d/dT ln P(0,T) | T=t,
        via a central finite difference. Hull-White's exact fit to the initial
        term structure requires the *instantaneous* forward, not the average
        forward (-ln P(0,t))/t that curve.forward_rate(0,t) returns.
        """
        t  = max(float(t), 0.0)
        lo = max(t - dt, 0.0)
        hi = t + dt
        return -(np.log(self.curve.discount(hi))
                 - np.log(self.curve.discount(lo))) / (hi - lo)

    @property
    def _r0(self) -> float:
        """Short-rate state r(0) = instantaneous forward f(0,0)."""
        return self._inst_forward(0.0)

    def _A(self, T: float) -> float:
        """Legacy/unused helper — the live curve reconstitution lives in bond_price()."""
        k, sig = self.kappa, self.sigma
        f0 = self._inst_forward(T)  # instantaneous forward (was average forward)
        B  = self._B(T)
        return (np.log(self.curve.discount(T))
                + B * f0
                - sig**2 * B**2 * (1 - np.exp(-2*k*T)) / (4*k))

    def bond_price(self, r: float, t: float, T: float) -> float:
        """P(t,T) given r(t), reconstituted from the initial curve (Hull-White)."""
        k, sig = self.kappa, self.sigma
        dt = T - t
        B  = (1 - np.exp(-k*dt)) / k
        # Affine reconstitution fitted to the initial curve:
        #   A(t,T) = P(0,T)/P(0,t) * exp(B f(0,t) - sigma^2/(4k)(1-e^{-2kt}) B^2)
        # f(0,t) MUST be the instantaneous forward at t. Using the average
        # forward over [t,T] broke the exact fit (P_HW(0,T) drifted up to ~9%
        # from the market curve at 10y). See Hull & White (1990).
        P0T = self.curve.discount(T)
        P0t = self.curve.discount(t) if t > 1e-8 else 1.0
        f0t = self._inst_forward(t)
        A   = (P0T/P0t) * np.exp(B*f0t - sig**2*B**2*(1-np.exp(-2*k*t))/(4*k))
        return A * np.exp(-B*r)

    def zero_rate(self, T: float) -> float:
        P  = self.bond_price(self._r0, 0, T)
        return -np.log(P) / T

    def bond_option(self, T_opt: float, T_bond: float, K: float,
                    opt: str = "call") -> float:
        """Analytic bond option under Hull-White."""
        k, sig = self.kappa, self.sigma
        self._B(T_opt)
        self._B(T_bond)
        P_T     = self.bond_price(self._r0, 0, T_opt)
        P_Tb    = self.bond_price(self._r0, 0, T_bond)
        sigma_p = sig * np.sqrt((1-np.exp(-2*k*T_opt))/(2*k)) * self._B(T_bond-T_opt)
        if sigma_p < 1e-10:
            return max(P_Tb - K*P_T, 0) if opt=="call" else max(K*P_T - P_Tb, 0)
        h = np.log(P_Tb/(K*P_T))/sigma_p + sigma_p/2
        if opt == "call":
            return P_Tb*norm.cdf(h) - K*P_T*norm.cdf(h-sigma_p)
        else:
            return K*P_T*norm.cdf(-h+sigma_p) - P_Tb*norm.cdf(-h)

    def swaption(self, notional: float, K: float, T_opt: float,
                 T_swap: float, freq: int = 2) -> dict:
        """Swaption price via Jamshidian decomposition."""
        dt      = 1.0 / freq
        periods = int(round(T_swap * freq))
        times   = [T_opt + i*dt for i in range(1, periods+1)]
        coupons = [K/freq * notional] * periods
        coupons[-1] += notional

        # Find r* such that sum of bond prices = notional
        def bond_sum(r_star):
            return sum(c * self.bond_price(r_star, T_opt, t)
                       for c, t in zip(coupons, times)) - notional

        try:
            r_star = brentq(bond_sum, -0.5, 2.0)
        except ValueError:
            r_star = self.curve.rate(T_opt)

        # Jamshidian: sum of bond options
        payer_price = sum(
            c * self.bond_option(T_opt, t, self.bond_price(r_star, T_opt, t), "put")
            for c, t in zip(coupons, times)
        )
        receiver_price = sum(
            c * self.bond_option(T_opt, t, self.bond_price(r_star, T_opt, t), "call")
            for c, t in zip(coupons, times)
        )
        return dict(payer=payer_price, receiver=receiver_price,
                    r_star=r_star, T_opt=T_opt, T_swap=T_swap)

    def simulate(self, T: float, steps: int = 252, n_sims: int = 10_000,
                 seed: int = 42) -> np.ndarray:
        rng = np.random.default_rng(seed)
        dt  = T / steps
        r0  = self.curve.rate(0.001)
        r   = np.full((n_sims, steps+1), r0)
        for i in range(steps):
            t_i = i * dt
            f   = self.curve.forward_rate(t_i, t_i+dt)
            dfdt = (self.curve.rate(t_i+dt) - self.curve.rate(max(t_i-dt,0.001))) / (2*dt)
            theta_t = dfdt + self.kappa*f + self.sigma**2*(1-np.exp(-2*self.kappa*t_i))/(2*self.kappa)
            Z = rng.standard_normal(n_sims)
            dr = (theta_t - self.kappa*r[:,i])*dt + self.sigma*np.sqrt(dt)*Z
            r[:,i+1] = r[:,i] + dr
        return r


# ─────────────────────────────────────────────────────────
# Ho-Lee model
# ─────────────────────────────────────────────────────────

class HoLee:
    """
    dr = theta(t)dt + sigma dW   (simplest no-arbitrage model)
    theta(t) = df(0,t)/dt + sigma^2 * t
    """
    def __init__(self, sigma: float, curve):
        self.sig   = sigma
        self.sigma = sigma
        self.curve = curve
        self.r0    = curve.rate(0.001)

    def bond_price(self, r: float, t: float, T: float) -> float:
        P0T = self.curve.discount(T)
        P0t = self.curve.discount(t) if t > 0 else 1.0
        f0t = self.curve.forward_rate(0, t)
        dt  = T - t
        return (P0T/P0t)*np.exp(-(r-f0t)*dt - 0.5*self.sig**2*t*dt**2)

    def zero_rate(self, T: float) -> float:
        r0 = self.curve.rate(0.001)
        P  = self.bond_price(r0, 0, T)
        return -np.log(max(P, 1e-12))/T

    def simulate(self, T: float, steps: int = 252, n_sims: int = 10_000,
                 seed: int = 42) -> np.ndarray:
        rng = np.random.default_rng(seed)
        dt  = T / steps
        r0  = self.curve.rate(0.001)
        r   = np.full((n_sims, steps+1), r0)
        for i in range(steps):
            t_i = i * dt
            dfdt = (self.curve.rate(t_i+dt) - self.curve.rate(max(t_i-dt, 0.001))) / (2*dt)
            theta_t = dfdt + self.sig**2 * t_i
            Z = rng.standard_normal(n_sims)
            r[:,i+1] = r[:,i] + theta_t*dt + self.sig*np.sqrt(dt)*Z
        return r


# ─────────────────────────────────────────────────────────
# Hull-White trinomial tree (Hull-White 1994) + Bermudan swaption (Phase 2)
# ─────────────────────────────────────────────────────────

class HullWhiteTree:
    """
    Two-stage Hull-White trinomial tree: OU process x with mean-reversion kappa
    and vol sigma on a clamped trinomial lattice (j_max), then time-dependent
    shifts alpha_i fitted to the initial discount curve via Arrow-Debreu prices.
    Node short rate r_ij = alpha_i + j*dx (the Δt-period rate).
    """

    def __init__(self, kappa: float, sigma: float, curve, T: float, steps: int = 200):
        self.kappa, self.sigma, self.curve = kappa, sigma, curve
        self.T, self.steps = float(T), int(steps)
        self.dt = self.T / self.steps
        self.dx = sigma * np.sqrt(3 * self.dt)
        self.j_max = max(1, int(np.ceil(0.184 / (kappa * self.dt))))
        self._build()

    def _branch_probs(self, j: int):
        """(moves, probs) at level j; clamped branching at ±j_max."""
        eta = self.kappa * j * self.dt
        if abs(j) < self.j_max:
            pu = 1/6 + (eta*eta - eta) / 2
            pm = 2/3 - eta*eta
            pd = 1/6 + (eta*eta + eta) / 2
            return (1, 0, -1), (pu, pm, pd)
        if j >= self.j_max:                      # downward branching: 0, -1, -2
            p0 = 7/6 + (eta*eta - 3*eta) / 2
            p1 = -1/3 + 2*eta - eta*eta
            p2 = 1/6 + (eta*eta - eta) / 2
            return (0, -1, -2), (p0, p1, p2)
        # j <= -j_max: upward branching: 0, +1, +2
        p0 = 7/6 + (eta*eta + 3*eta) / 2
        p1 = -1/3 - 2*eta - eta*eta
        p2 = 1/6 + (eta*eta + eta) / 2
        return (0, 1, 2), (p0, p1, p2)

    def _build(self):
        """Fit alpha_i so the tree reprices P(0, t_i) exactly (Arrow-Debreu).

        Calibrates one step PAST self.steps so short_rate(i, j) is defined at
        i == steps (needed when an exercise date sits on the tree horizon).
        """
        n, jm = self.steps + 1, self.j_max
        width = 2 * jm + 1                       # node index = j + jm
        self.alphas = np.zeros(n)
        Q = np.zeros(width)
        Q[jm] = 1.0                              # root
        self.Q = [Q.copy()]
        for i in range(n):
            P_next = self.curve.discount((i + 1) * self.dt)
            js = np.arange(-jm, jm + 1)
            mask = Q > 0
            denom = np.sum(Q[mask] * np.exp(-js[mask] * self.dx * self.dt))
            self.alphas[i] = (np.log(denom) - np.log(P_next)) / self.dt
            Q_next = np.zeros(width)
            for idx in np.where(mask)[0]:
                j = idx - jm
                r = self.alphas[i] + j * self.dx
                d = np.exp(-r * self.dt)
                moves, probs = self._branch_probs(j)
                for m, p in zip(moves, probs):
                    Q_next[idx + m] += Q[idx] * p * d
            Q = Q_next
            self.Q.append(Q.copy())

    def short_rate(self, i: int, j: int) -> float:
        return self.alphas[i] + j * self.dx

    def bond_price_at_node(self, i: int, j: int, T_bond: float) -> float:
        """Analytic HW zero-coupon bond P(t_i, T_bond) at the node's short rate."""
        hw = HullWhite(self.kappa, self.sigma, self.curve)
        return hw.bond_price(self.short_rate(i, j), i * self.dt, T_bond)

    def bermudan_swaption(self, notional: float, K: float, exercise_dates: list,
                          T_end: float, freq: int = 2, opt: str = "payer") -> dict:
        """
        Bermudan swaption: at each exercise date t_e the holder may enter a swap
        over [t_e, T_end] at fixed K. Swap value at a node uses the analytic HW
        reconstitution P(t, T; r). Exercise dates snap to the tree grid.
        A single exercise date reproduces the European (Jamshidian) price.
        """
        jm = self.j_max
        width = 2 * jm + 1
        dt_pay = 1.0 / freq
        ex_steps = sorted({min(self.steps, max(0, int(round(t / self.dt))))
                           for t in exercise_dates})
        last = max(ex_steps)
        hw = HullWhite(self.kappa, self.sigma, self.curve)
        sign = 1.0 if opt == "payer" else -1.0

        def intrinsic(i: int, j: int) -> float:
            t = i * self.dt
            r = self.short_rate(i, j)
            pay_times = []
            k = 1
            while t + k * dt_pay <= T_end + 1e-9:
                pay_times.append(t + k * dt_pay)
                k += 1
            if not pay_times:
                return 0.0
            annuity = sum(dt_pay * hw.bond_price(r, t, s) for s in pay_times)
            float_pv = 1.0 - hw.bond_price(r, t, pay_times[-1])
            swap = sign * (float_pv - K * annuity)
            return max(swap * notional, 0.0)

        V = np.zeros(width)
        for j in range(-jm, jm + 1):
            V[j + jm] = intrinsic(last, j)
        for i in range(last - 1, -1, -1):
            V_new = np.zeros(width)
            for j in range(-jm, jm + 1):
                moves, probs = self._branch_probs(j)
                cont = sum(p * V[j + jm + m] for m, p in zip(moves, probs))
                cont *= np.exp(-self.short_rate(i, j) * self.dt)
                V_new[j + jm] = max(cont, intrinsic(i, j)) if i in ex_steps else cont
            V = V_new
        return dict(price=V[jm], exercise_steps=ex_steps, opt=opt,
                    steps=self.steps, j_max=jm)


def bermudan_swaption_hw(notional: float, K: float, exercise_dates: list,
                         T_end: float, freq: int, curve,
                         kappa: float = 0.1, sigma: float = 0.012,
                         opt: str = "payer", steps: int = 200) -> dict:
    """Bermudan swaption via the Hull-White trinomial tree (Phase 2)."""
    tree = HullWhiteTree(kappa, sigma, curve, max(exercise_dates), steps)
    res = tree.bermudan_swaption(notional, K, exercise_dates, T_end, freq, opt)
    # European lower bound at the LAST exercise date via Jamshidian (analytic)
    hw = HullWhite(kappa, sigma, curve)
    t_last = max(exercise_dates)
    eu = hw.swaption(notional, K, t_last, T_end - t_last, freq)
    res["european_lower_bound"] = eu["payer"] if opt == "payer" else eu["receiver"]
    res["kappa"], res["sigma"] = kappa, sigma
    return res


# ─────────────────────────────────────────────────────────
# Calibration to the swaption cube (Stage A)
# ─────────────────────────────────────────────────────────

def _forward_swap_rate(curve, T_opt: float, T_swap: float, freq: int = 2):
    """(forward swap rate, annuity) for a swap starting at T_opt."""
    dt = 1.0 / freq
    times = [T_opt + i * dt for i in range(1, int(round(T_swap * freq)) + 1)]
    annuity = sum(dt * curve.discount(t) for t in times)
    S0 = (curve.discount(T_opt) - curve.discount(times[-1])) / annuity
    return S0, annuity


def black_swaption_price(notional: float, K: float, T_opt: float, T_swap: float,
                         freq: int, curve, sigma: float, opt: str = "payer") -> float:
    """Market-standard Black-76 swaption price (annuity numeraire)."""
    from models.black_scholes import black76
    S0, annuity = _forward_swap_rate(curve, T_opt, T_swap, freq)
    g = black76(S0, K, T_opt, 0.0, sigma, "call" if opt == "payer" else "put")
    return notional * annuity * g.price


def calibrate_hull_white(curve, cube, instruments: list, freq: int = 2,
                        notional: float = 1.0) -> dict:
    """
    Calibrate Hull-White (kappa, sigma) to ATM swaption prices off a
    SwaptionCube: market price = Black-76 with the cube's ATM vol, model
    price = Jamshidian payer at K = forward swap rate. Least squares on
    relative price errors over the instrument set [(T_opt, T_swap), ...].
    """
    from scipy.optimize import least_squares

    market = []
    for T_opt, T_swap in instruments:
        S0, _ = _forward_swap_rate(curve, T_opt, T_swap, freq)
        sigma_mkt = cube.atm_vol(T_opt, T_swap)
        market.append(black_swaption_price(notional, S0, T_opt, T_swap, freq,
                                           curve, sigma_mkt))

    def residuals(params):
        kappa, sigma = params
        if kappa <= 1e-4 or sigma <= 1e-6:
            return [1e3] * len(instruments)
        hw = HullWhite(kappa, sigma, curve)
        out = []
        for (T_opt, T_swap), mkt in zip(instruments, market):
            S0, _ = _forward_swap_rate(curve, T_opt, T_swap, freq)
            model = hw.swaption(notional, S0, T_opt, T_swap, freq)["payer"]
            out.append((model - mkt) / max(mkt, 1e-12))
        return out

    res = least_squares(residuals, x0=[0.05, 0.01],
                        bounds=([1e-4, 1e-6], [3.0, 0.5]))
    kappa, sigma = res.x
    table = []
    hw = HullWhite(kappa, sigma, curve)
    for (T_opt, T_swap), mkt in zip(instruments, market):
        S0, annuity = _forward_swap_rate(curve, T_opt, T_swap, freq)
        model = hw.swaption(notional, S0, T_opt, T_swap, freq)["payer"]
        table.append(dict(T_opt=T_opt, T_swap=T_swap, forward=S0,
                          market=mkt, model=model,
                          rel_error=(model - mkt) / max(mkt, 1e-12)))
    rmse = float(np.sqrt(np.mean([r["rel_error"] ** 2 for r in table])))
    return dict(kappa=float(kappa), sigma=float(sigma), rmse=rmse,
                instruments=table, converged=bool(res.success))


def bermudan_swaption_calibrated(notional: float, K: float, exercise_dates: list,
                                 T_end: float, freq: int, curve, cube,
                                 opt: str = "payer", steps: int = 200,
                                 calibration_instruments: list | None = None) -> dict:
    """
    Bermudan swaption with (kappa, sigma) calibrated to the cube's ATM
    co-terminal swaptions (each exercise date paired with the residual swap
    tenor) before pricing on the Hull-White tree — the market-standard
    co-terminal calibration for Bermudans.
    """
    instruments = calibration_instruments or [
        (t_e, T_end - t_e) for t_e in exercise_dates if T_end - t_e > 1e-9
    ]
    cal = calibrate_hull_white(curve, cube, instruments, freq)
    res = bermudan_swaption_hw(notional, K, exercise_dates, T_end, freq, curve,
                               cal["kappa"], cal["sigma"], opt, steps)
    res["calibration"] = cal
    return res
