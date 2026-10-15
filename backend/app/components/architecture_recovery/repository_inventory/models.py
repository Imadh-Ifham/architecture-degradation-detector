"""Repository inventory data model.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Defines the JSON contract written by the repository inventory. The contract
    is explicit and deterministically ordered so inventories taken from two
    releases of the same system can be diffed to detect structural drift.

    Vocabulary:
      * file           - a physical file found in the working tree.
      * classification - how a file's category was derived (rule + confidence).
      * component      - a *candidate* service boundary. Never asserted just
                         because a directory exists; see `components.py`.
      * relationship   - a potential link between files and components,
                         carrying the evidence that produced it.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


SCHEMA_VERSION = "1.0.0"
GENERATOR_NAME = "repository_inventory"
GENERATOR_VERSION = "0.1.0"


class FileCategory(StrEnum):
    """Taxonomy a file is classified into."""

    SOURCE_CODE = "source_code"
    BUILD_MANIFEST = "build_manifest"
    DEPLOYMENT_MANIFEST = "deployment_manifest"
    INFRASTRUCTURE_CONFIG = "infrastructure_config"
    API_SPECIFICATION = "api_specification"
    DATABASE_SCHEMA = "database_schema"
    TEST = "test"
    DOCUMENTATION = "documentation"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    """Whether an association is proven by explicit evidence or only inferred.

    `CONFIRMED` means an artifact names the thing (a manifest declares a name).
    `INFERRED` means structure suggests it (a file sits under a directory).
    """

    CONFIRMED = "confirmed"
    INFERRED = "inferred"


class ComponentKind(StrEnum):
    """How a candidate component was discovered."""

    BUILD_UNIT = "build_unit"
    DEPLOYMENT_SERVICE = "deployment_service"
    DIRECTORY_GROUP = "directory_group"


class RelationshipType(StrEnum):
    """Kinds of potential relationship recorded by the inventory."""

    FILE_IN_COMPONENT = "file_in_component"
    MANIFEST_DEFINES_COMPONENT = "manifest_defines_component"
    DEPLOYMENT_REFERENCES_COMPONENT = "deployment_references_component"
    API_SPEC_DESCRIBES_COMPONENT = "api_spec_describes_component"
    TEST_TARGETS_COMPONENT = "test_targets_component"


@dataclass(frozen=True)
class Evidence:
    """A single fact supporting an inferred or confirmed association."""

    type: str
    detail: str
    path: str | None = None

    def to_dict(self) -> dict:
        """Serialise the evidence, omitting an absent path."""

        payload: dict = {"type": self.type, "detail": self.detail}

        if self.path is not None:
            payload["path"] = self.path

        return payload


@dataclass
class FileRecord:
    """A file discovered during scanning.

    Field values are filled in by successive pipeline stages: scanning sets the
    path and size, classification sets language/format/category, and component
    detection sets `component_id`.
    """

    id: str
    path: str
    name: str
    extension: str
    size_bytes: int
    depth: int
    language: str | None = None
    format: str | None = None
    category: FileCategory = FileCategory.UNKNOWN
    component_id: str | None = None

    def to_dict(self) -> dict:
        """Serialise the file record in a stable key order."""

        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "extension": self.extension,
            "language": self.language,
            "format": self.format,
            "category": self.category.value,
            "size_bytes": self.size_bytes,
            "depth": self.depth,
            "component_id": self.component_id,
        }


@dataclass(frozen=True)
class Classification:
    """The audit trail for one file's category assignment."""

    file_id: str
    category: FileCategory
    confidence: Confidence
    rule: str

    def to_dict(self) -> dict:
        """Serialise the classification."""

        return {
            "file_id": self.file_id,
            "category": self.category.value,
            "confidence": self.confidence.value,
            "rule": self.rule,
        }


@dataclass
class CandidateComponent:
    """A candidate service boundary discovered from evidence.

    Components are candidates, not assertions: `confidence` and `evidence`
    record why the boundary was proposed so later stages can re-evaluate it.
    """

    id: str
    name: str
    kind: ComponentKind
    confidence: Confidence
    root_path: str | None
    languages: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    file_count: int = 0

    def to_dict(self) -> dict:
        """Serialise the component with its supporting evidence."""

        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "confidence": self.confidence.value,
            "root_path": self.root_path,
            "languages": self.languages,
            "file_count": self.file_count,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class Relationship:
    """A potential relationship between a file and a component, or two files."""

    id: str
    type: RelationshipType
    source_kind: str
    source_id: str
    target_kind: str
    target_id: str
    confidence: Confidence
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the relationship with nested endpoints."""

        return {
            "id": self.id,
            "type": self.type.value,
            "source": {"kind": self.source_kind, "id": self.source_id},
            "target": {"kind": self.target_kind, "id": self.target_id},
            "confidence": self.confidence.value,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class RepositoryRef:
    """Identity of the repository an inventory was taken from.

    Every field is optional so an inventory can be produced from a bare
    directory that was never ingested through the ingestion subcomponent.
    """

    id: str | None = None
    url: str | None = None
    branch: str | None = None
    commit: str | None = None

    def to_dict(self) -> dict:
        """Serialise the repository reference."""

        return {
            "id": self.id,
            "url": self.url,
            "branch": self.branch,
            "commit": self.commit,
        }


@dataclass
class InventorySummary:
    """Aggregate counts describing an inventory run."""

    file_count: int = 0
    total_size_bytes: int = 0
    excluded_file_count: int = 0
    excluded_directory_count: int = 0
    unreadable_count: int = 0
    truncated: bool = False
    component_count: int = 0
    relationship_count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_language: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise the summary in a stable key order."""

        return {
            "file_count": self.file_count,
            "total_size_bytes": self.total_size_bytes,
            "excluded_file_count": self.excluded_file_count,
            "excluded_directory_count": self.excluded_directory_count,
            "unreadable_count": self.unreadable_count,
            "truncated": self.truncated,
            "component_count": self.component_count,
            "relationship_count": self.relationship_count,
            "by_category": self.by_category,
            "by_language": self.by_language,
        }


@dataclass
class RepositoryInventory:
    """The complete inventory document written to `repository_inventory.json`."""

    generated_at: datetime
    repository: RepositoryRef
    scan_options: dict
    summary: InventorySummary
    files: list[FileRecord] = field(default_factory=list)
    classifications: list[Classification] = field(default_factory=list)
    components: list[CandidateComponent] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the whole document as the on-disk JSON structure."""

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at.isoformat(),
            "generator": {
                "name": GENERATOR_NAME,
                "version": GENERATOR_VERSION,
            },
            "repository": self.repository.to_dict(),
            "scan_options": self.scan_options,
            "summary": self.summary.to_dict(),
            "files": [item.to_dict() for item in self.files],
            "classifications": [item.to_dict() for item in self.classifications],
            "components": [item.to_dict() for item in self.components],
            "relationships": [item.to_dict() for item in self.relationships],
            "warnings": self.warnings,
        }
