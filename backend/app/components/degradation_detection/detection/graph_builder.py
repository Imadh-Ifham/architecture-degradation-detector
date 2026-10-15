"""M2 step 1: ``CanonicalRelease`` -> ``ArchGraph`` (pure).

M1 has already validated and normalised the release (no dangling edges, no self-loops, one
edge per ordered pair, every datastore access names an element), so the graph trusts it and only
sorts.
"""

import networkx as nx

from app.components.degradation_detection.detection.models import ArchGraph
from app.domain.canonical_release import CanonicalRelease


def build_graph(release: CanonicalRelease) -> ArchGraph:
    elements = {element.element_id: element for element in release.elements}
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(sorted(elements))
    for edge in sorted(release.dependencies, key=lambda e: (e.from_id, e.to_id)):
        graph.add_edge(edge.from_id, edge.to_id, types=edge.types, weight=edge.count)
    access = release.datastore_access
    if access is not None:
        access = tuple(sorted(access, key=lambda a: (a.datastore, a.element_id, a.mode or "")))
    return ArchGraph(release.release_id, graph, elements, access)
