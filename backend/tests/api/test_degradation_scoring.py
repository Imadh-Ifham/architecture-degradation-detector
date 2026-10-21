# Tests for the degradation scoring (C4) API: run list newest first, a run's report equal to
# the saved file, scoring a detection run (POST), and the 404 / 409 / 422 / 500 / 503 answers.
# Reads and writes temporary roots.
# The router runs in its own small app (so mypy stays inside C4); one test checks app.main.

import importlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api import degradation_scoring
from app.api.degradation_scoring import (
    get_degradation_scoring_service,
    get_run_service,
    history_inputs,
    repository_name,
    router,
)
from app.components.degradation_scoring import DegradationScoringService
from app.core.config import settings
from app.domain.severity_report import SeverityReportV1
from app.infrastructure.scoring_reports import DetectionHandoverFiles, ScoringReportFileStore
from tests.components.degradation_scoring.saved_runs import save_run
from tests.components.degradation_scoring.support import (
    FakeRunRepository,
    default_config,
    load_fixture,
)

app = FastAPI()
app.include_router(router)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "scoring"


@pytest.fixture
def client(root: Path) -> Iterator[TestClient]:
    service = DegradationScoringService(
        default_config(), saved_reports=ScoringReportFileStore(root)
    )
    app.dependency_overrides[get_degradation_scoring_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_no_runs_yet_is_an_empty_list(client: TestClient) -> None:
    response = client.get("/degradation-scoring/runs")

    assert response.status_code == 200
    assert response.json() == []


def test_runs_list_newest_first(client: TestClient, root: Path) -> None:
    save_run(root, "older", created_at="2026-10-18T10:00:00+00:00")
    save_run(root, "newer", created_at="2026-10-19T10:00:00+00:00", system_id="online-boutique")

    body = client.get("/degradation-scoring/runs").json()

    assert [run["run_id"] for run in body] == ["newer", "older"]
    assert body[1] == {
        "run_id": "older",
        "system_id": "c4-fixture-shop",
        "release_id": "v1.5.0",
        "data_provenance": "fixture",
        "active_dimensions": ["blast_radius", "adr_violation", "persistence"],
        "counts": {"payloads": 17, "ranked": 9, "skipped": 4, "quarantined": 4},
        "resolution_rate": 0.9,
        "created_at": "2026-10-18T10:00:00Z",
    }


def test_report_equals_the_saved_file(client: TestClient, root: Path) -> None:
    saved = save_run(root, "run-a")

    response = client.get("/degradation-scoring/runs/run-a/report")

    assert response.status_code == 200
    expected = SeverityReportV1.model_validate(saved).model_dump(mode="json")
    assert response.json() == expected
    assert [record["rank"] for record in response.json()["records"]] == list(range(1, 10))


def test_unknown_run_is_404(client: TestClient) -> None:
    response = client.get("/degradation-scoring/runs/missing/report")

    assert response.status_code == 404
    assert response.json()["detail"] == "no saved run 'missing'"


def test_run_id_in_two_systems_is_409(client: TestClient, root: Path) -> None:
    save_run(root, "run-a")
    save_run(root, "run-a", system_id="online-boutique")

    response = client.get("/degradation-scoring/runs/run-a/report")

    assert response.status_code == 409
    assert "several systems" in response.json()["detail"]


def test_bad_run_id_is_422(client: TestClient) -> None:
    assert client.get("/degradation-scoring/runs/.hidden/report").status_code == 422


def test_report_breaking_the_contract_is_500(client: TestClient, root: Path) -> None:
    save_run(root, "run-a")
    path = root / "c4-fixture-shop" / "run-a" / "c4_report.json"
    report = json.loads(path.read_text(encoding="utf-8")) | {"resolution_rate": 2.0}
    path.write_text(json.dumps(report), encoding="utf-8")

    response = client.get("/degradation-scoring/runs/run-a/report")

    assert response.status_code == 500
    assert "breaks SeverityReportV1" in response.json()["detail"]


def test_router_is_mounted_in_the_main_app() -> None:
    main = importlib.import_module("app.main").app

    assert "/degradation-scoring/runs/{run_id}/report" in main.openapi()["paths"]


def test_the_only_write_is_scoring_a_detection_run() -> None:
    paths = {p: ops for p, ops in app.openapi()["paths"].items() if "degradation-scoring" in p}

    assert {p: sorted(ops) for p, ops in paths.items()} == {
        "/degradation-scoring/runs": ["get", "post"],
        "/degradation-scoring/runs/{run_id}/report": ["get"],
        "/degradation-scoring/runs/{run_id}/files/{name}": ["get"],
    }


# POST /degradation-scoring/runs: score a detection run's hand-over

SYSTEM = "c4-fixture-shop"


@pytest.fixture
def scoring_client(tmp_path: Path) -> Iterator[TestClient]:
    folder = tmp_path / "degradation" / SYSTEM / "RUN-a"
    folder.mkdir(parents=True)
    events = load_fixture("events/fixture_events.v1.json")
    package = load_fixture("graphs/fixture_release_package.v1.5.0.json")
    (folder / "events.json").write_text(json.dumps(events), encoding="utf-8")
    (folder / "release_package.json").write_text(json.dumps(package), encoding="utf-8")
    config = default_config().model_copy(update={"outputs_root": tmp_path / "scoring"})
    service = DegradationScoringService(
        config,
        run_repository=FakeRunRepository(),
        saved_reports=ScoringReportFileStore(tmp_path / "scoring"),
        detection_handover=DetectionHandoverFiles(tmp_path / "degradation"),
    )
    app.dependency_overrides[get_run_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_scoring_a_detection_run_returns_its_ranking(scoring_client: TestClient) -> None:
    body = {"repository_id": SYSTEM, "detection_run_id": "RUN-a"}

    response = scoring_client.post("/degradation-scoring/runs", json=body)

    assert response.status_code == 200
    assert response.json()["run_id"] == "score-RUN-a"
    assert response.json()["data_provenance"] == "live"
    assert scoring_client.post("/degradation-scoring/runs", json=body).json() == response.json()


def test_scoring_a_run_without_a_handover_is_404(scoring_client: TestClient) -> None:
    body = {"repository_id": SYSTEM, "detection_run_id": "RUN-missing"}

    response = scoring_client.post("/degradation-scoring/runs", json=body)

    assert response.status_code == 404
    assert "RUN-missing" in response.json()["detail"]


@pytest.mark.parametrize("bad", [{"repository_id": "../x", "detection_run_id": "RUN-a"}, {}])
def test_scoring_with_bad_ids_is_422(scoring_client: TestClient, bad: dict[str, str]) -> None:
    assert scoring_client.post("/degradation-scoring/runs", json=bad).status_code == 422


def test_scoring_without_the_database_is_503() -> None:
    class Down:
        def score_detection(self, *args: object, **kwargs: object) -> None:
            raise OperationalError("connect", {}, Exception("down"))

    app.dependency_overrides[get_run_service] = lambda: Down()
    try:
        response = TestClient(app).post(
            "/degradation-scoring/runs", json={"repository_id": SYSTEM, "detection_run_id": "R"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503


def test_repository_name_drops_the_url_hash() -> None:
    assert repository_name("microservices-demo-65bf2e173bd5") == "microservices-demo"
    assert repository_name("online-boutique") == "online-boutique"


def test_history_inputs_need_both_the_clone_and_the_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "repositories_root", tmp_path)
    monkeypatch.setattr(degradation_scoring, "SOURCE_PATHS_DIR", tmp_path / "maps")
    assert history_inputs("shop-0123456789ab") == {}

    (tmp_path / "c4-history" / "shop" / ".git").mkdir(parents=True)
    assert history_inputs("shop-0123456789ab") == {}

    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "shop.json").write_text(
        json.dumps({"data_provenance": "manual-mapping", "elements": {"a": ["src/a/**"]}}),
        encoding="utf-8",
    )
    assert history_inputs("shop-0123456789ab") == {
        "repo_path": tmp_path / "c4-history" / "shop",
        "source_paths": {"a": ["src/a/**"]},
        "path_mapping": "manual-mapping",
    }


def test_code_commit_is_a_sha_or_none() -> None:
    commit = degradation_scoring.code_commit()

    assert commit is None or len(commit) == 40


# GET /degradation-scoring/runs/{run_id}/files/{name}: a saved run's files, unchanged


def test_run_files_come_back_unchanged_with_their_type(client: TestClient, root: Path) -> None:
    save_run(root, "run-a")
    (root / "c4-fixture-shop" / "run-a" / "c4_report.html").write_text("<html>", "utf-8")

    page = client.get("/degradation-scoring/runs/run-a/files/c4_report.html")
    report = client.get("/degradation-scoring/runs/run-a/files/c4_report.json")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.text == "<html>"
    assert report.headers["content-type"] == "application/json"
    assert report.json()["run_id"] == "run-a"


def test_a_missing_run_file_is_404(client: TestClient, root: Path) -> None:
    save_run(root, "run-a")

    response = client.get("/degradation-scoring/runs/run-a/files/c4_quarantine.json")

    assert response.status_code == 404


def test_only_the_run_files_can_be_asked_for(client: TestClient) -> None:
    assert client.get("/degradation-scoring/runs/run-a/files/logs").status_code == 422


def test_a_run_file_of_an_id_in_two_systems_is_409(client: TestClient, root: Path) -> None:
    save_run(root, "run-a")
    save_run(root, "run-a", system_id="online-boutique")

    response = client.get("/degradation-scoring/runs/run-a/files/c4_report.json")

    assert response.status_code == 409
