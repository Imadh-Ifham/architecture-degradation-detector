"""Evidence-based relationship resolution.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Correlates the configured endpoints, declared deployment dependencies and
    Kubernetes resource mappings recorded by manifest analysis with the
    components and artifacts established by component discovery.

    The resolver is deliberately conservative. It resolves a target only when
    the evidence identifies one component, keeps every unresolved and ambiguous
    reference, and never promotes a deployment declaration or an API contract
    to verified communication.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.components.architecture_recovery.component_discovery.models import (
    ComponentDiscoveryReport,
)
from app.components.architecture_recovery.dependency_resolution.index import (
    AliasMatch,
    ComponentIndex,
)
from app.components.architecture_recovery.dependency_resolution.models import (
    CONFIDENCE_SEMANTICS,
    LIMITATIONS,
    STATUS_SEMANTICS,
    DependencyCandidate,
    DependencyResolutionReport,
    DependencyResolutionSummary,
    EvidenceSource,
    InfrastructureKind,
    RelationshipType,
    ResolutionConfidence,
    ResolutionEvidence,
    ResolutionStatus,
    ResolvedRelationship,
    TargetClass,
    candidate_id,
    relationship_id,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    Diagnostic,
    DiagnosticSeverity,
    Endpoint,
    ManifestAnalysisReport,
    RelationshipOrigin,
    ResourceKind,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    RelationshipType as ManifestRelationshipType,
)
from app.components.architecture_recovery.repository_inventory.models import (
    RepositoryRef,
)

# Matches the configuration key inside the analyzers' evidence detail, for
# example "environment variable 'CART_SERVICE_ADDR' names the endpoint ...".
_ENVIRONMENT_KEY = re.compile(r"environment variable '([^']+)'")


#: How each target resolution was made, recorded in the report options.
RESOLUTION_METHODS: dict[str, str] = {
    "compose_service_alias": "configured host exactly matches a Compose service name",
    "kubernetes_workload_alias": "configured host exactly matches a Kubernetes workload name",
    "kubernetes_service_alias": "configured host exactly matches a Kubernetes Service name",
    "kubernetes_dns_name": "configured host matches a qualified Kubernetes DNS name",
    "kubernetes_dns_suffix": "configured host ends with .svc.cluster.local",
    "inventory_deployment_alias": (
        "configured host matches a deployment name the inventory recorded"
    ),
    "component_name": "configured host matches a component display name",
    "component_name_key": "configured host matches a normalised component name key",
    "normalized_alias": "configured host matches after case and separator normalisation",
    "host_port_disambiguation": "several host candidates matched and exactly one declares the port",
    "resource_ownership": "a manifest resource belongs to a component through component discovery",
    "container_image_family": "container image name identifies an infrastructure family",
    "declared_dependency": "a Compose depends_on or links declaration",
    "kubernetes_service_selector": "a Kubernetes Service selector matches a workload",
}


@dataclass
class _RelationshipDraft:
    """A relationship being accumulated from several evidence entries."""

    type: RelationshipType
    source_component_id: str
    target_component_id: str
    source_component_name: str | None
    target_component_name: str | None
    confidence: ResolutionConfidence
    target_class: TargetClass
    target_infrastructure_kind: InfrastructureKind | None
    resolution_method: str | None
    evidence: list[ResolutionEvidence] = field(default_factory=list)
    protocols: set[str] = field(default_factory=set)
    endpoints: set[str] = field(default_factory=set)
    ports: set[int] = field(default_factory=set)


@dataclass
class _CandidateDraft:
    """An unresolved or ambiguous candidate being accumulated."""

    type: RelationshipType
    source_component_id: str
    source_component_name: str | None
    status: ResolutionStatus
    target_reference: str | None
    host: str | None
    port: int | None
    protocol: str | None
    reason: str
    confidence: ResolutionConfidence
    candidate_component_ids: set[str] = field(default_factory=set)
    candidate_component_names: set[str] = field(default_factory=set)
    evidence: list[ResolutionEvidence] = field(default_factory=list)


class DependencyResolver:
    """Resolves architectural relationships from the upstream artifacts."""

    def resolve(
        self,
        component_discovery: ComponentDiscoveryReport,
        analysis: ManifestAnalysisReport,
    ) -> DependencyResolutionReport:
        """Resolve relationships from the typed upstream reports."""

        index = ComponentIndex.from_report(component_discovery, analysis)

        return self._resolve(index, analysis, component_discovery.repository)

    def resolve_documents(
        self,
        component_document: dict,
        analysis: ManifestAnalysisReport,
    ) -> DependencyResolutionReport:
        """Resolve relationships from a component-discovery JSON document."""

        index = ComponentIndex.from_document(component_document, analysis)
        repository = _repository_from_document(component_document) or analysis.repository

        return self._resolve(index, analysis, repository)

    # ------------------------------------------------------------------ #
    # Orchestration
    # ------------------------------------------------------------------ #

    def _resolve(
        self,
        index: ComponentIndex,
        analysis: ManifestAnalysisReport,
        repository: RepositoryRef,
    ) -> DependencyResolutionReport:
        """Resolve every supported evidence category, then assemble the report."""

        self._index = index
        self._relationships: dict[tuple, _RelationshipDraft] = {}
        self._candidates: dict[tuple, _CandidateDraft] = {}
        self._diagnostics: list[Diagnostic] = []
        self._diagnostic_keys: set[tuple] = set()
        self._duplicate_evidence_count = 0

        self._collect_index_diagnostics()
        self._resolve_configured_endpoints(analysis)
        self._resolve_declared_dependencies(analysis)
        self._resolve_resource_selections(analysis)

        if not analysis.endpoints and not analysis.relationships:
            self._add_diagnostic(
                DiagnosticSeverity.INFO,
                "manifest analysis contains no configured endpoints or deployment "
                "relationships to resolve",
            )

        return self._report(repository)

    # ------------------------------------------------------------------ #
    # Configured endpoints
    # ------------------------------------------------------------------ #

    def _resolve_configured_endpoints(self, analysis: ManifestAnalysisReport) -> None:
        """Resolve endpoints recorded from configuration values.

        Only endpoints with scope 'environment' are outbound references. The
        other scopes describe a component's own exposure and must never become
        a dependency on the component itself.
        """

        resources = {resource.id: resource for resource in analysis.resources}

        for endpoint in sorted(analysis.endpoints, key=_endpoint_sort_key):
            if endpoint.scope != "environment":
                continue

            source_resource = resources.get(endpoint.source_resource_id or "")

            if (
                source_resource is not None
                and source_resource.kind is ResourceKind.BUILD_STAGE
            ):
                # A Dockerfile ENV value configures a build, not a runtime call.
                self._add_diagnostic(
                    DiagnosticSeverity.INFO,
                    "a Dockerfile build-stage endpoint is build-time configuration "
                    "and was not treated as a runtime dependency",
                    endpoint.location.path,
                    endpoint.location.line,
                )
                continue

            if not endpoint.host:
                self._add_diagnostic(
                    DiagnosticSeverity.INFO,
                    "a configured endpoint records no host and cannot be resolved",
                    endpoint.location.path,
                    endpoint.location.line,
                )
                continue

            source_id = self._index.component_for_resource(endpoint.source_resource_id)

            if source_id is None:
                self._add_diagnostic(
                    DiagnosticSeverity.WARNING,
                    "a configured endpoint belongs to a resource that is not "
                    "associated with a discovered component; it was skipped",
                    endpoint.location.path,
                    endpoint.location.line,
                )
                continue

            matches, lookup_method = self._index.lookup(endpoint.host, endpoint.port)

            if lookup_method == "local_host":
                self._add_diagnostic(
                    DiagnosticSeverity.INFO,
                    f"configured endpoint '{_format_endpoint(endpoint)}' is a local "
                    "address and does not identify a component",
                    endpoint.location.path,
                    endpoint.location.line,
                )
                continue

            evidence = _endpoint_evidence(
                endpoint, _artifact_id(self._index, endpoint.source_resource_id)
            )

            if not matches:
                self._add_candidate(
                    relationship_type=RelationshipType.CONFIGURED_ENDPOINT,
                    source_component_id=source_id,
                    status=ResolutionStatus.UNRESOLVED,
                    target_reference=_format_endpoint(endpoint),
                    host=endpoint.host,
                    port=endpoint.port,
                    protocol=endpoint.protocol,
                    reason="host does not match any discovered component",
                    evidence=evidence,
                )
                self._add_diagnostic(
                    DiagnosticSeverity.INFO,
                    f"configured endpoint '{_format_endpoint(endpoint)}' does not "
                    "match any discovered component",
                    endpoint.location.path,
                    endpoint.location.line,
                )
                continue

            if len(matches) > 1:
                self._add_candidate(
                    relationship_type=RelationshipType.CONFIGURED_ENDPOINT,
                    source_component_id=source_id,
                    status=ResolutionStatus.AMBIGUOUS,
                    target_reference=_format_endpoint(endpoint),
                    host=endpoint.host,
                    port=endpoint.port,
                    protocol=endpoint.protocol,
                    reason="host matches more than one discovered component",
                    evidence=evidence,
                    matches=matches,
                )
                self._add_diagnostic(
                    DiagnosticSeverity.WARNING,
                    f"configured endpoint '{_format_endpoint(endpoint)}' is "
                    "ambiguous; candidates: "
                    + ", ".join(sorted(match.component_name for match in matches)),
                    endpoint.location.path,
                    endpoint.location.line,
                )
                continue

            match = matches[0]

            if match.component_id == source_id:
                self._add_diagnostic(
                    DiagnosticSeverity.INFO,
                    f"configured endpoint '{_format_endpoint(endpoint)}' points at "
                    "its own component and was not recorded as a dependency",
                    endpoint.location.path,
                    endpoint.location.line,
                )
                continue

            confidence = (
                ResolutionConfidence.DECLARED
                if match.declared
                and lookup_method not in ("normalized_alias", "host_port_disambiguation")
                else ResolutionConfidence.INFERRED
            )

            infrastructure = self._index.infrastructure(match.component_id)
            relationship_type = (
                RelationshipType.INFRASTRUCTURE_DEPENDENCY
                if infrastructure is not None
                else RelationshipType.CONFIGURED_ENDPOINT
            )

            draft = self._relationship(
                relationship_type=relationship_type,
                source_component_id=source_id,
                target_component_id=match.component_id,
                confidence=confidence,
                target_class=(
                    infrastructure.target_class
                    if infrastructure is not None
                    else TargetClass.COMPONENT
                ),
                target_infrastructure_kind=(
                    infrastructure.kind if infrastructure is not None else None
                ),
                resolution_method=_resolution_method(match, lookup_method),
            )

            self._add_evidence(draft.evidence, evidence)
            self._add_evidence(draft.evidence, [match.to_evidence()])

            # The endpoint resolved to this target, so what it declares about
            # the transport travels with the relationship. Kept as sets: two
            # endpoints naming one pair are two facts, not a conflict to
            # resolve by taking whichever was read first.
            if endpoint.protocol:
                draft.protocols.add(endpoint.protocol.lower())
            if endpoint.port:
                draft.ports.add(endpoint.port)
            draft.endpoints.add(_format_endpoint(endpoint))

            if infrastructure is not None:
                self._add_evidence(draft.evidence, list(infrastructure.evidence))

            self._add_evidence(
                draft.evidence, _contract_evidence(self._index, match.component_id)
            )

    # ------------------------------------------------------------------ #
    # Declared dependencies
    # ------------------------------------------------------------------ #

    def _resolve_declared_dependencies(self, analysis: ManifestAnalysisReport) -> None:
        """Resolve Compose depends_on and links declarations.

        These remain `declared_dependency` relationships. They are startup and
        orchestration declarations, not evidence that the application calls the
        target.
        """

        references = {reference.id: reference for reference in analysis.references}
        resources = {resource.id: resource for resource in analysis.resources}

        for relationship in sorted(analysis.relationships, key=lambda item: item.id):
            if (
                relationship.type is not ManifestRelationshipType.DEPENDS_ON
                or relationship.origin is not RelationshipOrigin.DECLARED_DEPENDENCY
            ):
                continue

            source_id = self._index.component_for_resource(relationship.source_id)

            if source_id is None:
                self._add_diagnostic(
                    DiagnosticSeverity.WARNING,
                    "a declared dependency belongs to a resource that is not "
                    "associated with a discovered component; it was skipped",
                    relationship.location.path,
                    relationship.location.line,
                )
                continue

            target_id = self._index.component_for_resource(relationship.target_id)

            if target_id is None:
                reference = references.get(relationship.target_id)
                target_name = (
                    reference.name
                    if reference is not None
                    else resources.get(relationship.target_id).name
                    if relationship.target_id in resources
                    else relationship.target_id
                )

                self._add_candidate(
                    relationship_type=RelationshipType.DECLARED_DEPENDENCY,
                    source_component_id=source_id,
                    status=ResolutionStatus.UNRESOLVED,
                    target_reference=target_name,
                    reason="declared dependency target is not a known component",
                    evidence=_manifest_relationship_evidence(
                        relationship,
                        _artifact_id(self._index, relationship.source_id),
                    ),
                )
                self._add_diagnostic(
                    DiagnosticSeverity.INFO,
                    f"declared dependency target '{target_name}' is not a known component",
                    relationship.location.path,
                    relationship.location.line,
                )
                continue

            if target_id == source_id:
                self._add_diagnostic(
                    DiagnosticSeverity.INFO,
                    "a declared dependency points at its own component and was not "
                    "recorded as a dependency",
                    relationship.location.path,
                    relationship.location.line,
                )
                continue

            infrastructure = self._index.infrastructure(target_id)

            draft = self._relationship(
                relationship_type=RelationshipType.DECLARED_DEPENDENCY,
                source_component_id=source_id,
                target_component_id=target_id,
                confidence=ResolutionConfidence.DECLARED,
                target_class=(
                    infrastructure.target_class
                    if infrastructure is not None
                    else TargetClass.COMPONENT
                ),
                target_infrastructure_kind=(
                    infrastructure.kind if infrastructure is not None else None
                ),
                resolution_method="declared_dependency",
            )

            self._add_evidence(
                draft.evidence,
                _manifest_relationship_evidence(
                    relationship,
                    _artifact_id(self._index, relationship.source_id),
                ),
            )
            self._add_evidence(
                draft.evidence,
                [
                    _resource_ownership_evidence(
                        self._index, relationship.target_id, target_id
                    )
                ],
            )

            if infrastructure is not None:
                self._add_evidence(draft.evidence, list(infrastructure.evidence))

            self._add_evidence(draft.evidence, _contract_evidence(self._index, target_id))

    # ------------------------------------------------------------------ #
    # Kubernetes resource selection
    # ------------------------------------------------------------------ #

    def _resolve_resource_selections(self, analysis: ManifestAnalysisReport) -> None:
        """Record cross-component Kubernetes Service selection explicitly.

        A selector that targets the workload of the same component is ordinary
        deployment wiring and produces no edge. When selection crosses
        components it is kept as `resource_selection`, which says what it is and
        does not claim application communication.
        """

        for relationship in sorted(analysis.relationships, key=lambda item: item.id):
            if relationship.type is not ManifestRelationshipType.SELECTS_WORKLOAD:
                continue

            source_id = self._index.component_for_resource(relationship.source_id)
            target_id = self._index.component_for_resource(relationship.target_id)

            if source_id is None or target_id is None:
                self._add_diagnostic(
                    DiagnosticSeverity.INFO,
                    "a Kubernetes Service selector could not be mapped to components",
                    relationship.location.path,
                    relationship.location.line,
                )
                continue

            if source_id == target_id:
                # The Service exposes its own workload; this is not a component
                # dependency and must not become a self-edge.
                continue

            infrastructure = self._index.infrastructure(target_id)

            draft = self._relationship(
                relationship_type=RelationshipType.RESOURCE_SELECTION,
                source_component_id=source_id,
                target_component_id=target_id,
                confidence=ResolutionConfidence.DECLARED,
                target_class=(
                    infrastructure.target_class
                    if infrastructure is not None
                    else TargetClass.COMPONENT
                ),
                target_infrastructure_kind=(
                    infrastructure.kind if infrastructure is not None else None
                ),
                resolution_method="kubernetes_service_selector",
            )

            self._add_evidence(
                draft.evidence,
                _manifest_relationship_evidence(
                    relationship,
                    _artifact_id(self._index, relationship.source_id),
                ),
            )
            self._add_evidence(
                draft.evidence,
                [
                    _resource_ownership_evidence(
                        self._index, relationship.target_id, target_id
                    )
                ],
            )

    # ------------------------------------------------------------------ #
    # Accumulation
    # ------------------------------------------------------------------ #

    def _relationship(
        self,
        *,
        relationship_type: RelationshipType,
        source_component_id: str,
        target_component_id: str,
        confidence: ResolutionConfidence,
        target_class: TargetClass,
        target_infrastructure_kind: InfrastructureKind | None,
        resolution_method: str | None,
    ) -> _RelationshipDraft:
        """Return the draft for a relationship, creating it on first evidence."""

        key = (relationship_type, source_component_id, target_component_id)
        draft = self._relationships.get(key)

        if draft is None:
            draft = _RelationshipDraft(
                type=relationship_type,
                source_component_id=source_component_id,
                target_component_id=target_component_id,
                source_component_name=self._index.component_name(source_component_id),
                target_component_name=self._index.component_name(target_component_id),
                confidence=confidence,
                target_class=target_class,
                target_infrastructure_kind=target_infrastructure_kind,
                resolution_method=resolution_method,
            )
            self._relationships[key] = draft
        else:
            # The strongest available mapping supports the whole relationship.
            if confidence is ResolutionConfidence.DECLARED:
                draft.confidence = ResolutionConfidence.DECLARED
                draft.resolution_method = resolution_method or draft.resolution_method

        return draft

    def _add_candidate(
        self,
        *,
        relationship_type: RelationshipType,
        source_component_id: str,
        status: ResolutionStatus,
        target_reference: str,
        reason: str,
        evidence: list[ResolutionEvidence],
        host: str | None = None,
        port: int | None = None,
        protocol: str | None = None,
        matches: list[AliasMatch] | None = None,
    ) -> None:
        """Record an unresolved or ambiguous reference, aggregating evidence."""

        key = (relationship_type, source_component_id, status, target_reference)
        draft = self._candidates.get(key)

        if draft is None:
            draft = _CandidateDraft(
                type=relationship_type,
                source_component_id=source_component_id,
                source_component_name=self._index.component_name(source_component_id),
                status=status,
                target_reference=target_reference,
                host=host,
                port=port,
                protocol=protocol,
                reason=reason,
                confidence=ResolutionConfidence.DECLARED,
            )
            self._candidates[key] = draft

        if matches:
            for match in matches:
                draft.candidate_component_ids.add(match.component_id)
                draft.candidate_component_names.add(match.component_name)

        self._add_evidence(draft.evidence, evidence)

    def _add_evidence(
        self, target: list[ResolutionEvidence], evidence: list[ResolutionEvidence]
    ) -> None:
        """Append evidence, counting exact duplicates instead of storing them."""

        seen = {item.sort_key() for item in target}

        for item in evidence:
            key = item.sort_key()

            if key in seen:
                self._duplicate_evidence_count += 1
                continue

            seen.add(key)
            target.append(item)

    # ------------------------------------------------------------------ #
    # Diagnostics and report
    # ------------------------------------------------------------------ #

    def _collect_index_diagnostics(self) -> None:
        """Surface ambiguity discovered while building the component index."""

        for message in self._index.diagnostics:
            self._add_diagnostic(DiagnosticSeverity.WARNING, message)

    def _add_diagnostic(
        self,
        severity: DiagnosticSeverity,
        message: str,
        path: str | None = None,
        line: int | None = None,
    ) -> None:
        """Record one diagnostic, deduplicated by its content."""

        key = (severity.value, message, path or "", line or 0)

        if key in self._diagnostic_keys:
            return

        self._diagnostic_keys.add(key)
        self._diagnostics.append(
            Diagnostic(
                severity=severity,
                message=message,
                path=path or "",
                line=line,
                analyzer="dependency_resolution",
            )
        )

    def _report(self, repository: RepositoryRef) -> DependencyResolutionReport:
        """Assemble the final report and compute its summary from real output."""

        relationships = [
            ResolvedRelationship(
                id=relationship_id(
                    draft.type, draft.source_component_id, draft.target_component_id
                ),
                type=draft.type,
                source_component_id=draft.source_component_id,
                source_component_name=draft.source_component_name,
                target_component_id=draft.target_component_id,
                target_component_name=draft.target_component_name,
                confidence=draft.confidence,
                target_class=draft.target_class,
                target_infrastructure_kind=draft.target_infrastructure_kind,
                resolution_method=draft.resolution_method,
                protocols=sorted(draft.protocols),
                endpoints=sorted(draft.endpoints),
                ports=sorted(draft.ports),
                evidence=sorted(draft.evidence, key=lambda item: item.sort_key()),
            )
            for draft in self._relationships.values()
        ]
        relationships.sort(
            key=lambda item: (
                item.type.value,
                item.source_component_name or item.source_component_id,
                item.target_component_name or item.target_component_id,
                item.id,
            )
        )

        candidates = [
            DependencyCandidate(
                id=candidate_id(
                    draft.type, draft.source_component_id, draft.target_reference or ""
                ),
                type=draft.type,
                source_component_id=draft.source_component_id,
                source_component_name=draft.source_component_name,
                status=draft.status,
                target_reference=draft.target_reference,
                host=draft.host,
                port=draft.port,
                protocol=draft.protocol,
                candidate_component_ids=sorted(draft.candidate_component_ids),
                candidate_component_names=sorted(draft.candidate_component_names),
                reason=draft.reason,
                confidence=draft.confidence,
                evidence=sorted(draft.evidence, key=lambda item: item.sort_key()),
            )
            for draft in self._candidates.values()
        ]
        candidates.sort(
            key=lambda item: (
                item.status.value,
                item.type.value,
                item.source_component_name or item.source_component_id,
                item.target_reference or "",
                item.id,
            )
        )

        unresolved = [
            item for item in candidates if item.status is ResolutionStatus.UNRESOLVED
        ]
        ambiguous = [
            item for item in candidates if item.status is ResolutionStatus.AMBIGUOUS
        ]

        diagnostics = sorted(
            self._diagnostics,
            key=lambda item: (
                item.path,
                item.line or 0,
                item.severity.value,
                item.message,
            ),
        )

        summary = _summarise(
            relationships=relationships,
            unresolved=unresolved,
            ambiguous=ambiguous,
            diagnostics=diagnostics,
            duplicate_evidence_count=self._duplicate_evidence_count,
        )

        return DependencyResolutionReport(
            generated_at=datetime.now(UTC),
            repository=repository,
            options={
                "confidence_semantics": CONFIDENCE_SEMANTICS,
                "status_semantics": STATUS_SEMANTICS,
                "resolution_methods": RESOLUTION_METHODS,
                "deduplication": (
                    "relationships are keyed by (source component, target component, "
                    "relationship type); equivalent evidence is aggregated and exact "
                    "duplicates are counted"
                ),
                "future_evidence_sources": [EvidenceSource.SOURCE_CODE.value],
                "limitations": list(LIMITATIONS),
            },
            summary=summary,
            relationships=relationships,
            unresolved=unresolved,
            ambiguous=ambiguous,
            diagnostics=diagnostics,
            warnings=[
                diagnostic.message
                for diagnostic in diagnostics
                if diagnostic.severity
                in (DiagnosticSeverity.WARNING, DiagnosticSeverity.ERROR)
            ],
        )


# --------------------------------------------------------------------------- #
# Evidence helpers
# --------------------------------------------------------------------------- #


def _endpoint_sort_key(endpoint: Endpoint) -> tuple:
    """Return a deterministic ordering key for an endpoint."""

    return (
        endpoint.source_resource_id or "",
        endpoint.host or "",
        endpoint.port or 0,
        endpoint.scope or "",
        endpoint.id,
    )


def _endpoint_evidence(
    endpoint: Endpoint, artifact_id: str | None
) -> list[ResolutionEvidence]:
    """Return provenance for a configured endpoint without its raw value."""

    reference = _format_endpoint(endpoint)
    key = _endpoint_key(endpoint)
    evidence: list[ResolutionEvidence] = []

    for item in endpoint.evidence:
        evidence.append(
            ResolutionEvidence(
                source=EvidenceSource.MANIFEST_ANALYSIS,
                type=item.type,
                detail=item.detail,
                declared=True,
                path=item.location.path,
                line=item.location.line,
                artifact_id=artifact_id,
                resource_id=endpoint.source_resource_id,
                key=key,
                endpoint=reference,
            )
        )

    if not evidence:
        evidence.append(
            ResolutionEvidence(
                source=EvidenceSource.MANIFEST_ANALYSIS,
                type="configured_endpoint",
                detail=f"configured endpoint '{reference}'",
                declared=True,
                path=endpoint.location.path,
                line=endpoint.location.line,
                artifact_id=artifact_id,
                resource_id=endpoint.source_resource_id,
                key=key,
                endpoint=reference,
            )
        )

    return evidence


def _endpoint_key(endpoint: Endpoint) -> str | None:
    """Extract the configuration key from an endpoint's evidence detail."""

    for item in endpoint.evidence:
        match = _ENVIRONMENT_KEY.search(item.detail)

        if match:
            return match.group(1)

    return None


def _format_endpoint(endpoint: Endpoint) -> str:
    """Format an endpoint identity for evidence and candidate references."""

    if endpoint.host and endpoint.port:
        if endpoint.protocol:
            return f"{endpoint.protocol}://{endpoint.host}:{endpoint.port}"

        return f"{endpoint.host}:{endpoint.port}"

    if endpoint.host:
        return endpoint.host

    if endpoint.port:
        return str(endpoint.port)

    return "<unnamed endpoint>"


def _manifest_relationship_evidence(
    relationship, artifact_id: str | None
) -> list[ResolutionEvidence]:
    """Return the manifest declaration's provenance."""

    evidence: list[ResolutionEvidence] = []

    for item in relationship.evidence:
        evidence.append(
            ResolutionEvidence(
                source=EvidenceSource.MANIFEST_ANALYSIS,
                type=item.type,
                detail=item.detail,
                declared=True,
                path=item.location.path,
                line=item.location.line,
                artifact_id=artifact_id,
                resource_id=relationship.source_id,
                resolution_method=relationship.type.value,
            )
        )

    if not evidence:
        evidence.append(
            ResolutionEvidence(
                source=EvidenceSource.MANIFEST_ANALYSIS,
                type=relationship.type.value,
                detail=f"manifest declares a {relationship.type.value} relationship",
                declared=True,
                path=relationship.location.path,
                line=relationship.location.line,
                artifact_id=artifact_id,
                resource_id=relationship.source_id,
                resolution_method=relationship.type.value,
            )
        )

    return evidence


def _artifact_id(index: ComponentIndex, resource_id: str | None) -> str | None:
    """Return the component artifact that declared a resource, if any."""

    artifact = index.artifact_for_resource(resource_id)

    return artifact.id if artifact else None


def _resource_ownership_evidence(
    index: ComponentIndex, resource_id: str, component_id: str
) -> ResolutionEvidence:
    """Return evidence that a manifest resource belongs to a component."""

    component_name = index.component_name(component_id) or component_id
    artifact = index.artifact_for_resource(resource_id)

    return ResolutionEvidence(
        source=EvidenceSource.COMPONENT_DISCOVERY,
        type="resource_ownership",
        detail=(
            f"analysis resource belongs to component '{component_name}' through "
            "component discovery"
        ),
        declared=True,
        path=artifact.path if artifact else None,
        line=artifact.line if artifact else None,
        artifact_id=artifact.id if artifact else None,
        resource_id=resource_id,
        resolution_method="resource_ownership",
    )


def _contract_evidence(
    index: ComponentIndex, component_id: str
) -> list[ResolutionEvidence]:
    """Return supporting contract evidence, which never creates an edge alone."""

    component_name = index.component_name(component_id) or component_id

    return [
        ResolutionEvidence(
            source=EvidenceSource.COMPONENT_DISCOVERY,
            type="contract_reference",
            detail=(
                f"component '{component_name}' declares a supporting API contract; "
                "a contract describes an interface and does not prove a call"
            ),
            declared=True,
            path=artifact.path,
            line=artifact.line,
            artifact_id=artifact.id,
            resource_id=artifact.resource_id,
            resolution_method="contract_artifact",
        )
        for artifact in index.contracts(component_id)
    ]


def _resolution_method(match: AliasMatch, lookup_method: str) -> str:
    """Return the most specific method that produced a resolved match."""

    if lookup_method == "host_port_disambiguation":
        return "host_port_disambiguation"

    if lookup_method == "normalized_alias":
        return "normalized_alias"

    return match.method


def _repository_from_document(document: dict) -> RepositoryRef | None:
    """Build a repository reference from a component-discovery document."""

    repository = document.get("repository")

    if not isinstance(repository, dict):
        return None

    return RepositoryRef(
        id=repository.get("id"),
        url=repository.get("url"),
        branch=repository.get("branch"),
        commit=repository.get("commit"),
    )


def _summarise(
    *,
    relationships: list[ResolvedRelationship],
    unresolved: list[DependencyCandidate],
    ambiguous: list[DependencyCandidate],
    diagnostics: list[Diagnostic],
    duplicate_evidence_count: int,
) -> DependencyResolutionSummary:
    """Compute summary counts from the report's actual contents."""

    by_type: dict[str, int] = {}
    by_target_class: dict[str, int] = {}
    by_evidence_source: dict[str, int] = {}
    sources: set[str] = set()
    targets: set[str] = set()
    evidence_count = 0

    for relationship in relationships:
        by_type[relationship.type.value] = by_type.get(relationship.type.value, 0) + 1
        by_target_class[relationship.target_class.value] = (
            by_target_class.get(relationship.target_class.value, 0) + 1
        )
        sources.add(relationship.source_component_id)
        targets.add(relationship.target_component_id)
        evidence_count += len(relationship.evidence)

        for item in relationship.evidence:
            by_evidence_source[item.source.value] = (
                by_evidence_source.get(item.source.value, 0) + 1
            )

    for candidate in [*unresolved, *ambiguous]:
        sources.add(candidate.source_component_id)
        evidence_count += len(candidate.evidence)

        for item in candidate.evidence:
            by_evidence_source[item.source.value] = (
                by_evidence_source.get(item.source.value, 0) + 1
            )

    return DependencyResolutionSummary(
        resolved_relationship_count=len(relationships),
        unresolved_count=len(unresolved),
        ambiguous_count=len(ambiguous),
        evidence_count=evidence_count,
        duplicate_evidence_count=duplicate_evidence_count,
        diagnostic_count=len(diagnostics),
        unique_source_component_count=len(sources),
        unique_target_component_count=len(targets),
        by_type=dict(sorted(by_type.items())),
        by_evidence_source=dict(sorted(by_evidence_source.items())),
        by_target_class=dict(sorted(by_target_class.items())),
    )


__all__ = [
    "RESOLUTION_METHODS",
    "DependencyResolver",
]
