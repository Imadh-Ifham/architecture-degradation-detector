"""Architecture snapshot domain model.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    One release of one repository, as architecture recovery observed it, with
    the provenance needed to compare it against another release.

    Three identities are deliberately separate, because collapsing them is how
    a historical graph stops being historical:

      * `ArchitectureSnapshot.snapshot_id` - the analyzed revision plus the
        analysis configuration. One release has one snapshot; the same input
        always resolves to the same id.
      * `AnalysisRun.analysis_id` - one execution of architecture recovery. A
        rerun of a release keeps the snapshot and records a new run id.
      * `SnapshotElement.logical_id` - the component's identity *across*
        releases, and only when the evidence supports it. It is `None` when two
        components in one release share a name, because promoting one of them
        would silently merge two histories.

    A snapshot is version-scoped data: an element belongs to exactly one
    snapshot, and an edge connects two elements of the same snapshot. Nothing
    here is shared between releases except the repository and the logical id.

    The file lives in the domain layer because the graph adapter under
    `app/infrastructure/` has to publish it, and infrastructure may not import
    a component.
"""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

SNAPSHOT_SCHEMA_VERSION = "1.0.0"

REPOSITORY_NODE = "Repository"
SNAPSHOT_NODE = "ArchitectureSnapshot"
ELEMENT_NODE = "ArchitectureElement"
DEPENDENCY_RELATIONSHIP = "ARCHITECTURE_DEPENDENCY"


class SnapshotStatus(StrEnum):
    """Whether the snapshot is a complete account of the release.

    Kept on the snapshot rather than inferred from element counts, because an
    element missing from an incomplete scan is indistinguishable from a
    removed element once that distinction is lost.
    """

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class OrderSource(StrEnum):
    """Which field placed this snapshot on the timeline.

    Recorded beside the timestamp so a consumer can tell a publication date
    from a commit date from the moment somebody happened to run the analysis.
    """

    RELEASE_DATE = "release_date"
    COMMIT_DATE = "commit_date"
    ANALYSIS_TIMESTAMP = "analysis_timestamp"


class IdentityBasis(StrEnum):
    """Why a logical identity was or was not assigned."""

    DIRECT = "direct"
    HEURISTIC = "heuristic"
    UNASSIGNED = "unassigned"


class SnapshotIncoherent(ValueError):
    """A relationship names an element the snapshot does not contain."""

    def __init__(self, missing: tuple[str, ...], snapshot_id: str) -> None:
        named = ", ".join(missing)
        super().__init__(
            f"Snapshot '{snapshot_id}' has relationships naming element(s) it "
            f"does not contain: {named}."
        )
        self.missing = missing
        self.snapshot_id = snapshot_id


@dataclass(frozen=True)
class ReleaseMetadata:
    """The source revision a snapshot describes.

    `release_tag` is what a human calls the release; `commit_sha` is what makes
    the analyzed source unambiguous. A tag can be moved, a SHA cannot, so the
    two are never interchangeable and both are recorded.
    """

    repository_id: str
    commit_sha: str
    repository_url: str | None = None
    release_tag: str | None = None
    release_date: dt.datetime | None = None
    release_date_source: str | None = None
    commit_date: dt.datetime | None = None
    branch_name: str | None = None

    @property
    def release_id(self) -> str:
        """The readable name of the analyzed revision."""

        return self.release_tag or f"commit:{self.commit_sha[:12]}"

    def to_dict(self) -> dict:
        return {
            "repository_id": self.repository_id,
            "repository_url": self.repository_url,
            "release_tag": self.release_tag,
            "release_id": self.release_id,
            "commit_sha": self.commit_sha,
            "release_date": _iso(self.release_date),
            "release_date_source": self.release_date_source,
            "commit_date": _iso(self.commit_date),
            "branch_name": self.branch_name,
        }


@dataclass(frozen=True)
class AnalysisRun:
    """One execution of architecture recovery for one revision."""

    analysis_id: str
    analysis_timestamp: dt.datetime
    configuration_key: str
    executed_by: str = "architecture_recovery"

    def to_dict(self) -> dict:
        return {
            "analysis_id": self.analysis_id,
            "analysis_timestamp": _iso(self.analysis_timestamp),
            "configuration_key": self.configuration_key,
            "executed_by": self.executed_by,
        }


@dataclass(frozen=True)
class SnapshotEvidence:
    """Evidence supporting one element or relationship, aggregated by stage."""

    stage: str
    type: str
    declared: bool
    count: int = 1
    references: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "type": self.type,
            "declared": self.declared,
            "count": self.count,
            "references": list(self.references),
        }


@dataclass(frozen=True)
class SnapshotElement:
    """One architectural element as observed in one snapshot."""

    id: str
    name: str
    kind: str
    identity_basis: IdentityBasis
    logical_id: str | None = None
    size: float | None = None
    size_unit: str | None = None
    confidence: str | None = None
    evidence: tuple[SnapshotEvidence, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "logical_id": self.logical_id,
            "name": self.name,
            "kind": self.kind,
            "identity_basis": self.identity_basis.value,
            "size": self.size,
            "size_unit": self.size_unit,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class SnapshotRelationship:
    """One architectural relationship inside one snapshot."""

    id: str
    source_id: str
    target_id: str
    kind: str
    confirmed_by_source: bool = False
    evidence: tuple[SnapshotEvidence, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "confirmed_by_source": self.confirmed_by_source,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class SnapshotUnresolved:
    """A reference the snapshot could not resolve, kept rather than dropped."""

    stage: str
    status: str
    reference: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "status": self.status,
            "reference": self.reference,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ArchitectureSnapshot:
    """One analyzed release, version-scoped and ready to persist."""

    snapshot_id: str
    status: SnapshotStatus
    release: ReleaseMetadata
    run: AnalysisRun
    order_timestamp: dt.datetime
    order_source: OrderSource
    elements: tuple[SnapshotElement, ...] = ()
    relationships: tuple[SnapshotRelationship, ...] = ()
    unresolved: tuple[SnapshotUnresolved, ...] = ()
    diagnostics: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        known = {element.id for element in self.elements}
        missing = tuple(
            sorted(
                {
                    end
                    for relationship in self.relationships
                    for end in (relationship.source_id, relationship.target_id)
                    if end not in known
                }
            )
        )

        if missing:
            raise SnapshotIncoherent(missing, self.snapshot_id)

    @property
    def repository_id(self) -> str:
        return self.release.repository_id

    @property
    def element_count(self) -> int:
        return len(self.elements)

    @property
    def relationship_count(self) -> int:
        return len(self.relationships)

    def element_by_id(self, element_id: str) -> SnapshotElement | None:
        return next((item for item in self.elements if item.id == element_id), None)

    def to_dict(self) -> dict:
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "status": self.status.value,
            "repository": self.release.to_dict(),
            "run": self.run.to_dict(),
            "order_timestamp": _iso(self.order_timestamp),
            "order_source": self.order_source.value,
            "elements": [item.to_dict() for item in self.elements],
            "relationships": [item.to_dict() for item in self.relationships],
            "unresolved": [item.to_dict() for item in self.unresolved],
            "missing_inputs": list(self.missing_inputs),
            "diagnostics": list(self.diagnostics),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class SnapshotSummary:
    """The history row a consumer reads before loading a full snapshot."""

    snapshot_id: str
    repository_id: str
    release_id: str
    release_tag: str | None
    commit_sha: str
    status: SnapshotStatus
    order_timestamp: dt.datetime
    order_source: OrderSource
    element_count: int
    relationship_count: int
    analysis_id: str
    analysis_timestamp: dt.datetime

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "repository_id": self.repository_id,
            "release_id": self.release_id,
            "release_tag": self.release_tag,
            "commit_sha": self.commit_sha,
            "status": self.status.value,
            "order_timestamp": _iso(self.order_timestamp),
            "order_source": self.order_source.value,
            "element_count": self.element_count,
            "relationship_count": self.relationship_count,
            "analysis_id": self.analysis_id,
            "analysis_timestamp": _iso(self.analysis_timestamp),
        }


def _iso(value: dt.datetime | None) -> str | None:
    """Serialise a timestamp as ISO 8601, in UTC when it carries a zone."""

    if value is None:
        return None

    if value.tzinfo is None:
        return value.isoformat()

    return value.astimezone(dt.UTC).isoformat()


__all__ = [
    "DEPENDENCY_RELATIONSHIP",
    "ELEMENT_NODE",
    "REPOSITORY_NODE",
    "SNAPSHOT_NODE",
    "SNAPSHOT_SCHEMA_VERSION",
    "AnalysisRun",
    "ArchitectureSnapshot",
    "IdentityBasis",
    "OrderSource",
    "ReleaseMetadata",
    "SnapshotElement",
    "SnapshotEvidence",
    "SnapshotIncoherent",
    "SnapshotRelationship",
    "SnapshotStatus",
    "SnapshotSummary",
    "SnapshotUnresolved",
]
