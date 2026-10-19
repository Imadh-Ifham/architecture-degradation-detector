"""The validated graph, projected into the graph store.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    The `GraphProjection` the component writes through. A view of the
    published document, rebuilt on every run.

    **What this exists for, since the file already holds the graph.** Two
    questions a file cannot answer cheaply: *this one element across every
    release*, and *what changed between these two releases*. In a document
    both mean loading every release and writing code; here both are one query,
    because following a connection is what the storage is for. That is also
    exactly what degradation detection is.

    **Why a re-run replaces its own edges rather than adding to them.** Two
    runs of one release leave two sets of relationships on one pair of nodes.
    Nothing errors, the graph still draws, and every count anybody reads off
    it is doubled - which is worse than a missing count because it looks like
    data. So the write merges forward and sweeps the previous run's edges
    last: a reader sees the old graph or the new one, never neither. The same
    property as the atomic rename on the file, for the same reason.

    **Why elements are per release.** A validation rollup is a property of a
    release, and one node reused across releases would either carry the last
    run's numbers or need them moved onto a relationship. Comparing two
    releases is then a comparison of two subgraphs.

    **And why history is followed by `canonical` rather than by the element
    id.** Recovery's ids are stable across the releases on record - checked,
    eleven of eleven - but the derivation belongs to another component, is
    undocumented, and is not a hash of the name or of the path. Stable for a
    reason nobody here can state is a coincidence rather than a contract, and
    a service that moves directory would silently start a new history.
"""

from app.domain.validated_architecture import ValidatedArchitectureGraph

CONSTRAINTS = (
    """
    CREATE CONSTRAINT release_key IF NOT EXISTS
    FOR (r:Release) REQUIRE (r.repository_id, r.release_id) IS UNIQUE
    """,
    """
    CREATE CONSTRAINT element_key IF NOT EXISTS
    FOR (e:Element) REQUIRE (e.repository_id, e.release_id, e.element_id) IS UNIQUE
    """,
    """
    CREATE INDEX element_canonical IF NOT EXISTS
    FOR (e:Element) ON (e.repository_id, e.canonical)
    """,
    """
    CREATE INDEX edge_bucket IF NOT EXISTS
    FOR ()-[d:VALIDATED_DEPENDENCY]-() ON (d.bucket)
    """,
)
"""Created before the first write, and idempotent.

A graph with no constraints grows duplicates in silence - the same release
merged twice as two nodes, and every traversal thereafter answering twice.
The `canonical` index is what makes the cross-release query a seek rather
than a scan over every element of every release.

**`IS UNIQUE` and not `IS NODE KEY`, because the team runs Community
edition.** This was written as `IS NODE KEY` and refused outright:
*Node Key constraint requires Neo4j Enterprise Edition*, on the database the
project actually has. Composite uniqueness is accepted there and gives the
guarantee that matters here, which is that one release and one element of it
exist once. What it does not add is the existence half - a node key also
requires the properties to be present - and nothing needs it: every node is
written by the `MERGE` below, which sets all three key properties in the same
statement, so a node missing one cannot be created by this code at all.
"""

MERGE_RELEASE = """
MERGE (repository:Repository {repository_id: $repository_id})
MERGE (release:Release {repository_id: $repository_id, release_id: $release_id})
SET release.release_sort_key = $release_sort_key,
    release.released_at = $released_at,
    release.architecture_style = $architecture_style,
    release.validation_confidence = $validation_confidence,
    release.run_id = $run_id
MERGE (repository)-[:HAS_RELEASE]->(release)
"""

MERGE_ELEMENT = """
MATCH (release:Release {repository_id: $repository_id, release_id: $release_id})
MERGE (element:Element {repository_id: $repository_id, release_id: $release_id,
                        element_id: $element_id})
SET element.canonical = $canonical,
    element.name = $name,
    element.kind = $kind,
    element.size = $size,
    element.size_unit = $size_unit,
    element.confirmed = $confirmed,
    element.contradicted = $contradicted,
    element.uncovered = $uncovered,
    element.needs_review = $needs_review,
    element.run_id = $run_id
MERGE (release)-[:CONTAINS]->(element)
"""

MERGE_DEPENDENCY = """
MATCH (source:Element {repository_id: $repository_id, release_id: $release_id,
                       element_id: $source_id})
MATCH (target:Element {repository_id: $repository_id, release_id: $release_id,
                       element_id: $target_id})
MERGE (source)-[dependency:VALIDATED_DEPENDENCY {fact_id: $fact_id}]->(target)
SET dependency.relationship = $relationship,
    dependency.bucket = $bucket,
    dependency.confidence = $confidence,
    dependency.governing_decision = $governing_decision,
    dependency.source_tier = $source_tier,
    dependency.evidence_refs = $evidence_refs,
    dependency.model_calls = $model_calls,
    dependency.produced_by = $produced_by,
    dependency.verification_outcome = $verification_outcome,
    dependency.arbiter_agreement = $arbiter_agreement,
    dependency.run_id = $run_id
"""

SWEEP_STALE_EDGES = """
MATCH (source:Element {repository_id: $repository_id, release_id: $release_id})
      -[dependency:VALIDATED_DEPENDENCY]->(:Element)
WHERE dependency.run_id <> $run_id
DELETE dependency
"""
"""Run last, so a reader sees the old graph or the new one and never neither.

Deleting the release's subgraph first and rebuilding it would leave a window
where the release has no dependencies - which is a valid-looking answer rather
than an error, and the one thing this projection must never produce.
"""

LINK_PREVIOUS_RELEASE = """
MATCH (release:Release {repository_id: $repository_id, release_id: $release_id})
MATCH (earlier:Release {repository_id: $repository_id})
WHERE earlier.release_sort_key < release.release_sort_key
WITH release, earlier
ORDER BY earlier.release_sort_key DESC
LIMIT 1
MERGE (release)-[:PRECEDED_BY]->(earlier)
"""
"""Ordered by the sort key and never by the tag.

Compared as text `v0.10.0` sorts before `v0.9.0`, which would chain the
releases backwards - and a backwards chain is how a superseded decision ends
up governing the release that replaced it.
"""


class Neo4jGraphProjection:
    """Projects a published document into Neo4j."""

    def __init__(self, session_factory) -> None:
        """Bind to something that yields a session per write.

        A factory rather than a session, because a projection outlives any one
        session and a session held open across runs is a transaction nobody
        closed.
        """

        self._session_factory = session_factory
        self._prepared = False

    def project(self, document: ValidatedArchitectureGraph) -> None:
        """Merge this release's subgraph and sweep the previous run's edges."""

        with self._session_factory() as session:
            if not self._prepared:
                for statement in CONSTRAINTS:
                    session.run(statement)
                self._prepared = True

            keys = {
                "repository_id": document.repository_id,
                "release_id": document.release_id,
                "run_id": document.stamp.run_id,
            }

            session.run(
                MERGE_RELEASE,
                **keys,
                release_sort_key=_sortable(document.release_order_key),
                released_at=(
                    document.released_at.isoformat() if document.released_at else None
                ),
                architecture_style=document.architecture_style,
                validation_confidence=document.validation_confidence,
            )

            for node in document.nodes:
                session.run(
                    MERGE_ELEMENT,
                    **keys,
                    element_id=node.id,
                    canonical=node.canonical or node.name,
                    name=node.name,
                    kind=str(node.kind),
                    size=node.size,
                    size_unit=node.size_unit,
                    confirmed=node.rollup.confirmed,
                    contradicted=node.rollup.contradicted,
                    uncovered=node.rollup.uncovered,
                    needs_review=node.rollup.needs_review,
                )

            for edge in document.edges:
                session.run(
                    MERGE_DEPENDENCY,
                    **keys,
                    fact_id=edge.fact_id,
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    relationship=str(edge.relationship),
                    bucket=str(edge.bucket),
                    confidence=edge.confidence,
                    governing_decision=edge.governing_decision,
                    source_tier=str(edge.source_tier) if edge.source_tier else None,
                    evidence_refs=list(edge.evidence_refs),
                    model_calls=edge.model_calls,
                    produced_by=edge.produced_by or None,
                    verification_outcome=edge.verification_outcome,
                    arbiter_agreement=edge.arbiter_agreement,
                )

            session.run(SWEEP_STALE_EDGES, **keys)
            session.run(
                LINK_PREVIOUS_RELEASE,
                repository_id=document.repository_id,
                release_id=document.release_id,
            )


def _sortable(order_key: tuple[int, ...]) -> str:
    """The release order key as one comparable string.

    Zero-padded so a string comparison in Cypher orders the releases the way
    the numeric tuple does. Stored as text rather than a list because Neo4j
    compares lists element-wise only in some positions, and the whole point of
    the key is that one comparison is enough.
    """

    return ".".join(f"{part:05d}" for part in order_key)
