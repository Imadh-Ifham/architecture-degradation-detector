# Tests for the degradation scoring service (C4-T16b): layers 1-2 on the fixtures and the
# plain rows saved for inspection (c4_scoring_run, c4_event_ingestion, c4_event_features),
# and the scoring engine's input built from the features (C4-T17).

from typing import Any

import pytest

from app.components import degradation_scoring
from app.components.degradation_scoring.features.models import HotspotFeatures
from app.components.degradation_scoring.service import DegradationScoringService, scoring_inputs
from app.domain.severity_report import Dimension
from tests.components.degradation_scoring.support import (
    FakeRunRepository,
    adr_index_document,
    default_config,
    load_fixture,
)

PAYLOADS: list[Any] = load_fixture("events/fixture_events.v1.json")
GRAPH_DOC = load_fixture("graphs/fixture_release_package.v1.5.0.json")
EXPECTED: dict[str, Any] = load_fixture("fixture_expected.json")
DESIGNED_AV: dict[str, Any] = load_fixture("adr/adr_links.v1.json")["designed_av"]


def run(**kwargs: Any) -> tuple[Any, FakeRunRepository]:
    repo = FakeRunRepository()
    service = DegradationScoringService(default_config(), run_repository=repo)
    result = service.run_features(
        PAYLOADS, GRAPH_DOC, run_id="test-run", data_provenance="fixture", **kwargs
    )
    return result, repo


def test_package_exports_only_the_service() -> None:
    assert degradation_scoring.__all__ == ["DegradationScoringService"]
    assert degradation_scoring.DegradationScoringService is DegradationScoringService


def test_run_row_has_the_designed_counts() -> None:
    result, repo = run()
    ((run_row, _, _),) = repo.saved
    counts = EXPECTED["counts"]

    assert (result.system_id, result.release_id) == ("c4-fixture-shop", "v1.5.0")
    assert run_row["run_id"] == "test-run"
    assert run_row["payloads"] == counts["payloads"]
    assert run_row["ranked"] == counts["ranked"]
    assert run_row["skipped"] == sum(counts["skipped"].values())
    assert run_row["quarantined"] == sum(counts["quarantined"].values())
    assert run_row["resolution_rate"] == counts["resolution_rate"]
    assert run_row["data_provenance"] == "fixture"


def test_one_ingestion_row_per_payload_in_order() -> None:
    _, repo = run()
    ((_, rows, _),) = repo.saved

    assert [row["payload_index"] for row in rows] == list(range(len(PAYLOADS)))
    designed = {e["event_id"]: e["outcome"] for e in EXPECTED["events"]}
    for row in rows:
        if row["event_id"] in designed:
            outcome, _, reason = designed[row["event_id"]].partition(":")
            assert row["outcome"] == outcome, row["event_id"]
            assert (row["reason"] or "") == reason, row["event_id"]


def test_malformed_payloads_keep_their_position() -> None:
    _, repo = run()
    ((_, rows, _),) = repo.saved

    for malformed in EXPECTED["malformed"]:
        row = rows[malformed["index"]]
        assert row["outcome"] == "quarantined"
        assert row["reason"] == "malformed_payload"
        assert row["event_id"] == malformed["event_id"]
        assert row["detail"]


def test_ranked_rows_carry_nodes_and_resolution() -> None:
    _, repo = run()
    ((_, rows, _),) = repo.saved
    by_id = {row["event_id"]: row for row in rows}

    cycle = by_id["DEG-C4FX-R02-0001"]
    assert cycle["nodes"] == sorted(EXPECTED["graph"]["cycle"])
    assert (cycle["resolution_status"], cycle["resolution_confidence"]) == ("exact", 1.0)
    prefix = by_id["DEG-C4FX-R02-0007"]
    assert (prefix["resolution_status"], prefix["resolution_confidence"]) == (
        "prefix_fallback",
        0.7,
    )
    unresolved = by_id["DEG-C4FX-R02-0009"]
    assert (unresolved["outcome"], unresolved["reason"]) == ("quarantined", "unresolved_element")
    assert unresolved["nodes"] == []


def test_feature_rows_without_repo_or_adr_index() -> None:
    result, repo = run()
    ((run_row, _, rows),) = repo.saved

    assert len(rows) == EXPECTED["counts"]["ranked"]
    assert (run_row["hotspot_active"], run_row["hotspot_inactive_reason"]) == (
        False,
        "no_repository",
    )
    assert (run_row["adr_active"], run_row["adr_inactive_reason"]) == (False, "no_adr_index")
    for row, features in zip(rows, result.features.events, strict=True):
        assert row["br_pagerank"] == features.blast_radius.pagerank
        assert row["ps_growth_slope"] == features.persistence.growth_slope
        assert row["eh_churn_decayed"] is None
        assert row["av_weight"] is None


def test_feature_rows_with_the_fixture_adr_index() -> None:
    _, repo = run(adr_document=adr_index_document())
    ((run_row, _, rows),) = repo.saved

    details = run_row["details"]
    assert isinstance(details, dict)
    assert run_row["adr_active"]
    assert details["adr_status_weights"]["accepted"] == 1.0
    got = {row["event_id"]: row["av_weight"] for row in rows}
    assert got == pytest.approx({event_id: d["av"] for event_id, d in DESIGNED_AV.items()})


def test_without_a_repository_nothing_is_saved() -> None:
    service = DegradationScoringService(default_config())

    result = service.run_features(PAYLOADS, GRAPH_DOC, run_id="r", data_provenance="fixture")

    assert len(result.features.events) == EXPECTED["counts"]["ranked"]


def test_every_row_column_exists_in_the_tables() -> None:
    from app.infrastructure.postgres.models.c4_scoring_run import (
        c4_event_features,
        c4_event_ingestion,
        c4_scoring_run,
    )

    _, repo = run(adr_document=adr_index_document())
    ((run_row, ingestion, features),) = repo.saved

    assert set(run_row) == set(c4_scoring_run.c.keys())
    assert set(ingestion[0]) == set(c4_event_ingestion.c.keys())
    assert set(features[0]) == set(c4_event_features.c.keys())


def test_scoring_inputs_match_the_saved_feature_rows() -> None:
    result, repo = run(adr_document=adr_index_document())
    ((_, _, rows),) = repo.saved
    active, events = scoring_inputs(result.features)
    assert active == [Dimension.BLAST_RADIUS, Dimension.ADR_VIOLATION, Dimension.PERSISTENCE]
    for row, item in zip(rows, events, strict=True):
        assert item.event_id == row["event_id"]
        assert item.values == {key: row[key] for key in item.values}
        assert not any(key.startswith("eh_") for key in item.values)


def test_scoring_inputs_with_hotspot_active() -> None:
    result, _ = run()
    hotspot = HotspotFeatures(
        churn_decayed=4.5,
        authors=2,
        coupling=1,
        bugfix_ratio=0.5,
        commits=2,
        from_release="v1.4.0",
        to_release="v1.5.0",
        first_seen_fallback=True,
        paths_available=True,
    )
    features = result.features.model_copy(
        update={
            "hotspot": result.features.hotspot.model_copy(update={"active": True}),
            "events": [e.model_copy(update={"hotspot": hotspot}) for e in result.features.events],
        }
    )
    active, events = scoring_inputs(features)
    assert active == [Dimension.BLAST_RADIUS, Dimension.HOTSPOT, Dimension.PERSISTENCE]
    assert events[0].values["eh_churn_decayed"] == 4.5
    assert events[0].values["eh_coupling"] == 1.0
