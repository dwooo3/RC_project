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
    from infra.certs import market_data_ssl_context

    ctx = market_data_ssl_context()    # trusts the anti-DDoS proxy chain too

    def fetch(url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "RiskCalc-CBR-Client/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")

    return fetch


def _ddmmyyyy_to_iso(text: str) -> str | None:
    """'10.06.2026' -> '2026-06-10' (CBR hd_base date format)."""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", str(text).strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def parse_keyrate_html(html: str) -> list[tuple[str, float]]:
    """
    CBR hd_base/KeyRate HTML table: rows of <td>DD.MM.YYYY</td><td>14,50</td>.
    Returns [(iso_date, decimal_rate)] (percent -> decimal).
    """
    out: list[tuple[str, float]] = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)]
        if len(cells) >= 2:
            iso = _ddmmyyyy_to_iso(cells[0])
            val = _to_float(cells[1])
            if iso and val is not None:
                out.append((iso, val / 100.0))
    return out


def parse_ruonia_html(html: str) -> list[tuple[str, float]]:
    """
    CBR hd_base/ruonia HTML table is TRANSPOSED: first row is the date header,
    the 'Ставка RUONIA' row carries the rates. Returns [(iso_date, decimal)].
    """
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.DOTALL)]
        if cells:
            rows.append(cells)
    dates, rates = None, None
    for cells in rows:
        head = cells[0].lower()
        if "дата" in head:
            dates = [_ddmmyyyy_to_iso(c) for c in cells[1:]]
        elif "ruonia" in head and "ставка" in head:
            rates = [_to_float(c) for c in cells[1:]]
    if not dates or not rates:
        return []
    return [(d, r / 100.0) for d, r in zip(dates, rates)
            if d and r is not None]


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

    @staticmethod
    def _ddmm(d: date) -> str:
        return d.strftime("%d.%m.%Y")

    def get_key_rate(self, from_date: date, till_date: date | None = None) -> list[tuple[str, float]]:
        """
        CBR key rate from hd_base/KeyRate (the legacy XML_dynamic?key_rate=1
        endpoint now 404s — confirmed 2026-06). HTML table parsed first; falls
        back to parse_rate_records so injected JSON/XML fixtures still work.
        """
        till_date = till_date or from_date
        url = (f"{self.base_url}/hd_base/KeyRate/?UniDbQuery.Posted=True"
               f"&UniDbQuery.From={self._ddmm(from_date)}&UniDbQuery.To={self._ddmm(till_date)}")
        payload = self._fetch(url)
        return parse_keyrate_html(payload) or parse_rate_records(payload)

    def get_ruonia(self, from_date: date, till_date: date | None = None) -> list[tuple[str, float]]:
        """CBR RUONIA from hd_base/ruonia (transposed HTML table; same fallback)."""
        till_date = till_date or from_date
        url = (f"{self.base_url}/hd_base/ruonia/?UniDbQuery.Posted=True"
               f"&UniDbQuery.From={self._ddmm(from_date)}&UniDbQuery.To={self._ddmm(till_date)}")
        payload = self._fetch(url)
        return parse_ruonia_html(payload) or parse_rate_records(payload)

    def get_official_rates(self, on_date: date,
                           codes: tuple = ("USD", "EUR", "CNY")) -> dict[str, float]:
        """
        CBR official FX fixes via XML_daily.asp -> {"USD/RUB": 74.5, ...}.
        The only free USD/EUR source since exchange trading stopped (2024);
        rates are per-Nominal (e.g. CNY quoted per 10 units).
        """
        import re

        d = on_date.strftime("%d/%m/%Y")
        payload = self._fetch(f"{self.base_url}/scripts/XML_daily.asp?date_req={d}")
        out: dict[str, float] = {}
        for m in re.finditer(
            r"<Valute[^>]*>.*?<CharCode>([A-Z]{3})</CharCode>.*?<Nominal>(\d+)</Nominal>"
            r".*?<Value>([\d,\.]+)</Value>.*?</Valute>",
            payload, re.DOTALL,
        ):
            code, nominal, value = m.group(1), float(m.group(2)), m.group(3)
            if code in codes and nominal > 0:
                out[f"{code}/RUB"] = float(value.replace(",", ".")) / nominal
        return out
