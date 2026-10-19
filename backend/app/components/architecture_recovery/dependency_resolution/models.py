"""Dependency resolution data model.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Defines the versioned JSON contract written by dependency resolution.

    Vocabulary:
      * evidence    - one fact from an upstream stage that suggests a target.
      * relationship - a resolved, defensible link between two components.
      * candidate   - an unresolved or ambiguous reference. It is retained so a
                      later source-code analyzer can resolve it rather than
                      silently losing the observation.

    Confidence is categorical, never numeric. `declared` means an explicit
    configuration value or deployment declaration identifies the target through
    a direct alias. `inferred` means the target was reached through a naming
    convention or port disambiguation. A declaration is not runtime traffic:
    no relationship in this document claims verified communication.

    Evidence deliberately records only endpoint identities (host, port, key)
    and provenance. Configuration values, manifest bodies and credentials are
    never copied into this document.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha1

# Reused deliberately: the project keeps one notion of a diagnostic and one
# notion of a repository reference, so downstream consumers can read every
# analysis artifact the same way.
from app.components.architecture_recovery.manifest_analysis.models import (
    Diagnostic,
)
from app.components.architecture_recovery.repository_inventory.models import (
    RepositoryRef,
)

SCHEMA_VERSION = "1.0.0"
GENERATOR_NAME = "dependency_resolution"
GENERATOR_VERSION = "0.1.0"


class RelationshipType(StrEnum):
    """Why a relationship was recorded.

    The types are kept separate because a configured endpoint, a declared
    startup dependency, an infrastructure connection and a deployment wiring
    fact are different observations even when they share two endpoints.
    """

    CONFIGURED_ENDPOINT = "configured_endpoint"
    DECLARED_DEPENDENCY = "declared_dependency"
    INFRASTRUCTURE_DEPENDENCY = "infrastructure_dependency"
    RESOURCE_SELECTION = "resource_selection"


class ResolutionStatus(StrEnum):
    """Whether a target could be resolved uniquely."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class ResolutionConfidence(StrEnum):
    """Strength of a target mapping, or of a candidate's source evidence.

    For a resolved relationship this describes the target mapping: `declared`
    comes from an exact deployment alias or qualified Kubernetes name, while
    `inferred` comes from a normalised name match or port disambiguation. For an
    unresolved or ambiguous candidate it describes the source evidence itself,
    because no target mapping exists yet.
    """

    DECLARED = "declared"
    INFERRED = "inferred"


class EvidenceSource(StrEnum):
    """The analysis stage that supplied a fact."""

    MANIFEST_ANALYSIS = "manifest_analysis"
    COMPONENT_DISCOVERY = "component_discovery"
    # Reserved for a later SCIP/AST stage. Nothing currently emits it.
    SOURCE_CODE = "source_code"


class TargetClass(StrEnum):
    """Whether a target is an application component or infrastructure."""

    COMPONENT = "component"
    INFRASTRUCTURE = "infrastructure"


class InfrastructureKind(StrEnum):
    """The infrastructure role inferred from manifest evidence."""

    DATABASE = "database"
    CACHE = "cache"
    MESSAGE_BROKER = "message_broker"
    INFRASTRUCTURE = "infrastructure"


#: Explanation of the confidence categories, recorded in the output so a
#: consumer does not have to infer the semantics from the source.
CONFIDENCE_SEMANTICS: dict[str, str] = {
    ResolutionConfidence.DECLARED.value: (
        "an explicit configuration value or declaration identifies the target "
        "through an exact deployment alias or qualified Kubernetes service name"
    ),
    ResolutionConfidence.INFERRED.value: (
        "the target was reached through a normalised name match, a component "
        "display name, or port-based disambiguation"
    ),
}

#: Explanation of the status categories.
STATUS_SEMANTICS: dict[str, str] = {
    ResolutionStatus.RESOLVED.value: (
        "exactly one known component matched the reference"
    ),
    ResolutionStatus.AMBIGUOUS.value: (
        "more than one known component matched; no target is asserted"
    ),
    ResolutionStatus.UNRESOLVED.value: (
        "no known component matched; the reference is preserved for a later stage"
    ),
}

#: What this stage cannot do yet. Kept in the artifact so a consumer does not
#: read an incomplete graph as a complete one.
LIMITATIONS: tuple[str, ...] = (
    "Source-code call evidence (SCIP, AST or similar) is not available; only "
    "declared configuration and deployment evidence is resolved.",
    "API contracts and protobuf declarations identify interfaces, not callers, "
    "and are never promoted to relationships on their own.",
    "A Compose depends_on entry and a Kubernetes Service selector describe "
    "deployment wiring, not verified application communication.",
    "Infrastructure targets are classified from container image names recorded "
    "by manifest analysis; an image that is not recognised stays a component.",
    "Only configured endpoints recorded with scope 'environment' are treated as "
    "outbound references. Published ports and OpenAPI server URLs describe "
    "exposure, not a dependency.",
    "Kubernetes ConfigMap, Secret and volume references stay configuration of "
    "their own component and are not promoted to component dependencies.",
    "Environment values are read only when they are literal. Values supplied "
    "through envFrom or a ConfigMap are not extracted by manifest analysis yet.",
)


@dataclass(frozen=True)
class ResolutionEvidence:
    """Provenance for one fact supporting a relationship or candidate."""

    source: EvidenceSource
    type: str
    detail: str
    declared: bool
    path: str | None = None
    line: int | None = None
    artifact_id: str | None = None
    resource_id: str | None = None
    key: str | None = None
    endpoint: str | None = None
    resolution_method: str | None = None

    def sort_key(self) -> tuple:
        """Return a deterministic ordering and deduplication key."""

        return (
            self.source.value,
            self.type,
            self.path or "",
            self.line or 0,
            self.key or "",
            self.endpoint or "",
            self.detail,
            self.artifact_id or "",
            self.resource_id or "",
            self.resolution_method or "",
            self.declared,
        )

    def to_dict(self) -> dict:
        """Serialise the evidence, keeping fields that do not apply as null."""

        return {
            "source": self.source.value,
            "type": self.type,
            "detail": self.detail,
            "declared": self.declared,
            "path": self.path,
            "line": self.line,
            "artifact_id": self.artifact_id,
            "resource_id": self.resource_id,
            "key": self.key,
            "endpoint": self.endpoint,
            "resolution_method": self.resolution_method,
        }


@dataclass
class ResolvedRelationship:
    """A defensible link between two known components."""

    id: str
    type: RelationshipType
    source_component_id: str
    target_component_id: str
    source_component_name: str | None = None
    target_component_name: str | None = None
    status: ResolutionStatus = ResolutionStatus.RESOLVED
    confidence: ResolutionConfidence = ResolutionConfidence.DECLARED
    target_class: TargetClass = TargetClass.COMPONENT
    target_infrastructure_kind: InfrastructureKind | None = None
    resolution_method: str | None = None
    evidence: list[ResolutionEvidence] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the relationship with its aggregated evidence."""

        return {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "confidence": self.confidence.value,
            "source_component_id": self.source_component_id,
            "source_component_name": self.source_component_name,
            "target_component_id": self.target_component_id,
            "target_component_name": self.target_component_name,
            "target_class": self.target_class.value,
            "target_infrastructure_kind": (
                self.target_infrastructure_kind.value
                if self.target_infrastructure_kind
                else None
            ),
            "resolution_method": self.resolution_method,
            "evidence": [
                item.to_dict() for item in sorted(self.evidence, key=lambda x: x.sort_key())
            ],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass
class DependencyCandidate:
    """A reference whose target could not be resolved uniquely."""

    id: str
    type: RelationshipType
    source_component_id: str
    status: ResolutionStatus
    source_component_name: str | None = None
    target_reference: str | None = None
    host: str | None = None
    port: int | None = None
    protocol: str | None = None
    candidate_component_ids: list[str] = field(default_factory=list)
    candidate_component_names: list[str] = field(default_factory=list)
    reason: str = ""
    confidence: ResolutionConfidence = ResolutionConfidence.DECLARED
    evidence: list[ResolutionEvidence] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the candidate with its preserved evidence."""

        return {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "confidence": self.confidence.value,
            "source_component_id": self.source_component_id,
            "source_component_name": self.source_component_name,
            "target_reference": self.target_reference,
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "candidate_component_ids": self.candidate_component_ids,
            "candidate_component_names": self.candidate_component_names,
            "reason": self.reason,
            "evidence": [
                item.to_dict() for item in sorted(self.evidence, key=lambda x: x.sort_key())
            ],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass
class DependencyResolutionSummary:
    """Aggregate counts computed from a completed report."""

    resolved_relationship_count: int = 0
    unresolved_count: int = 0
    ambiguous_count: int = 0
    evidence_count: int = 0
    duplicate_evidence_count: int = 0
    diagnostic_count: int = 0
    unique_source_component_count: int = 0
    unique_target_component_count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_evidence_source: dict[str, int] = field(default_factory=dict)
    by_target_class: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise the summary in a stable key order."""

        return {
            "resolved_relationship_count": self.resolved_relationship_count,
            "unresolved_count": self.unresolved_count,
            "ambiguous_count": self.ambiguous_count,
            "evidence_count": self.evidence_count,
            "duplicate_evidence_count": self.duplicate_evidence_count,
            "diagnostic_count": self.diagnostic_count,
            "unique_source_component_count": self.unique_source_component_count,
            "unique_target_component_count": self.unique_target_component_count,
            "by_type": self.by_type,
            "by_evidence_source": self.by_evidence_source,
            "by_target_class": self.by_target_class,
        }


@dataclass
class DependencyResolutionReport:
    """The complete report written to `dependency_resolution.json`."""

    generated_at: datetime
    repository: RepositoryRef
    options: dict
    summary: DependencyResolutionSummary
    relationships: list[ResolvedRelationship] = field(default_factory=list)
    unresolved: list[DependencyCandidate] = field(default_factory=list)
    ambiguous: list[DependencyCandidate] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the whole report as the on-disk JSON structure."""

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at.isoformat(),
            "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
            "repository": self.repository.to_dict(),
            "options": self.options,
            "summary": self.summary.to_dict(),
            "relationships": [item.to_dict() for item in self.relationships],
            "unresolved": [item.to_dict() for item in self.unresolved],
            "ambiguous": [item.to_dict() for item in self.ambiguous],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------- #
# Identifier helpers
# --------------------------------------------------------------------------- #
#
# Ids derive from the relationship's semantics and endpoints, never from an
# iteration index, so repeated analyses of the same inputs produce the same ids.


def _digest(*parts: str) -> str:
    """Return a short deterministic digest of the given parts."""

    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def relationship_id(
    relationship_type: RelationshipType, source_component_id: str, target_component_id: str
) -> str:
    """Derive a relationship id from its type and endpoints."""

    return (
        "dependency:"
        f"{_digest(relationship_type.value, source_component_id, target_component_id)}"
    )


def candidate_id(
    relationship_type: RelationshipType, source_component_id: str, target_reference: str
) -> str:
    """Derive a candidate id from its type, source and original reference."""

    return f"candidate:{_digest(relationship_type.value, source_component_id, target_reference)}"


__all__ = [
    "CONFIDENCE_SEMANTICS",
    "GENERATOR_NAME",
    "GENERATOR_VERSION",
    "LIMITATIONS",
    "SCHEMA_VERSION",
    "STATUS_SEMANTICS",
    "DependencyCandidate",
    "DependencyResolutionReport",
    "DependencyResolutionSummary",
    "EvidenceSource",
    "InfrastructureKind",
    "RelationshipType",
    "ResolutionConfidence",
    "ResolutionEvidence",
    "ResolutionStatus",
    "ResolvedRelationship",
    "TargetClass",
    "candidate_id",
    "relationship_id",
]
