"""Offshore funding curves — USD (SOFR), EUR (€STR), CNY (CNH).

Pulls the published overnight rate + compounded averages from official free
sources (NY Fed for SOFR, ECB for €STR), which give a short curve (O/N → 6M-1Y);
the long end isn't freely available. CNH (offshore CNY) is built from SOFR plus
the USD/CNY forward carry implied by MOEX crosses (Si ÷ CNY futures), per the
covered-interest-parity construction r_cnh = r_usd + carry(USD/CNY).

Rates are bootstrapped to continuous zeros for the engine (DF = exp(-z·t)).
"""

from __future__ import annotations

import json
import urllib.request

# ECB €STR compounded-average ISINs → tenor in years (ACT/365).
_ESTR_AVG = {
    "EU000A2QQF16": 7.0 / 365,    # 1W
    "EU000A2QQF24": 30.0 / 365,   # 1M
    "EU000A2QQF32": 91.0 / 365,   # 3M
    "EU000A2QQF40": 182.0 / 365,  # 6M
    "EU000A2QQF57": 1.0,          # 12M
}
_ESTR_ON = "EU000A2X2A25"         # €STR O/N volume-weighted trimmed mean (WT)
_ON_T = 1.0 / 365


def _fetch(url: str, timeout: float = 20.0) -> str:
    from infra.certs import market_data_ssl_context
    req = urllib.request.Request(url, headers={"User-Agent": "RiskCalc/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=market_data_ssl_context()) as r:  # noqa: S310
        return r.read().decode("utf-8", errors="replace")


def fetch_sofr() -> list[tuple[float, float]]:
    """SOFR O/N + 30/90/180-day averages (NY Fed) → [(tenor_years, rate)]."""
    base = "https://markets.newyorkfed.org/api/rates/secured"
    pts: list[tuple[float, float]] = []
    on = json.loads(_fetch(f"{base}/sofr/last/1.json"))["refRates"][0].get("percentRate")
    if on is not None:
        pts.append((_ON_T, float(on) / 100.0))
    ai = json.loads(_fetch(f"{base}/sofrai/last/1.json"))["refRates"][0]
    for key, tenor in (("average30day", 30 / 365), ("average90day", 91 / 365),
                       ("average180day", 182 / 365)):
        if ai.get(key) is not None:
            pts.append((tenor, float(ai[key]) / 100.0))
    return sorted(pts)


def fetch_estr() -> list[tuple[float, float]]:
    """€STR O/N + compounded averages (ECB) → [(tenor_years, rate)]."""
    url = "https://data-api.ecb.europa.eu/service/data/EST?format=csvdata&lastNObservations=1&detail=dataonly"
    rows = _fetch(url).splitlines()
    if not rows:
        return []
    header = rows[0].split(",")
    try:
        ki, vi = header.index("KEY"), header.index("OBS_VALUE")
    except ValueError:
        return []
    pts: list[tuple[float, float]] = []
    for line in rows[1:]:
        cols = line.split(",")
        if len(cols) <= max(ki, vi):
            continue
        key, val = cols[ki], cols[vi]
        isin = key.split(".")[2] if len(key.split(".")) > 2 else ""
        try:
            rate = float(val) / 100.0
        except ValueError:
            continue
        if isin == _ESTR_ON and ".WT" in key:
            pts.append((_ON_T, rate))
        elif isin in _ESTR_AVG and key.endswith(".CR"):
            pts.append((_ESTR_AVG[isin], rate))
    return sorted(pts)


def build_offshore_curve(par_rates: list[tuple[float, float]]) -> list[tuple[float, float, float]]:
    """Bootstrap O/N + average rates → continuous-zero curve points."""
    from infra.curves_ois import bootstrap_ois
    if len(par_rates) < 2:
        return []
    return bootstrap_ois([t for t, _ in par_rates], [r for _, r in par_rates])
