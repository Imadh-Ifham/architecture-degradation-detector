"""Source code analysis subcomponent.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Extracts source-level evidence of inter-service dependencies that
    complements manifest analysis and dependency resolution.

    The stage reuses component discovery for component identities and
    dependency resolution for configured endpoints and infrastructure targets.
    It does not reparse manifests, recreate endpoint resolution, or claim that
    a statically observed call executes at runtime.
"""

from app.components.architecture_recovery.source_code_analysis.errors import (
    SourceCodeAnalysisError,
    SourceCodeAnalysisInputError,
    SourceCodeAnalysisWriteError,
)
from app.components.architecture_recovery.source_code_analysis.models import (
    GENERATOR_NAME,
    GENERATOR_VERSION,
    LIMITATIONS,
    SCHEMA_VERSION,
    STRENGTH_SEMANTICS,
    EvidenceStrength,
    EvidenceType,
    FindingType,
    ResolutionStatus,
    SourceCandidate,
    SourceCodeAnalysisReport,
    SourceCodeAnalysisSummary,
    SourceEvidence,
    SourceFinding,
    SourceLanguage,
    candidate_id,
    finding_id,
)
from app.components.architecture_recovery.source_code_analysis.patterns import (
    MAX_SOURCE_BYTES,
    RawEvidence,
    ScanResult,
    language_for,
    sanitize_reference,
    scan_source,
    skip_reason,
)
from app.components.architecture_recovery.source_code_analysis.resolution import (
    ComponentRef,
    DependencyCandidateLink,
    DependencyLink,
    ResolutionResult,
    TargetIndex,
)
from app.components.architecture_recovery.source_code_analysis.schemas import (
    SourceCodeAnalysisSummaryResponse,
)
from app.components.architecture_recovery.source_code_analysis.service import (
    SourceCodeAnalysisService,
    source_code_analysis_service_from_settings,
)
from app.components.architecture_recovery.source_code_analysis.writer import (
    SOURCE_CODE_ANALYSIS_FILE_NAME,
    load_source_code_analysis,
    write_source_code_analysis,
)

__all__ = [
    "GENERATOR_NAME",
    "GENERATOR_VERSION",
    "LIMITATIONS",
    "MAX_SOURCE_BYTES",
    "SCHEMA_VERSION",
    "SOURCE_CODE_ANALYSIS_FILE_NAME",
    "STRENGTH_SEMANTICS",
    "ComponentRef",
    "DependencyCandidateLink",
    "DependencyLink",
    "EvidenceStrength",
    "EvidenceType",
    "FindingType",
    "RawEvidence",
    "ResolutionResult",
    "ResolutionStatus",
    "ScanResult",
    "SourceCandidate",
    "SourceCodeAnalysisError",
    "SourceCodeAnalysisInputError",
    "SourceCodeAnalysisReport",
    "SourceCodeAnalysisService",
    "SourceCodeAnalysisSummary",
    "SourceCodeAnalysisSummaryResponse",
    "SourceCodeAnalysisWriteError",
    "SourceEvidence",
    "SourceFinding",
    "SourceLanguage",
    "TargetIndex",
    "candidate_id",
    "finding_id",
    "language_for",
    "load_source_code_analysis",
    "sanitize_reference",
    "scan_source",
    "skip_reason",
    "source_code_analysis_service_from_settings",
    "write_source_code_analysis",
]
