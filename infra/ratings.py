"""Issuer credit ratings (АКРА / Эксперт РА) + baseline recovery assumptions.

Ratings live in their own table on the market-data connection (idempotent
schema). Neither agency publishes a machine-readable feed or per-issuer
recovery rates, so:

  * ratings are loaded from ``data/ratings_manual.csv`` by
    ``scripts/update_ratings.py`` (best-effort HTTP refresh is stubbed there
    with an honest failure message);
  * recovery comes from the BASELINE_RECOVERY bucket map — an explicit base
    assumption, flagged in every payload as ``recovery_source='baseline'``.
"""

from __future__ import annotations

import datetime as _dt

_SCHEMA = """CREATE TABLE IF NOT EXISTS issuer_ratings (
    issuer_key TEXT PRIMARY KEY,
    issuer_ru TEXT NOT NULL,
    agency TEXT NOT NULL,
    rating TEXT NOT NULL,
    outlook TEXT DEFAULT '',
    rating_date TEXT DEFAULT '',
    updated_at TEXT
)"""

# Baseline recovery by national-scale rating bucket — BASE ASSUMPTION (the
# agencies publish no recovery rates); senior unsecured, conservative for RU.
BASELINE_RECOVERY = [
    ("AAA", 0.40), ("AA", 0.40), ("A", 0.35),
    ("BBB", 0.30), ("BB", 0.25), ("B", 0.20),
    ("CCC", 0.15), ("CC", 0.10), ("C", 0.10), ("D", 0.05),
]

STALE_AFTER_DAYS = 90


def _norm(rating: str) -> str:
    """'AAA(RU)' / 'ruAA-' / 'BBB+(RU)' -> the letter bucket."""
    r = rating.upper().replace("RU", "").replace("(", "").replace(")", "")
    r = r.strip().rstrip("+-").strip(".")
    return r or "B"


def recovery_for(rating: str) -> float:
    bucket = _norm(rating)
    for prefix, rec in BASELINE_RECOVERY:
        if bucket.startswith(prefix):
            return rec
    return 0.20


def ensure_schema(conn) -> None:
    conn.execute(_SCHEMA)
    conn.commit()


def upsert(conn, issuer_ru: str, agency: str, rating: str,
           outlook: str = "", rating_date: str = "") -> None:
    ensure_schema(conn)
    conn.execute(
        """INSERT INTO issuer_ratings
           (issuer_key, issuer_ru, agency, rating, outlook, rating_date, updated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(issuer_key) DO UPDATE SET
             agency=excluded.agency, rating=excluded.rating,
             outlook=excluded.outlook, rating_date=excluded.rating_date,
             updated_at=excluded.updated_at""",
        (issuer_ru.lower().strip(), issuer_ru, agency, rating, outlook,
         rating_date, _dt.date.today().isoformat()))
    conn.commit()


def lookup(conn, issuer_ru: str) -> dict | None:
    """Rating for an issuer by substring match (either direction)."""
    ensure_schema(conn)
    needle = (issuer_ru or "").lower().strip()
    if not needle:
        return None
    for row in conn.execute("SELECT * FROM issuer_ratings").fetchall():
        key = row["issuer_key"]
        if key in needle or needle in key:
            d = dict(row)
            d["recovery"] = recovery_for(d["rating"])
            d["recovery_source"] = "baseline"      # база — агентства recovery не публикуют
            d["stale"] = _is_stale(d.get("updated_at"))
            return d
    return None


def all_ratings(conn) -> list[dict]:
    ensure_schema(conn)
    out = []
    for row in conn.execute("SELECT * FROM issuer_ratings ORDER BY issuer_ru").fetchall():
        d = dict(row)
        d["recovery"] = recovery_for(d["rating"])
        d["recovery_source"] = "baseline"
        d["stale"] = _is_stale(d.get("updated_at"))
        out.append(d)
    return out


def _is_stale(updated_at: str | None) -> bool:
    if not updated_at:
        return True
    try:
        age = (_dt.date.today() - _dt.date.fromisoformat(updated_at[:10])).days
    except ValueError:
        return True
    return age > STALE_AFTER_DAYS
