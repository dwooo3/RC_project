"""Governance workspace backed by GovernanceService."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QTabWidget

from services.governance_service import GovernanceService
from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace


class GovernanceWorkspace(WorkstationWorkspace):
    """Expose model governance, validation, audit, and limitations."""

    def __init__(self, parent=None):
        self.governance = GovernanceService()
        self.models = self.governance.list_models()
        self.counts = self.governance.status_counts()
        super().__init__(
            "Governance",
            "Model registry, validation status, audit trail, and limitations",
            chips=[
                DataSourceChip("REGISTRY"),
                StatusChip(self._worst_status(), text=f"Registry: {self._worst_status()}"),
            ],
            actions=[make_action("Review Models", True), make_action("Export")],
            kpi_strip=self._build_kpis(),
            left=self._build_summary(),
            center=self._build_sections(),
            right=self._build_policy(),
            bottom=self._build_limitation_preview(),
            context_items=[
                ("Layer", "Governance"),
                ("Service", "GovernanceService"),
                ("Model Registry", f"{len(self.models)} models"),
                ("Validation", "Status and evidence surfaced"),
                ("Audit Trail", "Pending persistence"),
                ("Limitations", "User visible"),
            ],
            parent=parent,
        )

    def _build_kpis(self):
        missing_validation = sum(1 for model in self.models if not model.validation_date)
        limitation_count = len(self.governance.limitations_report())
        return KpiStrip(
            [
                ("Models", str(len(self.models)), "registered"),
                ("Approx", str(self.counts.get("Approximation", 0)), "allowed with warnings"),
                ("Prototype", str(self.counts.get("Prototype", 0)), "not production"),
                ("Blocked", str(self.counts.get("Placeholder", 0) + self.counts.get("Broken", 0)), "placeholder/broken"),
                ("No Val Date", str(missing_validation), "metadata gap"),
                ("Limitations", str(limitation_count), "visible"),
            ]
        )

    def _build_summary(self):
        panel = WorkstationPanel("Governance Sections")
        panel.layout.addWidget(
            DenseTable(
                ["Section", "Purpose"],
                [
                    ["Model Registry", "Canonical inventory"],
                    ["Validation Status", "Evidence and production gating"],
                    ["Audit Trail", "Calculation provenance"],
                    ["Limitations", "User-facing caveats"],
                ],
            )
        )
        panel.layout.addWidget(
            DenseTable(
                ["Status", "Count"],
                [[status, count] for status, count in sorted(self.counts.items())],
            )
        )
        return panel

    def _build_sections(self):
        tabs = QTabWidget()
        tabs.addTab(self._model_registry_tab(), "Model Registry")
        tabs.addTab(self._validation_status_tab(), "Validation Status")
        tabs.addTab(self._audit_trail_tab(), "Audit Trail")
        tabs.addTab(self._limitations_tab(), "Limitations")
        return tabs

    def _model_registry_tab(self):
        panel = WorkstationPanel("Model Registry")
        rows = [
            [
                model.model_id,
                model.version,
                model.status,
                model.owner,
                self._date(model.validation_date),
                "Yes" if model.production_allowed else "No",
                model.workflow_layer,
                self._limit_summary(model.limitations),
            ]
            for model in self.models
        ]
        panel.layout.addWidget(
            DenseTable(
                [
                    "Model ID",
                    "Version",
                    "Status",
                    "Owner",
                    "Validation Date",
                    "Prod Allowed",
                    "Layer",
                    "Limitations",
                ],
                rows,
            )
        )
        return panel

    def _validation_status_tab(self):
        panel = WorkstationPanel("Validation Status")
        rows = []
        for item in self.governance.validation_status():
            rows.append(
                [
                    item["model_id"],
                    item["status"],
                    self._date(item["validation_date"]),
                    item["evidence_count"],
                    ", ".join(item["tests"]) or "No tests recorded",
                    "Yes" if item["production_allowed"] else "No",
                    item["workflow_layer"],
                ]
            )
        panel.layout.addWidget(
            DenseTable(
                ["Model ID", "Status", "Validation Date", "Evidence", "Tests", "Prod Allowed", "Layer"],
                rows,
            )
        )
        return panel

    def _audit_trail_tab(self):
        panel = WorkstationPanel("Audit Trail")
        rows = [
            [
                item["timestamp"],
                item["event"],
                item["model_id"],
                item["version"],
                item["status"],
                item["details"],
            ]
            for item in self.governance.audit_trail()
        ]
        panel.layout.addWidget(
            DenseTable(["Timestamp", "Event", "Model ID", "Version", "Status", "Details"], rows)
        )
        return panel

    def _limitations_tab(self):
        panel = WorkstationPanel("Limitations")
        rows = [
            [
                item["model_id"],
                item["status"],
                "Yes" if item["production_allowed"] else "No",
                item["limitation"],
            ]
            for item in self.governance.limitations_report()
        ]
        panel.layout.addWidget(DenseTable(["Model ID", "Status", "Prod Allowed", "Limitation"], rows))
        return panel

    def _build_policy(self):
        panel = WorkstationPanel("Governance Policy")
        panel.layout.addWidget(
            DenseTable(
                ["Policy", "State"],
                [
                    ["Service integration", "GovernanceService"],
                    ["Broken models", "Blocked"],
                    ["Placeholder models", "Blocked"],
                    ["Prototype models", "Warnings + not production"],
                    ["Approximation models", "Allowed with warnings"],
                    ["Validation evidence", "Visible in registry"],
                    ["Audit persistence", "Pending"],
                ],
            )
        )
        return panel

    def _build_limitation_preview(self):
        panel = WorkstationPanel("Top Limitations")
        rows = []
        for item in self.governance.limitations_report()[:12]:
            rows.append([item["model_id"], item["status"], item["limitation"]])
        panel.layout.addWidget(DenseTable(["Model ID", "Status", "Limitation"], rows))
        return panel

    def _worst_status(self) -> str:
        order = ["Validated", "Approximation", "Prototype", "Placeholder", "Broken"]
        statuses = [model.status for model in self.models]
        return max(statuses, key=lambda status: order.index(status) if status in order else 0)

    def _date(self, value) -> str:
        return value.isoformat() if value else ""

    def _limit_summary(self, limitations: list[str]) -> str:
        if not limitations:
            return "None recorded"
        text = limitations[0]
        return text if len(text) <= 120 else text[:117] + "..."
