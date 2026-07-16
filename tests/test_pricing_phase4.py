"""Phase 4 gate: Custom Product Engine (spec §16).

Exit criterion: a Phoenix/autocall definition is created WITHOUT any
product-specific pricing code — the seeded template is pure AST, and its
generic-evaluator price must match the dedicated instruments.structured
pricer exactly (same paths, same seed).
"""

from __future__ import annotations

import numpy as np
import pytest

from api.custom_products import (
    CustomProductStore,
    _phoenix_template,
    _reverse_convertible_template,
    _worst_of_barrier_rc_template,
    compile_definition,
    definition_hash,
    price_definition,
    validate_definition,
)
from instruments.structured.phoenix import (
    phoenix,
    reverse_convertible,
    worst_of_barrier_rc,
)


@pytest.fixture()
def store(tmp_path):
    return CustomProductStore(str(tmp_path / "custom.json"))


# ── exit criterion: golden parity with dedicated pricers ─

def test_phoenix_template_matches_dedicated_pricer_exactly():
    defn = _phoenix_template()
    slots = {"T": 2.0, "n_obs": 8, "autocall_barrier": 1.0,
             "ki_barrier": 0.65, "coupon_rate": 0.10}
    market = {"r": 0.05, "q": 0.0, "sigma": 0.25}
    got = price_definition(defn, slots, market,
                           n_sims=20_000, steps=252, seed=42)
    obs_dates = [2.0 * (i + 1) / 8 for i in range(8)]
    want = phoenix(1.0, 0.05, 0.0, 0.25, 2.0, obs_dates,
                   autocall_barrier=1.0, coupon_barrier=0.70, ki_barrier=0.65,
                   coupon_rate=0.10, memory_coupon=True,
                   n_sims=20_000, steps=252, seed=42)
    assert got["value"] == pytest.approx(want["price"], abs=1e-12), \
        "generic AST evaluator must reproduce the dedicated phoenix pricer"
    assert got["early_redemption_prob"] == pytest.approx(want["autocall_prob"],
                                                         abs=1e-12)


def test_reverse_convertible_template_matches_dedicated_pricer():
    defn = _reverse_convertible_template()
    slots = {"T": 1.0, "ki_barrier": 0.70, "coupon_rate": 0.12}
    market = {"r": 0.05, "q": 0.0, "sigma": 0.30}
    got = price_definition(defn, slots, market,
                           n_sims=20_000, steps=252, seed=42)
    want = reverse_convertible(1.0, 0.05, 0.0, 0.30, 1.0,
                               ki_barrier=0.70, coupon_rate=0.12,
                               n_sims=20_000, seed=42)
    assert got["value"] == pytest.approx(want["price"], abs=1e-12)


# ── multi-asset primitives (spec §16.2) ──────────────────

def test_worst_of_rc_template_matches_dedicated_pricer():
    import numpy as np

    defn = _worst_of_barrier_rc_template()
    slots = {"T": 1.0, "ki_barrier": 0.70, "coupon_rate": 0.15}
    corr = [[1.0, 0.6], [0.6, 1.0]]
    market = {"r": 0.05, "sigmas": [0.30, 0.25], "qs": [0.01, 0.0],
              "corr": corr}
    got = price_definition(defn, slots, market,
                           n_sims=20_000, steps=252, seed=42)
    want = worst_of_barrier_rc([1.0, 1.0], 0.05, [0.01, 0.0], [0.30, 0.25],
                               np.array(corr), 1.0, ki_barrier=0.70,
                               coupon_rate=0.15, n_sims=20_000, seed=42)
    assert got["value"] == pytest.approx(want["price"], abs=1e-12), \
        "worst_of/worst_path_min must reproduce the dedicated WBRC pricer"
    assert got["engine"] == "custom_mc_multi_gbm"
    assert got["assets"] == ["Asset A", "Asset B"]


def test_multi_asset_aggregations_deterministic_at_zero_vol():
    import math

    base = {
        "name": "agg-check", "author": "t",
        "assets": ["A", "B"],
        "slots": {},
        "state": {},
        "schedule": {"observations": 1, "maturity": 1.0},
        "observation_program": [],
    }
    market = {"r": 0.05, "sigmas": [0.0, 0.0], "qs": [0.0, 0.05], "rho": 0.0}
    # σ=0 → детерминированные форварды: perf_A = e^{0.05}, perf_B = 1.0
    perf_a, perf_b = math.exp(0.05), 1.0
    disc = math.exp(-0.05)
    cases = {
        "worst_of": min(perf_a, perf_b),
        "best_of": max(perf_a, perf_b),
        "basket_avg": (perf_a + perf_b) / 2,
    }
    for node, expected in cases.items():
        defn = {**base, "maturity_program": [
            {"action": "pay", "amount": {"node": node}}]}
        got = price_definition(defn, {}, market, n_sims=1000, steps=16)
        assert got["value"] == pytest.approx(disc * expected, abs=1e-12), node
    defn = {**base, "maturity_program": [
        {"action": "pay", "amount": {"node": "nth_worst", "rank": 2}}]}
    got = price_definition(defn, {}, market, n_sims=1000, steps=16)
    assert got["value"] == pytest.approx(disc * perf_a, abs=1e-12)
    defn = {**base, "maturity_program": [
        {"action": "pay",
         "amount": {"node": "weighted", "weights": [0.25, 0.75]}}]}
    got = price_definition(defn, {}, market, n_sims=1000, steps=16)
    assert got["value"] == pytest.approx(
        disc * (0.25 * perf_a + 0.75 * perf_b), abs=1e-12)


def test_multi_asset_validation_fail_closed():
    defn = _worst_of_barrier_rc_template()
    # ambiguous single-asset node with 2 assets
    defn["maturity_program"][0]["amount"] = {"node": "perf"}
    issues = validate_definition(defn)
    assert any(i["code"] == "CUSTOM_PRODUCT_AMBIGUOUS_ASSET" for i in issues)

    defn = _worst_of_barrier_rc_template()
    defn["maturity_program"][0]["amount"] = {"node": "asset", "index": 5}
    assert any("asset.index" in i["message"]
               for i in validate_definition(defn))

    defn = _worst_of_barrier_rc_template()
    defn["maturity_program"][0]["amount"] = {"node": "nth_worst", "rank": 3}
    assert any("nth_worst.rank" in i["message"]
               for i in validate_definition(defn))

    defn = _worst_of_barrier_rc_template()
    defn["maturity_program"][0]["amount"] = {"node": "weighted",
                                             "weights": [1.0]}
    assert any("weighted.weights" in i["message"]
               for i in validate_definition(defn))

    defn = _worst_of_barrier_rc_template()
    defn["assets"] = ["A", "A"]
    assert any("дублируются" in i["message"]
               for i in validate_definition(defn))


def test_wbrc_template_compiles_with_multi_asset_classification():
    report = compile_definition(_worst_of_barrier_rc_template())
    assert report["ok"], report["issues"]
    assert report["classification"]["underlyings"] == 2
    assert report["classification"]["dynamics"] == "correlated_gbm"
    assert report["classification"]["path_dependent"] is True  # worst_path_min
    assert report["compatible_engines"] == ["custom_mc_multi_gbm"]
    vectors = {v["scenario"]: v["pv"] for v in report["test_vectors"]}
    assert vectors["up"] > vectors["down"]


def test_price_rejects_wrong_sigma_vector_and_bad_corr():
    defn = _worst_of_barrier_rc_template()
    with pytest.raises(ValueError, match="sigmas"):
        price_definition(defn, {}, {"r": 0.05, "sigmas": [0.3]},
                         n_sims=1000, steps=16)
    with pytest.raises(ValueError, match="диапазоне"):
        price_definition(defn, {},
                         {"r": 0.05, "sigmas": [0.3, 0.3],
                          "corr": [[1.0, 2.0], [2.0, 1.0]]},
                         n_sims=1000, steps=16)
    with pytest.raises(ValueError, match="симметричной"):
        price_definition(defn, {},
                         {"r": 0.05, "sigmas": [0.3, 0.3],
                          "corr": [[1.0, 0.9], [0.0, 1.0]]},
                         n_sims=1000, steps=16)
    with pytest.raises(ValueError, match="диагональ"):
        price_definition(defn, {},
                         {"r": 0.05, "sigmas": [0.3, 0.3],
                          "corr": [[0.8, 0.2], [0.2, 1.0]]},
                         n_sims=1000, steps=16)
    with pytest.raises(ValueError, match="конечным"):
        price_definition(defn, {}, {"r": float("nan")},
                         n_sims=1000, steps=16)
    with pytest.raises(ValueError, match="seed"):
        price_definition(defn, {}, {"r": 0.05},
                         n_sims=1000, steps=16, seed=2_147_483_648)


def test_seeding_is_idempotent_and_adds_missing_templates(tmp_path):
    path = str(tmp_path / "seeds.json")
    store1 = CustomProductStore(path)
    assert len(store1.templates()) == 3
    # simulate a store created before the WBRC seed existed
    store1._data.pop("worst_of_barrier_rc")
    store1._save()
    store2 = CustomProductStore(path)
    names = {t["name"] for t in store2.templates()}
    assert "Worst-of Barrier RC" in names and len(store2.templates()) == 3


# ── compiler: fail-closed checks (spec §16.4) ────────────

def test_compiler_accepts_seeded_templates():
    for template in (_phoenix_template(), _reverse_convertible_template()):
        report = compile_definition(template)
        assert report["ok"], report["issues"]
        assert report["definition_hash"]
        assert report["summary"]
        assert len(report["test_vectors"]) == 3
        assert report["compatible_engines"] == ["custom_mc_gbm"]


def test_compiler_classification():
    report = compile_definition(_phoenix_template())
    assert report["classification"]["path_dependent"] is True
    assert report["classification"]["early_redemption"] is True
    rc = compile_definition(_reverse_convertible_template())
    assert rc["classification"]["early_redemption"] is False
    assert rc["classification"]["path_dependent"] is True   # path_min


def test_compiler_rejects_non_allowlisted_node():
    defn = _phoenix_template()
    defn["maturity_program"][0]["amount"] = {"node": "eval",
                                             "code": "os.system('x')"}
    issues = validate_definition(defn)
    assert any(i["code"] == "CUSTOM_PRODUCT_UNKNOWN_NODE" for i in issues)


def test_compiler_rejects_type_mismatch_and_undeclared_refs():
    defn = _phoenix_template()
    # bool where number expected
    defn["observation_program"][0]["value"] = {
        "node": "ge", "args": [{"node": "perf"}, {"node": "const", "value": 1}]}
    # undeclared slot + undeclared state
    defn["maturity_program"][0]["amount"] = {"node": "param", "name": "nope"}
    issues = validate_definition(defn)
    codes = {i["code"] for i in issues}
    assert "CUSTOM_PRODUCT_TYPE_MISMATCH" in codes
    assert "CUSTOM_PRODUCT_UNDECLARED_SLOT" in codes


def test_compiler_requires_unconditional_terminal_payout():
    defn = _phoenix_template()
    defn["maturity_program"][0]["when"] = {
        "node": "ge", "args": [{"node": "perf"}, {"node": "const", "value": 1}]}
    issues = validate_definition(defn)
    assert any(i["code"] == "CUSTOM_PRODUCT_NO_TERMINAL_PAYOUT" for i in issues)


def test_compiler_rejects_unknown_top_level_field_and_bad_schedule():
    defn = _phoenix_template()
    defn["python_hook"] = "import os"
    defn["schedule"] = {"observations": 0, "maturity": -1}
    issues = validate_definition(defn)
    codes = {i["code"] for i in issues}
    assert "SCHEMA_UNKNOWN_FIELD" in codes
    assert "CUSTOM_PRODUCT_SCHEDULE_INVALID" in codes


def test_definition_hash_is_canonical_and_content_sensitive():
    a, b = _phoenix_template(), _phoenix_template()
    assert definition_hash(a) == definition_hash(b)
    b["slots"]["coupon_rate"]["default"] = 0.11
    assert definition_hash(a) != definition_hash(b)


def test_compile_report_includes_event_timeline():
    report = compile_definition(_phoenix_template())
    timeline = report["timeline"]
    assert len(timeline) == 8 + 1               # 8 observations + maturity
    assert timeline[-1]["kind"] == "maturity"
    assert timeline[-1]["t"] == 2.0
    assert any("досрочное погашение" in e for e in timeline[0]["events"])
    assert any("выплата" in e for e in timeline[-1]["events"])
    times = [entry["t"] for entry in timeline]
    assert times == sorted(times)


def test_regression_vectors_are_deterministic():
    r1 = compile_definition(_phoenix_template())["test_vectors"]
    r2 = compile_definition(_phoenix_template())["test_vectors"]
    assert r1 == r2
    down = next(v for v in r1 if v["scenario"] == "down")
    up = next(v for v in r1 if v["scenario"] == "up")
    assert up["pv"] > down["pv"]


# ── lifecycle (spec §16.5, §20) ──────────────────────────

def test_store_seeds_published_templates(store):
    templates = store.templates()
    names = {t["name"] for t in templates}
    assert "Phoenix Autocall" in names and "Reverse Convertible" in names
    assert all(t["state"] == "published" for t in templates)


def test_template_mode_creates_draft_without_touching_template(store):
    template_id = next(t["id"] for t in store.templates()
                       if t["name"] == "Phoenix Autocall")
    product = store.create(template_id=template_id, name="Мой феникс",
                           author="alice", slot_defaults={"coupon_rate": 0.15})
    assert product["state"] == "draft"
    assert product["definition"]["slots"]["coupon_rate"]["default"] == 0.15
    # the published template itself is untouched (immutability)
    template = store.get(template_id)
    assert template["definition"]["slots"]["coupon_rate"]["default"] == 0.10
    assert template["state"] == "published"


def test_full_lifecycle_and_maker_checker(store):
    template_id = next(t["id"] for t in store.templates()
                       if t["name"] == "Phoenix Autocall")
    product = store.create(template_id=template_id, name="LC", author="alice")
    pid = product["id"]

    # draft cannot price (fail closed) and cannot submit
    with pytest.raises(ValueError, match="сначала compile"):
        store.price(pid, {}, {})
    with pytest.raises(ValueError, match="только из tested"):
        store.submit(pid, "alice")

    assert store.compile(pid)["state"] == "tested"
    # research watermark before publication (spec §20)
    priced = store.price(pid, {}, {"r": 0.05, "sigma": 0.2},
                         n_sims=2000, steps=32)
    assert priced["watermark"] == "research"

    store.submit(pid, "alice")
    with pytest.raises(ValueError, match="maker"):
        store.approve(pid, "alice")           # maker≠checker
    store.approve(pid, "bob")
    published = store.publish(pid)
    assert published["state"] == "published"
    assert store.price(pid, {}, {"r": 0.05, "sigma": 0.2},
                       n_sims=2000, steps=32)["watermark"] is None

    # published is immutable — edits and re-compilation are refused
    with pytest.raises(ValueError, match="неизменяема"):
        store.update_definition(pid, product["definition"])
    with pytest.raises(ValueError, match="неизменяема"):
        store.compile(pid)


def test_editing_resets_pipeline_to_draft(store):
    template_id = store.templates()[0]["id"]
    product = store.create(template_id=template_id, author="alice")
    pid = product["id"]
    store.compile(pid)
    defn = store.get(pid)["definition"]
    defn["description"] = "изменено"
    updated = store.update_definition(pid, defn)
    assert updated["state"] == "draft"
    assert updated["compile_report"] is None


def test_new_version_and_diff(store):
    template_id = next(t["id"] for t in store.templates()
                       if t["name"] == "Phoenix Autocall")
    v2 = store.new_version(template_id, author="alice")
    assert v2["version"] == 2 and v2["state"] == "draft"
    defn = v2["definition"]
    defn["slots"]["coupon_rate"]["default"] = 0.2
    store.update_definition(template_id, defn)
    diff = store.diff(template_id, 1, 2)
    assert diff["from_hash"] != diff["to_hash"]
    changed = {c["path"]: c for c in diff["changes"]}
    assert "slots.coupon_rate.default" in changed
    assert changed["slots.coupon_rate.default"]["from"] == 0.10
    assert changed["slots.coupon_rate.default"]["to"] == 0.2


def test_slot_bounds_enforced_on_price(store):
    template_id = store.templates()[0]["id"]
    pid = store.create(template_id=template_id, author="a")["id"]
    store.compile(pid)
    with pytest.raises(ValueError, match="ниже минимума|выше максимума"):
        store.price(pid, {"coupon_rate": 5.0}, {"r": 0.05, "sigma": 0.2},
                    n_sims=2000, steps=32)
    with pytest.raises(ValueError, match="неизвестный слот"):
        store.price(pid, {"nope": 1.0}, {"r": 0.05, "sigma": 0.2},
                    n_sims=2000, steps=32)


def test_price_is_seed_deterministic(store):
    template_id = store.templates()[0]["id"]
    a = store.price(template_id, {}, {"r": 0.05, "sigma": 0.2},
                    n_sims=5000, steps=64, seed=7)
    b = store.price(template_id, {}, {"r": 0.05, "sigma": 0.2},
                    n_sims=5000, steps=64, seed=7)
    c = store.price(template_id, {}, {"r": 0.05, "sigma": 0.2},
                    n_sims=5000, steps=64, seed=8)
    assert a["value"] == b["value"]
    assert a["value"] != c["value"]
    assert a["definition_hash"] == b["definition_hash"]


def test_store_persists_across_reopen(tmp_path):
    path = str(tmp_path / "cp.json")
    store1 = CustomProductStore(path)
    template_id = store1.templates()[0]["id"]
    pid = store1.create(template_id=template_id, name="persist",
                        author="alice")["id"]
    store1.compile(pid)

    store2 = CustomProductStore(path)
    product = store2.get(pid)
    assert product["state"] == "tested"
    assert product["definition"]["name"] == "persist"
