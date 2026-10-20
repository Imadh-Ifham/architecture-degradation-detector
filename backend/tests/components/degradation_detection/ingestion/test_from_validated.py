"""C2's published graph -> release package: what is carried, what is refused, and that the result
goes through M1 like any package."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.ingestion import IngestService
from app.components.degradation_detection.ingestion.from_validated import (
    GRAPH_UNREADABLE,
    RELEASE_UNDATED,
    UnconvertibleGraph,
    package_from_validated,
)
from app.components.degradation_detection.ingestion.models import IngestStatus, RawPackage
from app.domain.canonical_release import GateStatus
from app.domain.release_package import ReleasePackageV1
from tests.components.degradation_detection.fakes import FixedClock, InMemoryReleaseRepository

GOLDEN = Path(__file__).resolve().parents[3] / "fixtures" / "validation"
GOLDEN_GRAPH = GOLDEN / "validated_v0.9.0.graph.json"


def published(**graph: Any) -> dict[str, Any]:
    """A small C2 document: two services, a cache, one confirmed and one contradicted edge."""
    return {
        "directed": True,
        "multigraph": False,
        "graph": {
            "schema_version": "1.1.0",
            "repository_id": "shop-1",
            "release_id": "v1.0.0",
            "released_at": "2025-01-01T00:00:00+00:00",
            "c1_model_ref": "abc123",
            "architecture_style": "microservices",
            "validation_confidence": 0.8,
            "run": {"run_id": "c2-run-1"},
        }
        | graph,
        "nodes": [
            {"id": "a", "name": "cart", "canonical": "cart", "kind": "module", "size": 4.0},
            {"id": "b", "name": "checkout", "canonical": "checkout", "kind": "module"},
            {"id": "redis", "name": "redis-cart", "kind": "datastore"},
        ],
        "links": [
            {
                "source": "b",
                "target": "a",
                "relationship": "communicates-with",
                "bucket": "confirmed",
                "attributes": {"observed_as": "grpc"},
            },
            {
                "source": "a",
                "target": "b",
                "relationship": "depends-on",
                "bucket": "contradicted",
                "attributes": {},
            },
            {"source": "a", "target": "redis", "relationship": "depends-on", "bucket": "uncovered"},
        ],
    }


def test_golden_c2_document_becomes_a_valid_package() -> None:
    document = json.loads(GOLDEN_GRAPH.read_text(encoding="utf-8"))

    package = ReleasePackageV1.model_validate(package_from_validated(document))

    assert (package.system_id, package.release_id) == ("online-boutique", "v0.9.0")
    assert package.validation_confidence == document["graph"]["validation_confidence"]
    assert {e.id for e in package.elements} == {n["id"] for n in document["nodes"]}
    assert [(d.from_, d.to) for d in package.dependencies] == [
        (link["source"], link["target"]) for link in document["links"]
    ]


def test_every_edge_is_kept_whatever_its_verdict() -> None:
    package = ReleasePackageV1.model_validate(package_from_validated(published()))

    assert sorted((d.from_, d.to) for d in package.dependencies) == [("a", "b"), ("b", "a")]
    assert {(d.from_, tuple(d.types)) for d in package.dependencies} == {
        ("b", ("grpc",)),
        ("a", ("depends-on",)),
    }


def test_datastores_become_access_rows_not_elements() -> None:
    package = ReleasePackageV1.model_validate(package_from_validated(published()))

    assert [e.id for e in package.elements] == ["a", "b"]
    assert package.datastore_access is not None
    assert [(x.element, x.datastore) for x in package.datastore_access] == [("a", "redis-cart")]


def test_identity_style_and_provenance_are_carried() -> None:
    package = ReleasePackageV1.model_validate(package_from_validated(published()))

    assert package.architecture_style.value == "microservices"
    assert package.provenance.c1_model_ref == "abc123"
    assert package.provenance.c2_validation_ref == "c2-run-1"
    assert package.elements[0].extra == {"canonical": "cart"}


@pytest.mark.parametrize(
    ("style", "expected"),
    [("event_driven", "event-driven"), ("unknown", "generic"), ("", "generic"), (None, "generic")],
)
def test_style_names_map_or_fall_back_to_generic(style: str | None, expected: str) -> None:
    payload = package_from_validated(published(architecture_style=style))

    assert payload["architecture_style"] == expected


def test_a_release_without_a_date_is_refused_not_dated() -> None:
    with pytest.raises(UnconvertibleGraph) as refused:
        package_from_validated(published(released_at=None))

    assert refused.value.reason == RELEASE_UNDATED


def test_a_document_that_is_not_node_link_is_refused() -> None:
    with pytest.raises(UnconvertibleGraph) as refused:
        package_from_validated({"elements": []})

    assert refused.value.reason == GRAPH_UNREADABLE


def _raw(document: dict[str, Any]) -> RawPackage:
    return RawPackage(source="g", data=json.dumps(package_from_validated(document)).encode())


def test_a_release_validated_again_replaces_the_stored_one_only_when_asked() -> None:
    repo = InMemoryReleaseRepository()
    ingest = IngestService(repo, FixedClock(), C3Config())
    first = published()
    again = copy.deepcopy(first)
    again["graph"]["validation_confidence"] = 0.55
    again["graph"]["run"]["run_id"] = "c2-run-2"

    [stored] = ingest.ingest([_raw(first)]).outcomes
    [strict] = ingest.ingest([_raw(again)]).outcomes
    [replaced] = ingest.ingest([_raw(again)], replace_changed=True).outcomes
    [unchanged] = ingest.ingest([_raw(again)], replace_changed=True).outcomes

    assert stored.status is IngestStatus.STORED
    assert strict.status is IngestStatus.REJECTED
    assert replaced.status is IngestStatus.REPLACED
    assert replaced.gate_status is GateStatus.DOWNWEIGHTED
    assert unchanged.status is IngestStatus.UNCHANGED
    [release] = repo.list_releases("shop-1")
    assert release.c2_validation_ref == "c2-run-2"
