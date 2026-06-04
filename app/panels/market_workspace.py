"""Market Data workstation backed by MarketDataService snapshots."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import math

from PySide6.QtWidgets import QTabWidget

from services.market_data_service import MarketDataService
from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class MarketWorkspace(WorkstationWorkspace):
    """Market Data owns source, timestamp, snapshots, and validation display."""

    def __init__(self, parent=None):
        self.market_data = MarketDataService()
        self.snapshot = self.market_data.demo_snapshot()
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
        tabs.addTab(self._curve_explorer_tab(), "Curve Explorer")
        tabs.addTab(self._fx_explorer_tab(), "FX Explorer")
        tabs.addTab(self._vol_surface_explorer_tab(), "Vol Surface Explorer")
        tabs.addTab(self._credit_curve_explorer_tab(), "Credit Curve Explorer")
        return tabs

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
        panel.layout.addWidget(self._lineage_table())
        return panel

    def _credit_curve_explorer_tab(self):
        panel = WorkstationPanel("Credit Curve Explorer")
        panel.layout.addWidget(self._snapshot_context_table("Credit curves"))
        rows = []
        for curve_id, curve in sorted(self.snapshot.credit_curves.items()):
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
        vol = self._value(surface, "vol")
        return "" if vol in ("", None) else self._pct(float(vol))

    def _vol_validation(self, surface) -> str:
        vol = self._value(surface, "vol")
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
