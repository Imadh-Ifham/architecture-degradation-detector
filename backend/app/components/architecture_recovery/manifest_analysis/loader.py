"""Manifest analysis artifact loader.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Rebuilds the typed manifest-analysis report from the JSON written by the
    writer, so a later stage can consume the analysis without re-parsing the
    repository.

    This is the narrowly scoped interface the downstream component discovery
    stage needs: it keeps the JSON schema knowledge in the module that owns it
    instead of spreading it across consumers.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.components.architecture_recovery.manifest_analysis.models import (
    DeclaredRelationship,
    DeclaredResource,
    Diagnostic,
    DiagnosticSeverity,
    Endpoint,
    ExtractedEvidence,
    ExtractionMethod,
    FileAnalysisResult,
    ManifestAnalysisReport,
    ManifestAnalysisSummary,
    ParseStatus,
    ReferenceKind,
    ReferenceStatus,
    RelationshipOrigin,
    RelationshipType,
    ResourceKind,
    ResourceReference,
    SourceLocation,
)
from app.components.architecture_recovery.repository_inventory.models import (
    RepositoryRef,
)


class AnalysisArtifactError(ValueError):
    """The stored manifest analysis could not be reconstructed."""


def load_analysis_report(path: Path) -> ManifestAnalysisReport:
    """Read a `manifest_analysis.json` document back into typed objects.

    Raises `AnalysisArtifactError` when the file is missing, unreadable, or does
    not have the expected structure. A missing or malformed upstream artifact is
    an input problem, so it is raised rather than silently producing an empty
    report that a consumer would read as "no findings".
    """

    path = Path(path)

    if not path.is_file():
        raise AnalysisArtifactError(
            f"No manifest analysis at '{path}'; run manifest analysis first."
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AnalysisArtifactError(
            f"Could not read the manifest analysis at '{path}': {error}"
        ) from error

    if not isinstance(payload, dict):
        raise AnalysisArtifactError(
            f"Manifest analysis at '{path}' is not a JSON object."
        )

    try:
        return _report_from_dict(payload)
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise AnalysisArtifactError(
            f"Manifest analysis at '{path}' has an unexpected structure: {error}"
        ) from error


def _report_from_dict(payload: dict) -> ManifestAnalysisReport:
    """Rebuild the report from its serialised form."""

    repository = payload.get("repository") or {}
    summary = payload.get("summary") or {}

    return ManifestAnalysisReport(
        # The analysis is a completed run; its original timestamp is not needed
        # downstream, and the artifact carries it if it is ever required.
        generated_at=datetime.now(timezone.utc),
        repository=RepositoryRef(
            id=repository.get("id"),
            url=repository.get("url"),
            branch=repository.get("branch"),
            commit=repository.get("commit"),
        ),
        options=payload.get("options") or {},
        summary=ManifestAnalysisSummary(
            file_count=int(summary.get("file_count") or 0),
            analyzed_count=int(summary.get("analyzed_count") or 0),
            skipped_count=int(summary.get("skipped_count") or 0),
            failed_count=int(summary.get("failed_count") or 0),
            resource_count=int(summary.get("resource_count") or 0),
            relationship_count=int(summary.get("relationship_count") or 0),
            endpoint_count=int(summary.get("endpoint_count") or 0),
            unresolved_reference_count=int(
                summary.get("unresolved_reference_count") or 0
            ),
            by_analyzer=dict(summary.get("by_analyzer") or {}),
        ),
        results=[
            _file_result_from_dict(item) for item in payload.get("results") or []
        ],
        resources=[
            _resource_from_dict(item) for item in payload.get("resources") or []
        ],
        relationships=[
            _relationship_from_dict(item)
            for item in payload.get("relationships") or []
        ],
        endpoints=[_endpoint_from_dict(item) for item in payload.get("endpoints") or []],
        references=[
            _reference_from_dict(item) for item in payload.get("references") or []
        ],
        warnings=list(payload.get("warnings") or []),
    )


def _location_from_dict(payload: dict) -> SourceLocation:
    """Rebuild a source location."""

    return SourceLocation(path=payload.get("path") or "", line=payload.get("line"))


def _evidence_from_dict(payload: dict) -> ExtractedEvidence:
    """Rebuild one piece of extraction evidence."""

    return ExtractedEvidence(
        type=payload.get("type") or "",
        detail=payload.get("detail") or "",
        method=_method(payload.get("method")),
        location=SourceLocation(
            path=payload.get("path") or "", line=payload.get("line")
        ),
    )


def _resource_from_dict(payload: dict) -> DeclaredResource:
    """Rebuild one declared resource."""

    return DeclaredResource(
        id=payload["id"],
        kind=ResourceKind(payload["kind"]),
        name=payload.get("name") or "",
        namespace=payload.get("namespace"),
        location=_location_from_dict(payload),
        analyzer=payload.get("analyzer") or "",
        method=_method(payload.get("method")),
        attributes=dict(payload.get("attributes") or {}),
        evidence=[
            _evidence_from_dict(item) for item in payload.get("evidence") or []
        ],
    )


def _relationship_from_dict(payload: dict) -> DeclaredRelationship:
    """Rebuild one declared relationship."""

    return DeclaredRelationship(
        id=payload["id"],
        type=RelationshipType(payload["type"]),
        origin=RelationshipOrigin(payload["origin"]),
        source_id=payload["source_id"],
        target_id=payload["target_id"],
        location=_location_from_dict(payload),
        resolved=bool(payload.get("resolved")),
        evidence=[
            _evidence_from_dict(item) for item in payload.get("evidence") or []
        ],
    )


def _endpoint_from_dict(payload: dict) -> Endpoint:
    """Rebuild one endpoint."""

    return Endpoint(
        id=payload["id"],
        location=_location_from_dict(payload),
        host=payload.get("host"),
        port=payload.get("port"),
        protocol=payload.get("protocol"),
        source_resource_id=payload.get("source_resource_id"),
        scope=payload.get("scope"),
        evidence=[
            _evidence_from_dict(item) for item in payload.get("evidence") or []
        ],
    )


def _reference_from_dict(payload: dict) -> ResourceReference:
    """Rebuild one reference."""

    return ResourceReference(
        id=payload["id"],
        kind=ReferenceKind(payload["kind"]),
        name=payload.get("name") or "",
        location=_location_from_dict(payload),
        status=ReferenceStatus(payload["status"]),
        reference_type=payload.get("reference_type") or "",
        target_id=payload.get("target_id"),
        reason=payload.get("reason"),
        evidence=[
            _evidence_from_dict(item) for item in payload.get("evidence") or []
        ],
    )


def _file_result_from_dict(payload: dict) -> FileAnalysisResult:
    """Rebuild one per-file analysis result."""

    return FileAnalysisResult(
        path=payload.get("path") or "",
        analyzer=payload.get("analyzer"),
        status=ParseStatus(payload["status"]),
        method=_method(payload.get("method")) if payload.get("method") else None,
        resource_ids=list(payload.get("resource_ids") or []),
        relationship_ids=list(payload.get("relationship_ids") or []),
        diagnostics=[
            _diagnostic_from_dict(item) for item in payload.get("diagnostics") or []
        ],
    )


def _diagnostic_from_dict(payload: dict) -> Diagnostic:
    """Rebuild one diagnostic."""

    return Diagnostic(
        severity=DiagnosticSeverity(payload["severity"]),
        message=payload.get("message") or "",
        path=payload.get("path") or "",
        line=payload.get("line"),
        analyzer=payload.get("analyzer"),
    )


def _method(value: object) -> ExtractionMethod:
    """Map a serialised extraction method back to its enum."""

    try:
        return ExtractionMethod(value)
    except ValueError:
        return ExtractionMethod.TEXT


__all__ = ["AnalysisArtifactError", "load_analysis_report"]
