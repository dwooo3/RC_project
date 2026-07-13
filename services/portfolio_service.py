"""Portfolio workflow service."""

from collections import defaultdict
import math

from domain.market_data import MarketDataSnapshot
from domain.portfolio import Portfolio, PortfolioRiskResult, PortfolioValuationResult, Position
from domain.risk_factors import RiskFactor, RiskFactorExposure, RiskFactorBucket, RiskFactorGroup
from domain.results import PnLExplainResult
from domain.scenario import Scenario, ScenarioResult, ScenarioShock, ScenarioShockType, ScenarioType
from services.audit_service import AuditService
from services.market_data_service import MarketDataService
from services.pricing_service import PricingService


EXPOSURE_BUCKETS: tuple[RiskFactorBucket, ...] = (
    "Rates",
    "FX",
    "Equity",
    "Credit",
    "Volatility",
)


CANONICAL_RISK_FACTORS: dict[str, RiskFactor] = {
    "rates.yield_curve": RiskFactor(
        factor_id="rates.yield_curve",
        name="Yield Curve",
        bucket="Rates",
        factor_type="yield_curve",
        currency="RUB",
        unit="DV01",
        bump_size=0.0001,
    ),
    "rates.swap_curve": RiskFactor(
        factor_id="rates.swap_curve",
        name="Swap Curve",
        bucket="Rates",
        factor_type="swap_curve",
        currency="RUB",
        unit="DV01",
        bump_size=0.0001,
    ),
    "rates.risk_free_rate": RiskFactor(
        factor_id="rates.risk_free_rate",
        name="Risk-Free Rate",
        bucket="Rates",
        factor_type="rate",
        currency="RUB",
        unit="Rho",
        bump_size=0.01,
    ),
    "fx.spot": RiskFactor(
        factor_id="fx.spot",
        name="FX Spot",
        bucket="FX",
        factor_type="fx_spot",
        unit="FX Delta",
        bump_size=1.0,
    ),
    "equity.spot": RiskFactor(
        factor_id="equity.spot",
        name="Equity Spot",
        bucket="Equity",
        factor_type="spot",
        unit="Delta",
        bump_size=1.0,
    ),
    "equity.spot_gamma": RiskFactor(
        factor_id="equity.spot_gamma",
        name="Equity Spot Gamma",
        bucket="Equity",
        factor_type="spot_gamma",
        unit="Gamma",
        bump_size=1.0,
    ),
    "credit.spread": RiskFactor(
        factor_id="credit.spread",
        name="Credit Spread",
        bucket="Credit",
        factor_type="credit_spread",
        unit="CS01",
        bump_size=0.0001,
    ),
    "vol.implied": RiskFactor(
        factor_id="vol.implied",
        name="Implied Volatility",
        bucket="Volatility",
        factor_type="implied_vol",
        unit="Vega",
        bump_size=0.01,
    ),
}


class PortfolioService:
    """Owns portfolio pricing, risk-factor exposure aggregation, and scenario P&L."""

    def __init__(
        self,
        portfolio: Portfolio | str | None = None,
        market_data: MarketDataService | None = None,
        pricing: PricingService | None = None,
        audit: AuditService | None = None,
        snapshot: MarketDataSnapshot | None = None,
    ):
        if isinstance(portfolio, Portfolio):
            self.portfolio = portfolio
        elif isinstance(portfolio, str):
            self.portfolio = Portfolio(portfolio)
        else:
            self.portfolio = Portfolio()
        # A supplied PricingService may already own the intended market-data
        # service (common in tests and filtered/what-if books).  Reusing it
        # avoids constructing a disconnected DEMO service behind the portfolio.
        self.market_data = (
            market_data or getattr(pricing, "market_data", None) or MarketDataService()
        )
        self.audit = audit or getattr(pricing, "audit", None) or AuditService()
        self.pricing = pricing or PricingService(market_data=self.market_data, audit=self.audit)
        self.snapshot: MarketDataSnapshot | None = None
        self.bind_snapshot(snapshot)

    @property
    def positions(self) -> list[Position]:
        return self.portfolio.positions

    def add(self, pos: Position):
        if self.snapshot is not None:
            pos.market_data_snapshot_id = self.snapshot.snapshot_id
        self.portfolio.add(pos)

    def remove(self, position_id: str):
        self.portfolio.remove(position_id)

    # ── Persistence (Phase 4) ─────────────────────────────

    def save_to_db(self, db) -> str:
        """Persist the portfolio book (header + positions) to an AppDB."""
        db.save_portfolio(self.portfolio)
        return self.portfolio.portfolio_id

    @classmethod
    def load_from_db(cls, db, portfolio_id: str,
                     market_data: MarketDataService | None = None,
                     pricing: PricingService | None = None,
                     audit: AuditService | None = None,
                     snapshot: MarketDataSnapshot | None = None) -> "PortfolioService":
        """Rehydrate a PortfolioService from a persisted portfolio."""
        portfolio = db.load_portfolio(portfolio_id)
        return cls(portfolio, market_data=market_data, pricing=pricing, audit=audit,
                   snapshot=snapshot)

    def bind_snapshot(self, snapshot: MarketDataSnapshot | None) -> None:
        """Bind the valuation contour used by named curve/surface references.

        The snapshot object is deliberately runtime-only: curve/surface objects
        must never be serialized into position params.  The portfolio header and
        positions retain the immutable snapshot identity for audit/reporting.
        """
        self.snapshot = snapshot
        if snapshot is None:
            return
        self.portfolio.market_data_snapshot_id = snapshot.snapshot_id
        self.portfolio.valuation_date = snapshot.valuation_date
        for position in self.portfolio.positions:
            position.market_data_snapshot_id = snapshot.snapshot_id

    # ── Full-reprice scenario P&L (Phase 4) ───────────────

    _SPOT_KEYS = ("S", "S0", "S1", "S2", "spot")
    _RATE_KEYS = ("r", "r_d", "repo_rate", "rate", "discount_rate", "forward_rate")
    _VOL_KEYS = ("sigma", "vol", "sigma1", "sigma2")
    _CURVE_INSTRUMENTS = {
        "bond", "irs", "swap", "frn", "fra", "cap", "floor",
        "cap_floor", "swaption",
    }

    @staticmethod
    def _component_factor_ids(params: dict) -> list[str]:
        """Return aligned component identities for capturable multi-assets.

        ``component_secids`` is the canonical capture field. ``asset_ids`` is
        accepted as a compatibility alias for positions produced by earlier
        corrective builds. Schedule tokens may carry the workstation's legacy
        ``SECID:weight`` suffix; risk routing only needs the SECID part.
        """
        raw = (params or {}).get("component_secids")
        if raw in (None, "", []):
            raw = (params or {}).get("asset_ids")
        if raw in (None, "", []):
            return []
        values = raw if isinstance(raw, (list, tuple)) else str(raw).replace(";", ",").split(",")
        out = []
        for value in values:
            if isinstance(value, dict):
                value = value.get("secid") or value.get("id") or ""
            token = str(value).strip().split(":", 1)[0].strip()
            if token:
                out.append(token)
        return out

    @staticmethod
    def _position_tenor(params: dict) -> float:
        """Maturity anchor for the rate shock: T, or expiry+tenor for swaptions."""
        if not params:
            return 5.0
        if isinstance(params.get("T"), (int, float)):
            return float(params["T"])
        if isinstance(params.get("T2"), (int, float)):
            return float(params["T2"])
        t_opt = params.get("T_option")
        t_swap = params.get("T_swap")
        if isinstance(t_opt, (int, float)) and isinstance(t_swap, (int, float)):
            return float(t_opt) + float(t_swap)
        return 5.0

    @staticmethod
    def _position_curve_interval(instrument: str | None, params: dict) -> tuple[float, float]:
        """Positive curve times actually requested by the instrument pricer."""
        upper = PortfolioService._position_tenor(params)
        inst = str(instrument or "").lower()
        if inst == "fra":
            candidates = [params.get("T1"), params.get("T2")]
            positive = [float(value) for value in candidates
                        if isinstance(value, (int, float)) and float(value) > 0]
            lower = min(positive, default=upper)
        elif inst == "swaption":
            lower = float(params.get("T_option", upper))
        elif inst in {"irs", "swap"}:
            lower = 1.0 / float(params.get("freq", 4))
        elif inst in {"bond", "frn", "cap", "floor", "cap_floor"}:
            lower = 1.0 / float(params.get("freq", 2))
        else:
            lower = upper
        if (not math.isfinite(lower) or not math.isfinite(upper)
                or lower <= 0 or upper <= 0 or lower > upper + 1e-10):
            raise ValueError("position has invalid curve support interval")
        return lower, upper

    def _require_snapshot(self, reference: str) -> MarketDataSnapshot:
        if self.snapshot is None:
            raise ValueError(
                f"{reference} requires a bound market-data snapshot")
        return self.snapshot

    def _resolve_curve_object(
        self,
        params: dict,
        *,
        object_key: str = "curve",
        id_key: str = "curve_id",
        rate_key: str | None = "r",
        instrument: str | None = None,
    ):
        explicit = params.get(object_key)
        if explicit is not None:
            curve = explicit
            reference = str(params.get(id_key) or object_key)
        elif params.get(id_key):
            curve_id = params[id_key]
            snapshot = self._require_snapshot(f"curve '{curve_id}'")
            try:
                curve = self.market_data.get_curve(str(curve_id), snapshot)
            except KeyError as exc:
                raise ValueError(
                    f"curve '{curve_id}' is absent from snapshot "
                    f"'{snapshot.snapshot_id}'") from exc
            reference = str(curve_id)
        elif rate_key is None:
            return None
        else:
            if not isinstance(params.get(rate_key), (int, float)):
                raise ValueError(
                    f"position has neither {id_key} nor numeric {rate_key}")
            curve = self.market_data.flat_curve(float(params[rate_key]))
            reference = f"flat {rate_key}"

        # Named curves are executable dependencies.  Silent right-tail
        # extrapolation is unsafe for projected cashflows (for example a 3M
        # RUONIA stub used for a 5Y IRS), so require native tenor coverage.
        tenors = getattr(curve, "tenors", None)
        required_lower, required_upper = self._position_curve_interval(
            instrument, params)
        if tenors is not None and len(tenors):
            min_tenor = min(float(value) for value in tenors)
            max_tenor = max(float(value) for value in tenors)
            if (not math.isfinite(min_tenor) or not math.isfinite(max_tenor)
                    or required_lower < min_tenor - 1e-10):
                raise ValueError(
                    f"curve '{reference}' tenor coverage starts at "
                    f"{min_tenor:.6g}Y, above first required "
                    f"{required_lower:.6g}Y")
            if required_upper > max_tenor + 1e-10:
                raise ValueError(
                    f"curve '{reference}' tenor coverage ends at "
                    f"{max_tenor:.6g}Y, below required {required_upper:.6g}Y")
        return curve

    @staticmethod
    def _require_exact_curve_scenario_coverage(
        curve, moves: list | None, required_tenor: float, reference: str,
    ) -> None:
        """Reject an exact node map that would require shift extrapolation."""
        if not moves:
            raise ValueError(
                f"historical scenario has no node shifts for curve '{reference}'")
        try:
            shock_tenors = [float(tenor) for tenor, _move in moves]
            curve_tenors = [float(tenor) for tenor in curve.tenors]
        except (TypeError, ValueError, OverflowError, AttributeError) as exc:
            raise ValueError(
                f"historical scenario has invalid node shifts for curve "
                f"'{reference}'") from exc
        if (not shock_tenors or not curve_tenors
                or not all(math.isfinite(value) for value in shock_tenors)):
            raise ValueError(
                f"historical scenario has invalid node shifts for curve "
                f"'{reference}'")
        lower_required = min(curve_tenors)
        if min(shock_tenors) > lower_required + 1e-10:
            raise ValueError(
                f"historical node shifts for curve '{reference}' start at "
                f"{min(shock_tenors):.6g}Y, above native lower support "
                f"{lower_required:.6g}Y")
        upper_required = max(curve_tenors)
        if max(shock_tenors) < upper_required - 1e-10:
            raise ValueError(
                f"historical node shifts for curve '{reference}' end at "
                f"{max(shock_tenors):.6g}Y, below native upper support "
                f"{upper_required:.6g}Y")

    @staticmethod
    def _shift_curve_object(curve, dr: float, dr_curve: list | None):
        """Apply one historical curve scenario to every native curve node."""
        if not dr_curve:
            return curve.parallel_shift(float(dr) * 10000.0)

        import numpy as _np

        from curves.yield_curve import YieldCurve

        pairs = sorted((float(tenor), float(move)) for tenor, move in dr_curve)
        tenors = _np.asarray([tenor for tenor, _ in pairs], dtype=float)
        if len(tenors) != len(_np.unique(tenors)):
            raise ValueError("dr_curve tenors must be unique")
        moves = _np.asarray([move for _, move in pairs], dtype=float)
        node_moves = _np.interp(curve.tenors, tenors, moves)
        return YieldCurve(
            curve.tenors,
            curve.zero_rates + node_moves,
            label=f"{curve.label}+historical-node-shift",
            interp=getattr(curve, "_interp", "linear"),
            source=curve.source,
            valuation_date=curve.valuation_date,
            rate_type=curve.rate_type,
            compounding=curve.compounding,
            day_count=curve.day_count,
            metadata=dict(curve.metadata),
        )

    def _bind_scenario_curves(
        self,
        base: Position,
        shocked: Position,
        *,
        dr: float,
        dr_curve: list | None,
        dr_curves: dict | None,
    ) -> bool:
        """Resolve runtime-only discount/projection objects for one position.

        Returns True when the discount curve is object/ID-bound, in which case
        the scalar ``r`` field must not also be bumped.
        """
        if base.instrument not in self._CURVE_INSTRUMENTS:
            return False

        params = base.params or {}
        required_tenor = self._position_tenor(params)
        discount_bound = bool(params.get("curve") is not None or params.get("curve_id"))
        if discount_bound:
            curve = self._resolve_curve_object(params, instrument=base.instrument)
            curve_id = params.get("curve_id")
            curve_scenario = dr_curve
            if curve_id and dr_curves is not None:
                if str(curve_id) not in dr_curves:
                    raise ValueError(
                        f"historical scenario has no node shifts for curve "
                        f"'{curve_id}'")
                curve_scenario = dr_curves[str(curve_id)]
                self._require_exact_curve_scenario_coverage(
                    curve, curve_scenario, required_tenor, str(curve_id))
            base.params["curve"] = curve
            shocked.params["curve"] = self._shift_curve_object(
                curve, dr, curve_scenario)

        projection_bound = bool(
            params.get("proj_curve") is not None or params.get("proj_curve_id"))
        if projection_bound:
            projection = self._resolve_curve_object(
                params, object_key="proj_curve", id_key="proj_curve_id",
                rate_key=None, instrument=base.instrument)
            projection_id = params.get("proj_curve_id")
            projection_scenario = dr_curve
            if projection_id and dr_curves is not None:
                if str(projection_id) not in dr_curves:
                    raise ValueError(
                        f"historical scenario has no node shifts for curve "
                        f"'{projection_id}'")
                projection_scenario = dr_curves[str(projection_id)]
                self._require_exact_curve_scenario_coverage(
                    projection, projection_scenario, required_tenor,
                    str(projection_id))
            base.params["proj_curve"] = projection
            shocked.params["proj_curve"] = self._shift_curve_object(
                projection, dr, projection_scenario)
        return discount_bound

    def _resolve_surface_vol(self, params: dict) -> tuple[float, str | None]:
        surface_id = params.get("vol_surface_id")
        if not surface_id:
            return float(params["sigma"]), None
        snapshot = self._require_snapshot(f"vol surface '{surface_id}'")
        try:
            return self.pricing.resolve_vol_surface(
                str(surface_id), float(params["K"]), float(params["T"]),
                S=float(params["S"]), snapshot=snapshot)
        except KeyError as exc:
            raise ValueError(
                f"vol surface '{surface_id}' is absent from snapshot "
                f"'{snapshot.snapshot_id}'") from exc

    def full_reprice_pnl(self, dS: float = 0.0, dr: float = 0.0,
                         dvol: float = 0.0, dfx: float = 0.0,
                         dr_curve: list | None = None,
                         dS_by_name: dict | None = None,
                         dvol_by_name: dict | None = None,
                         dfx_by_pair: dict | None = None,
                         spot_shock_convention: str = "simple",
                         strict: bool = True,
                         dr_curves: dict | None = None,
                         dvol_by_position: dict | None = None) -> dict:
        """
        FULL-REPRICE portfolio P&L under a joint factor shock — every position
        is repriced through its actual pricer with shocked params, no
        delta-gamma approximation. Shocks: dS relative equity/spot move, dr
        absolute rate move, dvol absolute vol move, dfx relative FX move
        (applied to spot-like params of FX instruments).

        Гранулярная факторная карта (validation report M2/M3):
        * ``dr_curve`` — [(tenor, dr)]: named discount/projection curves
          receive an interpolated shift at every native node. Legacy scalar-r
          positions retain the maturity-bucket approximation;
        * ``dr_curves`` — {curve_id: [(tenor, dr), ...]}: historical nodes
          routed to the exact named discount/projection dependency.  When this
          typed map is supplied, a missing named curve is an error rather than
          a fallback to the generic RUB KBD scenario;
        * ``dS_by_name`` — {secid: dS}: акция/бонд с ``params["secid"]``
          шокируется собственным рядом, прочие — общим dS;
        * ``dvol_by_name`` — {secid: dvol}: implied-vol shock выбранного
          underlying. Для spread/basket component SECIDs маршрутизируют
          отдельные ``sigma1/sigma2`` или элементы ``sigmas``;
        * ``dvol_by_position`` — {position_id: dvol}: governed historical
          surface-node move for the position's exact ``vol_surface_id``/K/T.
          A named surface missing from this typed map is an error;
        * ``dfx_by_pair`` — {"USD/RUB": dfx}: FX-позиция шокируется своим
          курсом по ``ccy_pair``.
        * ``spot_shock_convention`` — ``"simple"`` для явных stress/what-if
          shocks (default) или ``"log"`` для исторических equity/FX returns.
          Log-returns преобразуются в simple shocks через ``expm1``
          на границе full repricing; rates/vol не затрагиваются.
        """
        import copy

        import numpy as _np

        if spot_shock_convention not in {"simple", "log"}:
            raise ValueError("spot_shock_convention must be 'simple' or 'log'")

        def _finite_scalar(value, label: str) -> float:
            try:
                array = _np.asarray(value)
                if array.ndim != 0:
                    raise TypeError
                number = float(array)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"{label} must be a finite scalar") from exc
            if not math.isfinite(number):
                raise ValueError(f"{label} is non-finite")
            return number

        dS = _finite_scalar(dS, "dS shock")
        dr = _finite_scalar(dr, "dr shock")
        dvol = _finite_scalar(dvol, "dvol shock")
        dfx = _finite_scalar(dfx, "dfx shock")

        def _finite_map(values, label: str):
            if values is None:
                return None
            if not isinstance(values, dict):
                raise ValueError(f"{label} must be a mapping")
            return {
                key: _finite_scalar(value, f"{label}[{key!r}]")
                for key, value in values.items()
            }

        dS_by_name = _finite_map(dS_by_name, "dS_by_name")
        dvol_by_name = _finite_map(dvol_by_name, "dvol_by_name")
        dfx_by_pair = _finite_map(dfx_by_pair, "dfx_by_pair")
        dvol_by_position = _finite_map(
            dvol_by_position, "dvol_by_position")

        def _curve_nodes(values, label: str, *, allow_empty: bool):
            if values is None:
                return None
            try:
                rows = list(values)
            except TypeError as exc:
                raise ValueError(f"{label} must be a sequence of tenor shocks") from exc
            if not rows:
                if allow_empty:
                    return []
                raise ValueError(f"{label} has no node shifts")
            parsed = []
            seen = set()
            for index, row in enumerate(rows):
                try:
                    tenor, move = row
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"{label}[{index}] must contain tenor and shock") from exc
                tenor = _finite_scalar(tenor, f"{label}[{index}] tenor")
                move = _finite_scalar(move, f"{label}[{index}] shock")
                if tenor <= 0:
                    raise ValueError(f"{label}[{index}] tenor must be positive")
                if tenor in seen:
                    raise ValueError(f"{label} tenors must be unique")
                seen.add(tenor)
                parsed.append((tenor, move))
            return parsed

        dr_curve = _curve_nodes(dr_curve, "dr_curve", allow_empty=True)
        if dr_curves is not None:
            if not isinstance(dr_curves, dict):
                raise ValueError("dr_curves must be a mapping")
            dr_curves = {
                curve_id: _curve_nodes(
                    nodes, f"dr_curves[{curve_id!r}]", allow_empty=False)
                for curve_id, nodes in dr_curves.items()
            }

        def _simple_spot_shock(value: float, label: str = "spot shock") -> float:
            value = _finite_scalar(value, label)
            if spot_shock_convention == "log":
                try:
                    value = math.expm1(value)
                except OverflowError as exc:
                    raise ValueError(
                        f"{label} converts to a non-finite simple shock") from exc
                if not math.isfinite(value):
                    raise ValueError(
                        f"{label} converts to a non-finite simple shock")
            return value

        applied_dS = _simple_spot_shock(dS, "dS shock")
        applied_dfx = _simple_spot_shock(dfx, "dfx shock")
        if spot_shock_convention == "log":
            for label, values in (("dS_by_name", dS_by_name),
                                  ("dfx_by_pair", dfx_by_pair)):
                for key, value in (values or {}).items():
                    _simple_spot_shock(value, f"{label}[{key!r}]")

        curve_tenors = curve_moves = None
        if dr_curve:
            pairs = sorted((float(t), float(v)) for t, v in dr_curve)
            curve_tenors = _np.array([t for t, _ in pairs])
            curve_moves = _np.array([v for _, v in pairs])

        base_total = 0.0
        shocked_total = 0.0
        errors: list[str] = []
        warnings: set[str] = set()
        for pos in self.positions:
            base = copy.deepcopy(pos)
            shocked = copy.deepcopy(pos)
            secid = (pos.params or {}).get("secid")
            is_fx = pos.instrument.startswith(("fx", "ndf", "xccy"))
            if is_fx:
                pair = (pos.params or {}).get("ccy_pair") or pos.ccy_pair
                raw_spot_shock = (dfx_by_pair or {}).get(pair, dfx)
            else:
                raw_spot_shock = (dS_by_name or {}).get(secid, dS)
            spot_shock = _simple_spot_shock(raw_spot_shock)
            dr_pos = dr
            if curve_tenors is not None:
                dr_pos = float(_np.interp(self._position_tenor(pos.params),
                                          curve_tenors, curve_moves))

            try:
                discount_curve_bound = self._bind_scenario_curves(
                    base, shocked, dr=dr, dr_curve=dr_curve,
                    dr_curves=dr_curves)
            except Exception as exc:
                errors.append(f"{pos.id}: {exc}")
                continue

            component_ids = self._component_factor_ids(pos.params)
            expected_components = (
                len(pos.params.get("assets") or []) if pos.instrument == "basket"
                else 2 if pos.instrument == "spread" else 0
            )
            if component_ids and len(component_ids) != expected_components:
                errors.append(
                    f"{pos.id}: component_secids has {len(component_ids)} entries; "
                    f"expected {expected_components}")
                continue
            component_slugs = [self._risk_factor_slug(value)
                               for value in component_ids]
            if component_ids and len(set(component_slugs)) != len(component_ids):
                errors.append(
                    f"{pos.id}: component_secids must be unique for factor attribution")
                continue

            # Multi-asset list fields need typed, component-by-component
            # routing. Previously basket assets/sigmas received no shock at
            # all, while a spread's one scalar secid moved both legs.
            if pos.instrument == "basket":
                assets = list(shocked.params.get("assets") or [])
                sigmas = list(shocked.params.get("sigmas") or [])
                if len(sigmas) != len(assets):
                    errors.append(
                        f"{pos.id}: basket assets/sigmas length mismatch "
                        f"({len(assets)} != {len(sigmas)})")
                    continue
                if not component_ids:
                    component_ids = [""] * len(assets)
                    warnings.add(
                        f"{pos.id}: basket component identity missing; "
                        "global equity/vol proxy applied")
                for idx, factor_id in enumerate(component_ids):
                    raw = (dS_by_name or {}).get(factor_id, dS) if factor_id else dS
                    assets[idx] *= 1.0 + _simple_spot_shock(raw)
                    vol_move = ((dvol_by_name or {}).get(factor_id, dvol)
                                if factor_id else dvol)
                    sigmas[idx] = max(sigmas[idx] + float(vol_move), 1e-4)
                shocked.params["assets"] = assets
                shocked.params["sigmas"] = sigmas
            elif pos.instrument == "spread" and component_ids:
                for idx, factor_id in enumerate(component_ids, start=1):
                    raw = (dS_by_name or {}).get(factor_id, dS)
                    key = f"S{idx}"
                    shocked.params[key] *= 1.0 + _simple_spot_shock(raw)
                    vol_key = f"sigma{idx}"
                    vol_move = (dvol_by_name or {}).get(factor_id, dvol)
                    shocked.params[vol_key] = max(
                        shocked.params[vol_key] + float(vol_move), 1e-4)
            else:
                if pos.instrument == "spread":
                    warnings.add(
                        f"{pos.id}: spread component identity missing; "
                        "global equity/vol proxy applied")
                # Real-market equity futures are captured as
                # ``instrument="future"`` with their quoted level in F. Treat
                # F as spot-like only for that typed route.
                spot_keys = self._SPOT_KEYS + (("F",) if pos.instrument == "future" else ())
                for key in spot_keys:
                    if key in shocked.params and isinstance(shocked.params[key], (int, float)):
                        shocked.params[key] *= 1.0 + spot_shock
            for key in self._RATE_KEYS:
                if key == "r" and discount_curve_bound:
                    continue
                if key in shocked.params and isinstance(shocked.params[key], (int, float)):
                    shocked.params[key] = shocked.params[key] + dr_pos
            if pos.instrument not in ("basket",) and not (
                    pos.instrument == "spread" and component_ids):
                named_surface = (
                    pos.instrument in ("call", "put", "option")
                    and bool(pos.params.get("vol_surface_id"))
                )
                if named_surface and dvol_by_position is not None:
                    if pos.id not in dvol_by_position:
                        errors.append(
                            f"{pos.id}: historical scenario has no node shift for "
                            f"vol surface '{pos.params.get('vol_surface_id')}'")
                        continue
                    vol_move = float(dvol_by_position[pos.id])
                else:
                    vol_move = (dvol_by_name or {}).get(secid, dvol)
                for key in self._VOL_KEYS:
                    if key in shocked.params and isinstance(shocked.params[key], (int, float)):
                        shocked.params[key] = max(
                            shocked.params[key] + float(vol_move), 1e-4)
                if (pos.instrument in ("call", "put", "option")
                        and pos.params.get("vol_surface_id")):
                    try:
                        resolved_sigma, surface_warning = self._resolve_surface_vol(
                            base.params)
                    except Exception as exc:
                        errors.append(f"{pos.id}: {exc}")
                        continue
                    base.params["_resolved_surface_sigma"] = resolved_sigma
                    shocked_sigma = resolved_sigma + float(vol_move)
                    if named_surface and dvol_by_position is not None:
                        if not math.isfinite(shocked_sigma) or not 0.0 < shocked_sigma < 5.0:
                            errors.append(
                                f"{pos.id}: historical surface shock produces "
                                f"invalid sigma {shocked_sigma}")
                            continue
                        shocked.params["_resolved_surface_sigma"] = shocked_sigma
                    else:
                        shocked.params["_resolved_surface_sigma"] = max(
                            shocked_sigma, 1e-4)
                    if surface_warning:
                        warnings.add(f"{pos.id}: {surface_warning}")
            try:
                self._price_position(base, calculate_risk=False)
                self._price_position(shocked, calculate_risk=False)
                values = (
                    base.price, base.market_value,
                    shocked.price, shocked.market_value,
                )
                if not all(math.isfinite(float(value)) for value in values):
                    raise ValueError("repricing returned a non-finite price or market value")
                base_total += base.market_value
                shocked_total += shocked.market_value
            except Exception as exc:
                errors.append(f"{pos.id}: {exc}")
        if not errors and not all(math.isfinite(float(value)) for value in (
                base_total, shocked_total, shocked_total - base_total)):
            errors.append("portfolio repricing returned non-finite totals")
        if errors:
            message = "full portfolio repricing failed: " + "; ".join(errors)
            if strict:
                raise ValueError(message)
            invalid = float("nan")
            return dict(pnl=invalid, base_value=invalid,
                        shocked_value=invalid, errors=errors, valid=False,
                        warnings=sorted(warnings),
                        shocks=dict(dS=applied_dS, dr=dr, dvol=dvol,
                                    dfx=applied_dfx))
        return dict(pnl=shocked_total - base_total, base_value=base_total,
                    shocked_value=shocked_total, errors=[], valid=True,
                    warnings=sorted(warnings),
                    shocks=dict(dS=applied_dS, dr=dr, dvol=dvol,
                                dfx=applied_dfx))

    def price_all(self):
        """Reprice all positions using their params."""
        errors = []
        warnings = []
        for pos in self.positions:
            try:
                self._price_position(pos)
                warnings.extend(pos.warnings)
                errors.extend(pos.errors)
            except Exception as exc:
                pos.price = float("nan")
                pos.market_value = float("nan")
                pos.exposures = []
                pos.errors = [f"Pricing failed for {pos.id}: {exc}"]
                errors.extend(pos.errors)
        record = self.audit.record_calculation(
            user_action="Value portfolio",
            calculation_type="portfolio_valuation",
            model_id="portfolio_service",
            model_version="1.0",
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            inputs=self._portfolio_inputs(),
            result_id=f"portfolio_valuation:{self.portfolio.portfolio_id}",
            details={"positions": len(self.positions), "errors": errors},
        )
        return PortfolioValuationResult(
            portfolio_id=self.portfolio.portfolio_id,
            valuation_date=self.portfolio.valuation_date,
            base_currency=self.portfolio.base_currency,
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            total_market_value=sum(p.market_value for p in self.positions),
            positions=list(self.positions),
            warnings=warnings,
            errors=errors,
            calculation_record=record,
            calculation_id=record.record_id,
            inputs_hash=record.inputs_hash,
        )

    def value(self) -> PortfolioValuationResult:
        """Canonical portfolio valuation entry point."""
        return self.price_all()

    @staticmethod
    def _require_valid_valuation(
        result: PortfolioValuationResult, *, context: str,
    ) -> None:
        errors = [str(error) for error in (result.errors or [])]
        if errors:
            raise ValueError(f"{context} failed: " + "; ".join(errors))
        numbers = [result.total_market_value]
        for position in result.positions:
            numbers.extend((position.price, position.market_value))
            numbers.extend(exposure.sensitivity for exposure in position.exposures)
        try:
            finite = all(math.isfinite(float(value)) for value in numbers)
        except (TypeError, ValueError):
            finite = False
        if not finite:
            raise ValueError(f"{context} returned non-finite valuation or exposure")

    def _reset_position_risk(self, pos: Position):
        pos.delta = 0.0
        pos.gamma = 0.0
        pos.vega = 0.0
        pos.theta = 0.0
        pos.rho = 0.0
        pos.dv01 = 0.0
        pos.cs01 = 0.0
        pos.fx_delta = 0.0
        pos.exposures = []
        pos.warnings = []
        pos.errors = []

    def _add_exposure(
        self,
        pos: Position,
        bucket: RiskFactorBucket,
        factor_name: str,
        sensitivity: float,
        unit: str,
        bump_size: float,
        factor_type: str | None = None,
        factor_id: str | None = None,
    ):
        if sensitivity == 0:
            return
        resolved_factor_id = factor_id or self._factor_id(bucket, factor_name)
        pos.exposures.append(
            RiskFactorExposure(
                factor_name=factor_name,
                factor_type=factor_type or bucket.lower(),
                currency=pos.currency,
                bump_size=bump_size,
                sensitivity=sensitivity,
                unit=unit,
                bucket=bucket,
                factor_id=resolved_factor_id,
                position_id=pos.id,
            )
        )

    def _factor_id(self, bucket: RiskFactorBucket | str, factor_name: str) -> str:
        normalized_name = factor_name.lower().replace(" ", "_")
        candidates = {
            ("Rates", "yield_curve"): "rates.yield_curve",
            ("Rates", "swap_curve"): "rates.swap_curve",
            ("Rates", "risk_free_rate"): "rates.risk_free_rate",
            ("FX", "fx_spot"): "fx.spot",
            ("FX", normalized_name): f"fx.{normalized_name}",
            ("Equity", "spot"): "equity.spot",
            ("Equity", "spot_gamma"): "equity.spot_gamma",
            ("Equity", "future_underlying"): "equity.spot",
            ("Credit", "credit_spread"): "credit.spread",
            ("Volatility", "implied_vol"): "vol.implied",
        }
        return candidates.get((bucket, factor_name), f"{str(bucket).lower()}.{normalized_name}")

    def _price_position(self, pos: Position, *, calculate_risk: bool = True):
        self._reset_position_risk(pos)
        p = pos.params
        qt = pos.quantity
        inst = pos.instrument

        if inst in ("call", "put", "option"):
            surface_warning = None
            if p.get("vol_surface_id"):
                if "_resolved_surface_sigma" in p:
                    sigma = float(p["_resolved_surface_sigma"])
                else:
                    sigma, surface_warning = self._resolve_surface_vol(p)
            else:
                sigma = float(p["sigma"])
            res = self.pricing.price_vanilla_option(
                p["S"], p["K"], p["T"], p["r"], sigma, p.get("q", 0),
                p.get("opt", inst), snapshot=self.snapshot,
                vol_surface_id=p.get("vol_surface_id"),
            )
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            if surface_warning and surface_warning not in pos.warnings:
                pos.warnings.append(surface_warning)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.delta = raw.get("delta", 0.0) * qt
            pos.gamma = raw.get("gamma", 0.0) * qt
            pos.vega = raw.get("vega", 0.0) * qt
            pos.theta = raw.get("theta", 0.0) * qt
            pos.rho = raw.get("rho", 0.0) * qt
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0, factor_id="equity.spot")
            self._add_exposure(pos, "Equity", "spot_gamma", pos.gamma, "Gamma", 1.0, factor_id="equity.spot_gamma")
            self._add_exposure(pos, "Volatility", "implied_vol", pos.vega, "Vega", 0.01, factor_id="vol.implied")
            self._add_exposure(pos, "Rates", "risk_free_rate", pos.rho, "Rho", 0.01, factor_id="rates.risk_free_rate")

        elif inst == "bond":
            curve = self._resolve_curve_object(p, instrument=inst)
            res = self.pricing.price_bond(
                p["face"], p["coupon"], p["T"], p.get("freq", 2),
                curve=curve, snapshot=self.snapshot,
                curve_id=p.get("curve_id", "flat_rub"))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt / p["face"]
            pos.dv01 = raw.get("dv01", 0.0) * qt / p["face"]
            pos.delta = raw.get("mod_duration", 0.0) * pos.market_value / 100
            self._add_exposure(pos, "Rates", "yield_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.yield_curve")
            # bucketed key-rate DV01 (distinct unit -> does not double-count the headline DV01)
            dirty = raw.get("dirty_price") or raw.get("price") or 0.0
            for tenor, krd in (raw.get("key_rate_durations") or {}).items():
                kr_dv01 = krd * dirty * 1e-4 * qt / p["face"]
                self._add_exposure(pos, "Rates", f"kr_{tenor:g}y", kr_dv01, "Key Rate DV01",
                                   0.0001, factor_id=f"rates.kr_{tenor:g}")

        elif inst in ("callable", "putable"):
            option = "callable" if inst == "callable" else "putable"
            def _cb(rr, _opt=option):
                return self.pricing.price_callable_bond(
                    p["face"], p["coupon"], p["T"], p.get("freq", 2), p.get("sigma", 0.15),
                    p.get("call_price"), p.get("call_start", 0.0), p.get("put_price"),
                    p.get("put_start", 0.0), _opt, curve=self.market_data.flat_curve(rr))["value"]
            res = self.pricing.price_callable_bond(
                p["face"], p["coupon"], p["T"], p.get("freq", 2), p.get("sigma", 0.15),
                p.get("call_price"), p.get("call_start", 0.0), p.get("put_price"),
                p.get("put_start", 0.0), option, curve=self.market_data.flat_curve(p["r"]))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt / p["face"]
            pos.dv01 = self._fd_rates_dv01(_cb, p["r"]) * qt / p["face"]
            self._add_exposure(pos, "Rates", "yield_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.yield_curve")

        elif inst == "bond_future":
            deliverables = [{"name": "CTD", "clean_price": p["clean_price"],
                             "accrued": p.get("accrued", 0.0),
                             "conversion_factor": p["conversion_factor"],
                             "coupon_income": p.get("coupon_income", 0.0),
                             "dv01": p.get("ctd_dv01", 0.0)}]
            res = self.pricing.price_bond_future(deliverables, p["futures_price"],
                                                 p["repo_rate"], p["T_delivery"], p.get("target_bpv"))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = raw.get("theoretical_futures", res["value"])
            pos.dv01 = raw.get("futures_dv01", 0.0) * qt
            pos.market_value = pos.price * qt
            self._add_exposure(pos, "Rates", "yield_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.yield_curve")

        elif inst == "stir_future":
            res = self.pricing.price_stir_future(p["forward_rate"], p.get("notional", 1_000_000),
                                                 p.get("tenor", 0.25))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = raw.get("dv01", 0.0) * qt
            self._add_exposure(pos, "Rates", "yield_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.yield_curve")

        elif inst == "repo":
            res = self.pricing.price_repo(p["spot"], p["repo_rate"], p["T"],
                                          p.get("coupon_income", 0.0), p.get("direction", "repo"))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = raw.get("forward_price", res["value"])
            pos.market_value = raw.get("carry", 0.0) * qt
            pos.dv01 = raw.get("funding_dv01", 0.0) * qt
            self._add_exposure(pos, "Rates", "repo_rate", pos.dv01, "DV01", 0.0001, factor_id="rates.repo")

        elif inst in ("deposit", "treasury_bill", "commercial_paper"):
            res = self._price_mm(inst, p)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = raw.get("dv01", 0.0) * qt
            self._add_exposure(pos, "Rates", "yield_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.yield_curve")

        elif inst == "custom_bond":
            res = self.pricing.price_custom_bond(p["cashflows"], p.get("freq", 2),
                                                 curve=self.market_data.flat_curve(p["r"]))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = raw.get("dv01", 0.0) * qt
            self._add_exposure(pos, "Rates", "yield_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.yield_curve")

        elif inst in ("amortizing", "step_bond", "perpetual", "inflation_linked"):
            res = self._price_fi_bond(inst, p)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            face = p.get("face", 1000.0)
            pos.price = res["value"]
            pos.market_value = pos.price * qt / face
            pos.dv01 = raw.get("dv01", 0.0) * qt / face
            self._add_exposure(pos, "Rates", "yield_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.yield_curve")
            dirty = raw.get("dirty_price") or raw.get("price") or 0.0
            for tenor, krd in (raw.get("key_rate_durations") or {}).items():
                kr = krd * dirty * 1e-4 * qt / face
                self._add_exposure(pos, "Rates", f"kr_{tenor:g}y", kr, "Key Rate DV01",
                                   0.0001, factor_id=f"rates.kr_{tenor:g}")

        elif inst == "cds":
            from instruments.credit import cds_implied_hazard

            hazard = p.get("hazard")
            if hazard is None:
                # Compatibility for older persisted positions that predate the
                # captured flat-hazard parameter.
                hazard = cds_implied_hazard(
                    p["spread"], p["T"], p.get("freq", 4), p["r"],
                    p.get("recovery", 0.4))
            res = self.pricing.price_cds(
                p["notional"], p["spread"], p["T"], p.get("freq", 4),
                hazard, p["r"], p.get("recovery", 0.4), p.get("buy", True))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.cs01 = raw.get("dv01", 0.0) * qt
            self._add_exposure(pos, "Credit", "credit_spread", pos.cs01, "CS01", 0.0001, factor_id="credit.spread")

        elif inst in ("irs", "swap"):
            curve = self._resolve_curve_object(p, instrument=inst)
            proj_curve = self._resolve_curve_object(
                p, object_key="proj_curve", id_key="proj_curve_id",
                rate_key=None, instrument=inst)
            res = self.pricing.price_irs(
                p["notional"], p["fixed_rate"], p["T"], p.get("freq", 4),
                curve=curve, pay_fixed=p.get("pay_fixed", True),
                snapshot=self.snapshot, curve_id=p.get("curve_id", "flat_rub"),
                proj_curve=proj_curve, proj_curve_id=p.get("proj_curve_id"),
            )
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = self._fd_curve_dv01(
                lambda disc, proj: self.pricing.price_irs(
                    p["notional"], p["fixed_rate"], p["T"],
                    p.get("freq", 4), curve=disc,
                    pay_fixed=p.get("pay_fixed", True),
                    proj_curve=proj)["value"],
                curve, proj_curve) * qt
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")

        elif inst == "equity":
            S = p["S"]
            pos.price = S
            pos.market_value = S * qt
            pos.delta = qt
            pos.model_id = "equity_spot"
            pos.model_status = "Manual"
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0, factor_id="equity.spot")

        elif inst == "fx_forward":
            explicit_notional = "notional" in p
            if explicit_notional:
                notional = p["notional"]
                position_multiplier = qt
            else:
                # Legacy/demo positions stored foreign notional in quantity.
                # Revalue that shape without multiplying the NPV twice.
                notional = abs(qt)
                position_multiplier = -1.0 if qt < 0 else 1.0
            agreed = p.get("K")
            res = self.pricing.price_fx_forward(
                p["S"], p["r_d"], p["r_f"], p["T"], notional, agreed)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            if agreed is None:
                # Legacy "quote-only" forwards omitted the contractual K:
                # keep their historical zero-MtM/unit-delta semantics. New
                # workstation capture always freezes a fair or entered K.
                pos.price = raw.get("forward", res["value"])
                pos.market_value = 0.0
                pos.fx_delta = qt
            else:
                pos.price = res["value"]
                pos.market_value = pos.price * position_multiplier
                pos.fx_delta = (notional * math.exp(-p["r_f"] * p["T"])
                                * position_multiplier)
            self._add_exposure(
                pos,
                "FX",
                p.get("ccy_pair", pos.ccy_pair or "fx_spot"),
                pos.fx_delta,
                "FX Delta",
                1.0,
                factor_id=f"fx.{p.get('ccy_pair', pos.ccy_pair or 'spot').lower()}",
            )

        elif inst == "future":
            F = p.get("F", p.get("S", 0))
            multiplier = p.get("multiplier", 1)
            pos.price = F
            pos.market_value = F * qt * multiplier
            pos.delta = qt * multiplier
            pos.model_id = "future_mark"
            pos.model_status = "Manual"
            self._add_exposure(pos, "Equity", "future_underlying", pos.delta, "Delta", 1.0, factor_id="equity.spot")

        elif inst == "digital":
            res = self.pricing.price_digital_option(
                p["S"], p["K"], p["T"], p["r"], p["sigma"], p.get("q", 0),
                p.get("opt", "call"), p.get("style", "cash"), p.get("cash", 1.0))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            raw = res["raw"] or {}
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.delta = raw.get("delta", 0.0) * qt
            pos.gamma = raw.get("gamma", 0.0) * qt
            pos.vega = raw.get("vega", 0.0) * qt
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0, factor_id="equity.spot")
            self._add_exposure(pos, "Equity", "spot_gamma", pos.gamma, "Gamma", 1.0, factor_id="equity.spot_gamma")
            self._add_exposure(pos, "Volatility", "implied_vol", pos.vega, "Vega", 0.01, factor_id="vol.implied")

        elif inst in ("barrier", "asian", "lookback", "spread", "basket", "autocall"):
            # Engines return price only (or MC) -> sensitivities via finite difference.
            base, S0, vol0 = self._equity_exotic_pricer(inst, p)
            res = base(S0, vol0)
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            if not calculate_risk:
                pos.price = float(res["value"])
                pos.market_value = pos.price * qt
                return
            component_ids = self._component_factor_ids(p)
            if inst in ("spread", "basket") and component_ids:
                expected = 2 if inst == "spread" else len(p.get("assets") or [])
                if len(component_ids) != expected:
                    raise ValueError(
                        f"component_secids has {len(component_ids)} entries; "
                        f"expected {expected}")
                component_slugs = [self._risk_factor_slug(value)
                                   for value in component_ids]
                if len(set(component_slugs)) != len(component_ids):
                    raise ValueError(
                        "component_secids must be unique for factor attribution")
                p0, component_delta, component_gamma, component_vega = (
                    self._multi_asset_component_greeks(inst, p))
                pos.price = p0
                pos.market_value = p0 * qt
                pos.delta = sum(component_delta) * qt
                pos.gamma = sum(component_gamma) * qt
                pos.vega = sum(component_vega) * qt
                for secid, delta, gamma, vega in zip(
                        component_ids, component_delta, component_gamma,
                        component_vega):
                    slug = self._risk_factor_slug(secid)
                    self._add_exposure(
                        pos, "Equity", f"{secid} spot", delta * qt,
                        "Delta", 1.0, factor_type="spot",
                        factor_id=f"equity.{slug}.spot")
                    self._add_exposure(
                        pos, "Equity", f"{secid} spot gamma", gamma * qt,
                        "Gamma", 1.0, factor_type="spot_gamma",
                        factor_id=f"equity.{slug}.spot_gamma")
                    self._add_exposure(
                        pos, "Volatility", f"{secid} implied vol", vega * qt,
                        "Vega", 0.01, factor_type="implied_vol",
                        factor_id=f"vol.{slug}.implied")
                return
            p0, delta, gamma, vega = self._fd_equity_greeks(
                lambda S, v: base(S, v)["value"], S0, vol0)
            pos.price = p0
            pos.market_value = p0 * qt
            pos.delta = delta * qt
            pos.gamma = gamma * qt
            pos.vega = vega * qt
            if inst in ("spread", "basket") and not component_ids:
                pos.warnings.append(
                    "Component identity missing; Greeks use the first-component "
                    "global proxy")
            self._add_exposure(pos, "Equity", "spot", pos.delta, "Delta", 1.0, factor_id="equity.spot")
            self._add_exposure(pos, "Equity", "spot_gamma", pos.gamma, "Gamma", 1.0, factor_id="equity.spot_gamma")
            self._add_exposure(pos, "Volatility", "implied_vol", pos.vega, "Vega", 0.01, factor_id="vol.implied")

        elif inst == "frn":
            curve = self._resolve_curve_object(p, instrument=inst)
            proj_curve = self._resolve_curve_object(
                p, object_key="proj_curve", id_key="proj_curve_id",
                rate_key=None, instrument=inst)
            res = self.pricing.price_frn(
                p["face"], p["spread"], p["T"], p.get("freq", 2),
                curve=curve, snapshot=self.snapshot,
                curve_id=p.get("curve_id", "flat_rub"), proj_curve=proj_curve,
                proj_curve_id=p.get("proj_curve_id"))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt / p["face"]
            pos.dv01 = self._fd_curve_dv01(
                lambda disc, proj: self.pricing.price_frn(
                    p["face"], p["spread"], p["T"], p.get("freq", 2),
                    curve=disc, proj_curve=proj)["value"],
                curve, proj_curve) * qt / p["face"]
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")

        elif inst == "fra":
            curve = self._resolve_curve_object(p, instrument=inst)
            proj_curve = self._resolve_curve_object(
                p, object_key="proj_curve", id_key="proj_curve_id",
                rate_key=None, instrument=inst)
            res = self.pricing.price_fra(
                p["notional"], p["K"], p["T1"], p["T2"], curve=curve,
                proj_curve=proj_curve, snapshot=self.snapshot,
                curve_id=p.get("curve_id", "flat_rub"),
                proj_curve_id=p.get("proj_curve_id"))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = self._fd_curve_dv01(
                lambda disc, proj: self.pricing.price_fra(
                    p["notional"], p["K"], p["T1"], p["T2"],
                    curve=disc, proj_curve=proj)["value"],
                curve, proj_curve) * qt
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")

        elif inst in ("cap", "floor", "cap_floor"):
            curve = self._resolve_curve_object(p, instrument=inst)
            proj_curve = self._resolve_curve_object(
                p, object_key="proj_curve", id_key="proj_curve_id",
                rate_key=None, instrument=inst)
            opt = p.get("opt", "cap")
            res = self.pricing.price_cap_floor(
                p["notional"], p["K"], p["T"], p.get("freq", 2),
                p["vol"], opt, curve=curve, proj_curve=proj_curve,
                snapshot=self.snapshot, curve_id=p.get("curve_id", "flat_rub"),
                proj_curve_id=p.get("proj_curve_id"))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = self._fd_curve_dv01(
                lambda disc, proj: self.pricing.price_cap_floor(
                    p["notional"], p["K"], p["T"], p.get("freq", 2),
                    p["vol"], opt, curve=disc, proj_curve=proj)["value"],
                curve, proj_curve) * qt
            pos.vega = self._fd_vol_vega(lambda v: self.pricing.price_cap_floor(
                p["notional"], p["K"], p["T"], p.get("freq", 2), v, opt,
                curve=curve, proj_curve=proj_curve)["value"],
                p["vol"]) * qt
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")
            self._add_exposure(pos, "Volatility", "rate_vol", pos.vega, "Vega", 0.01, factor_id="vol.rate")

        elif inst == "swaption":
            curve = self._resolve_curve_object(p, instrument=inst)
            opt = p.get("opt", "payer")
            res = self.pricing.price_swaption(
                p["notional"], p["K"], p["T_option"], p["T_swap"], p.get("freq", 2),
                p["sigma"], opt, curve=curve, snapshot=self.snapshot,
                curve_id=p.get("curve_id", "flat_rub"))
            if res["errors"]:
                raise ValueError("; ".join(res["errors"]))
            self._attach_service_metadata(pos, res)
            pos.price = res["value"]
            pos.market_value = pos.price * qt
            pos.dv01 = self._fd_curve_dv01(
                lambda disc, _proj: self.pricing.price_swaption(
                    p["notional"], p["K"], p["T_option"], p["T_swap"],
                    p.get("freq", 2), p["sigma"], opt, curve=disc)["value"],
                curve) * qt
            pos.vega = self._fd_vol_vega(lambda v: self.pricing.price_swaption(
                p["notional"], p["K"], p["T_option"], p["T_swap"], p.get("freq", 2),
                v, opt, curve=curve)["value"], p["sigma"]) * qt
            self._add_exposure(pos, "Rates", "swap_curve", pos.dv01, "DV01", 0.0001, factor_id="rates.swap_curve")
            self._add_exposure(pos, "Volatility", "rate_vol", pos.vega, "Vega", 0.01, factor_id="vol.rate")

        else:
            raise ValueError(f"unsupported portfolio instrument '{inst}'")

    def _price_mm(self, inst: str, p: dict) -> dict:
        """Route a money-market position to its PricingService method."""
        md = self.pricing
        if inst == "deposit":
            curve = p.get("curve") or self.market_data.flat_curve(p["r"])
            return md.price_deposit(p["notional"], p["rate"], p["T"], curve=curve)
        if inst == "treasury_bill":
            return md.price_treasury_bill(p["face"], p["discount_rate"], p["T"])
        return md.price_commercial_paper(p["face"], p["discount_rate"], p["T"])

    def _price_fi_bond(self, inst: str, p: dict) -> dict:
        """Route a bond-family position to its PricingService method (curve from r)."""
        curve = p.get("curve") or self.market_data.flat_curve(p["r"])
        md = self.pricing
        if inst == "amortizing":
            return md.price_amortizing_bond(p["face"], p["coupon"], p["T"], p.get("freq", 2),
                                            p.get("amort_type", "linear"),
                                            p.get("day_count", "act365"), curve=curve)
        if inst == "step_bond":
            return md.price_step_bond(p["face"], p["coupon1"], p["coupon2"], p["switch_year"],
                                      p["T"], p.get("freq", 2), p.get("day_count", "act365"),
                                      curve=curve)
        if inst == "perpetual":
            return md.price_perpetual_bond(p["face"], p["coupon"], p.get("freq", 1), curve=curve)
        return md.price_inflation_linked_bond(
            p["face"], p["real_coupon"], p["T"], p.get("freq", 2), p.get("base_cpi", 100.0),
            p.get("current_cpi", 100.0), p.get("inflation_rate", 0.04),
            p.get("day_count", "act365"), curve=curve)

    def _equity_exotic_pricer(self, inst: str, p: dict):
        """Return (value_fn(S, sigma) -> governed result, base_spot, base_vol) for an exotic."""
        if inst == "barrier":
            return (lambda S, v: self.pricing.price_barrier_option(
                S, p["K"], p["H"], p["T"], p["r"], v, p.get("q", 0),
                p.get("opt", "call"), p.get("barrier_type", "down-out"))), p["S"], p["sigma"]
        if inst == "asian":
            return (lambda S, v: self.pricing.price_asian_option(
                S, p["K"], p["T"], p["r"], v, p.get("q", 0), p.get("opt", "call"),
                p.get("averaging", "arithmetic"), p.get("n", 12),
                p.get("n_sims", 20_000))), p["S"], p["sigma"]
        if inst == "lookback":
            return (lambda S, v: self.pricing.price_lookback_option(
                S, p["T"], p["r"], v, p.get("q", 0), p.get("opt", "call"),
                p.get("strike_type", "floating"), p.get("K"))), p["S"], p["sigma"]
        if inst == "spread":
            return (lambda S, v: self.pricing.price_spread_option(
                S, p["S2"], p["K"], p["T"], p["r"], v, p["sigma2"], p["rho"],
                p.get("q1", 0), p.get("q2", 0))), p["S1"], p["sigma1"]
        if inst == "basket":
            return (lambda S, v: self.pricing.price_basket_option(
                [S] + list(p["assets"][1:]), p["weights"], p["K"], p["T"], p["r"],
                [v] + list(p["sigmas"][1:]), p["corr"], p.get("opt", "call"))), \
                p["assets"][0], p["sigmas"][0]
        # autocall / phoenix
        return (lambda S, v: self.pricing.price_autocall_phoenix(
            S, p["r"], p.get("q", 0), v, p["T"], p["obs_dates"], p["autocall_barrier"],
            p["coupon_barrier"], p["ki_barrier"], p["coupon_rate"],
            p.get("memory_coupon", True), p.get("n_sims", 20_000),
            p.get("steps", 100))), p["S0"], p["sigma"]

    @staticmethod
    def _risk_factor_slug(value: str) -> str:
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value)).strip("_")

    def _multi_asset_component_greeks(self, inst: str, params: dict):
        """FD price/Delta/Gamma/Vega for every spread or basket component."""
        if inst == "spread":
            spots = [float(params["S1"]), float(params["S2"])]
            sigmas = [float(params["sigma1"]), float(params["sigma2"])]

            def governed(current_spots, current_sigmas):
                return self.pricing.price_spread_option(
                    current_spots[0], current_spots[1], params["K"],
                    params["T"], params["r"], current_sigmas[0],
                    current_sigmas[1], params["rho"], params.get("q1", 0),
                    params.get("q2", 0))
        elif inst == "basket":
            spots = [float(value) for value in params["assets"]]
            sigmas = [float(value) for value in params["sigmas"]]

            def governed(current_spots, current_sigmas):
                return self.pricing.price_basket_option(
                    current_spots, params["weights"], params["K"], params["T"],
                    params["r"], current_sigmas, params["corr"],
                    params.get("opt", "call"))
        else:
            raise ValueError(f"component Greeks unsupported for '{inst}'")
        if len(spots) != len(sigmas) or not spots:
            raise ValueError("multi-asset spots/sigmas must be non-empty and aligned")

        def value(current_spots, current_sigmas) -> float:
            result = governed(current_spots, current_sigmas)
            if result.get("errors"):
                raise ValueError("; ".join(result["errors"]))
            number = float(result["value"])
            if not math.isfinite(number):
                raise ValueError("multi-asset component bump returned non-finite value")
            return number

        p0 = value(spots, sigmas)
        deltas, gammas, vegas = [], [], []
        for index, (spot, sigma) in enumerate(zip(spots, sigmas)):
            ds = max(abs(spot) * 0.01, 1e-4)
            if spot - ds <= 0:
                ds = max(abs(spot) * 0.5, 1e-6)
            up_spots, down_spots = list(spots), list(spots)
            up_spots[index] += ds
            down_spots[index] -= ds
            up = value(up_spots, sigmas)
            down = value(down_spots, sigmas)
            deltas.append((up - down) / (2.0 * ds))
            gammas.append((up - 2.0 * p0 + down) / (ds * ds))

            dv = min(0.01, max(sigma * 0.5, 1e-5))
            up_sigmas, down_sigmas = list(sigmas), list(sigmas)
            up_sigmas[index] += dv
            down_sigmas[index] = max(sigma - dv, 1e-6)
            vol_span = up_sigmas[index] - down_sigmas[index]
            vegas.append(
                (value(spots, up_sigmas) - value(spots, down_sigmas))
                / vol_span * 0.01)
        return p0, deltas, gammas, vegas

    @staticmethod
    def _fd_equity_greeks(value_fn, S: float, sigma: float):
        """Central-difference (price, delta, gamma, vega-per-1%) for an equity pricer."""
        dS = max(abs(S) * 0.01, 1e-4)
        dV = 0.01
        p0 = value_fn(S, sigma)
        pu, pd = value_fn(S + dS, sigma), value_fn(S - dS, sigma)
        vu, vd = value_fn(S, sigma + dV), value_fn(S, sigma - dV)
        delta = (pu - pd) / (2 * dS)
        gamma = (pu - 2 * p0 + pd) / (dS * dS)
        vega = (vu - vd) / (2 * dV) * 0.01
        return p0, delta, gamma, vega

    @staticmethod
    def _fd_rates_dv01(value_fn, r: float):
        """DV01 via a 1bp parallel curve bump: price change for a 1bp fall in rates."""
        dr = 1e-4
        return (value_fn(r - dr) - value_fn(r + dr)) / 2.0

    @staticmethod
    def _fd_curve_dv01(value_fn, curve, proj_curve=None):
        """DV01 from governed discount/projection curves with a joint 1bp bump."""
        down = curve.parallel_shift(-1.0)
        up = curve.parallel_shift(1.0)
        proj_down = proj_curve.parallel_shift(-1.0) if proj_curve is not None else None
        proj_up = proj_curve.parallel_shift(1.0) if proj_curve is not None else None
        return (value_fn(down, proj_down) - value_fn(up, proj_up)) / 2.0

    @staticmethod
    def _fd_vol_vega(value_fn, sigma: float, dV: float = 0.01):
        """Vega per 1% vol via central difference."""
        return (value_fn(sigma + dV) - value_fn(sigma - dV)) / (2 * dV) * 0.01

    def _attach_service_metadata(self, pos: Position, result: dict):
        pos.model_id = result.get("model_id", "")
        pos.model_status = result.get("model_status", "")
        pos.market_data_snapshot_id = result.get("market_data_snapshot_id", "")
        pos.warnings = list(result.get("warnings", []))
        pos.errors = list(result.get("errors", []))

    def aggregate(self) -> dict:
        risk = self.risk()

        totals = {
            "delta": self._sum_unit("Delta"),
            "gamma": self._sum_unit("Gamma"),
            "vega": self._sum_unit("Vega"),
            "rho": self._sum_unit("Rho"),
            "dv01": self._sum_unit("DV01"),
            "cs01": self._sum_unit("CS01"),
            "fx_delta": self._sum_unit("FX Delta"),
            "theta": sum(p.theta for p in self.positions),
        }

        return dict(
            n_positions=len(self.positions),
            market_value=risk.market_value,
            exposure_buckets=risk.exposure_buckets,
            risk_factor_exposures=risk.risk_factor_exposures,
            risk_factors=self.risk_factor_totals(),
            risk_factor_groups=risk.risk_factor_groups,
            factor_contributions=risk.factor_contributions,
            **totals,
        )

    def risk(self) -> PortfolioRiskResult:
        """Canonical portfolio risk aggregation entry point."""
        valuation = self.value()
        scenario = self._scenario_pnl_from_exposures(dS=0, dVol=0, dr=0, dSpread=0)
        record = self.audit.record_calculation(
            user_action="Aggregate portfolio risk",
            calculation_type="portfolio_risk",
            model_id="portfolio_service",
            model_version="1.0",
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            inputs=self._portfolio_inputs(),
            result_id=f"portfolio_risk:{self.portfolio.portfolio_id}",
            details={"valuation_calculation_id": valuation.calculation_id},
        )
        return PortfolioRiskResult(
            portfolio_id=self.portfolio.portfolio_id,
            base_currency=self.portfolio.base_currency,
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            market_value=valuation.total_market_value,
            exposure_buckets=self.exposure_buckets(),
            risk_factor_exposures=self.risk_factor_exposures(),
            risk_factor_groups=self.risk_factor_groups(),
            factor_contributions=self.factor_contributions(),
            scenario_pnl=scenario,
            warnings=valuation.warnings,
            errors=valuation.errors,
            calculation_record=record,
            calculation_id=record.record_id,
            inputs_hash=record.inputs_hash,
        )

    def _sum_unit(self, unit: str) -> float:
        return sum(exp.sensitivity for exp in self.risk_factor_exposures() if exp.unit == unit)

    def risk_factor_exposures(self) -> list[RiskFactorExposure]:
        exposures: list[RiskFactorExposure] = []
        for pos in self.positions:
            exposures.extend(pos.exposures)
        return exposures

    def exposure_buckets(self) -> dict[str, dict[str, float]]:
        buckets = {bucket: {} for bucket in EXPOSURE_BUCKETS}
        for exp in self.risk_factor_exposures():
            bucket = buckets.setdefault(exp.bucket, {})
            bucket.setdefault(exp.unit, 0.0)
            bucket[exp.unit] += exp.sensitivity
        return buckets

    def risk_factor_totals(self) -> dict[str, dict[str, float | str]]:
        """Aggregate exposures by canonical factor ID."""
        factors: dict[str, dict[str, float | str]] = {}
        for exp in self.risk_factor_exposures():
            factor_id = exp.factor_id or self._factor_id(exp.bucket, exp.factor_name)
            factor = factors.setdefault(
                factor_id,
                {
                    "factor_id": factor_id,
                    "factor_name": exp.factor_name,
                    "bucket": exp.bucket,
                    "factor_type": exp.factor_type,
                    "currency": exp.currency,
                    "unit": exp.unit,
                    "sensitivity": 0.0,
                    "contribution": 0.0,
                },
            )
            factor["sensitivity"] = float(factor["sensitivity"]) + exp.sensitivity
            factor["contribution"] = float(factor["contribution"]) + exp.contribution
        return factors

    def risk_factor_groups(self) -> list[RiskFactorGroup]:
        groups: dict[str, list[RiskFactorExposure]] = {bucket: [] for bucket in EXPOSURE_BUCKETS}
        for exp in self.risk_factor_exposures():
            groups.setdefault(exp.bucket, []).append(exp)
        return [
            RiskFactorGroup.from_exposures(bucket, exposures)
            for bucket, exposures in groups.items()
        ]

    def factor_contributions(
        self,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
    ) -> dict[str, float]:
        contributions: defaultdict[str, float] = defaultdict(float)
        for exp in self.risk_factor_exposures():
            factor_id = exp.factor_id or self._factor_id(exp.bucket, exp.factor_name)
            contributions[factor_id] += self._exposure_pnl(exp, dS, dVol, dr, dSpread)
        return dict(contributions)

    def run_scenario(self, scenario: Scenario | dict) -> ScenarioResult:
        """Run a unified scenario against current portfolio factor exposures."""
        scenario = self._coerce_scenario(scenario)
        valuation = self.value()
        raw, warnings = self._scenario_pnl_from_scenario(scenario)
        pnl = raw["pnl"]
        record = self.audit.record_calculation(
            user_action="Run portfolio scenario",
            calculation_type="portfolio_scenario",
            model_id="portfolio_service",
            model_version="1.0",
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            inputs={"portfolio": self._portfolio_inputs(), "scenario": scenario},
            result_id=f"portfolio_scenario:{self.portfolio.portfolio_id}:{scenario.scenario_id}",
            details={"valuation_calculation_id": valuation.calculation_id},
        )
        return ScenarioResult(
            scenario=scenario,
            base_value=valuation.total_market_value,
            stressed_value=valuation.total_market_value + pnl,
            pnl=pnl,
            bucket_pnl=raw.get("bucket_pnl", {}),
            factor_pnl=raw.get("factor_pnl", {}),
            position_pnl=raw.get("position_pnl", {}),
            warnings=warnings + valuation.warnings,
            errors=valuation.errors,
            raw=raw,
            calculation_record=record,
            calculation_id=record.record_id,
            inputs_hash=record.inputs_hash,
        )

    def _coerce_scenario(self, scenario: Scenario | dict) -> Scenario:
        if isinstance(scenario, Scenario):
            return scenario
        shocks = [
            shock if isinstance(shock, ScenarioShock) else ScenarioShock(**shock)
            for shock in scenario.get("shocks", [])
        ]
        return Scenario(
            scenario_id=scenario.get("scenario_id", scenario.get("name", "custom").lower().replace(" ", "-")),
            name=scenario.get("name", "Custom Scenario"),
            scenario_type=scenario.get("scenario_type", ScenarioType.CUSTOM),
            shocks=shocks,
            source=scenario.get("source", ""),
            description=scenario.get("description", ""),
            metadata=scenario.get("metadata", {}),
        )

    def _bps_to_rate(self, shock: ScenarioShock) -> float:
        return shock.value / 10000 if shock.unit.lower() in {"bp", "bps", "basis_points"} else shock.value

    def _scenario_pnl_from_scenario(self, scenario: Scenario) -> tuple[dict, list[str]]:
        bucket_pnl: defaultdict[str, float] = defaultdict(float)
        factor_pnl: defaultdict[str, float] = defaultdict(float)
        position_pnl: defaultdict[str, float] = defaultdict(float)
        warnings: list[str] = []

        for exp in self.risk_factor_exposures():
            factor_id = exp.factor_id or self._factor_id(exp.bucket, exp.factor_name)
            for shock in scenario.shocks:
                contribution, warning = self._shock_exposure_pnl(exp, shock)
                if warning and warning not in warnings:
                    warnings.append(warning)
                if contribution == 0.0:
                    continue
                bucket_pnl[exp.bucket] += contribution
                factor_pnl[factor_id] += contribution
                position_pnl[exp.position_id] += contribution

        pnl = sum(bucket_pnl.values())
        return (
            dict(
                pnl=pnl,
                scenario_id=scenario.scenario_id,
                scenario_name=scenario.name,
                scenario_type=scenario.type_value,
                bucket_pnl={bucket: bucket_pnl.get(bucket, 0.0) for bucket in EXPOSURE_BUCKETS},
                factor_pnl=dict(factor_pnl),
                position_pnl=dict(position_pnl),
            ),
            warnings,
        )

    def _shock_exposure_pnl(self, exp: RiskFactorExposure, shock: ScenarioShock) -> tuple[float, str]:
        shock_type = shock.type_value
        if shock.factor_id and exp.factor_id and shock.factor_id != exp.factor_id:
            return 0.0, ""
        if shock.bucket and shock.bucket != exp.bucket:
            return 0.0, ""

        if shock_type == ScenarioShockType.EQUITY_SHOCK.value:
            if exp.bucket != "Equity":
                return 0.0, ""
            if exp.unit == "Delta":
                return exp.sensitivity * shock.value, ""
            if exp.unit == "Gamma":
                return exp.sensitivity * shock.value**2 / 2, ""
            return 0.0, ""

        if shock_type == ScenarioShockType.FX_SHOCK.value:
            if exp.bucket != "FX" or exp.unit != "FX Delta":
                return 0.0, ""
            return exp.sensitivity * shock.value, ""

        if shock_type == ScenarioShockType.VOLATILITY_SHOCK.value:
            if exp.bucket != "Volatility" or exp.unit != "Vega":
                return 0.0, ""
            return exp.sensitivity * shock.value * 100, ""

        if shock_type == ScenarioShockType.PARALLEL_CURVE_SHIFT.value:
            if exp.bucket != "Rates":
                return 0.0, ""
            return self._rate_exposure_pnl(exp, self._bps_to_rate(shock)), ""

        if shock_type == ScenarioShockType.STEEPENER.value:
            if exp.bucket != "Rates":
                return 0.0, ""
            warning = "Steepener scenario is approximated through aggregate rate DV01 until tenor-level exposures are available."
            return self._rate_exposure_pnl(exp, self._bps_to_rate(shock)), warning

        if shock_type == ScenarioShockType.FLATTENER.value:
            if exp.bucket != "Rates":
                return 0.0, ""
            warning = "Flattener scenario is approximated through aggregate rate DV01 until tenor-level exposures are available."
            return self._rate_exposure_pnl(exp, -self._bps_to_rate(shock)), warning

        if exp.bucket == "Credit" and exp.unit == "CS01":
            return -exp.sensitivity * self._bps_to_rate(shock) * 10000, ""
        return 0.0, ""

    def _rate_exposure_pnl(self, exp: RiskFactorExposure, dr: float) -> float:
        if exp.unit == "DV01":
            return -exp.sensitivity * dr * 10000
        if exp.unit == "Rho":
            return exp.sensitivity * dr * 100
        return 0.0

    def positions_table(self) -> list[dict]:
        self.value()
        return [
            dict(
                id=p.id,
                instrument=p.instrument,
                description=p.description,
                quantity=p.quantity,
                price=round(p.price, 4),
                market_value=round(p.market_value, 2),
                delta=round(p.delta, 4),
                gamma=round(p.gamma, 6),
                vega=round(p.vega, 4),
                theta=round(p.theta, 4),
                dv01=round(p.dv01, 2),
                cs01=round(p.cs01, 2),
                currency=p.currency,
                book=p.book,
            )
            for p in self.positions
        ]

    def scenario_pnl(self, dS: float = 0, dVol: float = 0, dr: float = 0, dSpread: float = 0) -> dict:
        """First-order scenario P&L by risk-factor bucket."""
        valuation = self.value()
        self._require_valid_valuation(valuation, context="scenario exposure valuation")
        return self._scenario_pnl_from_exposures(dS, dVol, dr, dSpread)

    def explain_pnl(
        self,
        total_pnl: float | None = None,
        *,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
        theta_days: float = 0,
        scenario: Scenario | dict | None = None,
        dS_relative: float | None = None,
        dfx_relative: float | None = None,
        dS_relative_by_name: dict | None = None,
        dVol_by_name: dict | None = None,
        dfx_relative_by_pair: dict | None = None,
    ) -> PnLExplainResult:
        """Explain portfolio P&L using risk-factor exposures.

        ``dS`` remains the legacy *absolute* spot move used by existing callers.
        Historical workflows may instead supply simple relative equity/FX moves;
        those are converted to absolute moves from each position's own spot
        before applying Delta/Gamma or FX Delta.
        """
        valuation = self.value()
        self._require_valid_valuation(valuation, context="P&L Explain exposure valuation")
        if scenario is not None:
            scenario_result = self.run_scenario(scenario)
            components = self._pnl_components_from_scenario(scenario_result.raw, theta_days=theta_days)
            factor_pnl = scenario_result.factor_pnl
            position_pnl = scenario_result.position_pnl
            estimated_total = scenario_result.pnl + components["theta_pnl"]
            warnings = list(scenario_result.warnings)
            errors = list(scenario_result.errors)
        else:
            raw = self._scenario_pnl_from_exposures(
                dS, dVol, dr, dSpread, theta_days=theta_days,
                dS_relative=dS_relative, dfx_relative=dfx_relative,
                dS_relative_by_name=dS_relative_by_name,
                dVol_by_name=dVol_by_name,
                dfx_relative_by_pair=dfx_relative_by_pair)
            components = self._pnl_components_from_legacy(raw)
            factor_pnl = raw.get("factor_pnl", {})
            position_pnl = raw.get("position_pnl", {})
            estimated_total = raw["pnl"]
            warnings = []
            errors = []

        reported_total = estimated_total if total_pnl is None else float(total_pnl)
        explained = sum(components.values())
        residual = reported_total - explained
        record = self.audit.record_calculation(
            user_action="Explain portfolio PnL",
            calculation_type="pnl_explain",
            model_id="portfolio_service",
            model_version="1.0",
            market_data_snapshot_id=self.portfolio.market_data_snapshot_id,
            inputs={
                "portfolio": self._portfolio_inputs(),
                "total_pnl": total_pnl,
                "dS": dS,
                "dVol": dVol,
                "dr": dr,
                "dSpread": dSpread,
                "theta_days": theta_days,
                "scenario": scenario,
                "dS_relative": dS_relative,
                "dfx_relative": dfx_relative,
                "dS_relative_by_name": dS_relative_by_name,
                "dVol_by_name": dVol_by_name,
                "dfx_relative_by_pair": dfx_relative_by_pair,
            },
            result_id=f"pnl_explain:{self.portfolio.portfolio_id}",
            details={"reported_total": reported_total, "explained": explained, "residual": residual},
        )
        return PnLExplainResult(
            portfolio_id=self.portfolio.portfolio_id,
            total_pnl=reported_total,
            explained_pnl=explained,
            residual=residual,
            delta_pnl=components["delta_pnl"],
            gamma_pnl=components["gamma_pnl"],
            vega_pnl=components["vega_pnl"],
            theta_pnl=components["theta_pnl"],
            rate_pnl=components["rate_pnl"],
            fx_pnl=components["fx_pnl"],
            components=components,
            factor_pnl=factor_pnl,
            position_pnl=position_pnl,
            warnings=warnings,
            errors=errors,
            calculation_record=record,
            calculation_id=record.record_id,
            inputs_hash=record.inputs_hash,
        )

    def _portfolio_inputs(self) -> dict:
        return {
            "portfolio_id": self.portfolio.portfolio_id,
            "base_currency": self.portfolio.base_currency,
            "valuation_date": self.portfolio.valuation_date,
            "market_data_snapshot_id": self.portfolio.market_data_snapshot_id,
            "positions": [
                {
                    "id": position.id,
                    "instrument": position.instrument,
                    "description": position.description,
                    "quantity": position.quantity,
                    "params": position.params,
                    "currency": position.currency,
                    "book": position.book,
                    "ccy_pair": position.ccy_pair,
                }
                for position in self.positions
            ],
        }

    def _legacy_totals(self) -> dict:
        return {
            "delta": self._sum_unit("Delta"),
            "gamma": self._sum_unit("Gamma"),
            "vega": self._sum_unit("Vega"),
            "rho": self._sum_unit("Rho"),
            "dv01": self._sum_unit("DV01"),
            "cs01": self._sum_unit("CS01"),
            "fx_delta": self._sum_unit("FX Delta"),
            "theta": sum(p.theta for p in self.positions),
        }

    def _scenario_pnl_from_aggregate(
        self,
        agg: dict,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
    ) -> dict:
        components = {
            "Equity": agg["delta"] * dS + agg["gamma"] * dS**2 / 2,
            "Volatility": agg["vega"] * dVol * 100,
            "Rates": agg["rho"] * dr * 100 - agg["dv01"] * dr * 10000,
            "Credit": -agg["cs01"] * dSpread * 10000,
            "FX": agg["fx_delta"] * dS,
            "Theta": agg["theta"],
        }
        pnl = sum(components.values())
        legacy_components = defaultdict(float)
        legacy_components.update(
            delta=agg["delta"] * dS,
            gamma=agg["gamma"] * dS**2 / 2,
            vega=agg["vega"] * dVol * 100,
            theta=agg["theta"],
            rho=agg["rho"] * dr * 100,
            ir_01=agg["dv01"] * dr * 10000,
            cs_01=agg["cs01"] * dSpread * 10000,
            fx=agg["fx_delta"] * dS,
        )
        return dict(
            pnl=pnl,
            dS=dS,
            dVol=dVol,
            dr=dr,
            dSpread=dSpread,
            bucket_pnl=components,
            components=dict(legacy_components),
        )

    def _scenario_pnl_from_exposures(
        self,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
        theta_days: float = 0,
        dS_relative: float | None = None,
        dfx_relative: float | None = None,
        dS_relative_by_name: dict | None = None,
        dVol_by_name: dict | None = None,
        dfx_relative_by_pair: dict | None = None,
    ) -> dict:
        bucket_pnl: defaultdict[str, float] = defaultdict(float)
        factor_pnl: defaultdict[str, float] = defaultdict(float)
        position_pnl: defaultdict[str, float] = defaultdict(float)
        legacy_components: defaultdict[str, float] = defaultdict(float)
        positions = {p.id: p for p in self.positions}
        equity_relative = (dS_relative is not None
                           or dS_relative_by_name is not None)
        fx_relative = (dfx_relative is not None
                       or dfx_relative_by_pair is not None)

        for exp in self.risk_factor_exposures():
            pos = positions.get(exp.position_id)
            position_dS = dS
            position_dvol = dVol
            position_dfx = None
            if equity_relative and exp.unit in {"Delta", "Gamma"}:
                secid = self._exposure_component_id(pos, exp)
                if secid is None and pos is not None:
                    secid = (pos.params or {}).get("secid")
                relative_move = (dS_relative_by_name or {}).get(
                    secid, dS_relative if dS_relative is not None else 0.0)
                spot = self._position_spot_level(pos, component_id=secid)
                position_dS = spot * float(relative_move) if spot is not None else 0.0
            if exp.unit == "Vega" and dVol_by_name is not None:
                secid = self._exposure_component_id(pos, exp)
                if secid is None and pos is not None:
                    secid = (pos.params or {}).get("secid")
                position_dvol = float(dVol_by_name.get(secid, dVol))
            if fx_relative and exp.unit == "FX Delta":
                pair = None
                if pos is not None:
                    pair = (pos.params or {}).get("ccy_pair") or pos.ccy_pair
                relative_move = (dfx_relative_by_pair or {}).get(
                    pair, dfx_relative if dfx_relative is not None else 0.0)
                spot = self._position_spot_level(pos)
                position_dfx = spot * float(relative_move) if spot is not None else 0.0
            contribution = self._exposure_pnl(
                exp, position_dS, position_dvol, dr, dSpread,
                dfx=position_dfx)
            factor_id = exp.factor_id or self._factor_id(exp.bucket, exp.factor_name)
            bucket_pnl[exp.bucket] += contribution
            factor_pnl[factor_id] += contribution
            position_pnl[exp.position_id] += contribution
            legacy_components[self._legacy_component_name(exp)] += contribution

        theta_pnl = sum(p.theta for p in self.positions) * theta_days
        if theta_pnl:
            bucket_pnl["Theta"] += theta_pnl
            legacy_components["theta"] += theta_pnl

        pnl = sum(bucket_pnl.values())
        return dict(
            pnl=pnl,
            dS=dS,
            dVol=dVol,
            dr=dr,
            dSpread=dSpread,
            bucket_pnl={bucket: bucket_pnl.get(bucket, 0.0) for bucket in EXPOSURE_BUCKETS},
            factor_pnl=dict(factor_pnl),
            position_pnl=dict(position_pnl),
            components=dict(legacy_components),
        )

    def _exposure_component_id(
        self, pos: Position | None, exp: RiskFactorExposure,
    ) -> str | None:
        if pos is None:
            return None
        factor_id = exp.factor_id or ""
        for component_id in self._component_factor_ids(pos.params or {}):
            slug = self._risk_factor_slug(component_id)
            if factor_id in {
                f"equity.{slug}.spot", f"equity.{slug}.spot_gamma",
                f"vol.{slug}.implied",
            }:
                return component_id
        return None

    def _position_spot_level(
        self, pos: Position | None, component_id: str | None = None,
    ) -> float | None:
        """Base level matching the spot-like parameter shocked in repricing."""
        if pos is None:
            return None
        params = pos.params or {}
        if component_id:
            component_ids = self._component_factor_ids(params)
            try:
                index = component_ids.index(component_id)
            except ValueError:
                index = -1
            if index >= 0 and pos.instrument == "spread":
                key = f"S{index + 1}"
                if isinstance(params.get(key), (int, float)):
                    return float(params[key])
            if index >= 0 and pos.instrument == "basket":
                assets = params.get("assets") or []
                if index < len(assets) and isinstance(assets[index], (int, float)):
                    return float(assets[index])
        if pos.instrument == "future" and isinstance(params.get("F"), (int, float)):
            return float(params["F"])
        for key in self._SPOT_KEYS:
            if isinstance(params.get(key), (int, float)):
                return float(params[key])
        assets = params.get("assets")
        if isinstance(assets, (list, tuple)) and assets \
                and isinstance(assets[0], (int, float)):
            return float(assets[0])
        return None

    def _exposure_pnl(
        self,
        exp: RiskFactorExposure,
        dS: float = 0,
        dVol: float = 0,
        dr: float = 0,
        dSpread: float = 0,
        dfx: float | None = None,
    ) -> float:
        if exp.unit == "Delta":
            return exp.sensitivity * dS
        if exp.unit == "Gamma":
            return exp.sensitivity * dS**2 / 2
        if exp.unit == "Vega":
            return exp.sensitivity * dVol * 100
        if exp.unit == "Rho":
            return exp.sensitivity * dr * 100
        if exp.unit == "DV01":
            return -exp.sensitivity * dr * 10000
        if exp.unit == "CS01":
            return -exp.sensitivity * dSpread * 10000
        if exp.unit == "FX Delta":
            return exp.sensitivity * (dS if dfx is None else dfx)
        return 0.0

    def _legacy_component_name(self, exp: RiskFactorExposure) -> str:
        return {
            "Delta": "delta",
            "Gamma": "gamma",
            "Vega": "vega",
            "Rho": "rho",
            "DV01": "ir_01",
            "CS01": "cs_01",
            "FX Delta": "fx",
        }.get(exp.unit, exp.unit.lower().replace(" ", "_"))

    def _pnl_components_from_legacy(self, raw: dict) -> dict[str, float]:
        raw_components = raw.get("components", {})
        return {
            "delta_pnl": raw_components.get("delta", 0.0),
            "gamma_pnl": raw_components.get("gamma", 0.0),
            "vega_pnl": raw_components.get("vega", 0.0),
            "theta_pnl": raw_components.get("theta", 0.0),
            "rate_pnl": raw_components.get("rho", 0.0) + raw_components.get("ir_01", 0.0),
            "fx_pnl": raw_components.get("fx", 0.0),
        }

    def _pnl_components_from_scenario(self, raw: dict, theta_days: float = 0) -> dict[str, float]:
        factor_pnl = raw.get("factor_pnl", {})
        theta_pnl = sum(p.theta for p in self.positions) * theta_days
        return {
            "delta_pnl": sum(
                value for factor, value in factor_pnl.items()
                if factor == "equity.spot" or factor.endswith(".spot")),
            "gamma_pnl": sum(
                value for factor, value in factor_pnl.items()
                if factor == "equity.spot_gamma"
                or factor.endswith(".spot_gamma")),
            "vega_pnl": sum(
                value for factor, value in factor_pnl.items()
                if factor == "vol.implied" or factor.startswith("vol.")),
            "theta_pnl": theta_pnl,
            "rate_pnl": sum(value for factor, value in factor_pnl.items() if factor.startswith("rates.")),
            "fx_pnl": sum(value for factor, value in factor_pnl.items() if factor.startswith("fx.")),
        }

    def __len__(self):
        return len(self.portfolio)

    def __repr__(self):
        return repr(self.portfolio)
