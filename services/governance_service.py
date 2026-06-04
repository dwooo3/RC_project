"""Service facade over the model registry."""

from domain.model_governance import ModelRegistryEntry
from models import registry
from services.audit_service import AuditService


_PRODUCTION_ALLOWED = {
    registry.ModelStatus.VALIDATED,
    registry.ModelStatus.APPROXIMATION,
}

_QUANT_REVIEW_STATUS = {
    "black_scholes": "Fixed",
    "black76": "Partially Validated",
    "binomial_crr": "False Positive",
    "binomial_lr": "Partially Validated",
    "trinomial": "Partially Validated",
    "mc_gbm": "Fixed",
    "mc_lsm": "Open",
    "mc_heston": "Open",
    "heston_cf": "Fixed",
    "sabr": "Open",
    "garch": "Open",
    "fixed_bond": "Partially Validated",
    "frn": "Open",
    "irs": "Partially Validated",
    "capfloor": "Partially Validated",
    "short_rate": "Fixed",
    "fx_forward": "Partially Validated",
    "garman_kohlhagen": "Partially Validated",
    "fx_smile": "Open",
    "asian": "False Positive",
    "digital": "Fixed",
    "barrier": "Open",
    "lookback": "Open",
    "multi_asset": "Open",
    "variance_swap": "Partially Validated",
    "cds": "Open",
    "cva_dva": "Open",
    "structured_autocall": "Open",
    "cln_ftd": "Open",
    "var_parametric": "Partially Validated",
    "var_historical": "Partially Validated",
    "var_mc": "Partially Validated",
    "evt_var": "Partially Validated",
    "portfolio_aggregation": "Partially Validated",
}

QUANT_REVIEW_STATUSES = ("Fixed", "False Positive", "Partially Validated", "Open")


class GovernanceService:
    """Normalize model registry entries for application services."""

    def __init__(self, audit: AuditService | None = None):
        self.audit = audit

    def list_models(self) -> list[ModelRegistryEntry]:
        """Return all registered models as normalized governance entries."""
        return [self.get_model(model_id) for model_id in sorted(registry.MODEL_REGISTRY)]

    def status_counts(self) -> dict[str, int]:
        """Return model counts by governance status."""
        counts = {status.value: 0 for status in registry.ModelStatus}
        for model in self.list_models():
            counts[model.status] = counts.get(model.status, 0) + 1
        return counts

    def get_model(self, model_id: str) -> ModelRegistryEntry:
        entry = registry.get(model_id)
        status = entry["status"]
        status_value = status.value if hasattr(status, "value") else str(status)
        notes = entry.get("notes", "")
        limitations = [notes] if notes else []
        validation_date = entry.get("validation_date", entry.get("last_validated"))
        references = list(entry.get("references", []))
        documentation_link = entry.get("documentation_link", references[0] if references else "")
        return ModelRegistryEntry(
            model_id=model_id,
            version=entry.get("version", "0.1"),
            owner=entry.get("owner", entry.get("module_path", "unassigned")),
            status=status_value,
            validation_date=validation_date,
            limitations=entry.get("limitations", limitations),
            documentation_link=documentation_link,
            workflow_layer=entry.get("workflow_layer", "Production"),
            analytics_lab_only=entry.get("analytics_lab_only", False),
            name=entry.get("name", model_id),
            domain=entry.get("domain", "Unknown"),
            production_allowed=entry.get(
                "production_allowed", status in _PRODUCTION_ALLOWED
            ),
            quant_review_status=entry.get(
                "quant_review_status",
                self.quant_review_status(model_id),
            ),
            tests=list(entry.get("tests", [])),
            references=references,
            last_validated=validation_date,
        )

    def quant_review_status(self, model_id: str) -> str:
        """Return quant-review synchronization status for one model."""
        status = _QUANT_REVIEW_STATUS.get(model_id, "Open")
        return status if status in QUANT_REVIEW_STATUSES else "Open"

    def is_production_allowed(self, model_id: str) -> bool:
        return self.get_model(model_id).production_allowed

    def enforce_model(
        self,
        model_id: str,
        *,
        allow_analytics_lab: bool = False,
    ) -> ModelRegistryEntry:
        """Validate whether a model may be used for a service calculation."""
        model = self.get_model(model_id)
        if model.status == "Broken":
            raise ValueError(f"Model {model_id} is Broken and cannot be used.")
        if model.status == "Placeholder":
            raise ValueError(f"Model {model_id} is Placeholder and is blocked.")
        if model.is_research_only and not allow_analytics_lab:
            raise ValueError(
                f"Model {model_id} belongs to Analytics Lab and requires explicit allow_analytics_lab=True."
            )
        return model

    def warnings_for_model(self, model_id: str) -> list[str]:
        """Return service-level warnings implied by model governance status."""
        model = self.get_model(model_id)
        warnings = list(model.limitations)
        if model.is_prototype:
            warnings.append(f"Model {model_id} is Prototype and must not be used as production workflow.")
        if model.is_research_only:
            warnings.append(
                f"Model {model_id} belongs to Analytics Lab / Research and is not a production workflow model."
            )
        if not model.production_allowed:
            warnings.append(f"Model {model_id} is not production allowed: {model.status}.")
        elif model.status != "Validated":
            warnings.append(f"Model {model_id} status is {model.status}.")
        return warnings

    def metadata_for_model(self, model_id: str) -> dict:
        """Return serializable model metadata for pricing/risk results."""
        model = self.get_model(model_id)
        return {
            "model_id": model.model_id,
            "model_version": model.version,
            "model_owner": model.owner,
            "model_status": model.status,
            "model_validation_date": model.validation_date.isoformat() if model.validation_date else "",
            "model_limitations": list(model.limitations),
            "model_documentation_link": model.documentation_link,
            "model_production_allowed": model.production_allowed,
            "model_quant_review_status": model.quant_review_status,
            "model_workflow_layer": model.workflow_layer,
            "model_analytics_lab_only": model.analytics_lab_only,
        }

    def production_models(self) -> list[str]:
        """Return model ids allowed to appear in production workflows."""
        return [
            model_id
            for model_id in registry.PRODUCTION_MODELS
            if self.get_model(model_id).production_allowed and not self.get_model(model_id).is_research_only
        ]

    def research_models(self) -> list[str]:
        """Return model ids owned by Analytics Lab / Research."""
        return [
            model_id
            for model_id in registry.MODEL_REGISTRY
            if self.get_model(model_id).is_research_only
        ]

    def validation_status(self) -> list[dict]:
        """Return validation coverage rows for governance workspaces."""
        rows = []
        for model in self.list_models():
            rows.append(
                {
                    "model_id": model.model_id,
                    "status": model.status,
                    "validation_date": model.validation_date,
                    "tests": list(model.tests),
                    "evidence_count": len(model.tests) + len(model.references),
                    "production_allowed": model.production_allowed,
                    "quant_review_status": model.quant_review_status,
                    "workflow_layer": model.workflow_layer,
                }
            )
        return rows

    def limitations_report(self) -> list[dict]:
        """Return user-facing model limitations."""
        rows = []
        for model in self.list_models():
            limitations = list(model.limitations) or ["No limitations recorded."]
            for limitation in limitations:
                rows.append(
                    {
                        "model_id": model.model_id,
                        "status": model.status,
                        "production_allowed": model.production_allowed,
                        "quant_review_status": model.quant_review_status,
                        "limitation": limitation,
                    }
                )
        return rows

    def audit_trail(self) -> list[dict]:
        """Return calculation audit records.

        Durable persistence is not implemented yet. When an AuditService is
        provided, return in-memory calculation records; otherwise return an
        explicit placeholder instead of fabricating calculation history.
        """
        if self.audit and self.audit.records:
            return self.audit.audit_trail()
        return [
            {
                "timestamp": "",
                "event": "Audit persistence not implemented",
                "model_id": "",
                "version": "",
                "status": "Pending",
                "details": "PricingService and RiskService expose metadata, but durable audit storage is not available yet.",
            }
        ]
