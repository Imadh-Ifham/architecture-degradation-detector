# Turns a graph document into a directed graph where "A -> B" means A depends on B
# and loads each (system, release) only once per run.

from collections.abc import Mapping
from typing import Any

import networkx as nx
import structlog
from pydantic import ValidationError

from app.components.degradation_scoring.ingestion.errors import GraphLoadError
from app.components.degradation_scoring.ports import ArchitectureGraphSource
from app.domain.release_package import ReleasePackageV1

log = structlog.get_logger(__name__)

NODE_LINK_EDGE_KEY = "links"


def build_graph(document: object, *, reverse: bool) -> "nx.DiGraph[str]":
    # A dict with "elements" is C3's release package, a dict with "nodes" is node-link JSON
    # (test graphs), a string is GraphML. reverse=True flips every edge.
    if isinstance(document, Mapping) and "elements" in document:
        graph = _from_release_package(document)
    elif isinstance(document, Mapping) and "nodes" in document:
        graph = _from_node_link(document)
    elif isinstance(document, str):
        graph = _from_graphml(document)
    else:
        raise GraphLoadError(f"unrecognised graph document: {type(document).__name__}")
    return graph.reverse(copy=True) if reverse else graph


def _from_release_package(document: Mapping[str, Any]) -> "nx.DiGraph[str]":
    try:
        package = ReleasePackageV1.model_validate(document)
    except ValidationError as exc:
        raise GraphLoadError(f"invalid release package: {exc}") from exc

    graph: nx.DiGraph[str] = nx.DiGraph(system_id=package.system_id, release_id=package.release_id)
    for element in package.elements:
        graph.add_node(
            element.id,
            name=element.name or element.id,
            kind=element.kind,
            size=element.size,
            aliases=list(element.aliases),
            source_paths=list(element.extra.get("source_paths", [])),
        )
    # Same normalisation as C3: duplicate edges collapse (counts summed), self-loops dropped.
    for dep in package.dependencies:
        if dep.from_ == dep.to:
            log.info("self_loop_dropped", reason="self_loop_dropped", element=dep.from_)
            continue
        if graph.has_edge(dep.from_, dep.to):
            graph[dep.from_][dep.to]["weight"] += dep.count
        else:
            graph.add_edge(dep.from_, dep.to, weight=dep.count)
    return graph


def _from_node_link(document: Mapping[str, Any]) -> "nx.DiGraph[str]":
    # Edges must be under "links": a document using "edges" would otherwise load with no
    # edges at all, silently (networkx changed its default; see validated_architecture.py).
    if NODE_LINK_EDGE_KEY not in document:
        raise GraphLoadError(f"node-link document has no '{NODE_LINK_EDGE_KEY}' key")
    loaded = nx.node_link_graph(dict(document), directed=True, multigraph=False, edges="links")
    return _with_default_weights(nx.DiGraph(loaded))


def _from_graphml(text: str) -> "nx.DiGraph[str]":
    try:
        loaded = nx.parse_graphml(text)
    except Exception as exc:  # networkx raises several unrelated types for bad XML
        raise GraphLoadError(f"invalid GraphML: {exc}") from exc
    if not loaded.is_directed():
        raise GraphLoadError("GraphML graph is undirected; dependencies need a direction")
    return _with_default_weights(nx.DiGraph(loaded))


def _with_default_weights(graph: "nx.DiGraph[str]") -> "nx.DiGraph[str]":
    for _, _, data in graph.edges(data=True):
        data.setdefault("weight", 1)
    return graph


class GraphLoader:
    # Builds each (system, release) graph once and keeps it for the rest of the run.

    def __init__(self, source: ArchitectureGraphSource, *, reverse: bool) -> None:
        self._source = source
        self._reverse = reverse
        self._graphs: dict[tuple[str, str], nx.DiGraph[str]] = {}

    def load(self, system_id: str, release_id: str) -> "nx.DiGraph[str]":
        key = (system_id, release_id)
        if key not in self._graphs:
            document = self._source.fetch(system_id, release_id)
            self._graphs[key] = build_graph(document, reverse=self._reverse)
        return self._graphs[key]
