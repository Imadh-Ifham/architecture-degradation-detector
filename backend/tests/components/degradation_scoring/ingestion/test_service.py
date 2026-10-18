# Tests for the ingestion service entry point: the whole of Layer 1 on the fixtures.

from typing import Any

from app.components.degradation_scoring import ingestion
from app.components.degradation_scoring.ingestion.graph import GraphLoader
from app.components.degradation_scoring.ingestion.service import IngestionService
from tests.components.degradation_scoring.support import (
    FakeEventSource,
    FakeGraphSource,
    default_config,
    load_fixture,
)

EXPECTED: dict[str, Any] = load_fixture("fixture_expected.json")


def run(**overrides: Any) -> Any:
    events = FakeEventSource(load_fixture("events/fixture_events.v1.json"))
    graphs = FakeGraphSource({"v1.5.0": load_fixture("graphs/fixture_release_package.v1.5.0.json")})
    graph = GraphLoader(graphs, reverse=False).load("c4-fixture-shop", "v1.5.0")
    return IngestionService(default_config(**overrides)).ingest(
        events.fetch("c4-fixture-shop", "v1.5.0"), graph
    )


def test_package_exports_only_the_service() -> None:
    assert ingestion.__all__ == ["IngestionService"]
    assert ingestion.IngestionService is IngestionService


def test_fixtures_produce_every_designed_count() -> None:
    result = run()
    counts = EXPECTED["counts"]
    ranked = [row["event_id"] for row in EXPECTED["events"] if row["outcome"] == "ranked"]

    assert result.quarantine_counts() == counts["quarantined"]
    assert result.skip_counts() == counts["skipped"]
    assert len(result.eligible) == counts["eligible"]
    assert [r.event.event_id for r in result.resolved] == ranked
    assert result.resolution_rate == counts["resolution_rate"]


def test_confirmed_only_switch_comes_from_the_settings() -> None:
    result = run(rank_only_confirmed=True)

    assert [r.event.event_id for r in result.resolved] == EXPECTED["confirmed_event_ids"]


def test_prefix_confidence_comes_from_the_settings() -> None:
    result = run(resolution_prefix_confidence=0.6)
    fallback = [r for r in result.resolved if str(r.resolution.status) == "prefix_fallback"]

    assert [r.resolution.confidence for r in fallback] == [0.6]
