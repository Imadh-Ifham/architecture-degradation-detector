# Features: computes the severity criteria of each resolved event.
# Blast radius so far (T11); hotspot, ADR weight and persistence join in T13-T16.

from collections.abc import Sequence

import networkx as nx

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.features.blast_radius import CentralityCache, blast_radius
from app.components.degradation_scoring.features.models import EventFeatures
from app.components.degradation_scoring.models import ResolvedEvent


class FeatureExtractionService:
    # Turns resolved events plus their release graph into raw features, in input order.

    def __init__(self, config: C4Config) -> None:
        self._centralities = CentralityCache(
            alpha=config.pagerank_alpha,
            exact_max_nodes=config.betweenness_exact_max_nodes,
            sample_k=config.betweenness_sample_k,
            seed=config.seed,
        )

    def extract(
        self, events: Sequence[ResolvedEvent], graph: "nx.DiGraph[str]"
    ) -> list[EventFeatures]:
        # one call = one (system, release) and the graph of that release
        if not events:
            return []
        keys = {(item.event.system_id, item.event.window.end_release) for item in events}
        if len(keys) > 1:
            raise ValueError(f"events span several (system, release) pairs: {sorted(keys)}")
        centralities = self._centralities.get(keys.pop(), graph)
        return [
            EventFeatures(
                event_id=item.event.event_id,
                blast_radius=blast_radius(graph, item.nodes, centralities),
            )
            for item in events
        ]
