"""Manifest analysis data model.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    The common output model every analyzer produces, so consumers do not need
    to know which format a finding came from.

    Vocabulary:
      * resource     - something a manifest declares: a service, a workload, a
                       container, an image, a network, an RPC, a port.
      * relationship - a link between two resources, always tagged with the
                       reason it exists (see `RelationshipOrigin`).
      * endpoint     - a configured network location (a published port, a base
                       url, a service port).
      * reference    - a name a manifest points at, plus whether it could be
                       resolved inside the analysed file.

    A declaration is not a runtime fact. `RelationshipOrigin` keeps declared
    dependencies, configured endpoints, API definitions and build inputs
    distinct, and no analyzer may emit `VERIFIED_COMMUNICATION`: only a later
    stage that observes real traffic can claim that.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha1

# Reused deliberately: the inventory already defines what "confirmed" means
# (an artifact names the thing) versus "inferred" (structure suggests it).
from app.components.architecture_recovery.repository_inventory.models import (
    Confidence,
    RepositoryRef,
)


SCHEMA_VERSION = "1.0.0"
GENERATOR_NAME = "manifest_analysis"
GENERATOR_VERSION = "0.1.0"


class ParseStatus(StrEnum):
    """How far an analyzer got with a file."""

    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class DiagnosticSeverity(StrEnum):
    """Severity of a diagnostic recorded during analysis."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ExtractionMethod(StrEnum):
    """How a finding was obtained, so its provenance is auditable."""

    YAML = "yaml"
    JSON = "json"
    DOCKERFILE = "dockerfile"
    PROTOBUF = "protobuf"
    TEXT = "text"


class ResourceKind(StrEnum):
    """Kinds of resource an analyzer can declare."""

    SERVICE = "service"
    BUILD_STAGE = "build_stage"
    CONTAINER = "container"
    WORKLOAD = "workload"
    KUBERNETES_SERVICE = "kubernetes_service"
    CONFIG_MAP = "config_map"
    SECRET = "secret"
    NAMESPACE = "namespace"
    VOLUME = "volume"
    NETWORK = "network"
    IMAGE = "image"
    PORT = "port"
    API = "api"
    API_OPERATION = "api_operation"
    PROTO_PACKAGE = "proto_package"
    PROTO_SERVICE = "proto_service"
    PROTO_RPC = "proto_rpc"
    PROTO_MESSAGE = "proto_message"


class RelationshipOrigin(StrEnum):
    """Why a relationship was recorded.

    This is the distinction that keeps the model honest: a `depends_on` entry is
    a declared dependency, a published port is configured exposure, an OpenAPI
    path is an API definition, and none of them is proof of communication.
    """

    DECLARED_DEPENDENCY = "declared_dependency"
    DECLARED_BUILD_INPUT = "declared_build_input"
    CONFIGURED_ENDPOINT = "configured_endpoint"
    CONFIGURED_FILESYSTEM = "configured_filesystem"
    API_DEFINITION = "api_definition"
    # Reserved: only a stage that observes real traffic may claim this.
    VERIFIED_COMMUNICATION = "verified_communication"


class RelationshipType(StrEnum):
    """Kinds of relationship an analyzer can declare."""

    DEPENDS_ON = "depends_on"
    USES_IMAGE = "uses_image"
    BUILDS_FROM = "builds_from"
    BUILDS_SERVICE = "builds_service"
    PUBLISHES_PORT = "publishes_port"
    EXPOSES_PORT = "exposes_port"
    JOINS_NETWORK = "joins_network"
    MOUNTS_VOLUME = "mounts_volume"
    INCLUDES_FILE = "includes_file"
    REFERENCES_CONFIG = "references_config"
    REFERENCES_SECRET = "references_secret"
    REFERS_TO_SERVICE = "refers_to_service"
    SELECTS_WORKLOAD = "selects_workload"
    DEFINES_OPERATION = "defines_operation"
    SERVES_AT = "serves_at"
    DECLARES_PACKAGE = "declares_package"
    DEFINES_RPC = "defines_rpc"
    ACCEPTS_MESSAGE = "accepts_message"
    RETURNS_MESSAGE = "returns_message"


class ReferenceKind(StrEnum):
    """What a reference points at."""

    SERVICE = "service"
    IMAGE = "image"
    CONFIG_MAP = "config_map"
    SECRET = "secret"
    VOLUME = "volume"
    NETWORK = "network"
    FILE = "file"
    BUILD_STAGE = "build_stage"
    PROTO_MESSAGE = "proto_message"


class ReferenceStatus(StrEnum):
    """Whether a reference could be resolved within the analysed file."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class SourceLocation:
    """Where a finding came from, so a consumer can cite it."""

    path: str
    line: int | None = None

    def to_dict(self) -> dict:
        """Serialise the location."""

        return {"path": self.path, "line": self.line}


@dataclass(frozen=True)
class Diagnostic:
    """A parsing or extraction problem, or a noteworthy observation."""

    severity: DiagnosticSeverity
    message: str
    path: str
    line: int | None = None
    analyzer: str | None = None

    def to_dict(self) -> dict:
        """Serialise the diagnostic."""

        return {
            "severity": self.severity.value,
            "message": self.message,
            "path": self.path,
            "line": self.line,
            "analyzer": self.analyzer,
        }


@dataclass(frozen=True)
class ExtractedEvidence:
    """Provenance for a single extracted fact."""

    type: str
    detail: str
    method: ExtractionMethod
    location: SourceLocation

    def to_dict(self) -> dict:
        """Serialise the evidence."""

        return {
            "type": self.type,
            "detail": self.detail,
            "method": self.method.value,
            "path": self.location.path,
            "line": self.location.line,
        }


@dataclass
class DeclaredResource:
    """A resource declared by a manifest."""

    id: str
    kind: ResourceKind
    name: str
    location: SourceLocation
    analyzer: str
    method: ExtractionMethod
    namespace: str | None = None
    attributes: dict = field(default_factory=dict)
    evidence: list[ExtractedEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the resource with its attributes and evidence."""

        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "namespace": self.namespace,
            "path": self.location.path,
            "line": self.location.line,
            "analyzer": self.analyzer,
            "method": self.method.value,
            "attributes": self.attributes,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class DeclaredRelationship:
    """A relationship a manifest declares, never an asserted runtime call."""

    id: str
    type: RelationshipType
    origin: RelationshipOrigin
    source_id: str
    target_id: str
    location: SourceLocation
    resolved: bool
    confidence: Confidence = Confidence.CONFIRMED
    evidence: list[ExtractedEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the relationship."""

        return {
            "id": self.id,
            "type": self.type.value,
            "origin": self.origin.value,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "path": self.location.path,
            "line": self.location.line,
            "resolved": self.resolved,
            "confidence": self.confidence.value,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class Endpoint:
    """A configured network location declared by a manifest."""

    id: str
    location: SourceLocation
    host: str | None = None
    port: int | None = None
    protocol: str | None = None
    source_resource_id: str | None = None
    scope: str | None = None
    evidence: list[ExtractedEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the endpoint."""

        return {
            "id": self.id,
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "scope": self.scope,
            "source_resource_id": self.source_resource_id,
            "path": self.location.path,
            "line": self.location.line,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class ResourceReference:
    """A name a manifest points at, and whether it could be resolved."""

    id: str
    kind: ReferenceKind
    name: str
    location: SourceLocation
    status: ReferenceStatus
    reference_type: str
    target_id: str | None = None
    reason: str | None = None
    evidence: list[ExtractedEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the reference."""

        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "reference_type": self.reference_type,
            "status": self.status.value,
            "target_id": self.target_id,
            "reason": self.reason,
            "path": self.location.path,
            "line": self.location.line,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass
class FileAnalysisResult:
    """The outcome of analyzing one manifest file."""

    path: str
    analyzer: str | None
    status: ParseStatus
    method: ExtractionMethod | None = None
    resource_ids: list[str] = field(default_factory=list)
    relationship_ids: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the per-file result."""

        return {
            "path": self.path,
            "analyzer": self.analyzer,
            "status": self.status.value,
            "method": self.method.value if self.method else None,
            "resource_count": len(self.resource_ids),
            "relationship_count": len(self.relationship_ids),
            "resource_ids": self.resource_ids,
            "relationship_ids": self.relationship_ids,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass
class ManifestAnalysisSummary:
    """Aggregate counts describing an analysis run."""

    file_count: int = 0
    analyzed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    resource_count: int = 0
    relationship_count: int = 0
    endpoint_count: int = 0
    unresolved_reference_count: int = 0
    by_analyzer: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise the summary in a stable key order."""

        return {
            "file_count": self.file_count,
            "analyzed_count": self.analyzed_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "resource_count": self.resource_count,
            "relationship_count": self.relationship_count,
            "endpoint_count": self.endpoint_count,
            "unresolved_reference_count": self.unresolved_reference_count,
            "by_analyzer": self.by_analyzer,
        }


@dataclass
class ManifestAnalysisReport:
    """The complete report written to `manifest_analysis.json`."""

    generated_at: datetime
    repository: RepositoryRef
    options: dict
    summary: ManifestAnalysisSummary
    results: list[FileAnalysisResult] = field(default_factory=list)
    resources: list[DeclaredResource] = field(default_factory=list)
    relationships: list[DeclaredRelationship] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    references: list[ResourceReference] = field(default_factory=list)
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
            "results": [item.to_dict() for item in self.results],
            "resources": [item.to_dict() for item in self.resources],
            "relationships": [item.to_dict() for item in self.relationships],
            "endpoints": [item.to_dict() for item in self.endpoints],
            "references": [item.to_dict() for item in self.references],
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------- #
# Identifier helpers
# --------------------------------------------------------------------------- #
#
# Ids are derived from content, never from a sequence number, so two runs over
# the same repository produce comparable output. Ids are scoped to the file the
# resource was declared in, because the same logical name (a `web` service in
# two different Compose files) must not collapse into one node at this stage.


def _digest(*parts: str) -> str:
    """Return a short deterministic digest of the given parts."""

    return sha1(":".join(parts).encode("utf-8")).hexdigest()[:12]


def resource_id(path: str, kind: ResourceKind, name: str) -> str:
    """Derive a resource id from its declaring file, kind and name."""

    return f"resource:{_digest(path, kind.value, name)}"


def relationship_id(
    relationship_type: RelationshipType, source_id: str, target_id: str
) -> str:
    """Derive a relationship id from its type and endpoints."""

    return f"relationship:{_digest(relationship_type.value, source_id, target_id)}"


def endpoint_id(path: str, key: str) -> str:
    """Derive an endpoint id from its declaring file and a descriptive key."""

    return f"endpoint:{_digest(path, key)}"


def reference_id(path: str, kind: ReferenceKind, name: str, reference_type: str) -> str:
    """Derive a reference id from its declaring file, kind and name."""

    return f"reference:{_digest(path, kind.value, name, reference_type)}"
