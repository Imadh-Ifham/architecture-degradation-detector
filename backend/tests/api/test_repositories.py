from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.repositories import (
    get_component_discovery_service,
    get_manifest_analysis_service,
    get_repository_ingestion_service,
    get_repository_inventory_service,
)
from app.components.architecture_recovery.component_discovery import (
    ComponentDiscoveryError,
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
from app.main import app


class StubGitClient:
    """Writes a small working tree instead of cloning a repository."""

    commit = "a" * 40

    def clone(self, url: str, branch: str, destination: Path) -> None:
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

    def head_commit(self, repository: Path) -> str:
        return self.commit


@pytest.fixture
def client(tmp_path: Path):
    service = RepositoryIngestionService(git_client=StubGitClient(), root=tmp_path)
    app.dependency_overrides[get_repository_ingestion_service] = lambda: service

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


def test_previous_response_fields_are_unchanged(client: TestClient) -> None:
    """Adding component discovery must not disturb the earlier stages' output."""

    created = client.post(
        "/repositories",
        json={"url": "https://example.com/team/repo.git", "branch": "main"},
    ).json()

    # The ingestion fields are still present and correct.
    assert created["url"] == "https://example.com/team/repo.git"
    assert created["branch"] == "main"
    assert created["commit"] == "a" * 40

    # And so are both earlier analysis stages.
    assert created["inventory_error"] is None
    assert created["manifest_analysis_error"] is None
    assert created["inventory"]["file_count"] == 4
    assert created["manifest_analysis"]["resource_count"] == 2


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
