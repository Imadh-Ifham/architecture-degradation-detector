"""Component discovery HTTP schemas.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Response body summarising a discovery run. Kept in this subcomponent so the
    API layer can include it without any subcomponent importing another.
"""

from pathlib import Path

from pydantic import BaseModel

from app.components.architecture_recovery.component_discovery.models import (
    ComponentDiscoveryReport,
)


class ComponentDiscoverySummaryResponse(BaseModel):
    """Where a discovery report was written and what it contains."""

    path: str
    component_count: int
    artifact_count: int
    unresolved_count: int
    ambiguous_count: int
    duplicate_identity_count: int
    direct_association_count: int
    heuristic_association_count: int
    by_type: dict[str, int]
    by_confidence: dict[str, int]
    by_association: dict[str, int]

    @classmethod
    def from_report(
        cls, path: Path, report: ComponentDiscoveryReport
    ) -> "ComponentDiscoverySummaryResponse":
        """Build the response from a completed report and its output path."""

        summary = report.summary

        return cls(
            path=str(path),
            component_count=summary.component_count,
            artifact_count=summary.artifact_count,
            unresolved_count=summary.unresolved_count,
            ambiguous_count=summary.ambiguous_count,
            duplicate_identity_count=summary.duplicate_identity_count,
            direct_association_count=summary.direct_association_count,
            heuristic_association_count=summary.heuristic_association_count,
            by_type=summary.by_type,
            by_confidence=summary.by_confidence,
            by_association=summary.by_association,
        )
