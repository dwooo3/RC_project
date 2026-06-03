"""
Russian yield curve data and construction.

OFZ (Облигации федерального займа) — Russian Government Bonds
RUONIA — Ruble Overnight Index Average (≈ SOFR/EONIA for RUB)
Key rate — CBR (Центральный банк России) policy rate
MOEX curve — Moscow Exchange G-curve (government bond yield curve)

Data is entered manually (MOEX ISS integration pending).
Typical tenor structure for Russia: O/N, 1W, 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y
"""

import numpy as np
from curves.yield_curve import YieldCurve, NSCurve, SvenssonCurve, rate_to_df


# ─────────────────────────────────────────────────────────
# Default OFZ curve (approximate market levels as of mid-2025)
# G-curve published by MOEX daily
# ─────────────────────────────────────────────────────────

OFZ_TENORS_DEFAULT = [0.083, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0]
OFZ_RATES_DEFAULT  = [0.155, 0.152, 0.148, 0.145, 0.138, 0.133, 0.127, 0.123, 0.120, 0.118, 0.117]

# RUONIA OIS curve (overnight compound)
RUONIA_TENORS_DEFAULT = [0.003, 0.083, 0.25, 0.5, 1.0, 2.0, 3.0]
RUONIA_RATES_DEFAULT  = [0.158, 0.156, 0.153, 0.150, 0.147, 0.140, 0.135]

# CBR Key Rate
CBR_KEY_RATE_DEFAULT = 0.21   # 21% as of late 2024

# Indicative corporate spreads over OFZ (1st tier, 2nd tier, HY)
CORP_SPREAD_1T = [0.005, 0.007, 0.010, 0.015, 0.020, 0.025, 0.030, 0.035, 0.040, 0.045, 0.050]
CORP_SPREAD_2T = [0.015, 0.020, 0.025, 0.035, 0.045, 0.055, 0.065, 0.075, 0.085, 0.095, 0.105]
CORP_SPREAD_HY = [0.040, 0.055, 0.070, 0.090, 0.110, 0.130, 0.150, 0.170, 0.190, 0.210, 0.230]


def make_ofz_curve(tenors=None, rates=None, method="cubic",
                   label="OFZ G-curve") -> YieldCurve:
    """Build OFZ zero curve from par yield inputs."""
    tenors = tenors or OFZ_TENORS_DEFAULT
    rates  = rates  or OFZ_RATES_DEFAULT
    return YieldCurve(tenors, rates, label=label, interp=method)


def make_ruonia_curve(tenors=None, rates=None,
                      label="RUONIA OIS") -> YieldCurve:
    tenors = tenors or RUONIA_TENORS_DEFAULT
    rates  = rates  or RUONIA_RATES_DEFAULT
    return YieldCurve(tenors, rates, label=label)


def make_corporate_curve(base_curve: YieldCurve,
                         tier: str = "1st",
                         custom_spread_bps: float = None,
                         label: str = None) -> YieldCurve:
    """Build corporate curve = OFZ + credit spread."""
    spreads = {"1st": CORP_SPREAD_1T, "2nd": CORP_SPREAD_2T, "HY": CORP_SPREAD_HY}
    if custom_spread_bps is not None:
        sp = [custom_spread_bps/10000] * len(OFZ_TENORS_DEFAULT)
    else:
        sp = spreads.get(tier, CORP_SPREAD_1T)
    new_rates = [base_curve.rate(T) + s
                 for T, s in zip(OFZ_TENORS_DEFAULT, sp)]
    return YieldCurve(OFZ_TENORS_DEFAULT, new_rates,
                      label=label or f"Corp {tier}")


def fit_gcurve_ns(market_tenors: list, market_yields: list) -> NSCurve:
    """Fit Nelson-Siegel to MOEX G-curve market data."""
    return NSCurve.fit(market_tenors, market_yields, label="OFZ NS")


def fit_gcurve_svensson(market_tenors: list, market_yields: list) -> SvenssonCurve:
    """Fit Svensson to MOEX G-curve market data."""
    return SvenssonCurve.fit(market_tenors, market_yields, label="OFZ Svensson")


# ─────────────────────────────────────────────────────────
# Russian OFZ bond pricing
# ─────────────────────────────────────────────────────────

def price_ofz(face: float, coupon_rate: float, maturity: float,
              freq: int, curve: YieldCurve,
              accrued_days: int = 0, day_count: int = 365) -> dict:
    """
    Price OFZ bond.
    Russian OFZ use 30/360 for coupon calculation.
    Returns dirty price, clean price, accrued interest, YTM, duration.
    """
    from instruments.fixed_income import fixed_bond
    res = fixed_bond(face, coupon_rate, maturity, freq, curve)

    dt       = 1.0 / freq
    coupon   = face * coupon_rate / freq
    accrued  = coupon * accrued_days / (day_count / freq)
    clean    = res["price"] - accrued

    return dict(
        dirty_price  = res["price"],
        clean_price  = clean,
        accrued      = accrued,
        ytm          = res["ytm"],
        ytm_pct      = res["ytm"] * 100,
        mac_duration = res["mac_duration"],
        mod_duration = res["mod_duration"],
        convexity    = res["convexity"],
        dv01         = res["dv01"],
        zspread      = res.get("zspread", 0),
    )


# ─────────────────────────────────────────────────────────
# RUONIA fixing history (placeholder for ISS integration)
# ─────────────────────────────────────────────────────────

def ruonia_compounded(fixing_series: list, days: int) -> float:
    """
    Compound RUONIA overnight fixings over 'days' calendar days.
    fixing_series: list of daily RUONIA rates (annualized, continuous).
    """
    if not fixing_series:
        return 0.0
    product = 1.0
    for r in fixing_series[-days:]:
        product *= (1 + r/365)
    return (product - 1) * 365 / days


# ─────────────────────────────────────────────────────────
# Curve scenarios (Russian market relevant)
# ─────────────────────────────────────────────────────────

RUSSIAN_CURVE_SCENARIOS = {
    "CBR rate hike +200bp":  {"shift": +200, "twist": 0},
    "CBR rate hike +100bp":  {"shift": +100, "twist": 0},
    "CBR rate cut -100bp":   {"shift": -100, "twist": 0},
    "CBR rate cut -200bp":   {"shift": -200, "twist": 0},
    "Steepener +50bp 10Y":   {"shift": 0,    "twist": +50},
    "Flattener -50bp 10Y":   {"shift": 0,    "twist": -50},
    "2022 March shock":      {"shift": +1500, "twist": -100},
    "2024 Normalisation":    {"shift": -300,  "twist": +50},
    "Geopolitical stress":   {"shift": +500,  "twist": +100},
    "Risk-off flight":       {"shift": +300,  "twist": -50},
}


def apply_curve_scenario(curve: YieldCurve, scenario: str) -> YieldCurve:
    """Apply a named scenario shift to a curve."""
    sc = RUSSIAN_CURVE_SCENARIOS.get(scenario)
    if sc is None:
        return curve
    shift = sc["shift"] / 10000
    twist = sc["twist"] / 10000
    new_rates = []
    for T, r in zip(curve.tenors, curve.zero_rates):
        # Twist: linear from 0 at short end to twist at 10Y
        t_factor = min(T / 10.0, 1.0)
        new_rates.append(r + shift + twist * t_factor)
    return YieldCurve(curve.tenors, new_rates,
                      label=f"{curve.label} [{scenario}]")
