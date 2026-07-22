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
import hashlib
import json

# ISS bond markets / boards we track (OFZ + corporates).
BOND_BOARDS = ("TQOB", "TQCB")


def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


# CBR-rate FX pairs: secid (slash-free for routing) -> (CBR code, RU name, pair label).
FX_PAIRS = {
    "USDRUB": ("R01235", "Доллар США", "USD/RUB"),
    "EURRUB": ("R01239", "Евро", "EUR/RUB"),
    "CNYRUB": ("R01375", "Китайский юань", "CNY/RUB"),
}


class MarketStore:
    def __init__(self, db, iss_client, cbr_client=None):
        self.db = db
        self.iss = iss_client
        self.cbr = cbr_client

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
                            engine: str = "stock", board: str | None = None) -> list[dict]:
        """Daily OHLCV (+ yield) for a security over [frm, till], one row per day."""
        endpoint = f"history/engines/{engine}/markets/{market}/securities/{secid}"
        rows = self.iss.get_block_paginated(
            endpoint, "history", {"from": frm.isoformat(), "till": till.isoformat()})
        self._save_contract_fixings(
            rows, fallback_secid=secid, fallback_board=board)
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

    def _save_contract_fixings(
        self, rows: list[dict], *, fallback_secid: str | None = None,
        fallback_board: str | None = None,
    ) -> int:
        """Persist exact ISS close/settlement fields with their identities.

        ``price_history.close`` remains a display/history convenience and may
        choose between columns.  Lifecycle reconstruction must instead bind a
        named basis (CLOSE, LEGALCLOSEPRICE, WAPRICE or SETTLEPRICE), board and
        session.  Store every available positive basis without fallback so a
        contract can later request one exact series and fail closed on gaps.
        """
        saver = getattr(self.db, "save_contract_fixings", None)
        if not callable(saver) or not rows:
            return 0
        fetched_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        # Some history endpoints can return more than one physical row for the
        # same security/date/board.  Match the display-history rule and bind
        # the contractual fixing to the most-traded row deterministically.
        best_rows: dict[tuple[str, str, str, str], dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            secid = str(row.get("SECID") or fallback_secid or "").strip()
            observed_date = str(row.get("TRADEDATE") or "").strip()
            board = str(row.get("BOARDID") or fallback_board or "").strip().upper()
            session = str(
                row.get("TRADINGSESSION") or row.get("TRADE_SESSION") or ""
            ).strip().upper()
            if not secid or not observed_date:
                continue
            key = (secid, observed_date, board, session)
            previous = best_rows.get(key)
            volume = _num(row.get("VOLUME")) or 0.0
            previous_volume = (_num(previous.get("VOLUME")) or 0.0) if previous else -1.0
            if previous is None or volume >= previous_volume:
                best_rows[key] = row

        fixings: list[dict] = []
        for (secid, observed_date, board, session), row in best_rows.items():
            for basis in (
                    "CLOSE", "LEGALCLOSEPRICE", "WAPRICE", "SETTLEPRICE"):
                value = _num(row.get(basis))
                if value is None or value <= 0.0:
                    continue
                semantic = {
                    "factor_id": f"{secid}:price",
                    "observed_date": observed_date,
                    "value": value,
                    "price_basis": basis,
                    "board": board,
                    "session": session,
                    "source": "MOEX",
                }
                payload_hash = hashlib.sha256(json.dumps(
                    semantic, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False,
                ).encode("utf-8")).hexdigest()
                fixings.append({
                    **semantic,
                    "fetched_at": fetched_at,
                    "payload_hash": payload_hash,
                })
        return int(saver(fixings)) if fixings else 0

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

    def backfill_contract_fixings(
        self,
        secid: str,
        market: str,
        board: str,
        *,
        years: int = 5,
        engine: str = "stock",
        today: _dt.date | None = None,
    ) -> int:
        """Backfill the immutable MOEX fixing cursor behind existing history.

        This is independent from the append cursor in ``price_history``.  It is
        primarily a migration path for stores populated before
        ``contract_fixings`` existed: if exact rows are absent or cover a
        shorter boundary span, fetch only the missing leading/trailing ranges.
        Interior exchange holidays are intentionally not inferred here; the
        governed MOEX calendar remains the authority at valuation time.

        Returns the number of newly covered fixing dates (across all available
        named bases) and leaves repeated calls idempotent.
        """
        today = today or _dt.date.today()
        history_end_raw = self.db.price_history_max_dt(secid, market)
        if not history_end_raw:
            # The normal preload request will fetch the full requested range
            # and persist both price_history and exact fixings in one pass.
            return 0
        history_end = min(_dt.date.fromisoformat(history_end_raw), today)
        target_start = today.replace(year=today.year - years)
        if target_start > history_end:
            return 0

        factor_id = f"{secid}:price"
        coverage = self.db.contract_fixing_coverage(
            factor_id, source="MOEX", board=board, session="",
        )
        before = int(coverage["date_count"])
        first = (
            _dt.date.fromisoformat(coverage["first_date"])
            if coverage.get("first_date") else None
        )
        last = (
            _dt.date.fromisoformat(coverage["last_date"])
            if coverage.get("last_date") else None
        )
        ranges: list[tuple[_dt.date, _dt.date]] = []
        if first is None or last is None:
            ranges.append((target_start, history_end))
        else:
            old_end = min(history_end, first - _dt.timedelta(days=1))
            if target_start <= old_end:
                ranges.append((target_start, old_end))
            recent_start = max(target_start, last + _dt.timedelta(days=1))
            if recent_start <= history_end:
                ranges.append((recent_start, history_end))

        for frm, till in ranges:
            hist = self.fetch_daily_history(
                secid, market, frm, till, engine=engine, board=board,
            )
            if hist:
                # Exact fixings are saved inside fetch_daily_history.  Preserve
                # the useful older display history too; save_price_history is
                # idempotent for already populated stores.
                self.db.save_price_history(hist)

        after = self.db.contract_fixing_coverage(
            factor_id, source="MOEX", board=board, session="",
        )
        return max(int(after["date_count"]) - before, 0)

    def _preload_one(self, secid: str, board: str, *, category: str, market: str,
                     years: int, today: _dt.date, with_dividends: bool = False) -> int:
        """Full ref + append-missing daily history for one security → rows added."""
        ref = self.fetch_ref(secid)
        start = self.db.price_history_max_dt(secid, market)
        if start:
            self.backfill_contract_fixings(
                secid, market, board, years=years, today=today)
        frm = (_dt.date.fromisoformat(start) + _dt.timedelta(days=1)) if start \
            else today.replace(year=today.year - years)
        hist = self.fetch_daily_history(
            secid, market, frm, today, board=board) if frm <= today else []
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

    # -- daily append (cheap: one paginated request per market/board/date) --

    # market → (engine, iss_market, boards); boards=None → whole market.
    _DAILY_MARKETS = {
        "bonds": ("stock", "bonds", BOND_BOARDS),
        "shares": ("stock", "shares", ("TQBR",)),
        "forts": ("futures", "forts", None),
    }

    def _daily_rows(self, rows: list[dict], market: str) -> list[dict]:
        """Market-wide EOD rows for one date → price_history rows (dedup boards,
        keep the most-traded one) — same normalisation as fetch_daily_history."""
        best: dict[tuple, dict] = {}
        for r in rows:
            sid, d = r.get("SECID"), r.get("TRADEDATE")
            close = _num(r.get("CLOSE")) or _num(r.get("LEGALCLOSEPRICE"))
            if not sid or not d or close is None:
                continue
            vol = _num(r.get("VOLUME")) or 0.0
            prev = best.get((sid, d))
            if prev is None or vol >= (prev.get("volume") or 0.0):
                best[(sid, d)] = {
                    "secid": sid, "market": market, "dt": d,
                    "open": _num(r.get("OPEN")) or close,
                    "high": _num(r.get("HIGH")) or close,
                    "low": _num(r.get("LOW")) or close,
                    "close": close, "volume": vol,
                    "value": _num(r.get("VALUE")),
                    "yield": _num(r.get("YIELDCLOSE")),
                    "numtrades": _num(r.get("NUMTRADES")),
                }
        return list(best.values())

    def append_daily(self, *, markets=("bonds", "shares", "forts"),
                     today: _dt.date | None = None, progress=None) -> dict:
        """Append the missing EOD days for whole markets — the fix for the
        refresh button leaving price_history behind the snapshot: one paginated
        ISS request per board per missing date instead of one per security."""
        today = today or _dt.date.today()
        out: dict = {}
        for market in markets:
            engine, iss_market, boards = self._DAILY_MARKETS[market]
            start = self.db.market_max_dt(market)
            if not start:
                continue                       # empty store → run a preload instead
            d = _dt.date.fromisoformat(start) + _dt.timedelta(days=1)
            added = days = 0
            while d <= today:
                date_rows: list[dict] = []
                try:
                    if boards:
                        for b in boards:
                            board_rows = self.iss.get_block_paginated(
                                f"history/engines/{engine}/markets/{iss_market}"
                                f"/boards/{b}/securities",
                                "history", {"date": d.isoformat()})
                            self._save_contract_fixings(
                                board_rows, fallback_board=b)
                            date_rows += board_rows
                    else:
                        date_rows = self.iss.get_block_paginated(
                            f"history/engines/{engine}/markets/{iss_market}/securities",
                            "history", {"date": d.isoformat()})
                        self._save_contract_fixings(date_rows)
                except Exception:
                    date_rows = []             # one bad date must not kill the append
                hist = self._daily_rows(date_rows, market)
                if hist:
                    self.db.save_price_history(hist)
                    added += len(hist)
                days += 1
                if progress:
                    progress(f"  {market} {d}: +{len(hist)}")
                d += _dt.timedelta(days=1)
            out[market] = {"days": days, "rows_added": added}
        return out

    def refresh_last_change(self, *, markets=("bonds", "shares", "forts", "fx"),
                            lookback_days: int = 10) -> int:
        """Recompute the denormalised last/change_pct/as_of on instrument_ref
        from the price_history tail (set-based, no per-security requests)."""
        frm = (_dt.date.today() - _dt.timedelta(days=lookback_days)).isoformat()
        updated = 0
        for market in markets:
            closes: dict[str, list[tuple[str, float]]] = {}
            for r in self.db.recent_closes(market, frm):
                if r["close"] is not None:
                    closes.setdefault(r["secid"], []).append((r["dt"], r["close"]))
            for secid, pts in closes.items():
                last_dt, last = pts[-1]
                prev = pts[-2][1] if len(pts) >= 2 else None
                chg = ((last - prev) / prev * 100.0) if prev else None
                self.db.update_ref_quote(secid, last, chg, last_dt)
                updated += 1
        return updated

    # -- deep backfill (per-security, long-running; run via scripts/preload) --

    def backfill_one(self, secid: str, market: str, *, years: int = 8,
                     engine: str = "stock", today: _dt.date | None = None) -> int:
        """Extend history BACKWARDS: fetch [today-years, first_stored) once."""
        today = today or _dt.date.today()
        first = self.db.price_history_min_dt(secid, market)
        frm = today.replace(year=today.year - years)
        till = (_dt.date.fromisoformat(first) - _dt.timedelta(days=1)) if first else today
        if frm > till:
            return 0
        hist = self.fetch_daily_history(secid, market, frm, till, engine=engine)
        if hist:
            self.db.save_price_history(hist)
        return len(hist)

    def backfill(self, category: str, *, years: int = 8, limit: int | None = None,
                 progress=None) -> dict:
        """Deepen daily history for every tracked instrument of a category."""
        if category == "fx":                   # CBR fixings, not ISS
            return self._backfill_fx(years=years, progress=progress)
        engine = "futures" if category in ("futures", "options", "commodities") else "stock"
        refs = self.db.instrument_refs_for(category)
        if category == "futures":              # only active contracts carry history
            refs = [r for r in refs if r.get("is_active")]
        if limit:
            refs = refs[:limit]
        added = 0
        for i, r in enumerate(refs):
            try:
                added += self.backfill_one(r["secid"], r["market"], years=years, engine=engine)
            except Exception as exc:
                if progress:
                    progress(f"  {r['secid']}: ERROR {str(exc)[:80]}")
            if progress and (i + 1) % 25 == 0:
                progress(f"  {i + 1}/{len(refs)} {category}, {added} rows")
        return {category: len(refs), "rows_added": added}

    def _backfill_fx(self, *, years: int = 8, progress=None) -> dict:
        """Deepen CBR daily rates backwards to ``years``."""
        if self.cbr is None:
            raise ValueError("fx backfill needs a CBR client")
        today = _dt.date.today()
        frm = today.replace(year=today.year - years)
        added = 0
        for secid, (code, _name, pair) in FX_PAIRS.items():
            first = self.db.price_history_min_dt(secid, "fx")
            till = (_dt.date.fromisoformat(first) - _dt.timedelta(days=1)) if first else today
            if frm > till:
                continue
            rows = self.cbr.get_fx_history(code, frm, till)
            hist = [{"secid": secid, "market": "fx", "dt": d, "open": r, "high": r,
                     "low": r, "close": r, "volume": None, "value": None,
                     "yield": None, "numtrades": None} for d, r in rows]
            if hist:
                self.db.save_price_history(hist)
                added += len(hist)
            if progress:
                progress(f"  {pair}: +{len(hist)}")
        return {"fx": len(FX_PAIRS), "rows_added": added}

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

    def preload_fx(self, *, years: int = 5, progress=None) -> dict:
        """CBR official daily rates for USD/EUR/CNY → fx instruments + history."""
        if self.cbr is None:
            raise ValueError("preload_fx needs a CBR client")
        today = _dt.date.today()
        added = 0
        for secid, (code, name, pair) in FX_PAIRS.items():
            start = self.db.price_history_max_dt(secid, "fx")
            frm = (_dt.date.fromisoformat(start) + _dt.timedelta(days=1)) if start \
                else today.replace(year=today.year - years)
            rows = self.cbr.get_fx_history(code, frm, today) if frm <= today else []
            hist = [{"secid": secid, "market": "fx", "dt": d, "open": r, "high": r,
                     "low": r, "close": r, "volume": None, "value": None,
                     "yield": None, "numtrades": None} for d, r in rows]
            if hist:
                self.db.save_price_history(hist)
                added += len(hist)
            last, chg, as_of = self._last_change(self.db.get_price_history(secid, "fx"))
            ref = {"isin": None, "issuer_ru": name, "name_ru": f"{name} ({pair})",
                   "sec_type": "Курс ЦБ РФ", "list_level": None, "currency": "RUB",
                   "asset_code": pair, "last_trade_date": as_of,
                   "raw": [{"name": "pair", "title": "Валютная пара", "value": pair},
                           {"name": "code", "title": "Код ЦБ РФ", "value": code},
                           {"name": "source", "title": "Источник", "value": "ЦБ РФ (XML_dynamic)"}]}
            self._store_ref(secid, category="fx", market="fx", board="cbr",
                            ref=ref, last=last, change_pct=chg, as_of=as_of)
            if progress:
                progress(f"  {pair}: {len(hist)} rows, last={last}")
        return {"fx": len(FX_PAIRS), "rows_added": added}

    def preload_options(self, *, progress=None) -> dict:
        """Ingest the live FORTS option chain (one ref per underlying; the chain
        itself lives in option_quotes). Options have no single price series, so
        no history — the entity is the chain (strikes × expiries × call/put)."""
        today = _dt.date.today().isoformat()
        blocks = self.iss.get_blocks(
            "engines/futures/markets/options/securities", {"iss.meta": "off"})
        md = {r.get("SECID"): r for r in blocks.get("marketdata", [])}
        by_asset: dict[str, list] = {}
        for r in blocks.get("securities", []):
            sid, asset, exp = r.get("SECID"), r.get("ASSETCODE"), r.get("LASTTRADEDATE")
            if sid and asset and exp and exp >= today:     # live contracts only
                by_asset.setdefault(asset, []).append(r)

        underlyings = 0
        options = 0
        for asset, rows in by_asset.items():
            quotes = []
            for r in rows:
                sid = r["SECID"]
                m = md.get(sid, {})
                quotes.append({
                    "secid": sid, "asset_code": asset, "expiry": r.get("LASTTRADEDATE"),
                    "strike": _num(r.get("STRIKE")), "opt_type": r.get("OPTIONTYPE"),
                    "last": _num(m.get("LAST")), "settle": _num(m.get("SETTLEPRICE")) or _num(r.get("PREVSETTLEPRICE")),
                    "oi": _num(m.get("OPENPOSITION")), "volume": _num(m.get("VOLTODAY")),
                    "central_strike": _num(r.get("CENTRALSTRIKE")), "underlying": r.get("UNDERLYINGASSET"),
                })
            if not quotes:
                continue
            self.db.save_option_quotes(quotes)
            underlyings += 1
            options += len(quotes)
            expiries = sorted({q["expiry"] for q in quotes})
            central = next((q["central_strike"] for q in quotes if q["central_strike"]), None)
            ref = {"isin": None, "issuer_ru": f"{asset} — опционы", "name_ru": f"Опционы на {asset}",
                   "sec_type": "Опционы", "list_level": None, "currency": None, "asset_code": asset,
                   "last_trade_date": expiries[0] if expiries else None,
                   "raw": [{"name": "asset", "title": "Базовый актив", "value": asset},
                           {"name": "contracts", "title": "Контрактов в обращении", "value": str(len(quotes))},
                           {"name": "expiries", "title": "Серий (экспираций)", "value": str(len(expiries))},
                           {"name": "nearest", "title": "Ближайшая экспирация",
                            "value": expiries[0] if expiries else None},
                           {"name": "central", "title": "Центральный страйк",
                            "value": str(central) if central else None}]}
            self._store_ref(asset, category="options", market="options", board="forts",
                            ref=ref, last=central, change_pct=None, as_of=today, is_active=1)
            if progress and underlyings % 20 == 0:
                progress(f"  {underlyings} underlyings, {options} options")
        return {"underlyings": underlyings, "options": options}
