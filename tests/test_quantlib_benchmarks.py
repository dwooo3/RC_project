"""A6: кросс-валидация против QuantLib (пропускается без пакета)."""

from __future__ import annotations

import pytest

ql = pytest.importorskip("QuantLib")

from validation.quantlib_benchmarks import run_benchmarks  # noqa: E402

ROWS = run_benchmarks()


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_quantlib_benchmark(row):
    assert row["ok"], (
        f"{row['id']}: ours={row['ours']:.8f} QuantLib={row['quantlib']:.8f} "
        f"rel_diff={row['rel_diff']:.2e} > tol={row['tol']:.0e}")


def test_pack_covers_asset_classes():
    groups = {r["group"] for r in ROWS}
    assert {"vanilla", "fx", "exotics", "rates", "stochastic_vol"} <= groups
    assert len(ROWS) >= 12
