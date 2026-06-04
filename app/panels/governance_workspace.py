"""Governance workspace for model status, validation, and audit context."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QTabWidget

from services.governance_service import GovernanceService
from ui.components import (
    DataSourceChip,
    DenseTable,
    KpiStrip,
    StatusChip,
    WorkstationPanel,
    make_action,
)
from ui.layouts import WorkstationWorkspace


class GovernanceWorkspace(WorkstationWorkspace):
    """First-class model governance layer."""

    def __init__(self, parent=None):
        self.governance = GovernanceService()
        self._models = self._load_models()
        super().__init__(
            "Governance",
            "Model registry, validation, audit trail, and production gating",
            chips=[DataSourceChip("DEMO"), StatusChip("Approximation", text="Production gating active")],
            actions=[make_action("Export", primary=False)],
            kpi_strip=self._build_kpis(),
            left=self._build_filters(),
            center=self._build_registry(),
            right=self._build_validation(),
            bottom=self._build_bottom_tabs(),
            context_items=[
                ("Layer", "Model Governance"),
                ("Production gating", "Broken and Placeholder models blocked"),
                ("Prototype policy", "Warnings surfaced through services"),
                ("Audit", "Calculation audit trail pending persistence"),
            ],
            parent=parent,
        )

    def _load_models(self):
        from models.registry import MODEL_REGISTRY

        rows = []
        for model_id in sorted(MODEL_REGISTRY):
            model = self.governance.get_model(model_id)
            rows.append(model)
        return rows

    def _build_kpis(self):
        counts = {"Validated": 0, "Approximation": 0, "Prototype": 0, "Placeholder": 0, "Broken": 0}
        for model in self._models:
            counts[model.status] = counts.get(model.status, 0) + 1
        return KpiStrip(
            [
                ("Validated", str(counts.get("Validated", 0)), "Production ready"),
                ("Approximation", str(counts.get("Approximation", 0)), "Allowed with warnings"),
                ("Prototype", str(counts.get("Prototype", 0)), "Research or limited"),
                ("Placeholder", str(counts.get("Placeholder", 0)), "Blocked"),
                ("Broken", str(counts.get("Broken", 0)), "Blocked"),
                ("Used Today", "0", "No persisted audit yet"),
            ]
        )

    def _build_filters(self):
        panel = WorkstationPanel("Governance Views")
        rows = [
            ("Model Registry", "Canonical model inventory"),
            ("Validation Matrix", "Coverage and evidence"),
            ("Audit Trail", "Calculation provenance"),
            ("Approvals", "Lifecycle workflow"),
            ("Production Gating", "Blocked model policy"),
        ]
        table = DenseTable(["View", "Purpose"], rows)
        panel.layout.addWidget(table)
        panel.layout.addStretch()
        return panel

    def _build_registry(self):
        panel = WorkstationPanel("Model Registry")
        rows = [
            [
                model.model_id,
                model.name,
                model.domain,
                model.status,
                model.owner,
                "Yes" if model.production_allowed else "No",
            ]
            for model in self._models
        ]
        panel.layout.addWidget(
            DenseTable(["Model ID", "Name", "Domain", "Status", "Owner", "Prod"], rows)
        )
        return panel

    def _build_validation(self):
        panel = WorkstationPanel("Validation Context")
        blocked = [m for m in self._models if m.status in {"Broken", "Placeholder"}]
        prototype = [m for m in self._models if m.status == "Prototype"]
        rows = [
            ("Blocked models", len(blocked)),
            ("Prototype models", len(prototype)),
            ("Research-only models", sum(1 for m in self._models if m.analytics_lab_only)),
            ("Missing persistent audit", "Yes"),
        ]
        panel.layout.addWidget(DenseTable(["Check", "Value"], rows))
        return panel

    def _build_bottom_tabs(self):
        tabs = QTabWidget()
        validation = WorkstationPanel("Validation Matrix")
        validation.layout.addWidget(
            DenseTable(
                ["Area", "Status", "Next Action"],
                [
                    ["Pricing models", "Partial", "Attach validation evidence"],
                    ["Risk models", "Partial", "Expose backtesting evidence"],
                    ["Analytics Lab", "Separated", "Add promotion checklist"],
                    ["Audit trail", "Pending", "Persist calculation records"],
                ],
            )
        )
        audit = WorkstationPanel("Audit Trail")
        audit.layout.addWidget(
            DenseTable(
                ["Time", "Calculation", "Model", "Snapshot", "Status"],
                [["-", "No persisted records", "-", "DEMO:v3", "Pending"]],
            )
        )
        tabs.addTab(validation, "Validation")
        tabs.addTab(audit, "Audit Trail")
        return tabs
