"""Quant-component governance domain objects.

``ModelRegistryEntry`` is the legacy compatibility DTO used by existing
pricing/risk services.  QW1 introduces separate immutable model, solver and
engine-eligibility contracts so product readiness is no longer inferred from
one overloaded ``model_id``.
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, order=True)
class DefinitionRef:
    """Immutable reference to one exact definition version."""

    definition_id: str
    version: str = "1.0.0"


@dataclass(frozen=True)
class ModelDefinition:
    """Economic/stochastic dynamics, independent from its numerical solver.

    Deliberately has no ``production_allowed`` field.  Production approval is
    a property of an :class:`EngineEligibility` (product x model x solver).
    """

    ref: DefinitionRef
    name: str
    asset_class: str
    model_family: str
    specification_ref: str
    state_factors: tuple[str, ...]
    dynamics: str
    measure: str
    numeraire: str
    parameter_domain: str
    well_posedness_assumptions: tuple[str, ...]
    parameter_schema_ref: str
    parameter_resolution_policy: str
    calibration_policy: str
    q_level: str
    governance_status: str
    workflow_layer: str
    implementation_component_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    benchmark_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    implementation_owner: str = "unassigned"
    validation_owner: str = "unassigned"

    @property
    def definition_id(self) -> str:
        return self.ref.definition_id

    @property
    def version(self) -> str:
        return self.ref.version

    @property
    def is_research_only(self) -> bool:
        return self.workflow_layer == "Research"


@dataclass(frozen=True)
class SolverEvidenceRecord:
    """Evidence attached to a numerical algorithm, not to model dynamics."""

    evidence_id: str
    solver_ref: DefinitionRef
    status: str
    test_refs: tuple[str, ...]
    benchmark_refs: tuple[str, ...]
    convergence_evidence: str
    reproducibility_evidence: str
    confidence_interval_evidence: str
    greeks_validation_evidence: str
    performance_envelope: str
    validation_owner: str = "unassigned"
    validation_date: date | None = None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class SolverDefinition:
    """Numerical algorithm definition independent from the dynamics."""

    ref: DefinitionRef
    name: str
    method: str
    algorithm: str
    numerical_parameter_schema_ref: str
    supported_dimensions: tuple[str, ...]
    supported_features: tuple[str, ...]
    deterministic: bool
    random_source_policy: str
    seed_policy: str
    implementation_component_ids: tuple[str, ...]
    evidence_ref: str
    governance_status: str
    workflow_layer: str
    limitations: tuple[str, ...] = ()
    owner: str = "unassigned"

    @property
    def definition_id(self) -> str:
        return self.ref.definition_id

    @property
    def version(self) -> str:
        return self.ref.version

    @property
    def is_research_only(self) -> bool:
        return self.workflow_layer == "Research"


@dataclass(frozen=True)
class EngineEligibility:
    """Versioned product x model x solver publication and approval decision."""

    ref: DefinitionRef
    product_definition_id: str
    selector_id: str
    implementation_component_id: str
    model_ref: DefinitionRef
    solver_ref: DefinitionRef
    pricer_component_id: str | None
    parameterization_component_id: str | None
    calculation_type: str
    parameter_schema_ref: str
    required_market_dependencies: tuple[str, ...]
    supported_product_features: tuple[str, ...]
    unsupported_regions: tuple[str, ...]
    supported_measures: tuple[str, ...]
    publication_targets: tuple[str, ...]
    eligibility_status: str
    production_allowed: bool
    approval_basis: str
    approval_ref: str
    approval_expires_on: date | None
    fallback_policy: str
    evidence_refs: tuple[str, ...]
    owner: str
    workflow_layer: str
    runtime_variant: str = "default"

    @property
    def engine_id(self) -> str:
        return self.ref.definition_id

    @property
    def version(self) -> str:
        return self.ref.version

    @property
    def is_research_only(self) -> bool:
        return self.workflow_layer == "Research"


@dataclass(frozen=True)
class ComponentPublication:
    """Where one canonical component is published (or why it is hidden)."""

    component_id: str
    component_kind: str
    publication_targets: tuple[str, ...]
    publication_status: str
    reason: str
    owner: str
    engine_eligibility_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelRegistryEntry:
    """Normalized model registry entry used by governance services."""

    model_id: str
    status: str
    canonical_component_id: str = ""
    requested_component_id: str = ""
    deprecated_alias: bool = False
    component_kind: str = ""
    q_level: str = ""
    implementation_scope: str = ""
    version: str = "0.1"
    owner: str = "unassigned"
    validation_date: date | None = None
    limitations: list[str] = field(default_factory=list)
    documentation_link: str = ""
    workflow_layer: str = "Production"
    analytics_lab_only: bool = False
    name: str = ""
    domain: str = "Unknown"
    production_allowed: bool = False
    quant_review_status: str = "Open"
    tests: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    last_validated: date | None = None

    @property
    def model_status(self) -> str:
        return self.status

    @property
    def is_prototype(self) -> bool:
        return self.status == "Prototype"

    @property
    def is_research_only(self) -> bool:
        return self.analytics_lab_only or self.workflow_layer == "Research"
