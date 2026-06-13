"""
MOEX ISS ingestion (ETL) per MOEX_MARKET_DATA_INTEGRATION_PROMPT.md §4.

MoexIngestor pulls ISS blocks via the injected IssClient and writes normalised
rows into the local MarketDataDB. Each job logs to ingest_log. The client is
injectable, so ingestion is unit-tested with fixtures (no network).

Verified endpoints (spec §2): G-curve /engines/stock/zcyc, bonds
/engines/stock/markets/bonds/boards/<board>/securities, FX
/statistics/engines/currency/markets/selt/rates.
"""

from __future__ import annotations

import math
from datetime import date, datetime

from curves.yield_curve import YieldCurve
from infra.db.market_data_db import MarketDataDB
from infra.moex_iss.calibration import (
    build_corporate_curve_points, build_corporate_curve_points_bucketed,
    issuer_spreads, representative_spread,
)
from infra.moex_iss.client import IssClient
from infra.moex_iss.validation import validate_curve_points

# ISS FX instrument ids -> canonical pair. The selt/rates document carries
# several quotes; map the ones we use. Column layout is tolerant (see _pick_rate).
FX_SECID_TO_PAIR = {
    "USDRUB_TOM": "USD/RUB", "USDTOM_UTS": "USD/RUB", "CBRF_USD": "USD/RUB",
    "EURRUB_TOM": "EUR/RUB", "CBRF_EUR": "EUR/RUB",
    "CNYRUB_TOM": "CNY/RUB",
}
_RATE_COLUMNS = ("CLOSEPRICE", "LAST", "WAPRICE", "PRICE", "RATE", "price", "rate")


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _pick_rate(row: dict) -> float | None:
    for col in _RATE_COLUMNS:
        if col in row:
            r = _to_float(row[col])
            if r is not None:
                return r
    return None


def extract_fx_rates(blocks: dict[str, list[dict]]) -> tuple[dict[str, float], dict[str, str]]:
    """
    Extract {pair: rate} and {pair: trade_time} from selt/rates blocks.

    Tolerant of block/column layout: scans every block for rows whose SECID maps
    to a known pair and reads the first available price column. Layout should be
    confirmed against live ISS on first run (spec §9).
    """
    rates: dict[str, float] = {}
    times: dict[str, str] = {}
    for rows in blocks.values():
        for row in rows:
            secid = row.get("SECID") or row.get("secid")
            if not secid or secid not in FX_SECID_TO_PAIR:
                continue
            rate = _pick_rate(row)
            if rate is None:
                continue
            pair = FX_SECID_TO_PAIR[secid]
            rates.setdefault(pair, rate)  # first occurrence wins (prefer market over CBR ordering)
            t = row.get("TRADETIME") or row.get("tradetime") or row.get("TRADEDATE")
            if t:
                times.setdefault(pair, str(t))
    return rates, times


class MoexIngestor:
    def __init__(self, client: IssClient, db: MarketDataDB):
        self.client = client
        self.db = db

    @staticmethod
    def snapshot_id_for(valuation_date: date) -> str:
        return f"moex-{valuation_date.isoformat()}"

    # -- G-curve (КБД) -----------------------------------------------------
    def ingest_gcurve(self, snapshot_id: str, valuation_date: date,
                      *, historical: bool = False) -> int:
        """historical=True requests the curve AS OF valuation_date (backfill)."""
        started = datetime.now()
        endpoint = "engines/stock/zcyc"
        try:
            params = {"iss.only": "yearyields,params"}
            if historical:
                params["date"] = valuation_date.isoformat()
            blocks = self.client.get_blocks(endpoint, params)
            yy = blocks.get("yearyields", [])
            points: list[tuple[float, float, float | None]] = []
            as_of = None
            for row in yy:
                tenor = _to_float(row.get("period"))
                pct = _to_float(row.get("value"))
                if tenor is None or pct is None or tenor <= 0:
                    continue
                zero = pct / 100.0  # ISS publishes percent; engine wants decimal continuous
                points.append((tenor, zero, math.exp(-zero * tenor)))
                as_of = as_of or row.get("tradedate")
            params_rows = blocks.get("params", [])
            nss = {}
            if params_rows:
                p = params_rows[0]
                nss = {k: _to_float(p.get(k)) for k in ("B1", "B2", "B3", "T1") if k in p}
                as_of = as_of or p.get("tradedate")
            points.sort(key=lambda x: x[0])
            self.db.save_curve(
                snapshot_id, "GCURVE_RUB",
                method="nss" if nss else "points",
                nss_params=nss,
                as_of=as_of or valuation_date,
                points=points,
            )
            self.db.log_ingest(endpoint, "ok", len(points), started, datetime.now())
            return len(points)
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    # -- FX ----------------------------------------------------------------
    def ingest_fx(self, snapshot_id: str, valuation_date: date) -> int:
        started = datetime.now()
        endpoint = "statistics/engines/currency/markets/selt/rates"
        try:
            blocks = self.client.get_blocks(endpoint)
            rates, times = extract_fx_rates(blocks)
            for pair, rate in rates.items():
                self.db.save_fx_rate(snapshot_id, pair, rate, source="MOEX",
                                     trade_time=times.get(pair))
            self.db.log_ingest(endpoint, "ok", len(rates), started, datetime.now())
            return len(rates)
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    # -- Bonds (board, e.g. TQOB for OFZ) ----------------------------------
    def ingest_bonds(self, snapshot_id: str, valuation_date: date, board: str = "TQOB") -> int:
        started = datetime.now()
        endpoint = f"engines/stock/markets/bonds/boards/{board}/securities"
        try:
            blocks = self.client.get_blocks(endpoint, {"iss.only": "securities,marketdata"})
            sec_by_id = {r.get("SECID"): r for r in blocks.get("securities", [])}
            md_by_id = {r.get("SECID"): r for r in blocks.get("marketdata", [])}
            count = 0
            for secid, sec in sec_by_id.items():
                if not secid:
                    continue
                self.db.save_instrument({
                    "secid": secid,
                    "isin": sec.get("ISIN"),
                    "board": board,
                    "type": "bond",
                    "currency": sec.get("CURRENCYID") or sec.get("FACEUNIT"),
                    "facevalue": _to_float(sec.get("FACEVALUE")),
                    "coupon_percent": _to_float(sec.get("COUPONPERCENT")),
                    "coupon_period": int(_to_float(sec.get("COUPONPERIOD")) or 0) or None,
                    "next_coupon": sec.get("NEXTCOUPON"),
                    "mat_date": sec.get("MATDATE"),
                    "offer_date": sec.get("OFFERDATE"),
                    "lot_size": _to_float(sec.get("LOTSIZE")),
                    "list_level": int(_to_float(sec.get("LISTLEVEL")) or 0) or None,
                    "issuer": sec.get("SECNAME"),
                    "sector": None,
                    "static_json": None,
                })
                md = md_by_id.get(secid, {})
                ytm_pct = _to_float(md.get("YIELD") or sec.get("YIELDATPREVWAPRICE"))
                self.db.save_bond_quote(snapshot_id, {
                    "secid": secid,
                    "clean_price": _to_float(md.get("LAST") or sec.get("PREVPRICE")),
                    "dirty_price": None,
                    "wap_price": _to_float(md.get("WAPRICE") or sec.get("PREVWAPRICE")),
                    "accruedint": _to_float(sec.get("ACCRUEDINT")),
                    "ytm": (ytm_pct / 100.0) if ytm_pct is not None else None,  # percent -> decimal
                    "volume": _to_float(md.get("VALTODAY")),
                    "board": board,
                })
                count += 1
            self.db.log_ingest(endpoint, "ok", count, started, datetime.now())
            return count
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    # -- Historical yields (time series) -----------------------------------
    def ingest_yield_history(
        self,
        secid: str,
        from_date: date,
        till_date: date | None = None,
        *,
        market: str = "bonds",
    ) -> int:
        """
        Ingest a security's historical yields into time_series (kind='yield').

        Spec §2: /iss/history/engines/stock/markets/<market>/yields/<secid>.
        Note: per the day-scoped fill instruction, pass from==till for a single
        date (e.g. 2026-06-02). Yields are stored as decimals.
        """
        started = datetime.now()
        till_date = till_date or from_date
        endpoint = f"history/engines/stock/markets/{market}/yields/{secid}"
        try:
            rows = self.client.get_block_paginated(
                endpoint, "history",
                {"from": from_date.isoformat(), "till": till_date.isoformat()},
            )
            points: list[tuple[str, float]] = []
            for row in rows:
                dt = row.get("TRADEDATE") or row.get("tradedate")
                pct = None
                for col in ("YIELDCLOSE", "YIELD", "CLOSEYIELD", "CLOSE", "yield"):
                    if col in row:
                        pct = _to_float(row[col])
                        if pct is not None:
                            break
                if dt and pct is not None:
                    points.append((str(dt), pct / 100.0))
            self.db.save_time_series(f"{secid}:yield", "yield", points)
            self.db.log_ingest(endpoint, "ok", len(points), started, datetime.now())
            return len(points)
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    # -- Equity price history (TQBR) -> time_series ------------------------
    def ingest_equity_history(
        self,
        secid: str,
        from_date: date,
        till_date: date | None = None,
        *,
        board: str = "TQBR",
    ) -> int:
        """
        Ingest a share's close-price history into time_series (kind='price').

        Spec §2: /history/engines/stock/markets/shares/boards/<board>/securities/<secid>.
        Day-scoped fill: pass from==till (e.g. 2026-06-02).
        """
        started = datetime.now()
        endpoint = f"history/engines/stock/markets/shares/boards/{board}/securities/{secid}"
        return self._ingest_price_history(
            endpoint, f"{secid}:price", from_date, till_date, started,
            price_cols=("CLOSE", "LEGALCLOSEPRICE", "WAPRICE", "close"),
        )

    # -- Index history (IMOEX / RVI / RTSI) -> time_series -----------------
    def ingest_index_history(
        self,
        indexid: str,
        from_date: date,
        till_date: date | None = None,
    ) -> int:
        """
        Ingest an index close-value history into time_series (kind='price').

        Spec §2: index values come from the index market history
        (/history/engines/stock/markets/index/securities/<indexid>), NOT /analytics.
        """
        started = datetime.now()
        endpoint = f"history/engines/stock/markets/index/securities/{indexid}"
        return self._ingest_price_history(
            endpoint, f"{indexid}:price", from_date, till_date, started,
            price_cols=("CLOSE", "close", "VALUE"),
        )

    def _ingest_price_history(self, endpoint, factor_id, from_date, till_date,
                              started, *, price_cols) -> int:
        till_date = till_date or from_date
        try:
            rows = self.client.get_block_paginated(
                endpoint, "history",
                {"from": from_date.isoformat(), "till": till_date.isoformat()},
            )
            points: list[tuple[str, float]] = []
            for row in rows:
                dt = row.get("TRADEDATE") or row.get("tradedate")
                price = None
                for col in price_cols:
                    if col in row:
                        price = _to_float(row[col])
                        if price is not None:
                            break
                if dt and price is not None:
                    points.append((str(dt), price))
            self.db.save_time_series(factor_id, "price", points)
            self.db.log_ingest(endpoint, "ok", len(points), started, datetime.now())
            return len(points)
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    # -- Equity current quotes (TQBR) -> equity_quotes ---------------------
    def ingest_equity_quotes(self, snapshot_id: str, valuation_date: date,
                             *, board: str = "TQBR") -> int:
        """Ingest current share quotes (spot) into equity_quotes."""
        started = datetime.now()
        endpoint = f"engines/stock/markets/shares/boards/{board}/securities"
        try:
            blocks = self.client.get_blocks(endpoint, {"iss.only": "securities,marketdata"})
            sec = {r.get("SECID"): r for r in blocks.get("securities", [])}
            md = {r.get("SECID"): r for r in blocks.get("marketdata", [])}
            count = 0
            for secid, s in sec.items():
                if not secid:
                    continue
                m = md.get(secid, {})
                self.db.save_equity_quote(snapshot_id, {
                    "secid": secid,
                    "last": _to_float(m.get("LAST") or m.get("LCLOSEPRICE")),
                    "prevprice": _to_float(s.get("PREVPRICE") or m.get("LCLOSEPRICE")),
                    "board": board,
                    "volume": _to_float(m.get("VALTODAY")),
                })
                count += 1
            self.db.log_ingest(endpoint, "ok", count, started, datetime.now())
            return count
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    # -- Corporate curves (issuer/sector spreads over КБД) -----------------
    def ingest_corporate_curves(
        self,
        snapshot_id: str,
        valuation_date: date,
        *,
        min_bonds: int = 3,
    ) -> int:
        """Calibrate CORP_T1/T2/T3 curves = GCURVE_RUB + tier spread from bonds."""
        started = datetime.now()
        endpoint = "calibration/corporate_curves"
        try:
            gpts = self.db.get_curve_points(snapshot_id, "GCURVE_RUB")
            if len(gpts) < 3:
                self.db.log_ingest(endpoint, "skipped", 0, started, datetime.now(),
                                   "no GCURVE_RUB to calibrate against")
                return 0
            gcurve = YieldCurve(
                [p["tenor"] for p in gpts], [p["zero_rate"] for p in gpts],
                label="GCURVE_RUB", interp="cubic", rate_type="zero",
            )
            bonds = self.db.get_calibration_bonds(snapshot_id)
            spreads = issuer_spreads(gcurve, bonds, valuation_date)
            saved = 0
            wide_universe = len(spreads) > 50      # TQCB-scale: bucketed medians
            for tier in ("T1", "T2", "T3"):
                if wide_universe:
                    pts = build_corporate_curve_points_bucketed(
                        gcurve, spreads, tier, min_bonds_per_bucket=min_bonds)
                else:
                    pts = build_corporate_curve_points(gcurve, spreads, tier, min_bonds=min_bonds)
                if not pts:
                    continue
                pts_df = [(t, z, math.exp(-z * t)) for (t, z, _) in pts]
                if validate_curve_points(pts_df):
                    continue  # skip a tier that would poison the snapshot
                self.db.save_curve(
                    snapshot_id, f"CORP_{tier}", method="govt+spread",
                    nss_params={"mean_spread": representative_spread(spreads, tier)},
                    as_of=valuation_date, points=pts_df,
                )
                saved += 1
            self.db.log_ingest(endpoint, "ok", saved, started, datetime.now())
            return saved
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    # -- FORTS option vol surface -> vol_points ----------------------------
    def ingest_option_vol_surface(self, snapshot_id: str, valuation_date: date) -> int:
        """
        FORTS option implied vols into vol_points (Stage I.5 rewrite).

        EOD marketdata publishes NO volatility field (intraday-only), so vols
        are SELF-IMPLIED from settlement prices via Black-76 against the
        underlying futures settle (infra.moex_iss.vol_surface.imply_option_vols),
        with open-interest / moneyness / expiry quality filters.
        """
        from infra.moex_iss.vol_surface import imply_option_vols, normalise_option_rows

        started = datetime.now()
        endpoint = "engines/futures/markets/options/securities"
        try:
            opt = self.client.get_blocks(endpoint, {"iss.only": "securities,marketdata"})
            fut = self.client.get_blocks("engines/futures/markets/forts/securities",
                                         {"iss.only": "securities,marketdata"})
            points = imply_option_vols(
                opt.get("securities", []), opt.get("marketdata", []),
                fut.get("securities", []), fut.get("marketdata", []),
                valuation_date,
            )
            if not points:
                # legacy path: keep accepting intraday rows that DO carry IV
                merged: list[dict] = []
                md = {r.get("SECID"): r for r in opt.get("marketdata", [])}
                for sec in opt.get("securities", []):
                    row = dict(sec)
                    row.update(md.get(sec.get("SECID"), {}))
                    merged.append(row)
                points = normalise_option_rows(merged)
            for p in points:
                self.db.save_vol_point(snapshot_id, p["underlying"], p["expiry"],
                                       p["strike"], p["iv"])
            self.db.log_ingest(endpoint, "ok", len(points), started, datetime.now())
            return len(points)
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    # -- Real curve from OFZ-IN linkers (Stage I.3) -------------------------
    def ingest_real_curve(self, snapshot_id: str, valuation_date: date) -> int:
        """
        Real (inflation-adjusted) zero curve from OFZ-IN linkers (SU52*): the
        exchange quotes their YIELD off the indexed nominal, i.e. a real yield.
        Stored as REALCURVE_OFZIN with continuous compounding.
        """
        started = datetime.now()
        endpoint = "engines/stock/markets/bonds/boards/TQOB/securities"
        try:
            blocks = self.client.get_blocks(endpoint, {"iss.only": "securities,marketdata"})
            md_by_id = {r.get("SECID"): r for r in blocks.get("marketdata", [])}
            points = []
            for sec in blocks.get("securities", []):
                secid = str(sec.get("SECID") or "")
                if not secid.startswith("SU52"):
                    continue
                mat = sec.get("MATDATE")
                try:
                    tenor = (date.fromisoformat(str(mat)[:10]) - valuation_date).days / 365.0
                except (TypeError, ValueError):
                    continue
                md = md_by_id.get(secid, {})
                y_pct = _to_float(md.get("YIELD") or sec.get("YIELDATPREVWAPRICE"))
                if tenor <= 0 or y_pct is None or not -5 < y_pct < 30:
                    continue
                z = math.log(1.0 + y_pct / 100.0)        # effective -> continuous
                points.append((tenor, z, math.exp(-z * tenor)))
            points.sort(key=lambda p: p[0])
            if points:
                self.db.save_curve(snapshot_id, "REALCURVE_OFZIN", method="linker_yields",
                                   nss_params={}, as_of=valuation_date, points=points)
            self.db.log_ingest(endpoint + ":real", "ok", len(points), started, datetime.now())
            return len(points)
        except Exception as exc:
            self.db.log_ingest(endpoint + ":real", "error", 0, started, datetime.now(), str(exc))
            raise

    # -- FX forward curve from FORTS futures strips (Stage I.4) -------------
    FX_FUTURES_ASSETS = {"Si": "USD/RUB", "CNY": "CNY/RUB", "CR": "CNY/RUB", "Eu": "EUR/RUB"}

    def ingest_fx_futures(self, snapshot_id: str, valuation_date: date,
                          spot_rates: dict[str, float] | None = None) -> int:
        """
        FX forward curves from futures settlement strips: implied carry
        c(T) = ln(F/S)/T per expiry, stored as FXFWD_<CCY> (zero_rate = carry).
        spot_rates: {"USD/RUB": fix, ...}; the nearest future anchors the curve
        when no spot is supplied.
        """
        started = datetime.now()
        endpoint = "engines/futures/markets/forts/securities"
        try:
            blocks = self.client.get_blocks(endpoint, {"iss.only": "securities,marketdata"})
            md_by_id = {r.get("SECID"): r for r in blocks.get("marketdata", [])}
            strips: dict[str, list[tuple[float, float]]] = {}
            for sec in blocks.get("securities", []):
                asset = str(sec.get("ASSETCODE") or "")
                pair = self.FX_FUTURES_ASSETS.get(asset)
                if pair is None:
                    continue
                try:
                    expiry = date.fromisoformat(str(sec.get("LASTTRADEDATE"))[:10])
                except (TypeError, ValueError):
                    continue
                T = (expiry - valuation_date).days / 365.0
                md = md_by_id.get(sec.get("SECID"), {})
                settle = _to_float(md.get("SETTLEPRICE")) or _to_float(sec.get("PREVSETTLEPRICE"))
                if T <= 2 / 365.0 or not settle or settle <= 0:
                    continue
                strips.setdefault(pair, []).append((T, settle))

            spot_rates = spot_rates or {}
            saved = 0
            for pair, pts in strips.items():
                pts.sort(key=lambda p: p[0])
                # Si futures quote RUB per 1000 USD historically — normalise by
                # comparing the front contract to spot when available.
                spot = spot_rates.get(pair)
                scale = 1.0
                if spot and pts and pts[0][1] / spot > 100:
                    scale = 1000.0
                outrights = [(T, F / scale) for T, F in pts]
                anchor = spot or outrights[0][1]
                curve_pts = []
                for T, F in outrights:
                    carry = math.log(F / anchor) / T if T > 0 else 0.0
                    if abs(carry) > 1.0:
                        continue                      # poisoned print
                    curve_pts.append((T, carry, math.exp(-carry * T)))
                if not curve_pts:
                    continue
                ccy = pair.split("/")[0]
                self.db.save_curve(
                    snapshot_id, f"FXFWD_{ccy}", method="futures_strip",
                    nss_params={"pair": pair, "spot": anchor,
                                "spot_source": "fix" if spot else "front_future",
                                "outrights": {f"{T:.4f}": F for T, F in outrights}},
                    as_of=valuation_date, points=curve_pts)
                saved += 1
            self.db.log_ingest(endpoint + ":fxfwd", "ok", saved, started, datetime.now())
            return saved
        except Exception as exc:
            self.db.log_ingest(endpoint + ":fxfwd", "error", 0, started, datetime.now(), str(exc))
            raise

    # -- Commodity futures curves (Stage V.4) ------------------------------
    COMMODITY_ASSETS = ("BR", "NG", "GOLD", "SILV", "PLT", "SUGAR", "CU")

    def ingest_commodity_futures(self, snapshot_id: str, valuation_date: date) -> int:
        """
        Commodity futures settlement strips (Brent/gas/metals/sugar) into
        commodity_quotes — the price curve to complement the vols already implied
        from their options. One row per contract (asset, expiry, settle, OI).
        """
        started = datetime.now()
        endpoint = "engines/futures/markets/forts/securities:commodity"
        try:
            blocks = self.client.get_blocks(
                "engines/futures/markets/forts/securities",
                {"iss.only": "securities,marketdata"})
            md = {r.get("SECID"): r for r in blocks.get("marketdata", [])}
            rows = []
            for sec in blocks.get("securities", []):
                asset = str(sec.get("ASSETCODE") or "")
                if asset not in self.COMMODITY_ASSETS:
                    continue
                m = md.get(sec.get("SECID"), {})
                settle = _to_float(m.get("SETTLEPRICE")) or _to_float(sec.get("PREVSETTLEPRICE"))
                if settle is None or settle <= 0:
                    continue
                rows.append({
                    "asset": asset, "secid": sec.get("SECID"),
                    "expiry": sec.get("LASTTRADEDATE"), "settle": settle,
                    "open_interest": _to_float(m.get("OPENPOSITION")) or _to_float(sec.get("PREVOPENPOSITION")),
                    "volume": _to_float(m.get("VOLTODAY")),
                })
            self.db.save_commodity_quotes(snapshot_id, rows)
            self.db.log_ingest(endpoint, "ok", len(rows), started, datetime.now())
            return len(rows)
        except Exception as exc:
            self.db.log_ingest(endpoint, "error", 0, started, datetime.now(), str(exc))
            raise

    # -- Dividends (Stage V.4) ---------------------------------------------
    def ingest_dividends(self, secids: list[str]) -> int:
        """Dividend history per security into the dividends table (static data)."""
        started = datetime.now()
        endpoint = "securities/{secid}/dividends"
        saved = 0
        errors: list[str] = []
        for secid in secids:
            try:
                blocks = self.client.get_blocks(f"securities/{secid}/dividends", {})
                rows = [{"registry_date": r.get("registryclosedate"),
                         "value": _to_float(r.get("value")),
                         "currency": r.get("currencyid")}
                        for r in blocks.get("dividends", []) if r.get("registryclosedate")]
                if rows:
                    self.db.save_dividends(secid, rows)
                    saved += 1
            except Exception as exc:
                errors.append(f"{secid}: {exc}")
        self.db.log_ingest(endpoint, "ok" if not errors else "partial", saved,
                           started, datetime.now(), "; ".join(errors[:5]))
        return saved

    # -- Bondization: coupon / amortization / offer schedules (Stage I.6) ---
    def ingest_bondization(self, secids: list[str]) -> int:
        """Coupon schedules, amortizations and offers per security (static data)."""
        started = datetime.now()
        endpoint = "securities/{secid}/bondization"
        saved = 0
        errors: list[str] = []
        for secid in secids:
            try:
                blocks = self.client.get_blocks(
                    f"securities/{secid}/bondization",
                    {"iss.only": "coupons,amortizations,offers", "limit": "unlimited"})
                coupons = [{"date": r.get("coupondate"), "value": _to_float(r.get("value")),
                            "value_prc": _to_float(r.get("valueprc"))}
                           for r in blocks.get("coupons", []) if r.get("coupondate")]
                amorts = [{"date": r.get("amortdate"), "value": _to_float(r.get("value")),
                           "face_remaining": _to_float(r.get("facevalue"))}
                          for r in blocks.get("amortizations", []) if r.get("amortdate")]
                offers = [{"date": r.get("offerdate"), "price": _to_float(r.get("price")),
                           "offer_type": r.get("offertype")}
                          for r in blocks.get("offers", []) if r.get("offerdate")]
                if coupons or amorts or offers:
                    self.db.save_bond_schedule(secid, coupons=coupons,
                                               amortizations=amorts, offers=offers)
                    saved += 1
            except Exception as exc:               # isolate per-security failures
                errors.append(f"{secid}: {exc}")
        self.db.log_ingest(endpoint, "ok" if not errors else "partial", saved,
                           started, datetime.now(), "; ".join(errors[:5]))
        return saved

    def ingest_all(self, valuation_date: date, *, board: str = "TQOB") -> dict[str, int]:
        sid = self.snapshot_id_for(valuation_date)
        result = {
            "gcurve": self.ingest_gcurve(sid, valuation_date),
            "fx": self.ingest_fx(sid, valuation_date),
            "bonds": self.ingest_bonds(sid, valuation_date, board=board),
        }
        result["corporate"] = self.ingest_corporate_curves(sid, valuation_date)
        return result
