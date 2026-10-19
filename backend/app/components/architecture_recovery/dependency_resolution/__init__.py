"""Dependency resolution subcomponent.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Correlates the configured endpoints, deployment declarations and resource
    mappings recorded by manifest analysis with the components established by
    component discovery, and records the relationships that the evidence
    supports.

    The stage keeps configured endpoints, declared startup dependencies,
    infrastructure connections and Kubernetes resource selections distinct, and
    never promotes a declaration to verified communication. Its evidence model
    is deliberately open to a later SCIP or AST source so source-code findings
    can be added without rewriting the resolver.
"""

from app.components.architecture_recovery.dependency_resolution.errors import (
    DependencyResolutionError,
    DependencyResolutionInputError,
    DependencyResolutionWriteError,
)
from app.components.architecture_recovery.dependency_resolution.index import (
    AliasMatch,
    ArtifactInput,
    ComponentIndex,
    ComponentInput,
    InfrastructureMatch,
)
from app.components.architecture_recovery.dependency_resolution.models import (
    CONFIDENCE_SEMANTICS,
    GENERATOR_NAME,
    GENERATOR_VERSION,
    LIMITATIONS,
    SCHEMA_VERSION,
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
from app.components.architecture_recovery.dependency_resolution.resolver import (
    RESOLUTION_METHODS,
    DependencyResolver,
)
from app.components.architecture_recovery.dependency_resolution.schemas import (
    DependencyResolutionSummaryResponse,
)
from app.components.architecture_recovery.dependency_resolution.service import (
    DependencyResolutionService,
    dependency_resolution_service_from_settings,
)
from app.components.architecture_recovery.dependency_resolution.writer import (
    DEPENDENCY_RESOLUTION_FILE_NAME,
    load_dependency_resolution,
    write_dependency_resolution,
)

__all__ = [
    "CONFIDENCE_SEMANTICS",
    "DEPENDENCY_RESOLUTION_FILE_NAME",
    "GENERATOR_NAME",
    "GENERATOR_VERSION",
    "LIMITATIONS",
    "RESOLUTION_METHODS",
    "SCHEMA_VERSION",
    "STATUS_SEMANTICS",
    "AliasMatch",
    "ArtifactInput",
    "ComponentIndex",
    "ComponentInput",
    "DependencyCandidate",
    "DependencyResolutionError",
    "DependencyResolutionInputError",
    "DependencyResolutionReport",
    "DependencyResolutionService",
    "DependencyResolutionSummary",
    "DependencyResolutionSummaryResponse",
    "DependencyResolutionWriteError",
    "DependencyResolver",
    "EvidenceSource",
    "InfrastructureKind",
    "InfrastructureMatch",
    "RelationshipType",
    "ResolutionConfidence",
    "ResolutionEvidence",
    "ResolutionStatus",
    "ResolvedRelationship",
    "TargetClass",
    "candidate_id",
    "dependency_resolution_service_from_settings",
    "load_dependency_resolution",
    "relationship_id",
    "write_dependency_resolution",
]
