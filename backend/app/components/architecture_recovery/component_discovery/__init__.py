"""Component discovery subcomponent.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Identifies the logical architectural components in an ingested repository
    and associates the artifacts that implement, define, build, deploy and
    contract each one.

    Pipeline: candidate collection (from the inventory and manifest analysis)
    -> identity resolution -> artifact association -> report. The stage consumes
    the upstream artifacts rather than repeating any of their work, and its
    output is meant to feed source-code analysis, dependency resolution and graph
    construction.
"""

from app.components.architecture_recovery.component_discovery.association import (
    AssemblyResult,
    ComponentAssembler,
)
from app.components.architecture_recovery.component_discovery.candidates import (
    Candidate,
    CandidateCollection,
    CandidateCollector,
)
from app.components.architecture_recovery.component_discovery.errors import (
    ComponentDiscoveryError,
    DiscoveryInputError,
    DiscoveryWriteError,
)
from app.components.architecture_recovery.component_discovery.identity import (
    IdentityGroup,
    IdentityResolver,
    MergeDecision,
    UnionFind,
)
from app.components.architecture_recovery.component_discovery.models import (
    ASSOCIATION_BY_ROLE,
    DIRECT_RULES,
    IDENTITY_POLICY,
    SCHEMA_VERSION,
    AmbiguousAssociation,
    ArtifactRole,
    AssociationConfidence,
    AssociationType,
    Component,
    ComponentArtifact,
    ComponentDiscoveryReport,
    ComponentDiscoverySummary,
    ComponentType,
    DiscoveryEvidence,
    MergeRule,
    UnresolvedArtifact,
    confidence_for_rule,
    weakest_confidence,
)
from app.components.architecture_recovery.component_discovery.schemas import (
    ComponentDiscoverySummaryResponse,
)
from app.components.architecture_recovery.component_discovery.service import (
    ComponentDiscoveryService,
    component_discovery_service_from_settings,
)
from app.components.architecture_recovery.component_discovery.writer import (
    COMPONENT_DISCOVERY_FILE_NAME,
    load_component_discovery,
    write_component_discovery,
)

__all__ = [
    "ASSOCIATION_BY_ROLE",
    "COMPONENT_DISCOVERY_FILE_NAME",
    "DIRECT_RULES",
    "IDENTITY_POLICY",
    "SCHEMA_VERSION",
    "AmbiguousAssociation",
    "ArtifactRole",
    "AssemblyResult",
    "AssociationConfidence",
    "AssociationType",
    "Candidate",
    "CandidateCollection",
    "CandidateCollector",
    "Component",
    "ComponentArtifact",
    "ComponentAssembler",
    "ComponentDiscoveryError",
    "ComponentDiscoveryReport",
    "ComponentDiscoveryService",
    "ComponentDiscoverySummary",
    "ComponentDiscoverySummaryResponse",
    "ComponentType",
    "DiscoveryEvidence",
    "DiscoveryInputError",
    "DiscoveryWriteError",
    "IdentityGroup",
    "IdentityResolver",
    "MergeDecision",
    "MergeRule",
    "UnionFind",
    "UnresolvedArtifact",
    "component_discovery_service_from_settings",
    "confidence_for_rule",
    "load_component_discovery",
    "weakest_confidence",
    "write_component_discovery",
]
