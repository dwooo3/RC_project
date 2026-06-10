"""
MOEX ISS API client — paginated fetch + block parsing.

Network access is injected via ``fetch`` so the parser and cursor pagination are
unit-testable without hitting iss.moex.com (CI uses fixtures, no network).

Conventions used (per MOEX_MARKET_DATA_INTEGRATION_PROMPT.md §1):
  - JSON format, ``iss.meta=off`` always applied.
  - Optional ``iss.only=<block>`` to minimise payload.
  - Cursor pagination via the ``<block>.cursor`` companion block and ``start``.
  - Polite client: rate-limit, bounded retries with backoff, timeout.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Callable

ISS_BASE = "https://iss.moex.com/iss"


def parse_iss_json(payload: dict) -> dict[str, list[dict]]:
    """
    Convert a raw ISS JSON document into ``{block_name: [row_dict, ...]}``.

    Each ISS block is ``{"columns": [...], "data": [[...], ...]}``. Blocks that
    do not follow that shape are skipped.
    """
    blocks: dict[str, list[dict]] = {}
    for name, block in payload.items():
        if not isinstance(block, dict) or "columns" not in block or "data" not in block:
            continue
        columns = block["columns"]
        blocks[name] = [dict(zip(columns, row)) for row in block["data"]]
    return blocks


def _default_fetch(timeout: float) -> Callable[[str], str]:
    from infra.certs import market_data_ssl_context

    ctx = market_data_ssl_context()    # trusts the anti-DDoS proxy chain too

    def fetch(url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "RiskCalc-ISS-Client/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:  # noqa: S310 (public API)
            return resp.read().decode("utf-8")

    return fetch


class IssClient:
    """Low-level MOEX ISS client. No business logic — fetch + parse only."""

    def __init__(
        self,
        base_url: str = ISS_BASE,
        fetch: Callable[[str], str] | None = None,
        *,
        rate_limit_per_sec: float = 5.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        timeout: float = 15.0,
        lang: str = "en",
    ):
        self.base_url = base_url.rstrip("/")
        self._fetch = fetch or _default_fetch(timeout)
        self._min_interval = (1.0 / rate_limit_per_sec) if rate_limit_per_sec else 0.0
        self._last_call = 0.0
        self.max_retries = max_retries
        self.backoff = backoff
        self.lang = lang

    # -- url ---------------------------------------------------------------
    def build_url(self, path: str, params: dict | None = None) -> str:
        merged = {"iss.meta": "off", "lang": self.lang}
        merged.update(params or {})
        query = urllib.parse.urlencode(merged)
        return f"{self.base_url}/{path.strip('/')}.json?{query}"

    # -- transport ---------------------------------------------------------
    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                return self._fetch(url)
            except Exception as exc:  # transient network/HTTP errors
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (2**attempt))
        raise RuntimeError(f"ISS request failed after {self.max_retries} attempts: {url}") from last_error

    def get_blocks(self, path: str, params: dict | None = None) -> dict[str, list[dict]]:
        """Fetch a single ISS document and return parsed blocks."""
        url = self.build_url(path, params)
        return parse_iss_json(json.loads(self._get_text(url)))

    # -- pagination --------------------------------------------------------
    def get_block_paginated(
        self,
        path: str,
        block: str,
        params: dict | None = None,
        *,
        page_size: int = 100,
        max_pages: int = 1000,
    ) -> list[dict]:
        """
        Fetch all rows of ``block`` across cursor pages.

        Uses the ``<block>.cursor`` companion block (INDEX/TOTAL/PAGESIZE) when
        present; otherwise advances ``start`` until a page returns no rows.
        """
        rows: list[dict] = []
        start = 0
        for _ in range(max_pages):
            page_params = dict(params or {})
            page_params["start"] = start
            blocks = self.get_blocks(path, page_params)
            page = blocks.get(block, [])
            if not page:
                break
            rows.extend(page)

            cursor = blocks.get(f"{block}.cursor")
            if cursor:
                c = cursor[0]
                index = int(c.get("INDEX", start))
                total = int(c.get("TOTAL", len(rows)))
                size = int(c.get("PAGESIZE", page_size)) or page_size
                next_start = index + size
                if next_start >= total:
                    break
                start = next_start
            else:
                # No cursor metadata: advance by observed page length.
                if len(page) < page_size:
                    break
                start += len(page)
        return rows
