"""Service facade over the model registry."""

from domain.model_governance import ModelDefinition
from models import registry


_PRODUCTION_ALLOWED = {
    registry.ModelStatus.VALIDATED,
    registry.ModelStatus.APPROXIMATION,
}


class GovernanceService:
    """Normalize model registry entries for application services."""

    def get_model(self, model_id: str) -> ModelDefinition:
        entry = registry.get(model_id)
        status = entry["status"]
        notes = entry.get("notes", "")
        limitations = [notes] if notes else []
        return ModelDefinition(
            model_id=model_id,
            name=entry.get("name", model_id),
            domain=entry.get("domain", "Unknown"),
            status=status.value if hasattr(status, "value") else str(status),
            version=entry.get("version", "0.1"),
            owner=entry.get("owner", entry.get("module_path", "unassigned")),
            production_allowed=entry.get(
                "production_allowed", status in _PRODUCTION_ALLOWED
            ),
            limitations=entry.get("limitations", limitations),
            tests=list(entry.get("tests", [])),
            references=list(entry.get("references", [])),
            last_validated=entry.get("last_validated"),
        )

    def is_production_allowed(self, model_id: str) -> bool:
        return self.get_model(model_id).production_allowed
