"""Continuously-accumulated market store (instrument-entity model).

No snapshots: data is appended to the DB over time (idempotent add-missing) and
the latest value is shown with its own date. Each instrument is an entity —
full ISS reference (every description field) + a 5-year daily price history.

  MarketStore.preload_bonds()  — one-time/occasional: full ref + 5y daily history
  MarketStore.refresh_bonds()  — frequent: update last/change + append recent days

The 5y daily history is the source of truth for price + day-change; instrument_ref
denormalises the latest (last, change_pct, as_of) for a fast list view, and keeps
the full ISS description in ref_json for the instrument card.
"""

from __future__ import annotations

import datetime as _dt
import json

# ISS bond markets / boards we track (OFZ + corporates).
BOND_BOARDS = ("TQOB", "TQCB")


def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


class MarketStore:
    def __init__(self, db, iss_client):
        self.db = db
        self.iss = iss_client

    # -- ISS fetch helpers -------------------------------------------------
    def fetch_ref(self, secid: str) -> dict:
        """Full ISS security description → ref columns + raw_json (all fields)."""
        # lang=ru so issuer/name/type come back in Russian (the client defaults to en).
        blocks = self.iss.get_blocks(f"securities/{secid}", {"iss.only": "description", "lang": "ru"})
        desc = {r.get("name"): r.get("value") for r in blocks.get("description", [])}
        titles = {r.get("name"): r.get("title") for r in blocks.get("description", [])}
        return {
            "raw": [{"name": k, "title": titles.get(k), "value": desc.get(k)} for k in desc],
            "isin": desc.get("ISIN"),
            "issuer_ru": desc.get("SHORTNAME") or desc.get("ISSUENAME"),
            "name_ru": desc.get("NAME") or desc.get("ISSUENAME"),
            "sec_type": desc.get("TYPENAME"),
            "list_level": _num(desc.get("LISTLEVEL")),
            "currency": desc.get("FACEUNIT") or desc.get("CURRENCYID"),
            "asset_code": desc.get("ASSETCODE"),
            "last_trade_date": desc.get("LSTTRADE") or desc.get("MATDATE"),
        }

    def fetch_daily_history(self, secid: str, market: str, frm: _dt.date, till: _dt.date,
                            engine: str = "stock") -> list[dict]:
        """Daily OHLCV (+ yield) for a security over [frm, till], one row per day."""
        endpoint = f"history/engines/{engine}/markets/{market}/securities/{secid}"
        rows = self.iss.get_block_paginated(
            endpoint, "history", {"from": frm.isoformat(), "till": till.isoformat()})
        by_date: dict[str, dict] = {}
        for r in rows:
            d = r.get("TRADEDATE")
            close = _num(r.get("CLOSE")) or _num(r.get("LEGALCLOSEPRICE"))
            if not d or close is None:
                continue
            vol = _num(r.get("VOLUME")) or 0.0
            prev = by_date.get(d)
            if prev is None or vol >= (prev.get("volume") or 0.0):   # keep most-traded board
                by_date[d] = {
                    "secid": secid, "market": market, "dt": d,
                    "open": _num(r.get("OPEN")) or close,
                    "high": _num(r.get("HIGH")) or close,
                    "low": _num(r.get("LOW")) or close,
                    "close": close,
                    "volume": vol,
                    "value": _num(r.get("VALUE")),
                    "yield": _num(r.get("YIELDCLOSE")),
                    "numtrades": _num(r.get("NUMTRADES")),
                }
        return [by_date[d] for d in sorted(by_date)]

    def board_secids(self, market: str, boards) -> list[tuple[str, str]]:
        """(secid, board) for every security on the given stock-market boards."""
        out: list[tuple[str, str]] = []
        for board in boards:
            blocks = self.iss.get_blocks(
                f"engines/stock/markets/{market}/boards/{board}/securities", {"iss.only": "securities"})
            for r in blocks.get("securities", []):
                sid = r.get("SECID")
                if sid:
                    out.append((sid, board))
        return out

    def bond_secids(self, boards=BOND_BOARDS) -> list[tuple[str, str]]:
        return self.board_secids("bonds", boards)

    def equity_secids(self, board="TQBR") -> list[tuple[str, str]]:
        return self.board_secids("shares", (board,))

    def fetch_dividends(self, secid: str) -> list[dict]:
        """Dividend history → dividends-table rows."""
        blocks = self.iss.get_blocks(f"securities/{secid}/dividends", {"iss.meta": "off"})
        out = []
        for r in blocks.get("dividends", []):
            d = r.get("registryclosedate")
            if d and r.get("value") is not None:
                out.append({"secid": secid, "registry_date": d,
                            "value": _num(r.get("value")), "currency": r.get("currencyid")})
        return out

    # -- accumulation ------------------------------------------------------
    def _store_ref(self, secid, *, category, market, board, ref, last=None,
                   change_pct=None, as_of=None, is_active=1, day=None):
        self.db.save_instrument_ref({
            "secid": secid, "category": category, "market": market, "board": board,
            "isin": ref.get("isin"), "issuer_ru": ref.get("issuer_ru"),
            "name_ru": ref.get("name_ru"), "sec_type": ref.get("sec_type"),
            "list_level": ref.get("list_level"), "currency": ref.get("currency"),
            "asset_code": ref.get("asset_code"), "last_trade_date": ref.get("last_trade_date"),
            "is_active": is_active, "last": last, "change_pct": change_pct, "as_of": as_of,
            "day_json": json.dumps(day or {}), "ref_json": json.dumps(ref.get("raw") or []),
        })

    @staticmethod
    def _last_change(history: list[dict]) -> tuple[float | None, float | None, str | None]:
        if not history:
            return None, None, None
        last = history[-1]
        prev = history[-2]["close"] if len(history) >= 2 else None
        chg = ((last["close"] - prev) / prev * 100.0) if prev else None
        return last["close"], chg, last["dt"]

    def _preload_one(self, secid: str, board: str, *, category: str, market: str,
                     years: int, today: _dt.date, with_dividends: bool = False) -> int:
        """Full ref + append-missing daily history for one security → rows added."""
        ref = self.fetch_ref(secid)
        start = self.db.price_history_max_dt(secid, market)
        frm = (_dt.date.fromisoformat(start) + _dt.timedelta(days=1)) if start \
            else today.replace(year=today.year - years)
        hist = self.fetch_daily_history(secid, market, frm, today) if frm <= today else []
        if hist:
            self.db.save_price_history(hist)
        if with_dividends:
            try:
                self.db.save_dividends(secid, self.fetch_dividends(secid))
            except Exception:
                pass
        last, chg, as_of = self._last_change(self.db.get_price_history(secid, market))
        self._store_ref(secid, category=category, market=market, board=board,
                        ref=ref, last=last, change_pct=chg, as_of=as_of)
        return len(hist)

    def _preload_list(self, secids, *, category, market, years, limit, progress,
                      with_dividends=False) -> dict:
        today = _dt.date.today()
        if limit:
            secids = secids[:limit]
        added = 0
        for i, (secid, board) in enumerate(secids):
            try:
                added += self._preload_one(secid, board, category=category, market=market,
                                           years=years, today=today, with_dividends=with_dividends)
            except Exception as exc:  # isolate per-security failures
                if progress:
                    progress(f"  {secid}: ERROR {str(exc)[:80]}")
            if progress and (i + 1) % 25 == 0:
                progress(f"  {i + 1}/{len(secids)} {category}, {added} rows")
        return {category: len(secids), "rows_added": added}

    def preload_bond(self, secid: str, board: str, *, years: int = 5,
                     today: _dt.date | None = None) -> int:
        return self._preload_one(secid, board, category="bonds", market="bonds",
                                 years=years, today=today or _dt.date.today())

    def preload_bonds(self, boards=BOND_BOARDS, *, years: int = 5,
                      limit: int | None = None, progress=None) -> dict:
        return self._preload_list(self.bond_secids(boards), category="bonds", market="bonds",
                                  years=years, limit=limit, progress=progress)

    def preload_equity(self, secid: str, board: str = "TQBR", *, years: int = 5,
                       today: _dt.date | None = None) -> int:
        return self._preload_one(secid, board, category="equities", market="shares",
                                 years=years, today=today or _dt.date.today(), with_dividends=True)

    def preload_equities(self, board: str = "TQBR", *, years: int = 5,
                         limit: int | None = None, progress=None) -> dict:
        return self._preload_list(self.equity_secids(board), category="equities", market="shares",
                                  years=years, limit=limit, progress=progress, with_dividends=True)

    def preload_futures(self, *, years: int = 2, progress=None) -> dict:
        """Ingest the whole FORTS chain: ref for every contract (so the card can
        group the chain), mark the active contract per asset (nearest non-expired,
        max open interest), and pull daily history for the active contracts only."""
        today = _dt.date.today()
        blocks = self.iss.get_blocks(
            "engines/futures/markets/forts/securities", {"iss.meta": "off", "lang": "ru"})
        md = {r.get("SECID"): r for r in blocks.get("marketdata", [])}
        by_asset: dict[str, list] = {}
        for r in blocks.get("securities", []):
            sid, asset = r.get("SECID"), r.get("ASSETCODE")
            if sid and asset:
                by_asset.setdefault(asset, []).append(r)

        assets = 0
        added = 0
        contracts = 0
        for asset, rows in by_asset.items():
            live = [c for c in rows if (c.get("LASTTRADEDATE") or "") >= today.isoformat()]
            active = max(live, key=lambda c: _num(md.get(c.get("SECID"), {}).get("OPENPOSITION")) or 0.0) \
                if live else None
            if active:
                assets += 1
            for c in rows:
                sid = c.get("SECID")
                m = md.get(sid, {})
                last = _num(m.get("LAST")) or _num(m.get("SETTLEPRICE")) or _num(c.get("PREVSETTLEPRICE"))
                prev = _num(c.get("PREVSETTLEPRICE"))
                chg = ((last - prev) / prev * 100.0) if (last and prev) else None
                is_active = 1 if (active and sid == active.get("SECID")) else 0
                as_of = today.isoformat() if is_active else c.get("LASTTRADEDATE")
                ref = {"isin": None, "issuer_ru": c.get("SHORTNAME"),
                       "name_ru": c.get("SECNAME") or c.get("SHORTNAME"), "sec_type": "Фьючерс",
                       "list_level": None, "currency": None, "asset_code": asset,
                       "last_trade_date": c.get("LASTTRADEDATE"),
                       "raw": [{"name": k, "title": k, "value": c.get(k)} for k in c]}
                if is_active:
                    try:
                        ref = self.fetch_ref(sid)          # full description for the card
                    except Exception:
                        pass
                    start = self.db.price_history_max_dt(sid, "forts")
                    frm = (_dt.date.fromisoformat(start) + _dt.timedelta(days=1)) if start \
                        else today.replace(year=today.year - years)
                    hist = self.fetch_daily_history(sid, "forts", frm, today, engine="futures") \
                        if frm <= today else []
                    if hist:
                        self.db.save_price_history(hist)
                        added += len(hist)
                    full = self.db.get_price_history(sid, "forts")
                    if full:
                        last, chg, as_of = self._last_change(full)
                self._store_ref(sid, category="futures", market="forts", board="forts",
                                ref=ref, last=last, change_pct=chg, as_of=as_of, is_active=is_active)
                contracts += 1
            if progress and assets and assets % 20 == 0:
                progress(f"  {assets} assets, {contracts} contracts, {added} hist rows")
        return {"assets": assets, "contracts": contracts, "rows_added": added}
