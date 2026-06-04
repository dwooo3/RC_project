"""Service facade over the model registry."""

from domain.model_governance import ModelRegistryEntry
from models import registry


_PRODUCTION_ALLOWED = {
    registry.ModelStatus.VALIDATED,
    registry.ModelStatus.APPROXIMATION,
}


class GovernanceService:
    """Normalize model registry entries for application services."""

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
            tests=list(entry.get("tests", [])),
            references=references,
            last_validated=validation_date,
        )

    def is_production_allowed(self, model_id: str) -> bool:
        return self.get_model(model_id).production_allowed

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
