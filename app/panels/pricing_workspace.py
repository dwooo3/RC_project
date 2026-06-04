"""Pricing workstation backed exclusively by PricingService."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QTabWidget

from services.market_data_service import MarketDataService
from services.pricing_service import PricingService
from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class PricingWorkspace(WorkstationWorkspace):
    """Professional pricing workstation with service-owned calculation paths."""

    def __init__(self, parent=None):
        self.market_data = MarketDataService()
        self.snapshot = self.market_data.demo_snapshot()
        self.pricing = PricingService(market_data=self.market_data)
        self.results = self._calculate_results()
        self.audit_trail = self.pricing.audit.audit_trail()

        super().__init__(
            "Pricing",
            "Institutional pricing workstation for governed rates, FX, equity, credit, and structured workflows",
            chips=[
                DataSourceChip(self.snapshot.source_value),
                StatusChip(self._worst_status(), text=f"Governance: {self._worst_status()}"),
            ],
            actions=[make_action("Run Pricing", True), make_action("Save Set"), make_action("Export Audit")],
            kpi_strip=self._kpi_strip(),
            left=self._pricing_inventory(),
            center=self._pricing_tabs(),
            right=self._governance_context(),
            bottom=self._audit_trail_panel(),
            context_items=[
                ("Layer", "Pricing"),
                ("Service", "PricingService"),
                ("Market Data", self.snapshot.snapshot_id),
                ("Snapshot Version", f"v{self.snapshot.version}"),
                ("Source", self.snapshot.source_value),
                ("Governance", "Model registry enforced"),
                ("Audit Records", str(len(self.audit_trail))),
            ],
            parent=parent,
        )

    def _calculate_results(self) -> dict[str, list[dict]]:
        usd_rub = self.market_data.get_fx_rate("USD/RUB", self.snapshot)
        return {
            "Rates": [
                {
                    "workflow": "Fixed-Rate Bond",
                    "input": "RUB demo bond / OFZ curve",
                    "result": self.pricing.price_bond(1000, 0.08, 5.0, 2, snapshot=self.snapshot, curve_id="ofz_demo"),
                },
                {
                    "workflow": "Interest Rate Swap",
                    "input": "5Y pay-fixed / RUONIA curve",
                    "result": self.pricing.price_irs(1_000_000, 0.10, 5.0, 2, snapshot=self.snapshot, curve_id="ruonia_demo"),
                },
            ],
            "FX": [
                {
                    "workflow": "USD/RUB Forward",
                    "input": "6M forward",
                    "result": self.pricing.price_fx_forward(usd_rub, 0.10, 0.04, 0.5, snapshot=self.snapshot),
                },
                {
                    "workflow": "USD/RUB Option",
                    "input": "6M call / GK",
                    "result": self.pricing.price_fx_option(usd_rub, 92.0, 0.5, 0.10, 0.04, 0.20, snapshot=self.snapshot),
                },
            ],
            "Equity": [
                {
                    "workflow": "Vanilla Equity Option",
                    "input": "1Y ATM call / BSM",
                    "result": self.pricing.price_vanilla_option(100.0, 100.0, 1.0, 0.05, 0.20, snapshot=self.snapshot),
                },
                {
                    "workflow": "Monte Carlo Option",
                    "input": "Research-only path",
                    "result": self.pricing.workflow_status(
                        "mc_gbm",
                        snapshot=self.snapshot,
                        reason="Monte Carlo option pricing is Analytics Lab only in Pricing Workspace v1.",
                    ),
                },
            ],
            "Credit": [
                {
                    "workflow": "Credit Default Swap",
                    "input": "CDS workflow readiness",
                    "result": self.pricing.workflow_status(
                        "cds",
                        snapshot=self.snapshot,
                        reason="CDS pricing is not yet routed through a safe PricingService wrapper.",
                    ),
                },
                {
                    "workflow": "CVA / DVA",
                    "input": "XVA workflow readiness",
                    "result": self.pricing.workflow_status(
                        "cva_dva",
                        snapshot=self.snapshot,
                        reason="CVA/DVA belongs to governed risk workflow and is not production pricing in v1.",
                    ),
                },
            ],
            "Structured": [
                {
                    "workflow": "Variance Swap",
                    "input": "Replication workflow readiness",
                    "result": self.pricing.workflow_status(
                        "variance_swap",
                        snapshot=self.snapshot,
                        reason="Variance swap pricing needs a dedicated PricingService wrapper before production workflow use.",
                    ),
                },
                {
                    "workflow": "Barrier Options",
                    "input": "Exotic workflow readiness",
                    "result": self.pricing.workflow_status(
                        "barrier",
                        snapshot=self.snapshot,
                        reason="Barrier option pricing remains prototype and is not exposed as production workflow.",
                    ),
                },
                {
                    "workflow": "Asian Options",
                    "input": "Exotic workflow readiness",
                    "result": self.pricing.workflow_status(
                        "asian",
                        snapshot=self.snapshot,
                        reason="Asian option pricing remains prototype and requires a safe service wrapper.",
                    ),
                },
                {
                    "workflow": "Structured Products",
                    "input": "Autocall / CLN readiness",
                    "result": self.pricing.workflow_status(
                        "structured_autocall",
                        snapshot=self.snapshot,
                        reason="Structured product pricing remains prototype and requires product-specific governance.",
                    ),
                },
            ],
        }

    def _kpi_strip(self):
        all_results = self._all_results()
        warning_count = sum(len(result.get("warnings", [])) for result in all_results)
        error_count = sum(len(result.get("errors", [])) for result in all_results)
        available = sum(1 for result in all_results if result.get("value") is not None and not result.get("errors"))
        blocked = sum(1 for result in all_results if result.get("errors"))
        return KpiStrip(
            [
                ("Snapshot", f"v{self.snapshot.version}", self.snapshot.snapshot_id),
                ("Pricing Tasks", str(len(all_results)), "Rates / FX / Equity / Credit / Structured"),
                ("Priced", str(available), "service calculations"),
                ("Blocked", str(blocked), "governance/readiness"),
                ("Warnings", str(warning_count), "visible"),
                ("Audit Records", str(len(self.audit_trail)), f"{error_count} errors"),
            ]
        )

    def _pricing_inventory(self):
        panel = WorkstationPanel("Pricing Sections")
        rows = []
        for section, items in self.results.items():
            rows.append([section, len(items), self._section_status(items), self._section_models(items)])
        panel.layout.addWidget(DenseTable(["Section", "Pricing Tasks", "Status", "Models"], rows))
        panel.layout.addWidget(
            DenseTable(
                ["Active Snapshot", "Value"],
                [
                    ["Snapshot ID", self.snapshot.snapshot_id],
                    ["Version", f"v{self.snapshot.version}"],
                    ["Source", self.snapshot.source_value],
                    ["Quality", self.snapshot.quality],
                    ["Last Update", self.snapshot.created_at.isoformat(timespec="seconds")],
                ],
            )
        )
        return panel

    def _pricing_tabs(self):
        tabs = QTabWidget()
        tabs.addTab(self._section_tab("Rates"), "Rates")
        tabs.addTab(self._section_tab("FX"), "FX")
        tabs.addTab(self._section_tab("Equity"), "Equity")
        tabs.addTab(self._section_tab("Credit"), "Credit")
        tabs.addTab(self._section_tab("Structured"), "Structured")
        return tabs

    def _section_tab(self, section: str):
        panel = WorkstationPanel(section)
        panel.layout.addWidget(
            DenseTable(
                [
                    "Pricing Task",
                    "Inputs",
                    "Value",
                    "Model",
                    "Version",
                    "Governance",
                    "Market Snapshot",
                    "Warnings",
                    "Audit ID",
                    "Inputs Hash",
                ],
                [self._result_row(item) for item in self.results[section]],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                [
                    "Pricing Task",
                    "Market Source",
                    "Quality",
                    "Last Update",
                    "Warnings",
                    "Errors",
                ],
                [self._provenance_row(item) for item in self.results[section]],
            )
        )
        return panel

    def _governance_context(self):
        panel = WorkstationPanel("Governance Context")
        rows = []
        seen = set()
        for result in self._all_results():
            model_id = result.get("model_id", "")
            if model_id in seen:
                continue
            seen.add(model_id)
            rows.append(
                [
                    model_id,
                    result.get("model_version", ""),
                    result.get("model_status", ""),
                    "Yes" if result.get("model_production_allowed") else "No",
                    result.get("model_workflow_layer", ""),
                    len(result.get("warnings", [])),
                ]
            )
        panel.layout.addWidget(
            DenseTable(["Model", "Version", "Status", "Prod Allowed", "Layer", "Warnings"], rows)
        )
        return panel

    def _audit_trail_panel(self):
        panel = WorkstationPanel("Pricing Audit Trail")
        audit_rows = [
            [
                record.get("timestamp", ""),
                record.get("calculation_type", ""),
                record.get("model_id", ""),
                record.get("model_version", ""),
                record.get("snapshot_id", ""),
                record.get("calculation_id", ""),
                self._short_hash(record.get("inputs_hash", "")),
            ]
            for record in self.audit_trail
        ]
        panel.layout.addWidget(
            DenseTable(
                ["Timestamp", "Calculation", "Model", "Version", "Snapshot", "Audit ID", "Inputs Hash"],
                audit_rows,
            )
        )
        rows = []
        for section, items in self.results.items():
            for item in items:
                result = item["result"]
                messages = result.get("errors") or result.get("warnings") or ["No warnings"]
                for message in messages[:3]:
                    rows.append([section, item["workflow"], result.get("model_id", ""), message])
        panel.layout.addWidget(DenseTable(["Section", "Pricing Task", "Model", "Message"], rows))
        return panel

    def _result_row(self, item: dict) -> list:
        result = item["result"]
        audit_id = result.get("calculation_id", "")
        return [
            item["workflow"],
            item["input"],
            self._format_value(result.get("value")),
            result.get("model_id", ""),
            result.get("model_version", ""),
            result.get("model_status", ""),
            result.get("market_data_snapshot_id", ""),
            len(result.get("warnings", [])),
            audit_id,
            self._short_hash(result.get("inputs_hash", "")),
        ]

    def _provenance_row(self, item: dict) -> list:
        result = item["result"]
        return [
            item["workflow"],
            result.get("market_data_source", ""),
            result.get("market_data_quality", ""),
            self.snapshot.created_at.isoformat(timespec="seconds"),
            "; ".join(result.get("warnings", [])[:2]),
            "; ".join(result.get("errors", [])),
        ]

    def _section_status(self, items: list[dict]) -> str:
        statuses = [item["result"].get("model_status", "") for item in items]
        if any(item["result"].get("errors") for item in items):
            return "Blocked"
        if any(status in {"Prototype", "Placeholder", "Broken"} for status in statuses):
            return "Prototype"
        if any(status == "Approximation" for status in statuses):
            return "Approximation"
        return "Validated"

    def _section_models(self, items: list[dict]) -> str:
        return ", ".join(sorted({item["result"].get("model_id", "") for item in items}))

    def _worst_status(self) -> str:
        order = ["Validated", "Approximation", "Prototype", "Placeholder", "Broken"]
        statuses = [result.get("model_status", "Validated") for result in self._all_results()]
        return max(statuses, key=lambda status: order.index(status) if status in order else 0)

    def _all_results(self) -> list[dict]:
        return [item["result"] for items in self.results.values() for item in items]

    def _format_value(self, value) -> str:
        if value is None:
            return "Not routed"
        if isinstance(value, float):
            return f"{value:,.4f}"
        return str(value)

    def _short_hash(self, value: str) -> str:
        return value[:12] if value else ""
