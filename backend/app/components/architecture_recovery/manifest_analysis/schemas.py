"""Manifest analysis HTTP schemas.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Response body summarising an analysis run. Kept in this subcomponent so the
    API layer can include it without either subcomponent importing the other.
"""

from pathlib import Path

from pydantic import BaseModel

from app.components.architecture_recovery.manifest_analysis.models import (
    ManifestAnalysisReport,
)


class ManifestAnalysisSummaryResponse(BaseModel):
    """Where an analysis report was written and what it contains."""

    path: str
    file_count: int
    analyzed_count: int
    skipped_count: int
    failed_count: int
    resource_count: int
    relationship_count: int
    endpoint_count: int
    unresolved_reference_count: int
    by_analyzer: dict[str, int]

    @classmethod
    def from_report(
        cls, path: Path, report: ManifestAnalysisReport
    ) -> "ManifestAnalysisSummaryResponse":
        """Build the response from a completed report and its output path."""

        summary = report.summary

        return cls(
            path=str(path),
            file_count=summary.file_count,
            analyzed_count=summary.analyzed_count,
            skipped_count=summary.skipped_count,
            failed_count=summary.failed_count,
            resource_count=summary.resource_count,
            relationship_count=summary.relationship_count,
            endpoint_count=summary.endpoint_count,
            unresolved_reference_count=summary.unresolved_reference_count,
            by_analyzer=summary.by_analyzer,
        )
