# Tests for element resolution (C4-T10, FR-03).

import copy
from typing import Any

import networkx as nx
import pytest
from structlog.testing import capture_logs

from app.components.degradation_scoring.ingestion.events import ingest_events
from app.components.degradation_scoring.ingestion.graph import build_graph
from app.components.degradation_scoring.ingestion.resolution import resolve_events
from app.domain.degradation_event import DegradationEventV2
from app.domain.severity_report import QuarantineReason, ResolutionStatus
from tests.components.degradation_scoring.support import load_fixture

PAYLOADS: list[dict[str, Any]] = load_fixture("events/fixture_events.v1.json")
EXPECTED: dict[str, Any] = load_fixture("fixture_expected.json")
GRAPH = build_graph(load_fixture("graphs/fixture_release_package.v1.5.0.json"), reverse=False)
ELIGIBLE = ingest_events(PAYLOADS, rank_only_confirmed=False).eligible


def element_event(name: str) -> DegradationEventV2:
    payload = copy.deepcopy(PAYLOADS[2])  # fixture E03, an ELEMENT event
    payload["element_id"] = name
    return DegradationEventV2.model_validate(payload)


def instance_event(members: list[str]) -> DegradationEventV2:
    payload = copy.deepcopy(PAYLOADS[0])  # fixture E01, an INSTANCE event
    payload["members"] = members
    return DegradationEventV2.model_validate(payload)


def resolve(*events: DegradationEventV2, graph: "nx.DiGraph[str]" = GRAPH) -> Any:
    return resolve_events(list(events), graph, prefix_confidence=0.7)


def test_fixture_split_and_rate_match_the_design() -> None:
    resolved, quarantined, rate = resolve(*ELIGIBLE)
    designed = {
        row["event_id"]: row["resolution"] for row in EXPECTED["events"] if row["resolution"]
    }
    got = {r.event.event_id: str(r.resolution.status) for r in resolved}
    got |= {q.event_id: "unresolved" for q in quarantined if q.event_id}

    assert got == designed
    assert rate == EXPECTED["counts"]["resolution_rate"]


def test_instance_members_map_to_their_nodes() -> None:
    resolved, _, _ = resolve(*ELIGIBLE)
    cycle = next(r for r in resolved if r.event.event_id == "DEG-C4FX-R02-0001")

    assert cycle.nodes == sorted(EXPECTED["graph"]["cycle"])
    assert cycle.resolution.confidence == 1.0


def test_old_name_resolves_through_the_alias() -> None:
    resolved, _, _ = resolve(instance_event(["order-svc", "inventory-service"]))

    assert resolved[0].nodes == ["inventory-service", "order-service"]
    assert resolved[0].resolution.status is ResolutionStatus.EXACT


def test_module_path_resolves_by_prefix_with_the_configured_confidence() -> None:
    resolved, _, _ = resolve_events(
        [element_event("src/services/notification")], GRAPH, prefix_confidence=0.5
    )

    assert resolved[0].nodes == ["notification-service"]
    assert resolved[0].resolution.status is ResolutionStatus.PREFIX_FALLBACK
    assert resolved[0].resolution.confidence == 0.5


def test_one_prefix_member_makes_the_whole_event_a_fallback() -> None:
    resolved, _, _ = resolve(instance_event(["order-service", "src/services/payment"]))

    assert resolved[0].nodes == ["order-service", "payment-service"]
    assert resolved[0].resolution.status is ResolutionStatus.PREFIX_FALLBACK
    assert resolved[0].resolution.confidence == 0.7


@pytest.mark.parametrize("name", ["src/services/notification/", "src/services/notification"])
def test_trailing_slash_does_not_matter(name: str) -> None:
    resolved, _, _ = resolve(element_event(name))

    assert resolved[0].nodes == ["notification-service"]


def test_prefix_only_matches_whole_folders() -> None:
    _, quarantined, _ = resolve(element_event("src/services/notif"))

    assert quarantined[0].detail == "missing: src/services/notif"


def test_folder_pattern_paths_resolve_by_folder_name() -> None:
    # source_paths may be folder patterns, not only exact files (owner, before T13)
    g: nx.DiGraph[str] = nx.DiGraph()
    g.add_node("checkoutservice", source_paths=["src/checkoutservice/**"], aliases=[])

    resolved, _, _ = resolve(element_event("src/checkoutservice"), graph=g)

    assert resolved[0].nodes == ["checkoutservice"]
    assert resolved[0].resolution.status is ResolutionStatus.PREFIX_FALLBACK


def test_prefix_matching_several_nodes_is_ambiguous() -> None:
    _, quarantined, rate = resolve(element_event("src/services"))

    assert quarantined[0].reason is QuarantineReason.UNRESOLVED_ELEMENT
    assert quarantined[0].detail.startswith("ambiguous: src/services (matches ")
    assert rate == 0.0


def test_one_missing_member_quarantines_the_whole_instance() -> None:
    event = instance_event(["order-service", "payment-service", "ghost-a", "ghost-b"])

    resolved, quarantined, _ = resolve(event)

    assert resolved == []
    assert quarantined[0].event_id == event.event_id
    assert quarantined[0].detail == "missing: ghost-a; missing: ghost-b"


def test_graph_without_alias_or_path_attributes_still_resolves_ids() -> None:
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_edge("order-service", "payment-service")

    resolved, quarantined, _ = resolve(
        element_event("order-service"), element_event("src/x"), graph=graph
    )

    assert [r.nodes for r in resolved] == [["order-service"]]
    assert quarantined[0].detail == "missing: src/x"


def test_nothing_to_resolve_gives_rate_1() -> None:
    assert resolve() == ([], [], 1.0)


def test_unresolved_events_are_logged_with_the_reason() -> None:
    with capture_logs() as logs:
        resolve(element_event("legacy-billing"))

    assert [(e["event"], e["reason"]) for e in logs] == [
        ("event_quarantined", "unresolved_element")
    ]
