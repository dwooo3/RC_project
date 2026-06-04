"""
Bank of Russia (CBR) client — RUONIA fixing and the key rate.

These reference rates are NOT published on MOEX ISS (ISS only lists RUONIA
futures), so per MOEX_MARKET_DATA_INTEGRATION_PROMPT.md §2/§9 they come from
cbr.ru. As with the ISS client, the HTTP fetch is injectable so parsing is
unit-testable without network.

⚠️ The exact CBR endpoint/payload must be confirmed on first live run. CBR exposes
the data via a SOAP service (KeyRate / Ruonia) and via daily XML/HTML pages; the
parser below is tolerant of a simple ``[{date, value}]`` records shape and of the
CBR SOAP XML so it can adapt without code churn.
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import date
from typing import Callable

CBR_BASE = "https://www.cbr.ru"


def _default_fetch(timeout: float) -> Callable[[str], str]:
    def fetch(url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "RiskCalc-CBR-Client/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")

    return fetch


def _to_float(text) -> float | None:
    if text is None:
        return None
    s = str(text).strip().replace(",", ".").replace("%", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_rate_records(payload: str) -> list[tuple[str, float]]:
    """
    Parse CBR rate records into ``[(date_iso, value_decimal), ...]``.

    Accepts either JSON (list of {date/Date/DT, value/Value/rate/R/ruo}) or CBR
    SOAP/XML rows with date + value attributes/elements. Percent -> decimal.
    """
    records: list[tuple[str, float]] = []

    # JSON form
    try:
        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("records", data.get("data", []))
        for row in rows or []:
            d = row.get("date") or row.get("Date") or row.get("DT") or row.get("dt")
            v = (row.get("value") if "value" in row else None)
            for key in ("value", "Value", "rate", "Rate", "R", "ruo", "KeyRate"):
                if key in row:
                    v = row[key]
                    break
            fv = _to_float(v)
            if d and fv is not None:
                records.append((str(d)[:10], fv / 100.0))
        if records:
            return records
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    # XML/SOAP form: per record, take the date and the first decimal value
    # (numeric text node ">15,30<" preferred, else a rate/value attribute).
    for chunk in re.findall(
        r"<[^>]*(?:Record|Ruonia|RUONIA|KR|element)[^>]*>.*?</[^>]+>", payload, re.S
    ):
        d = re.search(r"([0-9]{4}-[0-9]{2}-[0-9]{2})", chunk)
        v = re.search(r">\s*([0-9]+[.,][0-9]+)\s*<", chunk)
        if not v:
            v = re.search(r'(?:value|rate|ruo|R)\s*=?\s*["\s>]*([0-9]+[.,][0-9]+)', chunk, re.I)
        if d and v:
            fv = _to_float(v.group(1))
            if fv is not None:
                records.append((d.group(1), fv / 100.0))
    return records


class CbrClient:
    def __init__(self, fetch: Callable[[str], str] | None = None, *,
                 base_url: str = CBR_BASE, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self._fetch = fetch or _default_fetch(timeout)

    def get_key_rate(self, from_date: date, till_date: date | None = None) -> list[tuple[str, float]]:
        till_date = till_date or from_date
        url = f"{self.base_url}/scripts/XML_dynamic.asp?key_rate=1&from={from_date}&to={till_date}"
        return parse_rate_records(self._fetch(url))

    def get_ruonia(self, from_date: date, till_date: date | None = None) -> list[tuple[str, float]]:
        till_date = till_date or from_date
        url = f"{self.base_url}/hd_base/ruonia/?from={from_date}&to={till_date}"
        return parse_rate_records(self._fetch(url))
