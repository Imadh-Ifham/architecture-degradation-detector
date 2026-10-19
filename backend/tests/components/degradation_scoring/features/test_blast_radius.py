# Tests for the blast-radius features (C4-T11, FR-04), hand-computed on small graphs.
# Edges mean "depends on" (C4-ADR-003); PageRank alpha = 0.85, so (1 - alpha) / n per node.

from collections.abc import Iterable
from typing import Any

import networkx as nx
import pytest

from app.components.degradation_scoring.features import blast_radius as br
from app.components.degradation_scoring.features.blast_radius import (
    CentralityCache,
    GraphCentralities,
    blast_radius,
    compute_centralities,
    node_depths,
)
from app.components.degradation_scoring.features.models import BlastRadiusFeatures
from app.components.degradation_scoring.ingestion.graph import build_graph
from tests.components.degradation_scoring.support import load_fixture

TOL = 1e-6


def graph(
    edges: Iterable[tuple[str, str]], weights: dict[tuple[str, str], int] | None = None
) -> "nx.DiGraph[str]":
    counts = weights or {}
    g: nx.DiGraph[str] = nx.DiGraph()
    for u, v in edges:
        g.add_edge(u, v, weight=counts.get((u, v), 1))
    return g


def centralities(g: "nx.DiGraph[str]", **overrides: int) -> GraphCentralities:
    params = {"exact_max_nodes": 5000, "sample_k": 500, "seed": 42} | overrides
    return compute_centralities(g, alpha=0.85, **params)


def features(g: "nx.DiGraph[str]", *nodes: str) -> BlastRadiusFeatures:
    return blast_radius(g, nodes, centralities(g))


# Star: four leaves l0..l3 depend on hub h. h is dangling, so its rank is spread over all 5:
# p_l = 0.03 + 0.17 p_h and p_h = 1 - 4 p_l  =>  p_h = 0.88 / 1.68 = 11/21, p_l = 5/42.
STAR = graph((f"l{i}", "h") for i in range(4))

# Chain a -> b -> c -> d: with x = p_a, p_b = 1.85x, p_c = 2.5725x, p_d = 3.186625x, sum 1.
CHAIN = graph([("a", "b"), ("b", "c"), ("c", "d")])
CHAIN_X = 1 / (1 + 1.85 + 2.5725 + 3.186625)

# Diamond a -> {b, c} -> d: p_b = p_c = 1.425x, p_d = 3.4225x with x = p_a.
DIAMOND = graph([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
DIAMOND_X = 1 / (1 + 2 * 1.425 + 3.4225)

# Cycle a -> b -> c -> a: symmetric, so PageRank 1/3 each; every node sits on exactly one
# ordered shortest path (b on a->c, ...), normalised by (n-1)(n-2) = 2.
CYCLE = graph([("a", "b"), ("b", "c"), ("c", "a")])


def test_star_hub() -> None:
    hub = features(STAR, "h")

    assert hub.fan_in_ratio == 1.0
    assert hub.pagerank == pytest.approx(11 / 21, abs=TOL)
    assert hub.betweenness == 0.0
    assert hub.depth == 1


def test_star_leaf() -> None:
    leaf = features(STAR, "l0")

    assert leaf.fan_in_ratio == 0.0
    assert leaf.pagerank == pytest.approx(5 / 42, abs=TOL)
    assert leaf.betweenness == 0.0
    assert leaf.depth == 0


def test_chain() -> None:
    c = features(CHAIN, "c")

    assert c.fan_in_ratio == pytest.approx(2 / 3, abs=TOL)
    assert c.pagerank == pytest.approx(2.5725 * CHAIN_X, abs=TOL)
    # c lies on a->d and b->d: 2 / ((4 - 1) * (4 - 2))
    assert c.betweenness == pytest.approx(2 / 6, abs=TOL)
    assert c.depth == 2


def test_chain_pagerank_values() -> None:
    pr = centralities(CHAIN).pagerank

    for node, share in zip("abcd", [1, 1.85, 2.5725, 3.186625], strict=True):
        assert pr[node] == pytest.approx(share * CHAIN_X, abs=TOL)


def test_diamond_sink() -> None:
    d = features(DIAMOND, "d")

    assert d.fan_in_ratio == 1.0
    assert d.pagerank == pytest.approx(3.4225 * DIAMOND_X, abs=TOL)
    assert d.betweenness == 0.0
    assert d.depth == 2


def test_diamond_two_elements_sum_pagerank_and_take_max_of_the_rest() -> None:
    middle = features(DIAMOND, "b", "c")

    # only a depends on b or c, out of n - |S| = 2 other nodes
    assert middle.fan_in_ratio == pytest.approx(1 / 2, abs=TOL)
    assert middle.pagerank == pytest.approx(2 * 1.425 * DIAMOND_X, abs=TOL)
    # b carries one of the two shortest a->d paths: 0.5 / 6
    assert middle.betweenness == pytest.approx(0.5 / 6, abs=TOL)
    assert middle.depth == 1


def test_cycle() -> None:
    a = features(CYCLE, "a")

    assert a.fan_in_ratio == 1.0
    assert a.pagerank == pytest.approx(1 / 3, abs=TOL)
    assert a.betweenness == pytest.approx(1 / 2, abs=TOL)
    # no node has in-degree 0; on the condensation the whole cycle is the root
    assert a.depth == 0


def test_pagerank_uses_dependency_counts() -> None:
    # a -> b counts 3, a -> c counts 1: p_b = x + 0.85 * 0.75x, p_c = x + 0.85 * 0.25x
    pr = centralities(graph(DIAMOND.edges, weights={("a", "b"): 3})).pagerank

    assert pr["b"] == pytest.approx(1.6375 * DIAMOND_X, abs=TOL)
    assert pr["c"] == pytest.approx(1.2125 * DIAMOND_X, abs=TOL)


def test_cycle_members_share_the_depth_of_their_cycle() -> None:
    # r -> a -> b -> c -> a: on the raw graph a, b, c would be 1, 2, 3 deep (C4-ADR-008)
    depths = node_depths(graph([("r", "a"), ("a", "b"), ("b", "c"), ("c", "a")]))

    assert depths == {"r": 0, "a": 1, "b": 1, "c": 1}


def test_depth_is_the_longest_of_the_shortest_root_paths() -> None:
    # root r1 reaches t in 1 step, root r2 needs 3: depth = max over roots of the shortest
    g = graph([("r1", "t"), ("r2", "x"), ("x", "y"), ("y", "t")])

    assert node_depths(g)["t"] == 3


def test_isolated_node_and_empty_graph() -> None:
    g = graph([("a", "b")])
    g.add_node("lonely")

    lonely = features(g, "lonely")

    # b and lonely are both dangling: p_lonely = p_a = y = 0.05 + 0.85 (1 - y) / 3 = 20/77
    assert lonely.pagerank == pytest.approx(20 / 77, abs=TOL)
    assert (lonely.fan_in_ratio, lonely.betweenness, lonely.depth) == (0.0, 0.0, 0)
    assert node_depths(nx.DiGraph()) == {}


def test_whole_graph_as_the_event_does_not_divide_by_zero() -> None:
    assert features(CYCLE, "a", "b", "c").fan_in_ratio == 0.0


# Fixture graph: 22 services, the 4-service cycle, hub common-lib, bridge integration-hub.
FIXTURE = load_fixture("fixture_expected.json")["graph"]


@pytest.fixture(scope="module")
def fixture_graph() -> "nx.DiGraph[str]":
    return build_graph(load_fixture("graphs/fixture_release_package.v1.5.0.json"), reverse=False)


def test_fixture_hub_is_depended_on_by_all_but_the_two_adapters(
    fixture_graph: "nx.DiGraph[str]",
) -> None:
    c = centralities(fixture_graph)
    hub = blast_radius(fixture_graph, [FIXTURE["hub"]], c)

    # every service except email-adapter and sms-adapter reaches common-lib: 19 of 21
    assert hub.fan_in_ratio == pytest.approx(19 / 21, abs=TOL)
    assert max(c.pagerank, key=c.pagerank.__getitem__) == FIXTURE["hub"]


def test_fixture_bridge_carries_every_back_office_path(fixture_graph: "nx.DiGraph[str]") -> None:
    c = centralities(fixture_graph)
    bridge = blast_radius(fixture_graph, [FIXTURE["bridge"]], c)
    reached = nx.descendants(fixture_graph, FIXTURE["bridge"])

    # only the 3 back-office services depend on it (admin-ui, analytics, reporting), and it is
    # their only route to the core: every (back office, reached) pair runs through it, / 21*20
    assert bridge.fan_in_ratio == pytest.approx(3 / 21, abs=TOL)
    assert bridge.betweenness == pytest.approx(3 * len(reached) / (21 * 20), abs=TOL)


def test_fixture_cycle_event(fixture_graph: "nx.DiGraph[str]") -> None:
    c = centralities(fixture_graph)
    cycle = blast_radius(fixture_graph, FIXTURE["cycle"], c)

    # gateway, integration-hub, the 3 back-office services and the 2 front ends: 7 of 18
    assert cycle.fan_in_ratio == pytest.approx(7 / 18, abs=TOL)
    assert {c.depth[node] for node in FIXTURE["cycle"]} == {cycle.depth}
    assert cycle.pagerank == pytest.approx(sum(c.pagerank[n] for n in FIXTURE["cycle"]))


def test_pagerank_sums_to_one_on_the_fixture(fixture_graph: "nx.DiGraph[str]") -> None:
    assert sum(centralities(fixture_graph).pagerank.values()) == pytest.approx(1.0, abs=TOL)


# Sampling path: above exact_max_nodes, betweenness uses k pivots chosen with the seed.
RANDOM = nx.gnp_random_graph(200, 0.03, seed=7, directed=True)
LARGE: "nx.DiGraph[str]" = nx.DiGraph()
LARGE.add_nodes_from(str(node) for node in RANDOM)
LARGE.add_edges_from((str(u), str(v)) for u, v in RANDOM.edges)


def test_large_graph_uses_seeded_sampling() -> None:
    sampled = centralities(LARGE, exact_max_nodes=100, sample_k=20)
    exact = centralities(LARGE)

    assert sampled.betweenness_sampled
    assert not exact.betweenness_sampled
    assert sampled.betweenness == nx.betweenness_centrality(LARGE, k=20, normalized=True, seed=42)
    assert sampled.betweenness != exact.betweenness
    assert blast_radius(LARGE, ["0"], sampled).betweenness_sampled


def test_sampling_is_deterministic() -> None:
    first = centralities(LARGE, exact_max_nodes=100, sample_k=20)
    second = centralities(LARGE, exact_max_nodes=100, sample_k=20)

    assert first == second


def test_graph_at_the_threshold_is_exact() -> None:
    assert not centralities(LARGE, exact_max_nodes=200, sample_k=20).betweenness_sampled


def test_sample_size_is_capped_at_the_node_count() -> None:
    # k = 500 > n = 200: every node is a pivot, which is the exact computation
    capped = centralities(LARGE, exact_max_nodes=100, sample_k=500)

    assert capped.betweenness_sampled
    assert capped.betweenness == pytest.approx(centralities(LARGE).betweenness, abs=1e-12)


def test_cache_computes_once_per_system_and_release(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = br.compute_centralities

    def counting(g: "nx.DiGraph[str]", **kwargs: Any) -> GraphCentralities:
        calls.append(g.number_of_nodes())
        return real(g, **kwargs)

    monkeypatch.setattr(br, "compute_centralities", counting)
    cache = CentralityCache(alpha=0.85, exact_max_nodes=5000, sample_k=500, seed=42)

    first = cache.get(("shop", "v1"), CHAIN)
    again = cache.get(("shop", "v1"), CHAIN)
    other = cache.get(("shop", "v2"), STAR)

    assert first is again
    assert other.pagerank.keys() == set(STAR)
    assert calls == [4, 5]
