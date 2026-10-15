"""Manifest analysis subcomponent.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Extracts structured architectural information from the configuration and
    manifest files the repository inventory discovered, and re-exports the
    subcomponent's public surface.

    Pipeline: inventory (already done) -> analyzer selection -> format-specific
    parsing -> structured findings -> report. Analyzers only read; nothing is
    executed, nothing is written back to the repository, and no relationship is
    asserted that a later stage would need traffic evidence for.
"""

from app.components.architecture_recovery.manifest_analysis.base import (
    AnalyzerResult,
    ManifestAnalyzer,
    has_template_expressions,
    read_manifest_text,
)
from app.components.architecture_recovery.manifest_analysis.compose import (
    ComposeAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.dockerfile import (
    DockerfileAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.errors import (
    AnalysisInputError,
    AnalysisWriteError,
    ManifestAnalysisError,
)
from app.components.architecture_recovery.manifest_analysis.kubernetes import (
    KubernetesAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.loader import (
    AnalysisArtifactError,
    load_analysis_report,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    SCHEMA_VERSION,
    Confidence,
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
from app.components.architecture_recovery.manifest_analysis.openapi import (
    OpenApiAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.protobuf import (
    ProtobufAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.registry import (
    AnalyzerRegistry,
    CANDIDATE_CATEGORIES,
    DEFAULT_ANALYZER_FACTORIES,
)
from app.components.architecture_recovery.manifest_analysis.schemas import (
    ManifestAnalysisSummaryResponse,
)
from app.components.architecture_recovery.manifest_analysis.service import (
    ManifestAnalysisService,
    load_inventory,
    manifest_analysis_service_from_settings,
)
from app.components.architecture_recovery.manifest_analysis.writer import (
    MANIFEST_ANALYSIS_FILE_NAME,
    load_manifest_analysis,
    write_manifest_analysis,
)


__all__ = [
    "CANDIDATE_CATEGORIES",
    "DEFAULT_ANALYZER_FACTORIES",
    "MANIFEST_ANALYSIS_FILE_NAME",
    "SCHEMA_VERSION",
    "AnalysisInputError",
    "AnalysisArtifactError",
    "AnalysisWriteError",
    "AnalyzerRegistry",
    "AnalyzerResult",
    "ComposeAnalyzer",
    "Confidence",
    "DeclaredRelationship",
    "DeclaredResource",
    "Diagnostic",
    "DiagnosticSeverity",
    "DockerfileAnalyzer",
    "Endpoint",
    "ExtractedEvidence",
    "ExtractionMethod",
    "FileAnalysisResult",
    "has_template_expressions",
    "KubernetesAnalyzer",
    "ManifestAnalysisError",
    "ManifestAnalysisReport",
    "ManifestAnalysisService",
    "ManifestAnalysisSummary",
    "ManifestAnalysisSummaryResponse",
    "ManifestAnalyzer",
    "OpenApiAnalyzer",
    "ParseStatus",
    "ProtobufAnalyzer",
    "ReferenceKind",
    "ReferenceStatus",
    "RelationshipOrigin",
    "RelationshipType",
    "ResourceKind",
    "ResourceReference",
    "SourceLocation",
    "load_inventory",
    "load_analysis_report",
    "load_manifest_analysis",
    "manifest_analysis_service_from_settings",
    "read_manifest_text",
    "write_manifest_analysis",
]
