"""Reading recovery's architecture graph.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    The live input boundary: recovery's own snapshot, in this component's
    shape.

    The store is a fake built from the real domain dataclasses rather than a
    database, because what is being tested is the translation and the
    resolution, and both are pure. The one thing a real store would add -
    that Neo4j returns what it was given - is recovery's test to run and it
    already runs it.

    Two failures here are worth more than the rest put together. A service
    call that arrives as a dependency puts every communication rule out of
    reach silently, and a release that resolves to the wrong snapshot
    validates the wrong architecture while looking correct.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.architecture_snapshot import (
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
)
from app.domain.recovered_architecture import (
    DerivationMethod,
    ElementKind,
    EvidenceQuality,
)
from app.domain.validated_architecture import ReleaseDateSource
from app.infrastructure.recovery_gateway import (
    GraphContractError,
    GraphStoreReader,
    WorkspaceIndex,
    WorkspaceUnavailable,
)

REPOSITORY_KEY = "subject-abc123def456"
WORKSPACE_ID = "subject-abc123def456-v0-10-0"
RELEASE = "v0.10.0"
COMMIT = "98e60f5ee0b6aa11bbccddeeff00112233445566"
RELEASED = datetime(2024, 4, 23, tzinfo=UTC)


def metadata(release_tag: str = RELEASE, workspace_id: str = WORKSPACE_ID) -> dict:
    """One ingestion record, as recovery writes it beside a clone."""

    return {
        "id": workspace_id,
        "url": "https://example.invalid/subject",
        "branch": "main",
        "commit": COMMIT,
        "ingested_at": "2026-10-19T09:00:00+00:00",
        "repository_id": REPOSITORY_KEY,
        "release_tag": release_tag,
        "revision": release_tag,
        "release_date": RELEASED.isoformat(),
        "release_date_source": "tag",
        "commit_date": "2024-04-22T00:00:00+00:00",
    }


def workspace(root: Path, *records: dict) -> Path:
    """Write ingestion records into a workspace root."""

    for record in records:
        directory = root / record["id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "metadata.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

    return root


def evidence(stage: str, type_: str, declared: bool = True) -> SnapshotEvidence:
    return SnapshotEvidence(stage=stage, type=type_, declared=declared, count=1)


def snapshot(
    snapshot_id: str = "snapshot:68775e60",
    *,
    status: SnapshotStatus = SnapshotStatus.COMPLETE,
    order_source: OrderSource = OrderSource.RELEASE_DATE,
    relationships: tuple[SnapshotRelationship, ...] | None = None,
    unresolved=(),
) -> ArchitectureSnapshot:
    """One snapshot, in recovery's own shape."""

    elements = (
        SnapshotElement(
            id="component:frontend",
            name="frontend",
            kind="deployment_service",
            identity_basis=IdentityBasis.HEURISTIC,
            logical_id="frontend",
            size=71.0,
            size_unit="files",
            confidence="heuristic",
        ),
        SnapshotElement(
            id="component:cartservice",
            name="cartservice",
            kind="deployment_service",
            identity_basis=IdentityBasis.DIRECT,
            logical_id="cartservice",
            confidence="direct",
        ),
        SnapshotElement(
            id="component:redis-cart",
            name="redis-cart",
            kind="cache",
            identity_basis=IdentityBasis.DIRECT,
            logical_id="redis-cart",
            confidence="direct",
        ),
    )

    default = (
        SnapshotRelationship(
            id="dependency:1",
            source_id="component:frontend",
            target_id="component:cartservice",
            kind="service_dependency",
            confirmed_by_source=True,
            evidence=(
                evidence("dependency_resolution", "configured_endpoint"),
                evidence("source_code_analysis", "grpc_service_call"),
            ),
        ),
        SnapshotRelationship(
            id="dependency:2",
            source_id="component:cartservice",
            target_id="component:redis-cart",
            kind="infrastructure_dependency",
            evidence=(evidence("dependency_resolution", "infrastructure_dependency"),),
        ),
    )

    return ArchitectureSnapshot(
        snapshot_id=snapshot_id,
        status=status,
        release=ReleaseMetadata(
            repository_id=REPOSITORY_KEY,
            commit_sha=COMMIT,
            release_tag=RELEASE,
            release_date=RELEASED,
        ),
        run=AnalysisRun(
            analysis_id="analysis:1",
            analysis_timestamp=datetime(2026, 10, 19, tzinfo=UTC),
            configuration_key="cfg1",
        ),
        order_timestamp=RELEASED,
        order_source=order_source,
        elements=elements,
        relationships=default if relationships is None else relationships,
        unresolved=unresolved,
    )


def summary_of(item: ArchitectureSnapshot, when: datetime | None = None) -> SnapshotSummary:
    return SnapshotSummary(
        snapshot_id=item.snapshot_id,
        repository_id=item.release.repository_id,
        release_id=item.release.release_id,
        release_tag=item.release.release_tag,
        commit_sha=item.release.commit_sha,
        status=item.status,
        order_timestamp=item.order_timestamp,
        order_source=item.order_source,
        element_count=item.element_count,
        relationship_count=item.relationship_count,
        analysis_id=item.run.analysis_id,
        analysis_timestamp=when or item.run.analysis_timestamp,
    )


class FakeStore:
    """Recovery's store, holding whatever a test put in it."""

    def __init__(self, *snapshots: ArchitectureSnapshot, stamps=None) -> None:
        self._snapshots = {item.snapshot_id: item for item in snapshots}
        self._stamps = stamps or {}

    def read(self, repository_id: str, snapshot_id: str):
        held = self._snapshots.get(snapshot_id)
        return held if held and held.release.repository_id == repository_id else None

    def history(self, repository_id: str):
        return [
            summary_of(item, self._stamps.get(item.snapshot_id))
            for item in self._snapshots.values()
            if item.release.repository_id == repository_id
        ]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return workspace(tmp_path, metadata())


class TestResolvingARelease:
    def test_either_identifier_finds_the_release(self, root):
        """A caller holds whichever id the route it came through gave it, and
        should not have to know about recovery's directory layout."""

        reader = GraphStoreReader(FakeStore(snapshot()), root)

        by_key = reader.read(REPOSITORY_KEY, RELEASE)
        by_workspace = reader.read(WORKSPACE_ID, RELEASE)

        assert by_key.provenance.source_snapshot_id
        assert by_workspace.provenance.source_snapshot_id == (
            by_key.provenance.source_snapshot_id
        )

    def test_the_newest_analysis_of_a_release_wins(self, root):
        """One release analysed twice leaves two snapshots, because the id
        covers the analysis configuration as well as the commit. Taking the
        first would validate whichever happened to be written first."""

        older = snapshot("snapshot:old")
        newer = snapshot("snapshot:new")
        store = FakeStore(
            older,
            newer,
            stamps={
                "snapshot:old": datetime(2026, 10, 18, tzinfo=UTC),
                "snapshot:new": datetime(2026, 10, 19, tzinfo=UTC),
            },
        )

        architecture = GraphStoreReader(store, root).read(REPOSITORY_KEY, RELEASE)

        assert architecture.provenance.source_snapshot_id == "snapshot:new"

    def test_an_unknown_release_names_the_ones_that_exist(self, root):
        """A caller who asked for the wrong release and a caller who asked
        before ingesting need different things done about them, so the
        message has to tell them apart."""

        reader = GraphStoreReader(FakeStore(snapshot()), root)

        with pytest.raises(GraphContractError) as error:
            reader.read(REPOSITORY_KEY, "v9.9.9")

        assert "v0.10.0" in str(error.value)

    def test_a_repository_the_store_never_saw_says_so(self, tmp_path):
        """The store is the authority on what has been analysed, not the
        workspace: a clone can be removed and its architecture remain."""

        reader = GraphStoreReader(FakeStore(snapshot()), tmp_path)

        with pytest.raises(GraphContractError) as error:
            reader.read("nothing-here", RELEASE)

        assert "no architecture for release" in str(error.value)

    def test_a_removed_clone_still_reads(self, tmp_path):
        """What a removed working tree costs is the file paths, not the
        architecture. Refusing here would make a readable result unreadable
        to protect a detail most screens do not ask for."""

        reader = GraphStoreReader(FakeStore(snapshot()), tmp_path)
        architecture = reader.read(REPOSITORY_KEY, RELEASE)

        assert len(architecture.elements) == 3
        assert all(not element.source_paths for element in architecture.elements)

    def test_a_store_that_is_down_is_a_conflict_not_a_crash(self, root):
        """A driver error reaching a screen as a 500 says nothing anybody can
        act on. This says which store, and what to do instead."""

        class Unreachable:
            def history(self, repository_id):
                raise RuntimeError("connection refused")

            def read(self, repository_id, snapshot_id):
                raise RuntimeError("connection refused")

        with pytest.raises(GraphContractError) as error:
            GraphStoreReader(Unreachable(), root).read(REPOSITORY_KEY, RELEASE)

        assert "could not be read" in str(error.value)


class TestTheVocabulary:
    def test_a_service_dependency_is_a_communication(self, root):
        """The silent one. An unmapped kind becomes a dependency, every rule
        about communication then matches nothing, and the run reports the
        whole architecture as ungoverned with no error anywhere."""

        from app.components.architecture_validation.models import RelationshipKind
        from app.components.architecture_validation.observation_normalization.styles.base import (  # noqa: E501
            classify_label,
        )

        architecture = GraphStoreReader(FakeStore(snapshot()), root).read(
            REPOSITORY_KEY, RELEASE
        )
        call = next(
            item
            for item in architecture.relationships
            if item.attributes["kind"] == "service_dependency"
        )

        assert classify_label(call.label) is RelationshipKind.COMMUNICATES_WITH

    def test_the_protocol_comes_from_the_evidence(self, root):
        """Recovery collapses gRPC and HTTP into one kind and keeps the
        distinction on the evidence. Reading it back is both more honest and
        more useful than labelling every call the same."""

        architecture = GraphStoreReader(FakeStore(snapshot()), root).read(
            REPOSITORY_KEY, RELEASE
        )
        call = next(
            item
            for item in architecture.relationships
            if item.target_id == "component:cartservice"
        )

        assert call.label == "grpc"
        assert call.attributes["confirmed_by_source"] is True

    def test_a_cache_is_a_datastore_not_a_module(self, root):
        architecture = GraphStoreReader(FakeStore(snapshot()), root).read(
            REPOSITORY_KEY, RELEASE
        )

        assert architecture.element_by_id("component:redis-cart").kind is (
            ElementKind.DATASTORE
        )

    def test_recovery_decided_the_identity_and_it_is_kept(self, root):
        """Recovery assigns a cross-release identity, and refuses to assign
        one when two components share a name. Dropping its answer would mean
        re-deriving something already settled."""

        architecture = GraphStoreReader(FakeStore(snapshot()), root).read(
            REPOSITORY_KEY, RELEASE
        )
        frontend = architecture.element_by_id("component:frontend")

        assert frontend.attributes["logical_id"] == "frontend"
        assert frontend.attributes["identity_basis"] == "heuristic"
        assert frontend.size == 71.0 and frontend.size_unit == "files"

    def test_every_relationship_is_recovery_s_own(self, root):
        """Nothing in this component derives an edge any more."""

        architecture = GraphStoreReader(FakeStore(snapshot()), root).read(
            REPOSITORY_KEY, RELEASE
        )

        assert all(
            item.derived_by is DerivationMethod.RECOVERED
            for item in architecture.relationships
        )
        assert architecture.has_element_relationships

    def test_a_declared_element_is_confirmed_and_a_heuristic_one_is_not(self, root):
        architecture = GraphStoreReader(FakeStore(snapshot()), root).read(
            REPOSITORY_KEY, RELEASE
        )

        assert architecture.element_by_id("component:cartservice").quality is (
            EvidenceQuality.CONFIRMED
        )
        assert architecture.element_by_id("component:frontend").quality is (
            EvidenceQuality.INFERRED
        )


class TestWhatRecoverySaidAboutTheScan:
    def test_an_incomplete_scan_is_reported_rather_than_hidden(self, root):
        """An element recovery never saw must not read as one that was
        removed."""

        store = FakeStore(snapshot(status=SnapshotStatus.INCOMPLETE))
        reader = GraphStoreReader(store, root)

        architecture = reader.read(REPOSITORY_KEY, RELEASE)
        notes = reader.notes(REPOSITORY_KEY, RELEASE)

        assert architecture.provenance.source_status == "incomplete"
        assert any("incomplete" in note for note in notes)

    def test_an_unresolved_reference_is_a_finding(self, root):
        """A configured address naming nothing in the architecture is a true
        statement about the repository, and this is the only place a person
        sees it."""

        from app.domain.architecture_snapshot import SnapshotUnresolved

        store = FakeStore(
            snapshot(
                unresolved=(
                    SnapshotUnresolved(
                        stage="dependency_resolution",
                        status="unresolved",
                        reference="PACKAGING_SERVICE_URL",
                        reason="no component matches",
                    ),
                )
            )
        )

        notes = GraphStoreReader(store, root).notes(REPOSITORY_KEY, RELEASE)

        assert any("PACKAGING_SERVICE_URL" in note for note in notes)


class TestTheReleaseDate:
    def test_recovery_s_release_date_is_taken(self, root):
        found = GraphStoreReader(FakeStore(snapshot()), root).released_at(
            REPOSITORY_KEY, RELEASE
        )

        assert found == (RELEASED, ReleaseDateSource.TAGGER)

    def test_the_analysis_timestamp_is_not_a_release_date(self, root):
        """It is when somebody ran the scan. Published as a release date it
        would order a consumer's timeline by analysis order while looking
        exactly like a real one."""

        store = FakeStore(snapshot(order_source=OrderSource.ANALYSIS_TIMESTAMP))

        assert GraphStoreReader(store, root).released_at(REPOSITORY_KEY, RELEASE) is None


class TestTheWorkspaceIndex:
    def test_a_directory_without_a_record_is_skipped(self, tmp_path):
        """Something else under the root must not stop a caller finding the
        repository they asked for."""

        (tmp_path / "not-a-clone").mkdir()
        workspace(tmp_path, metadata())

        assert len(WorkspaceIndex(tmp_path).records()) == 1

    def test_the_newest_ingest_of_a_release_wins(self, tmp_path):
        older = metadata(workspace_id="older")
        older["ingested_at"] = "2026-10-18T09:00:00+00:00"
        newer = metadata(workspace_id="newer")
        newer["ingested_at"] = (
            datetime(2026, 10, 19, tzinfo=UTC) + timedelta(hours=1)
        ).isoformat()

        workspace(tmp_path, older, newer)

        assert WorkspaceIndex(tmp_path).resolve(REPOSITORY_KEY, RELEASE).id == "newer"

    def test_nothing_ingested_says_nothing_is_ingested(self, tmp_path):
        with pytest.raises(WorkspaceUnavailable) as error:
            WorkspaceIndex(tmp_path).resolve(REPOSITORY_KEY)

        assert "nothing is ingested" in str(error.value)
