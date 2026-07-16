"""Service facade over component, model, solver and engine registries."""

from dataclasses import replace
from datetime import date

from domain.model_governance import (
    ComponentPublication,
    EngineEligibility,
    ModelDefinition,
    ModelRegistryEntry,
    SolverDefinition,
    SolverEvidenceRecord,
)
from models import registry
from models.engine_eligibility import (
    build_engine_eligibility,
    effective_production_allowed,
    eligibility_consistency_errors,
    eligibility_policy_issues,
)
from models.quant_definitions import (
    COMPONENT_PUBLICATIONS,
    MODEL_DEFINITIONS,
    SOLVER_DEFINITIONS,
    SOLVER_EVIDENCE,
    assert_definitions_consistent,
    coverage_summary as definition_coverage_summary,
)
from services.audit_service import AuditService


_PRODUCTION_ALLOWED = {
    registry.ModelStatus.VALIDATED,
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
    "structured_basket_note": "Open",
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
        registry.assert_registry_consistent()
        assert_definitions_consistent()
        eligibility_errors = eligibility_consistency_errors(
            self._workstation_binding_rows()
        )
        if eligibility_errors:
            raise RuntimeError(
                "Engine eligibility is inconsistent: "
                + "; ".join(eligibility_errors)
            )
        self.audit = audit

    @staticmethod
    def _workstation_binding_rows() -> list[tuple[str, str, str, dict]]:
        """Return the authoritative workstation product/selector projection."""
        from api.pricing_workstation import PRODUCTS

        rows = []
        for product in PRODUCTS:
            for engine in product.engines:
                defaults = {
                    spec.key: spec.default
                    for spec in product.params_for(engine, [], [])
                }
                rows.append((product.id, engine.id, engine.model_id, defaults))
        return rows

    @staticmethod
    def _market_dependencies(product) -> tuple[str, ...]:
        dependencies = []
        if product.needs_curve:
            dependencies.append("discount_curve")
        if product.needs_proj:
            dependencies.append("projection_curve")
        if product.vol_surfaces:
            dependencies.append("volatility_surface_or_manual_vol")
        if product.underlying:
            dependencies.append("underlying_market_facts")
        return tuple(dependencies)

    def list_models(self) -> list[ModelRegistryEntry]:
        """Legacy: return all 124 implementation components.

        New clients should use :meth:`list_model_definitions` for dynamics and
        the solver/publication APIs for other component roles.
        """
        return [self.get_model(model_id) for model_id in sorted(registry.MODEL_REGISTRY)]

    def list_model_definitions(self) -> list[ModelDefinition]:
        return [MODEL_DEFINITIONS[key] for key in sorted(MODEL_DEFINITIONS)]

    def get_model_definition(self, definition_id: str) -> ModelDefinition:
        try:
            return MODEL_DEFINITIONS[definition_id]
        except KeyError as exc:
            raise KeyError(f"unknown model definition {definition_id!r}") from exc

    def list_solver_definitions(self) -> list[SolverDefinition]:
        return [SOLVER_DEFINITIONS[key] for key in sorted(SOLVER_DEFINITIONS)]

    def get_solver_definition(self, definition_id: str) -> SolverDefinition:
        try:
            return SOLVER_DEFINITIONS[definition_id]
        except KeyError as exc:
            raise KeyError(f"unknown solver definition {definition_id!r}") from exc

    def list_solver_evidence(self) -> list[SolverEvidenceRecord]:
        return [SOLVER_EVIDENCE[key] for key in sorted(SOLVER_EVIDENCE)]

    def get_engine_eligibility(
        self,
        product_id: str,
        selector_id: str | None = None,
        params: dict | None = None,
    ) -> EngineEligibility:
        from api.pricing_workstation import find_product

        product = find_product(product_id)
        if product is None:
            raise KeyError(f"unknown product {product_id!r}")
        selector_id = selector_id or product.engines[0].id
        engine = next((item for item in product.engines if item.id == selector_id), None)
        if engine is None:
            raise KeyError(
                f"unknown engine {selector_id!r} for product {product_id!r}"
            )
        return build_engine_eligibility(
            product_id=product.id,
            selector_id=engine.id,
            implementation_component_id=engine.model_id,
            params=params,
            required_market_dependencies=self._market_dependencies(product),
            supported_product_features=(product.group, product.note) if product.note else (product.group,),
        )

    def list_engine_eligibilities(self) -> list[EngineEligibility]:
        """Return every workstation binding, including both Carr-Madan variants."""
        from api.pricing_workstation import PRODUCTS

        rows = []
        for product in PRODUCTS:
            for engine in product.engines:
                defaults = {
                    spec.key: spec.default
                    for spec in product.params_for(engine, [], [])
                }
                variants = [defaults]
                if engine.model_id == "carr_madan":
                    variants = [
                        {**defaults, "cf_model": "bsm"},
                        {**defaults, "cf_model": "heston"},
                    ]
                for params in variants:
                    rows.append(self.get_engine_eligibility(
                        product.id, engine.id, params
                    ))
        return rows

    def enforce_engine(
        self,
        product_id: str,
        selector_id: str | None,
        params: dict | None = None,
        *,
        allow_analytics_lab: bool = False,
        allow_non_production: bool = False,
    ) -> EngineEligibility:
        eligibility = self.get_engine_eligibility(product_id, selector_id, params)
        issues = eligibility_policy_issues(
            eligibility,
            allow_analytics_lab=allow_analytics_lab,
            allow_non_production=allow_non_production,
        )
        if issues:
            raise ValueError("; ".join(f"{code}: {message}" for code, message in issues))
        return eligibility

    def list_component_publications(self) -> list[ComponentPublication]:
        """Return all 124 routes enriched with workstation eligibility refs."""
        refs_by_component: dict[str, list[str]] = {}
        for eligibility in self.list_engine_eligibilities():
            refs_by_component.setdefault(
                eligibility.implementation_component_id, []
            ).append(eligibility.engine_id)
        return [
            replace(
                COMPONENT_PUBLICATIONS[component_id],
                engine_eligibility_refs=tuple(sorted(
                    refs_by_component.get(component_id, [])
                )),
                publication_targets=tuple(dict.fromkeys((
                    *COMPONENT_PUBLICATIONS[component_id].publication_targets,
                    *(("pricing_workstation",)
                      if refs_by_component.get(component_id) else ()),
                ))),
                publication_status=(
                    "published"
                    if (COMPONENT_PUBLICATIONS[component_id].publication_status
                        == "routed"
                        and refs_by_component.get(component_id))
                    else COMPONENT_PUBLICATIONS[component_id].publication_status
                ),
                reason=(
                    "Integrated in pricing_workstation."
                    if (COMPONENT_PUBLICATIONS[component_id].publication_status
                        == "routed"
                        and refs_by_component.get(component_id))
                    else COMPONENT_PUBLICATIONS[component_id].reason
                ),
            )
            for component_id in sorted(COMPONENT_PUBLICATIONS)
        ]

    def quant_coverage_summary(self, *, as_of: date | None = None) -> dict:
        summary = dict(definition_coverage_summary())
        eligibilities = self.list_engine_eligibilities()
        publications = self.list_component_publications()
        selector_pairs = {
            (item.product_definition_id, item.selector_id)
            for item in eligibilities
        }
        summary.update({
            "publication_counts": dict(sorted({
                status: sum(
                    item.publication_status == status for item in publications
                )
                for status in {item.publication_status for item in publications}
            }.items())),
            "workstation_selector_count": len(selector_pairs),
            "engine_eligibility_count": len(eligibilities),
            "production_engine_count": sum(
                effective_production_allowed(item, as_of=as_of)
                for item in eligibilities
            ),
            "declared_production_engine_count": sum(
                item.production_allowed for item in eligibilities
            ),
            "legacy_transition_engine_count": sum(
                effective_production_allowed(item, as_of=as_of)
                and item.approval_basis == "legacy_transition"
                for item in eligibilities
            ),
            "expired_transition_engine_count": sum(
                item.production_allowed
                and item.approval_basis == "legacy_transition"
                and not effective_production_allowed(item, as_of=as_of)
                for item in eligibilities
            ),
            "independently_approved_engine_count": sum(
                effective_production_allowed(item, as_of=as_of)
                and item.approval_basis == "independent_validation"
                for item in eligibilities
            ),
            "research_engine_count": sum(
                item.is_research_only for item in eligibilities
            ),
        })
        return summary

    def quant_coverage(self) -> dict:
        return {
            "summary": self.quant_coverage_summary(),
            "model_definitions": self.list_model_definitions(),
            "solver_definitions": self.list_solver_definitions(),
            "solver_evidence": self.list_solver_evidence(),
            "engine_eligibilities": self.list_engine_eligibilities(),
            "component_publications": self.list_component_publications(),
        }

    def status_counts(self) -> dict[str, int]:
        """Return model counts by governance status."""
        counts = {status.value: 0 for status in registry.ModelStatus}
        for model in self.list_models():
            counts[model.status] = counts.get(model.status, 0) + 1
        return counts

    def get_model(self, model_id: str,
                  calculation_type: str | None = None) -> ModelRegistryEntry:
        entry = registry.get(model_id, calculation_type)
        status = entry["status"]
        status_value = status.value if hasattr(status, "value") else str(status)
        notes = entry.get("notes", "")
        limitations = [notes] if notes else []
        validation_date = entry.get("validation_date", entry.get("last_validated"))
        references = list(entry.get("references", []))
        documentation_link = entry.get("documentation_link", references[0] if references else "")
        return ModelRegistryEntry(
            model_id=entry["canonical_component_id"],
            canonical_component_id=entry["canonical_component_id"],
            requested_component_id=entry["requested_component_id"],
            deprecated_alias=entry["deprecated_alias"],
            component_kind=entry.get("component_kind") or "",
            q_level=entry.get("q_level", ""),
            implementation_scope=entry.get("implementation_scope", ""),
            version=entry.get("version", "0.1"),
            owner=entry.get("owner", entry.get("module_path", "unassigned")),
            status=status_value,
            validation_date=validation_date,
            limitations=entry.get("limitations", limitations),
            documentation_link=documentation_link,
            workflow_layer=entry.get("workflow_layer", "Production"),
            analytics_lab_only=entry.get("analytics_lab_only", False),
            name=entry.get("name", entry["canonical_component_id"]),
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
        status = _QUANT_REVIEW_STATUS.get(registry.canonical_model_id(model_id), "Open")
        return status if status in QUANT_REVIEW_STATUSES else "Open"

    def is_production_allowed(self, model_id: str) -> bool:
        return self.get_model(model_id).production_allowed

    def enforce_model(
        self,
        model_id: str,
        *,
        allow_analytics_lab: bool = False,
        allow_non_production: bool = False,
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
        # Approximation is the production-policy regression addressed by P0:
        # it must be an explicit analytical opt-in. Existing Prototype
        # workflows remain callable with governed warnings (unless separately
        # blocked as Analytics Lab), preserving the research workstation.
        if (model.status == registry.ModelStatus.APPROXIMATION.value
                and not model.production_allowed
                and not allow_non_production):
            raise ValueError(
                f"Model {model_id} is not production allowed: {model.status}."
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

    def metadata_for_model(self, model_id: str,
                           calculation_type: str | None = None) -> dict:
        """Return serializable model metadata for pricing/risk results."""
        model = self.get_model(model_id, calculation_type)
        return {
            "model_id": model.model_id,
            "canonical_component_id": model.canonical_component_id,
            "requested_component_id": model.requested_component_id,
            "deprecated_alias": model.deprecated_alias,
            "component_kind": model.component_kind,
            "q_level": model.q_level,
            "implementation_scope": model.implementation_scope,
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
            for model_id in registry.MODEL_REGISTRY
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

    def audit_trail(self, limit: int = 200) -> list[dict]:
        """Return calculation audit records.

        A2 (validation report): durable-first — when the AuditService carries
        an AppDB sink, the trail is read back from ``audit_records`` and thus
        survives restarts. In-memory records are the fallback for services
        constructed without persistence; the explicit placeholder remains for
        a bare GovernanceService so history is never fabricated.
        """
        db = getattr(self.audit, "db", None) if self.audit else None
        if db is not None:
            try:
                rows = db.load_audit_records(limit=limit)
            except Exception:
                rows = []
            if rows:
                normalized = []
                for r in rows:
                    details = r.get("details", {}) or {}
                    requested_model_id = details.get(
                        "requested_model_id", r.get("model_id", ""))
                    calculation_type = r.get("calculation_type", "")
                    canonical_model_id = registry.canonical_model_id(
                        requested_model_id, calculation_type)
                    normalized.append({
                        "timestamp": r.get("ts", ""),
                        "event": r.get("user_action", ""),
                        "model_id": canonical_model_id,
                        "requested_model_id": requested_model_id,
                        "deprecated_alias": requested_model_id != canonical_model_id,
                        "version": r.get("model_version", ""),
                        "status": "Recorded",
                        "calculation_type": calculation_type,
                        "snapshot_id": r.get("market_data_snapshot_id", ""),
                        "inputs_hash": r.get("inputs_hash", ""),
                        "details": details,
                    })
                return normalized
        if self.audit and self.audit.records:
            normalized = []
            for record in self.audit.audit_trail():
                details = record.get("details", {}) or {}
                requested_model_id = details.get(
                    "requested_model_id", record.get("model_id", ""))
                calculation_type = record.get("calculation_type", "")
                canonical_model_id = registry.canonical_model_id(
                    requested_model_id, calculation_type)
                normalized.append({
                    **record,
                    "model_id": canonical_model_id,
                    "requested_model_id": requested_model_id,
                    "deprecated_alias": requested_model_id != canonical_model_id,
                })
            return normalized
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
