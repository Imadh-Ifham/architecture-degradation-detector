"""Dependency resolution HTTP schemas.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Response body summarising a dependency resolution run. Kept in this
    subcomponent so the API layer can include it without the resolver importing
    the transport layer.
"""

from pathlib import Path

from pydantic import BaseModel

from app.components.architecture_recovery.dependency_resolution.models import (
    DependencyResolutionReport,
)


class DependencyResolutionSummaryResponse(BaseModel):
    """Where a dependency resolution report was written and what it contains."""

    path: str
    resolved_relationship_count: int
    unresolved_count: int
    ambiguous_count: int
    evidence_count: int
    duplicate_evidence_count: int
    diagnostic_count: int
    unique_source_component_count: int
    unique_target_component_count: int
    by_type: dict[str, int]
    by_evidence_source: dict[str, int]
    by_target_class: dict[str, int]

    @classmethod
    def from_report(
        cls, path: Path, report: DependencyResolutionReport
    ) -> "DependencyResolutionSummaryResponse":
        """Build the response from a completed report and its output path."""

        summary = report.summary

        return cls(
            path=str(path),
            resolved_relationship_count=summary.resolved_relationship_count,
            unresolved_count=summary.unresolved_count,
            ambiguous_count=summary.ambiguous_count,
            evidence_count=summary.evidence_count,
            duplicate_evidence_count=summary.duplicate_evidence_count,
            diagnostic_count=summary.diagnostic_count,
            unique_source_component_count=summary.unique_source_component_count,
            unique_target_component_count=summary.unique_target_component_count,
            by_type=summary.by_type,
            by_evidence_source=summary.by_evidence_source,
            by_target_class=summary.by_target_class,
        )
