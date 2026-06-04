"""Analytics Lab workspace backed by GovernanceService."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import QLabel, QTabWidget

from services.governance_service import GovernanceService
from ui.components import DataSourceChip, DenseTable, KpiStrip, StatusChip, WorkstationPanel, make_action
from ui.layouts import WorkstationWorkspace
from ui.theme import PALETTE


RESEARCH_SECTIONS = {
    "Rates Models": [
        ("short_rate", "Hull-White / Vasicek / CIR", "Research calibration and rate model experiments"),
        ("frn", "Floating Rate Note", "Prototype reset/projection research"),
        ("capfloor", "Cap / Floor / Swaption", "Rates option methodology under approximation governance"),
    ],
    "Volatility Models": [
        ("heston_cf", "Heston Characteristic Function", "Stochastic volatility research"),
        ("sabr", "SABR", "Smile calibration research"),
        ("garch", "GARCH / EWMA", "Volatility forecasting research"),
    ],
    "Monte Carlo": [
        ("mc_gbm", "Monte Carlo GBM", "Simulation and convergence experiments"),
        ("mc_lsm", "Longstaff-Schwartz LSM", "American exercise research"),
        ("mc_heston", "Heston Monte Carlo", "Stochastic-volatility path simulation"),
        ("multi_asset", "Multi-Asset / Rainbow", "Correlation and basket simulation research"),
    ],
    "Research Sandbox": [
        ("barrier", "Barrier Options", "Prototype exotic option formulas"),
        ("asian", "Asian Options", "Prototype averaging methodology"),
        ("structured_autocall", "Autocall / Phoenix", "Structured product research"),
        ("cln_ftd", "CLN / FTD", "Credit copula research"),
        ("placeholder", "Unregistered Sandbox", "Blocked placeholder guardrail"),
    ],
}


class AnalyticsWorkspace(WorkstationWorkspace):
    """Research-only model lab separated from production workflows."""

    def __init__(self, parent=None):
        self.governance = GovernanceService()
        self.section_models = self._load_sections()
        super().__init__(
            "Analytics Lab",
            "Research models, experiments, and sandbox workflows separated from production",
            chips=[
                DataSourceChip("RESEARCH"),
                StatusChip("Prototype", text="RESEARCH"),
            ],
            actions=[make_action("Open Governance"), make_action("Export")],
            kpi_strip=self._build_kpis(),
            left=self._build_boundary_panel(),
            center=self._build_sections(),
            right=self._build_policy_panel(),
            bottom=self._build_warning_log(),
            context_items=[
                ("Layer", "Analytics Lab"),
                ("Mode", "RESEARCH"),
                ("Production", "Use Pricing/Risk workspaces"),
                ("Governance", "Research models not production allowed"),
                ("Bypass", "Requires explicit allow_analytics_lab=True in services"),
            ],
            parent=parent,
        )

    def _load_sections(self) -> dict[str, list[dict]]:
        sections = {}
        for section, specs in RESEARCH_SECTIONS.items():
            rows = []
            for model_id, name, purpose in specs:
                model = self.governance.get_model(model_id)
                warnings = self.governance.warnings_for_model(model_id)
                rows.append(
                    {
                        "model": model,
                        "name": name,
                        "purpose": purpose,
                        "warnings": warnings,
                        "banner": "RESEARCH" if not model.production_allowed else "PRODUCTION",
                    }
                )
            sections[section] = rows
        return sections

    def _build_kpis(self):
        models = self._all_rows()
        research = sum(1 for row in models if row["banner"] == "RESEARCH")
        production = sum(1 for row in models if row["banner"] == "PRODUCTION")
        blocked = sum(1 for row in models if not row["model"].production_allowed)
        warnings = sum(len(row["warnings"]) for row in models)
        return KpiStrip(
            [
                ("Models", str(len(models)), "lab inventory"),
                ("Research", str(research), "lab-only"),
                ("Production", str(production), "reference only"),
                ("Blocked", str(blocked), "not production"),
                ("Warnings", str(warnings), "governance"),
                ("Runs", "0", "no production execution"),
            ]
        )

    def _build_boundary_panel(self):
        panel = WorkstationPanel("Workflow Boundary")
        panel.layout.addWidget(self._banner("PRODUCTION", "Pricing, Risk, Portfolio, and Market Data workspaces"))
        panel.layout.addWidget(
            DenseTable(
                ["Production Rule", "State"],
                [
                    ["Production calculations", "Outside Analytics Lab"],
                    ["Research model use", "Blocked unless service opt-in is explicit"],
                    ["Result promotion", "Requires Governance review"],
                    ["Model warnings", "Always visible"],
                ],
            )
        )
        panel.layout.addWidget(self._banner("RESEARCH", "Analytics Lab models are experiments and prototypes"))
        return panel

    def _build_sections(self):
        tabs = QTabWidget()
        tabs.addTab(self._section_tab("Rates Models"), "Rates Models")
        tabs.addTab(self._section_tab("Volatility Models"), "Volatility Models")
        tabs.addTab(self._section_tab("Monte Carlo"), "Monte Carlo")
        tabs.addTab(self._section_tab("Research Sandbox"), "Research Sandbox")
        return tabs

    def _section_tab(self, section: str):
        panel = WorkstationPanel(section)
        panel.layout.addWidget(self._banner("RESEARCH", f"{section} are not production workflows"))
        rows = []
        for row in self.section_models[section]:
            model = row["model"]
            rows.append(
                [
                    row["banner"],
                    model.model_id,
                    model.version,
                    model.status,
                    model.owner,
                    "Yes" if model.production_allowed else "No",
                    model.workflow_layer,
                    row["purpose"],
                    len(row["warnings"]),
                ]
            )
        panel.layout.addWidget(
            DenseTable(
                [
                    "Boundary",
                    "Model ID",
                    "Version",
                    "Status",
                    "Owner",
                    "Prod Allowed",
                    "Layer",
                    "Purpose",
                    "Warnings",
                ],
                rows,
            )
        )
        return panel

    def _build_policy_panel(self):
        panel = WorkstationPanel("Production Guardrails")
        panel.layout.addWidget(
            DenseTable(
                ["Guardrail", "Implementation"],
                [
                    ["Registry owner", "GovernanceService"],
                    ["Research model default", "Not production allowed"],
                    ["Production bypass", "No UI bypass in Analytics Lab"],
                    ["Service bypass", "Explicit allow_analytics_lab=True only"],
                    ["Placeholder", "Blocked"],
                    ["Broken", "Blocked"],
                ],
            )
        )
        return panel

    def _build_warning_log(self):
        panel = WorkstationPanel("Research Warnings")
        rows = []
        for section, items in self.section_models.items():
            for item in items:
                model = item["model"]
                messages = item["warnings"] or ["No warnings recorded"]
                for message in messages[:2]:
                    rows.append([section, item["banner"], model.model_id, model.status, message])
        panel.layout.addWidget(DenseTable(["Section", "Boundary", "Model ID", "Status", "Warning"], rows))
        return panel

    def _banner(self, label: str, detail: str) -> QLabel:
        banner = QLabel(f"{label}  |  {detail}")
        banner.setWordWrap(True)
        if label == "PRODUCTION":
            bg, fg, border = PALETTE.bg_success, PALETTE.green, PALETTE.status_valid_border
        else:
            bg, fg, border = PALETTE.status_prototype_bg, PALETTE.status_prototype_text, PALETTE.status_prototype_border
        banner.setStyleSheet(
            f"background:{bg};color:{fg};border:1px solid {border};"
            "border-radius:5px;padding:7px 10px;font-size:11px;font-weight:700;"
        )
        return banner

    def _all_rows(self) -> list[dict]:
        return [row for rows in self.section_models.values() for row in rows]
