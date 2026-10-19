"""Graph construction report model.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    The JSON report written beside the analysis, and the summary returned to
    the caller.

    The report is not a second graph database. It records what was built, from
    which revision, under which analysis run, and whether the store accepted
    it. Neo4j holds the graph; this file explains one run.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.architecture_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    ArchitectureSnapshot,
    SnapshotStatus,
)

REPORT_SCHEMA_VERSION = "1.0.0"
GENERATOR_NAME = "graph_construction"
GENERATOR_VERSION = "0.1.0"


@dataclass(frozen=True)
class GraphConstructionSummary:
    """Counts computed from a completed snapshot."""

    status: str
    element_count: int
    relationship_count: int
    confirmed_by_source_count: int
    unresolved_count: int
    ambiguous_count: int
    diagnostic_count: int
    by_kind: dict[str, int] = field(default_factory=dict)
    by_identity_basis: dict[str, int] = field(default_factory=dict)
    size_unit: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "element_count": self.element_count,
            "relationship_count": self.relationship_count,
            "confirmed_by_source_count": self.confirmed_by_source_count,
            "unresolved_count": self.unresolved_count,
            "ambiguous_count": self.ambiguous_count,
            "diagnostic_count": self.diagnostic_count,
            "by_kind": self.by_kind,
            "by_identity_basis": self.by_identity_basis,
            "size_unit": self.size_unit,
        }

    @classmethod
    def from_snapshot(cls, snapshot: ArchitectureSnapshot) -> "GraphConstructionSummary":
        """Compute every count from the snapshot itself."""

        by_kind: dict[str, int] = {}

        for relationship in snapshot.relationships:
            by_kind[relationship.kind] = by_kind.get(relationship.kind, 0) + 1

        by_identity: dict[str, int] = {}

        for element in snapshot.elements:
            key = element.identity_basis.value
            by_identity[key] = by_identity.get(key, 0) + 1

        units = {element.size_unit for element in snapshot.elements if element.size_unit}

        return cls(
            status=snapshot.status.value,
            element_count=snapshot.element_count,
            relationship_count=snapshot.relationship_count,
            confirmed_by_source_count=sum(
                1 for item in snapshot.relationships if item.confirmed_by_source
            ),
            unresolved_count=sum(
                1
                for item in snapshot.unresolved
                if item.status == "unresolved"
            ),
            ambiguous_count=sum(
                1 for item in snapshot.unresolved if item.status == "ambiguous"
            ),
            diagnostic_count=len(snapshot.diagnostics),
            by_kind=dict(sorted(by_kind.items())),
            by_identity_basis=dict(sorted(by_identity.items())),
            size_unit=next(iter(units)) if len(units) == 1 else None,
        )


@dataclass(frozen=True)
class GraphConstructionReport:
    """One completed graph construction run."""

    generated_at: datetime
    snapshot: ArchitectureSnapshot
    summary: GraphConstructionSummary
    options: dict
    store_published: bool = False
    store_reference: str | None = None
    store_warnings: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def status(self) -> SnapshotStatus:
        return self.snapshot.status

    @property
    def snapshot_id(self) -> str:
        return self.snapshot.snapshot_id

    def to_dict(self) -> dict:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
            "generated_at": self.generated_at.isoformat(),
            "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
            "snapshot_id": self.snapshot.snapshot_id,
            "status": self.snapshot.status.value,
            "repository": self.snapshot.release.to_dict(),
            "analysis_run": self.snapshot.run.to_dict(),
            "summary": self.summary.to_dict(),
            "snapshot": self.snapshot.to_dict(),
            "store": {
                "published": self.store_published,
                "reference": self.store_reference,
                "warnings": list(self.store_warnings),
            },
            "options": self.options,
            "warnings": list(self.warnings),
        }


__all__ = [
    "GENERATOR_NAME",
    "GENERATOR_VERSION",
    "REPORT_SCHEMA_VERSION",
    "GraphConstructionReport",
    "GraphConstructionSummary",
]
