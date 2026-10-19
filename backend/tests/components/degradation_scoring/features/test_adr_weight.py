# Tests for the ADR-violation weight (C4-T16, FR-06): AV = status x scope x explicitness,
# max over C2-linked ADRs, 0 without a link, inactive without an index.

from typing import Any

import pytest
from structlog.testing import capture_logs

from app.components.degradation_scoring.features.adr_weight import (
    SCOPE_WEIGHTS,
    STATUS_WEIGHTS,
    adr_context,
    adr_weight,
    event_adr_weight,
)
from app.components.degradation_scoring.features.service import FeatureExtractionService
from app.components.degradation_scoring.ingestion.adr import parse_index
from app.components.degradation_scoring.ingestion.graph import build_graph
from app.components.degradation_scoring.ingestion.service import IngestionService
from app.components.degradation_scoring.models import AdrIndex, AdrRecord
from tests.components.degradation_scoring.support import (
    adr_index_document,
    default_config,
    load_fixture,
)

INDEX = parse_index(adr_index_document())
DESIGNED: dict[str, Any] = load_fixture("adr/adr_links.v1.json")["designed_av"]
GRAPH = build_graph(load_fixture("graphs/fixture_release_package.v1.5.0.json"), reverse=False)
RESOLVED = (
    IngestionService(default_config())
    .ingest(load_fixture("events/fixture_events.v1.json"), GRAPH)
    .resolved
)


def record(adr_id: str, status: str, scope: str) -> AdrRecord:
    return AdrRecord(adr_id=adr_id, title=adr_id, status=status, scope=scope)


def test_the_three_fixture_adrs_have_their_designed_weights() -> None:
    weights = {adr_id: adr_weight(rec) for adr_id, rec in INDEX.adrs.items()}

    assert weights == pytest.approx({"ADR-0001": 1.0, "ADR-0002": 0.14, "ADR-0003": 0.2})


@pytest.mark.parametrize(
    ("status", "scope", "weight"),
    [
        ("accepted", "system", 1.0),
        ("accepted", "module", 0.7),
        ("proposed", "component", 0.35),
        ("deprecated", "local", 0.08),
        ("rejected", "system", 0.0),
        ("unknown", "system", 0.0),
        ("accepted", "unspecified", 0.4),
    ],
)
def test_weight_table(status: str, scope: str, weight: float) -> None:
    assert adr_weight(record("A", status, scope)) == pytest.approx(weight)


def test_semantic_explicitness_scales_the_weight() -> None:
    # post-PP1 fallback: explicitness = similarity x 0.5
    assert adr_weight(record("A", "accepted", "system"), explicitness=0.8 * 0.5) == 0.4


def test_fixture_events_get_their_designed_av() -> None:
    got = {item.event.event_id: event_adr_weight(item.nodes, INDEX) for item in RESOLVED}

    assert set(got) == set(DESIGNED)
    for event_id, designed in DESIGNED.items():
        assert got[event_id].av == pytest.approx(designed["av"]), event_id
        assert got[event_id].adr_id == designed["adr_id"], event_id


def test_no_link_is_a_defined_zero() -> None:
    features = event_adr_weight(["common-lib"], INDEX)

    assert (features.av, features.adr_id, features.linked_adrs) == (0.0, None, [])


def test_the_most_serious_linked_adr_decides() -> None:
    index = AdrIndex(
        adrs={
            "ADR-1": record("ADR-1", "proposed", "local"),
            "ADR-2": record("ADR-2", "accepted", "system"),
        },
        links={"a": ["ADR-1"], "b": ["ADR-2"]},
    )

    features = event_adr_weight(["a", "b"], index)

    assert (features.av, features.adr_id) == (1.0, "ADR-2")
    assert features.linked_adrs == ["ADR-1", "ADR-2"]  # max, not 0.2 + 1.0


def test_ties_go_to_the_smallest_adr_id() -> None:
    index = AdrIndex(
        adrs={i: record(i, "accepted", "system") for i in ("ADR-2", "ADR-1")},
        links={"a": ["ADR-2", "ADR-1"]},
    )

    assert event_adr_weight(["a"], index).adr_id == "ADR-1"


def test_link_to_an_unknown_adr_is_logged_and_skipped() -> None:
    index = AdrIndex(adrs={}, links={"a": ["ADR-9"]})

    with capture_logs() as logs:
        features = event_adr_weight(["a"], index)

    assert features.av == 0.0
    assert [entry["reason"] for entry in logs] == ["adr_link_unknown"]


def test_context_records_activity_and_the_weight_table() -> None:
    active = adr_context(INDEX)

    assert active.active and active.inactive_reason is None
    assert (active.status_weights, active.scope_weights) == (STATUS_WEIGHTS, SCOPE_WEIGHTS)
    assert active.explicitness == 1.0


def test_no_index_or_empty_index_makes_av_inactive() -> None:
    with capture_logs() as logs:
        missing = adr_context(None)
        empty = adr_context(AdrIndex())

    assert (missing.active, missing.inactive_reason) == (False, "no_adr_index")
    assert (empty.active, empty.inactive_reason) == (False, "empty_adr_index")
    assert [entry["reason"] for entry in logs] == ["no_adr_index", "empty_adr_index"]


def test_service_with_and_without_an_index() -> None:
    service = FeatureExtractionService(default_config())

    off = service.extract(RESOLVED, GRAPH)
    on = service.extract(RESOLVED, GRAPH, adr_index=INDEX)

    assert not off.adr.active
    assert all(row.adr_violation is None for row in off.events)
    assert on.adr.active
    assert {row.event_id: row.adr_violation.av for row in on.events if row.adr_violation} == (
        pytest.approx({event_id: d["av"] for event_id, d in DESIGNED.items()})
    )


def test_no_events_still_reports_the_av_state() -> None:
    result = FeatureExtractionService(default_config()).extract([], GRAPH, adr_index=INDEX)

    assert result.adr.active
