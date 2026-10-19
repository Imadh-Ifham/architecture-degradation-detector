# Tests for the ADR index parser (C4-T16, FR-06): MADR / Nygard status and scope, C2 links.

import pytest
from structlog.testing import capture_logs

from app.components.degradation_scoring.ingestion.adr import parse_adr, parse_index
from app.components.degradation_scoring.ingestion.errors import AdrIndexError
from app.components.degradation_scoring.ingestion.graph import build_graph
from app.components.degradation_scoring.ingestion.service import IngestionService
from tests.components.degradation_scoring.support import (
    adr_index_document,
    default_config,
    load_fixture,
)


def test_fixture_adrs_parse_to_their_designed_status_and_scope() -> None:
    index = parse_index(adr_index_document())

    assert {a.adr_id: (a.status, a.scope) for a in index.adrs.values()} == {
        "ADR-0001": ("accepted", "system"),
        "ADR-0002": ("superseded", "component"),
        "ADR-0003": ("proposed", "local"),
    }
    assert index.adrs["ADR-0001"].title == "ADR-0001: Modular core"


def test_links_are_c2_adr_refs_per_element() -> None:
    index = parse_index(adr_index_document())

    assert index.links == {
        "inventory-service": ["ADR-0001"],
        "notification-service": ["ADR-0003"],
        "reporting-service": ["ADR-0002"],
    }


def test_nygard_status_section() -> None:
    text = "# 5. Use a queue\n\nDate: 2025-01-01\n\n## Status\n\nAccepted\n\n## Context\n..."

    adr = parse_adr("ADR-0005", text)

    assert (adr.status, adr.scope, adr.title) == ("accepted", "unspecified", "5. Use a queue")


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        ("Accepted", "accepted"),
        ("Superseded by ADR-0009", "superseded"),
        ("deprecated", "deprecated"),
        ("Rejected", "rejected"),
        ('"proposed"', "proposed"),
    ],
)
def test_status_is_normalised(raw: str, status: str) -> None:
    assert parse_adr("A", f"---\nstatus: {raw}\n---\n# A\n").status == status


@pytest.mark.parametrize(
    ("raw", "scope"), [("System", "system"), ("module", "module"), ("team", "unspecified")]
)
def test_scope_is_normalised(raw: str, scope: str) -> None:
    assert parse_adr("A", f"---\nstatus: accepted\nscope: {raw}\n---\n").scope == scope


def test_unknown_or_missing_status_is_logged() -> None:
    with capture_logs() as logs:
        drafted = parse_adr("A", "---\nstatus: draft\n---\n# A\n")
        bare = parse_adr("B", "No front matter, no status section.")

    assert (drafted.status, bare.status, bare.title) == ("unknown", "unknown", "B")
    assert [entry["reason"] for entry in logs] == ["adr_status_unknown"] * 2


def test_links_are_deduplicated_and_sorted() -> None:
    index = parse_index({"adrs": [], "links": {"x": ["ADR-2", "ADR-1", "ADR-2"]}})

    assert index.links == {"x": ["ADR-1", "ADR-2"]}


@pytest.mark.parametrize(
    "document",
    [
        "not a mapping",
        {"links": {}},
        {"adrs": [{"id": "A"}]},
        {"adrs": [{"text": "t"}]},
        {"adrs": [{"id": "A", "text": "t"}, {"id": "A", "text": "t"}]},
        {"adrs": [], "links": ["A"]},
    ],
)
def test_unusable_index_stops_the_run(document: object) -> None:
    with pytest.raises(AdrIndexError):
        parse_index(document)


def test_ingestion_parses_the_index_only_when_given() -> None:
    graph = build_graph(load_fixture("graphs/fixture_release_package.v1.5.0.json"), reverse=False)
    payloads = load_fixture("events/fixture_events.v1.json")
    service = IngestionService(default_config())

    with_index = service.ingest(payloads, graph, adr_index_document())
    without = service.ingest(payloads, graph)

    assert with_index.adr_index is not None
    assert set(with_index.adr_index.adrs) == {"ADR-0001", "ADR-0002", "ADR-0003"}
    assert without.adr_index is None
