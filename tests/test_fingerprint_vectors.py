"""Acceptance §27.17: Python and Swift produce identical canonical bytes и
hash на общем наборе versioned fixtures.

The Swift side (macapp PricingFingerprint) drives workspace staleness; this
Python replica pins the SAME canonicalization against the shared fixture
macapp/Tests/RiskCalcTests/Fixtures/fingerprint_vectors.json. The Swift
XCTest (PricingFingerprintTests) asserts the same vectors — a drift in
either implementation turns exactly one of the two suites red.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

FIXTURE = (Path(__file__).resolve().parent.parent / "macapp" / "Tests"
           / "RiskCalcTests" / "Fixtures" / "fingerprint_vectors.json")


def canonical_number(v: float) -> str:
    """Byte-for-byte replica of Swift PricingFingerprint.canonicalNumber."""
    if v == 0:
        return "0"
    if v == round(v) and abs(v) < 1e15:
        return str(int(v))
    s = "%.12g" % v
    if "." in s and "e" not in s and "E" not in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fingerprint(product, engine, env, secid, numeric, choice) -> str:
    parts = [f"product={product}", f"engine={engine}",
             f"env={env or ''}", f"secid={secid or ''}"]
    for key in sorted(numeric):
        parts.append(f"n:{key}={canonical_number(numeric[key])}")
    for key in sorted(choice):
        parts.append(f"s:{key}={choice[key]}")
    preimage = "pricing-fingerprint-v1\x00" + "\x01".join(parts)
    return hashlib.sha256(preimage.encode()).hexdigest()


def _cases():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_vector_matches_fixture(case):
    got = fingerprint(case["product"], case["engine"], case["env"],
                      case["secid"], case["numeric"], case["choice"])
    assert got == case["expected"], (
        f"{case['name']}: канонизация разошлась с зафиксированным вектором")


def test_canonical_number_edges():
    assert canonical_number(0.0) == "0"
    assert canonical_number(-0.0) == "0"
    assert canonical_number(100.0) == "100"
    assert canonical_number(-42.0) == "-42"
    assert canonical_number(1e14) == "100000000000000"
    assert canonical_number(100.5) == "100.5"
    assert canonical_number(1 / 3) == "0.333333333333"
    assert canonical_number(2.5e-07) == "2.5e-07"


def test_order_independence_and_sensitivity():
    a = fingerprint("p", "e", None, None, {"x": 1.0, "y": 2.0}, {})
    b = fingerprint("p", "e", None, None, {"y": 2.0, "x": 1.0}, {})
    assert a == b, "порядок ключей не должен влиять на отпечаток"
    c = fingerprint("p", "e", None, None, {"x": 1.0, "y": 2.000001}, {})
    assert a != c
