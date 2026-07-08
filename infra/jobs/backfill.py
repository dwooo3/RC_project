"""
Historical backfill job (Stage I.1).

Fills time_series with the history VaR/backtesting needs:
  - index closes (IMOEX/RVI/RGBI/RUCBTRNS/RUSFAR*) via range history calls;
  - equity closes for the most liquid TQBR names (range calls — one request
    per security for the whole window);
  - КБД zero rates per business day (zcyc is date-scoped, one call per day),
    storing both per-date curve snapshots and KBD:<tenor>Y rate series;
  - CBR key rate / RUONIA via range queries.

Idempotent: every write is an upsert; re-running a window is safe.
"""

from __future__ import annotations

from datetime import date, timedelta

from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.ingest import MoexIngestor

DEFAULT_INDICES = ["IMOEX", "RVI", "RGBI", "RUCBTRNS",
                   "RUSFAR", "RUSFAR1W", "RUSFAR1M", "RUSFAR3M"]
KBD_SERIES_TENORS = (0.25, 1.0, 2.0, 5.0, 10.0)

# Fallback when the DB has no equity snapshot to rank by volume.
FALLBACK_EQUITIES = ["SBER", "GAZP", "LKOH", "T", "ROSN", "YDEX", "VTBR",
                     "NVTK", "GMKN", "PLZL", "TATN", "MAGN", "NLMK", "CHMF",
                     "MOEX", "MTSS", "ALRS", "AFLT", "OZON", "X5"]


def top_equities_by_volume(db: MarketDataDB, n: int = 50) -> list[str]:
    """Most liquid TQBR names from the latest equity_quotes snapshot."""
    rows = db._query(  # noqa: SLF001 — internal job, same package family
        "SELECT secid, MAX(volume) AS volume FROM equity_quotes "
        "GROUP BY secid ORDER BY volume DESC LIMIT ?", (n,))
    secids = [r["secid"] for r in rows if r.get("secid")]
    return secids or FALLBACK_EQUITIES[:n]


def business_days(from_date: date, till_date: date) -> list[date]:
    out, d = [], from_date
    while d <= till_date:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


class BackfillJob:
    def __init__(self, db: MarketDataDB, iss_client, cbr_client=None):
        self.db = db
        self.iss_client = iss_client
        self.cbr_client = cbr_client

    def run(self, from_date: date, till_date: date | None = None, *,
            equities: list[str] | None = None, top: int = 50,
            indices: list[str] | None = None,
            kbd: bool = True, kbd_tenors=KBD_SERIES_TENORS) -> dict:
        till_date = till_date or date.today()
        moex = MoexIngestor(self.iss_client, self.db)
        indices = list(indices if indices is not None else DEFAULT_INDICES)
        equities = list(equities) if equities else top_equities_by_volume(self.db, top)
        summary: dict = {"from": from_date.isoformat(), "till": till_date.isoformat(),
                         "steps": {}}

        def step(name, fn):
            try:
                summary["steps"][name] = fn()
            except Exception as exc:
                summary["steps"][name] = f"error: {exc}"

        for idx in indices:
            step(f"index:{idx}",
                 lambda idx=idx: moex.ingest_index_history(idx, from_date, till_date))
        for sec in equities:
            step(f"equity:{sec}",
                 lambda sec=sec: moex.ingest_equity_history(sec, from_date, till_date))

        if kbd:
            days = business_days(from_date, till_date)

            def _kbd():
                from curves.yield_curve import YieldCurve
                filled = 0
                for d in days:
                    sid = MoexIngestor.snapshot_id_for(d)
                    try:
                        n = moex.ingest_gcurve(sid, d, historical=True)
                    except Exception:
                        continue                     # holiday / no curve published
                    if not n:
                        continue
                    pts = self.db.get_curve_points(sid, "GCURVE_RUB")
                    if len(pts) >= 3:
                        curve = YieldCurve([p["tenor"] for p in pts],
                                           [p["zero_rate"] for p in pts],
                                           label="GCURVE_RUB", interp="cubic")
                        for tenor in kbd_tenors:
                            self.db.save_time_series(
                                f"KBD:{tenor:g}Y", "rate",
                                [(d.isoformat(), curve.rate(tenor))])
                    filled += 1
                return filled

            step("kbd_days", _kbd)

        if self.cbr_client is not None:
            def _cbr(series, fetch):
                rows = fetch(from_date, till_date)
                self.db.save_time_series(series, "rate", rows)
                return len(rows)

            step("cbr_key_rate",
                 lambda: _cbr("CBR_KEY_RATE", self.cbr_client.get_key_rate))
            step("cbr_ruonia",
                 lambda: _cbr("RUONIA", self.cbr_client.get_ruonia))

            # Daily official FX fixings (USD/EUR/CNY) — the fx risk factor for
            # HypPL/VaR; the only free RUB FX history since exchange trading
            # of USD/EUR stopped in 2024.
            def _fx(pair, code):
                rows = self.cbr_client.get_fx_history(code, from_date, till_date)
                self.db.save_time_series(f"{pair.replace('/', '')}:fix", "fx", rows)
                return len(rows)

            for pair, code in getattr(self.cbr_client, "FX_CODES", {}).items():
                step(f"cbr_fx:{pair}", lambda pair=pair, code=code: _fx(pair, code))

        summary["equities"] = equities
        summary["indices"] = indices
        return summary


def load_cpi_csv(db: MarketDataDB, path: str, factor_id: str = "CPI_RU") -> int:
    """
    Load a monthly CPI index from a CSV with rows ``YYYY-MM-DD,value``
    (Rosstat/CBR publish CPI as tables, not an API — manual refresh path).
    Stored as time_series kind='index' for linker base-CPI indexation.
    """
    import csv

    points: list[tuple[str, float]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row or row[0].startswith("#"):
                continue
            try:
                points.append((row[0].strip(), float(row[1])))
            except (IndexError, ValueError):
                continue
    db.save_time_series(factor_id, "index", points)
    return len(points)
