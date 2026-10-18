# Tests for the features service (C4-T11): the package export and extract() on the fixtures.

from typing import Any

import pytest

from app.components.degradation_scoring import features
from app.components.degradation_scoring.features import blast_radius as br
from app.components.degradation_scoring.features.service import FeatureExtractionService
from app.components.degradation_scoring.ingestion.graph import build_graph
from app.components.degradation_scoring.ingestion.service import IngestionService
from tests.components.degradation_scoring.support import default_config, load_fixture

GRAPH = build_graph(load_fixture("graphs/fixture_release_package.v1.5.0.json"), reverse=False)
RESOLVED = (
    IngestionService(default_config())
    .ingest(load_fixture("events/fixture_events.v1.json"), GRAPH)
    .resolved
)


def test_package_exports_only_the_service() -> None:
    assert features.__all__ == ["FeatureExtractionService"]
    assert features.FeatureExtractionService is FeatureExtractionService


def test_extract_returns_one_row_per_resolved_event_in_order() -> None:
    rows = FeatureExtractionService(default_config()).extract(RESOLVED, GRAPH)
    expected = load_fixture("fixture_expected.json")["counts"]["ranked"]

    assert [row.event_id for row in rows] == [item.event.event_id for item in RESOLVED]
    assert len(rows) == expected


def test_extract_matches_the_pure_function() -> None:
    rows = FeatureExtractionService(default_config()).extract(RESOLVED, GRAPH)
    c = br.compute_centralities(GRAPH, alpha=0.85, exact_max_nodes=5000, sample_k=500, seed=42)

    for item, row in zip(RESOLVED, rows, strict=True):
        assert row.blast_radius == br.blast_radius(GRAPH, item.nodes, c)


def test_settings_reach_the_computation() -> None:
    config = default_config(betweenness_exact_max_nodes=10, betweenness_sample_k=5, seed=7)
    rows = FeatureExtractionService(config).extract(RESOLVED, GRAPH)

    assert all(row.blast_radius.betweenness_sampled for row in rows)


def test_centralities_are_computed_once_per_release(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = br.compute_centralities

    def counting(graph: Any, **kwargs: Any) -> br.GraphCentralities:
        calls.append(graph.graph["release_id"])
        return real(graph, **kwargs)

    monkeypatch.setattr(br, "compute_centralities", counting)
    service = FeatureExtractionService(default_config())

    service.extract(RESOLVED, GRAPH)
    service.extract(RESOLVED[:2], GRAPH)

    assert calls == ["v1.5.0"]


def test_no_events_means_no_work() -> None:
    assert FeatureExtractionService(default_config()).extract([], GRAPH) == []


def test_events_from_two_releases_are_refused() -> None:
    other = RESOLVED[1].model_copy(
        update={
            "event": RESOLVED[1].event.model_copy(
                update={
                    "window": RESOLVED[1].event.window.model_copy(update={"end_release": "v1.4.0"})
                }
            )
        }
    )

    with pytest.raises(ValueError, match="several"):
        FeatureExtractionService(default_config()).extract([RESOLVED[0], other], GRAPH)
