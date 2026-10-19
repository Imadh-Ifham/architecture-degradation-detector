"""Architecture snapshots, projected into the graph store.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    The `ArchitectureSnapshotStore` graph construction writes through, and the
    reader the later components use.

    **Why the labels are new rather than reused.** The validated graph already
    owns `(:Release)` and `(:Element)`, keyed by `(repository_id, release_id)`.
    Recovery's snapshot is a different observation of a different stage, and
    writing it onto those nodes would overwrite a validation rollup with
    analysed evidence. So recovery writes `(:ArchitectureSnapshot)` and
    `(:ArchitectureElement)`, under a shared `(:Repository)`, and leaves the
    validated labels alone. One repository, two views of it, neither able to
    destroy the other.

    **Why a rerun only touches its own subgraph.** Two runs of one revision
    that both merge forward would leave two sets of edges on one pair, and
    every count read afterwards would be doubled. The sweep is scoped to the
    snapshot's own elements and runs last, so a reader sees the old shape or
    the new one.

    **Why `order_timestamp` is stored as text.** Released dates, commit dates
    and analysis timestamps all become one comparable ISO 8601 string in UTC,
    and `order_source` says which field produced it. A consumer ordering by a
    tag would sort `v0.10.0` before `v0.9.0`; a consumer ordering by this
    value cannot.
"""

import json
from datetime import UTC, datetime

from app.domain.architecture_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    AnalysisRun,
    ArchitectureSnapshot,
    IdentityBasis,
    OrderSource,
    ReleaseMetadata,
    SnapshotElement,
    SnapshotEvidence,
    SnapshotRelationship,
    SnapshotStatus,
    SnapshotSummary,
    SnapshotUnresolved,
)

CONSTRAINTS = (
    """
    CREATE CONSTRAINT architecture_snapshot_key IF NOT EXISTS
    FOR (s:ArchitectureSnapshot) REQUIRE (s.repository_id, s.snapshot_id) IS UNIQUE
    """,
    """
    CREATE CONSTRAINT architecture_element_key IF NOT EXISTS
    FOR (e:ArchitectureElement) REQUIRE (e.repository_id, e.snapshot_id, e.element_id)
    IS UNIQUE
    """,
    """
    CREATE INDEX architecture_element_logical IF NOT EXISTS
    FOR (e:ArchitectureElement) ON (e.repository_id, e.logical_id)
    """,
    """
    CREATE INDEX architecture_snapshot_order IF NOT EXISTS
    FOR (s:ArchitectureSnapshot) ON (s.repository_id, s.order_timestamp)
    """,
)
"""Created before the first write, and idempotent.

The unique keys are what make a rerun a rerun rather than a second history.
`IS UNIQUE` and not `IS NODE KEY`, for the same reason as the validated
projection: the team runs Community edition, which refuses node keys.
"""

MERGE_SNAPSHOT = """
MERGE (repository:Repository {repository_id: $repository_id})
MERGE (snapshot:ArchitectureSnapshot {repository_id: $repository_id,
                                      snapshot_id: $snapshot_id})
ON CREATE SET snapshot.first_analyzed_at = $analysis_timestamp,
              snapshot.analysis_count = 0
SET snapshot.schema_version = $schema_version,
    snapshot.release_id = $release_id,
    snapshot.release_tag = $release_tag,
    snapshot.repository_url = $repository_url,
    snapshot.branch_name = $branch_name,
    snapshot.commit_sha = $commit_sha,
    snapshot.release_date = $release_date,
    snapshot.release_date_source = $release_date_source,
    snapshot.commit_date = $commit_date,
    snapshot.status = $status,
    snapshot.order_timestamp = $order_timestamp,
    snapshot.order_source = $order_source,
    snapshot.analysis_id = $analysis_id,
    snapshot.analysis_timestamp = $analysis_timestamp,
    snapshot.last_analyzed_at = $analysis_timestamp,
    snapshot.analysis_count = snapshot.analysis_count + 1,
    snapshot.configuration_key = $configuration_key,
    snapshot.element_count = $element_count,
    snapshot.relationship_count = $relationship_count,
    snapshot.unresolved_json = $unresolved_json,
    snapshot.diagnostics_json = $diagnostics_json,
    snapshot.missing_inputs = $missing_inputs,
    snapshot.notes = $notes
MERGE (repository)-[:HAS_SNAPSHOT]->(snapshot)
"""

MERGE_ELEMENT = """
MATCH (snapshot:ArchitectureSnapshot {repository_id: $repository_id,
                                      snapshot_id: $snapshot_id})
MERGE (element:ArchitectureElement {repository_id: $repository_id,
                                    snapshot_id: $snapshot_id,
                                    element_id: $element_id})
SET element.logical_id = $logical_id,
    element.name = $name,
    element.kind = $kind,
    element.identity_basis = $identity_basis,
    element.size = $size,
    element.size_unit = $size_unit,
    element.confidence = $confidence,
    element.evidence_json = $evidence_json,
    element.analysis_id = $analysis_id
MERGE (snapshot)-[:CONTAINS]->(element)
"""

MERGE_RELATIONSHIP = """
MATCH (source:ArchitectureElement {repository_id: $repository_id,
                                   snapshot_id: $snapshot_id,
                                   element_id: $source_id})
MATCH (target:ArchitectureElement {repository_id: $repository_id,
                                   snapshot_id: $snapshot_id,
                                   element_id: $target_id})
MERGE (source)-[dependency:ARCHITECTURE_DEPENDENCY {relationship_id: $relationship_id}]->
      (target)
SET dependency.kind = $kind,
    dependency.confirmed_by_source = $confirmed_by_source,
    dependency.evidence_json = $evidence_json,
    dependency.evidence_types = $evidence_types,
    dependency.analysis_id = $analysis_id
"""

SWEEP_STALE_RELATIONSHIPS = """
MATCH (source:ArchitectureElement {repository_id: $repository_id,
                                   snapshot_id: $snapshot_id})
      -[dependency:ARCHITECTURE_DEPENDENCY]->(:ArchitectureElement)
WHERE NOT dependency.relationship_id IN $relationship_ids
DELETE dependency
"""

SWEEP_STALE_ELEMENTS = """
MATCH (snapshot:ArchitectureSnapshot {repository_id: $repository_id,
                                      snapshot_id: $snapshot_id})
      -[:CONTAINS]->(element:ArchitectureElement)
WHERE NOT element.element_id IN $element_ids
DETACH DELETE element
"""

CLEAR_PRECEDENCE = """
MATCH (snapshot:ArchitectureSnapshot {repository_id: $repository_id,
                                      snapshot_id: $snapshot_id})
      -[previous:PRECEDED_BY]->(:ArchitectureSnapshot)
DELETE previous
"""

LINK_PRECEDENCE = """
MATCH (snapshot:ArchitectureSnapshot {repository_id: $repository_id,
                                      snapshot_id: $snapshot_id})
MATCH (earlier:ArchitectureSnapshot {repository_id: $repository_id})
WHERE earlier.snapshot_id <> $snapshot_id
  AND (earlier.order_timestamp < snapshot.order_timestamp
       OR (earlier.order_timestamp = snapshot.order_timestamp
           AND earlier.snapshot_id < snapshot.snapshot_id))
WITH snapshot, earlier
ORDER BY earlier.order_timestamp DESC, earlier.snapshot_id DESC
LIMIT 1
MERGE (snapshot)-[:PRECEDED_BY]->(earlier)
"""

READ_SNAPSHOT = """
MATCH (snapshot:ArchitectureSnapshot {repository_id: $repository_id,
                                      snapshot_id: $snapshot_id})
RETURN snapshot
"""

READ_ELEMENTS = """
MATCH (:ArchitectureSnapshot {repository_id: $repository_id,
                              snapshot_id: $snapshot_id})
      -[:CONTAINS]->(element:ArchitectureElement)
RETURN element
ORDER BY element.element_id
"""

READ_RELATIONSHIPS = """
MATCH (source:ArchitectureElement {repository_id: $repository_id,
                                   snapshot_id: $snapshot_id})
      -[dependency:ARCHITECTURE_DEPENDENCY]->
      (target:ArchitectureElement {repository_id: $repository_id,
                                   snapshot_id: $snapshot_id})
RETURN source.element_id AS source_id,
       target.element_id AS target_id,
       dependency
ORDER BY dependency.relationship_id
"""

READ_HISTORY = """
MATCH (snapshot:ArchitectureSnapshot {repository_id: $repository_id})
RETURN snapshot
ORDER BY snapshot.order_timestamp ASC, snapshot.snapshot_id ASC
"""


class Neo4jArchitectureSnapshotStore:
    """Stores and reads version-scoped architecture snapshots in Neo4j."""

    def __init__(self, session_factory) -> None:
        """Bind to something that yields a session per operation."""

        self._session_factory = session_factory
        self._prepared = False

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    def publish(self, snapshot: ArchitectureSnapshot) -> str:
        """Persist the snapshot, replacing only its own contents."""

        with self._session_factory() as session:
            self._prepare(session)
            keys = {
                "repository_id": snapshot.repository_id,
                "snapshot_id": snapshot.snapshot_id,
            }

            session.run(
                MERGE_SNAPSHOT,
                **keys,
                schema_version=SNAPSHOT_SCHEMA_VERSION,
                release_id=snapshot.release.release_id,
                release_tag=snapshot.release.release_tag,
                repository_url=snapshot.release.repository_url,
                branch_name=snapshot.release.branch_name,
                commit_sha=snapshot.release.commit_sha,
                release_date=_iso(snapshot.release.release_date),
                release_date_source=snapshot.release.release_date_source,
                commit_date=_iso(snapshot.release.commit_date),
                status=snapshot.status.value,
                order_timestamp=_iso(snapshot.order_timestamp),
                order_source=snapshot.order_source.value,
                analysis_id=snapshot.run.analysis_id,
                analysis_timestamp=_iso(snapshot.run.analysis_timestamp),
                configuration_key=snapshot.run.configuration_key,
                element_count=snapshot.element_count,
                relationship_count=snapshot.relationship_count,
                unresolved_json=_json(
                    [item.to_dict() for item in snapshot.unresolved]
                ),
                diagnostics_json=_json(list(snapshot.diagnostics)),
                missing_inputs=list(snapshot.missing_inputs),
                notes=list(snapshot.notes),
            )

            for element in snapshot.elements:
                session.run(
                    MERGE_ELEMENT,
                    **keys,
                    element_id=element.id,
                    logical_id=element.logical_id,
                    name=element.name,
                    kind=element.kind,
                    identity_basis=element.identity_basis.value,
                    size=element.size,
                    size_unit=element.size_unit,
                    confidence=element.confidence,
                    evidence_json=_json(
                        [item.to_dict() for item in element.evidence]
                    ),
                    analysis_id=snapshot.run.analysis_id,
                )

            for relationship in snapshot.relationships:
                session.run(
                    MERGE_RELATIONSHIP,
                    **keys,
                    relationship_id=relationship.id,
                    source_id=relationship.source_id,
                    target_id=relationship.target_id,
                    kind=relationship.kind,
                    confirmed_by_source=relationship.confirmed_by_source,
                    evidence_json=_json(
                        [item.to_dict() for item in relationship.evidence]
                    ),
                    evidence_types=sorted(
                        {item.type for item in relationship.evidence}
                    ),
                    analysis_id=snapshot.run.analysis_id,
                )

            # Run last: a reader sees the previous shape or the new one.
            session.run(
                SWEEP_STALE_RELATIONSHIPS,
                **keys,
                relationship_ids=[item.id for item in snapshot.relationships],
            )
            session.run(
                SWEEP_STALE_ELEMENTS,
                **keys,
                element_ids=[item.id for item in snapshot.elements],
            )
            session.run(CLEAR_PRECEDENCE, **keys)
            session.run(LINK_PRECEDENCE, **keys)

        return f"neo4j://{snapshot.repository_id}/{snapshot.snapshot_id}"

    def _prepare(self, session) -> None:
        """Create the constraints once per store instance."""

        if self._prepared:
            return

        for statement in CONSTRAINTS:
            session.run(statement)

        self._prepared = True

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def read(
        self, repository_id: str, snapshot_id: str
    ) -> ArchitectureSnapshot | None:
        """Return one stored snapshot, or None when it is not there."""

        with self._session_factory() as session:
            record = session.run(
                READ_SNAPSHOT,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
            ).single()

            if record is None:
                return None

            properties = dict(record["snapshot"])
            elements = [
                _element_from(dict(item["element"]))
                for item in session.run(
                    READ_ELEMENTS,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                )
            ]
            relationships = [
                _relationship_from(dict(item["dependency"]), item)
                for item in session.run(
                    READ_RELATIONSHIPS,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                )
            ]

        return _snapshot_from(properties, elements, relationships)

    def history(self, repository_id: str) -> list[SnapshotSummary]:
        """Return every snapshot of a repository, oldest first."""

        with self._session_factory() as session:
            records = list(
                session.run(READ_HISTORY, repository_id=repository_id)
            )

        return [_summary_from(dict(record["snapshot"])) for record in records]


# --------------------------------------------------------------------------- #
# Serialisation helpers
# --------------------------------------------------------------------------- #


def _json(value) -> str:
    """Serialise a property that Neo4j cannot store as nested maps."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load_json(value, default):
    """Read a JSON property, falling back to a default when it is absent."""

    if not value:
        return default

    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _iso(value: datetime | None) -> str | None:
    """Store every timestamp as one comparable UTC ISO 8601 string."""

    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()

    return value.astimezone(UTC).isoformat()


def _datetime(value) -> datetime | None:
    """Read a stored timestamp."""

    return datetime.fromisoformat(value) if value else None


def _element_from(properties: dict) -> SnapshotElement:
    """Rebuild one element from its stored properties."""

    return SnapshotElement(
        id=properties["element_id"],
        name=properties.get("name") or "",
        kind=properties.get("kind") or "unknown",
        identity_basis=IdentityBasis(
            properties.get("identity_basis") or IdentityBasis.UNASSIGNED.value
        ),
        logical_id=properties.get("logical_id"),
        size=properties.get("size"),
        size_unit=properties.get("size_unit"),
        confidence=properties.get("confidence"),
        evidence=tuple(
            _evidence_from(item)
            for item in _load_json(properties.get("evidence_json"), [])
        ),
    )


def _relationship_from(
    properties: dict, record
) -> SnapshotRelationship:
    """Rebuild one relationship from its stored properties."""

    return SnapshotRelationship(
        id=properties["relationship_id"],
        source_id=record["source_id"],
        target_id=record["target_id"],
        kind=properties.get("kind") or "service_dependency",
        confirmed_by_source=bool(properties.get("confirmed_by_source")),
        evidence=tuple(
            _evidence_from(item)
            for item in _load_json(properties.get("evidence_json"), [])
        ),
    )


def _evidence_from(item: dict) -> SnapshotEvidence:
    """Rebuild one evidence entry."""

    return SnapshotEvidence(
        stage=item.get("stage") or "",
        type=item.get("type") or "",
        declared=bool(item.get("declared")),
        count=int(item.get("count") or 1),
        references=tuple(item.get("references") or ()),
    )


def _snapshot_from(
    properties: dict,
    elements: list[SnapshotElement],
    relationships: list[SnapshotRelationship],
) -> ArchitectureSnapshot:
    """Rebuild a snapshot from its stored node and the nodes it owns."""

    return ArchitectureSnapshot(
        snapshot_id=properties["snapshot_id"],
        status=SnapshotStatus(properties.get("status") or "incomplete"),
        release=ReleaseMetadata(
            repository_id=properties["repository_id"],
            commit_sha=properties.get("commit_sha") or "",
            repository_url=properties.get("repository_url"),
            release_tag=properties.get("release_tag"),
            release_date=_datetime(properties.get("release_date")),
            release_date_source=properties.get("release_date_source"),
            commit_date=_datetime(properties.get("commit_date")),
            branch_name=properties.get("branch_name"),
        ),
        run=AnalysisRun(
            analysis_id=properties.get("analysis_id") or "",
            analysis_timestamp=_datetime(properties.get("analysis_timestamp")),
            configuration_key=properties.get("configuration_key") or "",
            executed_by="architecture_recovery",
        ),
        order_timestamp=_datetime(properties.get("order_timestamp")),
        order_source=OrderSource(
            properties.get("order_source") or OrderSource.ANALYSIS_TIMESTAMP.value
        ),
        elements=tuple(elements),
        relationships=tuple(relationships),
        unresolved=tuple(
            SnapshotUnresolved(
                stage=item.get("stage") or "",
                status=item.get("status") or "",
                reference=item.get("reference") or "",
                reason=item.get("reason") or "",
            )
            for item in _load_json(properties.get("unresolved_json"), [])
        ),
        diagnostics=tuple(_load_json(properties.get("diagnostics_json"), [])),
        missing_inputs=tuple(properties.get("missing_inputs") or ()),
        notes=tuple(properties.get("notes") or ()),
    )


def _summary_from(properties: dict) -> SnapshotSummary:
    """Rebuild one history row."""

    return SnapshotSummary(
        snapshot_id=properties["snapshot_id"],
        repository_id=properties["repository_id"],
        release_id=properties.get("release_id") or "",
        release_tag=properties.get("release_tag"),
        commit_sha=properties.get("commit_sha") or "",
        status=SnapshotStatus(properties.get("status") or "incomplete"),
        order_timestamp=_datetime(properties.get("order_timestamp")),
        order_source=OrderSource(
            properties.get("order_source") or OrderSource.ANALYSIS_TIMESTAMP.value
        ),
        element_count=int(properties.get("element_count") or 0),
        relationship_count=int(properties.get("relationship_count") or 0),
        analysis_id=properties.get("analysis_id") or "",
        analysis_timestamp=_datetime(properties.get("analysis_timestamp")),
    )


__all__ = ["Neo4jArchitectureSnapshotStore"]
