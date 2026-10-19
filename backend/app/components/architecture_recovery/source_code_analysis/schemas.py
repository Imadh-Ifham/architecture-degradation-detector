"""Source code analysis HTTP schemas.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Response body summarising a source code analysis run.
"""

from pathlib import Path

from pydantic import BaseModel

from app.components.architecture_recovery.source_code_analysis.models import (
    SourceCodeAnalysisReport,
)


class SourceCodeAnalysisSummaryResponse(BaseModel):
    """Where a source code analysis report was written and what it contains."""

    path: str
    component_count: int
    source_file_count: int
    skipped_file_count: int
    finding_count: int
    resolved_count: int
    unresolved_count: int
    ambiguous_count: int
    corroborated_count: int
    evidence_count: int
    diagnostic_count: int
    by_finding_type: dict[str, int]
    by_evidence_type: dict[str, int]
    by_language: dict[str, int]

    @classmethod
    def from_report(
        cls, path: Path, report: SourceCodeAnalysisReport
    ) -> "SourceCodeAnalysisSummaryResponse":
        """Build the response from a completed report and its output path."""

        summary = report.summary

        return cls(
            path=str(path),
            component_count=summary.component_count,
            source_file_count=summary.source_file_count,
            skipped_file_count=summary.skipped_file_count,
            finding_count=summary.finding_count,
            resolved_count=summary.resolved_count,
            unresolved_count=summary.unresolved_count,
            ambiguous_count=summary.ambiguous_count,
            corroborated_count=summary.corroborated_count,
            evidence_count=summary.evidence_count,
            diagnostic_count=summary.diagnostic_count,
            by_finding_type=summary.by_finding_type,
            by_evidence_type=summary.by_evidence_type,
            by_language=summary.by_language,
        )
