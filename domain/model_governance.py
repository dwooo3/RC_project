"""Model governance domain objects."""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ModelRegistryEntry:
    """Normalized model registry entry used by governance services."""

    model_id: str
    status: str
    version: str = "0.1"
    owner: str = "unassigned"
    validation_date: date | None = None
    limitations: list[str] = field(default_factory=list)
    documentation_link: str = ""
    name: str = ""
    domain: str = "Unknown"
    production_allowed: bool = False
    tests: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    last_validated: date | None = None

    @property
    def model_status(self) -> str:
        return self.status

    @property
    def is_prototype(self) -> bool:
        return self.status == "Prototype"


ModelDefinition = ModelRegistryEntry
