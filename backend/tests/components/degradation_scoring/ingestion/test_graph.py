# Tests for the graph loader (C4-T09, FR-02).

import copy
from typing import Any

import networkx as nx
import pytest

from app.components.degradation_scoring.ingestion.errors import GraphLoadError
from app.components.degradation_scoring.ingestion.graph import GraphLoader, build_graph
from tests.components.degradation_scoring.support import FakeGraphSource, load_fixture

PACKAGE: dict[str, Any] = load_fixture("graphs/fixture_release_package.v1.5.0.json")
EXPECTED: dict[str, Any] = load_fixture("fixture_expected.json")


def chain() -> "nx.DiGraph[str]":
    # a depends on b, b depends on c.
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_edge("a", "b", weight=2)
    graph.add_edge("b", "c", weight=1)
    return graph


def package_with(dependencies: list[dict[str, Any]]) -> dict[str, Any]:
    package = copy.deepcopy(PACKAGE)
    package["dependencies"] = dependencies
    return package


# --- release package ----------------------------------------------------------------------


def test_fixture_package_becomes_the_designed_graph() -> None:
    graph = build_graph(PACKAGE, reverse=False)
    design = EXPECTED["graph"]

    assert graph.number_of_nodes() == design["elements"]
    assert graph.number_of_edges() == len(PACKAGE["dependencies"])
    assert graph.in_degree(design["hub"]) == design["hub_dependents"]
    assert [sorted(c) for c in nx.simple_cycles(graph)] == [sorted(design["cycle"])]
    assert graph.graph == {"system_id": "c4-fixture-shop", "release_id": "v1.5.0"}


def test_nodes_keep_the_attributes_later_steps_need() -> None:
    graph = build_graph(PACKAGE, reverse=False)

    assert graph.nodes["order-service"]["aliases"] == ["order-svc"]
    assert graph.nodes["order-service"]["size"] == 12450
    assert graph.nodes["notification-service"]["source_paths"][0].startswith(
        "src/services/notification/"
    )
    assert graph.nodes["admin-ui"]["source_paths"] == []


def test_edge_weight_is_the_dependency_count() -> None:
    graph = build_graph(PACKAGE, reverse=False)

    assert graph["order-service"]["payment-service"]["weight"] == 4
    assert graph["cart-service"]["catalog-service"]["weight"] == 1


def test_dependents_are_ancestors() -> None:
    # "A -> B" means A depends on B, so whatever depends on X (directly or not) is an ancestor.
    graph = build_graph(PACKAGE, reverse=False)

    assert nx.ancestors(graph, "email-adapter") >= {"notification-service", "payment-service"}
    assert "email-adapter" not in nx.ancestors(graph, "notification-service")
    assert nx.ancestors(graph, "admin-ui") == set()  # nothing depends on the UI


def test_duplicate_edges_collapse_and_self_loops_are_dropped() -> None:
    call = {"types": ["call"]}
    package = package_with(
        [
            {"from": "cart-service", "to": "user-service", "count": 2, **call},
            {"from": "cart-service", "to": "user-service", "count": 3, **call},
            {"from": "user-service", "to": "user-service", "count": 1, **call},
        ]
    )

    graph = build_graph(package, reverse=False)

    assert list(graph.edges(data="weight")) == [("cart-service", "user-service", 5)]


def test_invalid_release_package_stops_the_run() -> None:
    package = package_with([{"from": "cart-service", "to": "ghost-service", "count": 1}])

    with pytest.raises(GraphLoadError, match="invalid release package"):
        build_graph(package, reverse=False)


# --- direction flag -----------------------------------------------------------------------


def test_reverse_flag_flips_every_edge() -> None:
    reversed_graph = build_graph(nx.node_link_data(chain(), edges="links"), reverse=True)

    assert sorted(reversed_graph.edges) == [("b", "a"), ("c", "b")]
    assert nx.ancestors(reversed_graph, "a") == {"b", "c"}


# --- test-graph formats -------------------------------------------------------------------


def test_node_link_round_trip_keeps_nodes_edges_and_weights() -> None:
    graph = build_graph(nx.node_link_data(chain(), edges="links"), reverse=False)

    assert sorted(graph.edges(data="weight")) == [("a", "b", 2), ("b", "c", 1)]


def test_node_link_without_links_key_is_refused() -> None:
    document = nx.node_link_data(chain(), edges="edges")

    with pytest.raises(GraphLoadError, match="'links'"):
        build_graph(document, reverse=False)


def test_node_link_edges_get_weight_1_by_default() -> None:
    document = {"directed": True, "nodes": [{"id": "a"}, {"id": "b"}],
                "links": [{"source": "a", "target": "b"}]}  # fmt: skip

    assert build_graph(document, reverse=False)["a"]["b"]["weight"] == 1


def test_graphml_round_trip() -> None:
    text = "\n".join(nx.generate_graphml(chain()))

    graph = build_graph(text, reverse=False)

    assert sorted(graph.edges(data="weight")) == [("a", "b", 2), ("b", "c", 1)]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("\n".join(nx.generate_graphml(nx.path_graph(3))), "undirected"),
        ("<not graphml", "invalid GraphML"),
        (42, "unrecognised"),
        ({"neither": "nodes nor elements"}, "unrecognised"),
    ],
    ids=["undirected_graphml", "broken_xml", "number", "unknown_dict"],
)
def test_unusable_documents_stop_the_run(document: object, message: str) -> None:
    with pytest.raises(GraphLoadError, match=message):
        build_graph(document, reverse=False)


# --- memoisation --------------------------------------------------------------------------


def test_second_load_of_a_release_is_served_from_memory() -> None:
    source = FakeGraphSource({"v1.5.0": PACKAGE, "v1.4.0": PACKAGE})
    loader = GraphLoader(source, reverse=False)

    first = loader.load("c4-fixture-shop", "v1.5.0")
    second = loader.load("c4-fixture-shop", "v1.5.0")
    loader.load("c4-fixture-shop", "v1.4.0")

    assert second is first
    assert source.requests == [("c4-fixture-shop", "v1.5.0"), ("c4-fixture-shop", "v1.4.0")]


def test_loader_applies_the_direction_flag() -> None:
    source = FakeGraphSource({"r1": nx.node_link_data(chain(), edges="links")})

    graph = GraphLoader(source, reverse=True).load("s", "r1")

    assert graph.has_edge("b", "a")
