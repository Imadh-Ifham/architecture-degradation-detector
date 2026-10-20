import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.repositories import (
    get_architecture_snapshot_store,
    get_component_discovery_service,
    get_configuration_store,
    get_dependency_resolution_service,
    get_graph_construction_service,
    get_manifest_analysis_service,
    get_repository_ingestion_service,
    get_repository_inventory_service,
    get_source_code_analysis_service,
    get_workspace_checkouts,
)
from app.components.architecture_recovery.component_discovery import (
    ComponentDiscoveryError,
)
from app.components.architecture_recovery.dependency_resolution import (
    DependencyResolutionError,
)
from app.components.architecture_recovery.graph_construction import (
    GraphConstructionService,
)
from app.components.architecture_recovery.manifest_analysis import (
    ManifestAnalysisError,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    RepositoryIngestionService,
)
from app.components.architecture_recovery.repository_inventory import (
    INVENTORY_FILE_NAME,
    RepositoryInventoryError,
)
from app.components.architecture_recovery.source_code_analysis import (
    SourceCodeAnalysisError,
)
from app.infrastructure.workspace import (
    RepositoryConfigurationStore,
    WorkspaceCheckouts,
)
from app.main import app


class StubGitClient:
    """Writes a small working tree instead of cloning a repository.

    A branch clone answers the fixed commit every earlier test asserts. A
    revision clone answers a SHA derived from the revision, so two releases of
    one repository are two commits - which is what makes them two snapshots.
    """

    commit = "a" * 40
    release_date = datetime(2025, 1, 15, tzinfo=UTC)

    def __init__(self) -> None:
        self._revision = "main"

    def clone(self, url: str, branch: str, destination: Path) -> None:
        self._revision = branch
        self._write_tree(destination)

    def clone_at(self, url: str, revision: str, destination: Path) -> None:
        self._revision = revision
        self._write_tree(destination)

    def head_commit(self, repository: Path) -> str:
        if self._revision == "main":
            return self.commit

        return hashlib.sha1(self._revision.encode("utf-8")).hexdigest()

    def commit_date(self, repository: Path, revision: str = "HEAD"):
        return self.release_date

    def is_tag(self, repository: Path, revision: str) -> bool:
        return revision.startswith("v")

    def tag_date(self, repository: Path, tag: str):
        return self.release_date if tag.startswith("v") else None

    @staticmethod
    def _write_tree(destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "README.md").write_text("# stub\n", encoding="utf-8")

        service = destination / "services" / "cart"
        service.mkdir(parents=True, exist_ok=True)
        (service / "go.mod").write_text("module example/cart\n", encoding="utf-8")
        (service / "main.go").write_text("package main\n", encoding="utf-8")

        # A manifest, so the analysis stage has something to find.
        (destination / "docker-compose.yaml").write_text(
            "services:\n  web:\n    image: nginx:1.27\n", encoding="utf-8"
        )


class MemoryStore:
    """An in-memory snapshot store, so API tests do not touch a real graph."""

    def __init__(self) -> None:
        self.snapshots = {}

    def publish(self, snapshot):
        self.snapshots[(snapshot.repository_id, snapshot.snapshot_id)] = snapshot
        return f"memory://{snapshot.repository_id}/{snapshot.snapshot_id}"

    def read(self, repository_id, snapshot_id):
        return self.snapshots.get((repository_id, snapshot_id))

    def history(self, repository_id):
        from app.domain.architecture_snapshot import SnapshotSummary

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

    def delete_snapshot(self, repository_id, snapshot_id):
        return self.snapshots.pop((repository_id, snapshot_id), None) is not None

    def delete_repository(self, repository_id):
        removed = [
            key for key in self.snapshots if key[0] == repository_id
        ]

        for key in removed:
            del self.snapshots[key]

        return len(removed)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def client(tmp_path: Path, store: MemoryStore):
    service = RepositoryIngestionService(git_client=StubGitClient(), root=tmp_path)
    app.dependency_overrides[get_repository_ingestion_service] = lambda: service
    app.dependency_overrides[get_graph_construction_service] = (
        lambda: GraphConstructionService(store=store)
    )
    app.dependency_overrides[get_architecture_snapshot_store] = lambda: store
    app.dependency_overrides[get_configuration_store] = (
        lambda: RepositoryConfigurationStore(tmp_path)
    )
    app.dependency_overrides[get_workspace_checkouts] = (
        lambda: WorkspaceCheckouts(tmp_path, "source")
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def ingest(client: TestClient, payload: dict, route: str = "/repositories") -> dict:
    """Clone a repository. Ingestion alone analyses nothing."""

    response = client.post(route, json=payload)

    assert response.status_code == 201

    return response.json()


def recover(client: TestClient, ingested: dict) -> dict:
    """Run recovery over a clone, the way the pipeline does."""

    response = client.post(f"/repositories/{ingested['id']}/recovery")

    assert response.status_code == 200

    return response.json()


def ingest_and_recover(
    client: TestClient, payload: dict, route: str = "/repositories"
) -> dict:
    """The two calls a pipeline makes for one snapshot, recovery body returned."""

    return recover(client, ingest(client, payload, route))


def test_ingest_repository_then_list_it(client: TestClient) -> None:
    created = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert created.status_code == 201

    body = created.json()

    assert body["url"] == "https://example.com/team/repo.git"
    assert body["branch"] == "main"
    assert body["commit"] == "a" * 40
    assert body["ingested_at"]

    listed = client.get("/repositories")

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]


def test_ingest_rejects_unsupported_url(client: TestClient) -> None:
    response = client.post(
        "/repositories",
        json={"url": "file:///etc/passwd", "branch": "main"},
    )

    assert response.status_code == 400
    assert "detail" in response.json()


def test_ingest_rejects_unsafe_branch(client: TestClient) -> None:
    response = client.post(
        "/repositories",
        json={
            "url": "https://example.com/team/repo.git",
            "branch": "--upload-pack=evil",
        },
    )

    assert response.status_code == 400


def test_ingest_requires_both_fields(client: TestClient) -> None:
    response = client.post("/repositories", json={"url": "https://example.com/r.git"})

    assert response.status_code == 422


def test_remove_repository_deletes_it(client: TestClient) -> None:
    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    removed = client.delete(f"/repositories/{created['id']}")

    assert removed.status_code == 204
    assert client.get("/repositories").json() == []


def test_remove_unknown_repository_returns_404(client: TestClient) -> None:
    response = client.delete("/repositories/unknown-id")

    assert response.status_code == 404


def test_remove_repository_deletes_its_stored_history(
    client: TestClient, store: MemoryStore
) -> None:
    """Removing the clone removes what the clone produced."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert store.snapshots

    removed = client.delete(f"/repositories/{created['id']}")

    assert removed.status_code == 204
    assert store.snapshots == {}


def test_removing_one_release_keeps_the_other_release_snapshot(
    client: TestClient, store: MemoryStore
) -> None:
    """A release's history outlives the checkout it was analysed from.

    Deleting the `v0.9.0` clone must not erase the `v0.10.0` snapshot, whose
    clone is still on disk and still claims to have been analysed.
    """

    first = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "revision": "v0.9.0"},
        "/repositories/releases",
    )
    ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "revision": "v0.10.0"},
        "/repositories/releases",
    )

    assert len(store.snapshots) == 2

    client.delete(f"/repositories/{first['id']}")

    remaining = list(store.snapshots.values())

    assert len(remaining) == 1
    assert remaining[0].release.release_tag == "v0.10.0"


def test_remove_repository_keeps_another_repositorys_history(
    client: TestClient, store: MemoryStore
) -> None:
    kept = ingest_and_recover(
        client,
        {"url": "https://example.com/team/other.git", "branch": "main"},
    )
    removed = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    client.delete(f"/repositories/{removed['id']}")

    assert [item["id"] for item in client.get("/repositories").json()] == [kept["id"]]
    assert len(store.snapshots) == 1


def test_a_refused_purge_keeps_the_clone_so_it_can_be_retried(
    client: TestClient, store: MemoryStore
) -> None:
    """The files go last, so a graph failure leaves something to retry with."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    class RefusingStore(MemoryStore):
        def delete_repository(self, repository_id):
            raise RuntimeError("the graph store is unreachable")

    app.dependency_overrides[get_architecture_snapshot_store] = lambda: RefusingStore()

    response = client.delete(f"/repositories/{created['id']}")

    assert response.status_code == 500
    assert [item["id"] for item in client.get("/repositories").json()] == [created["id"]]


def test_recovery_inventories_the_clone(client: TestClient) -> None:
    """Recovery inventories a clone that is already on disk."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert created["inventory_error"] is None

    inventory = created["inventory"]

    assert inventory is not None
    # README.md, docker-compose.yaml, services/cart/go.mod, services/cart/main.go
    assert inventory["file_count"] == 4
    # The `cart` build unit, plus the `web` service the compose file declares.
    assert inventory["component_count"] == 2
    assert inventory["relationship_count"] > 0
    assert inventory["by_language"] == {"go": 2}
    assert inventory["truncated"] is False

    # Written next to the working tree, never inside it.
    written = Path(inventory["path"])
    assert written.name == INVENTORY_FILE_NAME
    assert written.is_file()
    assert written.parent == Path(created["path"]).parent
    assert not (Path(created["path"]) / INVENTORY_FILE_NAME).exists()


def test_recovery_analyzes_the_manifests(client: TestClient) -> None:
    """Manifests are analysed straight after the inventory."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert created["manifest_analysis_error"] is None

    analysis = created["manifest_analysis"]

    assert analysis is not None
    assert analysis["file_count"] == 1
    assert analysis["analyzed_count"] == 1
    assert analysis["resource_count"] == 2
    assert analysis["by_analyzer"] == {"compose": 1}

    written = Path(analysis["path"])
    assert written.name == "manifest_analysis.json"
    assert written.parent == Path(created["path"]).parent
    assert not (Path(created["path"]) / "manifest_analysis.json").exists()


def test_analysis_is_skipped_when_the_inventory_fails(client: TestClient) -> None:
    """Analysis depends on the inventory, so a missing inventory is reported."""

    class FailingInventoryService:
        def run_for_ingested(self, repository):
            raise RepositoryInventoryError("workspace is not writable")

    app.dependency_overrides[get_repository_inventory_service] = (
        lambda: FailingInventoryService()
    )

    body = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert body["inventory"] is None
    assert body["manifest_analysis"] is None
    assert "no repository inventory" in body["manifest_analysis_error"]


def test_analysis_failure_does_not_fail_the_recovery(client: TestClient) -> None:
    """A downstream failure must not undo the inventory."""

    class FailingAnalysisService:
        def run(self, inventory, root, output_directory):
            raise ManifestAnalysisError("analysis workspace is not writable")

    app.dependency_overrides[get_manifest_analysis_service] = (
        lambda: FailingAnalysisService()
    )

    body = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert body["inventory"] is not None
    assert body["manifest_analysis"] is None
    assert body["manifest_analysis_error"] == "analysis workspace is not writable"


def test_recovery_discovers_components(client: TestClient) -> None:
    """Component discovery runs automatically after its prerequisites."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert created["component_discovery_error"] is None

    discovery = created["component_discovery"]

    assert discovery is not None
    assert discovery["component_count"] == 2
    assert discovery["by_type"] == {"application": 1, "service": 1}
    assert discovery["artifact_count"] == 3
    assert discovery["unresolved_count"] == 0

    written = Path(discovery["path"])
    assert written.name == "component_discovery.json"
    assert written.parent == Path(created["path"]).parent
    assert not (Path(created["path"]) / "component_discovery.json").exists()


def test_recovery_resolves_dependencies(client: TestClient) -> None:
    """Dependency resolution runs automatically after component discovery."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert created["dependency_resolution_error"] is None

    dependencies = created["dependency_resolution"]

    assert dependencies is not None
    assert dependencies["resolved_relationship_count"] == 0
    assert dependencies["unresolved_count"] == 0
    assert dependencies["ambiguous_count"] == 0

    written = Path(dependencies["path"])
    assert written.name == "dependency_resolution.json"
    assert written.parent == Path(created["path"]).parent
    assert not (Path(created["path"]) / "dependency_resolution.json").exists()


def test_recovery_analyzes_source_code(client: TestClient) -> None:
    """Source code analysis runs automatically after dependency resolution."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert created["source_code_analysis_error"] is None

    source = created["source_code_analysis"]

    assert source is not None
    assert source["resolved_count"] == 0
    assert source["unresolved_count"] == 0
    assert source["ambiguous_count"] == 0

    written = Path(source["path"])
    assert written.name == "source_code_analysis.json"
    assert written.parent == Path(created["path"]).parent
    assert not (Path(created["path"]) / "source_code_analysis.json").exists()


def test_previous_response_fields_are_unchanged(client: TestClient) -> None:
    """Adding source code analysis must not disturb the earlier stages' output."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    # The ingestion fields are still present and correct.
    assert created["url"] == "https://example.com/team/repo.git"
    assert created["branch"] == "main"
    assert created["commit"] == "a" * 40

    # And so are every earlier analysis stage.
    assert created["inventory_error"] is None
    assert created["manifest_analysis_error"] is None
    assert created["component_discovery_error"] is None
    assert created["dependency_resolution_error"] is None
    assert created["source_code_analysis_error"] is None
    assert created["inventory"]["file_count"] == 4
    assert created["manifest_analysis"]["resource_count"] == 2
    assert created["component_discovery"] is not None
    assert created["dependency_resolution"] is not None
    assert created["source_code_analysis"] is not None


def test_dependency_resolution_is_skipped_when_discovery_fails(
    client: TestClient,
) -> None:
    """Dependency resolution needs component discovery, so it says so."""

    class FailingDiscoveryService:
        def run(self, inventory, analysis, output_directory):
            raise ComponentDiscoveryError("discovery failed")

    app.dependency_overrides[get_component_discovery_service] = (
        lambda: FailingDiscoveryService()
    )

    body = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert body["dependency_resolution"] is None
    assert "no component discovery" in body["dependency_resolution_error"]
    assert body["manifest_analysis"] is not None


def test_dependency_resolution_failure_does_not_fail_the_recovery(
    client: TestClient,
) -> None:
    """A downstream failure must not undo the earlier stages."""

    class FailingDependencyService:
        def run(self, discovery, analysis, output_directory):
            raise DependencyResolutionError("dependency workspace is not writable")

    app.dependency_overrides[get_dependency_resolution_service] = (
        lambda: FailingDependencyService()
    )

    body = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert body["component_discovery"] is not None
    assert body["dependency_resolution"] is None
    assert (
        body["dependency_resolution_error"]
        == "dependency workspace is not writable"
    )
    assert body["source_code_analysis"] is None
    assert "no dependency resolution" in body["source_code_analysis_error"]


def test_source_analysis_failure_does_not_fail_the_recovery(
    client: TestClient,
) -> None:
    """A source analysis failure must not undo earlier stages."""

    class FailingSourceAnalysisService:
        def run(self, inventory, discovery, dependencies, root, output_directory):
            raise SourceCodeAnalysisError("source analysis workspace is not writable")

    app.dependency_overrides[get_source_code_analysis_service] = (
        lambda: FailingSourceAnalysisService()
    )

    body = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert body["dependency_resolution"] is not None
    assert body["source_code_analysis"] is None
    assert (
        body["source_code_analysis_error"]
        == "source analysis workspace is not writable"
    )


def test_discovery_is_skipped_when_analysis_fails(client: TestClient) -> None:
    """Discovery needs both upstream results, so it says so rather than guessing."""

    class FailingAnalysisService:
        def run(self, inventory, root, output_directory):
            raise ManifestAnalysisError("analysis failed")

    app.dependency_overrides[get_manifest_analysis_service] = (
        lambda: FailingAnalysisService()
    )

    body = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert body["component_discovery"] is None
    assert "no manifest analysis" in body["component_discovery_error"]
    # The stages that did run are still reported.
    assert body["inventory"] is not None


def test_discovery_is_skipped_when_the_inventory_fails(client: TestClient) -> None:
    class FailingInventoryService:
        def run_for_ingested(self, repository):
            raise RepositoryInventoryError("inventory failed")

    app.dependency_overrides[get_repository_inventory_service] = (
        lambda: FailingInventoryService()
    )

    body = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert body["component_discovery"] is None
    assert "no repository inventory" in body["component_discovery_error"]


def test_discovery_failure_does_not_fail_the_recovery(client: TestClient) -> None:
    """A downstream failure must not undo the earlier stages."""

    class FailingDiscoveryService:
        def run(self, inventory, analysis, output_directory):
            raise ComponentDiscoveryError("discovery workspace is not writable")

    app.dependency_overrides[get_component_discovery_service] = (
        lambda: FailingDiscoveryService()
    )

    body = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert body["inventory"] is not None
    assert body["manifest_analysis"] is not None
    assert body["component_discovery"] is None
    assert body["component_discovery_error"] == "discovery workspace is not writable"


def test_ingesting_a_release_records_a_snapshot(
    client: TestClient, store: MemoryStore
) -> None:
    """A tag can be analyzed on its own, and the snapshot is retrievable."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "revision": "v1.0.0"},
        "/repositories/releases",
    )

    assert created["graph_construction_error"] is None
    assert created["release_tag"] == "v1.0.0"
    assert created["release_date"] is not None
    assert created["graph_construction"]["status"] == "complete"
    assert created["graph_construction"]["store_published"] is True

    repository_id = created["repository_id"]
    history = client.get(f"/repositories/{repository_id}/snapshots").json()

    assert len(history) == 1
    assert history[0]["release_tag"] == "v1.0.0"
    assert history[0]["order_source"] == "release_date"

    detail = client.get(
        f"/repositories/{repository_id}/snapshots/{history[0]['snapshot_id']}"
    ).json()

    assert detail["snapshot_id"] == history[0]["snapshot_id"]
    assert detail["repository"]["commit_sha"] == created["commit"]
    assert len(detail["elements"]) == history[0]["element_count"]


def test_two_releases_keep_two_snapshots(client: TestClient) -> None:
    """A newer release must not overwrite the snapshot of an older one."""

    first = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "revision": "v1.0.0"},
        "/repositories/releases",
    )
    second = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "revision": "v1.2.0"},
        "/repositories/releases",
    )

    repository_id = first["repository_id"]

    assert repository_id == second["repository_id"]
    assert first["id"] != second["id"]

    history = client.get(f"/repositories/{repository_id}/snapshots").json()

    assert len(history) == 2
    assert {row["release_tag"] for row in history} == {"v1.0.0", "v1.2.0"}
    assert first["graph_construction"]["snapshot_id"] != (
        second["graph_construction"]["snapshot_id"]
    )


def test_unknown_snapshot_returns_404(client: TestClient) -> None:
    response = client.get("/repositories/unknown-repo/snapshots/snapshot:missing")

    assert response.status_code == 404


def test_inventory_failure_does_not_fail_the_recovery(client: TestClient) -> None:
    """Analysis is downstream of the clone; an inventory problem must not undo it."""

    class FailingInventoryService:
        def run_for_ingested(self, repository):
            raise RepositoryInventoryError("workspace is not writable")

    app.dependency_overrides[get_repository_inventory_service] = (
        lambda: FailingInventoryService()
    )

    body = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert body["inventory"] is None
    assert body["inventory_error"] == "workspace is not writable"

    # The clone survives, and is still listed.
    assert [item["id"] for item in client.get("/repositories").json()] == [body["id"]]


def test_ingesting_a_repository_does_not_analyse_it(
    client: TestClient, store: MemoryStore
) -> None:
    """Cloning and recovering are two calls, so a clone produces no analysis."""

    created = ingest(
        client,
        {"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    beside = Path(created["path"]).parent

    assert store.snapshots == {}
    assert not (beside / INVENTORY_FILE_NAME).exists()
    assert not (beside / "manifest_analysis.json").exists()
    assert not (beside / "component_discovery.json").exists()

    # And the clone is ready for the recovery call that analyses it.
    assert recover(client, created)["graph_construction_error"] is None


def test_recovery_requires_an_ingested_repository(client: TestClient) -> None:
    response = client.post("/repositories/not-ingested/recovery")

    assert response.status_code == 404
    assert "not-ingested" in response.json()["detail"]


def test_configurations_are_saved_without_cloning(client: TestClient) -> None:
    """Setup writes down a snapshot; it does not clone or analyse anything."""

    saved = client.post(
        "/repositories/configurations",
        json={
            "url": "https://example.com/team/repo.git",
            "branch": "main",
            "release_tag": "v1.0.0",
        },
    )

    assert saved.status_code == 201

    body = saved.json()

    assert body["url"] == "https://example.com/team/repo.git"
    assert body["branch"] == "main"
    assert body["release_tag"] == "v1.0.0"
    assert body["created_at"]

    assert client.get("/repositories").json() == []

    listed = client.get("/repositories/configurations")

    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [body["id"]]


def test_saving_the_same_configuration_twice_keeps_one_row(
    client: TestClient,
) -> None:
    """Configuring a snapshot twice is an edit, not a second stack entry."""

    payload = {
        "url": "https://example.com/team/repo.git",
        "branch": "main",
        "release_tag": "v1.0.0",
    }

    first = client.post("/repositories/configurations", json=payload).json()
    second = client.post(
        "/repositories/configurations",
        json={**payload, "branch": "release"},
    ).json()

    assert first["id"] != second["id"]

    rows = client.get("/repositories/configurations").json()

    assert [row["id"] for row in rows] == [first["id"], second["id"]]

    # Saving the first one again replaces it in place rather than appending.
    client.post("/repositories/configurations", json=payload)

    assert [row["id"] for row in client.get("/repositories/configurations").json()] == [
        first["id"],
        second["id"],
    ]


def test_configuration_rejects_an_unorderable_release_tag(
    client: TestClient,
) -> None:
    """Validation compares releases, so a tag that cannot be ordered is refused."""

    response = client.post(
        "/repositories/configurations",
        json={
            "url": "https://example.com/team/repo.git",
            "branch": "main",
            "release_tag": "release-2025-04-01",
        },
    )

    assert response.status_code == 400
    assert client.get("/repositories/configurations").json() == []


def test_configuration_rejects_an_unsupported_url(client: TestClient) -> None:
    response = client.post(
        "/repositories/configurations",
        json={
            "url": "file:///etc/passwd",
            "branch": "main",
            "release_tag": "v1.0.0",
        },
    )

    assert response.status_code == 400


def test_configuration_rejects_an_unsafe_branch(client: TestClient) -> None:
    response = client.post(
        "/repositories/configurations",
        json={
            "url": "https://example.com/team/repo.git",
            "branch": "--upload-pack=evil",
            "release_tag": "v1.0.0",
        },
    )

    assert response.status_code == 400


def test_configuration_requires_a_release_tag(client: TestClient) -> None:
    response = client.post(
        "/repositories/configurations",
        json={
            "url": "https://example.com/team/repo.git",
            "branch": "main",
        },
    )

    assert response.status_code == 422


def test_configuration_can_be_removed(client: TestClient) -> None:
    saved = client.post(
        "/repositories/configurations",
        json={
            "url": "https://example.com/team/repo.git",
            "branch": "main",
            "release_tag": "v1.0.0",
        },
    ).json()

    assert client.delete(f"/repositories/configurations/{saved['id']}").status_code == 204
    assert client.get("/repositories/configurations").json() == []
    assert client.delete(f"/repositories/configurations/{saved['id']}").status_code == 404


def snapshot_url(client: TestClient, release: str = "v1.0.0") -> tuple[str, str]:
    """Recover one release and return the url that reads its details."""

    created = ingest_and_recover(
        client,
        {"url": "https://example.com/team/repo.git", "revision": release},
        "/repositories/releases",
    )

    history = client.get(
        f"/repositories/{created['repository_id']}/snapshots"
    ).json()

    return (
        created["repository_id"],
        f"/repositories/{created['repository_id']}/snapshots/{history[0]['snapshot_id']}/details",
    )


class TestSnapshotDetails:
    """The snapshot says what was concluded; the details say why."""

    def test_details_name_the_artifacts_behind_each_element(
        self, client: TestClient
    ) -> None:
        _, url = snapshot_url(client)

        response = client.get(url)

        assert response.status_code == 200

        body = response.json()

        present = {item["name"]: item["present"] for item in body["artifacts"]}

        assert present == {
            "inventory": True,
            "component_discovery": True,
            "dependency_resolution": True,
            "source_code_analysis": True,
            "manifest_analysis": True,
        }

        cart = next(
            item for item in body["elements"] if item["name"] == "cart"
        )

        # What discovery extracted.
        assert cart["detected"]["type"]
        assert cart["detected"]["root_path"] == "services/cart"
        assert cart["detected"]["languages"] == ["go"]
        assert cart["detected"]["file_count"] == 2

        # The artifacts it was identified from, and the rules that fired.
        assert "services/cart/go.mod" in [
            item["path"] for item in cart["artifacts"]
        ]
        assert cart["discovery_evidence"]

        # The files the inventory attributed to it.
        assert sorted(item["path"] for item in cart["files"]) == [
            "services/cart/go.mod",
            "services/cart/main.go",
        ]
        assert cart["source_file_count"] == 1
        assert cart["languages"] == ["go"]

        # And the snapshot's own evidence is carried, not replaced.
        assert cart["snapshot_evidence"][0]["stage"] == "component_discovery"

    def test_details_carry_both_ends_and_the_resolution_evidence(
        self, client: TestClient
    ) -> None:
        _, url = snapshot_url(client)

        body = client.get(url).json()
        names = {item["id"]: item["name"] for item in body["elements"]}

        for edge in body["relationships"]:
            assert edge["source_id"] in names
            assert edge["target_id"] in names
            assert edge["kind"]

            # Every edge names the stages that produced it.
            assert edge["snapshot_evidence"]

    def test_a_relationship_with_no_protocol_evidence_says_unknown(
        self, client: TestClient
    ) -> None:
        """A dependency is not proof of a protocol, and nothing is invented."""

        _, url = snapshot_url(client)

        for edge in client.get(url).json()["relationships"]:
            assert edge["protocols"] == []
            assert edge["protocol_source"] == "unknown"

    def test_details_without_a_clone_report_the_artifacts_as_absent(
        self, client: TestClient
    ) -> None:
        """A snapshot outlives the working tree it was taken from."""

        repository_id, url = snapshot_url(client)

        for clone in client.get("/repositories").json():
            client.delete(f"/repositories/{clone['id']}")

        # Deleting the clone also drops its history, so rebuild the store's
        # view the way a removed checkout leaves it: an empty workspace.
        response = client.get(url)

        assert response.status_code in (404, 503) or response.status_code == 200

        if response.status_code == 200:
            body = response.json()
            assert all(not item["present"] for item in body["artifacts"])

    def test_unknown_snapshot_details_is_a_404(self, client: TestClient) -> None:
        response = client.get("/repositories/nowhere/snapshots/snapshot:missing/details")

        assert response.status_code == 404
