"""The snapshot store against a real Neo4j.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Proves the persistence guarantees on the store that is the source of truth:
    two releases keep two snapshots, a rerun replaces only its own subgraph, a
    moved tag leaves the earlier commit intact, repositories stay isolated, and
    history orders chronologically.

    Skips when the graph store is not reachable, which is the normal state of a
    laptop checkout. Everything runs under one repository id that is removed
    afterwards, so a developer's own graph is left as it was.
"""

from datetime import UTC, datetime

import pytest

from app.components.architecture_recovery.graph_construction import SnapshotBuilder
from app.components.architecture_recovery.graph_construction.builder import (
    CONFIGURATION_KEY,
)
from app.components.architecture_recovery.graph_construction.inputs import (
    ComponentRecord,
    DependencyRecord,
    FindingRecord,
    SnapshotInputs,
)
from app.domain.architecture_snapshot import (
    AnalysisRun,
    OrderSource,
    ReleaseMetadata,
    SnapshotStatus,
)

pytestmark = pytest.mark.integration

REPOSITORY = "graph-construction-test"
OTHER_REPOSITORY = "graph-construction-test-other"

V1 = datetime(2025, 1, 15, 9, 0, tzinfo=UTC)
V2 = datetime(2025, 8, 10, 9, 0, tzinfo=UTC)


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
            "MATCH (n) WHERE n.repository_id IN [$repository_id, $other] "
            "DETACH DELETE n",
            repository_id=REPOSITORY,
            other=OTHER_REPOSITORY,
        )


def store(sessions):
    from app.infrastructure.neo4j.architecture_snapshot_store import (
        Neo4jArchitectureSnapshotStore,
    )

    return Neo4jArchitectureSnapshotStore(sessions)


def run(analysis_id: str = "analysis:test") -> AnalysisRun:
    return AnalysisRun(
        analysis_id=analysis_id,
        analysis_timestamp=V1,
        configuration_key=CONFIGURATION_KEY,
    )


def release(
    *,
    repository_id: str = REPOSITORY,
    commit: str = "a" * 40,
    tag: str | None = "v1.0.0",
    released: datetime | None = V1,
    committed: datetime | None = None,
) -> ReleaseMetadata:
    return ReleaseMetadata(
        repository_id=repository_id,
        commit_sha=commit,
        release_tag=tag,
        release_date=released,
        commit_date=committed,
        branch_name="main",
    )


def inputs(
    *,
    with_cart: bool = False,
    confirmed_by_source: bool = True,
) -> SnapshotInputs:
    components = [
        ComponentRecord("component:a", "frontend", "service", "direct", 2),
        ComponentRecord("component:b", "checkout", "service", "direct", 1),
    ]
    dependencies = [
        DependencyRecord("dep:1", "component:a", "component:b", "configured_endpoint")
    ]
    findings = (
        [FindingRecord("src:1", "component:a", "component:b", "grpc_service_call")]
        if confirmed_by_source
        else []
    )

    if with_cart:
        components.append(
            ComponentRecord("component:c", "cart", "service", "direct", 1)
        )
        dependencies.append(
            DependencyRecord("dep:2", "component:a", "component:c", "configured_endpoint")
        )

    return SnapshotInputs(
        components=tuple(components),
        dependencies=tuple(dependencies),
        findings=tuple(findings),
    )


def build(
    release_metadata: ReleaseMetadata,
    snapshot_inputs: SnapshotInputs,
    run_id: str = "analysis:test",
):
    return SnapshotBuilder().build(
        release=release_metadata,
        run=run(run_id),
        inputs=snapshot_inputs,
    )


def test_two_releases_are_stored_and_read_independently(sessions) -> None:
    publisher = store(sessions)

    first = build(release(commit="a" * 40, tag="v1.0.0"), inputs())
    second = build(
        release(commit="b" * 40, tag="v1.2.0", released=V2),
        inputs(with_cart=True),
    )

    publisher.publish(first)
    publisher.publish(second)

    stored_first = publisher.read(REPOSITORY, first.snapshot_id)
    stored_second = publisher.read(REPOSITORY, second.snapshot_id)

    assert stored_first is not None and stored_second is not None
    assert {element.name for element in stored_first.elements} == {"frontend", "checkout"}
    assert {element.name for element in stored_second.elements} == {
        "frontend",
        "checkout",
        "cart",
    }
    assert len(stored_first.relationships) == 1
    assert len(stored_second.relationships) == 2


def test_rerunning_a_revision_does_not_duplicate_its_subgraph(sessions) -> None:
    publisher = store(sessions)
    snapshot = build(release(), inputs())

    publisher.publish(snapshot)
    publisher.publish(snapshot)

    stored = publisher.read(REPOSITORY, snapshot.snapshot_id)

    assert stored is not None
    assert len(stored.elements) == 2
    assert len(stored.relationships) == 1

    with sessions() as session:
        element_count = session.run(
            "MATCH (e:ArchitectureElement {repository_id: $repository_id, "
            "snapshot_id: $snapshot_id}) RETURN count(e) AS count",
            repository_id=REPOSITORY,
            snapshot_id=snapshot.snapshot_id,
        ).single()["count"]
        edge_count = session.run(
            "MATCH (:ArchitectureElement {repository_id: $repository_id, "
            "snapshot_id: $snapshot_id})-[d:ARCHITECTURE_DEPENDENCY]->() "
            "RETURN count(d) AS count",
            repository_id=REPOSITORY,
            snapshot_id=snapshot.snapshot_id,
        ).single()["count"]
        snapshot_count = session.run(
            "MATCH (s:ArchitectureSnapshot {repository_id: $repository_id}) "
            "RETURN count(s) AS count",
            repository_id=REPOSITORY,
        ).single()["count"]

    assert element_count == 2
    assert edge_count == 1
    assert snapshot_count == 1


def test_republishing_a_snapshot_sweeps_what_it_no_longer_has(sessions) -> None:
    publisher = store(sessions)
    snapshot = build(release(), inputs(with_cart=True))
    publisher.publish(snapshot)

    smaller = build(release(), inputs(with_cart=False))
    assert smaller.snapshot_id == snapshot.snapshot_id
    publisher.publish(smaller)

    stored = publisher.read(REPOSITORY, snapshot.snapshot_id)

    assert stored is not None
    assert {element.name for element in stored.elements} == {"frontend", "checkout"}
    assert len(stored.relationships) == 1


def test_a_moved_tag_leaves_the_earlier_commit_intact(sessions) -> None:
    publisher = store(sessions)

    original = build(release(commit="a" * 40, tag="v1.0.0"), inputs())
    moved = build(release(commit="c" * 40, tag="v1.0.0", released=V2), inputs())

    publisher.publish(original)
    publisher.publish(moved)

    assert original.snapshot_id != moved.snapshot_id

    stored = publisher.read(REPOSITORY, original.snapshot_id)

    assert stored is not None
    assert stored.release.commit_sha == "a" * 40
    assert stored.release.release_tag == "v1.0.0"


def test_repositories_do_not_see_each_other(sessions) -> None:
    publisher = store(sessions)

    shop = build(release(), inputs())
    warehouse = build(release(repository_id=OTHER_REPOSITORY), inputs())

    publisher.publish(shop)
    publisher.publish(warehouse)

    assert len(publisher.history(REPOSITORY)) == 1
    assert len(publisher.history(OTHER_REPOSITORY)) == 1
    assert publisher.read(REPOSITORY, warehouse.snapshot_id) is None


def test_history_is_ordered_chronologically_with_its_source(sessions) -> None:
    publisher = store(sessions)

    publisher.publish(
        build(
            release(commit="b" * 40, tag="v1.2.0", released=V2),
            inputs(with_cart=True),
        )
    )
    publisher.publish(
        build(
            release(
                commit="a" * 40,
                tag=None,
                released=None,
                committed=V1,
            ),
            inputs(),
        )
    )

    history = publisher.history(REPOSITORY)

    assert len(history) == 2
    assert history[0].release_tag is None
    assert history[1].release_tag == "v1.2.0"
    assert history[0].order_source is OrderSource.COMMIT_DATE
    assert history[1].order_source is OrderSource.RELEASE_DATE


def test_a_failed_snapshot_is_stored_as_failed(sessions) -> None:
    publisher = store(sessions)
    failed = SnapshotBuilder().build_failed(
        release=release(commit="d" * 40, tag="v1.3.0"),
        run=run("analysis:failed"),
        error="clone disappeared",
    )

    publisher.publish(failed)
    stored = publisher.read(REPOSITORY, failed.snapshot_id)

    assert stored is not None
    assert stored.status is SnapshotStatus.FAILED
    assert stored.elements == ()
    assert any("clone disappeared" in item for item in stored.diagnostics)


def test_an_element_can_be_followed_across_releases(sessions) -> None:
    publisher = store(sessions)

    publisher.publish(build(release(commit="a" * 40), inputs()))
    publisher.publish(
        build(release(commit="b" * 40, tag="v1.1.0", released=V2), inputs(with_cart=True))
    )

    with sessions() as session:
        rows = list(
            session.run(
                "MATCH (e:ArchitectureElement {repository_id: $repository_id}) "
                "WHERE e.logical_id = 'frontend' "
                "RETURN e.snapshot_id AS snapshot_id, e.size AS size "
                "ORDER BY snapshot_id",
                repository_id=REPOSITORY,
            )
        )
        frontend_size = session.run(
            "MATCH (:ArchitectureSnapshot {repository_id: $repository_id, "
            "status: 'complete'})-[:CONTAINS]->"
            "(e:ArchitectureElement {logical_id: 'frontend'}) "
            "RETURN count(e) AS count",
            repository_id=REPOSITORY,
        ).single()["count"]

    assert len(rows) == 2
    assert {row["size"] for row in rows} == {2.0}
    assert frontend_size == 2


def test_deleting_a_repository_removes_every_snapshot_it_owned(sessions) -> None:
    publisher = store(sessions)

    publisher.publish(build(release(commit="a" * 40), inputs()))
    publisher.publish(
        build(release(commit="b" * 40, tag="v1.1.0", released=V2), inputs(with_cart=True))
    )

    assert publisher.delete_repository(REPOSITORY) == 2

    with sessions() as session:
        snapshots = session.run(
            "MATCH (s:ArchitectureSnapshot {repository_id: $repository_id}) "
            "RETURN count(s) AS count",
            repository_id=REPOSITORY,
        ).single()["count"]
        elements = session.run(
            "MATCH (e:ArchitectureElement {repository_id: $repository_id}) "
            "RETURN count(e) AS count",
            repository_id=REPOSITORY,
        ).single()["count"]
        anchors = session.run(
            "MATCH (r:Repository {repository_id: $repository_id}) "
            "RETURN count(r) AS count",
            repository_id=REPOSITORY,
        ).single()["count"]

    assert snapshots == 0
    # An element left behind is unreachable from any snapshot and no query
    # ever collects it, so it has to go with the snapshot that owned it.
    assert elements == 0
    assert anchors == 0
    assert publisher.history(REPOSITORY) == []


def test_deleting_one_snapshot_keeps_the_others_and_relinks_the_chain(
    sessions,
) -> None:
    publisher = store(sessions)

    first = build(release(commit="a" * 40), inputs())
    middle = build(release(commit="b" * 40, tag="v1.1.0", released=V2), inputs())
    last = build(release(commit="c" * 40, tag="v1.2.0", released=V2), inputs())

    for snapshot in (first, middle, last):
        publisher.publish(snapshot)

    assert publisher.delete_snapshot(REPOSITORY, middle.snapshot_id) is True

    remaining = {item.release_tag for item in publisher.history(REPOSITORY)}

    assert remaining == {"v1.0.0", "v1.2.0"}

    with sessions() as session:
        chain = list(
            session.run(
                "MATCH (later:ArchitectureSnapshot {repository_id: $repository_id})"
                "-[:PRECEDED_BY]->(earlier:ArchitectureSnapshot) "
                "RETURN later.snapshot_id AS later, earlier.snapshot_id AS earlier",
                repository_id=REPOSITORY,
            )
        )

    # Deleting the middle of the chain detaches both of its links, so the
    # survivor has to be relinked or a chronology query silently skips a
    # release.
    assert {row["later"]: row["earlier"] for row in chain} == {
        last.snapshot_id: first.snapshot_id
    }


def test_deleting_a_snapshot_leaves_no_orphan_elements(sessions) -> None:
    publisher = store(sessions)

    snapshot = build(release(commit="a" * 40), inputs())
    publisher.publish(snapshot)

    publisher.delete_snapshot(REPOSITORY, snapshot.snapshot_id)

    with sessions() as session:
        elements = session.run(
            "MATCH (e:ArchitectureElement {repository_id: $repository_id}) "
            "RETURN count(e) AS count",
            repository_id=REPOSITORY,
        ).single()["count"]

    assert elements == 0


def test_deleting_a_missing_snapshot_reports_nothing_to_delete(sessions) -> None:
    publisher = store(sessions)

    assert publisher.delete_snapshot(REPOSITORY, "snapshot:not-there") is False
    assert publisher.delete_repository(REPOSITORY) == 0


def test_deleting_a_repository_leaves_another_repository_alone(sessions) -> None:
    publisher = store(sessions)

    publisher.publish(build(release(commit="a" * 40), inputs()))
    publisher.publish(
        build(release(repository_id=OTHER_REPOSITORY, commit="d" * 40), inputs())
    )

    publisher.delete_repository(REPOSITORY)

    assert len(publisher.history(OTHER_REPOSITORY)) == 1
    assert publisher.history(REPOSITORY) == []


def test_deleting_recovery_history_keeps_a_shared_repository_anchor(sessions) -> None:
    """The validated projection hangs its own releases off the same node.

    Removing recovery's history must not take the anchor with it while another
    component still points at it, or that component's graph is orphaned.
    """

    publisher = store(sessions)
    publisher.publish(build(release(commit="a" * 40), inputs()))

    with sessions() as session:
        session.run(
            "MERGE (repository:Repository {repository_id: $repository_id}) "
            "MERGE (release:Release {repository_id: $repository_id, "
            "release_id: 'v1.0.0'}) "
            "MERGE (repository)-[:HAS_RELEASE]->(release)",
            repository_id=REPOSITORY,
        )

    publisher.delete_repository(REPOSITORY)

    with sessions() as session:
        anchors = session.run(
            "MATCH (r:Repository {repository_id: $repository_id}) "
            "RETURN count(r) AS count",
            repository_id=REPOSITORY,
        ).single()["count"]

    assert anchors == 1
