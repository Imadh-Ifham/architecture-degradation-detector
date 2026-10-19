"""Source code analysis data model.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Defines the versioned JSON contract written by source code analysis.

    A finding is a source-level observation about a client that may reach
    another component. It is not proof that the call executes at runtime, and it
    is kept separate from the manifest-derived relationships written by
    dependency resolution.

    Evidence strength is categorical:

      * `observed_invocation` - a client construction and an invocation method
                                 occur at the analysed call sites.
      * `client_construction`  - a client is constructed or configured, but no
                                 invocation was found.
      * `symbol_reference`     - a symbol suggests a client, with no construction
                                 or invocation.

    Evidence records only provenance and the referenced symbol or method. Source
    text, configuration values and credentials are never copied into the report.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha1

from app.components.architecture_recovery.manifest_analysis.models import (
    Diagnostic,
)
from app.components.architecture_recovery.repository_inventory.models import (
    RepositoryRef,
)

SCHEMA_VERSION = "1.0.0"
GENERATOR_NAME = "source_code_analysis"
GENERATOR_VERSION = "0.1.0"


class SourceLanguage(StrEnum):
    """Languages with a source analyzer in this implementation."""

    GO = "go"
    PYTHON = "python"
    CSHARP = "csharp"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    UNKNOWN = "unknown"


class FindingType(StrEnum):
    """The kind of source-level relationship a finding represents."""

    GRPC_SERVICE_CALL = "grpc_service_call"
    HTTP_SERVICE_CALL = "http_service_call"
    CACHE_CLIENT_USAGE = "cache_client_usage"
    DATABASE_CLIENT_USAGE = "database_client_usage"


class EvidenceType(StrEnum):
    """The exact source construct that produced a finding."""

    GRPC_CLIENT_CONSTRUCTION = "grpc_client_construction"
    GRPC_CLIENT_INVOCATION = "grpc_client_invocation"
    HTTP_CLIENT_INVOCATION = "http_client_invocation"
    CACHE_CLIENT_CONSTRUCTION = "cache_client_construction"
    CACHE_CLIENT_INVOCATION = "cache_client_invocation"
    DATABASE_CLIENT_CONSTRUCTION = "database_client_construction"
    DATABASE_CLIENT_INVOCATION = "database_client_invocation"
    SYMBOL_REFERENCE = "symbol_reference"


class EvidenceStrength(StrEnum):
    """How strongly a finding is supported by source evidence."""

    OBSERVED_INVOCATION = "observed_invocation"
    CLIENT_CONSTRUCTION = "client_construction"
    SYMBOL_REFERENCE = "symbol_reference"


class ResolutionStatus(StrEnum):
    """Whether a target component could be resolved uniquely."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


#: Explanation of the strength categories, recorded in the report options.
STRENGTH_SEMANTICS: dict[str, str] = {
    EvidenceStrength.OBSERVED_INVOCATION.value: (
        "a client construction and an invocation method are both present at the "
        "analysed call sites; the code contains a call path, not proof of runtime "
        "execution"
    ),
    EvidenceStrength.CLIENT_CONSTRUCTION.value: (
        "a client is constructed or configured, but no invocation method was found"
    ),
    EvidenceStrength.SYMBOL_REFERENCE.value: (
        "a symbol or import suggests a client, with no construction or invocation"
    ),
}

#: What this stage does not prove. Recorded in the artifact so a consumer does
#: not read the graph as verified runtime behaviour.
LIMITATIONS: tuple[str, ...] = (
    "Static analysis does not prove that a detected call path executes at "
    "runtime, nor that a configured client is ever used.",
    "Only a scoped set of language patterns is recognised (Go, Python, C#, "
    "JavaScript/TypeScript and Java). Unsupported languages are counted and "
    "diagnosed, not guessed.",
    "Generated code, test files and standalone client/example files are skipped "
    "to avoid duplicate or false findings.",
    "HTTP targets are resolved from a literal host, a configured environment key "
    "recorded by dependency resolution, or the component's only configured "
    "endpoint. Otherwise the finding stays unresolved.",
    "Multiple call sites between the same component pair are aggregated into one "
    "finding per finding type; they do not create duplicate logical edges.",
    "A finding that corroborates a dependency-resolution relationship links to "
    "that relationship id and does not replace the manifest evidence.",
)


@dataclass(frozen=True)
class SourceEvidence:
    """Provenance for one source construct supporting a finding."""

    evidence_type: EvidenceType
    strength: EvidenceStrength
    path: str
    line: int
    symbol: str | None = None
    method: str | None = None
    detail: str = ""
    target_reference: str | None = None
    resolution_method: str | None = None
    language: SourceLanguage = SourceLanguage.UNKNOWN

    def sort_key(self) -> tuple:
        """Return a deterministic ordering and deduplication key."""

        return (
            self.evidence_type.value,
            self.path,
            self.line,
            self.symbol or "",
            self.method or "",
            self.target_reference or "",
            self.detail,
        )

    def to_dict(self) -> dict:
        """Serialise the evidence, keeping fields that do not apply as null."""

        return {
            "evidence_type": self.evidence_type.value,
            "strength": self.strength.value,
            "language": self.language.value,
            "path": self.path,
            "line": self.line,
            "symbol": self.symbol,
            "method": self.method,
            "detail": self.detail,
            "target_reference": self.target_reference,
            "resolution_method": self.resolution_method,
        }


@dataclass
class SourceFinding:
    """A resolved source-level relationship between two components."""

    id: str
    finding_type: FindingType
    source_component_id: str
    target_component_id: str
    source_component_name: str | None = None
    target_component_name: str | None = None
    status: ResolutionStatus = ResolutionStatus.RESOLVED
    evidence_strength: EvidenceStrength = EvidenceStrength.OBSERVED_INVOCATION
    language: SourceLanguage = SourceLanguage.UNKNOWN
    target_reference: str | None = None
    resolution_method: str | None = None
    corroborates_dependency_relationship_id: str | None = None
    evidence: list[SourceEvidence] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the finding with its aggregated evidence."""

        return {
            "id": self.id,
            "finding_type": self.finding_type.value,
            "status": self.status.value,
            "evidence_strength": self.evidence_strength.value,
            "language": self.language.value,
            "source_component_id": self.source_component_id,
            "source_component_name": self.source_component_name,
            "target_component_id": self.target_component_id,
            "target_component_name": self.target_component_name,
            "target_reference": self.target_reference,
            "resolution_method": self.resolution_method,
            "corroborates_dependency_relationship_id": (
                self.corroborates_dependency_relationship_id
            ),
            "evidence": [
                item.to_dict() for item in sorted(self.evidence, key=lambda x: x.sort_key())
            ],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass
class SourceCandidate:
    """An unresolved or ambiguous source-level finding."""

    id: str
    finding_type: FindingType
    source_component_id: str
    status: ResolutionStatus
    source_component_name: str | None = None
    target_reference: str | None = None
    language: SourceLanguage = SourceLanguage.UNKNOWN
    evidence_strength: EvidenceStrength = EvidenceStrength.OBSERVED_INVOCATION
    candidate_component_ids: list[str] = field(default_factory=list)
    candidate_component_names: list[str] = field(default_factory=list)
    reason: str = ""
    resolution_method: str | None = None
    evidence: list[SourceEvidence] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the candidate with its preserved evidence."""

        return {
            "id": self.id,
            "finding_type": self.finding_type.value,
            "status": self.status.value,
            "evidence_strength": self.evidence_strength.value,
            "language": self.language.value,
            "source_component_id": self.source_component_id,
            "source_component_name": self.source_component_name,
            "target_reference": self.target_reference,
            "candidate_component_ids": self.candidate_component_ids,
            "candidate_component_names": self.candidate_component_names,
            "reason": self.reason,
            "resolution_method": self.resolution_method,
            "evidence": [
                item.to_dict() for item in sorted(self.evidence, key=lambda x: x.sort_key())
            ],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass
class SourceCodeAnalysisSummary:
    """Aggregate counts computed from a completed report."""

    component_count: int = 0
    source_file_count: int = 0
    skipped_file_count: int = 0
    finding_count: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    ambiguous_count: int = 0
    corroborated_count: int = 0
    evidence_count: int = 0
    diagnostic_count: int = 0
    by_finding_type: dict[str, int] = field(default_factory=dict)
    by_evidence_type: dict[str, int] = field(default_factory=dict)
    by_language: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise the summary in a stable key order."""

        return {
            "component_count": self.component_count,
            "source_file_count": self.source_file_count,
            "skipped_file_count": self.skipped_file_count,
            "finding_count": self.finding_count,
            "resolved_count": self.resolved_count,
            "unresolved_count": self.unresolved_count,
            "ambiguous_count": self.ambiguous_count,
            "corroborated_count": self.corroborated_count,
            "evidence_count": self.evidence_count,
            "diagnostic_count": self.diagnostic_count,
            "by_finding_type": self.by_finding_type,
            "by_evidence_type": self.by_evidence_type,
            "by_language": self.by_language,
        }


@dataclass
class SourceCodeAnalysisReport:
    """The complete report written to `source_code_analysis.json`."""

    generated_at: datetime
    repository: RepositoryRef
    options: dict
    summary: SourceCodeAnalysisSummary
    findings: list[SourceFinding] = field(default_factory=list)
    unresolved: list[SourceCandidate] = field(default_factory=list)
    ambiguous: list[SourceCandidate] = field(default_factory=list)
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
            "findings": [item.to_dict() for item in self.findings],
            "unresolved": [item.to_dict() for item in self.unresolved],
            "ambiguous": [item.to_dict() for item in self.ambiguous],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------- #
# Identifier helpers
# --------------------------------------------------------------------------- #


def _digest(*parts: str) -> str:
    """Return a short deterministic digest of the given parts."""

    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def finding_id(
    finding_type: FindingType, source_component_id: str, target_component_id: str
) -> str:
    """Derive a finding id from its type and component endpoints."""

    return f"source-finding:{_digest(finding_type.value, source_component_id, target_component_id)}"


def candidate_id(
    finding_type: FindingType, source_component_id: str, target_reference: str
) -> str:
    """Derive a candidate id from its type, source and original reference."""

    return f"source-candidate:{_digest(finding_type.value, source_component_id, target_reference)}"


__all__ = [
    "GENERATOR_NAME",
    "GENERATOR_VERSION",
    "LIMITATIONS",
    "SCHEMA_VERSION",
    "STRENGTH_SEMANTICS",
    "EvidenceStrength",
    "EvidenceType",
    "FindingType",
    "ResolutionStatus",
    "SourceCandidate",
    "SourceCodeAnalysisReport",
    "SourceCodeAnalysisSummary",
    "SourceEvidence",
    "SourceFinding",
    "SourceLanguage",
    "candidate_id",
    "finding_id",
]
