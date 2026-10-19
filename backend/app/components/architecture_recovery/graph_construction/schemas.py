"""Graph construction HTTP schemas.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    The compact summary returned with an ingest, and the history rows the read
    endpoints return.

    A full snapshot is served as its stored document rather than duplicated as
    a second transport model: the domain document is already versioned and is
    what downstream components read.
"""

from pathlib import Path

from pydantic import BaseModel

from app.components.architecture_recovery.graph_construction.models import (
    GraphConstructionReport,
)
from app.domain.architecture_snapshot import SnapshotSummary


class GraphConstructionSummaryResponse(BaseModel):
    """Where a graph construction report was written and what it contains."""

    path: str
    snapshot_id: str
    status: str
    element_count: int
    relationship_count: int
    confirmed_by_source_count: int
    unresolved_count: int
    ambiguous_count: int
    diagnostic_count: int
    by_kind: dict[str, int]
    by_identity_basis: dict[str, int]
    size_unit: str | None
    store_published: bool

    @classmethod
    def from_report(
        cls, path: Path, report: GraphConstructionReport
    ) -> "GraphConstructionSummaryResponse":
        """Build the response from a completed report and its report path."""

        summary = report.summary

        return cls(
            path=str(path),
            snapshot_id=report.snapshot_id,
            status=summary.status,
            element_count=summary.element_count,
            relationship_count=summary.relationship_count,
            confirmed_by_source_count=summary.confirmed_by_source_count,
            unresolved_count=summary.unresolved_count,
            ambiguous_count=summary.ambiguous_count,
            diagnostic_count=summary.diagnostic_count,
            by_kind=summary.by_kind,
            by_identity_basis=summary.by_identity_basis,
            size_unit=summary.size_unit,
            store_published=report.store_published,
        )


class SnapshotSummaryResponse(BaseModel):
    """One row of a repository's architecture history."""

    snapshot_id: str
    repository_id: str
    release_id: str
    release_tag: str | None
    commit_sha: str
    status: str
    order_timestamp: str | None
    order_source: str
    element_count: int
    relationship_count: int
    analysis_id: str
    analysis_timestamp: str | None

    @classmethod
    def from_summary(cls, summary: SnapshotSummary) -> "SnapshotSummaryResponse":
        """Build the response from one stored history row."""

        return cls(
            snapshot_id=summary.snapshot_id,
            repository_id=summary.repository_id,
            release_id=summary.release_id,
            release_tag=summary.release_tag,
            commit_sha=summary.commit_sha,
            status=summary.status.value,
            order_timestamp=(
                summary.order_timestamp.isoformat()
                if summary.order_timestamp
                else None
            ),
            order_source=summary.order_source.value,
            element_count=summary.element_count,
            relationship_count=summary.relationship_count,
            analysis_id=summary.analysis_id,
            analysis_timestamp=(
                summary.analysis_timestamp.isoformat()
                if summary.analysis_timestamp
                else None
            ),
        )


__all__ = ["GraphConstructionSummaryResponse", "SnapshotSummaryResponse"]
