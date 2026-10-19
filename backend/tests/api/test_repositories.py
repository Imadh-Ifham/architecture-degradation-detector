import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.repositories import (
    get_architecture_snapshot_store,
    get_component_discovery_service,
    get_dependency_resolution_service,
    get_graph_construction_service,
    get_manifest_analysis_service,
    get_repository_ingestion_service,
    get_repository_inventory_service,
    get_source_code_analysis_service,
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

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


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
    created = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

    removed = client.delete(f"/repositories/{created['id']}")

    assert removed.status_code == 204
    assert client.get("/repositories").json() == []


def test_remove_unknown_repository_returns_404(client: TestClient) -> None:
    response = client.delete("/repositories/unknown-id")

    assert response.status_code == 404


def test_ingesting_a_repository_inventories_the_clone(client: TestClient) -> None:
    """A successful clone is inventoried automatically."""

    created = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

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


def test_ingesting_a_repository_analyzes_the_manifests(client: TestClient) -> None:
    """A successful clone is inventoried and then analyzed automatically."""

    created = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

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

    body = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

    assert body["inventory"] is None
    assert body["manifest_analysis"] is None
    assert "no repository inventory" in body["manifest_analysis_error"]


def test_analysis_failure_does_not_fail_the_ingest(client: TestClient) -> None:
    """A downstream failure must not undo the clone or the inventory."""

    class FailingAnalysisService:
        def run(self, inventory, root, output_directory):
            raise ManifestAnalysisError("analysis workspace is not writable")

    app.dependency_overrides[get_manifest_analysis_service] = (
        lambda: FailingAnalysisService()
    )

    response = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert response.status_code == 201

    body = response.json()

    assert body["inventory"] is not None
    assert body["manifest_analysis"] is None
    assert body["manifest_analysis_error"] == "analysis workspace is not writable"


def test_ingesting_a_repository_discovers_components(client: TestClient) -> None:
    """Component discovery runs automatically after its prerequisites."""

    created = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

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


def test_ingesting_a_repository_resolves_dependencies(client: TestClient) -> None:
    """Dependency resolution runs automatically after component discovery."""

    created = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

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


def test_ingesting_a_repository_analyzes_source_code(client: TestClient) -> None:
    """Source code analysis runs automatically after dependency resolution."""

    created = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

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

    created = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

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

    body = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

    assert body["dependency_resolution"] is None
    assert "no component discovery" in body["dependency_resolution_error"]
    assert body["manifest_analysis"] is not None


def test_dependency_resolution_failure_does_not_fail_the_ingest(
    client: TestClient,
) -> None:
    """A downstream failure must not undo the clone or the earlier stages."""

    class FailingDependencyService:
        def run(self, discovery, analysis, output_directory):
            raise DependencyResolutionError("dependency workspace is not writable")

    app.dependency_overrides[get_dependency_resolution_service] = (
        lambda: FailingDependencyService()
    )

    response = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert response.status_code == 201

    body = response.json()

    assert body["component_discovery"] is not None
    assert body["dependency_resolution"] is None
    assert (
        body["dependency_resolution_error"]
        == "dependency workspace is not writable"
    )
    assert body["source_code_analysis"] is None
    assert "no dependency resolution" in body["source_code_analysis_error"]


def test_source_analysis_failure_does_not_fail_the_ingest(
    client: TestClient,
) -> None:
    """A source analysis failure must not undo the clone or earlier stages."""

    class FailingSourceAnalysisService:
        def run(self, inventory, discovery, dependencies, root, output_directory):
            raise SourceCodeAnalysisError("source analysis workspace is not writable")

    app.dependency_overrides[get_source_code_analysis_service] = (
        lambda: FailingSourceAnalysisService()
    )

    response = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert response.status_code == 201

    body = response.json()

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

    body = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

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

    body = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

    assert body["component_discovery"] is None
    assert "no repository inventory" in body["component_discovery_error"]


def test_discovery_failure_does_not_fail_the_ingest(client: TestClient) -> None:
    """A downstream failure must not undo the clone or the earlier stages."""

    class FailingDiscoveryService:
        def run(self, inventory, analysis, output_directory):
            raise ComponentDiscoveryError("discovery workspace is not writable")

    app.dependency_overrides[get_component_discovery_service] = (
        lambda: FailingDiscoveryService()
    )

    response = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert response.status_code == 201

    body = response.json()

    assert body["inventory"] is not None
    assert body["manifest_analysis"] is not None
    assert body["component_discovery"] is None
    assert body["component_discovery_error"] == "discovery workspace is not writable"


def test_ingesting_a_release_records_a_snapshot(
    client: TestClient, store: MemoryStore
) -> None:
    """A tag can be analyzed on its own, and the snapshot is retrievable."""

    created = client.post(
        "/repositories/releases",
        json={"url": "https://example.com/team/repo.git", "revision": "v1.0.0"},
    ).json()

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

    first = client.post(
        "/repositories/releases",
        json={"url": "https://example.com/team/repo.git", "revision": "v1.0.0"},
    ).json()
    second = client.post(
        "/repositories/releases",
        json={"url": "https://example.com/team/repo.git", "revision": "v1.2.0"},
    ).json()

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


def test_inventory_failure_does_not_fail_the_ingest(client: TestClient) -> None:
    """The clone is the primary operation; an inventory problem must not undo it."""

    class FailingInventoryService:
        def run_for_ingested(self, repository):
            raise RepositoryInventoryError("workspace is not writable")

    app.dependency_overrides[get_repository_inventory_service] = (
        lambda: FailingInventoryService()
    )

    response = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    )

    assert response.status_code == 201

    body = response.json()

    assert body["inventory"] is None
    assert body["inventory_error"] == "workspace is not writable"

    # The clone survives, and is still listed.
    assert [item["id"] for item in client.get("/repositories").json()] == [body["id"]]
