"""M2 step 1: a CanonicalRelease becomes a read-only directed graph."""

import networkx as nx
import pytest

from app.components.degradation_detection.detection.graph_builder import build_graph
from tests.components.degradation_detection.detection.graphs import release


def test_one_node_per_element_including_isolated_ones() -> None:
    g = build_graph(release(["a", "b", "lonely"], [("a", "b")]))

    assert g.nodes == ("a", "b", "lonely")
    assert g.n == 3
    assert g.predecessors("lonely") == () and g.successors("lonely") == ()


def test_edges_carry_types_and_count_as_weight() -> None:
    g = build_graph(release(["a", "b"], [("a", "b")], counts={("a", "b"): 4}))

    assert g.edges == (("a", "b"),)
    assert g.nx.edges["a", "b"] == {"types": ("call",), "weight": 4}


def test_neighbours_are_distinct_and_sorted() -> None:
    g = build_graph(release(["hub", "z", "y", "x"], [("hub", "z"), ("hub", "y"), ("x", "hub")]))

    assert g.successors("hub") == ("y", "z")
    assert g.predecessors("hub") == ("x",)


def test_graph_does_not_depend_on_the_order_elements_and_edges_arrive_in() -> None:
    forward = build_graph(release(["a", "b", "c"], [("a", "b"), ("b", "c")]))
    backward = build_graph(release(["c", "b", "a"], [("b", "c"), ("a", "b")]))

    assert list(forward.nx.nodes) == list(backward.nx.nodes) == ["a", "b", "c"]
    assert list(forward.nx.edges) == list(backward.nx.edges)


def test_element_snapshot_is_reachable_from_the_graph() -> None:
    g = build_graph(release(["a"], sizes={"a": 120.0}))

    assert g.element("a").size == 120.0
    assert g.release_id == "v1.0.0"


def test_graph_is_read_only() -> None:
    g = build_graph(release(["a", "b"], [("a", "b")]))

    with pytest.raises(nx.NetworkXError):
        g.nx.add_edge("b", "a")


def test_datastore_access_is_carried_in_a_fixed_order() -> None:
    access = [("b", "z_db"), ("a", "z_db"), ("a", "a_db")]

    g = build_graph(release("ab", datastore_access=access))

    assert g.datastore_access is not None
    assert [(x.datastore, x.element_id) for x in g.datastore_access] == [
        ("a_db", "a"),
        ("z_db", "a"),
        ("z_db", "b"),
    ]


def test_missing_datastore_access_stays_missing() -> None:
    """None (C2 did not send it) is different from an empty list (C2 found none)."""
    assert build_graph(release("ab")).datastore_access is None
    assert build_graph(release("ab", datastore_access=[])).datastore_access == ()
