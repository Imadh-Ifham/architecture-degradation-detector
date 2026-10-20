"""Degradation detection endpoint tests.

Description:
    The routes over the real component, with in-memory stores in place of
    PostgreSQL and C2's file store pointed at a temporary directory - so a run
    reads published graphs exactly as the application does.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import degradation
from app.components.degradation_detection import DegradationDetectionService
from app.components.degradation_detection.config import (
    CONFIG_DIR,
    DEFAULT_CATALOG_PATH,
    load_config,
)
from app.components.degradation_scoring.ingestion.events import ingest_events
from app.components.degradation_scoring.ingestion.graph import build_graph
from app.infrastructure.validated_graph import ValidatedGraphFileStore
from app.main import app
from tests.components.degradation_detection.fakes import (
    FixedClock,
    InMemoryAnalysisRunRepository,
    InMemoryReleaseRepository,
)

REPOSITORY = "shop-1"


def publish(root: Path, index: int, *, dated: bool = True) -> None:
    services = [f"s{i}" for i in range(index + 3)]
    links = [
        {"source": a, "target": b, "relationship": "depends-on", "bucket": "confirmed"}
        for a, b in zip(services, services[1:], strict=False)
    ]
    document: dict[str, Any] = {
        "graph": {
            "repository_id": REPOSITORY,
            "release_id": f"v1.{index}.0",
            "released_at": f"2025-0{index + 1}-01T00:00:00+00:00" if dated else None,
            "architecture_style": "generic",
            "validation_confidence": 0.9,
            "run": {"run_id": f"c2-{index}"},
        },
        "nodes": [{"id": s, "name": s, "kind": "module"} for s in services],
        "links": links,
    }
    directory = root / REPOSITORY / f"v1.{index}.0"
    directory.mkdir(parents=True)
    (directory / "latest.graph.json").write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture
def published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    service = DegradationDetectionService(
        InMemoryReleaseRepository(),
        InMemoryAnalysisRunRepository(),
        FixedClock(),
        load_config(CONFIG_DIR / "demo.yaml", DEFAULT_CATALOG_PATH),
    )
    monkeypatch.setattr(degradation, "get_service", lambda: service)
    monkeypatch.setattr(degradation, "get_graph_store", lambda: ValidatedGraphFileStore(tmp_path))
    monkeypatch.setattr(degradation, "code_version", lambda: "test")
    monkeypatch.setattr(degradation.settings, "degradation_outputs_root", tmp_path / "out")
    return tmp_path


client = TestClient(app)


def test_a_run_reads_every_published_release_and_returns_the_view(published: Path) -> None:
    for index in range(3):
        publish(published, index)
    publish(published, 3, dated=False)

    response = client.post("/degradation/runs", json={"repository_id": REPOSITORY})

    assert response.status_code == 200
    body = response.json()
    refused = [o for o in body["ingest"] if not o["accepted"]]
    assert [(o["release_id"], o["reason"]) for o in refused] == [("v1.3.0", "RELEASE_UNDATED")]
    assert [r["release_id"] for r in body["report"]["releases"]] == ["v1.0.0", "v1.1.0", "v1.2.0"]

    latest = client.get("/degradation/runs/latest", params={"repository_id": REPOSITORY})
    assert latest.status_code == 200
    assert latest.json()["run"]["run_id"] == body["report"]["run"]["run_id"]

    by_id = client.get(f"/degradation/runs/{body['report']['run']['run_id']}")
    assert by_id.json() == latest.json()


def test_nothing_validated_is_a_404_with_a_sentence(published: Path) -> None:
    response = client.post("/degradation/runs", json={"repository_id": REPOSITORY})

    assert response.status_code == 404
    assert "validated" in response.json()["detail"]


def test_nothing_ingestible_is_a_409_that_says_why(published: Path) -> None:
    publish(published, 0, dated=False)

    response = client.post("/degradation/runs", json={"repository_id": REPOSITORY})

    assert response.status_code == 409
    assert response.json()["detail"]["ingest"][0]["reason"] == "RELEASE_UNDATED"


def test_no_run_yet_is_a_404(published: Path) -> None:
    assert client.get("/degradation/runs/latest", params={"repository_id": "x"}).status_code == 404
    assert client.get("/degradation/runs/RUN-missing").status_code == 404


def test_a_run_leaves_the_files_the_scoring_phase_reads(published: Path) -> None:
    for index in range(3):
        publish(published, index)

    body = client.post("/degradation/runs", json={"repository_id": REPOSITORY}).json()
    handover = body["report"]["handover"]

    # What scripts/c4_rank.py is pointed at: --events and --graph, run and latest.
    for key in ("events", "graph", "latest_events", "latest_graph"):
        assert handover[key] and Path(handover[key]).is_file()
    events = json.loads(Path(handover["latest_events"]).read_text(encoding="utf-8"))
    package = json.loads(Path(handover["latest_graph"]).read_text(encoding="utf-8"))

    # Read with C4's own readers, so a change on either side fails here.
    assert ingest_events(events, rank_only_confirmed=False).quarantined == []
    graph = build_graph(package, reverse=False)
    assert graph.graph["release_id"] == "v1.2.0"
    assert set(graph.nodes) == {"s0", "s1", "s2", "s3", "s4"}

    latest = client.get("/degradation/runs/latest", params={"repository_id": REPOSITORY})
    assert latest.json()["handover"] == handover
