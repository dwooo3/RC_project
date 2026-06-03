"""Model governance domain objects."""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ModelDefinition:
    """Normalized model registry entry used by services."""

    model_id: str
    name: str
    domain: str
    status: str
    version: str = "0.1"
    owner: str = "unassigned"
    production_allowed: bool = False
    limitations: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    last_validated: date | None = None
