"""Market Data workstation backed by MarketDataService snapshots."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import math

from PySide6.QtWidgets import QTabWidget

from services.market_data_service import MarketDataService  # noqa: F401  (service-boundary marker)
from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class MarketWorkspace(WorkstationWorkspace):
    """Market Data owns source, timestamp, snapshots, and validation display."""

    def __init__(self, parent=None):
        from app.runtime import active_snapshot, market_service
        self.market_data = market_service()
        # latest real MOEX snapshot when a local DB is present, else demo
        self.snapshot = active_snapshot(self.market_data)
        self._db = getattr(self.market_data, "market_db", None)
        self.validation = self._validation_summary()
        self.snapshot_lineage = self.market_data.snapshot_lineage(self.snapshot.snapshot_id)
        source = self.snapshot.source_value
        validation_status = "Validated" if self.validation["status"] == "Pass" else "Approximation"

        super().__init__(
            "Market Data",
            "Single source of truth for snapshots, curves, FX, vol surfaces, and credit data",
            chips=[
                DataSourceChip(source),
                StatusChip(validation_status, text=f"Validation: {self.validation['status']}"),
            ],
            actions=[make_action("Create Snapshot"), make_action("Import CSV"), make_action("Validate", True)],
            kpi_strip=self._kpi_strip(),
            left=self._build_sources(),
            center=self._build_detail_tabs(),
            right=self._build_validation(),
            bottom=self._build_snapshot_metadata(),
            context_items=[
                ("Layer", "Market Data"),
                ("Service", "MarketDataService"),
                ("Snapshot", self.snapshot.snapshot_id),
                ("Version", f"v{self.snapshot.version}"),
                ("Source", source),
                ("Timestamp", self._timestamp()),
                ("Lineage", self._lineage_label()),
                ("Validation", self.validation["status"]),
            ],
            parent=parent,
        )

    def _kpi_strip(self):
        return KpiStrip(
            [
                ("Snapshot", f"v{self.snapshot.version}", self.snapshot.snapshot_id),
                ("Source", self.snapshot.source_value, self.snapshot.quality),
                ("Curves", str(len(self.snapshot.curves)), "yield curve objects"),
                ("FX", str(len(self.snapshot.fx_rates)), "spot pairs"),
                ("Vol Surfaces", str(len(self.snapshot.vol_surfaces)), "surface objects"),
                ("Validation", self.validation["status"], f"{self.validation['warnings']} warnings"),
                ("Lineage", self._lineage_label(), "MarketDataStore"),
            ]
        )

    def _build_sources(self):
        panel = WorkstationPanel("Snapshot Sources")
        panel.layout.addWidget(
            DenseTable(
                ["Source", "State", "Ownership"],
                [
                    [self.snapshot.source_value, "Active", self.snapshot.source_details.get("provider", "MarketDataService")],
                    ["DEMO", "Available", "Service default snapshot"],
                    ["MANUAL", "Available", "Service-created manual snapshot"],
                    ["CSV", "Available", "Service-created parsed snapshot"],
                    ["MOEX", "Prepared", "Provider interface only"],
                    ["Bloomberg", "Prepared", "Provider interface only"],
                    ["Reuters", "Prepared", "Provider interface only"],
                ],
            )
        )
        return panel

    def _build_detail_tabs(self):
        tabs = QTabWidget()
        tabs.addTab(self._data_browser_tab(), "Data Browser")
        tabs.addTab(self._curve_explorer_tab(), "Curve Explorer")
        tabs.addTab(self._fx_explorer_tab(), "FX Explorer")
        tabs.addTab(self._vol_surface_explorer_tab(), "Vol Surface Explorer")
        tabs.addTab(self._credit_curve_explorer_tab(), "Credit Curve Explorer")
        tabs.addTab(self._data_health_tab(), "Data Health")
        return tabs

    def _data_browser_tab(self):
        """
        Spreadsheet-style browser: pick a snapshot date and a dataset from two
        dropdowns; the table rebuilds and a chart appears for graphical datasets
        (yield curves overlay, commodity strips).
        """
        from datetime import date
        from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget
        from app.chart import ChartWidget
        from services import market_views as mv

        panel = WorkstationPanel("Data Browser")
        state = {"snapshot": self.snapshot}

        snap_combo = QComboBox()
        snap_combo.setObjectName("snapshot_selector")
        snaps = mv.available_snapshots(self._db)
        for s in snaps:
            snap_combo.addItem(f"{s['valuation_date']} · {s['source']} ({s['quality']})",
                               s["snapshot_id"])
        if not snaps:
            snap_combo.addItem(f"{state['snapshot'].valuation_date} · "
                               f"{state['snapshot'].source_value}",
                               state["snapshot"].snapshot_id)

        ds_combo = QComboBox()
        ds_combo.setObjectName("dataset_selector")

        selectors = QHBoxLayout()
        selectors.addWidget(QLabel("Snapshot:"))
        selectors.addWidget(snap_combo, 1)
        selectors.addWidget(QLabel("Dataset:"))
        selectors.addWidget(ds_combo, 1)
        selectors.addStretch()
        sel_wrap = QWidget()
        sel_wrap.setLayout(selectors)
        panel.layout.addWidget(sel_wrap)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 8, 0, 0)
        panel.layout.addWidget(body)
        chart = ChartWidget()
        chart.setMinimumHeight(260)
        panel.layout.addWidget(chart)

        def load_snapshot():
            sid = snap_combo.currentData()
            snap = self.snapshot
            if self._db and sid and sid != self.snapshot.snapshot_id:
                try:
                    d = date.fromisoformat(sid.split("-", 1)[1])
                    snap = self.market_data.moex_snapshot(d, fallback_to_demo=True)
                except Exception:
                    snap = self.snapshot
            state["snapshot"] = snap
            ds_combo.blockSignals(True)
            ds_combo.clear()
            for d in mv.dataset_catalog(self._db, snap):
                ds_combo.addItem(f"{d['label']}  ({d['count']})", d["key"])
            ds_combo.blockSignals(False)
            render_dataset()

        def render_dataset():
            while body_layout.count():
                w = body_layout.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            snap = state["snapshot"]
            key = ds_combo.currentData()
            if key is None:
                return
            try:
                t = mv.dataset_table(self._db, snap, key)
                body_layout.addWidget(DenseTable(t["columns"], t["rows"]))
            except Exception as exc:
                body_layout.addWidget(DenseTable(["Error"], [[str(exc)[:120]]]))
            self._draw_dataset_chart(chart, snap, key)

        snap_combo.currentIndexChanged.connect(lambda _i: load_snapshot())
        ds_combo.currentIndexChanged.connect(lambda _i: render_dataset())
        load_snapshot()
        return panel

    def _draw_dataset_chart(self, chart, snap, key):
        """Draw the chart appropriate to the selected dataset, or hide it."""
        from services import market_views as mv
        try:
            if key == "curves":
                series = mv.curve_overlay_chart(snap)
                chart.plot_curves(series, title="Yield Curves (overlay)")
                chart.show()
            elif key == "commodity" and self._db is not None:
                series = mv.commodity_curve_chart(self._db, snap.snapshot_id)
                if series:
                    chart.plot_curves(series, title="Commodity Futures (strip)",
                                      xlabel="Years to expiry", ylabel="Settle")
                    chart.show()
                else:
                    chart.hide()
            else:
                chart.hide()
        except Exception:
            chart.hide()

    def _breakeven_panel(self):
        """Market breakeven inflation (nominal − real) when both curves exist."""
        from services import market_views as mv
        be = mv.breakeven_term_structure(self.snapshot)
        if not be["available"]:
            return None
        panel = WorkstationPanel("Breakeven Inflation (КБД − OFZ-IN real)")
        rows = [[f"{T}y", f"{n:.2f}%", f"{r:.2f}%", f"{b:.2f}%"]
                for T, n, r, b in zip(be["tenors"], be["nominal"],
                                      be["real"], be["breakeven"])]
        panel.layout.addWidget(
            DenseTable(["Tenor", "Nominal", "Real", "Breakeven"], rows))
        return panel

    def _data_health_tab(self):
        """Snapshot coverage calendar + recent ingest log + quality alerts."""
        panel = WorkstationPanel("Data Health")
        if self._db is None:
            panel.layout.addWidget(self._snapshot_context_table(
                "Demo mode — no local market-data DB connected"))
            return panel
        from services import market_views as mv
        from infra.jobs.data_quality import snapshot_quality_report
        cal = mv.snapshot_calendar(self._db, 30)
        rep = snapshot_quality_report(self._db, self.snapshot.snapshot_id)
        panel.layout.addWidget(DenseTable(
            ["Metric", "Value"],
            [["Snapshot", rep["snapshot_id"]],
             ["Source / quality", f"{rep['source']} / {rep['quality']}"],
             ["Completeness", f"{rep['completeness_pct']}%"],
             ["Freshness", f"{rep.get('staleness_days', '—')} days"],
             ["Calendar coverage (30d)", f"{cal['present']}/{cal['business_days']} "
                                         f"({cal['coverage_pct']}%)"],
             ["Status", rep["status"]],
             ["Alerts", "; ".join(rep["alerts"]) or "none"]]))
        log_rows = [[r["endpoint"][:42], r["status"], r["rows"] or 0,
                     str(r["finished_at"])[:19]]
                    for r in mv.ingest_history(self._db, 20)]
        if log_rows:
            panel.layout.addWidget(DenseTable(
                ["Endpoint", "Status", "Rows", "Finished"], log_rows))
        return panel

    def _curve_explorer_tab(self):
        panel = WorkstationPanel("Curve Explorer")
        panel.layout.addWidget(self._snapshot_context_table("Yield curves"))
        rows = []
        for curve_id, curve in self.snapshot.curves.items():
            check = curve.validate()
            rows.append(
                [
                    curve_id,
                    getattr(curve, "label", curve_id),
                    self.snapshot.source_value,
                    self.snapshot.quality,
                    self._timestamp(),
                    self.snapshot.snapshot_id,
                    self._lineage_label(),
                    "Pass" if check.valid else "Fail",
                    len(getattr(curve, "tenors", [])),
                    self._pct(curve.rate(1.0)),
                    self._pct(curve.rate(5.0)),
                    self._pct(curve.rate(10.0)),
                ]
            )
        panel.layout.addWidget(
            DenseTable(
                [
                    "Curve ID",
                    "Label",
                    "Source",
                    "Quality",
                    "Timestamp",
                    "Snapshot ID",
                    "Lineage",
                    "Validation",
                    "Tenors",
                    "1Y",
                    "5Y",
                    "10Y",
                ],
                rows,
            )
        )
        # overlay chart of all snapshot curves
        try:
            from app.chart import ChartWidget
            from services import market_views as mv
            series = mv.curve_overlay_chart(self.snapshot)
            if series:
                chart = ChartWidget()
                chart.setMinimumHeight(240)
                chart.plot_curves(series, title="Yield Curves (overlay)")
                panel.layout.addWidget(chart)
        except Exception:
            pass
        breakeven = self._breakeven_panel()
        if breakeven is not None:
            panel.layout.addWidget(breakeven)
        # КБД tenor history (if a live DB carries the series)
        if self._db is not None:
            try:
                from app.chart import ChartWidget
                from services import market_views as mv
                hist = mv.curve_history_series(self._db, "KBD:5Y")
                if len(hist["dates"]) > 5:
                    h = ChartWidget()
                    h.setMinimumHeight(220)
                    h.plot_series(hist["dates"], [("KBD 5Y", hist["values"])],
                                  title="КБД 5Y history", ylabel="Rate (%)")
                    panel.layout.addWidget(h)
            except Exception:
                pass
        panel.layout.addWidget(self._lineage_table())
        return panel

    def _fx_explorer_tab(self):
        panel = WorkstationPanel("FX Explorer")
        panel.layout.addWidget(self._snapshot_context_table("FX rates"))
        rows = [
            [
                pair,
                rate,
                self.snapshot.source_value,
                self.snapshot.quality,
                self._timestamp(),
                self.snapshot.snapshot_id,
                self._lineage_label(),
                "Pass" if self._positive_number(rate) else "Fail",
            ]
            for pair, rate in sorted(self.snapshot.fx_rates.items())
        ]
        panel.layout.addWidget(
            DenseTable(
                ["Pair", "Spot", "Source", "Quality", "Timestamp", "Snapshot ID", "Lineage", "Validation"],
                rows,
            )
        )
        panel.layout.addWidget(self._lineage_table())
        return panel

    def _vol_surface_explorer_tab(self):
        panel = WorkstationPanel("Vol Surface Explorer")
        panel.layout.addWidget(self._snapshot_context_table("Vol surfaces"))
        rows = []
        for surface_id, surface in sorted(self.snapshot.vol_surfaces.items()):
            rows.append(
                [
                    surface_id,
                    self._value(surface, "type"),
                    self._vol_value(surface),
                    self.snapshot.source_value,
                    self.snapshot.quality,
                    self._timestamp(),
                    self.snapshot.snapshot_id,
                    self._lineage_label(),
                    self._vol_validation(surface),
                ]
            )
        panel.layout.addWidget(
            DenseTable(
                ["Surface ID", "Type", "Vol", "Source", "Quality", "Timestamp", "Snapshot ID", "Lineage", "Validation"],
                rows,
            )
        )
        smile = self._smile_explorer_panel()
        if smile is not None:
            panel.layout.addWidget(smile)
        panel.layout.addWidget(self._lineage_table())
        return panel

    def _smile_explorer_panel(self):
        """
        Vol Explorer 2.0: dropdown over all implied underlyings; the chosen one
        shows its per-expiry smile table, a smile+SVI chart, and the ATM term
        structure. Self-implied from settlement prices.
        """
        if self._db is None:
            return None
        from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget
        from app.chart import ChartWidget
        from services import market_views as mv

        sid = self.snapshot.snapshot_id
        unds = mv.vol_underlyings(self._db, sid)
        if not unds:
            return None

        panel = WorkstationPanel("Vol Explorer — implied surfaces (self-implied)")
        combo = QComboBox()
        combo.setObjectName("vol_underlying_selector")
        for u in unds:
            combo.addItem(u)
        # headline default: a liquid FX/index/commodity surface if present
        for pref in ("Si", "RTS", "GOLD", "BR"):
            if pref in unds:
                combo.setCurrentIndex(unds.index(pref))
                break
        sel = QHBoxLayout()
        sel.addWidget(QLabel("Underlying:"))
        sel.addWidget(combo, 1)
        sel.addStretch()
        sel_wrap = QWidget()
        sel_wrap.setLayout(sel)
        panel.layout.addWidget(sel_wrap)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 8, 0, 0)
        panel.layout.addWidget(body)
        smile_chart = ChartWidget()
        smile_chart.setMinimumHeight(230)
        panel.layout.addWidget(smile_chart)
        term_chart = ChartWidget()
        term_chart.setMinimumHeight(200)
        panel.layout.addWidget(term_chart)

        def render():
            while body_layout.count():
                w = body_layout.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            underlying = combo.currentText()
            smile = mv.vol_smile_slices(self._db, sid, underlying)
            rows = [[s["expiry"], s["n_points"], f"{s['forward']:.4g}",
                     f"{s['atm_vol']:.2f}%",
                     (f"{s['svi']['rmse']:.2f}%" if s.get("svi") else "—")]
                    for s in smile["slices"]]
            body_layout.addWidget(DenseTable(
                ["Expiry", "Strikes", "Forward", "ATM vol", "SVI rmse"], rows))
            # smile + SVI chart (first fitted expiry)
            slc = next((s for s in smile["slices"] if s.get("svi")), None)
            if slc is not None:
                smile_chart.plot_vol_smile(
                    slc["strikes"], [v / 100 for v in slc["vols"]], F=slc["forward"],
                    strikes2=slc["strikes"], vols2=[v / 100 for v in slc["svi"]["fit_vols"]],
                    label2=f"SVI rmse {slc['svi']['rmse']:.2f}%")
                smile_chart.show()
            else:
                smile_chart.hide()
            # ATM term structure
            ats = mv.atm_term_structure(smile)
            if len(ats["expiries"]) > 1:
                term_chart.plot_series(ats["expiries"], [("ATM vol", ats["atm_vols"])],
                                       title=f"{underlying} ATM term structure",
                                       ylabel="ATM vol (%)")
                term_chart.show()
            else:
                term_chart.hide()

        combo.currentIndexChanged.connect(lambda _i: render())
        render()
        return panel

    def _credit_curve_explorer_tab(self):
        panel = WorkstationPanel("Credit Curve Explorer")
        panel.layout.addWidget(self._snapshot_context_table("Credit curves"))
        rows = []
        for curve_id, curve in sorted(self.snapshot.credit_curves.items()):
            # Bootstrapped hazard curves are service-owned objects; detect them
            # structurally to keep this workspace free of engine-layer imports.
            if hasattr(curve, "hazards") and hasattr(curve, "survival"):
                ok = all(self._non_negative_number(h) for h in curve.hazards)
                rows.append(
                    [
                        curve_id,
                        "hazard curve",
                        f"λ(5y) {curve.hazard(5.0) * 100:.2f}% / Q(5y) {curve.survival(5.0):.2f}",
                        self.snapshot.source_value,
                        self.snapshot.quality,
                        self._timestamp(),
                        self.snapshot.snapshot_id,
                        self._lineage_label(),
                        "Pass" if ok and "infeasible_tenors" not in curve.metadata else "Review",
                    ]
                )
                continue
            spread = self._value(curve, "spread")
            rows.append(
                [
                    curve_id,
                    self._value(curve, "base_curve_id"),
                    self._spread(spread),
                    self.snapshot.source_value,
                    self.snapshot.quality,
                    self._timestamp(),
                    self.snapshot.snapshot_id,
                    self._lineage_label(),
                    "Pass" if self._non_negative_number(spread) else "Review",
                ]
            )
        for spread_id, spread in sorted(self.snapshot.credit_spreads.items()):
            rows.append(
                [
                    spread_id,
                    "spread",
                    self._spread(spread),
                    self.snapshot.source_value,
                    self.snapshot.quality,
                    self._timestamp(),
                    self.snapshot.snapshot_id,
                    self._lineage_label(),
                    "Pass" if self._non_negative_number(spread) else "Fail",
                ]
            )
        panel.layout.addWidget(
            DenseTable(
                ["Curve / Spread", "Base", "Spread", "Source", "Quality", "Timestamp", "Snapshot ID", "Lineage", "Validation"],
                rows,
            )
        )
        panel.layout.addWidget(self._lineage_table())
        return panel

    def _build_validation(self):
        panel = WorkstationPanel("Validation")
        panel.layout.addWidget(
            DenseTable(
                ["Check", "Status", "Detail"],
                [
                    ["Snapshot ID", "Pass" if self.snapshot.snapshot_id else "Fail", self.snapshot.snapshot_id],
                    ["Timestamp", "Pass" if self.snapshot.created_at.tzinfo else "Fail", self._timestamp()],
                    ["Source", "Pass", self.snapshot.source_value],
                    ["Yield curves", self.validation["curve_status"], self.validation["curve_detail"]],
                    ["FX", self.validation["fx_status"], self.validation["fx_detail"]],
                    ["Vol surfaces", self.validation["vol_status"], self.validation["vol_detail"]],
                    ["Credit curves", self.validation["credit_status"], self.validation["credit_detail"]],
                    ["Source quality", "Warn" if self.snapshot.is_demo else "Pass", self.snapshot.quality],
                ],
            )
        )
        return panel

    def _build_snapshot_metadata(self):
        panel = WorkstationPanel("Active Snapshot Metadata")
        panel.layout.addWidget(
            DenseTable(
                ["Field", "Value"],
                [
                    ["Snapshot ID", self.snapshot.snapshot_id],
                    ["Version", f"v{self.snapshot.version}"],
                    ["Valuation Date", self.snapshot.valuation_date.isoformat()],
                    ["Timestamp", self._timestamp()],
                    ["Source", self.snapshot.source_value],
                    ["Quality", self.snapshot.quality],
                    ["Created By", self.snapshot.created_by],
                    ["Provider", self.snapshot.source_details.get("provider", "")],
                    ["Parent Snapshot", self.snapshot.parent_snapshot_id or "ROOT"],
                    ["Lineage", self._lineage_label()],
                    ["Warning", self.snapshot.metadata.get("warning", "")],
                ],
            )
        )
        return panel

    def _snapshot_context_table(self, data_set: str) -> DenseTable:
        return DenseTable(
            ["Field", "Value"],
            [
                ["Dataset", data_set],
                ["Snapshot ID", self.snapshot.snapshot_id],
                ["Version", f"v{self.snapshot.version}"],
                ["Source", self.snapshot.source_value],
                ["Quality", self.snapshot.quality],
                ["Validation", self.validation["status"]],
                ["Last Update", self._timestamp()],
                ["Lineage", self._lineage_label()],
            ],
        )

    def _lineage_table(self) -> DenseTable:
        rows = [
            [
                item["snapshot_id"],
                f"v{item['version']}",
                item["source"],
                item["quality"],
                item["created_at"].isoformat(timespec="seconds"),
                item["parent_snapshot_id"] or "ROOT",
                item["created_by"],
            ]
            for item in self.snapshot_lineage
        ]
        return DenseTable(
            ["Snapshot", "Version", "Source", "Quality", "Last Update", "Parent", "Created By"],
            rows or [[self.snapshot.snapshot_id, f"v{self.snapshot.version}", self.snapshot.source_value, self.snapshot.quality, self._timestamp(), "ROOT", self.snapshot.created_by]],
        )

    def _validation_summary(self) -> dict[str, str | int]:
        curve_results = [curve.validate() for curve in self.snapshot.curves.values()]
        curve_failures = [result for result in curve_results if not result.valid]
        fx_failures = [pair for pair, rate in self.snapshot.fx_rates.items() if not self._positive_number(rate)]
        vol_failures = [
            surface_id
            for surface_id, surface in self.snapshot.vol_surfaces.items()
            if self._vol_validation(surface) != "Pass"
        ]
        credit_failures = [
            key
            for key, value in self.snapshot.credit_spreads.items()
            if not self._non_negative_number(value)
        ]
        warning_count = int(self.snapshot.is_demo)
        if curve_failures or fx_failures or vol_failures or credit_failures:
            status = "Fail"
        elif warning_count:
            status = "Warn"
        else:
            status = "Pass"
        return {
            "status": status,
            "warnings": warning_count,
            "curve_status": "Pass" if not curve_failures else "Fail",
            "curve_detail": f"{len(curve_results)} curves checked",
            "fx_status": "Pass" if not fx_failures else "Fail",
            "fx_detail": f"{len(self.snapshot.fx_rates)} pairs checked",
            "vol_status": "Pass" if not vol_failures else "Fail",
            "vol_detail": f"{len(self.snapshot.vol_surfaces)} surfaces checked",
            "credit_status": "Pass" if not credit_failures else "Fail",
            "credit_detail": f"{len(self.snapshot.credit_curves)} curves / {len(self.snapshot.credit_spreads)} spreads",
        }

    def _timestamp(self) -> str:
        return self.snapshot.created_at.isoformat(timespec="seconds")

    def _lineage_label(self) -> str:
        return " -> ".join(f"v{item['version']}" for item in self.snapshot_lineage) or f"v{self.snapshot.version}"

    def _pct(self, value: float) -> str:
        return f"{value * 100:.2f}%"

    def _spread(self, value) -> str:
        return "" if value in ("", None) else f"{float(value) * 10_000:.0f}bp"

    def _value(self, item, key: str):
        if isinstance(item, dict):
            return item.get(key, "")
        return getattr(item, key, "")

    def _vol_value(self, surface) -> str:
        # rates-vol structures first (duck-typed; their .vol is a METHOD, so the
        # generic _value lookup below must not see them)
        if hasattr(surface, "atm_vol"):
            return f"ATM(1y,5y) {self._pct(float(surface.atm_vol(1.0, 5.0)))}"
        if hasattr(surface, "expiries") and callable(getattr(surface, "vol", None)):
            return f"ATM(1y) {self._pct(float(surface.vol(1.0)))}"
        vol = self._value(surface, "vol")
        if vol in ("", None) and isinstance(surface, dict) and surface.get("type") == "rr_bf":
            atm, rr, bf = surface.get("atm"), surface.get("rr", 0), surface.get("bf", 0)
            if atm is not None:
                return f"{self._pct(float(atm))} (RR {rr * 100:+.1f} / BF {bf * 100:.1f})"
        return "" if vol in ("", None) else self._pct(float(vol))

    def _vol_validation(self, surface) -> str:
        if hasattr(surface, "atm_vol"):
            vol = surface.atm_vol(1.0, 5.0)
        elif hasattr(surface, "expiries") and callable(getattr(surface, "vol", None)):
            vol = surface.vol(1.0)
        else:
            vol = self._value(surface, "vol")
            if vol in ("", None) and isinstance(surface, dict) and surface.get("type") == "rr_bf":
                vol = surface.get("atm")    # FX smile quote set: ATM anchors the level
        return "Pass" if self._positive_number(vol) else "Review"

    def _positive_number(self, value) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and number > 0

    def _non_negative_number(self, value) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and number >= 0
