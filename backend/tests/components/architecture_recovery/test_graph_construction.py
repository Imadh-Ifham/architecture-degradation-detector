"""Tests for the graph construction subcomponent.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Covers the history guarantees the later components depend on: two releases
    of one repository keep two snapshots, a rerun is idempotent, a moved tag
    does not overwrite the earlier analysis, a failed scan is not a complete
    snapshot, and repositories never see each other's history.

    Each release fixture is run through the real inventory, manifest analysis,
    component discovery, dependency resolution and source code analysis first.
    No network access or live clone is required; the history store is an
    in-memory implementation of the same port the Neo4j adapter satisfies, and
    the Neo4j behaviour itself is covered by
    `tests/infrastructure/neo4j/test_architecture_snapshot_store.py`.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.components.architecture_recovery.component_discovery import (
    ComponentDiscoveryService,
    write_component_discovery,
)
from app.components.architecture_recovery.dependency_resolution import (
    DependencyResolutionService,
    write_dependency_resolution,
)
from app.components.architecture_recovery.graph_construction import (
    GRAPH_CONSTRUCTION_FILE_NAME,
    GraphConstructionService,
    SnapshotStoreError,
    release_from_ingested,
)
from app.components.architecture_recovery.graph_construction.builder import (
    SnapshotBuilder,
    snapshot_identity,
)
from app.components.architecture_recovery.graph_construction.inputs import (
    ComponentRecord,
    SnapshotInputs,
    UnresolvedRecord,
)
from app.components.architecture_recovery.graph_construction.service import (
    new_analysis_run,
)
from app.components.architecture_recovery.manifest_analysis import (
    ManifestAnalysisService,
    write_manifest_analysis,
)
from app.components.architecture_recovery.repository_inventory import (
    RepositoryInventoryService,
    RepositoryRef,
    write_inventory,
)
from app.components.architecture_recovery.source_code_analysis import (
    SOURCE_CODE_ANALYSIS_FILE_NAME,
    SourceCodeAnalysisService,
    write_source_code_analysis,
)
from app.domain.architecture_snapshot import (
    ArchitectureSnapshot,
    IdentityBasis,
    OrderSource,
    ReleaseMetadata,
    SnapshotStatus,
    SnapshotSummary,
)
from app.domain.repository import IngestedRepository

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "graph_construction"

V1 = datetime(2025, 1, 15, 9, 0, tzinfo=UTC)
V2 = datetime(2025, 8, 10, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class MemorySnapshotStore:
    """An in-memory implementation of the history port.

    It applies the same identity rules as the graph adapter: a snapshot is one
    row per `(repository_id, snapshot_id)`, publishing replaces that row and
    nothing else. That is what makes it a usable stand-in for the policy, while
    the Cypher that enforces it is tested separately.
    """

    def __init__(self) -> None:
        self.snapshots: dict[tuple[str, str], ArchitectureSnapshot] = {}
        self.publish_count = 0

    def publish(self, snapshot: ArchitectureSnapshot) -> str:
        self.publish_count += 1
        self.snapshots[(snapshot.repository_id, snapshot.snapshot_id)] = snapshot
        return f"memory://{snapshot.repository_id}/{snapshot.snapshot_id}"

    def read(
        self, repository_id: str, snapshot_id: str
    ) -> ArchitectureSnapshot | None:
        return self.snapshots.get((repository_id, snapshot_id))

    def history(self, repository_id: str) -> list[SnapshotSummary]:
        rows = [
            snapshot
            for (owner, _), snapshot in self.snapshots.items()
            if owner == repository_id
        ]
        rows.sort(key=lambda item: (item.order_timestamp, item.snapshot_id))

        return [
            SnapshotSummary(
                snapshot_id=item.snapshot_id,
                repository_id=item.repository_id,
                release_id=item.release.release_id,
                release_tag=item.release.release_tag,
                commit_sha=item.release.commit_sha,
                status=item.status,
                order_timestamp=item.order_timestamp,
                order_source=item.order_source,
                element_count=item.element_count,
                relationship_count=item.relationship_count,
                analysis_id=item.run.analysis_id,
                analysis_timestamp=item.run.analysis_timestamp,
            )
            for item in rows
        ]


class RefusingStore:
    """A store that is configured but cannot write."""

    def publish(self, snapshot: ArchitectureSnapshot) -> str:
        raise RuntimeError("graph store is down")

    def read(self, repository_id, snapshot_id):  # pragma: no cover - unused
        return None

    def history(self, repository_id):  # pragma: no cover - unused
        return []


def run_pipeline(root: Path, repository_id: str):
    """Run every recovery stage over one working tree."""

    inventory = RepositoryInventoryService().build(
        root, RepositoryRef(id=repository_id, branch="main", commit="a" * 40)
    )
    analysis = ManifestAnalysisService().analyze(inventory, root)
    discovery = ComponentDiscoveryService().discover(inventory, analysis)
    dependencies = DependencyResolutionService().resolve(discovery, analysis)
    source = SourceCodeAnalysisService().analyze(
        inventory, discovery, dependencies, root
    )

    return inventory, analysis, discovery, dependencies, source


def stage_release(
    workspace: Path,
    fixture: str,
    *,
    repository_id: str,
    commit: str,
    tag: str | None,
    release_date: datetime | None,
    commit_date: datetime | None = None,
    with_source: bool = True,
) -> IngestedRepository:
    """Build a release workspace the way the ingest flow leaves it on disk."""

    source_root = workspace / "source"
    if source_root.exists():
        shutil.rmtree(source_root)

    shutil.copytree(FIXTURES / fixture, source_root)

    inventory, analysis, discovery, dependencies, source = run_pipeline(
        source_root, repository_id
    )

    write_inventory(inventory, workspace)
    write_manifest_analysis(analysis, workspace)
    write_component_discovery(discovery, workspace)
    write_dependency_resolution(dependencies, workspace)

    if with_source:
        write_source_code_analysis(source, workspace)

    return IngestedRepository(
        id=workspace.name,
        url="https://example.com/team/shop.git",
        branch="main",
        commit=commit,
        path=source_root,
        ingested_at=datetime.now(UTC),
        repository_id=repository_id,
        release_tag=tag,
        revision=tag or commit,
        release_date=release_date,
        release_date_source="tagger" if release_date else None,
        commit_date=commit_date,
    )


def release(
    *,
    repository_id: str = "shop",
    commit: str = "a" * 40,
    tag: str | None = "v1.0.0",
    released: datetime | None = V1,
    committed: datetime | None = None,
) -> ReleaseMetadata:
    """A release identity for builder-level tests."""

    return ReleaseMetadata(
        repository_id=repository_id,
        commit_sha=commit,
        repository_url="https://example.com/team/shop.git",
        release_tag=tag,
        release_date=released,
        release_date_source="tagger" if released else None,
        commit_date=committed,
        branch_name="main",
    )


def analyse_two_releases(tmp_path: Path, store: MemorySnapshotStore):
    """Stage v1.0.0 and v1.2.0 and return their snapshot ids."""

    service = GraphConstructionService(store=store)

    first = stage_release(
        tmp_path / "v1",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
    )
    first_path, first_report = service.run_for_ingested(first)

    second = stage_release(
        tmp_path / "v2",
        "release_v2",
        repository_id="shop",
        commit="b" * 40,
        tag="v1.2.0",
        release_date=V2,
    )
    second_path, second_report = service.run_for_ingested(second)

    return first, second, first_path, first_report, second_path, second_report


# --------------------------------------------------------------------------- #
# 1-2. Two releases, both preserved
# --------------------------------------------------------------------------- #


def test_two_releases_produce_separate_snapshots(tmp_path: Path) -> None:
    store = MemorySnapshotStore()
    _, _, _, first, _, second = analyse_two_releases(tmp_path, store)

    assert first.snapshot_id != second.snapshot_id
    assert first.snapshot.release.release_tag == "v1.0.0"
    assert second.snapshot.release.release_tag == "v1.2.0"
    assert len(store.snapshots) == 2


def test_both_snapshots_remain_queryable_after_the_second_release(
    tmp_path: Path,
) -> None:
    store = MemorySnapshotStore()
    _, _, _, first, _, _ = analyse_two_releases(tmp_path, store)

    stored = store.read("shop", first.snapshot_id)

    assert stored is not None
    assert stored.release.release_tag == "v1.0.0"
    assert {element.name for element in stored.elements} == {"frontend", "checkout"}
    assert len(stored.relationships) == 1

    history = store.history("shop")

    assert [row.release_tag for row in history] == ["v1.0.0", "v1.2.0"]


# --------------------------------------------------------------------------- #
# 3-5. Comparison across releases
# --------------------------------------------------------------------------- #


def test_unchanged_component_keeps_its_logical_identity(tmp_path: Path) -> None:
    store = MemorySnapshotStore()
    _, _, _, first, _, second = analyse_two_releases(tmp_path, store)

    def element(snapshot, name: str):
        return next(item for item in snapshot.elements if item.name == name)

    first_frontend = element(first.snapshot, "frontend")
    second_frontend = element(second.snapshot, "frontend")

    assert first_frontend.logical_id == "frontend"
    assert second_frontend.logical_id == "frontend"
    assert first_frontend.identity_basis is IdentityBasis.DIRECT
    assert second_frontend.identity_basis is IdentityBasis.DIRECT

    # Snapshot identity stays separate: the same component is two observations.
    assert first_frontend.id == second_frontend.id  # upstream ids are stable
    assert first.snapshot_id != second.snapshot_id


def test_component_size_can_differ_between_releases(tmp_path: Path) -> None:
    store = MemorySnapshotStore()
    _, _, _, first, _, second = analyse_two_releases(tmp_path, store)

    first_frontend = next(
        item for item in first.snapshot.elements if item.name == "frontend"
    )
    second_frontend = next(
        item for item in second.snapshot.elements if item.name == "frontend"
    )

    assert first_frontend.size == 2.0
    assert second_frontend.size == 3.0
    assert first_frontend.size_unit == second_frontend.size_unit == "files"


def test_relationships_are_added_without_changing_the_earlier_snapshot(
    tmp_path: Path,
) -> None:
    store = MemorySnapshotStore()
    _, _, _, first, _, second = analyse_two_releases(tmp_path, store)

    first_names = {element.name for element in first.snapshot.elements}
    second_names = {element.name for element in second.snapshot.elements}

    assert first_names == {"frontend", "checkout"}
    assert second_names == {"frontend", "checkout", "cart"}
    assert len(first.snapshot.relationships) == 1
    assert len(second.snapshot.relationships) == 2

    stored = store.read("shop", first.snapshot_id)

    assert stored is not None
    assert len(stored.relationships) == 1
    assert {element.name for element in stored.elements} == {"frontend", "checkout"}


# --------------------------------------------------------------------------- #
# 6-7. Idempotency and moved tags
# --------------------------------------------------------------------------- #


def test_reprocessing_the_same_revision_is_idempotent(tmp_path: Path) -> None:
    store = MemorySnapshotStore()
    service = GraphConstructionService(store=store)
    repository = stage_release(
        tmp_path / "v1",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
    )

    first_path, first = service.run_for_ingested(repository)
    second_path, second = service.run_for_ingested(repository)

    assert first.snapshot_id == second.snapshot_id
    assert first_path == second_path
    assert len(store.snapshots) == 1
    assert store.publish_count == 2  # two runs, one stored snapshot
    assert second.snapshot.run.analysis_id != first.snapshot.run.analysis_id

    assert len(second.snapshot.elements) == len(first.snapshot.elements)
    assert len(second.snapshot.relationships) == len(first.snapshot.relationships)


def test_a_moved_tag_does_not_overwrite_the_earlier_commit(tmp_path: Path) -> None:
    store = MemorySnapshotStore()
    service = GraphConstructionService(store=store)

    original = stage_release(
        tmp_path / "original",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
    )
    _, first = service.run_for_ingested(original)

    moved = stage_release(
        tmp_path / "moved",
        "release_v2",
        repository_id="shop",
        commit="c" * 40,
        tag="v1.0.0",
        release_date=V2,
    )
    _, second = service.run_for_ingested(moved)

    assert first.snapshot.release.release_tag == second.snapshot.release.release_tag
    assert first.snapshot_id != second.snapshot_id

    stored = store.read("shop", first.snapshot_id)

    assert stored is not None
    assert stored.release.commit_sha == "a" * 40
    assert len(stored.elements) == 2


# --------------------------------------------------------------------------- #
# 8-9. Failed or incomplete scans never look complete
# --------------------------------------------------------------------------- #


def test_missing_source_evidence_makes_the_snapshot_incomplete(
    tmp_path: Path,
) -> None:
    store = MemorySnapshotStore()
    repository = stage_release(
        tmp_path / "v1",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
        with_source=False,
    )

    _, report = GraphConstructionService(store=store).run_for_ingested(repository)

    assert report.snapshot.status is SnapshotStatus.INCOMPLETE
    assert "source_code_analysis" in report.snapshot.missing_inputs
    assert store.read("shop", report.snapshot_id).status is SnapshotStatus.INCOMPLETE


def test_a_failed_scan_is_stored_as_failed_with_no_elements(tmp_path: Path) -> None:
    store = MemorySnapshotStore()

    _, report = GraphConstructionService(store=store).record_failure(
        release=release(commit="d" * 40, tag="v1.3.0"),
        error="source clone disappeared mid-run",
        workspace=tmp_path,
    )

    assert report.snapshot.status is SnapshotStatus.FAILED
    assert report.snapshot.elements == ()
    assert report.snapshot.relationships == ()
    assert any("failed" in note for note in report.snapshot.notes)

    stored = store.read("shop", report.snapshot_id)

    assert stored is not None
    assert stored.status is SnapshotStatus.FAILED


# --------------------------------------------------------------------------- #
# 10. Repository isolation and chronology
# --------------------------------------------------------------------------- #


def test_repositories_stay_isolated(tmp_path: Path) -> None:
    store = MemorySnapshotStore()
    service = GraphConstructionService(store=store)

    shop = stage_release(
        tmp_path / "shop",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
    )
    warehouse = stage_release(
        tmp_path / "warehouse",
        "release_v1",
        repository_id="warehouse",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
    )

    _, shop_report = service.run_for_ingested(shop)
    _, warehouse_report = service.run_for_ingested(warehouse)

    assert shop_report.snapshot_id != warehouse_report.snapshot_id
    assert len(store.history("shop")) == 1
    assert len(store.history("warehouse")) == 1
    assert store.read("shop", warehouse_report.snapshot_id) is None


def test_history_is_ordered_by_release_date(tmp_path: Path) -> None:
    store = MemorySnapshotStore()
    service = GraphConstructionService(store=store)

    for name, fixture, commit, tag, released in (
        ("v2", "release_v2", "b" * 40, "v1.2.0", V2),
        ("v1", "release_v1", "a" * 40, "v1.0.0", V1),
    ):
        repository = stage_release(
            tmp_path / name,
            fixture,
            repository_id="shop",
            commit=commit,
            tag=tag,
            release_date=released,
        )
        service.run_for_ingested(repository)

    history = store.history("shop")

    assert [row.release_tag for row in history] == ["v1.0.0", "v1.2.0"]
    assert all(row.order_source is OrderSource.RELEASE_DATE for row in history)


def test_history_falls_back_to_commit_date_and_records_it(tmp_path: Path) -> None:
    store = MemorySnapshotStore()
    service = GraphConstructionService(store=store)

    repository = stage_release(
        tmp_path / "v1",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag=None,
        release_date=None,
        commit_date=V1,
    )

    _, report = service.run_for_ingested(repository)

    assert report.snapshot.order_source is OrderSource.COMMIT_DATE
    assert report.snapshot.order_timestamp == V1


def test_history_falls_back_to_the_analysis_timestamp(tmp_path: Path) -> None:
    store = MemorySnapshotStore()
    service = GraphConstructionService(store=store)

    repository = stage_release(
        tmp_path / "v1",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag=None,
        release_date=None,
        commit_date=None,
    )

    _, report = service.run_for_ingested(repository)

    assert report.snapshot.order_source is OrderSource.ANALYSIS_TIMESTAMP


# --------------------------------------------------------------------------- #
# Evidence semantics
# --------------------------------------------------------------------------- #


def test_source_evidence_corroborates_a_configured_relationship(
    tmp_path: Path,
) -> None:
    store = MemorySnapshotStore()
    repository = stage_release(
        tmp_path / "v1",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
    )

    _, report = GraphConstructionService(store=store).run_for_ingested(repository)
    edge = report.snapshot.relationships[0]
    stages = {item.stage for item in edge.evidence}

    assert edge.confirmed_by_source is True
    assert stages == {"dependency_resolution", "source_code_analysis"}
    assert len(report.snapshot.relationships) == 1


def test_two_components_sharing_a_name_get_no_logical_identity() -> None:
    builder = SnapshotBuilder()
    inputs = SnapshotInputs(
        components=(
            ComponentRecord("c1", "paymentservice", "service", "direct", 1),
            ComponentRecord("c2", "paymentservice", "service", "direct", 1),
        )
    )

    snapshot = builder.build(
        release=release(), run=new_analysis_run(timestamp=V1), inputs=inputs
    )

    assert all(
        element.logical_id is None
        and element.identity_basis is IdentityBasis.UNASSIGNED
        for element in snapshot.elements
    )


def test_heuristic_component_identity_is_labelled() -> None:
    builder = SnapshotBuilder()
    inputs = SnapshotInputs(
        components=(
            ComponentRecord("c1", "frontend", "service", "heuristic", 1),
        )
    )

    snapshot = builder.build(
        release=release(), run=new_analysis_run(timestamp=V1), inputs=inputs
    )

    assert snapshot.elements[0].logical_id == "frontend"
    assert snapshot.elements[0].identity_basis is IdentityBasis.HEURISTIC


def test_unresolved_references_are_carried_onto_the_snapshot() -> None:
    builder = SnapshotBuilder()
    inputs = SnapshotInputs(
        components=(ComponentRecord("c1", "frontend", "service", "direct", 1),),
        unresolved=(
            UnresolvedRecord(
                stage="dependency_resolution",
                status="unresolved",
                reference="legacy-db:5432",
                reason="no component matched",
            ),
            UnresolvedRecord(
                stage="source_code_analysis",
                status="ambiguous",
                reference="paymentservice",
                reason="two components matched",
            ),
        ),
    )

    snapshot = builder.build(
        release=release(), run=new_analysis_run(timestamp=V1), inputs=inputs
    )

    assert len(snapshot.unresolved) == 2
    assert {item.status for item in snapshot.unresolved} == {"unresolved", "ambiguous"}
    assert json.loads(json.dumps(snapshot.to_dict()))["unresolved"][0]["reference"]


def test_snapshot_identity_is_deterministic_for_one_configuration() -> None:
    run = new_analysis_run(timestamp=V1)
    first = snapshot_identity(release(), run)
    second = snapshot_identity(release(), run)

    assert first == second
    assert first.startswith("snapshot:")


# --------------------------------------------------------------------------- #
# Report and store failure
# --------------------------------------------------------------------------- #


def test_reports_of_two_releases_do_not_overwrite_each_other(
    tmp_path: Path,
) -> None:
    _, _, first_path, first, second_path, second = analyse_two_releases(
        tmp_path / "runs", MemorySnapshotStore()
    )

    assert first_path != second_path
    assert first_path.name == GRAPH_CONSTRUCTION_FILE_NAME
    assert first_path.parent.parent.name == "graph_construction"
    assert second_path.parent.parent.name == "graph_construction"

    first_payload = json.loads(first_path.read_text(encoding="utf-8"))

    assert first_payload["snapshot_id"] == first.snapshot_id
    assert first_payload["status"] == "complete"
    assert first_payload["store"]["published"] is True


def test_a_refused_store_write_is_reported(tmp_path: Path) -> None:
    store = RefusingStore()
    repository = stage_release(
        tmp_path / "v1",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
    )

    with pytest.raises(SnapshotStoreError, match="graph store is down"):
        GraphConstructionService(store=store).run_for_ingested(repository)

    # The report is still on disk and says the store did not accept it.
    report_path = next((tmp_path / "v1").rglob(GRAPH_CONSTRUCTION_FILE_NAME))
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["store"]["published"] is False


def test_missing_required_upstream_artifact_is_an_input_error(
    tmp_path: Path,
) -> None:
    from app.components.architecture_recovery.graph_construction import (
        GraphConstructionInputError,
    )

    repository = stage_release(
        tmp_path / "v1",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
    )
    (tmp_path / "v1" / SOURCE_CODE_ANALYSIS_FILE_NAME).unlink(missing_ok=True)
    (tmp_path / "v1" / "dependency_resolution.json").unlink()

    with pytest.raises(GraphConstructionInputError, match="dependency resolution"):
        GraphConstructionService().run_for_ingested(repository)


def test_release_metadata_carries_both_identities(tmp_path: Path) -> None:
    repository = stage_release(
        tmp_path / "v1",
        "release_v1",
        repository_id="shop",
        commit="a" * 40,
        tag="v1.0.0",
        release_date=V1,
    )

    metadata = release_from_ingested(repository)

    assert metadata.repository_id == "shop"
    assert metadata.release_id == "v1.0.0"
    assert metadata.commit_sha == "a" * 40
    assert metadata.release_date == V1
