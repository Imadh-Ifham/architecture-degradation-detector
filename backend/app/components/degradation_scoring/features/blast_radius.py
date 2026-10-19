# Blast radius: how much of the system an event's elements can affect.
# Depth is always measured on the condensation, i.e. with cycles collapsed (C4-ADR-008).

from collections.abc import Collection
from dataclasses import dataclass

import networkx as nx

from app.components.degradation_scoring.features.models import BlastRadiusFeatures

# PageRank is iterative: stop when the per-node change is below 1e-10 (networkx default 1e-6),
# with room for the extra iterations that needs
PAGERANK_TOL = 1e-10
PAGERANK_MAX_ITER = 1000


@dataclass(frozen=True)
class GraphCentralities:
    # graph-wide values computed once per (system, release)

    pagerank: dict[str, float]
    betweenness: dict[str, float]
    depth: dict[str, int]
    betweenness_sampled: bool


def compute_centralities(
    graph: "nx.DiGraph[str]",
    *,
    alpha: float,
    exact_max_nodes: int,
    sample_k: int,
    seed: int,
) -> GraphCentralities:
    # PageRank weighted by dependency count; betweenness exact up to exact_max_nodes nodes,
    # above that estimated from sample_k pivots chosen with a fixed seed.
    n = graph.number_of_nodes()
    sampled = n > exact_max_nodes
    if sampled:
        betweenness = nx.betweenness_centrality(
            graph, k=min(sample_k, n), normalized=True, weight=None, seed=seed
        )
    else:
        betweenness = nx.betweenness_centrality(graph, normalized=True, weight=None)
    return GraphCentralities(
        pagerank=nx.pagerank(
            graph, alpha=alpha, weight="weight", tol=PAGERANK_TOL, max_iter=PAGERANK_MAX_ITER
        ),
        betweenness=betweenness,
        depth=node_depths(graph),
        betweenness_sampled=sampled,
    )


def node_depths(graph: "nx.DiGraph[str]") -> dict[str, int]:
    # depth of a node = longest of the shortest paths from any root to it, measured on the
    # condensation (each cycle is one node, so roots always exist and members share a depth)
    condensed = nx.condensation(graph)
    deepest: dict[int, int] = {}
    for root in (c for c in condensed if condensed.in_degree(c) == 0):
        for component, distance in nx.single_source_shortest_path_length(condensed, root).items():
            deepest[component] = max(deepest.get(component, 0), distance)
    mapping: dict[str, int] = condensed.graph["mapping"]
    return {node: deepest[component] for node, component in mapping.items()}


def blast_radius(
    graph: "nx.DiGraph[str]", nodes: Collection[str], centralities: GraphCentralities
) -> BlastRadiusFeatures:
    # fan_in_ratio = |ancestors(S) \ S| / max(n - |S|, 1); pagerank = sum; betweenness and
    # depth = max over S. A -> B means A depends on B, so dependents are ancestors (ADR-003).
    members = set(nodes)
    dependents: set[str] = set()
    for node in members:
        dependents |= nx.ancestors(graph, node)
    dependents -= members
    return BlastRadiusFeatures(
        fan_in_ratio=len(dependents) / max(graph.number_of_nodes() - len(members), 1),
        pagerank=sum(centralities.pagerank[node] for node in members),
        betweenness=max(centralities.betweenness[node] for node in members),
        depth=max(centralities.depth[node] for node in members),
        betweenness_sampled=centralities.betweenness_sampled,
    )


class CentralityCache:
    # memoises GraphCentralities per (system, release) for the life of this object

    def __init__(self, *, alpha: float, exact_max_nodes: int, sample_k: int, seed: int) -> None:
        self._alpha = alpha
        self._exact_max_nodes = exact_max_nodes
        self._sample_k = sample_k
        self._seed = seed
        self._cache: dict[tuple[str, str], GraphCentralities] = {}

    def get(self, key: tuple[str, str], graph: "nx.DiGraph[str]") -> GraphCentralities:
        if key not in self._cache:
            self._cache[key] = compute_centralities(
                graph,
                alpha=self._alpha,
                exact_max_nodes=self._exact_max_nodes,
                sample_k=self._sample_k,
                seed=self._seed,
            )
        return self._cache[key]
