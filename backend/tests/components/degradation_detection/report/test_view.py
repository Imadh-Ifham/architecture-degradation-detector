"""C2's published graphs -> a stored run -> the document the drift screen reads."""

from typing import Any

from app.components.degradation_detection import DegradationDetectionService
from app.components.degradation_detection.config import (
    CONFIG_DIR,
    DEFAULT_CATALOG_PATH,
    load_config,
)
from app.components.degradation_detection.ingestion.from_validated import RELEASE_UNDATED
from app.components.degradation_detection.ingestion.models import IngestStatus
from app.components.degradation_detection.report.view import OFF_MAIN_LINE
from tests.components.degradation_detection.fakes import (
    FixedClock,
    InMemoryAnalysisRunRepository,
    InMemoryReleaseRepository,
)

DEMO = load_config(CONFIG_DIR / "demo.yaml", DEFAULT_CATALOG_PATH)
SYSTEM = "shop-1"


def release(index: int, release_id: str | None = None, *, dated: bool = True) -> dict[str, Any]:
    """Release ``index`` of a system whose services couple into one cycle that keeps growing."""
    services = [f"s{i}" for i in range(index + 3)]
    links = [
        {"source": a, "target": b, "relationship": "depends-on", "bucket": "confirmed"}
        for a, b in zip(services, services[1:], strict=False)
    ]
    # From the second release on, the last service calls back into the first: a cycle whose
    # membership grows by one service per release.
    if index >= 1:
        links.append(
            {"source": services[-1], "target": "s0", "relationship": "depends-on", "bucket": "x"}
        )
    return {
        "graph": {
            "repository_id": SYSTEM,
            "release_id": release_id or f"v1.{index}.0",
            "released_at": f"2025-0{index + 1}-01T00:00:00+00:00" if dated else None,
            "architecture_style": "generic",
            "validation_confidence": 0.9,
            "run": {"run_id": f"c2-{index}"},
        },
        "nodes": [{"id": s, "name": s, "kind": "module", "size": 10.0} for s in services],
        "links": links,
    }


def detect(documents: list[dict[str, Any]]) -> tuple[DegradationDetectionService, Any]:
    service = DegradationDetectionService(
        InMemoryReleaseRepository(), InMemoryAnalysisRunRepository(), FixedClock(), DEMO
    )
    ingest = service.ingest_validated(documents)
    result = service.run(SYSTEM, code_version="test")
    return service, (ingest, result)


def test_the_demo_config_differs_from_the_research_one_only_in_min_releases() -> None:
    research = load_config()

    assert DEMO.trend.min_releases == 3
    assert DEMO.model_dump() | {"trend": None} == research.model_dump() | {"trend": None}
    assert DEMO.config_hash != research.config_hash


def test_each_published_graph_is_reported_on_the_way_in() -> None:
    _, (ingest, _) = detect(
        [release(0), release(1), release(2), release(3, dated=False), release(4, "nightly")]
    )

    statuses = {o.release_id: (o.status, o.reason) for o in ingest.outcomes}
    assert statuses["v1.3.0"] == (IngestStatus.REJECTED, RELEASE_UNDATED)
    assert statuses["v1.0.0"] == (IngestStatus.STORED, None)
    assert statuses["nightly"] == (IngestStatus.STORED, None)


def test_view_lists_the_timeline_in_order_then_what_is_off_it() -> None:
    service, (_, result) = detect([release(2), release(0), release(4, "nightly"), release(1)])

    view = service.view(result.stored.run.run_id)

    assert [(r["release_id"], r["ordinal"]) for r in view["releases"]] == [
        ("v1.0.0", 0),
        ("v1.1.0", 1),
        ("v1.2.0", 2),
        ("nightly", None),
    ]
    assert view["releases"][-1]["absent_because"] == OFF_MAIN_LINE
    assert view["run"]["trend"]["min_releases"] == 3


def test_view_carries_each_release_graph_and_its_anti_patterns() -> None:
    service, (_, result) = detect([release(0), release(1), release(2), release(3)])

    view = service.view(result.stored.run.run_id)
    by_id = {r["release_id"]: r for r in view["releases"]}

    first, last = by_id["v1.0.0"], by_id["v1.3.0"]
    assert len(last["elements"]) == 6
    assert all(e["lineage_id"] for e in last["elements"])
    assert "CyclicDependency" in last["detectors_run"]
    assert not [i for i in first["instances"] if i["anti_pattern_type"] == "CyclicDependency"]
    [cycle] = [i for i in last["instances"] if i["anti_pattern_type"] == "CyclicDependency"]
    assert cycle["track_id"] and cycle["transition"] == "GREW"
    assert last["element_metrics"]["s0"]
    assert last["system_metrics"]


def test_view_carries_trends_untested_series_and_tracks_without_recomputing() -> None:
    service, (_, result) = detect([release(0), release(1), release(2), release(3)])

    view = service.view(result.stored.run.run_id)
    outputs = result.stored.outputs

    assert len(view["trends"]) == len(outputs.trends) > 0
    assert len(view["untested"]) == len(outputs.untested)
    assert len(view["events"]) == len(outputs.events)
    assert {t["track_id"] for t in view["tracks"]}
    # Exact Mann-Kendall on 4 points cannot reach q <= 0.05, so nothing is an event yet.
    assert all(t["n"] <= 4 for t in view["trends"])
    assert view["events"] == []


def test_latest_run_id_is_the_newest_completed_run() -> None:
    service, (_, result) = detect([release(0), release(1), release(2)])

    assert service.latest_run_id(SYSTEM) == result.stored.run.run_id
    assert service.latest_run_id("another") is None
