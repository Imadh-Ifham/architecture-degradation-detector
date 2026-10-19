"""The projection against a real Neo4j (Docker: ``docker compose up -d``).

Skips when the graph store is not reachable, which is the normal state on a laptop and the reason
the component treats a failed projection as a warning rather than a failed run.

What is asserted here is not that the write happened - the fake-session tests in
``test_graph_publishing.py`` cover the Cypher - but that the three queries the shape exists for
return what they are supposed to. A graph model is only right if the questions it was built for
are cheap, and those questions are: the architecture at one release, one element through time,
and what changed between two releases.

Everything runs under one repository id that is removed afterwards, so a developer's own graph is
left as it was.
"""

import datetime as dt

import pytest

from app.domain.validated_architecture import (
    RunMode,
    ValidatedArchitectureGraph,
    ValidatedEdge,
    ValidatedNode,
    ValidationBucket,
    ValidationRollup,
    ValidationRunStamp,
)

pytestmark = pytest.mark.integration

REPOSITORY = "c2-projection-test"
GENERATED_AT = dt.datetime(2026, 10, 19, tzinfo=dt.UTC)


@pytest.fixture
def sessions():
    """A session factory, or a skip when nothing answers."""

    try:
        from app.infrastructure.neo4j.database import driver
    except Exception as exc:  # settings come from .env
        pytest.skip(f"Neo4j settings unavailable: {exc}")

    try:
        with driver.session() as session:
            session.run("RETURN 1").single()
    except Exception as exc:
        pytest.skip(f"Neo4j is not reachable: {exc}")

    yield driver.session

    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.repository_id = $repository_id DETACH DELETE n",
            repository_id=REPOSITORY,
        )


def document(release: str, order: tuple[int, ...], run_id: str, bucket):
    """One release of a two-element system, validated."""

    return ValidatedArchitectureGraph(
        repository_id=REPOSITORY,
        release_id=release,
        architecture_style="microservices",
        nodes=(
            ValidatedNode(
                "component:a", "frontend", "service",
                ValidationRollup(confirmed=1 if bucket is ValidationBucket.CONFIRMED else 0,
                                 needs_review=0 if bucket is ValidationBucket.CONFIRMED else 1),
                canonical="frontend",
                size=1420.0,
                size_unit="loc",
            ),
            ValidatedNode(
                "component:b", "cartservice", "service", ValidationRollup(),
                canonical="cart",
            ),
        ),
        edges=(
            ValidatedEdge(
                fact_id=f"fact-{release}",
                source_id="component:a",
                target_id="component:b",
                relationship="communicates-with",
                bucket=bucket,
                confidence=0.85,
                governing_decision="rule-frontend-cartservice",
                evidence_refs=("rule-frontend-cartservice",),
                source_tier="tier_2_executable_config",
                model_calls=2,
                produced_by="model",
            ),
        ),
        stamp=ValidationRunStamp(
            run_id=run_id,
            generated_at=GENERATED_AT,
            mode=RunMode.RECONSTRUCTION,
            reasoner_model=None,
            verifier_model=None,
        ),
        validation_confidence=0.85,
        release_order_key=order,
    )


def projection(sessions):
    from app.infrastructure.neo4j.validated_graph_projection import (
        Neo4jGraphProjection,
    )

    return Neo4jGraphProjection(sessions)


class TestTheThreeQueriesTheShapeExistsFor:
    def test_the_architecture_at_one_release_is_one_hop(self, sessions):
        projection(sessions).project(
            document("v0.9.0", (0, 0, 9, 0, 0, 4, 0, 1, 0), "run-1",
                     ValidationBucket.CONFIRMED)
        )

        with sessions() as session:
            rows = session.run(
                """
                MATCH (r:Release {repository_id: $repository_id, release_id: $release_id})
                      -[:CONTAINS]->(e:Element)
                OPTIONAL MATCH (e)-[d:VALIDATED_DEPENDENCY]->(f:Element)
                RETURN e.canonical AS element, d.bucket AS bucket, f.canonical AS target
                ORDER BY element
                """,
                repository_id=REPOSITORY,
                release_id="v0.9.0",
            ).data()

        assert rows == [
            {"element": "cart", "bucket": None, "target": None},
            {"element": "frontend", "bucket": "confirmed", "target": "cart"},
        ]

    def test_one_element_through_time_is_ordered_by_the_key(self, sessions):
        """Followed by `canonical` and not by recovery's element id, and
        ordered by the sort key and never by the tag: compared as text
        `v0.10.0` sorts before `v0.9.0`."""

        store = projection(sessions)
        store.project(
            document("v0.9.0", (0, 0, 9, 0, 0, 4, 0, 1, 0), "run-1",
                     ValidationBucket.CONFIRMED)
        )
        store.project(
            document("v0.10.0", (0, 0, 10, 0, 0, 4, 0, 1, 0), "run-2",
                     ValidationBucket.NEEDS_REVIEW)
        )

        with sessions() as session:
            rows = session.run(
                """
                MATCH (e:Element {repository_id: $repository_id, canonical: $canonical})
                      <-[:CONTAINS]-(r:Release)
                RETURN r.release_id AS release, e.needs_review AS needs_review
                ORDER BY r.release_sort_key
                """,
                repository_id=REPOSITORY,
                canonical="frontend",
            ).data()

        assert rows == [
            {"release": "v0.9.0", "needs_review": 0},
            {"release": "v0.10.0", "needs_review": 1},
        ]

    def test_what_changed_between_two_releases(self, sessions):
        store = projection(sessions)
        store.project(
            document("v0.9.0", (0, 0, 9, 0, 0, 4, 0, 1, 0), "run-1",
                     ValidationBucket.CONFIRMED)
        )
        store.project(
            document("v0.10.0", (0, 0, 10, 0, 0, 4, 0, 1, 0), "run-2",
                     ValidationBucket.NEEDS_REVIEW)
        )

        with sessions() as session:
            rows = session.run(
                """
                MATCH (:Release {repository_id: $repository_id, release_id: $release_id})
                      -[:CONTAINS]->(s)-[d:VALIDATED_DEPENDENCY]->(t)
                RETURN s.canonical AS source, t.canonical AS target, d.bucket AS bucket
                """,
                repository_id=REPOSITORY,
                release_id="v0.10.0",
            ).data()

        assert rows == [
            {"source": "frontend", "target": "cart", "bucket": "needs_review"}
        ]

    def test_the_releases_are_chained_in_order(self, sessions):
        store = projection(sessions)
        store.project(
            document("v0.9.0", (0, 0, 9, 0, 0, 4, 0, 1, 0), "run-1",
                     ValidationBucket.CONFIRMED)
        )
        store.project(
            document("v0.10.0", (0, 0, 10, 0, 0, 4, 0, 1, 0), "run-2",
                     ValidationBucket.NEEDS_REVIEW)
        )

        with sessions() as session:
            rows = session.run(
                """
                MATCH (later:Release {repository_id: $repository_id})
                      -[:PRECEDED_BY]->(earlier:Release)
                RETURN later.release_id AS later, earlier.release_id AS earlier
                """,
                repository_id=REPOSITORY,
            ).data()

        assert rows == [{"later": "v0.10.0", "earlier": "v0.9.0"}]


class TestARerunReplacesItsOwnProjection:
    def test_two_runs_of_one_release_leave_one_set_of_edges(self, sessions):
        """Two runs leave two sets of relationships on one pair of nodes.
        Nothing errors, the graph still draws, and every count read off it is
        doubled - which is worse than a missing count because it looks like
        data."""

        store = projection(sessions)
        store.project(
            document("v0.9.0", (0, 0, 9, 0, 0, 4, 0, 1, 0), "run-1",
                     ValidationBucket.CONFIRMED)
        )
        store.project(
            document("v0.9.0", (0, 0, 9, 0, 0, 4, 0, 1, 0), "run-2",
                     ValidationBucket.NEEDS_REVIEW)
        )

        with sessions() as session:
            edges = session.run(
                """
                MATCH (:Element {repository_id: $repository_id, release_id: $release_id})
                      -[d:VALIDATED_DEPENDENCY]->()
                RETURN count(d) AS edges, collect(DISTINCT d.run_id) AS runs
                """,
                repository_id=REPOSITORY,
                release_id="v0.9.0",
            ).single()

        assert edges["edges"] == 1
        assert edges["runs"] == ["run-2"]

    def test_a_rerun_leaves_one_release_node_rather_than_two(self, sessions):
        """What the node key constraint is for. A graph with no constraints
        grows duplicates in silence, and every traversal then answers twice."""

        store = projection(sessions)
        for run_id in ("run-1", "run-2"):
            store.project(
                document("v0.9.0", (0, 0, 9, 0, 0, 4, 0, 1, 0), run_id,
                         ValidationBucket.CONFIRMED)
            )

        with sessions() as session:
            releases = session.run(
                """
                MATCH (r:Release {repository_id: $repository_id, release_id: $release_id})
                RETURN count(r) AS releases
                """,
                repository_id=REPOSITORY,
                release_id="v0.9.0",
            ).single()

        assert releases["releases"] == 1
