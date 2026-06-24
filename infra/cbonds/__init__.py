"""cbonds RUONIA OIS reference curve.

cbonds.ru index 93204 — "OIS RUB RUONIA mid (МБ СПФИ OTC)" — publishes a full
RUONIA overnight-index-swap term structure. The site is paywalled / bot-guarded,
so the quotes are captured manually here; refreshing = re-reading the page and
updating ``CBONDS_RUONIA_OIS`` / ``CBONDS_AS_OF`` below.

Stored as curve ``RUONIA-OIS-CBONDS`` for cross-validation against the MOEX
RUSFAR-bootstrapped ``RUONIA_RUB``.

Source: https://cbonds.ru/indexes/93204/
"""

from __future__ import annotations

from datetime import date

# OIS RUB RUONIA mid par rates as of CBONDS_AS_OF. (tenor_years, rate_percent),
# ACT/365 tenors. Captured from cbonds.ru index 93204.
CBONDS_AS_OF = date(2026, 6, 23)
CBONDS_RUONIA_OIS: list[tuple[float, float]] = [
    (7.0 / 365, 14.14),    # 1W
    (14.0 / 365, 14.14),   # 2W
    (30.0 / 365, 14.13),   # 1M
    (60.0 / 365, 14.12),   # 2M
    (91.0 / 365, 14.12),   # 3M
    (182.0 / 365, 14.10),  # 6M
    (1.0, 14.16),          # 1Y
    (2.0, 13.34),          # 2Y
    (5.0, 13.54),          # 5Y
    (10.0, 13.71),         # 10Y
]


def ingest_cbonds_ruonia_ois(db, snapshot_id: str, as_of: date | None = None) -> int:
    """Bootstrap the cbonds RUONIA OIS quotes → curve RUONIA-OIS-CBONDS."""
    from infra.curves_ois import bootstrap_ois

    as_of = as_of or CBONDS_AS_OF
    tenors = [t for t, _ in CBONDS_RUONIA_OIS]
    pars = [r / 100.0 for _, r in CBONDS_RUONIA_OIS]
    points = bootstrap_ois(tenors, pars)
    db.delete_curve(snapshot_id, "RUONIA-OIS-CBONDS")
    db.save_curve(
        snapshot_id, "RUONIA-OIS-CBONDS", method="ois_bootstrap_cbonds",
        nss_params={"source": "cbonds.ru/indexes/93204", "as_of": as_of.isoformat(),
                    "par_rates_pct": {f"{t:.4f}": r for t, r in CBONDS_RUONIA_OIS}},
        as_of=as_of, points=points,
    )
    return len(points)
