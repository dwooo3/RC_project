"""ISS client — block parsing, cursor pagination, retry (no network; fixtures)."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import infra.certs
import infra.moex_iss.client as client_module
from infra.moex_iss.client import IssClient, parse_iss_json


# ── parse_iss_json ───────────────────────────────────────

def test_parse_iss_json_columns_data_to_dicts():
    payload = {
        "yearyields": {
            "columns": ["tradedate", "period", "value"],
            "data": [["2026-06-04", 0.25, 15.5], ["2026-06-04", 1.0, 14.5]],
        },
        "metadata_block": {"foo": 1},  # ignored — wrong shape
    }
    blocks = parse_iss_json(payload)
    assert "metadata_block" not in blocks
    assert blocks["yearyields"] == [
        {"tradedate": "2026-06-04", "period": 0.25, "value": 15.5},
        {"tradedate": "2026-06-04", "period": 1.0, "value": 14.5},
    ]


def test_build_url_applies_meta_off_and_lang():
    client = IssClient(fetch=lambda url: "{}")
    url = client.build_url("engines/stock/zcyc", {"iss.only": "params"})
    assert url.startswith("https://iss.moex.com/iss/engines/stock/zcyc.json?")
    assert "iss.meta=off" in url
    assert "lang=en" in url
    assert "iss.only=params" in url


def test_default_transport_sends_algopack_bearer_without_persisting_it(
    monkeypatch,
):
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b"{}"

    def urlopen(request, **kwargs):
        observed["authorization"] = request.get_header("Authorization")
        observed["url"] = request.full_url
        observed.update(kwargs)
        return Response()

    monkeypatch.setattr(
        infra.certs, "market_data_ssl_context", lambda: "ssl-context")
    monkeypatch.setattr(client_module.urllib.request, "urlopen", urlopen)
    client = IssClient(
        base_url="https://apim.moex.com/iss",
        bearer_token="secret-api-key",
        rate_limit_per_sec=0,
    )

    assert client.get_blocks("calendars/stock") == {}
    assert observed["authorization"] == "Bearer secret-api-key"
    assert observed["url"].startswith(
        "https://apim.moex.com/iss/calendars/stock.json?")
    assert not hasattr(client, "bearer_token")


def test_bearer_and_authorization_header_are_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        IssClient(
            bearer_token="token",
            headers={"Authorization": "Bearer other"},
        )


# ── pagination ───────────────────────────────────────────

def _page(rows, index, total, pagesize=2):
    return json.dumps({
        "history": {"columns": ["secid", "v"], "data": rows},
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[index, total, pagesize]],
        },
    })


def test_get_block_paginated_follows_cursor():
    pages = {0: _page([["A", 1], ["B", 2]], 0, 5), 2: _page([["C", 3], ["D", 4]], 2, 5),
             4: _page([["E", 5]], 4, 5)}

    def fetch(url):
        start = int(url.split("start=")[1].split("&")[0]) if "start=" in url else 0
        return pages[start]

    client = IssClient(fetch=fetch, rate_limit_per_sec=0)
    rows = client.get_block_paginated("history/...", "history", page_size=2)
    assert [r["secid"] for r in rows] == ["A", "B", "C", "D", "E"]


def test_get_block_paginated_stops_without_cursor():
    def fetch(url):
        start = int(url.split("start=")[1].split("&")[0]) if "start=" in url else 0
        if start == 0:
            return json.dumps({"securities": {"columns": ["s"], "data": [["A"], ["B"]]}})
        return json.dumps({"securities": {"columns": ["s"], "data": []}})

    client = IssClient(fetch=fetch, rate_limit_per_sec=0)
    rows = client.get_block_paginated("x", "securities", page_size=100)
    assert [r["s"] for r in rows] == ["A", "B"]


# ── retry ────────────────────────────────────────────────

def test_get_retries_then_succeeds():
    calls = {"n": 0}

    def flaky(url):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("transient")
        return "{}"

    client = IssClient(fetch=flaky, rate_limit_per_sec=0, backoff=0.0, max_retries=3)
    client.get_blocks("ping")
    assert calls["n"] == 3


def test_get_raises_after_max_retries():
    def always_fail(url):
        raise OSError("down")

    client = IssClient(fetch=always_fail, rate_limit_per_sec=0, backoff=0.0, max_retries=2)
    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        client.get_blocks("ping")
