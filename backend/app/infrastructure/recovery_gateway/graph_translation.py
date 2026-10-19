"""Architecture graph translation.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Turns recovery's architecture snapshot into the shape validation reads.

    This is the second translation in this package and it is deliberately not
    the first one extended. The inventory document describes a working tree;
    the snapshot describes an architecture, with element-to-element edges,
    a release identity and an order. They are different documents answering
    different questions, and one function trying to read both would be a
    function with a mode flag.

    ---------------------------------------------------------------------
    THE THREE VOCABULARIES
    ---------------------------------------------------------------------

    Recovery names things its own way, and all three mappings live here
    because this package exists to absorb exactly that.

    **Relationship kind.** Recovery reports four kinds. Validation reduces a
    label to communicates-with or depends-on, and the reduction is driven by
    the label rather than the kind - so a call between two services has to
    arrive carrying a word validation recognises as communication. It would
    otherwise fall through to a dependency, every rule written about
    communication would match nothing, and a correct run would report the
    whole architecture as ungoverned without a single error anywhere.

    **The protocol is recovered from the evidence, not invented.** Recovery
    collapses a gRPC call and an HTTP call into one kind and keeps the
    distinction on the evidence item. Reading it back gives the edge its real
    label - `grpc`, `http` - which is both more honest and more useful than a
    generic one. Where no source-level evidence exists, the edge says
    `service-call` and nothing more specific is claimed.

    **Element kind.** Recovery's component kinds plus the infrastructure roles
    it assigns to a dependency target. A message broker becomes a channel,
    which is the one mapping with a consequence: it is what gives the
    event-driven adapter a publish-subscribe pair to collapse.

    **Evidence quality.** Validation has two values and uses them as a
    ceiling. Recovery carries two separate facts - how confident discovery was
    in the element, and whether a source-level call corroborated the edge -
    and the second is strictly stronger than a manifest declaration. There is
    no third value for it and one is not added here: the ceiling table is
    argued row by row, and `confirmed_by_source` travels as an attribute
    instead, where a screen can show it and the dissertation can sweep it.

    ---------------------------------------------------------------------
    WHAT IS KEPT THAT THE SHAPE HAS NO FIELD FOR
    ---------------------------------------------------------------------

    `logical_id` and `identity_basis` go on the element's attributes,
    `snapshot_id` and `status` on the provenance. Recovery decided a
    component's identity across releases and whether the scan was complete;
    dropping either would mean validation re-deriving an answer that exists,
    or reading a partial scan as a release where elements were removed.
"""

from datetime import datetime

from app.domain.architecture_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    ArchitectureSnapshot,
    SnapshotElement,
    SnapshotRelationship,
    SnapshotStatus,
)
from app.domain.recovered_architecture import (
    ArchitectureElement,
    ArchitectureRelationship,
    ArchitectureStyle,
    DerivationMethod,
    ElementKind,
    EvidenceQuality,
    RecoveredArchitecture,
    RecoveryProvenance,
    StyleSource,
)
from app.domain.validated_architecture import ReleaseDateSource

READER_NAME = "graph_store_reader"

SERVICE_DEPENDENCY = "service_dependency"

#: What recovery's relationship kinds are called in validation's vocabulary.
RELATIONSHIP_LABELS: dict[str, str] = {
    SERVICE_DEPENDENCY: "service-call",
    "infrastructure_dependency": "infrastructure",
    "declared_dependency": "declared",
    "resource_selection": "resource-selection",
}

#: The protocol an evidence item reveals, where it reveals one.
EVIDENCE_LABELS: dict[str, str] = {
    "grpc_service_call": "grpc",
    "http_service_call": "http",
    "cache_client_usage": "cache",
    "database_client_usage": "database",
}

#: Recovery's component kinds and infrastructure roles, as architectural kinds.
ELEMENT_KINDS: dict[str, ElementKind] = {
    "deployment_service": ElementKind.SERVICE,
    "build_unit": ElementKind.MODULE,
    "directory_group": ElementKind.MODULE,
    "database": ElementKind.DATASTORE,
    "cache": ElementKind.DATASTORE,
    "message_broker": ElementKind.CHANNEL,
    "infrastructure": ElementKind.EXTERNAL,
}

#: Discovery confidences that mean an artifact names the thing.
DECLARED_CONFIDENCES = frozenset({"direct", "declared", "confirmed"})

SOURCE_STAGE = "source_code_analysis"


def translate_snapshot(
    snapshot: ArchitectureSnapshot,
    *,
    repository_id: str,
    release_id: str,
    source_reference: str,
    source_paths: dict[str, tuple[str, ...]] | None = None,
    manifest_paths: tuple[str, ...] = (),
    reader: str = READER_NAME,
) -> RecoveredArchitecture:
    """Read one recovery snapshot as a recovered architecture.

    `repository_id` and `release_id` are the caller's names for the thing, not
    recovery's. A run is requested, reported and remembered under the names
    the caller used, and recovery's own identifiers travel beside them on the
    provenance rather than replacing them.
    """

    paths = source_paths or {}

    return RecoveredArchitecture(
        repository_id=repository_id,
        release_id=release_id,
        style=ArchitectureStyle.UNKNOWN,
        style_source=StyleSource.INFERRED_BY_C2,
        elements=tuple(
            _element(item, paths.get(item.id, ())) for item in snapshot.elements
        ),
        relationships=tuple(_relationship(item) for item in snapshot.relationships),
        manifest_paths=manifest_paths,
        provenance=RecoveryProvenance(
            reader=reader,
            source_schema_version=SNAPSHOT_SCHEMA_VERSION,
            source_reference=source_reference,
            source_commit=snapshot.release.commit_sha,
            source_snapshot_id=snapshot.snapshot_id,
            source_status=snapshot.status.value,
        ),
    )


def is_complete(snapshot: ArchitectureSnapshot) -> bool:
    """Whether recovery considers the scan a full account of the release."""

    return snapshot.status is SnapshotStatus.COMPLETE


def incompleteness_note(snapshot: ArchitectureSnapshot) -> str | None:
    """One sentence a reviewer can act on, or nothing when the scan was whole.

    Written as a sentence rather than a code because it is read by a person on
    a screen. The missing inputs are named: `incomplete` alone does not say
    whether a stage failed or was never asked to run.
    """

    if is_complete(snapshot):
        return None

    missing = ", ".join(snapshot.missing_inputs) or "a stage did not report"

    return (
        f"recovery reported release '{snapshot.release.release_id}' as "
        f"{snapshot.status.value} ({missing}), so an element it did not see "
        "cannot be told apart from one that was removed"
    )


def unresolved_warnings(snapshot: ArchitectureSnapshot) -> tuple[str, ...]:
    """What recovery could not resolve, as findings about the subject system.

    A configured address naming nothing in the architecture is a true
    statement about the repository, not a fault in either component, and this
    is the only place in the pipeline where a person sees it.
    """

    return tuple(
        f"{item.stage} could not resolve '{item.reference}'"
        + (f": {item.reason}" if item.reason else "")
        for item in snapshot.unresolved
    )


#: Recovery's ordering fields, as release-date sources this component publishes.
ORDER_SOURCES: dict[str, ReleaseDateSource] = {
    "release_date": ReleaseDateSource.TAGGER,
    "commit_date": ReleaseDateSource.AUTHOR,
}


def released_at(
    snapshot: ArchitectureSnapshot,
) -> tuple[datetime, ReleaseDateSource] | None:
    """When the release was cut, by recovery's account, or nothing.

    Recovery orders a snapshot by the release date, then the commit date,
    then the moment its own analysis ran. The first two are release dates and
    are published as such. **The third is not** - it is when somebody happened
    to run the scan, and publishing it as a release date would order a
    consumer's timeline by analysis order while looking exactly like a real
    one. Nothing is returned for it, which leaves the field empty and honest.
    """

    source = ORDER_SOURCES.get(snapshot.order_source.value)

    return (snapshot.order_timestamp, source) if source else None


def _element(
    element: SnapshotElement, source_paths: tuple[str, ...]
) -> ArchitectureElement:
    """One snapshot element, in validation's vocabulary."""

    attributes = {
        "recovered_kind": element.kind,
        "identity_basis": element.identity_basis.value,
    }

    if element.logical_id:
        attributes["logical_id"] = element.logical_id

    return ArchitectureElement(
        id=element.id,
        name=element.name,
        kind=ELEMENT_KINDS.get(element.kind, ElementKind.MODULE),
        quality=_quality(element.confidence in DECLARED_CONFIDENCES),
        source_paths=source_paths,
        size=element.size,
        size_unit=element.size_unit,
        attributes=attributes,
    )


def _relationship(relationship: SnapshotRelationship) -> ArchitectureRelationship:
    """One snapshot relationship, in validation's vocabulary."""

    declared = any(item.declared for item in relationship.evidence)
    observed = any(
        item.stage == SOURCE_STAGE and item.declared for item in relationship.evidence
    )

    return ArchitectureRelationship(
        source_id=relationship.source_id,
        target_id=relationship.target_id,
        label=_label(relationship),
        quality=_quality(declared or relationship.confirmed_by_source),
        derived_by=DerivationMethod.RECOVERED,
        attributes={
            "kind": relationship.kind,
            "confirmed_by_source": relationship.confirmed_by_source,
            "observed": observed,
            "evidence_stages": sorted(
                {item.stage for item in relationship.evidence}
            ),
            "evidence_types": sorted({item.type for item in relationship.evidence}),
        },
    )


def _label(relationship: SnapshotRelationship) -> str:
    """The word validation reduces, taken from the evidence where it says one.

    Sorted before choosing, so a relationship carrying both a gRPC and an HTTP
    finding resolves the same way every run. Two protocols between one pair is
    a real thing and the second one is not lost - it stays in
    `evidence_types`.
    """

    for item in sorted(relationship.evidence, key=lambda e: (e.stage, e.type)):
        if item.type in EVIDENCE_LABELS:
            return EVIDENCE_LABELS[item.type]

    return RELATIONSHIP_LABELS.get(relationship.kind, relationship.kind)


def _quality(declared: bool) -> EvidenceQuality:
    """Whether an artifact names the thing, in validation's two values."""

    return EvidenceQuality.CONFIRMED if declared else EvidenceQuality.INFERRED


__all__ = [
    "DECLARED_CONFIDENCES",
    "ORDER_SOURCES",
    "ELEMENT_KINDS",
    "EVIDENCE_LABELS",
    "READER_NAME",
    "RELATIONSHIP_LABELS",
    "incompleteness_note",
    "is_complete",
    "released_at",
    "translate_snapshot",
    "unresolved_warnings",
]
