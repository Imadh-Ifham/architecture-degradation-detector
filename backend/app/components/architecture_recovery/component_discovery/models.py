"""Component discovery data model.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Defines the JSON contract written by component discovery.

    Vocabulary:
      * artifact  - a single repository artifact that *describes or implements*
                    a component: a deployment declaration, a build definition, a
                    Dockerfile, an API contract. Artifacts are not components.
      * component - a logical architectural unit (a service, application or
                    module) that one or more artifacts belong to.
      * association - the link from a component to one of its artifacts, tagged
                    with the role the artifact plays and how the link was
                    established.

    The distinction between an artifact and a component is the point of this
    stage: a Compose service, its Dockerfile, its source project and its API
    contract are four artifacts of one component, not four components.

    Confidence semantics (deliberately categorical, not numeric):

      * `direct`    - explicit evidence links the artifact to the component: a
                      declared build context, a path containment relationship, a
                      shared image reference, or a name match corroborated by
                      location. Machine-checkable from the inputs.
      * `heuristic` - the evidence suggests the association but does not prove
                      it: name equality with no location link, or only weak path
                      structure. Reported so a consumer can discount it.

    These map onto the inventory's `confirmed`/`inferred` distinction, but are
    named for what they mean here: the strength of an *association*, not the
    existence of a resource.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha1

# Reused deliberately: manifest analysis already defines the diagnostic types,
# and the inventory defines a repository reference, so the documents stay
# linkable and the project keeps one notion of each concept.
from app.components.architecture_recovery.manifest_analysis.models import (
    Diagnostic,
)
from app.components.architecture_recovery.repository_inventory.models import (
    RepositoryRef,
)


SCHEMA_VERSION = "1.0.0"
GENERATOR_NAME = "component_discovery"
GENERATOR_VERSION = "0.1.0"

#: The identity policy this implementation applies, recorded in the output so a
#: consumer can see how ids were derived without reading the source.
IDENTITY_POLICY = (
    "A component id is a hash of its normalised name and canonical root path, so "
    "it is stable across runs and independent of iteration order. Artifacts are "
    "merged into one component only when a named rule applies; the component's "
    "confidence is the weakest rule that merged it."
)


class ComponentType(StrEnum):
    """What kind of architectural unit a component is."""

    SERVICE = "service"
    APPLICATION = "application"
    LIBRARY = "library"
    UNKNOWN = "unknown"


class ArtifactRole(StrEnum):
    """The part an artifact plays for its component."""

    DEPLOYMENT = "deployment"
    DEFINITION = "definition"
    BUILD = "build"
    IMPLEMENTATION = "implementation"
    CONTRACT = "contract"


class AssociationType(StrEnum):
    """How a component relates to one of its artifacts.

    Kept distinct because a deployment declaration, a build recipe, an
    implementation directory and an API contract do not mean the same thing.
    """

    DEPLOYED_AS = "deployed_as"
    DEFINED_BY = "defined_by"
    BUILT_FROM = "built_from"
    IMPLEMENTED_BY = "implemented_by"
    CONTRACT_DEFINED_BY = "contract_defined_by"


#: Role to association type, so the two cannot drift apart.
ASSOCIATION_BY_ROLE: dict[ArtifactRole, AssociationType] = {
    ArtifactRole.DEPLOYMENT: AssociationType.DEPLOYED_AS,
    ArtifactRole.DEFINITION: AssociationType.DEFINED_BY,
    ArtifactRole.BUILD: AssociationType.BUILT_FROM,
    ArtifactRole.IMPLEMENTATION: AssociationType.IMPLEMENTED_BY,
    ArtifactRole.CONTRACT: AssociationType.CONTRACT_DEFINED_BY,
}


class AssociationConfidence(StrEnum):
    """Whether an association is machine-checkable or a heuristic inference."""

    DIRECT = "direct"
    HEURISTIC = "heuristic"


#: Weakest first, so a merged component's confidence can be chosen as the
#: weakest link that holds it together.
_CONFIDENCE_ORDER: tuple[AssociationConfidence, ...] = (
    AssociationConfidence.HEURISTIC,
    AssociationConfidence.DIRECT,
)


def weakest_confidence(
    confidences: list[AssociationConfidence],
) -> AssociationConfidence:
    """Return the weakest of the given confidences.

    A component is only as trustworthy as the weakest evidence keeping it
    together, so a single heuristic link caps the whole component at heuristic.
    """

    if not confidences:
        return AssociationConfidence.HEURISTIC

    for confidence in _CONFIDENCE_ORDER:
        if confidence in confidences:
            return confidence

    return AssociationConfidence.HEURISTIC


class MergeRule(StrEnum):
    """The named rule that merged artifact identity into one component."""

    BUILD_CONTEXT_CONTAINMENT = "build_context_containment"
    PROJECT_LOCATION_CONTAINMENT = "project_location_containment"
    SHARED_IMAGE_REFERENCE = "shared_image_reference"
    NAME_AND_LOCATION_MATCH = "name_and_location_match"
    NAME_MATCH = "name_match"
    DIRECTORY_GROUP_ONLY = "directory_group_only"


#: Rules that count as direct, machine-checkable evidence.
DIRECT_RULES: frozenset[MergeRule] = frozenset(
    {
        MergeRule.BUILD_CONTEXT_CONTAINMENT,
        MergeRule.PROJECT_LOCATION_CONTAINMENT,
        MergeRule.SHARED_IMAGE_REFERENCE,
        MergeRule.NAME_AND_LOCATION_MATCH,
    }
)


def confidence_for_rule(rule: MergeRule) -> AssociationConfidence:
    """Return the confidence implied by a merge rule."""

    return (
        AssociationConfidence.DIRECT
        if rule in DIRECT_RULES
        else AssociationConfidence.HEURISTIC
    )


@dataclass(frozen=True)
class DiscoveryEvidence:
    """One fact explaining a discovery decision or an artifact association."""

    source: str
    type: str
    detail: str
    confidence: AssociationConfidence
    path: str | None = None
    line: int | None = None
    resource_id: str | None = None
    rule: MergeRule | None = None

    def to_dict(self) -> dict:
        """Serialise the evidence, keeping fields that do not apply as null."""

        return {
            "source": self.source,
            "type": self.type,
            "detail": self.detail,
            "confidence": self.confidence.value,
            "path": self.path,
            "line": self.line,
            "resource_id": self.resource_id,
            "rule": self.rule.value if self.rule else None,
        }


@dataclass
class ComponentArtifact:
    """A repository artifact associated with a component."""

    id: str
    role: ArtifactRole
    confidence: AssociationConfidence
    kind: str
    path: str
    name: str | None = None
    line: int | None = None
    resource_id: str | None = None
    inventory_component_id: str | None = None
    attributes: dict = field(default_factory=dict)
    evidence: list[DiscoveryEvidence] = field(default_factory=list)

    @property
    def association(self) -> AssociationType:
        """Return the association type implied by this artifact's role."""

        return ASSOCIATION_BY_ROLE[self.role]

    def to_dict(self) -> dict:
        """Serialise the artifact."""

        return {
            "id": self.id,
            "role": self.role.value,
            "association": self.association.value,
            "confidence": self.confidence.value,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "line": self.line,
            "resource_id": self.resource_id,
            "inventory_component_id": self.inventory_component_id,
            "attributes": self.attributes,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass
class Component:
    """A logical architectural component and the artifacts that belong to it."""

    id: str
    name: str
    type: ComponentType
    confidence: AssociationConfidence
    root_path: str | None = None
    languages: list[str] = field(default_factory=list)
    file_count: int = 0
    inventory_component_id: str | None = None
    artifact_ids: list[str] = field(default_factory=list)
    name_keys: list[str] = field(default_factory=list)
    evidence: list[DiscoveryEvidence] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def artifact_paths(self, artifacts: dict[str, ComponentArtifact]) -> list[str]:
        """Return the repository-relative paths of this component's artifacts."""

        return sorted(
            {
                artifacts[artifact_id].path
                for artifact_id in self.artifact_ids
                if artifact_id in artifacts
            }
        )

    def to_dict(self, artifacts: dict[str, ComponentArtifact]) -> dict:
        """Serialise the component, including its associated artifact paths."""

        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "confidence": self.confidence.value,
            "root_path": self.root_path,
            "languages": self.languages,
            "file_count": self.file_count,
            "inventory_component_id": self.inventory_component_id,
            "artifact_count": len(self.artifact_ids),
            "artifact_ids": self.artifact_ids,
            "paths": self.artifact_paths(artifacts),
            "name_keys": self.name_keys,
            "evidence": [item.to_dict() for item in self.evidence],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True)
class UnresolvedArtifact:
    """An artifact that could not be associated with any component."""

    id: str
    kind: str
    path: str
    reason: str
    name: str | None = None
    line: int | None = None
    resource_id: str | None = None
    evidence: list[DiscoveryEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the unresolved artifact."""

        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "line": self.line,
            "resource_id": self.resource_id,
            "reason": self.reason,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class AmbiguousAssociation:
    """An artifact with more than one plausible component."""

    id: str
    kind: str
    name: str
    path: str
    candidate_component_ids: list[str]
    reason: str
    line: int | None = None
    evidence: list[DiscoveryEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the ambiguity."""

        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "line": self.line,
            "candidate_component_ids": self.candidate_component_ids,
            "reason": self.reason,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass
class ComponentDiscoverySummary:
    """Aggregate counts describing a discovery run."""

    component_count: int = 0
    artifact_count: int = 0
    unresolved_count: int = 0
    ambiguous_count: int = 0
    duplicate_identity_count: int = 0
    direct_association_count: int = 0
    heuristic_association_count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_confidence: dict[str, int] = field(default_factory=dict)
    by_association: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise the summary in a stable key order."""

        return {
            "component_count": self.component_count,
            "artifact_count": self.artifact_count,
            "unresolved_count": self.unresolved_count,
            "ambiguous_count": self.ambiguous_count,
            "duplicate_identity_count": self.duplicate_identity_count,
            "direct_association_count": self.direct_association_count,
            "heuristic_association_count": self.heuristic_association_count,
            "by_type": self.by_type,
            "by_confidence": self.by_confidence,
            "by_association": self.by_association,
        }


@dataclass
class ComponentDiscoveryReport:
    """The complete report written to `component_discovery.json`."""

    generated_at: datetime
    repository: RepositoryRef
    options: dict
    summary: ComponentDiscoverySummary
    components: list[Component] = field(default_factory=list)
    artifacts: list[ComponentArtifact] = field(default_factory=list)
    unresolved: list[UnresolvedArtifact] = field(default_factory=list)
    ambiguous: list[AmbiguousAssociation] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def artifact_index(self) -> dict[str, ComponentArtifact]:
        """Return the artifacts keyed by id, for serialising components."""

        return {artifact.id: artifact for artifact in self.artifacts}

    def to_dict(self) -> dict:
        """Serialise the whole report as the on-disk JSON structure."""

        artifacts = self.artifact_index()

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at.isoformat(),
            "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
            "repository": self.repository.to_dict(),
            "options": self.options,
            "summary": self.summary.to_dict(),
            "components": [item.to_dict(artifacts) for item in self.components],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "unresolved": [item.to_dict() for item in self.unresolved],
            "ambiguous": [item.to_dict() for item in self.ambiguous],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------- #
# Identifier helpers
# --------------------------------------------------------------------------- #
#
# Ids derive from stable repository-relative identity, never from a sequence
# number or a random value, so two runs over the same inputs produce the same
# ids and the report stays comparable and mergeable downstream.


def _digest(*parts: str) -> str:
    """Return a short deterministic digest of the given parts."""

    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def component_id(name_key: str, root_path: str | None) -> str:
    """Derive a component id from its normalised name and canonical root."""

    return f"component:{_digest(name_key, root_path or '')}"


def artifact_id(kind: str, path: str, name: str | None = None) -> str:
    """Derive an artifact id from its kind, path and optional name."""

    return f"artifact:{_digest(kind, path, name or '')}"


def unresolved_id(kind: str, path: str, name: str | None = None) -> str:
    """Derive an id for an unresolved artifact."""

    return f"unresolved:{_digest(kind, path, name or '')}"


def ambiguous_id(kind: str, path: str, name: str) -> str:
    """Derive an id for an ambiguous association."""

    return f"ambiguous:{_digest(kind, path, name)}"


__all__ = [
    "AmbiguousAssociation",
    "ArtifactRole",
    "AssociationConfidence",
    "AssociationType",
    "ASSOCIATION_BY_ROLE",
    "Component",
    "ComponentArtifact",
    "ComponentDiscoveryReport",
    "ComponentDiscoverySummary",
    "ComponentType",
    "DIRECT_RULES",
    "DiscoveryEvidence",
    "Diagnostic",
    "GENERATOR_NAME",
    "GENERATOR_VERSION",
    "IDENTITY_POLICY",
    "MergeRule",
    "RepositoryRef",
    "SCHEMA_VERSION",
    "UnresolvedArtifact",
    "ambiguous_id",
    "artifact_id",
    "component_id",
    "confidence_for_rule",
    "unresolved_id",
    "weakest_confidence",
]
